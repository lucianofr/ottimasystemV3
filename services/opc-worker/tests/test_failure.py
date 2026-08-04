"""Testes da integração de falha do opc-worker (RF-207, spec F2 §2.2-6, §3.6, §3.8).

Tudo roda contra o opcsim in-process (nunca contra PLC real) e contra o Redis real da
fixture da raiz. O assinante é UM só para os dois canais (`events` e
`opc.values.<conn_id>`): a ordem relativa entre a rajada de `quality=2` e o alarme é
contrato da spec e só se prova observando os dois no mesmo fluxo de entrega.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress

import pytest
from redis.asyncio import Redis

from opcsim import (
    NODE_COUNTER,
    NODE_SINE,
    NODE_STATIC,
    NODE_W_FLOAT,
    NODE_WD_FROM_SYSTEM,
    NODE_WD_TO_SYSTEM,
    OpcSimServer,
    free_port,
)
from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_COMM_FAILURE,
    KIND_COMM_RESTORED,
    channel_opc_values,
)
from ottima_opc_worker import connection as connection_module
from ottima_opc_worker.connection import ConnectionRuntime
from ottima_opc_worker.state import (
    ConnectionConfig,
    ConnectionSnapshot,
    ConnectionState,
    TagConfig,
)
from ottima_opc_worker.subscriptions import QUALITY_BAD

CONN_ID = 11

# O rung do opcsim reage a cada 50 ms; abaixo de 100 ms o handshake não fecha.
WATCHDOG_PERIOD_MS = 200
# 1,1 s com período de 200 ms cai no 6º ciclo (1,2 s) depois da última alternância: longe
# das duas bordas da janela medida. Um limiar de 1,0 s seria múltiplo exato do período e
# deixaria a detecção oscilando entre o 5º e o 6º ciclo, no fio do limiar.
TEST_FREEZE_THRESHOLD_S = 1.1

# Backoff curto: os testes não podem esperar o 1→2→4 s de produção.
TEST_BACKOFF_INITIAL_S = 0.05
TEST_BACKOFF_MAX_S = 0.2
# Heartbeat fora do caminho: só a rajada da transição publica `quality=2` nestes ensaios.
QUIET_HEARTBEAT_S = 30.0
# Heartbeat rápido, para o ensaio que exige republicação bad DEPOIS da rajada.
FAST_HEARTBEAT_S = 1.0

AWAIT_TIMEOUT_S = 20.0
# Janela para provar que algo NÃO acontece (vários ciclos de reconexão em backoff).
QUIET_WINDOW_S = 1.5

TAG_SINE = TagConfig(
    id=101, name="Temperatura", node_id=NODE_SINE, direction="r", data_type="float"
)
TAG_COUNTER = TagConfig(id=102, name="Ciclos", node_id=NODE_COUNTER, direction="r", data_type="int")
TAG_STATIC = TagConfig(
    id=103, name="Nível fixo", node_id=NODE_STATIC, direction="r", data_type="float"
)
# Tag de escrita: a rajada é só das tags `r`, e este é o contraexemplo que prova isso.
TAG_WRITE = TagConfig(
    id=104, name="Setpoint", node_id=NODE_W_FLOAT, direction="w", data_type="float"
)
TAGS = (TAG_SINE, TAG_COUNTER, TAG_STATIC, TAG_WRITE)
READ_TAG_IDS = frozenset({TAG_SINE.id, TAG_COUNTER.id, TAG_STATIC.id})

BusTrail = list[tuple[str, dict]]


async def await_until(
    condition: Callable[[], bool], timeout_s: float = AWAIT_TIMEOUT_S, interval: float = 0.02
) -> None:
    """Aguarda a condição virar verdadeira, com polling — evita sleep cego nos testes."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if condition():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"condição não satisfeita em {timeout_s}s")


def make_config(endpoint: str, *, with_watchdog: bool = False) -> ConnectionConfig:
    return ConnectionConfig(
        id=CONN_ID,
        project_id=1,
        name="Forno 1",
        endpoint=endpoint,
        security_policy="none",
        security_mode="none",
        auth_mode="anonymous",
        auth_username=None,
        auth_password_enc=None,
        server_cert_file=None,
        watchdog_read_node_id=NODE_WD_TO_SYSTEM if with_watchdog else None,
        watchdog_write_node_id=NODE_WD_FROM_SYSTEM if with_watchdog else None,
        watchdog_period_ms=WATCHDOG_PERIOD_MS,
        tags=TAGS,
    )


def make_runtime(
    config: ConnectionConfig,
    redis_client: Redis,
    snapshot: ConnectionSnapshot,
    *,
    heartbeat_interval_s: float = QUIET_HEARTBEAT_S,
) -> ConnectionRuntime:
    return ConnectionRuntime(
        config,
        redis_client,
        snapshot,
        backoff_initial_s=TEST_BACKOFF_INITIAL_S,
        backoff_max_s=TEST_BACKOFF_MAX_S,
        heartbeat_interval_s=heartbeat_interval_s,
        watchdog_freeze_threshold_s=TEST_FREEZE_THRESHOLD_S,
    )


@asynccontextmanager
async def collect_bus(redis_client: Redis, conn_id: int) -> AsyncIterator[BusTrail]:
    """Assina `events` e `opc.values.<id>` no MESMO pubsub.

    Dois assinantes separados não provariam nada: só uma única conexão de entrega
    preserva a ordem relativa entre os canais, que é o que a spec §2.2-6 fixa.
    """
    values_channel = channel_opc_values(conn_id)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_EVENTS, values_channel)
    trail: BusTrail = []
    pending = {CHANNEL_EVENTS, values_channel}
    subscribed = asyncio.Event()

    async def _reader() -> None:
        async for message in pubsub.listen():
            if message["type"] == "subscribe":
                pending.discard(message["channel"])
                if not pending:
                    subscribed.set()
            elif message["type"] == "message":
                trail.append((message["channel"], json.loads(message["data"])))

    task = asyncio.create_task(_reader(), name="test-bus-reader")
    try:
        await asyncio.wait_for(subscribed.wait(), timeout=5.0)
        yield trail
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await pubsub.aclose()


def events_of_kind(trail: BusTrail, kind: str) -> list[dict]:
    return [
        message
        for channel, message in list(trail)
        if channel == CHANNEL_EVENTS and message["payload"]["kind"] == kind
    ]


def bad_values(trail: BusTrail) -> list[dict]:
    return [
        message
        for channel, message in list(trail)
        if channel != CHANNEL_EVENTS and message["quality"] == QUALITY_BAD
    ]


def index_of_first(trail: BusTrail, kind: str) -> int:
    for position, (channel, message) in enumerate(list(trail)):
        if channel == CHANNEL_EVENTS and message["payload"]["kind"] == kind:
            return position
    raise AssertionError(f"evento {kind} não chegou ao barramento")


def bad_tag_ids_before(trail: BusTrail, position: int) -> set[int]:
    return {message["tag_id"] for message in bad_values(list(trail)[:position])}


@asynccontextmanager
async def running(runtime: ConnectionRuntime) -> AsyncIterator[ConnectionRuntime]:
    await runtime.start()
    try:
        yield runtime
    finally:
        await runtime.stop()


@pytest.fixture
async def sim() -> AsyncIterator[OpcSimServer]:
    server = OpcSimServer(port=free_port())
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


# --- transição de falha: alarme e rajada bad ---------------------------------------


async def test_congelamento_alarma_uma_vez_com_a_rajada_bad_antes(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Rung congelado ⇒ 1 alarme `watchdog_timeout` e todas as tags `r` em quality=2 antes dele."""
    config = make_config(sim.endpoint, with_watchdog=True)
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_bus(redis_client, config.id) as trail:
        async with running(make_runtime(config, redis_client, snapshot)) as runtime:
            await await_until(lambda: snapshot.watchdog_alive)
            await sim.set_freeze_watchdog(True)
            await await_until(lambda: len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1)

            posicao = index_of_first(trail, KIND_COMM_FAILURE)
            alarme = list(trail)[posicao][1]
            assert alarme["severity"] == "alarm"
            assert alarme["origin"] == f"conn:{config.id}"
            assert alarme["payload"]["kind"] == KIND_COMM_FAILURE
            assert alarme["payload"]["conn_id"] == config.id
            assert alarme["payload"]["reason"] == "watchdog_timeout"
            assert alarme["payload"]["detail"]
            # A rajada precede o alarme: quem reage ao alarme já lê dado coerente.
            assert bad_tag_ids_before(trail, posicao) == set(READ_TAG_IDS)
            # Bloqueio de escrita simultâneo à detecção (spec §3.8).
            assert runtime.state is ConnectionState.FAILED
            assert snapshot.watchdog_alive is False
            assert snapshot.session_up_since is None


async def test_delta_da_deteccao_ao_alarme_e_proporcional_ao_limiar(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Detecção → evento sem espera intermediária: prova em escala do aceite <12 s (§3.8)."""
    config = make_config(sim.endpoint, with_watchdog=True)
    snapshot = ConnectionSnapshot(name=config.name)
    periodo_s = WATCHDOG_PERIOD_MS / 1000
    async with collect_bus(redis_client, config.id) as trail:
        async with running(make_runtime(config, redis_client, snapshot)):
            await await_until(lambda: snapshot.watchdog_alive)
            await sim.set_freeze_watchdog(True)
            congelado_em = time.monotonic()
            await await_until(
                lambda: len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1, interval=0.005
            )
            decorrido = time.monotonic() - congelado_em

    assert TEST_FREEZE_THRESHOLD_S <= decorrido <= TEST_FREEZE_THRESHOLD_S + 2 * periodo_s + 1.0


async def test_falha_dura_alarma_quase_imediatamente(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Servidor sumindo com a sessão `up`: `session_lost` em ~0 s, com a rajada bad junto."""
    config = make_config(sim.endpoint, with_watchdog=True)
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_bus(redis_client, config.id) as trail:
        async with running(make_runtime(config, redis_client, snapshot)):
            await await_until(lambda: snapshot.watchdog_alive)
            await sim.stop()
            caiu_em = time.monotonic()
            await await_until(
                lambda: len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1, interval=0.005
            )
            decorrido = time.monotonic() - caiu_em
            posicao = index_of_first(trail, KIND_COMM_FAILURE)
            alarme = list(trail)[posicao][1]

    assert decorrido < 2.0, f"falha dura demorou {decorrido:.3f}s"
    assert alarme["payload"]["reason"] == "session_lost"
    assert bad_tag_ids_before(trail, posicao) == set(READ_TAG_IDS)


async def test_fail_concorrente_produz_um_alarme_e_uma_rajada(redis_client: Redis) -> None:
    """Watchdog e laço de sessão podem chamar `fail()` juntos: 1 evento, 1 rajada."""
    # Runtime não iniciado: o ensaio é da transição em si, sem sessão nem reconexão.
    config = make_config("opc.tcp://127.0.0.1:1/nao-usado")
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = make_runtime(config, redis_client, snapshot)
    async with collect_bus(redis_client, config.id) as trail:
        await asyncio.gather(
            runtime.fail("session_lost", "primeira"),
            runtime.fail("watchdog_timeout", "segunda"),
        )
        await await_until(lambda: len(bad_values(trail)) == len(READ_TAG_IDS))
        await await_until(lambda: len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1)
        await asyncio.sleep(QUIET_WINDOW_S / 3)

        assert len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1
        assert Counter(message["tag_id"] for message in bad_values(trail)) == dict.fromkeys(
            READ_TAG_IDS, 1
        )


async def test_reconexoes_em_backoff_nao_reemitem_o_alarme(
    sim: OpcSimServer, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Conexão em `failed` atravessa vários ciclos de reconexão com um único `comm_failure`."""
    tentativas = 0
    build_client_real = connection_module.build_client

    def contando(*args, **kwargs):
        nonlocal tentativas
        tentativas += 1
        return build_client_real(*args, **kwargs)

    monkeypatch.setattr(connection_module, "build_client", contando)

    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_bus(redis_client, config.id) as trail:
        async with running(make_runtime(config, redis_client, snapshot)) as runtime:
            await await_until(lambda: runtime.state is ConnectionState.UP)
            await sim.stop()
            await await_until(lambda: len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1)
            conectadas_na_falha = tentativas
            await asyncio.sleep(QUIET_WINDOW_S)

            assert len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1
            assert tentativas - conectadas_na_falha >= 3, "backoff não tentou reconectar"
            assert runtime.state is ConnectionState.FAILED


async def test_heartbeat_segue_publicando_bad_durante_a_falha(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Depois da rajada, a conexão caída continua batendo `quality=2` (spec §2.2-6)."""
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = make_runtime(config, redis_client, snapshot, heartbeat_interval_s=FAST_HEARTBEAT_S)
    async with collect_bus(redis_client, config.id) as trail:
        async with running(runtime):
            await await_until(lambda: runtime.state is ConnectionState.UP)
            await sim.stop()
            await await_until(lambda: len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1)
            await await_until(lambda: len(bad_values(trail)) >= len(READ_TAG_IDS))
            apos_rajada = len(bad_values(trail))
            await await_until(lambda: len(bad_values(trail)) >= apos_rajada + len(READ_TAG_IDS))

            assert runtime.state is ConnectionState.FAILED
            batidas = Counter(message["tag_id"] for message in bad_values(trail)[apos_rajada:])
            assert set(batidas) == set(READ_TAG_IDS)


# --- restauração ---------------------------------------------------------------------


async def test_descongelar_restaura_so_depois_da_alternancia(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Com watchdog, a volta da sessão não basta: `comm_restored` espera o bit alternar."""
    config = make_config(sim.endpoint, with_watchdog=True)
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_bus(redis_client, config.id) as trail:
        async with running(make_runtime(config, redis_client, snapshot)) as runtime:
            await await_until(lambda: snapshot.watchdog_alive)
            await sim.set_freeze_watchdog(True)
            await await_until(lambda: events_of_kind(trail, KIND_COMM_FAILURE) != [])
            await sim.set_freeze_watchdog(False)

            await await_until(lambda: runtime.state is ConnectionState.UP)
            # Sessão de volta e ainda sem alternância: nada de restored neste instante.
            assert snapshot.watchdog_alive is False
            assert events_of_kind(trail, KIND_COMM_RESTORED) == []

            await await_until(lambda: len(events_of_kind(trail, KIND_COMM_RESTORED)) == 1)
            assert snapshot.watchdog_alive is True
            restaurado = events_of_kind(trail, KIND_COMM_RESTORED)[0]
            assert restaurado["severity"] == "info"
            assert restaurado["origin"] == f"conn:{config.id}"
            assert restaurado["payload"] == {
                "kind": KIND_COMM_RESTORED,
                "conn_id": config.id,
            }

            await asyncio.sleep(QUIET_WINDOW_S)
            assert len(events_of_kind(trail, KIND_COMM_RESTORED)) == 1


async def test_sem_watchdog_a_volta_da_sessao_restaura(redis_client: Redis) -> None:
    """Sem o par de node_ids não há alternância a esperar: sessão `up` restabelece."""
    porta = free_port()
    sim = OpcSimServer(port=porta)
    await sim.start()
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_bus(redis_client, config.id) as trail:
        async with running(make_runtime(config, redis_client, snapshot)) as runtime:
            await await_until(lambda: runtime.state is ConnectionState.UP)
            await sim.stop()
            await await_until(lambda: len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1)
            assert bad_tag_ids_before(trail, index_of_first(trail, KIND_COMM_FAILURE)) == set(
                READ_TAG_IDS
            )

            sim = OpcSimServer(port=porta)
            await sim.start()
            try:
                await await_until(lambda: len(events_of_kind(trail, KIND_COMM_RESTORED)) == 1)
                assert runtime.state is ConnectionState.UP
                await asyncio.sleep(QUIET_WINDOW_S)
                assert len(events_of_kind(trail, KIND_COMM_RESTORED)) == 1
            finally:
                await sim.stop()
