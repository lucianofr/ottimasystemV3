"""WebSocket `/ws`: auth, protocolo, fanout e isolamento entre clientes (RF-305, spec §5.3).

Redis de verdade (fixture da F1) publicando em `flow.status.<id>`: nada de mock do hub.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI

from ottima_api.ws import QUEUE_MAX, FlowStatusHub
from ottima_core.bus import FlowStatus, PortValue, channel_flow_status
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
    """Factory do `/ws` instrumentada: conta as sessões que a autenticação abre e fecha.

    A sessão em SAVEPOINT é só emprestada — fechá-la de verdade quebraria o isolamento do
    teste. O que se conta é o ciclo: `abertas` na entrada, `fechadas` na saída do `with`.
    """
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
    return make_token(await make_user("oper-ws", role="operator"))


async def test_operador_recebe_status_do_flow_inscrito(connect, operator_token, redis_client):
    async with connect(operator_token) as ws:
        await ws.ready()
        await ws.subscribe(1)

        await redis_client.publish(channel_flow_status(1), status_json())

        message = await ws.receive_json()
        assert message["channel"] == "flow.status.1"
        assert message["data"]["state"] == "running"
        # O contrato do canvas é o conteúdo de `ports`, não a presença da chave
        assert message["data"]["ports"]["b1"]["out"] == {"v": 42.5, "ok": True}
        assert message["data"]["ports"]["b1"]["in"] == {"v": None, "ok": False}


async def test_admin_tambem_e_aceito(connect, make_user, make_token, redis_client):
    token = make_token(await make_user("admin-ws", role="admin"))
    async with connect(token) as ws:
        await ws.ready()
        await ws.subscribe(1)

        await redis_client.publish(channel_flow_status(1), status_json())

        assert (await ws.receive_json())["channel"] == "flow.status.1"


async def test_token_ausente_fecha_com_1008(connect):
    async with connect(None) as ws:
        assert await ws.close_code() == 1008


async def test_token_invalido_fecha_com_1008(connect):
    async with connect("nao-e-um-jwt") as ws:
        assert await ws.close_code() == 1008


async def test_token_expirado_fecha_com_1008(connect, make_user, make_token):
    token = make_token(await make_user("oper-exp", role="operator"), ttl_hours=-1)
    async with connect(token) as ws:
        assert await ws.close_code() == 1008


async def test_usuario_inativo_fecha_com_1008(connect, make_user, make_token):
    token = make_token(await make_user("oper-off", role="operator", is_active=False))
    async with connect(token) as ws:
        assert await ws.close_code() == 1008


async def test_socket_vivo_nao_retem_sessao_do_banco(
    connect, ws_session_cycles, operator_token, redis_client
):
    """A sessão da autenticação fecha antes do laço de `receive`: socket vivo, pool livre.

    Com o `Depends(get_ws_db)` antigo a sessão só fechava junto com o socket — `fechadas`
    ficaria 0 neste ponto — e uma dúzia de editores abertos esgotava o pool da API inteira.
    """
    async with connect(operator_token) as ws:
        await ws.ready()  # só volta com o servidor já dentro do laço de receive

        assert ws_session_cycles == {"abertas": 1, "fechadas": 1}

        # O socket segue funcional sem sessão alguma: o laço nunca tocou no banco.
        await ws.subscribe(1)
        await redis_client.publish(channel_flow_status(1), status_json())
        assert (await ws.receive_json())["channel"] == "flow.status.1"


async def test_sem_subscribe_nao_ha_fanout(connect, operator_token, redis_client):
    async with connect(operator_token) as ws:
        await ws.ready()

        await redis_client.publish(channel_flow_status(1), status_json())
        await ws.assert_silent()

        await ws.subscribe(1)
        await redis_client.publish(channel_flow_status(1), status_json())
        assert (await ws.receive_json())["channel"] == "flow.status.1"


async def test_unsubscribe_para_o_fanout_e_subscribe_retoma(connect, operator_token, redis_client):
    async with connect(operator_token) as ws:
        await ws.ready()
        await ws.subscribe(1)
        await redis_client.publish(channel_flow_status(1), status_json(scan_ms=1.0))
        assert (await ws.receive_json())["data"]["scan_ms"] == 1.0

        await ws.unsubscribe(1)
        await redis_client.publish(channel_flow_status(1), status_json(scan_ms=2.0))
        await ws.assert_silent()

        await ws.subscribe(1)
        await redis_client.publish(channel_flow_status(1), status_json(scan_ms=3.0))
        assert (await ws.receive_json())["data"]["scan_ms"] == 3.0


async def test_dois_sockets_no_mesmo_flow_recebem_ambos(connect, operator_token, redis_client):
    async with connect(operator_token) as um, connect(operator_token) as outro:
        for ws in (um, outro):
            await ws.ready()
            await ws.subscribe(7)

        await redis_client.publish(channel_flow_status(7), status_json(scan_ms=9.5))

        for ws in (um, outro):
            assert (await ws.receive_json())["data"]["scan_ms"] == 9.5


async def test_flow_nao_inscrito_nao_vaza_para_o_socket(connect, operator_token, redis_client):
    async with connect(operator_token) as ws:
        await ws.ready()
        await ws.subscribe(1)

        await redis_client.publish(channel_flow_status(2), status_json())
        await ws.assert_silent()

        await redis_client.publish(channel_flow_status(1), status_json())
        assert (await ws.receive_json())["channel"] == "flow.status.1"


async def test_uma_assinatura_redis_para_n_sockets(connect, operator_token, redis_client):
    """Efeito observável: abrir sockets não cria assinante nem cliente pubsub novo."""
    padroes_antes = await redis_client.pubsub_numpat()
    # Leitura escopada por tipo, sem CLIENT KILL: só se conta o que está em modo pubsub
    clientes_antes = len(await redis_client.client_list(_type="pubsub"))

    async with (
        connect(operator_token) as um,
        connect(operator_token) as dois,
        connect(operator_token) as tres,
    ):
        sockets = (um, dois, tres)
        for ws in sockets:
            await ws.ready()
            await ws.subscribe(4)

        assert await redis_client.pubsub_numpat() == padroes_antes
        assert len(await redis_client.client_list(_type="pubsub")) == clientes_antes

        await redis_client.publish(channel_flow_status(4), status_json(scan_ms=4.4))
        for ws in sockets:
            assert (await ws.receive_json())["data"]["scan_ms"] == 4.4


@pytest.mark.parametrize(
    "lixo",
    [
        "isto nao e json",
        '{"subscribe": "flow_status"}',
        '{"subscribe": {"eventos": [1]}}',
        '{"subscribe": {"flow_status": "tudo"}}',
        '{"subscribe": {"flow_status": [1, "dois", null]}}',
        "[1, 2, 3]",
    ],
)
async def test_mensagem_malformada_nao_derruba_o_socket(
    connect, operator_token, redis_client, lixo
):
    async with connect(operator_token) as ws:
        await ws.ready()
        await ws.send_text(lixo)

        await ws.subscribe(1)
        await redis_client.publish(channel_flow_status(1), status_json())
        assert (await ws.receive_json())["channel"] == "flow.status.1"


async def test_sem_replay_do_ultimo_valor(connect, operator_token, redis_client):
    """Assinar não entrega o último valor: o hub não guarda estado de flow (RNF-05)."""
    async with connect(operator_token) as testemunha, connect(operator_token) as ws:
        await testemunha.ready()
        await testemunha.subscribe(1)
        await ws.ready()

        await redis_client.publish(channel_flow_status(1), status_json(scan_ms=1.0))
        # A testemunha recebendo é a prova de que o hub já processou esta publicação
        assert (await testemunha.receive_json())["data"]["scan_ms"] == 1.0

        await ws.subscribe(1)
        await ws.assert_silent()

        await redis_client.publish(channel_flow_status(1), status_json(scan_ms=2.0))
        assert (await ws.receive_json())["data"]["scan_ms"] == 2.0


async def test_queda_de_um_socket_nao_derruba_o_hub(connect, operator_token, redis_client):
    async with connect(operator_token) as sobrevivente:
        await sobrevivente.ready()
        await sobrevivente.subscribe(1)

        efemero = connect(operator_token)
        await efemero.__aenter__()
        await efemero.ready()
        await efemero.subscribe(1)
        await efemero.disconnect()

        await redis_client.publish(channel_flow_status(1), status_json(scan_ms=8.0))
        assert (await sobrevivente.receive_json())["data"]["scan_ms"] == 8.0


async def test_cliente_lento_nao_bloqueia_os_demais(connect, operator_token, redis_client):
    """Contrato 2: o laço do hub só enfileira.

    Com `await socket.send_json(...)` direto no laço, o socket travado congelaria o fanout e
    o cliente em dia não receberia a sequência inteira.
    """
    publicadas = QUEUE_MAX + 5
    async with connect(operator_token) as lento, connect(operator_token) as em_dia:
        for ws in (lento, em_dia):
            await ws.ready()
            await ws.subscribe(1)

        lento.stall()
        for i in range(publicadas):
            await redis_client.publish(channel_flow_status(1), status_json(scan_ms=float(i)))

        recebidas = [(await em_dia.receive_json())["data"]["scan_ms"] for _ in range(publicadas)]
        assert recebidas == [float(i) for i in range(publicadas)]

        lento.resume()
        atrasadas = [m["data"]["scan_ms"] for m in await lento.drain()]
        # Fila limitada + a mensagem presa no envio; o mais novo chega, o miolo é descartado
        assert 0 < len(atrasadas) <= QUEUE_MAX + 1
        assert len(atrasadas) < publicadas
        assert atrasadas[-1] == float(publicadas - 1)
