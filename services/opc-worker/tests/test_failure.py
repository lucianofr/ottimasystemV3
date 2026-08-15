"""Testes da integração de falha do opc-worker (RF-207, spec F2 §2.2-6, §3.6, §3.8).

Tudo roda contra o opcsim in-process (nunca contra PLC real) e contra o Redis real da
fixture da raiz. O assinante é UM só para os dois canais (`events` e
`opc.values.<conn_id>`): a ordem relativa entre a rajada de `quality=2` e o alarme é
contrato da spec e só se prova observando os dois no mesmo fluxo de entrega.

Watchdog é por FLOW (ADR-009 revisado): `ConnectionConfig` não carrega node_ids, quem
descreve um watchdog é o `FlowWatchdogConfig`, aplicado via `set_flow_watchdogs`.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import pytest
from redis.asyncio import Redis
from worker_test_helpers import await_until

from opcsim import (
    NODE_COUNTER,
    NODE_SINE,
    NODE_STATIC,
    NODE_W_ONLY,
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
from ottima_opc_worker.polling import QUALITY_BAD
from ottima_opc_worker.state import (
    ConnectionConfig,
    ConnectionSnapshot,
    ConnectionState,
    FlowWatchdogConfig,
    TagConfig,
)

CONN_ID = 11
FLOW_ID = 601

# O rung do opcsim espelha `NOT(from_system)` incondicionalmente a cada 50 ms: qualquer
# período do watchdog funciona (não há mais reação a mudança para sincronizar).
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

# Janela para provar que algo NÃO acontece (vários ciclos de reconexão em backoff).
QUIET_WINDOW_S = 1.5
# Período longo de propósito no ensaio da tentativa superada: alarga a janela em que uma
# task de watchdog órfã ainda estaria viva antes de morrer sozinha no primeiro read contra
# o cliente já desconectado. Sem isso a asserção viraria uma corrida.
SLOW_PERIOD_MS = 1000

TAG_SINE = TagConfig(
    id=101, name="Temperatura", node_id=NODE_SINE, direction="r", data_type="float"
)
TAG_COUNTER = TagConfig(id=102, name="Ciclos", node_id=NODE_COUNTER, direction="r", data_type="int")
TAG_STATIC = TagConfig(
    id=103, name="Nível fixo", node_id=NODE_STATIC, direction="r", data_type="float"
)
# Contraexemplo da rajada: tag SEM série. Precisa ser write-only (comando que o servidor
# declara ilegível), não uma tag `w` qualquer — desde que o worker assina todo node legível,
# uma tag `w` sobre node legível TEM série e entra na rajada como qualquer outra. Com
# `NODE_W_FLOAT` aqui o ensaio viraria corrida: a rajada incluiria a tag ou não, conforme a
# primeira notificação dela ter chegado antes da queda.
TAG_WRITE_ONLY = TagConfig(
    id=104, name="Comando cego", node_id=NODE_W_ONLY, direction="w", data_type="float"
)
TAGS = (TAG_SINE, TAG_COUNTER, TAG_STATIC, TAG_WRITE_ONLY)
SERIES_TAG_IDS = frozenset({TAG_SINE.id, TAG_COUNTER.id, TAG_STATIC.id})

BusTrail = list[tuple[str, dict]]


def make_config(endpoint: str) -> ConnectionConfig:
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
        tags=TAGS,
    )


def make_watchdog(
    *, flow_id: int = FLOW_ID, period_ms: int = WATCHDOG_PERIOD_MS
) -> FlowWatchdogConfig:
    return FlowWatchdogConfig(
        flow_id=flow_id,
        read_node_id=NODE_WD_TO_SYSTEM,
        write_node_id=NODE_WD_FROM_SYSTEM,
        period_ms=period_ms,
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


def watchdog_tasks(flow_id: int) -> list[asyncio.Task]:
    """Tasks de watchdog vivas, achadas pelo nome que `WatchdogTask.start()` dá a elas."""
    nome = f"opc-watchdog-flow-{flow_id}"
    return [task for task in asyncio.all_tasks() if task.get_name() == nome and not task.done()]


async def assert_bit_estavel(sim: OpcSimServer, node_id: str, janela_s: float) -> None:
    """Prova que ninguém mais escreve no rung: o bit lido não muda durante a janela."""
    baseline = await sim.read(node_id)
    loop = asyncio.get_running_loop()
    limite = loop.time() + janela_s
    while loop.time() < limite:
        await asyncio.sleep(0.02)
        assert await sim.read(node_id) == baseline, f"{node_id} mudou: sobrou quem escreve nele"


@asynccontextmanager
async def running(
    runtime: ConnectionRuntime, *, watchdog: FlowWatchdogConfig | None = None
) -> AsyncIterator[ConnectionRuntime]:
    if watchdog is not None:
        await runtime.set_flow_watchdogs({watchdog.flow_id: watchdog})
    await runtime.start()
    try:
        yield runtime
    finally:
        await runtime.stop()


# --- transição de falha: alarme e rajada bad ---------------------------------------


async def test_congelamento_de_flow_alarma_sem_afetar_sessao_ou_tags(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Rung congelado ⇒ 1 alarme `watchdog_timeout` (payload com `flow_id`), isolado do
    flow: a sessão continua `up` e as tags `r` continuam publicando bem (ADR-009
    revisado — quem deriva a sessão é falha de sessão, não de watchdog de um flow)."""
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    watchdog = make_watchdog()
    async with collect_bus(redis_client, config.id) as trail:
        async with running(
            make_runtime(config, redis_client, snapshot), watchdog=watchdog
        ) as runtime:
            await await_until(lambda: snapshot.flow_watchdog_alive.get(FLOW_ID))
            await sim.set_freeze_watchdog(True)
            await await_until(lambda: len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1)

            alarme = events_of_kind(trail, KIND_COMM_FAILURE)[0]
            assert alarme["severity"] == "alarm"
            assert alarme["origin"] == f"conn:{config.id}"
            assert alarme["payload"]["kind"] == KIND_COMM_FAILURE
            assert alarme["payload"]["conn_id"] == config.id
            assert alarme["payload"]["flow_id"] == FLOW_ID
            assert alarme["payload"]["reason"] == "watchdog_timeout"
            assert alarme["payload"]["detail"]
            # Isolado por flow: nem a sessão cai, nem as tags de leitura viram bad.
            assert runtime.state is ConnectionState.UP
            assert snapshot.flow_watchdog_alive[FLOW_ID] is False
            assert snapshot.session_up_since is not None
            await asyncio.sleep(QUIET_WINDOW_S)
            assert bad_values(trail) == [], "watchdog de flow não é falha de sessão"


async def test_delta_da_deteccao_ao_alarme_e_proporcional_ao_limiar(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Detecção → evento sem espera intermediária: prova em escala do aceite <12 s (§3.8)."""
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    watchdog = make_watchdog()
    periodo_s = WATCHDOG_PERIOD_MS / 1000
    async with collect_bus(redis_client, config.id) as trail:
        async with running(make_runtime(config, redis_client, snapshot), watchdog=watchdog):
            await await_until(lambda: snapshot.flow_watchdog_alive.get(FLOW_ID))
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
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    watchdog = make_watchdog()
    async with collect_bus(redis_client, config.id) as trail:
        async with running(make_runtime(config, redis_client, snapshot), watchdog=watchdog):
            await await_until(lambda: snapshot.flow_watchdog_alive.get(FLOW_ID))
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
    assert bad_tag_ids_before(trail, posicao) == set(SERIES_TAG_IDS)


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
        await await_until(lambda: len(bad_values(trail)) == len(SERIES_TAG_IDS))
        await await_until(lambda: len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1)
        await asyncio.sleep(QUIET_WINDOW_S / 3)

        assert len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1
        assert Counter(message["tag_id"] for message in bad_values(trail)) == dict.fromkeys(
            SERIES_TAG_IDS, 1
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
            await await_until(lambda: len(bad_values(trail)) >= len(SERIES_TAG_IDS))
            apos_rajada = len(bad_values(trail))
            await await_until(lambda: len(bad_values(trail)) >= apos_rajada + len(SERIES_TAG_IDS))

            assert runtime.state is ConnectionState.FAILED
            batidas = Counter(message["tag_id"] for message in bad_values(trail)[apos_rajada:])
            assert set(batidas) == set(SERIES_TAG_IDS)


@pytest.mark.parametrize("falha_antes_do_watchdog", [True, False])
async def test_tentativa_superada_nao_deixa_watchdog_orfao(
    sim: OpcSimServer,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
    falha_antes_do_watchdog: bool,
) -> None:
    """`fail()` concorrente durante `on_session_up` não pode deixar task viva sem dono.

    Os dois momentos importam e vazam por caminhos distintos: com `fail()` ANTES de o
    watchdog nascer, o `_close_session()` dele já correu e a limpeza só pode vir da saída
    de `_open_session`; DEPOIS, a sessão nunca chegou a `up`, e a guarda de `_session_open`
    impede o gancho de saída de rodar. Nos dois, a próxima tentativa sobrescreveria
    `_flow_watchdogs` sem parar o anterior.
    """
    start_flow_watchdog_real = ConnectionRuntime._start_flow_watchdog
    open_session_real = ConnectionRuntime._open_session
    forcado = False
    tentativas_encerradas = 0

    async def start_flow_watchdog_com_fail(runtime_self, client, config):
        nonlocal forcado
        if forcado:
            await start_flow_watchdog_real(runtime_self, client, config)
            return
        forcado = True
        if falha_antes_do_watchdog:
            await runtime_self.fail("session_lost", "corrida forçada no teste")
            await start_flow_watchdog_real(runtime_self, client, config)
        else:
            await start_flow_watchdog_real(runtime_self, client, config)
            await runtime_self.fail("session_lost", "corrida forçada no teste")

    async def open_session_contado(runtime_self):
        nonlocal tentativas_encerradas
        try:
            await open_session_real(runtime_self)
        finally:
            tentativas_encerradas += 1

    monkeypatch.setattr(ConnectionRuntime, "_start_flow_watchdog", start_flow_watchdog_com_fail)
    monkeypatch.setattr(ConnectionRuntime, "_open_session", open_session_contado)
    # Sem reconexão dentro do ensaio: um watchdog novo e legítimo confundiria a contagem.
    monkeypatch.setattr(connection_module, "backoff_delay", lambda *args, **kwargs: 60.0)

    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    watchdog = make_watchdog(period_ms=SLOW_PERIOD_MS)
    async with collect_bus(redis_client, config.id) as trail:
        async with running(
            make_runtime(config, redis_client, snapshot), watchdog=watchdog
        ) as runtime:
            await await_until(lambda: len(events_of_kind(trail, KIND_COMM_FAILURE)) == 1)
            # Marcador determinístico: a tentativa superada já desenrolou por completo.
            await await_until(lambda: tentativas_encerradas >= 1)

            assert forcado, "a corrida não foi forçada: o ensaio não provaria nada"
            assert runtime.state is ConnectionState.FAILED
            assert watchdog_tasks(FLOW_ID) == [], "sobrou task de watchdog órfã"
            assert runtime.flow_watchdogs == {}
            assert runtime.poller is None
            # Sem ninguém escrevendo em `from_system`, o rung do opcsim para de alternar.
            await assert_bit_estavel(sim, NODE_WD_FROM_SYSTEM, SLOW_PERIOD_MS / 1000 * 1.5)


# --- restauração ---------------------------------------------------------------------


async def test_flow_so_restaura_depois_de_alternar_apos_a_sessao_voltar(
    redis_client: Redis,
) -> None:
    """Um flow que já congelou o watchdog e teve a task encerrada (isolado da sessão,
    ADR-009 revisado) só ganha uma task nova quando a SESSÃO reconecta — `on_session_down`
    seguido de `on_session_up` reconcilia do zero, preservando a falha pendente do flow —
    e o `comm_restored` dele (payload com `flow_id`) só sai depois do bit voltar a
    alternar de fato, não no instante em que a sessão sobe."""
    port = free_port()
    sim = OpcSimServer(port=port)
    await sim.start()
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    watchdog = make_watchdog()
    async with collect_bus(redis_client, config.id) as trail:
        async with running(
            make_runtime(config, redis_client, snapshot), watchdog=watchdog
        ) as runtime:
            await await_until(lambda: snapshot.flow_watchdog_alive.get(FLOW_ID))
            await sim.set_freeze_watchdog(True)
            await await_until(
                lambda: any(
                    "flow_id" in e["payload"] for e in events_of_kind(trail, KIND_COMM_FAILURE)
                )
            )
            assert snapshot.flow_watchdog_alive[FLOW_ID] is False

            await sim.stop()
            await await_until(lambda: runtime.state is ConnectionState.FAILED)

            sim = OpcSimServer(port=port)
            await sim.start()
            try:
                await await_until(lambda: runtime.state is ConnectionState.UP)
                assert snapshot.flow_watchdog_alive.get(FLOW_ID) is False, (
                    "sessão voltou, mas o flow ainda não alternou"
                )

                await await_until(
                    lambda: any(
                        "flow_id" in e["payload"] for e in events_of_kind(trail, KIND_COMM_RESTORED)
                    )
                )
                restaurado = next(
                    e
                    for e in events_of_kind(trail, KIND_COMM_RESTORED)
                    if "flow_id" in e["payload"]
                )
                assert restaurado["severity"] == "info"
                assert restaurado["origin"] == f"conn:{config.id}"
                assert restaurado["payload"] == {
                    "kind": KIND_COMM_RESTORED,
                    "conn_id": config.id,
                    "flow_id": FLOW_ID,
                }
                assert snapshot.flow_watchdog_alive[FLOW_ID] is True

                await asyncio.sleep(QUIET_WINDOW_S)
                restaurados = [
                    e
                    for e in events_of_kind(trail, KIND_COMM_RESTORED)
                    if "flow_id" in e["payload"]
                ]
                assert len(restaurados) == 1
            finally:
                await sim.stop()


async def test_sem_watchdog_a_volta_da_sessao_restaura(redis_client: Redis) -> None:
    """Sem nenhum flow com watchdog nesta conexão, sessão `up` restabelece na hora."""
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
                SERIES_TAG_IDS
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
