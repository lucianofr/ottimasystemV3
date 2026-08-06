"""WebSocket `/ws`: fanout de `mpc.state.<flow_id>.<block_id>` (spec F4 §6.2, decisão A-6).

Redis de verdade (fixture da F1) publicando em `mpc.state.<flow_id>.<block_id>`: nada de mock
do hub — mesmo padrão de `test_ws.py`.

`WSClient` e as fixtures de conexão são cópia local das de `test_ws.py`: o workspace roda com
`--import-mode=importlib` (vários serviços têm `tests/test_health.py` homônimos sem
`__init__.py`), que não insere o diretório de testes no `sys.path` — importar a classe do outro
arquivo não funciona. Duplicar aqui é o mesmo padrão já aberto como débito #7 do plano F4a
(`await_until` em 5 cópias); nenhum dos dois foi fechado nesta tarefa.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI

from ottima_api.ws import FlowStatusHub
from ottima_core.bus import (
    FlowStatus,
    MpcModes,
    MpcPrediction,
    MpcState,
    MpcStatus,
    MpcVarState,
    PortValue,
    channel_flow_status,
    channel_mpc_state,
)
from ottima_core.security import create_access_token

RECEIVE_TIMEOUT_S = 5.0
"""Teto de espera por mensagem: cobre o trânsito pelo Redis real."""

SILENCE_S = 0.5
"""Janela para provar que nada chega. Todo teste de silêncio confirma em seguida que o cano
funciona, então uma janela curta não vira falso positivo."""


def _payload_of(message: dict[str, Any]) -> dict[str, Any]:
    assert message["type"] == "websocket.send", message
    return json.loads(message["text"])


class WSClient:
    """Cliente WS in-process: fala ASGI direto, no mesmo event loop do teste.

    O `TestClient` do Starlette roda o app em outra thread com o seu próprio loop, e a sessão
    de banco das fixtures vive num SAVEPOINT preso ao loop do teste. Aqui também mora o
    cliente lento: `stall()` trava o `send` do servidor como um TCP cheio o travaria.

    A conexão só é aberta em `ready()`/`close_code()`, e `ready()` volta apenas com o socket
    já registrado no hub — sem essa barreira o teste correria contra a autenticação, que
    consulta o banco, e publicaria antes de haver quem recebesse.
    """

    def __init__(self, app: FastAPI, token: str | None) -> None:
        self._app = app
        self._token = token
        self._inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._gate = asyncio.Event()
        self._gate.set()
        self._consumed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> WSClient:
        self._task = asyncio.create_task(self._app(self._scope(), self._receive, self._send))
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.resume()  # um socket travado não pode segurar o desmonte do teste
        await self.disconnect()

    async def ready(self) -> None:
        """Abre a conexão e volta com o socket aceito, autenticado e registrado no hub."""
        await self._outbox.put({"type": "websocket.connect"})
        message = await self._next(RECEIVE_TIMEOUT_S)
        assert message["type"] == "websocket.accept", message
        # `{}` é no-op no protocolo; ser consumido prova que o servidor já está no laço
        await self.send_text("{}")

    async def close_code(self) -> int:
        """Código do fechamento; o upgrade é aceito antes de recusar (contrato do §5.3)."""
        await self._outbox.put({"type": "websocket.connect"})
        message = await self._next(RECEIVE_TIMEOUT_S)
        assert message["type"] == "websocket.accept", message
        message = await self._next(RECEIVE_TIMEOUT_S)
        assert message["type"] == "websocket.close", message
        return message["code"]

    async def disconnect(self) -> None:
        """Desconexão do lado do cliente, como um browser que fecha a aba."""
        task, self._task = self._task, None
        if task is None:
            return
        await self._outbox.put({"type": "websocket.disconnect", "code": 1000})
        with suppress(TimeoutError):
            await asyncio.wait_for(task, RECEIVE_TIMEOUT_S)

    def stall(self) -> None:
        """Trava o envio do servidor para este cliente (TCP cheio)."""
        self._gate.clear()

    def resume(self) -> None:
        self._gate.set()

    async def send_text(self, text: str) -> None:
        self._consumed.clear()
        await self._outbox.put({"type": "websocket.receive", "text": text})
        await self._settled()

    async def send_json(self, payload: dict[str, Any]) -> None:
        await self.send_text(json.dumps(payload))

    async def subscribe(self, *flow_ids: int) -> None:
        await self.send_json({"subscribe": {"flow_status": list(flow_ids)}})

    async def unsubscribe(self, *flow_ids: int) -> None:
        await self.send_json({"unsubscribe": {"flow_status": list(flow_ids)}})

    async def subscribe_mpc_state(self, *ids: str) -> None:
        await self.send_json({"subscribe": {"mpc_state": list(ids)}})

    async def unsubscribe_mpc_state(self, *ids: str) -> None:
        await self.send_json({"unsubscribe": {"mpc_state": list(ids)}})

    async def receive_json(self) -> dict[str, Any]:
        return _payload_of(await self._next(RECEIVE_TIMEOUT_S))

    async def assert_silent(self) -> None:
        with pytest.raises(TimeoutError):
            await self._next(SILENCE_S)

    async def drain(self) -> list[dict[str, Any]]:
        """Tudo o que o cliente ainda tem para receber, até o cano secar."""
        received = []
        while True:
            try:
                received.append(_payload_of(await self._next(SILENCE_S)))
            except TimeoutError:
                return received

    async def _settled(self) -> None:
        """Volta quando o servidor consumiu o envio.

        O comando é aplicado sem nenhum `await` no meio, então consumo já significa comando
        em vigor: é o que torna `subscribe` seguido de `publish` determinístico.
        """
        async with asyncio.timeout(RECEIVE_TIMEOUT_S):
            await self._consumed.wait()

    async def _next(self, wait_s: float) -> dict[str, Any]:
        async with asyncio.timeout(wait_s):
            return await self._inbox.get()

    async def _send(self, message: dict[str, Any]) -> None:
        await self._gate.wait()
        await self._inbox.put(message)

    async def _receive(self) -> dict[str, Any]:
        message = await self._outbox.get()
        self._consumed.set()
        return message

    def _scope(self) -> dict[str, Any]:
        query = b"" if self._token is None else f"token={self._token}".encode()
        return {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "server": ("test", 80),
            "client": ("test", 50000),
            "path": "/ws",
            "raw_path": b"/ws",
            "root_path": "",
            "query_string": query,
            "headers": [(b"host", b"test")],
            "subprotocols": [],
            "state": {},
        }


def status_json(scan_ms: float = 3.2, v: float | bool | None = 42.5) -> str:
    """Payload de varredura do §4.2, com `ports` preenchido como o runtime publica."""
    return FlowStatus(
        state="running",
        scan_ms=scan_ms,
        overruns=0,
        ts=datetime.now(UTC),
        ports={"b1": {"out": PortValue(v=v, ok=True), "in": PortValue(v=None, ok=False)}},
    ).model_dump_json()


def mpc_state_json(
    *,
    local_remote: str = "local",
    man_auto: str = "man",
    solver: str = "idle",
    var_id: str = "mv_x7k2",
    v: float = 12.3,
    sp: float | None = None,
) -> str:
    """Payload `mpc.state.<flow_id>.<block_id>` do §5.1, com um único var preenchido.

    `ts`/`prediction.ts` (spec F5 §2.1) são carimbados com o mesmo instante — fora de AUTO
    (o único modo exercitado por este helper), `prediction.ts == ts` e `t: []` (§2.1-2).
    """
    ts = datetime.now(UTC)
    return MpcState(
        ts=ts,
        modes=MpcModes(local_remote=local_remote, man_auto=man_auto),
        status=MpcStatus(
            solver=solver, overruns=0, last_solve_ms=0.0, armed=False, input_valid=True
        ),
        vars={var_id: MpcVarState(v=v, sp=sp)},
        cost=0.0,
        prediction=MpcPrediction(ts=ts, t=[], cv=[], mv=[]),
    ).model_dump_json()


@pytest.fixture
async def hub(app, redis_client):
    """Hub real sobre o Redis efêmero: o lifespan não roda sob ASGITransport."""
    flow_status_hub = FlowStatusHub(redis_client)
    await flow_status_hub.start()
    app.state.flow_status_hub = flow_status_hub
    yield flow_status_hub
    await flow_status_hub.stop()


@pytest.fixture
def ws_session_cycles(app, db_session):
    """Factory do `/ws` instrumentada: emprestar a sessão em SAVEPOINT sem fechá-la de verdade."""
    ciclos = {"abertas": 0, "fechadas": 0}

    @asynccontextmanager
    async def _session_factory():
        ciclos["abertas"] += 1
        try:
            yield db_session
        finally:
            ciclos["fechadas"] += 1

    app.state.session_factory = _session_factory
    return ciclos


@pytest.fixture
def connect(app, hub, ws_session_cycles):
    """Abre sockets contra o app real; a factory do `/ws` serve a sessão em SAVEPOINT."""

    def _connect(token: str | None) -> WSClient:
        return WSClient(app, token)

    return _connect


@pytest.fixture
def make_token(test_settings):
    def _make(user, ttl_hours: int = 1) -> str:
        return create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
            secret=test_settings.secret_key,
            ttl_hours=ttl_hours,
        )

    return _make


@pytest.fixture
async def operator_token(make_user, make_token) -> str:
    return make_token(await make_user("oper-ws-mpc", role="operator"))


async def test_subscribe_mpc_state_recebe_payload_do_bloco(connect, operator_token, redis_client):
    async with connect(operator_token) as ws:
        await ws.ready()
        await ws.subscribe_mpc_state("1/b1")

        await redis_client.publish(channel_mpc_state(1, "b1"), mpc_state_json(v=42.5))

        message = await ws.receive_json()
        assert message["channel"] == "mpc.state.1.b1"
        assert message["data"]["vars"]["mv_x7k2"]["v"] == 42.5


async def test_unsubscribe_mpc_state_para_o_fanout_e_subscribe_retoma(
    connect, operator_token, redis_client
):
    async with connect(operator_token) as ws:
        await ws.ready()
        await ws.subscribe_mpc_state("1/b1")
        await redis_client.publish(channel_mpc_state(1, "b1"), mpc_state_json())
        await ws.receive_json()

        await ws.unsubscribe_mpc_state("1/b1")
        await redis_client.publish(channel_mpc_state(1, "b1"), mpc_state_json())
        await ws.assert_silent()

        # o cano continua vivo: reassinar retoma o fanout normalmente
        await ws.subscribe_mpc_state("1/b1")
        await redis_client.publish(channel_mpc_state(1, "b1"), mpc_state_json(v=7.0))
        message = await ws.receive_json()
        assert message["data"]["vars"]["mv_x7k2"]["v"] == 7.0


async def test_flow_status_e_mpc_state_roteiam_juntos_sem_vazar(
    connect, operator_token, redis_client
):
    """Regressão do roteio duplo: o segundo `PatternListener` do hub (`mpc.state.*`) não
    atropela nem vaza no roteio de `flow.status.*` — cada barramento segue isolado por
    flow/bloco inscrito, no mesmo socket (§5.3/§6.2)."""
    async with connect(operator_token) as ws:
        await ws.ready()
        await ws.subscribe(1)
        await ws.subscribe_mpc_state("1/b1")

        await redis_client.publish(channel_flow_status(1), status_json(scan_ms=7.0))
        await redis_client.publish(channel_mpc_state(1, "b1"), mpc_state_json(v=99.0))
        # não inscrito em nenhum dos dois: prova que não vaza entre flows nem entre blocos
        await redis_client.publish(channel_flow_status(2), status_json())
        await redis_client.publish(channel_mpc_state(1, "outro"), mpc_state_json())

        received = {}
        for _ in range(2):
            message = await ws.receive_json()
            received[message["channel"]] = message["data"]
        assert received["flow.status.1"]["scan_ms"] == 7.0
        assert received["mpc.state.1.b1"]["vars"]["mv_x7k2"]["v"] == 99.0
        await ws.assert_silent()


async def test_mpc_state_malformado_e_ignorado_sem_derrubar_o_socket(
    connect, operator_token, redis_client
):
    async with connect(operator_token) as ws:
        await ws.ready()
        await ws.send_json(
            {"subscribe": {"mpc_state": ["sem-barra", 42, None, "1/", "/b1", "x/b1"]}}
        )
        # nenhum item acima forma um par (flow_id, block_id) válido: nada alcança o socket
        await redis_client.publish(channel_mpc_state(1, "b1"), mpc_state_json())
        await ws.assert_silent()

        # o socket segue vivo: uma inscrição válida na sequência funciona normalmente
        await ws.subscribe_mpc_state("1/b1")
        await redis_client.publish(channel_mpc_state(1, "b1"), mpc_state_json(v=3.0))
        message = await ws.receive_json()
        assert message["data"]["vars"]["mv_x7k2"]["v"] == 3.0


async def test_token_invalido_fecha_com_1008(connect):
    async with connect("nao-e-um-jwt") as ws:
        assert await ws.close_code() == 1008
