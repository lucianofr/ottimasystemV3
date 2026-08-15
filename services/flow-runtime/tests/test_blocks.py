"""Contratos das regras de base e dos blocos OPC-Read/OPC-Write (RF-501/502, spec F3 §3.0-3.2).

Read é testado com um duplo do espelho (a absorção do barramento é contrato da tarefa 1.1);
Write é testado contra o Redis real, porque o que ele entrega é uma publicação de barramento.
"""

import json
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from ottima_core.bus import (
    CHANNEL_EVENTS,
    CHANNEL_OPC_WRITES,
    KIND_WRITE_SUPPRESSED,
)
from ottima_core.snapshot import TagValue
from ottima_flow_runtime.blocks.base import (
    Block,
    PortSample,
    has_cold_input,
    null_outputs,
)
from ottima_flow_runtime.blocks.opc_read import OpcReadBlock
from ottima_flow_runtime.blocks.opc_write import OpcWriteBlock

TS = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)
DRAIN_TIMEOUT_S = 5.0
SENTINEL_CHANNEL = "tests.sentinel"
"""Marca de fim-de-fila: a ordem de entrega numa conexão é a ordem de publicação, então a
chegada do sentinela prova que nada anterior ficou pendente — sem sleep cego no teste."""


class FakeSnapshot:
    """Duplo do `ValueSnapshot`: só o `get`, que é tudo o que o Read consome."""

    def __init__(self, values: dict[int, TagValue]) -> None:
        self._values = values

    def get(self, tag_id: int) -> TagValue | None:
        return self._values.get(tag_id)


class _AccumulatorBlock(Block):
    """Bloco mínimo com estado, para exercitar as regras de base sem a matemática do TFS."""

    def __init__(self, block_id: str) -> None:
        super().__init__(block_id)
        self._total = 0.0

    @property
    def input_ports(self) -> tuple[str, ...]:
        return ("in",)

    @property
    def output_ports(self) -> tuple[str, ...]:
        return ("out",)

    async def step(self, inputs):
        if has_cold_input(inputs):
            return null_outputs(self.output_ports)
        sample = inputs["in"]
        self._total += float(sample.v)
        return {"out": PortSample(self._total, sample.ok)}


def tag_value(value: float, quality: int = 0) -> TagValue:
    return TagValue(value=value, quality=quality, ts=TS)


@pytest.fixture
async def bus(redis_client: Redis):
    """Assinante confirmado dos canais que o Write toca, mais o canal do sentinela."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_OPC_WRITES, CHANNEL_EVENTS, SENTINEL_CHANNEL)
    for _ in range(3):
        message = await pubsub.get_message(timeout=DRAIN_TIMEOUT_S)
        assert message is not None and message["type"] == "subscribe"
    yield pubsub
    await pubsub.aclose()


async def drain(pubsub: PubSub, redis_client: Redis) -> dict[str, list[dict]]:
    """Colhe tudo o que já foi publicado, por canal, terminando no sentinela."""
    await redis_client.publish(SENTINEL_CHANNEL, "eof")
    collected: dict[str, list[dict]] = {}
    while True:
        message = await pubsub.get_message(timeout=DRAIN_TIMEOUT_S)
        assert message is not None, "sentinela não chegou: assinatura ou Redis inconsistente"
        if message["type"] != "message":
            continue
        if message["channel"] == SENTINEL_CHANNEL:
            return collected
        collected.setdefault(message["channel"], []).append(json.loads(message["data"]))


def writer(redis_client: Redis) -> OpcWriteBlock:
    return OpcWriteBlock("b2", tag_id=9, conn_id=3, flow_id=7, redis_client=redis_client)


# --------------------------------------------------------------------------------------
# OPC-Read (spec §3.1)
# --------------------------------------------------------------------------------------


async def test_read_de_tag_sem_valor_e_invalida():
    """Spec §3.1: sem valor no espelho é invalidez, não 0.0 sintético."""
    block = OpcReadBlock("b1", tag_id=9, data_type="float", snapshot=FakeSnapshot({}))

    out = await block.step({})

    assert out == {"out": PortSample(None, False)}


async def test_read_com_quality_boa_e_valida():
    snapshot = FakeSnapshot({9: tag_value(42.5)})
    block = OpcReadBlock("b1", tag_id=9, data_type="float", snapshot=snapshot)

    assert await block.step({}) == {"out": PortSample(42.5, True)}


@pytest.mark.parametrize("quality", [1, 2])
async def test_read_com_quality_ruim_preserva_o_valor(quality: int):
    """Uncertain e bad invalidam (§3.1), mas o valor é propagado (decisão A-6)."""
    snapshot = FakeSnapshot({9: tag_value(42.5, quality=quality)})
    block = OpcReadBlock("b1", tag_id=9, data_type="float", snapshot=snapshot)

    assert await block.step({}) == {"out": PortSample(42.5, False)}


@pytest.mark.parametrize(("raw", "expected"), [(0.0, False), (1.0, True), (2.0, True)])
async def test_read_de_tag_booleana_devolve_bool(raw: float, expected: bool):
    """Decisão A-5: tag `bool` sai como `bool` do Python, não como float."""
    snapshot = FakeSnapshot({9: tag_value(raw)})
    block = OpcReadBlock("b1", tag_id=9, data_type="bool", snapshot=snapshot)

    sample = (await block.step({}))["out"]

    assert sample.v is expected


async def test_read_de_tag_inteira_devolve_float():
    snapshot = FakeSnapshot({9: tag_value(7.0)})
    block = OpcReadBlock("b1", tag_id=9, data_type="int", snapshot=snapshot)

    sample = (await block.step({}))["out"]

    assert isinstance(sample.v, float) and sample.v == 7.0


async def test_read_nao_declara_entradas():
    block = OpcReadBlock("b1", tag_id=9, data_type="float", snapshot=FakeSnapshot({}))

    assert block.input_ports == ()
    assert block.output_ports == ("out",)


# --------------------------------------------------------------------------------------
# OPC-Write (spec §3.2)
# --------------------------------------------------------------------------------------


async def test_write_publica_opc_write_com_source_do_bloco(redis_client, bus):
    block = writer(redis_client)

    assert await block.step({"in": PortSample(12.5, True)}) == {}

    collected = await drain(bus, redis_client)
    assert CHANNEL_EVENTS not in collected
    (write,) = collected[CHANNEL_OPC_WRITES]
    assert write["conn_id"] == 3
    assert write["tag_id"] == 9
    assert write["value"] == 12.5
    assert write["source"] == "flow:7/block:b2"
    assert datetime.fromisoformat(write["ts"]).tzinfo is not None


async def test_write_de_entrada_booleana_publica_float(redis_client, bus):
    """Contrato de barramento: `value` é float; a coerção de Variant é do opc-worker."""
    block = writer(redis_client)

    await block.step({"in": PortSample(True, True)})

    (write,) = (await drain(bus, redis_client))[CHANNEL_OPC_WRITES]
    assert write["value"] == 1.0
    assert isinstance(write["value"], float)


async def test_write_com_entrada_invalida_suprime_e_avisa(redis_client, bus):
    block = writer(redis_client)

    await block.step({"in": PortSample(12.5, False)})

    collected = await drain(bus, redis_client)
    assert CHANNEL_OPC_WRITES not in collected
    (event,) = collected[CHANNEL_EVENTS]
    assert event["payload"]["kind"] == KIND_WRITE_SUPPRESSED
    assert event["payload"]["tag_id"] == 9
    assert event["severity"] == "warning"
    assert event["origin"] == "flow:7/block:b2"
    assert event["message"]


async def test_write_com_entrada_nula_suprime_e_avisa(redis_client, bus):
    """Caso do E2E-F3-10: cold start a montante não vira escrita de 0.0."""
    block = writer(redis_client)

    await block.step({"in": PortSample(None, True)})

    collected = await drain(bus, redis_client)
    assert CHANNEL_OPC_WRITES not in collected
    (event,) = collected[CHANNEL_EVENTS]
    assert event["payload"]["kind"] == KIND_WRITE_SUPPRESSED


async def test_write_dedupe_um_evento_por_periodo_de_supressao(redis_client, bus):
    """Decisão A-6: um evento por período; publicar de novo re-arma o dedupe."""
    block = writer(redis_client)

    for _ in range(3):
        await block.step({"in": PortSample(None, True)})

    collected = await drain(bus, redis_client)
    assert len(collected[CHANNEL_EVENTS]) == 1

    await block.step({"in": PortSample(1.0, True)})
    await block.step({"in": PortSample(None, True)})

    collected = await drain(bus, redis_client)
    assert len(collected[CHANNEL_OPC_WRITES]) == 1
    assert len(collected[CHANNEL_EVENTS]) == 1


async def test_write_reset_rearma_o_dedupe(redis_client, bus):
    """`reset()` é o deploy/stop: o próximo período de supressão avisa de novo."""
    block = writer(redis_client)
    await block.step({"in": PortSample(None, True)})
    await drain(bus, redis_client)

    block.reset()
    await block.step({"in": PortSample(None, True)})

    assert len((await drain(bus, redis_client))[CHANNEL_EVENTS]) == 1


async def test_write_nao_declara_saidas(redis_client):
    block = writer(redis_client)

    assert block.input_ports == ("in",)
    assert block.output_ports == ()


# --------------------------------------------------------------------------------------
# Regras de base (spec §3.0)
# --------------------------------------------------------------------------------------


async def test_cold_start_nao_executa_e_nao_avanca_estado():
    """Spec §3.0: entrada `null` não executa o bloco nem move o estado interno."""
    block = _AccumulatorBlock("b3")

    assert await block.step({"in": PortSample(None, False)}) == {"out": PortSample(None, False)}

    # O efeito observável do não-avanço: a varredura seguinte parte do zero.
    assert await block.step({"in": PortSample(5.0, True)}) == {"out": PortSample(5.0, True)}


async def test_invalidez_propaga_sem_impedir_execucao():
    """Decisão A-6: valor conhecido com flag ruim executa e contamina a saída."""
    block = _AccumulatorBlock("b3")

    out = await block.step({"in": PortSample(5.0, False)})

    assert out["out"].v == 5.0
    assert out["out"].ok is False


def test_has_cold_input_ignora_portas_ausentes():
    """Contrato do scheduler: porta desconectada não aparece em `inputs` e não bloqueia."""
    assert has_cold_input({}) is False
    assert has_cold_input({"a": PortSample(1.0, True)}) is False
    assert has_cold_input({"a": PortSample(1.0, True), "b": PortSample(None, True)}) is True


def test_null_outputs_marca_todas_as_saidas_como_invalidas():
    assert null_outputs(("y1", "y2")) == {
        "y1": PortSample(None, False),
        "y2": PortSample(None, False),
    }
