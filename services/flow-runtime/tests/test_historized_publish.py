"""Publicação de variável historiada em `flow.values` (ADR-041 D2-D5, RF-308).

Três mesas:

- `FlowTask` com relógio falso (scheduler.py) — mesmo arreio de `test_scheduler.py`: prova o
  throttle por porta (D3), o mapeamento de valor (D4) e a purga de chave morta no hot-swap
  (item 4 do Target).
- `build_definition` pura (definition.py) — mesmo padrão de `test_definition.py`: prova que
  o cadastro é filtrado pelas portas que o grafo REALMENTE tem (D7), sem exceção.
- Um teste ponta a ponta com `Supervisor`/banco (mesmo arreio de `test_hotswap.py`): prova
  que `supervisor.py` recarrega `historized_vars` no MESMO ponto em que lê o `Flow`, tanto
  no deploy quanto no `reload` — o cadastro no banco, não só a definição em memória, é quem
  muda o que publica.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from runtime_test_helpers import (
    Collector,
    Harness,
    await_until,
    create_flow,
    create_project,
    graph,
    read_node,
    script_node,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import CHANNEL_FLOW_VALUES, OpcValue
from ottima_core.flowgraph import TagRef, parse_graph
from ottima_core.models import HistorizedVar, Tag
from ottima_core.script_pool import ScriptPool
from ottima_flow_runtime.blocks.base import Block, PortSample
from ottima_flow_runtime.definition import build_definition
from ottima_flow_runtime.scheduler import FlowDefinition, FlowTask, HistorizedPort

Factory = Callable[..., Awaitable[Harness]]
Collect = Callable[[str], Awaitable[Collector]]
Sessions = async_sessionmaker[AsyncSession]

FLOW_ID = 41
TS_SECONDS = 1.0
EPOCH = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)
TWO_COUNTERS = graph([script_node("s1", 1), script_node("s2", 2)])


# --------------------------------------------------------------------------------------
# Arreio de `FlowTask` com relógio falso — mesmo padrão de `test_scheduler.py`.
# --------------------------------------------------------------------------------------


class FakeClock:
    """Relógio virtual do laço: o tempo só anda quando o teste manda (cópia de
    `test_scheduler.py::FakeClock` — arreio local, não compartilhado entre módulos)."""

    def __init__(self) -> None:
        self._t = 0.0
        self._waiters: list[tuple[float, asyncio.Event]] = []
        self._sleeping = asyncio.Event()

    def monotonic(self) -> float:
        return self._t

    def now(self) -> datetime:
        return EPOCH + timedelta(seconds=self._t)

    async def sleep_until(self, deadline_monotonic: float) -> None:
        if self._t >= deadline_monotonic:
            await asyncio.sleep(0)
            return
        waiter = asyncio.Event()
        self._waiters.append((deadline_monotonic, waiter))
        self._sleeping.set()
        await waiter.wait()

    async def next_deadline(self) -> float:
        await asyncio.wait_for(self._sleeping.wait(), 5.0)
        return min(deadline for deadline, _ in self._waiters)

    async def fire(self) -> float:
        deadline = await self.next_deadline()
        self._sleeping.clear()
        self._t = deadline
        for entry in [entry for entry in self._waiters if entry[0] <= self._t]:
            self._waiters.remove(entry)
            entry[1].set()
        return deadline


class JitteredClock(FakeClock):
    """Grade monotônica exata, hora de PAREDE com jitter — como o `SystemClock` real.

    `now()` devolve o carimbo da grade menos alguns microssegundos alternados, reproduzindo
    o que o stack mostrou: com tolerância de 1 µs, a varredura cujo delta de parede caía
    abaixo de 1,0 s perdia a publicação e a série ia a ~1,5 s num flow de Ts = 1 s.
    """

    def now(self) -> datetime:
        # Jitter alternante de ±3 µs POR VARREDURA: metade dos deltas de parede fica ABAIXO
        # do Ts nominal (ex.: Ts=1 s ⇒ 1,000006 s, depois 0,999994 s).
        jitter = -3e-6 if int(round(self._t)) % 2 else +3e-6
        return EPOCH + timedelta(seconds=self._t + jitter)


async def run_scan(clock: FakeClock) -> float:
    """Uma varredura completa: dispara a fronteira e devolve quando o laço voltou a dormir."""
    deadline = await clock.fire()
    await clock.next_deadline()
    return deadline


class ValueBlock(Block):
    """Bloco-duplo: devolve sempre a MESMA `PortSample` em toda porta declarada — o throttle
    sob teste é o de `_publish_historized`, não a lógica de um bloco real."""

    def __init__(self, block_id: str, *, outputs: tuple[str, ...], sample: PortSample) -> None:
        super().__init__(block_id)
        self._outputs = outputs
        self._sample = sample

    @property
    def output_ports(self) -> tuple[str, ...]:
        return self._outputs

    async def step(
        self, inputs: dict[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        return {port: self._sample for port in self._outputs}


@pytest.fixture
async def subscribe(redis_client: Redis):
    """Fábrica de assinantes de canal cru (cópia de `test_scheduler.py::subscribe`)."""
    pumps: list[asyncio.Task[None]] = []
    pubsubs: list = []

    async def factory(channel: str) -> list[str]:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        received: list[str] = []
        ready = asyncio.Event()

        async def pump() -> None:
            async for message in pubsub.listen():
                if message["type"] == "subscribe":
                    ready.set()
                elif message["type"] == "message":
                    received.append(message["data"])

        pumps.append(asyncio.create_task(pump()))
        pubsubs.append(pubsub)
        await asyncio.wait_for(ready.wait(), 5.0)
        return received

    yield factory

    for pump_task in pumps:
        pump_task.cancel()
    for pump_task in pumps:
        with suppress(asyncio.CancelledError):
            await pump_task
    for pubsub in pubsubs:
        await pubsub.aclose()


@pytest.fixture
async def flow(redis_client: Redis):
    """Fábrica de `FlowTask` já rodando e dormindo na primeira fronteira, com `historized`
    (cópia de `test_scheduler.py::flow`, estendida com o cadastro sob teste)."""
    tasks: list[FlowTask] = []

    async def factory(
        clock: FakeClock,
        blocks: list[Block],
        *,
        historized: tuple[HistorizedPort, ...] = (),
        ts_seconds: float = TS_SECONDS,
        flow_id: int = FLOW_ID,
    ) -> FlowTask:
        definition = FlowDefinition(
            flow_id=flow_id,
            ts_seconds=ts_seconds,
            blocks=tuple(blocks),
            wiring={},
            historized=historized,
        )
        task = FlowTask(definition, redis_client=redis_client, clock=clock)
        tasks.append(task)
        await task.start(user="admin")
        await clock.next_deadline()
        return task

    yield factory

    for task in tasks:
        await task.stop(user="admin", reason="user")


def _values(raw: list[str]) -> list[OpcValue]:
    return [OpcValue.model_validate_json(item) for item in raw]


async def _esperar_valores(raw: list[str], quantidade: int) -> list[OpcValue]:
    """Espera a CONTAGEM esperada antes de asserir.

    Publicar em `flow.values` → Redis → pump do assinante é um round-trip assíncrono: ler
    `raw` no instante em que a varredura volta a dormir é uma corrida que só perde quando a
    máquina está carregada (foi exatamente assim que este arquivo falhou rodando junto com
    as outras suítes, e passou sozinho).
    """
    await await_until(lambda: len(raw) >= quantidade)
    return _values(raw)


SENTINELA_TAG_ID = -1


async def _barreira(redis_client: Redis, raw: list[str]) -> None:
    """Barreira para asserir AUSÊNCIA de publicação: manda um sentinela pelo MESMO canal e
    espera vê-lo. O pub/sub preserva a ordem por canal, então qualquer mensagem da varredura
    já teria chegado antes dele — `raw` só com o sentinela prova o silêncio, sem `sleep`
    arbitrário (que passaria por sorte e falharia sob carga)."""
    sentinela = OpcValue(tag_id=SENTINELA_TAG_ID, ts=EPOCH, value=0.0, quality=0)
    await redis_client.publish(CHANNEL_FLOW_VALUES, sentinela.model_dump_json())
    await await_until(lambda: any(SENTINELA_TAG_ID == v.tag_id for v in _values(raw)))


# --------------------------------------------------------------------------------------
# Cadência por porta (ADR-041 D3): `max(Ts_flow, 1 s)` cai do comparativo contra o tempo
# REAL entre varreduras, sem o código conhecer o próprio Ts (scheduler.py `HISTORIZED_THROTTLE_S`).
# --------------------------------------------------------------------------------------


async def test_ts_0_5s_publica_uma_mensagem_a_cada_duas_varreduras(
    flow, subscribe, redis_client: Redis
):
    clock = FakeClock()
    port = HistorizedPort(block_id="a", port="out", tag_id=100)
    block = ValueBlock("a", outputs=("out",), sample=PortSample(1.0, True))
    raw = await subscribe(CHANNEL_FLOW_VALUES)
    await flow(clock, [block], historized=(port,), ts_seconds=0.5)

    for _ in range(4):
        await run_scan(clock)

    # Fronteiras em 0.5/1.0/1.5/2.0 s: a primeira sempre publica (D3), a cadência de 1 s
    # deixa a segunda passar em 1.5 s (0.5 s de intervalo real não vence o teto).
    valores = await _esperar_valores(raw, 2)
    # Barreira depois da contagem: `>=` sozinho passaria mesmo se o throttle publicasse as 4
    # varreduras, bastando a asserção rodar antes da 3ª chegar. O sentinela prova o silêncio.
    await _barreira(redis_client, raw)
    valores = [v for v in valores if v.tag_id != SENTINELA_TAG_ID]
    assert len([v for v in _values(raw) if v.tag_id != SENTINELA_TAG_ID]) == 2
    assert [v.ts for v in valores] == [
        EPOCH + timedelta(seconds=0.5),
        EPOCH + timedelta(seconds=1.5),
    ]
    assert {v.tag_id for v in valores} == {100}


async def test_ts_1s_publica_uma_mensagem_por_varredura(flow, subscribe, redis_client: Redis):
    clock = FakeClock()
    port = HistorizedPort(block_id="a", port="out", tag_id=100)
    block = ValueBlock("a", outputs=("out",), sample=PortSample(1.0, True))
    raw = await subscribe(CHANNEL_FLOW_VALUES)
    await flow(clock, [block], historized=(port,), ts_seconds=1.0)

    for _ in range(3):
        await run_scan(clock)

    valores = await _esperar_valores(raw, 3)
    await _barreira(redis_client, raw)
    assert len([v for v in _values(raw) if v.tag_id != SENTINELA_TAG_ID]) == 3
    assert [v.ts for v in valores] == [EPOCH + timedelta(seconds=n) for n in (1.0, 2.0, 3.0)]


async def test_ts_1s_com_jitter_de_parede_nao_perde_varredura(flow, subscribe, redis_client: Redis):
    """REGRESSÃO (achado na prova no stack): o `ts` publicado é hora de parede e oscila em
    torno do Ts. Com tolerância de 1 µs, a varredura cujo delta caía para 0,999997 s era
    descartada e a série de um flow Ts=1 s saía a ~1,5 s (16 amostras em 25 s, alternando
    1,000/2,003 s). Tolerância de meia varredura tem de publicar as 4."""
    clock = JitteredClock()
    port = HistorizedPort(block_id="a", port="out", tag_id=100)
    block = ValueBlock("a", outputs=("out",), sample=PortSample(1.0, True))
    raw = await subscribe(CHANNEL_FLOW_VALUES)
    await flow(clock, [block], historized=(port,), ts_seconds=1.0)

    for _ in range(4):
        await run_scan(clock)

    valores = await _esperar_valores(raw, 4)
    await _barreira(redis_client, raw)
    assert len([v for v in _values(raw) if v.tag_id != SENTINELA_TAG_ID]) == 4
    deltas = [(valores[i + 1].ts - valores[i].ts).total_seconds() for i in range(len(valores) - 1)]
    assert max(deltas) < 1.5, f"varredura perdida: deltas {deltas}"


async def test_ts_2s_publica_uma_mensagem_por_varredura_sem_interpolar(
    flow, subscribe, redis_client: Redis
):
    """Ts >= 1 s já vence o teto sozinho: uma mensagem por varredura, nunca sintetizada
    entre fronteiras — o número de mensagens é exatamente o número de varreduras."""
    clock = FakeClock()
    port = HistorizedPort(block_id="a", port="out", tag_id=100)
    block = ValueBlock("a", outputs=("out",), sample=PortSample(1.0, True))
    raw = await subscribe(CHANNEL_FLOW_VALUES)
    await flow(clock, [block], historized=(port,), ts_seconds=2.0)

    for _ in range(3):
        await run_scan(clock)

    valores = await _esperar_valores(raw, 3)
    await _barreira(redis_client, raw)
    assert len([v for v in _values(raw) if v.tag_id != SENTINELA_TAG_ID]) == 3
    assert len(valores) == 3
    assert [v.ts for v in valores] == [EPOCH + timedelta(seconds=n) for n in (2.0, 4.0, 6.0)]


# --------------------------------------------------------------------------------------
# Mapeamento de valor (ADR-041 D4).
# --------------------------------------------------------------------------------------


async def test_porta_invalida_publica_value_0_quality_2(flow, subscribe):
    """`ok=False` OU `v=None` — as duas vias caem no mesmo `value=0.0, quality=2` que o
    recorder troca por NULL (ADR-037), sem alargar `OpcValue.value`."""
    clock = FakeClock()
    cold = HistorizedPort(block_id="cold", port="out", tag_id=100)
    ruim = HistorizedPort(block_id="ruim", port="out", tag_id=200)
    bloco_cold = ValueBlock("cold", outputs=("out",), sample=PortSample(None, False))
    bloco_ruim = ValueBlock("ruim", outputs=("out",), sample=PortSample(5.0, False))
    raw = await subscribe(CHANNEL_FLOW_VALUES)
    await flow(clock, [bloco_cold, bloco_ruim], historized=(cold, ruim), ts_seconds=1.0)

    await run_scan(clock)

    valores = {v.tag_id: v for v in await _esperar_valores(raw, 2)}
    assert valores[100].value == 0.0
    assert valores[100].quality == 2
    assert valores[200].value == 0.0  # v numérico descartado: ok=False já basta (D4)
    assert valores[200].quality == 2


async def test_porta_booleana_publica_1_0_ou_0_0(flow, subscribe):
    clock = FakeClock()
    ligado = HistorizedPort(block_id="on", port="out", tag_id=100)
    desligado = HistorizedPort(block_id="off", port="out", tag_id=200)
    bloco_on = ValueBlock("on", outputs=("out",), sample=PortSample(True, True))
    bloco_off = ValueBlock("off", outputs=("out",), sample=PortSample(False, True))
    raw = await subscribe(CHANNEL_FLOW_VALUES)
    await flow(clock, [bloco_on, bloco_off], historized=(ligado, desligado), ts_seconds=1.0)

    await run_scan(clock)

    valores = {v.tag_id: v for v in await _esperar_valores(raw, 2)}
    assert valores[100].value == 1.0
    assert valores[100].quality == 0
    assert valores[200].value == 0.0
    assert valores[200].quality == 0


async def test_porta_nao_finita_com_qualidade_boa_publica_quality_2(flow, subscribe):
    """`OpcReadBlock` propaga o float do PLC verbatim com `ok=True`: um NaN/Inf de campo
    chegaria com qualidade BOA e, diferente de NULL (que `avg` ignora), NaN contamina o
    bucket do CAgg de 1 min para sempre. Não-finito é falha, não valor."""
    clock = FakeClock()
    nan = HistorizedPort(block_id="nan", port="out", tag_id=100)
    inf = HistorizedPort(block_id="inf", port="out", tag_id=200)
    bloco_nan = ValueBlock("nan", outputs=("out",), sample=PortSample(float("nan"), True))
    bloco_inf = ValueBlock("inf", outputs=("out",), sample=PortSample(float("inf"), True))
    raw = await subscribe(CHANNEL_FLOW_VALUES)
    await flow(clock, [bloco_nan, bloco_inf], historized=(nan, inf), ts_seconds=1.0)

    await run_scan(clock)

    valores = {v.tag_id: v for v in await _esperar_valores(raw, 2)}
    assert valores[100].value == 0.0
    assert valores[100].quality == 2
    assert valores[200].value == 0.0
    assert valores[200].quality == 2


# --------------------------------------------------------------------------------------
# Custo zero sem porta historiada + purga de chave morta no hot-swap.
# --------------------------------------------------------------------------------------


async def test_historized_vazio_nao_publica_nada(flow, subscribe, redis_client: Redis):
    clock = FakeClock()
    block = ValueBlock("a", outputs=("out",), sample=PortSample(1.0, True))
    raw = await subscribe(CHANNEL_FLOW_VALUES)
    await flow(clock, [block], historized=(), ts_seconds=1.0)

    for _ in range(3):
        await run_scan(clock)

    await _barreira(redis_client, raw)
    assert [v.tag_id for v in _values(raw)] == [SENTINELA_TAG_ID]


async def test_hot_swap_troca_o_conjunto_e_purga_a_porta_removida(flow, subscribe):
    """Item 4 do Target: `_adopt_staged` descarta a chave da porta que saiu do cadastro —
    prova indireta: reintroduzida depois, ela publica IMEDIATAMENTE (sem "lembrar" do
    último `ts` de antes de sair), exatamente como uma porta nova. A porta que nunca saiu
    do cadastro (b) mantém a própria cadência sem interrupção na troca.
    """
    clock = FakeClock()
    port_a = HistorizedPort(block_id="a", port="out", tag_id=100)
    port_b = HistorizedPort(block_id="b", port="out", tag_id=200)
    bloco_a = ValueBlock("a", outputs=("out",), sample=PortSample(1.0, True))
    bloco_b = ValueBlock("b", outputs=("out",), sample=PortSample(2.0, True))
    raw = await subscribe(CHANNEL_FLOW_VALUES)
    task = await flow(clock, [bloco_a, bloco_b], historized=(port_a,), ts_seconds=1.0)

    await run_scan(clock)  # ts=1.0: só "a" está no cadastro

    task.stage(
        FlowDefinition(
            flow_id=FLOW_ID,
            ts_seconds=1.0,
            blocks=(bloco_a, bloco_b),
            wiring={},
            historized=(port_b,),  # "a" sai do cadastro, "b" entra
        )
    )
    await run_scan(clock)  # ts=2.0: adota o staged ANTES de publicar

    task.stage(
        FlowDefinition(
            flow_id=FLOW_ID,
            ts_seconds=1.0,
            blocks=(bloco_a, bloco_b),
            wiring={},
            historized=(port_a, port_b),  # "a" volta, "b" nunca saiu
        )
    )
    await run_scan(clock)  # ts=3.0: "a" republica na hora; "b" mantém a cadência de 1 em 1

    valores = await _esperar_valores(raw, 4)
    por_ts: dict[float, set[int]] = {}
    for v in valores:
        por_ts.setdefault((v.ts - EPOCH).total_seconds(), set()).add(v.tag_id)

    assert por_ts[1.0] == {100}  # antes da troca, só "a"
    assert por_ts[2.0] == {200}  # depois da troca, só "b" — "a" nunca herda o valor velho
    assert por_ts[3.0] == {100, 200}  # "a" reintroduzida publica na hora; "b" segue no ritmo


# --------------------------------------------------------------------------------------
# `build_definition` pura (definition.py, ADR-041 D7) — mesmo padrão de `test_definition.py`.
# --------------------------------------------------------------------------------------


class _FakeRedis:
    """Duplo do Redis: `build_definition` só usa o cliente dentro de fechamentos
    (`write_opc`/`publish`/`emit_event`) — este teste nunca chama `step()`, então nenhum
    fechamento dispara (mesma justificativa de `test_definition.py::_FakeRedis`)."""


class _FakeSnapshot:
    """Duplo do `ValueSnapshot`: `OpcReadBlock` só guarda a referência, nunca a usa fora de
    `step()` (mesmo padrão de `test_definition.py::_FakeSnapshot`)."""

    def get(self, tag_id: int) -> None:
        return None


def test_build_definition_ignora_porta_inexistente_do_cadastro():
    """ADR-041 D7: bloco removido, porta que nunca existiu ou renomeada — o cadastro é
    filtrado contra o grafo REAL, nunca confiado às cegas. Só a linha que aponta para uma
    porta que o bloco `r1` realmente tem sobrevive ao build."""
    g = parse_graph(graph([read_node("r1", 1, 1)]))
    tags = {1: TagRef(id=1, conn_id=10, direction="r", data_type="float")}
    historized_vars = [
        HistorizedVar(tag_id=100, flow_id=1, block_id="r1", port="nao_existe"),
        HistorizedVar(tag_id=101, flow_id=1, block_id="fantasma", port="out"),
        HistorizedVar(tag_id=102, flow_id=1, block_id="r1", port="out"),
    ]

    staged = build_definition(
        g,
        tags,
        flow_id=1,
        ts_seconds=1.0,
        reuse={},
        redis_client=_FakeRedis(),
        pool=ScriptPool(),
        snapshot=_FakeSnapshot(),
        exchange=_FakeSnapshot(),  # nenhum bloco de barramento nestes grafos
        historized_vars=historized_vars,
    )

    assert staged.definition.historized == (HistorizedPort(block_id="r1", port="out", tag_id=102),)


# --------------------------------------------------------------------------------------
# Ponta a ponta com `Supervisor`/banco (mesmo arreio de `test_hotswap.py`): o cadastro no
# BANCO, não só a definição em memória, é quem muda o que publica no reload.
# --------------------------------------------------------------------------------------


async def _criar_historized_var(
    factory: Sessions, project_id: int, flow_id: int, *, block_id: str, port: str, name: str
) -> int:
    """Fundação da ADR-041 D1 direto no banco — mesma forma da tag calculada (ADR-033 D1):
    `connection_id`/`node_id` NULL, `project_id` preenchido. A rota REST é do `ApiCrud`; o
    runtime só lê o que já está nas duas tabelas."""
    async with factory() as session:
        tag = Tag(project_id=project_id, name=name, direction="r", data_type="float")
        session.add(tag)
        await session.flush()
        session.add(HistorizedVar(tag_id=tag.id, flow_id=flow_id, block_id=block_id, port=port))
        await session.commit()
        return tag.id


async def _apagar_historized_var(factory: Sessions, tag_id: int) -> None:
    """Apaga a linha em `tags` — a cascata (ADR-041 D5) leva `historized_vars` junto."""
    async with factory() as session:
        tag = await session.get(Tag, tag_id)
        assert tag is not None
        await session.delete(tag)
        await session.commit()


def _tag_ids(collector: Collector) -> list[int]:
    return [OpcValue.model_validate_json(raw).tag_id for raw in collector.received]


async def test_hot_swap_via_supervisor_troca_o_cadastro_no_banco(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """`supervisor._build` carrega `historized_vars` do banco no MESMO ponto em que lê o
    `Flow` — deploy e `reload` passam pelo mesmo método. Cadastro trocado no banco (variável
    velha apagada, variável nova criada) tem de valer na varredura seguinte ao `reload`,
    sem parar o flow."""
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=TWO_COUNTERS)
    tag_a = await _criar_historized_var(
        session_factory, project_id, flow_id, block_id="s1", port="OUT1", name="var.s1.OUT1"
    )
    values = await collect(CHANNEL_FLOW_VALUES)
    harness = await harness_factory()

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await await_until(lambda: tag_a in _tag_ids(values))

    await _apagar_historized_var(session_factory, tag_a)
    tag_b = await _criar_historized_var(
        session_factory, project_id, flow_id, block_id="s2", port="OUT1", name="var.s2.OUT1"
    )
    await harness.command("reload", flow_id)

    await await_until(lambda: tag_b in _tag_ids(values))
    ids = _tag_ids(values)
    primeiro_b = ids.index(tag_b)
    # Da adoção do cadastro novo em diante, a variável apagada nunca mais aparece — não é
    # só a definição em memória que trocou, é o cadastro relido do banco.
    assert tag_a not in ids[primeiro_b:]
