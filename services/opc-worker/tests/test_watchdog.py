"""Testes da task de watchdog do opc-worker (spec F2 §3.1-3.4, RF-206, ADR-009 revisado).

Tudo contra o opcsim in-process: o rung do simulador é o espelho do PLC (escreve
`NOT(from_system)` em `to_system` a cada scan), de modo que o handshake completo do
life-bit é exercitado, e não apenas metade dele. Watchdog é por FLOW (não mais por
conexão): o `ConnectionConfig` não carrega node_ids nenhum, quem descreve um watchdog é o
`FlowWatchdogConfig`, aplicado via `ConnectionRuntime.set_flow_watchdogs`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from asyncua import Client
from redis.asyncio import Redis
from worker_test_helpers import AWAIT_TIMEOUT_S, await_until

from opcsim import (
    NODE_WD_FROM_SYSTEM,
    NODE_WD_FROM_SYSTEM_2,
    NODE_WD_TO_SYSTEM,
    NODE_WD_TO_SYSTEM_2,
    OpcSimServer,
)
from ottima_opc_worker.connection import ConnectionRuntime
from ottima_opc_worker.state import (
    ConnectionConfig,
    ConnectionSnapshot,
    ConnectionState,
    FlowWatchdogConfig,
)
from ottima_opc_worker.watchdog import WatchdogTask

CONN_ID = 9
FLOW_ID = 501
POLL_INTERVAL_S = 0.01
MISSING_NODE = "ns=2;s=nao.existe"
# NodeId sintaticamente torto: nem chega a virar requisição, quebra no parse do client.
MALFORMED_NODE = "not-a-valid-nodeid"

# Período curto para o teste não arrastar; >= 100 ms para o rung (50 ms) reagir a tempo.
FAST_PERIOD_MS = 100
# Período do ensaio de congelamento: com limiar 1,0 s a detecção cai no 4º ciclo (1,2 s),
# dentro da janela [limiar, limiar + 2 períodos] e longe das duas bordas.
FREEZE_PERIOD_MS = 300
TEST_FREEZE_THRESHOLD_S = 1.0
# Janela para provar que algo NÃO acontece: três ciclos do watchdog.
QUIET_WINDOW_S = 3 * FAST_PERIOD_MS / 1000


async def await_bit(
    sim: OpcSimServer, node_id: str, expected: bool, timeout_s: float = AWAIT_TIMEOUT_S
) -> None:
    """Aguarda o bit assumir o valor esperado, lido no address space do próprio servidor."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if await sim.read(node_id) == expected:
            return
        await asyncio.sleep(POLL_INTERVAL_S)
    raise AssertionError(f"{node_id} não chegou a {expected} em {timeout_s}s")


async def await_flips(
    sim: OpcSimServer, node_id: str, count: int, timeout_s: float = AWAIT_TIMEOUT_S
) -> None:
    """Aguarda `count` inversões do bit, lidas no address space do próprio servidor."""
    previous = await sim.read(node_id)
    seen = 0
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        await asyncio.sleep(POLL_INTERVAL_S)
        current = await sim.read(node_id)
        if current != previous:
            previous = current
            seen += 1
            if seen >= count:
                return
    raise AssertionError(f"{node_id} não inverteu {count}x em {timeout_s}s")


async def assert_bit_stable(sim: OpcSimServer, node_id: str, window_s: float) -> None:
    """Prova que o bit NÃO muda durante a janela; polling fino pega qualquer ciclo vivo."""
    baseline = await sim.read(node_id)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + window_s
    while loop.time() < deadline:
        await asyncio.sleep(POLL_INTERVAL_S)
        assert await sim.read(node_id) == baseline, f"{node_id} mudou dentro da janela quieta"


def make_connection_config(endpoint: str) -> ConnectionConfig:
    """Conexão sem watchdog nenhum: o par de node_ids não mora mais aqui (ADR-009 revisado)."""
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
        tags=(),
    )


def make_watchdog_config(
    *,
    flow_id: int = FLOW_ID,
    read_node: str = NODE_WD_TO_SYSTEM,
    write_node: str = NODE_WD_FROM_SYSTEM,
    period_ms: int = FAST_PERIOD_MS,
) -> FlowWatchdogConfig:
    return FlowWatchdogConfig(
        flow_id=flow_id, read_node_id=read_node, write_node_id=write_node, period_ms=period_ms
    )


class Recorder:
    """Coletor dos três callbacks do watchdog, com o instante monotônico do 1º alarme."""

    def __init__(self) -> None:
        self.freezes: list[str] = []
        self.alives: list[float] = []
        self.hard_failures: list[str] = []
        self.first_freeze_at: float | None = None

    async def on_freeze(self, detail: str) -> None:
        if self.first_freeze_at is None:
            self.first_freeze_at = time.monotonic()
        self.freezes.append(detail)

    async def on_alive(self) -> None:
        self.alives.append(time.monotonic())

    async def on_hard_failure(self, detail: str) -> None:
        self.hard_failures.append(detail)


@asynccontextmanager
async def connected(sim: OpcSimServer) -> AsyncIterator[Client]:
    client = Client(sim.endpoint)
    await client.connect(auto_reconnect=False)
    try:
        yield client
    finally:
        await client.disconnect()


def make_watchdog(
    config: FlowWatchdogConfig,
    client: Client,
    snapshot: ConnectionSnapshot,
    recorder: Recorder,
    *,
    freeze_threshold_s: float = TEST_FREEZE_THRESHOLD_S,
) -> WatchdogTask:
    return WatchdogTask(
        config,
        client,
        snapshot,
        on_freeze=recorder.on_freeze,
        on_alive=recorder.on_alive,
        on_hard_failure=recorder.on_hard_failure,
        freeze_threshold_s=freeze_threshold_s,
    )


@asynccontextmanager
async def watchdog_running(
    sim: OpcSimServer,
    recorder: Recorder,
    *,
    period_ms: int = FAST_PERIOD_MS,
    read_node: str = NODE_WD_TO_SYSTEM,
    write_node: str = NODE_WD_FROM_SYSTEM,
    flow_id: int = FLOW_ID,
    freeze_threshold_s: float = TEST_FREEZE_THRESHOLD_S,
) -> AsyncIterator[ConnectionSnapshot]:
    """Watchdog vivo contra o opcsim, com o snapshot da conexão à disposição do teste."""
    config = make_watchdog_config(
        flow_id=flow_id, read_node=read_node, write_node=write_node, period_ms=period_ms
    )
    snapshot = ConnectionSnapshot(name="Forno 1")
    async with connected(sim) as client:
        task = make_watchdog(
            config, client, snapshot, recorder, freeze_threshold_s=freeze_threshold_s
        )
        await task.start()
        try:
            yield snapshot
        finally:
            await task.stop()


# --- limiar de produção ------------------------------------------------------------


def test_limiar_de_congelamento_default_em_dez_segundos() -> None:
    """RF-206 revisado: 10 s é o DEFAULT por flow (`timeout_s`); injeção só em teste."""
    cfg = FlowWatchdogConfig(flow_id=1, read_node_id="a", write_node_id="b", period_ms=1500)
    assert cfg.timeout_s == 10.0


# --- ciclo do watchdog contra o rung do opcsim -------------------------------------


async def test_alternancia_do_rung_arma_flow_watchdog_alive(sim: OpcSimServer) -> None:
    """Rung alternando ⇒ `flow_watchdog_alive[flow_id]` vira True e `on_alive` roda 1x."""
    recorder = Recorder()
    async with watchdog_running(sim, recorder) as snapshot:
        await await_until(lambda: snapshot.flow_watchdog_alive.get(FLOW_ID))
        # Muitas alternâncias depois, o gancho continua com uma chamada só: é edge-trigger
        # da (re)conexão, não pulso por ciclo.
        await await_flips(sim, NODE_WD_TO_SYSTEM, 6)
        assert snapshot.flow_watchdog_alive[FLOW_ID] is True

    assert len(recorder.alives) == 1
    assert recorder.freezes == []
    assert recorder.hard_failures == []


async def test_escreve_o_mesmo_valor_lido_copia_pura(sim: OpcSimServer) -> None:
    """O bit escrito é sempre uma CÓPIA do último bit lido: quem inverte é o PLC do outro
    lado, o ottima não (ADR-009 revisado, handshake da spec §3.1)."""
    # Com o rung congelado o teste governa `to_system` sozinho: a escrita do watchdog fica
    # determinística, sem corrida com a inversão do simulador.
    await sim.set_freeze_watchdog(True)
    await sim.write(NODE_WD_TO_SYSTEM, True)
    recorder = Recorder()
    async with watchdog_running(sim, recorder, freeze_threshold_s=AWAIT_TIMEOUT_S):
        await await_bit(sim, NODE_WD_FROM_SYSTEM, True)
        await sim.write(NODE_WD_TO_SYSTEM, False)
        await await_bit(sim, NODE_WD_FROM_SYSTEM, False)

    assert recorder.freezes == []
    assert recorder.hard_failures == []


async def test_congelamento_dispara_on_freeze_na_janela_do_limiar(sim: OpcSimServer) -> None:
    """Rung congelado ⇒ `on_freeze` entre o limiar e o limiar + 2 períodos, uma vez só."""
    period_s = FREEZE_PERIOD_MS / 1000
    recorder = Recorder()
    async with watchdog_running(sim, recorder, period_ms=FREEZE_PERIOD_MS) as snapshot:
        await await_until(lambda: snapshot.flow_watchdog_alive.get(FLOW_ID))
        # Congelar logo depois de uma inversão alinha o instante de referência do Δt com a
        # última transição que o watchdog ainda consegue observar.
        await await_flips(sim, NODE_WD_TO_SYSTEM, 1)
        frozen_at = time.monotonic()
        await sim.set_freeze_watchdog(True)

        await await_until(
            lambda: bool(recorder.freezes), timeout_s=TEST_FREEZE_THRESHOLD_S + 4 * period_s
        )
        elapsed = recorder.first_freeze_at - frozen_at
        assert TEST_FREEZE_THRESHOLD_S <= elapsed <= TEST_FREEZE_THRESHOLD_S + 2 * period_s

        # A task encerra na 1ª detecção: quem alarma de novo é a próxima sessão.
        await asyncio.sleep(3 * period_s)
        assert len(recorder.freezes) == 1

    assert recorder.hard_failures == []


async def test_nao_falha_antes_do_limiar(sim: OpcSimServer) -> None:
    """Congelamento mais curto que o limiar não alarma: o watchdog não é um gatilho nervoso."""
    recorder = Recorder()
    async with watchdog_running(sim, recorder) as snapshot:
        await await_until(lambda: snapshot.flow_watchdog_alive.get(FLOW_ID))
        await sim.set_freeze_watchdog(True)
        await asyncio.sleep(0.3)

        assert recorder.freezes == []
        assert recorder.hard_failures == []


async def test_read_invalido_e_falha_dura_imediata(sim: OpcSimServer) -> None:
    """Exceção no read ⇒ `on_hard_failure` imediato, sem retry interno e sem congelamento."""
    recorder = Recorder()
    async with watchdog_running(sim, recorder, read_node=MISSING_NODE):
        # Antes do limiar de congelamento (1 s): é falha dura de sessão, não timeout.
        await await_until(lambda: bool(recorder.hard_failures), timeout_s=0.9)
        await asyncio.sleep(QUIET_WINDOW_S)

    assert len(recorder.hard_failures) == 1
    assert recorder.hard_failures[0]
    assert recorder.freezes == []
    assert recorder.alives == []


async def test_write_invalido_e_falha_dura_imediata(sim: OpcSimServer) -> None:
    """Exceção no write do watchdog tem o mesmo tratamento do read: falha dura imediata."""
    recorder = Recorder()
    async with watchdog_running(sim, recorder, write_node=MISSING_NODE):
        await await_until(lambda: bool(recorder.hard_failures), timeout_s=0.9)
        await asyncio.sleep(QUIET_WINDOW_S)

    assert len(recorder.hard_failures) == 1
    assert recorder.hard_failures[0]
    assert recorder.freezes == []


async def test_read_com_node_id_malformado_avisa_em_vez_de_matar_a_task(
    sim: OpcSimServer,
) -> None:
    """NodeId inválido falha já no parse: tem de virar `on_hard_failure`, não task morta.

    Watchdog que morre calado deixa `flow_watchdog_alive` congelado e o gate de escrita
    (2.3) decidindo por um valor que nunca mais muda (ADR-009).
    """
    recorder = Recorder()
    async with watchdog_running(sim, recorder, read_node=MALFORMED_NODE):
        await await_until(lambda: bool(recorder.hard_failures), timeout_s=0.9)
        await asyncio.sleep(QUIET_WINDOW_S)

    assert len(recorder.hard_failures) == 1
    # O node_id torto vai no detalhe: é o que permite achar a configuração errada.
    assert MALFORMED_NODE in recorder.hard_failures[0]
    assert recorder.freezes == []
    assert recorder.alives == []


async def test_write_com_node_id_malformado_avisa_em_vez_de_matar_a_task(
    sim: OpcSimServer,
) -> None:
    """Mesmo tratamento quando quem está torto é o node de escrita."""
    recorder = Recorder()
    async with watchdog_running(sim, recorder, write_node=MALFORMED_NODE):
        await await_until(lambda: bool(recorder.hard_failures), timeout_s=0.9)
        await asyncio.sleep(QUIET_WINDOW_S)

    assert len(recorder.hard_failures) == 1
    assert MALFORMED_NODE in recorder.hard_failures[0]
    assert recorder.freezes == []
    assert recorder.alives == []


async def test_stop_e_idempotente_e_cala_o_ciclo(sim: OpcSimServer) -> None:
    """Depois de `stop()` não há mais escrita nem callback; chamar de novo é no-op."""
    watchdog_config = make_watchdog_config()
    snapshot = ConnectionSnapshot(name="Forno 1")
    recorder = Recorder()
    async with connected(sim) as client:
        task = make_watchdog(watchdog_config, client, snapshot, recorder)
        await task.start()
        await await_until(lambda: snapshot.flow_watchdog_alive.get(FLOW_ID))
        await task.stop()
        await task.stop()

        alives = len(recorder.alives)
        # O cancelamento pode pegar uma escrita já despachada: o servidor ainda a aplica,
        # e um ciclo de folga separa esse resíduo de um laço que continuasse vivo.
        await asyncio.sleep(FAST_PERIOD_MS / 1000)
        await assert_bit_stable(sim, NODE_WD_FROM_SYSTEM, QUIET_WINDOW_S)

        assert len(recorder.alives) == alives
        assert recorder.freezes == []
        assert recorder.hard_failures == []


# --- integração com o runtime da conexão -------------------------------------------


async def test_conexao_sem_flow_watchdog_nao_cria_task(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Sem nenhum `set_flow_watchdogs`, a conexão sobe read-only de fato (spec §3.5)."""
    config = make_connection_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = ConnectionRuntime(config, redis_client, snapshot)
    await runtime.start()
    try:
        await await_until(lambda: runtime.state is ConnectionState.UP)
        await asyncio.sleep(QUIET_WINDOW_S)

        assert runtime.flow_watchdogs == {}
        assert snapshot.flow_watchdog_alive == {}
    finally:
        await runtime.stop()


async def test_runtime_falha_e_so_rearma_com_reconfiguracao(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Ciclo completo do flow: alive ⇒ congelou ⇒ `watchdog_dead`. A task encerra sozinha
    na 1ª detecção (comentário de `watchdog.py`) e NÃO se autocura só porque o bit voltou
    a alternar — isolada por flow (ADR-009 revisado), congelar não derruba a sessão nem
    reinicia a task sozinha; só uma reconfiguração de verdade via `set_flow_watchdogs`
    (o que o supervisor faz quando o flow é reeditado) a traz de volta."""
    config = make_connection_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = ConnectionRuntime(
        config,
        redis_client,
        snapshot,
        backoff_initial_s=0.1,
        backoff_max_s=0.2,
        watchdog_freeze_threshold_s=TEST_FREEZE_THRESHOLD_S,
    )
    await runtime.set_flow_watchdogs({FLOW_ID: make_watchdog_config()})
    await runtime.start()
    try:
        await await_until(lambda: snapshot.flow_watchdog_alive.get(FLOW_ID))
        assert FLOW_ID in runtime.flow_watchdogs

        await sim.set_freeze_watchdog(True)
        await await_until(
            lambda: snapshot.flow_watchdog_alive.get(FLOW_ID) is False,
            timeout_s=TEST_FREEZE_THRESHOLD_S + 5,
        )
        assert runtime.state is ConnectionState.UP, "watchdog de flow não derruba a sessão"

        await sim.set_freeze_watchdog(False)
        await asyncio.sleep(QUIET_WINDOW_S)
        assert snapshot.flow_watchdog_alive.get(FLOW_ID) is False, (
            "o bit voltou a alternar sozinho, mas a task já tinha encerrado"
        )

        # Reconfiguração de verdade: reconcilia como o supervisor faria num flow reeditado.
        await runtime.set_flow_watchdogs(
            {FLOW_ID: make_watchdog_config(period_ms=FAST_PERIOD_MS + 1)}
        )
        await await_until(lambda: snapshot.flow_watchdog_alive.get(FLOW_ID) is True)
    finally:
        await runtime.stop()


async def test_dois_flow_watchdogs_na_mesma_conexao_sao_isolados(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Dois flows com watchdog na MESMA conexão: um congela, o outro segue vivo.

    Impossível de expressar no modelo antigo (watchdog por conexão): o isolamento por
    flow (ADR-009 revisado) é exatamente o que viabiliza este caso — uma conexão-gateway
    com vários PLCs atrás dela não pode arrastar todos os flows quando só um deles trava.
    """
    config = make_connection_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = ConnectionRuntime(
        config, redis_client, snapshot, watchdog_freeze_threshold_s=TEST_FREEZE_THRESHOLD_S
    )
    flow_a = make_watchdog_config(
        flow_id=1, read_node=NODE_WD_TO_SYSTEM, write_node=NODE_WD_FROM_SYSTEM
    )
    flow_b = make_watchdog_config(
        flow_id=2, read_node=NODE_WD_TO_SYSTEM_2, write_node=NODE_WD_FROM_SYSTEM_2
    )
    await runtime.set_flow_watchdogs({1: flow_a, 2: flow_b})
    await runtime.start()
    try:
        await await_until(
            lambda: snapshot.flow_watchdog_alive.get(1) and snapshot.flow_watchdog_alive.get(2)
        )

        await sim.set_freeze_watchdog(True, pair=1)
        await await_until(lambda: snapshot.flow_watchdog_alive.get(1) is False)

        # O flow 2 nunca para: nem a alternância dele, nem a sessão, nem os dois flows.
        await await_flips(sim, NODE_WD_TO_SYSTEM_2, 3)
        assert snapshot.flow_watchdog_alive.get(2) is True
        assert runtime.state is ConnectionState.UP
        assert set(runtime.flow_watchdogs) == {1, 2}
    finally:
        await runtime.stop()


async def test_dois_flows_no_mesmo_par_de_nos_nao_se_congelam(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Dois flows apontados ao MESMO par de nós continuam vivos (achado do gate E2E).

    Cada watchdog copia `to_system` para `from_system` na sua cadência; com dois copiadores
    defasados o bit alterna 2× por período, e uma leitura por período veria sempre o MESMO
    valor (aliasing) e acusaria congelamento de um handshake vivo. A leitura é
    sobreamostrada justamente para isso — o par compartilhado é topologia degenerada (em
    planta cada flow tem o seu par), mas não pode virar `watchdog_dead` fantasma.
    """
    config = make_connection_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = ConnectionRuntime(
        config, redis_client, snapshot, watchdog_freeze_threshold_s=TEST_FREEZE_THRESHOLD_S
    )
    par = {"read_node": NODE_WD_TO_SYSTEM, "write_node": NODE_WD_FROM_SYSTEM}
    await runtime.set_flow_watchdogs(
        {
            1: make_watchdog_config(flow_id=1, **par),
            2: make_watchdog_config(flow_id=2, **par),
        }
    )
    await runtime.start()
    try:
        await await_until(
            lambda: snapshot.flow_watchdog_alive.get(1) and snapshot.flow_watchdog_alive.get(2)
        )
        # Passada a janela do limiar, nenhum dos dois pode ter caído por falso congelamento.
        await asyncio.sleep(TEST_FREEZE_THRESHOLD_S * 1.5)
        assert snapshot.flow_watchdog_alive.get(1) is True
        assert snapshot.flow_watchdog_alive.get(2) is True
        assert runtime.state is ConnectionState.UP
    finally:
        await runtime.stop()
