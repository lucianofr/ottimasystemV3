"""Fixtures do pacote: backend falso (`HubFalso`) e `ClienteOttima` conectado contra ele, sem
rede (`httpx.MockTransport`). Mesmo padrão de fixture-factory de `services/api/tests/conftest.py`
(`make_user`)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
import pytest

from ottima_mcp.cliente import ClienteOttima
from ottima_mcp.config import Config

_CONFIG = Config(url="http://ottima.local", username="agente", password="segredo")

_USER_OUT = {
    "id": 7,
    "username": "agente",
    "name": "Agente MCP",
    "role": "admin",
    "is_active": True,
    "created_at": "2026-08-01T00:00:00Z",
    "updated_at": "2026-08-01T00:00:00Z",
}


def _login_out(token: str) -> dict[str, object]:
    return {"access_token": token, "token_type": "bearer", "expires_in": 43200, "user": _USER_OUT}


class HubFalso:
    """Backend falso: emite um token novo a cada login; `rota` decide a resposta para
    requests já autenticados. `chamadas_login` prova quantas vezes logou de verdade — é o
    que garante 'exatamente um retry, nunca loop' nos testes de `_chamar`."""

    def __init__(self, rota: Callable[[httpx.Request], httpx.Response]) -> None:
        self._rota = rota
        self.chamadas_login = 0
        self.token_atual: str | None = None
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/auth/login":
            self.chamadas_login += 1
            self.token_atual = f"tok{self.chamadas_login}"
            return httpx.Response(200, json=_login_out(self.token_atual))
        return self._rota(request)


RotaFalsa = Callable[[httpx.Request], httpx.Response]
FabricaCliente = Callable[[RotaFalsa], Awaitable[tuple[ClienteOttima, HubFalso]]]


@pytest.fixture
async def cliente_falso() -> AsyncIterator[FabricaCliente]:
    """`cliente, hub = await cliente_falso(rota)` — cliente conectado contra um `HubFalso`
    com a rota dada; fecha todos os clientes criados ao fim do teste."""
    abertos: list[ClienteOttima] = []

    async def _criar(rota: RotaFalsa) -> tuple[ClienteOttima, HubFalso]:
        hub = HubFalso(rota)
        transporte = httpx.MockTransport(hub.handler)
        cliente = await ClienteOttima.conectar(_CONFIG, transport=transporte)
        abertos.append(cliente)
        return cliente, hub

    yield _criar
    for cliente in abertos:
        await cliente.fechar()
