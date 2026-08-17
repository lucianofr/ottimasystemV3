"""Fixtures do pacote: backend falso (`HubFalso`) e `ClienteOttima` conectado contra ele, sem
rede (`httpx.MockTransport`). Mesmo padrão de fixture-factory de `services/api/tests/conftest.py`
(`make_user`). `hub_ws_falso`/`cliente_com_ws` sobem um servidor `websockets` REAL local para
testar o protocolo `/ws` de verdade (Fase 3) — REST continua mockado via `httpx.MockTransport`;
só a URL usada por `confirmacao.py` para derivar `ws://` é redirecionada ao servidor real
(`dataclasses.replace` no `Config` imutável, nunca tocando `cliente._http`)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace

import httpx
import pytest
import websockets
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

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


class HubWsFalso:
    """Servidor `/ws` real e local (`websockets.serve`, não mock): aceita, lê o subscribe
    (guardado em `.subscribes`), e fica esperando — o teste publica o que quiser via
    `.publicar(canal, dado)`, chamado de FORA da corrotina do handler, na mesma conexão
    (o padrão que o próprio `websockets` suporta: `send` concorrente de outra task).
    `.fechar_com_1008()` faz a(s) PRÓXIMA(S) conexão(ões) recusarem com código 1008 — para
    testar reautenticação (`confirmacao.py::_SessaoRecusada`)."""

    def __init__(self) -> None:
        self.subscribes: list[dict[str, object]] = []
        self._conexoes: list[ServerConnection] = []
        self._recusar_proximas = 0

    def fechar_com_1008(self, quantas: int = 1) -> None:
        self._recusar_proximas = quantas

    async def _handler(self, ws: ServerConnection) -> None:
        if self._recusar_proximas > 0:
            self._recusar_proximas -= 1
            await ws.close(code=1008, reason="Sessão inválida ou expirada")
            return
        self._conexoes.append(ws)
        try:
            bruta = await ws.recv()
            self.subscribes.append(json.loads(bruta))
            await ws.wait_closed()  # hiberna até o server fechar; teste publica via `.publicar()`
        except ConnectionClosed:
            pass
        finally:
            if ws in self._conexoes:
                self._conexoes.remove(ws)

    async def publicar(self, canal: str, dado: dict[str, object]) -> None:
        texto = json.dumps({"channel": canal, "data": dado})
        for ws in list(self._conexoes):
            await ws.send(texto)


FabricaClienteWs = Callable[[RotaFalsa], Awaitable[tuple[ClienteOttima, HubFalso, HubWsFalso]]]


@pytest.fixture
async def cliente_com_ws() -> AsyncIterator[FabricaClienteWs]:
    """`cliente, hub_rest, hub_ws = await cliente_com_ws(rota)` — REST mockado (igual
    `cliente_falso`) + `/ws` real local; `cliente.url` é redirecionada ao servidor real só
    para a derivação de `ws://` em `confirmacao.py` (REST continua no `MockTransport`)."""
    abertos: list[ClienteOttima] = []
    servidores: list[websockets.Server] = []

    async def _criar(rota: RotaFalsa) -> tuple[ClienteOttima, HubFalso, HubWsFalso]:
        hub_rest = HubFalso(rota)
        transporte = httpx.MockTransport(hub_rest.handler)
        cliente = await ClienteOttima.conectar(_CONFIG, transport=transporte)
        abertos.append(cliente)

        hub_ws = HubWsFalso()
        servidor = await websockets.serve(hub_ws._handler, "127.0.0.1", 0)
        porta = servidor.sockets[0].getsockname()[1]
        cliente._config = replace(cliente._config, url=f"http://127.0.0.1:{porta}")
        servidores.append(servidor)
        return cliente, hub_rest, hub_ws

    yield _criar
    for cliente in abertos:
        await cliente.fechar()
    for servidor in servidores:
        servidor.close()
        await servidor.wait_closed()
