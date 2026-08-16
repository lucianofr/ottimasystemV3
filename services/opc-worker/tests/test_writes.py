"""Testes do consumidor de `opc.writes` (spec F2 §3.4/3.5/§4, RF-205/207).

Tudo contra o opcsim in-process e o Redis real da fixture da raiz: os espelhos R do
simulador são a prova de que a escrita chegou ao servidor, e o canal `events` é a prova
da auditoria.

Watchdog é por FLOW (ADR-009 revisado): `ConnectionConfig` não carrega node_ids, e o gate
de escrita olha `write.flow_id` em `runtime.snapshot.flow_watchdog_alive`, não mais um
booleano único por conexão.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from asyncua import ua
from asyncua.common.node import Node
from redis.asyncio import Redis
from worker_test_helpers import AWAIT_TIMEOUT_S, await_until, collecting

from opcsim import (
    NODE_MIRROR_BOOL,
    NODE_MIRROR_FLOAT,
    NODE_MIRROR_INT,
    NODE_SINE,
    NODE_W_BOOL,
    NODE_W_FLOAT,
    NODE_W_INT,
    NODE_WD_FROM_SYSTEM,
    NODE_WD_FROM_SYSTEM_2,
    NODE_WD_TO_SYSTEM,
    NODE_WD_TO_SYSTEM_2,
    OpcSimServer,
    free_port,
)
from ottima_core.bus import (
    CHANNEL_EVENTS,
    CHANNEL_OPC_WRITES,
    KIND_OPC_WRITE,
    KIND_WRITE_BLOCKED,
    KIND_WRITE_REJECTED,
    OpcWrite,
)
from ottima_opc_worker.connection import ConnectionRuntime
from ottima_opc_worker.state import (
    ConnectionConfig,
    ConnectionSnapshot,
    ConnectionState,
    FlowWatchdogConfig,
    TagConfig,
)
from ottima_opc_worker.writes import WriteConsumer, coerce_value

CONN_ID = 7
FLOW_ID = 3
TAG_FLOAT = 11
TAG_INT = 12
TAG_BOOL = 13
TAG_READONLY = 14

# Backoff e watchdog curtos: o teste não pode esperar a cadência de produção.
TEST_BACKOFF_INITIAL_S = 0.05
TEST_BACKOFF_MAX_S = 0.2
TEST_WATCHDOG_PERIOD_MS = 100
TEST_FREEZE_THRESHOLD_S = 0.5
# Janela para provar que algo NÃO acontece.
QUIET_WINDOW_S = 1.0

TAGS: tuple[TagConfig, ...] = (
    TagConfig(
        id=TAG_FLOAT, name="SP Vazão", node_id=NODE_W_FLOAT, direction="w", data_type="float"
    ),
    TagConfig(id=TAG_INT, name="SP Passo", node_id=NODE_W_INT, direction="w", data_type="int"),
    TagConfig(id=TAG_BOOL, name="Liga Bomba", node_id=NODE_W_BOOL, direction="w", data_type="bool"),
    TagConfig(
        id=TAG_READONLY, name="Leitura", node_id=NODE_W_FLOAT, direction="r", data_type="float"
    ),
)


def make_config(
    endpoint: str,
    *,
    conn_id: int = CONN_ID,
    tags: tuple[TagConfig, ...] = TAGS,
) -> ConnectionConfig:
    return ConnectionConfig(
        id=conn_id,
        project_id=1,
        name="Forno 1",
        endpoint=endpoint,
        security_policy="none",
        security_mode="none",
        auth_mode="anonymous",
        auth_username=None,
        auth_password_enc=None,
        server_cert_file=None,
        tags=tags,
    )


def make_watchdog(
    *,
    flow_id: int = FLOW_ID,
    read_node: str = NODE_WD_TO_SYSTEM,
    write_node: str = NODE_WD_FROM_SYSTEM,
    period_ms: int = TEST_WATCHDOG_PERIOD_MS,
) -> FlowWatchdogConfig:
    return FlowWatchdogConfig(
        flow_id=flow_id, read_node_id=read_node, write_node_id=write_node, period_ms=period_ms
    )


class Bancada:
    """Runtime de conexão e consumidor ligados ao mesmo mapping vivo de runtimes."""

    def __init__(self, runtime: ConnectionRuntime, consumer: WriteConsumer) -> None:
        self.runtime = runtime
        self.consumer = consumer
        self.snapshot = runtime.snapshot

    async def gate_aberto(self, flow_id: int = FLOW_ID) -> None:
        await await_until(
            lambda: (
                self.runtime.state is ConnectionState.UP
                and self.snapshot.flow_watchdog_alive.get(flow_id, False)
            )
        )


@asynccontextmanager
async def bancada(
    redis_client: Redis,
    sim: OpcSimServer,
    *,
    with_watchdog: bool = True,
    tags: tuple[TagConfig, ...] = TAGS,
    conn_id: int = CONN_ID,
    flow_id: int = FLOW_ID,
    freeze_threshold_s: float = TEST_FREEZE_THRESHOLD_S,
) -> AsyncIterator[Bancada]:
    config = make_config(sim.endpoint, conn_id=conn_id, tags=tags)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = ConnectionRuntime(
        config,
        redis_client,
        snapshot,
        backoff_initial_s=TEST_BACKOFF_INITIAL_S,
        backoff_max_s=TEST_BACKOFF_MAX_S,
        watchdog_freeze_threshold_s=freeze_threshold_s,
    )
    if with_watchdog:
        await runtime.set_flow_watchdogs({flow_id: make_watchdog(flow_id=flow_id)})
    consumer = WriteConsumer(redis_client, {conn_id: runtime})
    await runtime.start()
    await consumer.start()
    try:
        yield Bancada(runtime, consumer)
    finally:
        await consumer.stop()
        await runtime.stop()


async def publicar(
    redis_client: Redis,
    *,
    tag_id: int,
    value: float,
    conn_id: int = CONN_ID,
    flow_id: int = FLOW_ID,
    source: str = "flow:3/block:opcw1",
) -> None:
    write = OpcWrite(
        conn_id=conn_id,
        tag_id=tag_id,
        flow_id=flow_id,
        value=value,
        source=source,
        ts=datetime.now(UTC),
    )
    await redis_client.publish(CHANNEL_OPC_WRITES, write.model_dump_json())


async def esperar_valor(sim: OpcSimServer, node_id: str, esperado: Any) -> None:
    """Espera o node do simulador valer `esperado`; a leitura é server-side, sem cliente."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + AWAIT_TIMEOUT_S
    atual: Any = None
    while loop.time() < deadline:
        atual = await sim.read(node_id)
        if atual == esperado:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"{node_id} ficou em {atual!r}, esperado {esperado!r}")


def of_kind(events: list[dict], kind: str) -> list[dict]:
    return [event for event in events if event["payload"]["kind"] == kind]


async def test_escrita_ok_chega_ao_servidor_e_gera_evento_info(redis_client: Redis, sim):
    async with bancada(redis_client, sim) as banca, collecting(redis_client, CHANNEL_EVENTS) as ev:
        await banca.gate_aberto()

        await publicar(redis_client, tag_id=TAG_FLOAT, value=61.5)

        await await_until(lambda: len(of_kind(ev, KIND_OPC_WRITE)) == 1)
        await esperar_valor(sim, NODE_MIRROR_FLOAT, 61.5)
        evento = of_kind(ev, KIND_OPC_WRITE)[0]
        assert evento["severity"] == "info"
        assert evento["origin"] == "flow:3/block:opcw1", "origin é o source verbatim (§4.4)"
        assert evento["payload"]["status"] == "ok"
        assert evento["payload"]["conn_id"] == CONN_ID
        assert evento["payload"]["tag_id"] == TAG_FLOAT
        assert evento["payload"]["value"] == pytest.approx(61.5)


async def test_coercao_usa_o_datatype_real_do_servidor(redis_client: Redis, sim):
    async with bancada(redis_client, sim) as banca, collecting(redis_client, CHANNEL_EVENTS) as ev:
        await banca.gate_aberto()

        await publicar(redis_client, tag_id=TAG_INT, value=7.9)
        await publicar(redis_client, tag_id=TAG_BOOL, value=2.5)

        await await_until(lambda: len(of_kind(ev, KIND_OPC_WRITE)) == 2)
        assert all(e["payload"]["status"] == "ok" for e in of_kind(ev, KIND_OPC_WRITE)), (
            "Int64 num node Int32 daria BadTypeMismatch"
        )
        await esperar_valor(sim, NODE_MIRROR_INT, 8)
        await esperar_valor(sim, NODE_MIRROR_BOOL, True)

        await publicar(redis_client, tag_id=TAG_BOOL, value=0.0)
        await esperar_valor(sim, NODE_MIRROR_BOOL, False)


async def test_datatype_e_lido_uma_vez_por_sessao(redis_client: Redis, sim, monkeypatch):
    original = Node.read_data_type_as_variant_type
    lidos: list[str] = []

    async def contando(self: Node) -> ua.VariantType:
        lidos.append(self.nodeid.to_string())
        return await original(self)

    monkeypatch.setattr(Node, "read_data_type_as_variant_type", contando)

    tags = tuple(tag for tag in TAGS if tag.id == TAG_FLOAT)
    async with bancada(redis_client, sim, tags=tags) as banca:
        await banca.gate_aberto()
        await await_until(lambda: len(lidos) == 1)

        await publicar(redis_client, tag_id=TAG_FLOAT, value=1.0)
        await esperar_valor(sim, NODE_MIRROR_FLOAT, 1.0)
        await publicar(redis_client, tag_id=TAG_FLOAT, value=2.0)
        await esperar_valor(sim, NODE_MIRROR_FLOAT, 2.0)

        assert lidos == [NODE_W_FLOAT], "o cache é de sessão, não de escrita"


async def test_datatype_ilegivel_cai_no_fallback_sem_derrubar_a_sessao(redis_client: Redis, sim):
    tags = (
        TagConfig(
            id=TAG_INT,
            name="SP Fantasma",
            node_id="ns=2;s=sim.nao.existe",
            direction="w",
            data_type="int",
        ),
    )
    async with bancada(redis_client, sim, tags=tags) as banca:
        await banca.gate_aberto()

        assert banca.runtime.variant_type_for(TAG_INT) is ua.VariantType.Int32
        await asyncio.sleep(QUIET_WINDOW_S)
        assert banca.runtime.state is ConnectionState.UP, "node ilegível não derruba a sessão"


async def test_tag_de_leitura_e_recusada(redis_client: Redis, sim):
    async with bancada(redis_client, sim) as banca, collecting(redis_client, CHANNEL_EVENTS) as ev:
        await banca.gate_aberto()
        antes = await sim.read(NODE_W_FLOAT)

        await publicar(redis_client, tag_id=TAG_READONLY, value=99.0)

        await await_until(lambda: len(of_kind(ev, KIND_WRITE_REJECTED)) == 1)
        evento = of_kind(ev, KIND_WRITE_REJECTED)[0]
        assert evento["severity"] == "warning"
        assert evento["origin"] == f"conn:{CONN_ID}"
        assert evento["payload"]["reason"] == "tag_not_writable"
        assert await sim.read(NODE_W_FLOAT) == antes
        assert not of_kind(ev, KIND_OPC_WRITE)


async def test_conexao_desconhecida_e_recusada_uma_vez(redis_client: Redis, sim):
    async with bancada(redis_client, sim) as banca, collecting(redis_client, CHANNEL_EVENTS) as ev:
        await banca.gate_aberto()

        await publicar(redis_client, tag_id=TAG_FLOAT, value=1.0, conn_id=999)
        await await_until(lambda: len(of_kind(ev, KIND_WRITE_REJECTED)) == 1)
        assert of_kind(ev, KIND_WRITE_REJECTED)[0]["payload"]["reason"] == "unknown_connection"

        await publicar(redis_client, tag_id=TAG_FLOAT, value=2.0, conn_id=999)
        # A 2ª escrita idêntica só é observável pelo silêncio: espere e reconte.
        await asyncio.sleep(QUIET_WINDOW_S)
        assert len(of_kind(ev, KIND_WRITE_REJECTED)) == 1, "recusa é deduplicada"


async def test_conexao_sem_watchdog_recusa_e_nao_escreve(redis_client: Redis, sim):
    async with (
        bancada(redis_client, sim, with_watchdog=False) as banca,
        collecting(redis_client, CHANNEL_EVENTS) as ev,
    ):
        await await_until(lambda: banca.runtime.state is ConnectionState.UP)
        antes = await sim.read(NODE_W_FLOAT)

        await publicar(redis_client, tag_id=TAG_FLOAT, value=77.0)
        await await_until(lambda: len(of_kind(ev, KIND_WRITE_REJECTED)) == 1)
        assert of_kind(ev, KIND_WRITE_REJECTED)[0]["payload"]["reason"] == "no_watchdog"

        await publicar(redis_client, tag_id=TAG_FLOAT, value=78.0)
        await asyncio.sleep(QUIET_WINDOW_S)
        assert len(of_kind(ev, KIND_WRITE_REJECTED)) == 1, "recusa é deduplicada por conexão"
        assert await sim.read(NODE_W_FLOAT) == antes


async def test_gate_fechado_bloqueia_e_dedupe_conta_suprimidos(redis_client: Redis, sim):
    async with bancada(redis_client, sim) as banca, collecting(redis_client, CHANNEL_EVENTS) as ev:
        await banca.gate_aberto()
        antes = await sim.read(NODE_MIRROR_FLOAT)

        await sim.set_freeze_watchdog(True)
        await await_until(lambda: not banca.snapshot.flow_watchdog_alive.get(FLOW_ID, False))

        for i in range(5):
            await publicar(redis_client, tag_id=TAG_FLOAT, value=100.0 + i)

        await await_until(lambda: len(of_kind(ev, KIND_WRITE_BLOCKED)) == 1)
        evento = of_kind(ev, KIND_WRITE_BLOCKED)[0]
        assert evento["severity"] == "warning"
        assert evento["origin"] == f"conn:{CONN_ID}"
        assert evento["payload"]["suppressed"] >= 4
        assert len(of_kind(ev, KIND_WRITE_BLOCKED)) == 1, "um evento por período de falha"
        assert await sim.read(NODE_MIRROR_FLOAT) == antes, "nenhuma escrita chegou ao servidor"
        assert not of_kind(ev, KIND_OPC_WRITE)


async def test_gate_reabre_apos_a_sessao_voltar_e_o_watchdog_alternar(redis_client: Redis) -> None:
    """O gate reabre quando o watchdog volta a alternar — e, como a task encerra sozinha
    na 1ª detecção de congelamento (ADR-009 revisado), só volta quando a SESSÃO reconecta
    (que recria a task do zero), não com o simples descongelar."""
    port = free_port()
    sim = OpcSimServer(port=port)
    await sim.start()
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = ConnectionRuntime(
        config,
        redis_client,
        snapshot,
        backoff_initial_s=TEST_BACKOFF_INITIAL_S,
        backoff_max_s=TEST_BACKOFF_MAX_S,
        watchdog_freeze_threshold_s=TEST_FREEZE_THRESHOLD_S,
    )
    await runtime.set_flow_watchdogs({FLOW_ID: make_watchdog()})
    consumer = WriteConsumer(redis_client, {CONN_ID: runtime})
    await runtime.start()
    await consumer.start()
    try:
        async with collecting(redis_client, CHANNEL_EVENTS) as ev:
            await await_until(
                lambda: (
                    runtime.state is ConnectionState.UP
                    and snapshot.flow_watchdog_alive.get(FLOW_ID)
                )
            )

            await sim.set_freeze_watchdog(True)
            await await_until(lambda: not snapshot.flow_watchdog_alive.get(FLOW_ID, False))
            await publicar(redis_client, tag_id=TAG_FLOAT, value=10.0)
            await await_until(lambda: len(of_kind(ev, KIND_WRITE_BLOCKED)) == 1)

            # A sessão cai (servidor sumiu) e volta no mesmo endpoint.
            await sim.stop()
            await await_until(lambda: runtime.state is ConnectionState.FAILED)
            sim = OpcSimServer(port=port)
            await sim.start()
            try:
                await await_until(
                    lambda: (
                        runtime.state is ConnectionState.UP
                        and snapshot.flow_watchdog_alive.get(FLOW_ID)
                    )
                )
                await publicar(redis_client, tag_id=TAG_FLOAT, value=33.0)
                await esperar_valor(sim, NODE_MIRROR_FLOAT, 33.0)
                assert of_kind(ev, KIND_OPC_WRITE)[-1]["payload"]["status"] == "ok"

                # Novo período de falha volta a avisar: o dedupe é do período, não da conexão.
                await sim.set_freeze_watchdog(True)
                await await_until(lambda: not snapshot.flow_watchdog_alive.get(FLOW_ID, False))
                await publicar(redis_client, tag_id=TAG_FLOAT, value=44.0)
                await await_until(lambda: len(of_kind(ev, KIND_WRITE_BLOCKED)) == 2)
            finally:
                await sim.stop()
    finally:
        await consumer.stop()
        await runtime.stop()


async def test_falha_de_execucao_conta_em_write_errors(redis_client: Redis, sim):
    tags = (
        TagConfig(
            id=TAG_FLOAT, name="SP Senoide", node_id=NODE_SINE, direction="w", data_type="float"
        ),
    )
    async with (
        bancada(redis_client, sim, tags=tags) as banca,
        collecting(redis_client, CHANNEL_EVENTS) as ev,
    ):
        await banca.gate_aberto()

        await publicar(redis_client, tag_id=TAG_FLOAT, value=5.0)

        await await_until(lambda: len(of_kind(ev, KIND_OPC_WRITE)) == 1)
        evento = of_kind(ev, KIND_OPC_WRITE)[0]
        assert evento["severity"] == "warning"
        assert evento["origin"] == "flow:3/block:opcw1", "erro também é rastro de quem mandou"
        assert evento["payload"]["status"] == "error"
        assert evento["payload"]["detail"]
        assert banca.snapshot.write_errors == 1


async def test_payload_malformado_nao_derruba_o_consumidor(redis_client: Redis, sim):
    async with bancada(redis_client, sim) as banca, collecting(redis_client, CHANNEL_EVENTS) as ev:
        await banca.gate_aberto()

        await redis_client.publish(CHANNEL_OPC_WRITES, "lixo que não é json")
        await redis_client.publish(CHANNEL_OPC_WRITES, '{"conn_id": "abacaxi"}')

        await publicar(redis_client, tag_id=TAG_FLOAT, value=12.5)
        await esperar_valor(sim, NODE_MIRROR_FLOAT, 12.5)
        assert len(of_kind(ev, KIND_OPC_WRITE)) == 1


async def test_stop_e_idempotente(redis_client: Redis, sim):
    async with bancada(redis_client, sim) as banca:
        await banca.gate_aberto()
        await banca.consumer.stop()
        await banca.consumer.stop()


async def test_novo_periodo_avisa_mesmo_sem_escrita_na_janela_aberta(redis_client: Redis) -> None:
    """Rearme dirigido pela recuperação real, não pela chegada de uma escrita.

    Com o rearme reativo, o período antigo continuava vivo e o segundo episódio de falha
    ficava mudo indefinidamente — o alarme só voltava se uma escrita caísse por acaso na
    janela em que o gate esteve aberto.
    """
    port = free_port()
    sim = OpcSimServer(port=port)
    await sim.start()
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = ConnectionRuntime(
        config,
        redis_client,
        snapshot,
        backoff_initial_s=TEST_BACKOFF_INITIAL_S,
        backoff_max_s=TEST_BACKOFF_MAX_S,
        watchdog_freeze_threshold_s=TEST_FREEZE_THRESHOLD_S,
    )
    await runtime.set_flow_watchdogs({FLOW_ID: make_watchdog()})
    consumer = WriteConsumer(redis_client, {CONN_ID: runtime})
    await runtime.start()
    await consumer.start()
    try:
        async with collecting(redis_client, CHANNEL_EVENTS) as ev:
            await await_until(
                lambda: (
                    runtime.state is ConnectionState.UP
                    and snapshot.flow_watchdog_alive.get(FLOW_ID)
                )
            )

            await sim.set_freeze_watchdog(True)
            await await_until(lambda: not snapshot.flow_watchdog_alive.get(FLOW_ID, False))
            await publicar(redis_client, tag_id=TAG_FLOAT, value=10.0)
            await await_until(lambda: len(of_kind(ev, KIND_WRITE_BLOCKED)) == 1)

            # Recuperação (a sessão volta) e nova queda SEM nenhuma escrita no meio.
            await sim.stop()
            await await_until(lambda: runtime.state is ConnectionState.FAILED)
            sim = OpcSimServer(port=port)
            await sim.start()
            try:
                await await_until(
                    lambda: (
                        runtime.state is ConnectionState.UP
                        and snapshot.flow_watchdog_alive.get(FLOW_ID)
                    )
                )
                await sim.set_freeze_watchdog(True)
                await await_until(lambda: not snapshot.flow_watchdog_alive.get(FLOW_ID, False))

                await publicar(redis_client, tag_id=TAG_FLOAT, value=11.0)
                await await_until(lambda: len(of_kind(ev, KIND_WRITE_BLOCKED)) == 2)
            finally:
                await sim.stop()
    finally:
        await consumer.stop()
        await runtime.stop()


async def test_apply_tags_recarrega_o_datatype_do_node_novo(redis_client: Redis, sim):
    """Trocar o `node_id` de uma tag `w` numa sessão viva invalida o cache (spec §4.3).

    `data_type` continua "float" de propósito: quem decide a codificação é o tipo REAL do
    servidor. Com o cache velho, a escrita iria ao node novo com a codificação do antigo.
    """
    tags = (
        TagConfig(id=TAG_FLOAT, name="SP", node_id=NODE_W_FLOAT, direction="w", data_type="float"),
    )
    async with bancada(redis_client, sim, tags=tags) as banca:
        await banca.gate_aberto()
        assert banca.runtime.variant_type_for(TAG_FLOAT) is ua.VariantType.Double

        trocadas = (
            TagConfig(
                id=TAG_FLOAT, name="SP", node_id=NODE_W_INT, direction="w", data_type="float"
            ),
        )
        await banca.runtime.apply_tags(trocadas)
        assert banca.runtime.variant_type_for(TAG_FLOAT) is ua.VariantType.Int32

        await publicar(redis_client, tag_id=TAG_FLOAT, value=7.9)
        await esperar_valor(sim, NODE_MIRROR_INT, 8)


async def test_sessao_up_sem_a_primeira_alternancia_bloqueia(redis_client: Redis, sim):
    """Segunda cláusula do gate isolada: sessão `up`, client válido, watchdog nunca armado.

    O limiar de congelamento é alto de propósito para a conexão FICAR nessa janela — é o
    estado natural entre o connect e a primeira alternância do life-bit.
    """
    await sim.set_freeze_watchdog(True)
    async with (
        bancada(redis_client, sim, freeze_threshold_s=30.0) as banca,
        collecting(redis_client, CHANNEL_EVENTS) as ev,
    ):
        await await_until(lambda: banca.runtime.state is ConnectionState.UP)
        assert banca.runtime.client is not None, "a sessão está viva; só o watchdog não armou"
        assert banca.snapshot.flow_watchdog_alive.get(FLOW_ID) is False

        await publicar(redis_client, tag_id=TAG_FLOAT, value=55.0)

        await await_until(lambda: len(of_kind(ev, KIND_WRITE_BLOCKED)) == 1)
        assert of_kind(ev, KIND_WRITE_BLOCKED)[0]["payload"]["reason"] == "watchdog_dead"
        assert await sim.read(NODE_MIRROR_FLOAT) == 0.0
        assert not of_kind(ev, KIND_OPC_WRITE)


async def test_execucao_reconfere_o_watchdog_antes_de_escrever(redis_client: Redis, sim):
    """`_execute` revalida o gate inteiro, não só a sessão.

    Chamada direta de propósito: é o último ponto antes de o valor chegar ao PLC, e a
    reconferência dele não pode depender de `fail()` zerar `state` e `flow_watchdog_alive`
    juntos — invariante implícita entre dois módulos.
    """
    async with bancada(redis_client, sim) as banca, collecting(redis_client, CHANNEL_EVENTS) as ev:
        await banca.gate_aberto()
        tag = next(t for t in TAGS if t.id == TAG_FLOAT)
        write = OpcWrite(
            conn_id=CONN_ID,
            tag_id=TAG_FLOAT,
            flow_id=FLOW_ID,
            value=88.0,
            source="user:2",
            ts=datetime.now(UTC),
        )

        # Sessão viva e client válido; só o watchdog cai. Sem await entre a marcação e a
        # chamada, então o watchdog não tem como rearmar no meio.
        banca.snapshot.flow_watchdog_alive[FLOW_ID] = False
        await banca.consumer._execute(write, banca.runtime, tag)

        await await_until(lambda: len(of_kind(ev, KIND_WRITE_BLOCKED)) == 1)
        assert of_kind(ev, KIND_WRITE_BLOCKED)[0]["payload"]["reason"] == "watchdog_dead"
        assert not of_kind(ev, KIND_OPC_WRITE)
        assert await sim.read(NODE_MIRROR_FLOAT) == 0.0


async def test_dois_flows_na_mesma_conexao_watchdog_de_um_nao_trava_o_outro(
    redis_client: Redis, sim
):
    """Dois flows com watchdog na MESMA conexão: o de um congela e bloqueia as escritas
    DELE, o outro continua escrevendo normalmente. Impossível de expressar no modelo
    antigo (watchdog por conexão) — o isolamento por flow (ADR-009 revisado) é o que
    viabiliza este caso."""
    flow_a, flow_b = FLOW_ID, FLOW_ID + 1
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = ConnectionRuntime(
        config,
        redis_client,
        snapshot,
        backoff_initial_s=TEST_BACKOFF_INITIAL_S,
        backoff_max_s=TEST_BACKOFF_MAX_S,
        watchdog_freeze_threshold_s=TEST_FREEZE_THRESHOLD_S,
    )
    await runtime.set_flow_watchdogs(
        {
            flow_a: make_watchdog(
                flow_id=flow_a, read_node=NODE_WD_TO_SYSTEM, write_node=NODE_WD_FROM_SYSTEM
            ),
            flow_b: make_watchdog(
                flow_id=flow_b, read_node=NODE_WD_TO_SYSTEM_2, write_node=NODE_WD_FROM_SYSTEM_2
            ),
        }
    )
    consumer = WriteConsumer(redis_client, {CONN_ID: runtime})
    await runtime.start()
    await consumer.start()
    try:
        async with collecting(redis_client, CHANNEL_EVENTS) as ev:
            await await_until(
                lambda: (
                    runtime.state is ConnectionState.UP
                    and snapshot.flow_watchdog_alive.get(flow_a)
                    and snapshot.flow_watchdog_alive.get(flow_b)
                )
            )

            await sim.set_freeze_watchdog(True, pair=1)
            await await_until(lambda: snapshot.flow_watchdog_alive.get(flow_a) is False)
            assert snapshot.flow_watchdog_alive.get(flow_b) is True

            await publicar(redis_client, tag_id=TAG_FLOAT, value=10.0, flow_id=flow_a)
            await await_until(lambda: len(of_kind(ev, KIND_WRITE_BLOCKED)) == 1)
            assert of_kind(ev, KIND_WRITE_BLOCKED)[0]["payload"]["flow_id"] == flow_a

            await publicar(redis_client, tag_id=TAG_FLOAT, value=20.0, flow_id=flow_b)
            await esperar_valor(sim, NODE_MIRROR_FLOAT, 20.0)
            assert of_kind(ev, KIND_OPC_WRITE)[-1]["payload"]["status"] == "ok"
            assert not of_kind(ev, KIND_WRITE_REJECTED)
    finally:
        await consumer.stop()
        await runtime.stop()


async def test_escrita_travada_na_conexao_a_nao_atrasa_a_conexao_b(
    redis_client: Redis, sim, monkeypatch
):
    """Isolamento entre conexões no consumo de `opc.writes`.

    A topologia de produção é UM consumidor para todas as conexões: uma escrita travada
    no servidor da conexão A não pode atrasar a escrita da conexão B publicada logo
    depois. Dentro de cada conexão a ordem de chegada segue garantida (fila por conexão).
    """
    sim_b = OpcSimServer(port=free_port())
    await sim_b.start()
    try:
        config_a = make_config(sim.endpoint, conn_id=8)
        config_b = make_config(sim_b.endpoint, conn_id=9)
        runtime_a = ConnectionRuntime(
            config_a,
            redis_client,
            ConnectionSnapshot(name=config_a.name),
            backoff_initial_s=TEST_BACKOFF_INITIAL_S,
            backoff_max_s=TEST_BACKOFF_MAX_S,
            watchdog_freeze_threshold_s=TEST_FREEZE_THRESHOLD_S,
        )
        runtime_b = ConnectionRuntime(
            config_b,
            redis_client,
            ConnectionSnapshot(name=config_b.name),
            backoff_initial_s=TEST_BACKOFF_INITIAL_S,
            backoff_max_s=TEST_BACKOFF_MAX_S,
            watchdog_freeze_threshold_s=TEST_FREEZE_THRESHOLD_S,
        )
        flow_b = FLOW_ID + 1
        await runtime_a.set_flow_watchdogs({FLOW_ID: make_watchdog()})
        await runtime_b.set_flow_watchdogs({flow_b: make_watchdog(flow_id=flow_b)})
        consumer = WriteConsumer(redis_client, {8: runtime_a, 9: runtime_b})
        await runtime_a.start()
        await runtime_b.start()
        await consumer.start()
        try:
            await await_until(
                lambda: (
                    runtime_a.state is ConnectionState.UP
                    and runtime_a.snapshot.flow_watchdog_alive.get(FLOW_ID, False)
                )
            )
            await await_until(
                lambda: (
                    runtime_b.state is ConnectionState.UP
                    and runtime_b.snapshot.flow_watchdog_alive.get(flow_b, False)
                )
            )

            # A escrita no node de A trava para sempre: servidor lento/travado.
            original_write = Node.write_value
            hung = asyncio.Event()

            async def write_value(self, *args, **kwargs):
                if self.nodeid.to_string() == NODE_W_FLOAT:
                    await hung.wait()
                return await original_write(self, *args, **kwargs)

            monkeypatch.setattr(Node, "write_value", write_value)

            await publicar(redis_client, tag_id=TAG_FLOAT, value=61.5, conn_id=8)
            await publicar(redis_client, tag_id=TAG_INT, value=7.0, conn_id=9, flow_id=flow_b)

            # B tem que chegar ao servidor mesmo com A pendurada na primeira escrita.
            await esperar_valor(sim_b, NODE_MIRROR_INT, 7)
            assert await sim.read(NODE_W_FLOAT) == 0.0, "escrita de A nunca chegou"
        finally:
            await consumer.stop()
            await runtime_a.stop()
            await runtime_b.stop()
    finally:
        await sim_b.stop()


async def test_fila_de_conexao_removida_e_recusada_e_nao_descartada(
    redis_client: Redis, sim, monkeypatch
):
    """Conexão que sai do mapping com fila cheia: o que sobrou é RECUSADO com evento.

    A fila por conexão não pode virar buraco de auditoria (RF-205) — escrita enfileirada
    atrás de uma travada, cuja conexão o supervisor derruba no meio, sai como
    `unknown_connection`, e a task se aposenta só depois de drenar tudo.
    """
    config = make_config(sim.endpoint, conn_id=8)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = ConnectionRuntime(
        config,
        redis_client,
        snapshot,
        backoff_initial_s=TEST_BACKOFF_INITIAL_S,
        backoff_max_s=TEST_BACKOFF_MAX_S,
        watchdog_freeze_threshold_s=TEST_FREEZE_THRESHOLD_S,
    )
    await runtime.set_flow_watchdogs({FLOW_ID: make_watchdog()})
    runtimes: dict[int, ConnectionRuntime] = {8: runtime}
    consumer = WriteConsumer(redis_client, runtimes)
    await runtime.start()
    await consumer.start()
    try:
        async with collecting(redis_client, CHANNEL_EVENTS) as ev:
            await await_until(
                lambda: (
                    runtime.state is ConnectionState.UP
                    and snapshot.flow_watchdog_alive.get(FLOW_ID, False)
                )
            )

            entrou = asyncio.Event()
            liberar = asyncio.Event()
            original_write = Node.write_value

            async def write_value(self, *args, **kwargs):
                if self.nodeid.to_string() == NODE_W_FLOAT:
                    entrou.set()
                    await liberar.wait()
                return await original_write(self, *args, **kwargs)

            monkeypatch.setattr(Node, "write_value", write_value)

            # A 1ª escrita trava a task da conexão; a 2ª fica enfileirada atrás dela.
            await publicar(redis_client, tag_id=TAG_FLOAT, value=1.5, conn_id=8)
            await asyncio.wait_for(entrou.wait(), timeout=AWAIT_TIMEOUT_S)
            await publicar(redis_client, tag_id=TAG_INT, value=5.0, conn_id=8)
            await await_until(lambda: consumer._conn_queues[8].qsize() == 1)

            # O supervisor derruba a conexão no meio do atraso e a travada é liberada.
            runtimes.pop(8)
            liberar.set()

            await await_until(
                lambda: any(
                    e["payload"]["tag_id"] == TAG_INT
                    and e["payload"]["reason"] == "unknown_connection"
                    for e in of_kind(ev, KIND_WRITE_REJECTED)
                )
            )
            # Drenou tudo antes de se aposentar: nada de fila órfã nem task viva.
            await await_until(lambda: 8 not in consumer._conn_queues)
            assert 8 not in consumer._conn_tasks
    finally:
        await consumer.stop()
        await runtime.stop()


def test_coercao_por_variant_type():
    assert coerce_value(7.9, ua.VariantType.Int32) == 8
    assert coerce_value(-7.9, ua.VariantType.Int16) == -8
    assert coerce_value(0.0, ua.VariantType.Boolean) is False
    assert coerce_value(2.5, ua.VariantType.Boolean) is True
    assert isinstance(coerce_value(2, ua.VariantType.Double), float)
