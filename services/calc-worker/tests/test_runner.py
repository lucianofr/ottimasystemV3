"""Testes do `CalcTagRunner`: ciclo de UMA tag calculada (ADR-033).

O pool é **real**, mesma justificativa do `test_script.py` do flow-runtime: um timeout
dublê devolveria "timeout" sem nunca provar que o processo morreu de verdade nem que o
`state` sobreviveu intacto.
"""

import json
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from ottima_calc_worker.runner import CalcTagRunner
from ottima_core.bus import (
    CHANNEL_CALC_VALUES,
    CHANNEL_EVENTS,
    KIND_CALC_TAG_ERROR,
    KIND_CALC_TAG_RECOVERED,
    KIND_CALC_TAG_TIMEOUT,
    OpcValue,
    channel_opc_values,
)
from ottima_core.script_pool import ScriptPool
from ottima_core.snapshot import ValueSnapshot
from testkit.await_until import await_until

DRAIN_TIMEOUT_S = 5.0
SENTINEL_CHANNEL = "tests.sentinel.calc_runner"
CONN_ID = 1  # `opc.values.1`: canal sintético usado para publicar entradas de teste


class FlakyRedis:
    """Cliente cujo `publish` falha nas chamadas indicadas a um canal — simula uma queda
    do Redis bem na hora de publicar (idioma de `test_supervisor.py::FlakyRedis` do
    opc-worker, adaptado para falhar por número de chamada, não por assinatura)."""

    def __init__(self, inner: Redis, *, fail_channel: str, fail_on_calls: frozenset[int]) -> None:
        self._inner = inner
        self._fail_channel = fail_channel
        self._fail_on_calls = fail_on_calls
        self._call_count = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    async def publish(self, channel: str, message: str) -> int:
        if channel == self._fail_channel:
            self._call_count += 1
            if self._call_count in self._fail_on_calls:
                raise ConnectionError("queda simulada do Redis")
        return await self._inner.publish(channel, message)


@pytest.fixture
async def pool():
    """Pool de 2 workers: um timeout mata um, a varredura seguinte usa o outro já pronto."""
    p = ScriptPool(size=2)
    await p.start()
    yield p
    await p.stop()


@pytest.fixture
async def snapshot(redis_client: Redis):
    s = ValueSnapshot(redis_client)
    await s.start()
    yield s
    await s.stop()


@pytest.fixture
async def bus(redis_client: Redis):
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_EVENTS, CHANNEL_CALC_VALUES, SENTINEL_CHANNEL)
    for _ in range(3):
        message = await pubsub.get_message(timeout=DRAIN_TIMEOUT_S)
        assert message is not None and message["type"] == "subscribe"
    yield pubsub
    await pubsub.aclose()


async def mensagens(pubsub: PubSub, redis_client: Redis) -> list[tuple[str, dict]]:
    """Mensagens já publicadas em `events`/`calc.values`, terminando no sentinela — a ordem
    de entrega numa conexão é a ordem de publicação, então a chegada do sentinela prova que
    nada ficou pendente."""
    await redis_client.publish(SENTINEL_CHANNEL, "eof")
    collected: list[tuple[str, dict]] = []
    while True:
        message = await pubsub.get_message(timeout=DRAIN_TIMEOUT_S)
        assert message is not None, "sentinela não chegou: assinatura ou Redis inconsistente"
        if message["type"] != "message":
            continue
        if message["channel"] == SENTINEL_CHANNEL:
            return collected
        collected.append((message["channel"], json.loads(message["data"])))


async def publicar_entrada(
    redis_client: Redis, snapshot: ValueSnapshot, tag_id: int, value: float, *, quality: int = 0
) -> None:
    """Publica um valor OPC e espera o espelho refletir, para não correr contra o assinante."""
    payload = OpcValue(tag_id=tag_id, ts=datetime.now(UTC), value=value, quality=quality)
    await redis_client.publish(channel_opc_values(CONN_ID), payload.model_dump_json())
    await await_until(lambda: (tv := snapshot.get(tag_id)) is not None and tv.value == value)


def make_runner(
    redis_client: Redis,
    pool: ScriptPool,
    snapshot: ValueSnapshot,
    code: str,
    *,
    tag_id: int = 900,
    period_seconds: int = 1,
    input_tag_ids: tuple[int, ...] = (),
) -> CalcTagRunner:
    return CalcTagRunner(
        tag_id=tag_id,
        code=code,
        period_seconds=period_seconds,
        input_tag_ids=input_tag_ids,
        pool=pool,
        snapshot=snapshot,
        redis_client=redis_client,
    )


async def test_happy_path_publica_no_calc_values_com_tag_id_e_valor(
    redis_client, bus, pool, snapshot
):
    await publicar_entrada(redis_client, snapshot, tag_id=5, value=3.0)
    runner = make_runner(redis_client, pool, snapshot, "OUT = IN1 * 2\n", input_tag_ids=(5,))

    await runner._run_cycle()

    publicados = await mensagens(bus, redis_client)
    assert len(publicados) == 1
    channel, payload = publicados[0]
    assert channel == CHANNEL_CALC_VALUES
    assert payload["tag_id"] == 900
    assert payload["value"] == 6.0
    assert payload["quality"] == 0
    assert runner.health.last_status == "ok"


async def test_entradas_seguem_a_ordem_de_position(redis_client, bus, pool, snapshot):
    await publicar_entrada(redis_client, snapshot, tag_id=10, value=10.0)
    await publicar_entrada(redis_client, snapshot, tag_id=11, value=3.0)
    runner = make_runner(redis_client, pool, snapshot, "OUT = IN1 - IN2\n", input_tag_ids=(10, 11))

    await runner._run_cycle()

    _, payload = (await mensagens(bus, redis_client))[0]
    assert payload["value"] == 7.0


async def test_entrada_fria_pula_o_ciclo_sem_publicar(redis_client, bus, pool, snapshot):
    """Cold start: `IN2` nunca publicou, o ciclo é pulado sem substituir por 0.0."""
    await publicar_entrada(redis_client, snapshot, tag_id=20, value=1.0)
    runner = make_runner(redis_client, pool, snapshot, "OUT = IN1 + IN2\n", input_tag_ids=(20, 21))

    await runner._run_cycle()

    assert await mensagens(bus, redis_client) == []


async def test_qualidade_publicada_e_a_pior_entre_as_entradas(redis_client, bus, pool, snapshot):
    await publicar_entrada(redis_client, snapshot, tag_id=30, value=1.0, quality=0)
    await publicar_entrada(redis_client, snapshot, tag_id=31, value=2.0, quality=2)
    runner = make_runner(redis_client, pool, snapshot, "OUT = IN1 + IN2\n", input_tag_ids=(30, 31))

    await runner._run_cycle()

    _, payload = (await mensagens(bus, redis_client))[0]
    assert payload["quality"] == 2


async def test_timeout_publica_um_unico_evento_em_falhas_consecutivas(
    redis_client, bus, pool, snapshot
):
    """RF-514/ADR-020: uma tag em falha permanente não pode afogar o log de eventos."""
    runner = make_runner(redis_client, pool, snapshot, "while True:\n    pass\n")

    for _ in range(3):
        await runner._run_cycle()

    publicados = await mensagens(bus, redis_client)
    assert [channel for channel, _ in publicados] == [CHANNEL_EVENTS]
    _, payload = publicados[0]
    assert payload["payload"]["kind"] == KIND_CALC_TAG_TIMEOUT
    assert payload["severity"] == "alarm"
    assert payload["origin"] == "tag:900"
    assert runner.health.consecutive_failures == 3
    assert runner.health.last_status == "timeout"


async def test_recuperacao_apos_falha_publica_recovered_uma_vez(redis_client, bus, pool, snapshot):
    code = "if IN1 > 0:\n    while True:\n        pass\nOUT = 1.0\n"
    runner = make_runner(redis_client, pool, snapshot, code, input_tag_ids=(40,))

    await publicar_entrada(redis_client, snapshot, tag_id=40, value=1.0)
    await runner._run_cycle()  # timeout
    await publicar_entrada(redis_client, snapshot, tag_id=40, value=-1.0)
    await runner._run_cycle()  # sucesso: rearma o latch

    publicados = await mensagens(bus, redis_client)
    kinds = [p["payload"]["kind"] for c, p in publicados if c == CHANNEL_EVENTS]
    assert kinds == [KIND_CALC_TAG_TIMEOUT, KIND_CALC_TAG_RECOVERED]
    valores = [p for c, p in publicados if c == CHANNEL_CALC_VALUES]
    assert len(valores) == 1
    assert valores[0]["value"] == 1.0


async def test_state_persiste_entre_ciclos_e_nao_avanca_no_timeout(
    redis_client, bus, pool, snapshot
):
    """A 3a varredura prova o `state`: se o timeout tivesse avançado a cópia-mestre, o
    script sairia do laço infinito na 2a passada por `n == 1` e devolveria um valor."""
    code = """
n = state.get('n', 0)
if n == 1:
    while True:
        pass
state['n'] = n + 1
OUT = float(n + 10)
"""
    runner = make_runner(redis_client, pool, snapshot, code)

    await runner._run_cycle()  # n=0 -> publica 10.0, state.n vira 1
    await runner._run_cycle()  # n=1 -> timeout, state não avança
    await runner._run_cycle()  # n=1 de novo -> timeout de novo, prova que não avançou

    publicados = await mensagens(bus, redis_client)
    valores = [p for c, p in publicados if c == CHANNEL_CALC_VALUES]
    assert len(valores) == 1
    assert valores[0]["value"] == 10.0
    kinds = [p["payload"]["kind"] for c, p in publicados if c == CHANNEL_EVENTS]
    assert kinds == [KIND_CALC_TAG_TIMEOUT]  # latch: 2 falhas, 1 evento só


async def test_out_nao_finito_e_recusado_e_nao_publicado(redis_client, bus, pool, snapshot):
    runner = make_runner(redis_client, pool, snapshot, "OUT = float('nan')\n")

    await runner._run_cycle()

    publicados = await mensagens(bus, redis_client)
    assert [channel for channel, _ in publicados] == [CHANNEL_EVENTS]
    _, payload = publicados[0]
    assert payload["payload"]["kind"] == KIND_CALC_TAG_ERROR
    assert "finito" in payload["payload"]["detail"]


async def test_out1_em_vez_de_out_e_um_erro(redis_client, bus, pool, snapshot):
    """Convenção da tag calculada é `OUT` único, não `OUT1..OUTn` do bloco Script."""
    runner = make_runner(redis_client, pool, snapshot, "OUT1 = 1.0\n")

    await runner._run_cycle()

    publicados = await mensagens(bus, redis_client)
    assert [channel for channel, _ in publicados] == [CHANNEL_EVENTS]
    _, payload = publicados[0]
    assert payload["payload"]["kind"] == KIND_CALC_TAG_ERROR
    assert "OUT" in payload["payload"]["detail"]


async def test_falha_no_publish_do_evento_de_falha_nao_avanca_o_latch(
    redis_client, bus, pool, snapshot
):
    """Se o Redis cair bem na hora da 1a falha, o `_reported_kind` não pode travar sem o
    alarme ter saído — senão a tag fica em falha permanente pro resto da vida do processo
    sem o operador nunca ver o banner. A varredura seguinte, com o Redis de volta, tem que
    reenviar o MESMO alarme uma única vez (a política de latch continua valendo)."""
    flaky = FlakyRedis(redis_client, fail_channel=CHANNEL_EVENTS, fail_on_calls=frozenset({1}))
    runner = make_runner(flaky, pool, snapshot, "while True:\n    pass\n")

    await runner._run_cycle()  # timeout: publish do evento cai -> latch continua destravado
    await runner._run_cycle()  # timeout de novo, Redis recuperado -> alarme sai agora
    await runner._run_cycle()  # timeout de novo, latch já travado -> nada novo

    publicados = await mensagens(bus, redis_client)
    kinds = [p["payload"]["kind"] for c, p in publicados if c == CHANNEL_EVENTS]
    assert kinds == [KIND_CALC_TAG_TIMEOUT]
    assert runner.health.consecutive_failures == 3
    assert runner.health.last_status == "timeout"


async def test_falha_no_publish_do_evento_recovered_nao_avanca_o_latch(
    redis_client, bus, pool, snapshot
):
    """Mesmo buraco na recuperação (ADR-033): se o `calc_tag_recovered` não sair por causa
    de uma queda do Redis, o latch tem que continuar travado — senão a tag é marcada como
    recuperada sem o operador nunca ter visto o evento."""
    code = "if IN1 > 0:\n    while True:\n        pass\nOUT = 1.0\n"
    flaky = FlakyRedis(redis_client, fail_channel=CHANNEL_EVENTS, fail_on_calls=frozenset({2}))
    runner = make_runner(flaky, pool, snapshot, code, input_tag_ids=(41,))

    await publicar_entrada(redis_client, snapshot, tag_id=41, value=1.0)
    await runner._run_cycle()  # timeout: 1a publicação em CHANNEL_EVENTS, sucesso -> latch trava
    await publicar_entrada(redis_client, snapshot, tag_id=41, value=-1.0)
    await runner._run_cycle()  # sucesso do script, mas o `recovered` (2a chamada) cai
    await runner._run_cycle()  # sucesso de novo, Redis recuperado -> `recovered` sai agora

    publicados = await mensagens(bus, redis_client)
    kinds = [p["payload"]["kind"] for c, p in publicados if c == CHANNEL_EVENTS]
    assert kinds == [KIND_CALC_TAG_TIMEOUT, KIND_CALC_TAG_RECOVERED]
    valores = [p for c, p in publicados if c == CHANNEL_CALC_VALUES]
    assert [v["value"] for v in valores] == [1.0, 1.0]


async def test_falha_no_publish_do_calc_values_marca_health_distinto_sem_virar_erro(
    redis_client, bus, pool, snapshot
):
    """Uma queda do Redis bem na hora do `calc.values` é falha de TRANSPORTE, não de
    execução: o script rodou certo. O `/health` tem que refletir isso com um estado
    distinto do ciclo anterior — nunca `calc_tag_error`, reservado pra falha de execução
    (ADR-018) — e o ciclo seguinte, com o Redis de volta, tem que publicar normalmente."""
    flaky = FlakyRedis(redis_client, fail_channel=CHANNEL_CALC_VALUES, fail_on_calls=frozenset({1}))
    runner = make_runner(flaky, pool, snapshot, "OUT = 1.0\n")

    await runner._run_cycle()

    assert await mensagens(bus, redis_client) == []
    assert runner.health.last_status == "publish_failed"
    assert runner.health.consecutive_failures == 1

    await runner._run_cycle()  # Redis recuperado -> publica normalmente

    publicados = await mensagens(bus, redis_client)
    assert [c for c, _ in publicados] == [CHANNEL_CALC_VALUES]
    assert runner.health.last_status == "ok"
    assert runner.health.consecutive_failures == 0
