"""ClienteOttima: login, bearer automático, re-login único em 401 (nunca loop), e ErroOttima
com o `detail` do backend verbatim. Sem rede — tudo via `httpx.MockTransport`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from ottima_mcp.cliente import ClienteOttima, ErroOttima
from ottima_mcp.config import Config

_CONFIG = Config(url="http://ottima.local", username="agente", password="segredo")

_USER_OUT: dict[str, Any] = {
    "id": 7,
    "username": "agente",
    "name": "Agente MCP",
    "role": "admin",
    "is_active": True,
    "created_at": "2026-08-01T00:00:00Z",
    "updated_at": "2026-08-01T00:00:00Z",
}


def _login_out(token: str) -> dict[str, Any]:
    return {"access_token": token, "token_type": "bearer", "expires_in": 43200, "user": _USER_OUT}


class HubFalso:
    """Backend falso: emite um token novo a cada login; `rota` (injetada no construtor)
    decide a resposta para requests já autenticados. `chamadas_login` prova quantas vezes
    logou de verdade — é o que garante 'exatamente um retry, nunca loop' nos testes abaixo."""

    def __init__(self, rota: Callable[[httpx.Request], httpx.Response]) -> None:
        self._rota = rota
        self.chamadas_login = 0
        self.token_atual: str | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            self.chamadas_login += 1
            self.token_atual = f"tok{self.chamadas_login}"
            return httpx.Response(200, json=_login_out(self.token_atual))
        return self._rota(request)


async def _cliente(hub: HubFalso) -> ClienteOttima:
    transporte = httpx.MockTransport(hub.handler)
    return await ClienteOttima.conectar(_CONFIG, transport=transporte)


@pytest.mark.asyncio
async def test_login_seta_bearer_automatico() -> None:
    hub = HubFalso(
        rota=lambda r: httpx.Response(200, json={"ok": True})
        if r.headers.get("authorization") == "Bearer tok1"
        else httpx.Response(401, json={"detail": "Sessão inválida ou expirada"})
    )
    cliente = await _cliente(hub)
    resultado = await cliente.get("/api/qualquer")
    assert resultado == {"ok": True}
    assert hub.chamadas_login == 1
    await cliente.fechar()


@pytest.mark.asyncio
async def test_401_faz_exatamente_um_relogin_e_um_retry() -> None:
    # token da conexão inicial (tok1) já "expirou" do ponto de vista do backend: só tok2
    # (emitido pelo relogin dentro de `_chamar`) é aceito.
    hub = HubFalso(
        rota=lambda r: httpx.Response(200, json={"dado": 42})
        if r.headers.get("authorization") == "Bearer tok2"
        else httpx.Response(401, json={"detail": "Sessão inválida ou expirada"})
    )
    cliente = await _cliente(hub)
    resultado = await cliente.get("/api/protegido")
    assert resultado == {"dado": 42}
    assert hub.chamadas_login == 2  # 1 na conexão + 1 no retry — nunca mais
    await cliente.fechar()


@pytest.mark.asyncio
async def test_401_persistente_nao_faz_loop_e_levanta_erro() -> None:
    hub = HubFalso(
        rota=lambda r: httpx.Response(401, json={"detail": "Sessão inválida ou expirada"})
    )
    cliente = await _cliente(hub)
    with pytest.raises(ErroOttima) as exc_info:
        await cliente.get("/api/sempre-401")
    assert exc_info.value.status_code == 401
    assert exc_info.value.mensagem == "Sessão inválida ou expirada"
    # exatamente 2 logins (conexão + 1 retry) — a prova de que não entrou em loop.
    assert hub.chamadas_login == 2
    await cliente.fechar()


@pytest.mark.asyncio
async def test_422_vira_erro_ottima_com_detail_verbatim() -> None:
    mensagem = "Valor 150.0 fora da faixa de SP de 'cv_nivel' (80.0..120.0)"
    hub = HubFalso(rota=lambda r: httpx.Response(422, json={"detail": mensagem}))
    cliente = await _cliente(hub)
    with pytest.raises(ErroOttima) as exc_info:
        await cliente.post("/api/operate/1/mpc/sp", json={"var_id": "cv_nivel", "value": 150.0})
    assert exc_info.value.status_code == 422
    assert exc_info.value.mensagem == mensagem
    await cliente.fechar()


@pytest.mark.asyncio
async def test_404_vira_erro_ottima() -> None:
    hub = HubFalso(rota=lambda r: httpx.Response(404, json={"detail": "Flow não encontrado"}))
    cliente = await _cliente(hub)
    with pytest.raises(ErroOttima) as exc_info:
        await cliente.get("/api/flows/999")
    assert exc_info.value.status_code == 404
    assert exc_info.value.mensagem == "Flow não encontrado"
    await cliente.fechar()


@pytest.mark.asyncio
async def test_202_sem_corpo_devolve_none() -> None:
    hub = HubFalso(rota=lambda r: httpx.Response(202))
    cliente = await _cliente(hub)
    resultado = await cliente.post("/api/flows/1/deploy")
    assert resultado is None
    await cliente.fechar()


@pytest.mark.asyncio
async def test_204_sem_corpo_devolve_none() -> None:
    hub = HubFalso(rota=lambda r: httpx.Response(204))
    cliente = await _cliente(hub)
    resultado = await cliente.delete("/api/projects/1")
    assert resultado is None
    await cliente.fechar()


@pytest.mark.asyncio
async def test_get_omite_params_none_da_query_string() -> None:
    capturado: dict[str, Any] = {}

    def _rota(request: httpx.Request) -> httpx.Response:
        capturado["query"] = dict(request.url.params)
        return httpx.Response(200, json={"ok": True})

    hub = HubFalso(rota=_rota)
    cliente = await _cliente(hub)
    await cliente.get("/api/history", tag_ids="1,2", start=None, end="2026-08-17T00:00:00Z")
    assert capturado["query"] == {"tag_ids": "1,2", "end": "2026-08-17T00:00:00Z"}
    await cliente.fechar()
