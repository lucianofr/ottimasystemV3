"""WebSocket `/ws`: fanout do canal `events` (spec F5 §5, decisão A-5; F5R-15; ADR-020).

Redis de verdade (fixture da F1) publicando no canal fixo `events` — nada de mock do hub,
mesmo padrão de `test_ws.py`/`test_ws_mpc.py`.

`WSClient` e as fixtures de conexão são cópia local das de `test_ws.py`/`test_ws_mpc.py`: o
workspace roda com `--import-mode=importlib` (vários serviços têm `tests/test_health.py`
homônimos sem `__init__.py`), que não insere o diretório de testes no `sys.path` — importar a
classe do outro arquivo não funciona. Duplicar aqui é o mesmo padrão já aberto como débito #7
do plano F4a (`await_until` em 5 cópias); nenhum dos dois foi fechado nesta tarefa.
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
    CHANNEL_EVENTS,
    EventMessage,
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

    async def subscribe_events(self) -> None:
        await self.send_json({"subscribe": {"events": True}})

    async def unsubscribe_events(self) -> None:
        await self.send_json({"unsubscribe": {"events": True}})

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
    """Payload `mpc.state.<flow_id>.<block_id>` do §5.1, com um único var preenchido."""
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


def event_json(
    *,
    severity: str = "warning",
    origin: str = "flow:1",
    message: str = "Falha de leitura",
    kind: str = "comm_failure",
) -> str:
    """Payload do canal `events` (bus §1.1): `{ts, severity, origin, message, payload}`."""
    return EventMessage(
        ts=datetime.now(UTC),
        severity=severity,
        origin=origin,
        message=message,
        payload={"kind": kind},
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
    return make_token(await make_user("oper-ws-events", role="operator"))


async def test_subscribe_events_recebe_payload_publicado(connect, operator_token, redis_client):
    async with connect(operator_token) as ws:
        await ws.ready()
        await ws.subscribe_events()

        await redis_client.publish(CHANNEL_EVENTS, event_json(message="Timeout no OPC"))

        message = await ws.receive_json()
        assert message["channel"] == "events"
        assert message["data"]["message"] == "Timeout no OPC"
        assert message["data"]["severity"] == "warning"


async def test_unsubscribe_events_para_o_fanout_e_subscribe_retoma(
    connect, operator_token, redis_client
):
    async with connect(operator_token) as ws:
        await ws.ready()
        await ws.subscribe_events()
        await redis_client.publish(CHANNEL_EVENTS, event_json())
        await ws.receive_json()

        await ws.unsubscribe_events()
        await redis_client.publish(CHANNEL_EVENTS, event_json())
        await ws.assert_silent()

        # o cano continua vivo: reassinar retoma o fanout normalmente
        await ws.subscribe_events()
        await redis_client.publish(CHANNEL_EVENTS, event_json(message="Retomado"))
        message = await ws.receive_json()
        assert message["data"]["message"] == "Retomado"


async def test_tres_canais_no_mesmo_socket_sem_vazar(connect, operator_token, redis_client):
    """flow_status, mpc_state e events assinados no mesmo socket roteiam juntos, sem um
    atropelar o outro (regressão de `flow_status`/`mpc_state` com o terceiro canal novo)."""
    async with connect(operator_token) as ws:
        await ws.ready()
        await ws.subscribe(1)
        await ws.subscribe_mpc_state("1/b1")
        await ws.subscribe_events()

        await redis_client.publish(channel_flow_status(1), status_json(scan_ms=7.0))
        await redis_client.publish(channel_mpc_state(1, "b1"), mpc_state_json(v=99.0))
        await redis_client.publish(CHANNEL_EVENTS, event_json(message="Evento do teste"))
        # não inscrito em nenhum: prova que o canal events não vaza para quem não assinou
        await redis_client.publish(channel_flow_status(2), status_json())

        received = {}
        for _ in range(3):
            message = await ws.receive_json()
            received[message["channel"]] = message
        assert received["flow.status.1"]["data"]["scan_ms"] == 7.0
        assert received["mpc.state.1.b1"]["data"]["vars"]["mv_x7k2"]["v"] == 99.0
        assert received["events"]["data"]["message"] == "Evento do teste"
        await ws.assert_silent()


async def test_events_valor_nao_booleano_e_no_op_logado(connect, operator_token, redis_client):
    async with connect(operator_token) as ws:
        await ws.ready()

        # false não assina
        await ws.send_json({"subscribe": {"events": False}})
        await redis_client.publish(CHANNEL_EVENTS, event_json())
        await ws.assert_silent()

        # número e lista também são ignorados, sem inverter a ação
        await ws.send_json({"subscribe": {"events": 1}})
        await ws.send_json({"subscribe": {"events": [True]}})
        await redis_client.publish(CHANNEL_EVENTS, event_json())
        await ws.assert_silent()

        # depois de assinar de verdade, um valor não-booleano em "unsubscribe" não desfaz
        await ws.subscribe_events()
        await redis_client.publish(CHANNEL_EVENTS, event_json())
        await ws.receive_json()

        await ws.send_json({"unsubscribe": {"events": False}})
        await redis_client.publish(CHANNEL_EVENTS, event_json(message="Ainda assinado"))
        message = await ws.receive_json()
        assert message["data"]["message"] == "Ainda assinado"


async def test_flow_status_e_mpc_state_seguem_intactos_sem_subscribe_events(
    connect, operator_token, redis_client
):
    """Regressão explícita: socket que nunca toca `events` mantém `flow_status`/`mpc_state`
    funcionando exatamente como antes desta tarefa, e um evento publicado nunca vaza para
    quem não assinou o canal."""
    async with connect(operator_token) as ws:
        await ws.ready()
        await ws.subscribe(1)
        await ws.subscribe_mpc_state("1/b1")

        await redis_client.publish(channel_flow_status(1), status_json(scan_ms=4.0))
        await redis_client.publish(channel_mpc_state(1, "b1"), mpc_state_json(v=5.0))
        await redis_client.publish(CHANNEL_EVENTS, event_json())

        received = {}
        for _ in range(2):
            message = await ws.receive_json()
            received[message["channel"]] = message
        assert received["flow.status.1"]["data"]["scan_ms"] == 4.0
        assert received["mpc.state.1.b1"]["data"]["vars"]["mv_x7k2"]["v"] == 5.0
        await ws.assert_silent()


async def test_token_invalido_fecha_com_1008(connect):
    async with connect("nao-e-um-jwt") as ws:
        assert await ws.close_code() == 1008
