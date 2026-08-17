"""ClienteOttima: login, bearer automático, re-login único em 401 (nunca loop), e ErroOttima
com o `detail` do backend verbatim. Sem rede — via a fixture `cliente_falso` (conftest.py)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ottima_mcp.cliente import ErroOttima


@pytest.mark.asyncio
async def test_login_seta_bearer_automatico(cliente_falso) -> None:
    cliente, hub = await cliente_falso(
        lambda r: httpx.Response(200, json={"ok": True})
        if r.headers.get("authorization") == "Bearer tok1"
        else httpx.Response(401, json={"detail": "Sessão inválida ou expirada"})
    )
    resultado = await cliente.get("/api/qualquer")
    assert resultado == {"ok": True}
    assert hub.chamadas_login == 1


@pytest.mark.asyncio
async def test_401_faz_exatamente_um_relogin_e_um_retry(cliente_falso) -> None:
    # token da conexão inicial (tok1) já "expirou" do ponto de vista do backend: só tok2
    # (emitido pelo relogin dentro de `_chamar`) é aceito.
    cliente, hub = await cliente_falso(
        lambda r: httpx.Response(200, json={"dado": 42})
        if r.headers.get("authorization") == "Bearer tok2"
        else httpx.Response(401, json={"detail": "Sessão inválida ou expirada"})
    )
    resultado = await cliente.get("/api/protegido")
    assert resultado == {"dado": 42}
    assert hub.chamadas_login == 2  # 1 na conexão + 1 no retry — nunca mais


@pytest.mark.asyncio
async def test_401_persistente_nao_faz_loop_e_levanta_erro(cliente_falso) -> None:
    cliente, hub = await cliente_falso(
        lambda r: httpx.Response(401, json={"detail": "Sessão inválida ou expirada"})
    )
    with pytest.raises(ErroOttima) as exc_info:
        await cliente.get("/api/sempre-401")
    assert exc_info.value.status_code == 401
    assert exc_info.value.mensagem == "Sessão inválida ou expirada"
    # exatamente 2 logins (conexão + 1 retry) — a prova de que não entrou em loop.
    assert hub.chamadas_login == 2


@pytest.mark.asyncio
async def test_422_vira_erro_ottima_com_detail_verbatim(cliente_falso) -> None:
    mensagem = "Valor 150.0 fora da faixa de SP de 'cv_nivel' (80.0..120.0)"
    cliente, _hub = await cliente_falso(lambda r: httpx.Response(422, json={"detail": mensagem}))
    with pytest.raises(ErroOttima) as exc_info:
        await cliente.post("/api/operate/1/mpc/sp", json={"var_id": "cv_nivel", "value": 150.0})
    assert exc_info.value.status_code == 422
    assert exc_info.value.mensagem == mensagem


@pytest.mark.asyncio
async def test_404_vira_erro_ottima(cliente_falso) -> None:
    cliente, _hub = await cliente_falso(
        lambda r: httpx.Response(404, json={"detail": "Flow não encontrado"})
    )
    with pytest.raises(ErroOttima) as exc_info:
        await cliente.get("/api/flows/999")
    assert exc_info.value.status_code == 404
    assert exc_info.value.mensagem == "Flow não encontrado"


@pytest.mark.asyncio
async def test_202_sem_corpo_devolve_none(cliente_falso) -> None:
    cliente, _hub = await cliente_falso(lambda r: httpx.Response(202))
    resultado = await cliente.post("/api/flows/1/deploy")
    assert resultado is None


@pytest.mark.asyncio
async def test_204_sem_corpo_devolve_none(cliente_falso) -> None:
    cliente, _hub = await cliente_falso(lambda r: httpx.Response(204))
    resultado = await cliente.delete("/api/projects/1")
    assert resultado is None


@pytest.mark.asyncio
async def test_get_omite_params_none_da_query_string(cliente_falso) -> None:
    capturado: dict[str, Any] = {}

    def _rota(request: httpx.Request) -> httpx.Response:
        capturado["query"] = dict(request.url.params)
        return httpx.Response(200, json={"ok": True})

    cliente, _hub = await cliente_falso(_rota)
    await cliente.get("/api/history", tag_ids="1,2", start=None, end="2026-08-17T00:00:00Z")
    assert capturado["query"] == {"tag_ids": "1,2", "end": "2026-08-17T00:00:00Z"}
