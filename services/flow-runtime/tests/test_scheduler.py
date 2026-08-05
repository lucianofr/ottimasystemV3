"""Contratos do laço de varredura (RF-401/402/404, ADR-004/007/024, spec F3 §2.2, §4.2).

O relógio é falso e o teste é quem move o tempo: as fronteiras saem exatas, e comparação
exata (não tolerância) é o que prova ausência de deriva. Os blocos são duplos — o que está
sob teste é o laço, não os blocos reais.
"""

import asyncio
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis

from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_FLOW_FAILED,
    KIND_FLOW_OVERRUN,
    EventMessage,
    FlowStatus,
    PortValue,
    channel_flow_status,
)
from ottima_flow_runtime.blocks.base import Block, PortSample
from ottima_flow_runtime.scheduler import FlowDefinition, FlowTask
from runtime_test_helpers import AWAIT_TIMEOUT_S, await_until

FLOW_ID = 7
OTHER_FLOW_ID = 9
TS_SECONDS = 1.0
EPOCH = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)


class FakeClock:
    """Relógio virtual do laço: o tempo só anda quando o teste manda.

    `fire()` salta para a fronteira que o próprio laço pediu — se o laço derivar (pedir
    `agora + Ts` em vez de `t0 + n·Ts`), a sequência de instantes registrados denuncia.
    """

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

    def advance(self, seconds: float) -> None:
        """Tempo consumido dentro de uma varredura (quem chama é o bloco-duplo)."""
        self._t += seconds
        self._wake_due()

    async def next_deadline(self) -> float:
        """Espera o laço chegar a dormir e devolve a fronteira que ele pediu."""
        await asyncio.wait_for(self._sleeping.wait(), AWAIT_TIMEOUT_S)
        return min(deadline for deadline, _ in self._waiters)

    async def fire(self) -> float:
        """Salta exatamente para a fronteira pedida e libera o laço."""
        deadline = await self.next_deadline()
        self._sleeping.clear()
        self._t = deadline
        self._wake_due()
        return deadline

    def _wake_due(self) -> None:
        for entry in [entry for entry in self._waiters if entry[0] <= self._t]:
            self._waiters.remove(entry)
            entry[1].set()


async def run_scan(clock: FakeClock) -> float:
    """Uma varredura completa: dispara a fronteira e devolve quando o laço voltou a dormir."""
    deadline = await clock.fire()
    await clock.next_deadline()
    return deadline


class SpyBlock(Block):
    """Bloco-duplo: registra quando executou e o que recebeu; conta 1 a cada varredura."""

    def __init__(
        self,
        block_id: str,
        clock: FakeClock,
        *,
        inputs: tuple[str, ...] = (),
        outputs: tuple[str, ...] = (),
        cost: float = 0.0,
        calls: list[str] | None = None,
    ) -> None:
        super().__init__(block_id)
        self._clock = clock
        self._inputs = inputs
        self._outputs = outputs
        self.cost = cost
        self.fired: list[float] = []
        self.seen: list[Mapping[str, PortSample]] = []
        self.calls: list[str] = calls if calls is not None else []
        self.value = 0.0
        self.on_step: Callable[[], None] | None = None

    @property
    def input_ports(self) -> tuple[str, ...]:
        return self._inputs

    @property
    def output_ports(self) -> tuple[str, ...]:
        return self._outputs

    async def step(self, inputs: Mapping[str, PortSample]) -> dict[str, PortSample]:
        self.fired.append(self._clock.monotonic())
        self.seen.append(dict(inputs))
        self.calls.append(self.block_id)
        if self.on_step is not None:
            self.on_step()
        if self.cost:
            self._clock.advance(self.cost)
        self.value += 1.0
        return {port: PortSample(self.value, True) for port in self._outputs}


class BoomBlock(Block):
    """Bloco que levanta: gatilho do isolamento de falha (RF-402)."""

    async def step(self, inputs: Mapping[str, PortSample]) -> dict[str, PortSample]:
        raise RuntimeError("bloco-duplo explodiu de proposito")


@pytest.fixture
async def subscribe(redis_client: Redis):
    """Fábrica de assinantes: devolve a lista que recebe os payloads crus de um canal."""
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
        await asyncio.wait_for(ready.wait(), AWAIT_TIMEOUT_S)
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
    """Fábrica de FlowTask já rodando e dormindo na primeira fronteira."""
    tasks: list[FlowTask] = []

    async def factory(
        clock: FakeClock,
        blocks: list[Block],
        *,
        wiring: Mapping[str, Mapping[str, tuple[str, str]]] | None = None,
        ts_seconds: float = TS_SECONDS,
        flow_id: int = FLOW_ID,
    ) -> FlowTask:
        definition = FlowDefinition(
            flow_id=flow_id,
            ts_seconds=ts_seconds,
            blocks=tuple(blocks),
            wiring=wiring or {},
        )
        task = FlowTask(definition, redis_client=redis_client, clock=clock)
        tasks.append(task)
        await task.start(user="admin")
        await clock.next_deadline()
        return task

    yield factory

    for task in tasks:
        await task.stop(user="admin", reason="user")


def events_of(raw: list[str], kind: str) -> list[EventMessage]:
    parsed = [EventMessage.model_validate_json(item) for item in raw]
    return [event for event in parsed if event.payload["kind"] == kind]


async def test_fronteiras_absolutas_nao_derivam(flow):
    """Varredura de custo variável não desloca a grade: disparo n é sempre `t0 + n·Ts`."""
    clock = FakeClock()
    block = SpyBlock("a", clock, outputs=("out",))
    await flow(clock, [block])

    costs = [0.0, 0.1, 0.37, 0.7, 0.05]
    for scan in range(100):
        block.cost = costs[scan % len(costs)]
        await run_scan(clock)

    assert block.fired == [TS_SECONDS * n for n in range(1, 101)]


async def test_fronteiras_perdidas_sao_puladas(flow):
    """Estouro de 2,5×Ts: a próxima é a primeira fronteira futura, sem rajada compensatória."""
    clock = FakeClock()
    block = SpyBlock("a", clock, outputs=("out",), cost=2.5)
    await flow(clock, [block])

    await run_scan(clock)  # dispara em 1.0, termina em 3.5
    block.cost = 0.0
    await run_scan(clock)
    await run_scan(clock)

    # Exatamente três disparos: as fronteiras 2.0 e 3.0 foram puladas, não enfileiradas.
    assert block.fired == [1.0, 4.0, 5.0]


async def test_overruns_conta_uma_unidade_por_varredura_estourada(flow):
    clock = FakeClock()
    block = SpyBlock("a", clock, outputs=("out",), cost=2.5)
    task = await flow(clock, [block])

    await run_scan(clock)

    assert task.overruns == 1  # duas fronteiras perdidas, uma só varredura estourada


async def test_flow_overrun_deduplica_e_rearma(flow, subscribe):
    clock = FakeClock()
    block = SpyBlock("a", clock, outputs=("out",), cost=2.5)
    raw = await subscribe(CHANNEL_EVENTS)
    task = await flow(clock, [block])

    for _ in range(3):
        await run_scan(clock)
    await await_until(lambda: len(events_of(raw, KIND_FLOW_OVERRUN)) >= 1)
    assert len(events_of(raw, KIND_FLOW_OVERRUN)) == 1
    assert task.overruns == 3

    block.cost = 0.0
    await run_scan(clock)  # varredura dentro do orçamento re-arma o dedupe
    block.cost = 2.5
    await run_scan(clock)

    await await_until(lambda: len(events_of(raw, KIND_FLOW_OVERRUN)) >= 2)
    overrun = events_of(raw, KIND_FLOW_OVERRUN)[0]
    assert overrun.severity == "warning"
    assert overrun.origin == f"flow:{FLOW_ID}"


async def test_blocos_executam_na_ordem_da_definicao(flow):
    """A tupla já vem em `exec_order` crescente (ADR-024): o laço honra a tupla, nada mais."""
    clock = FakeClock()
    calls: list[str] = []
    first = SpyBlock("a", clock, outputs=("out",), calls=calls)
    second = SpyBlock("b", clock, outputs=("out",), calls=calls)
    await flow(clock, [first, second])
    await run_scan(clock)
    assert calls == ["a", "b"]

    other_clock = FakeClock()
    reversed_calls: list[str] = []
    third = SpyBlock("a", other_clock, outputs=("out",), calls=reversed_calls)
    fourth = SpyBlock("b", other_clock, outputs=("out",), calls=reversed_calls)
    await flow(other_clock, [fourth, third], flow_id=OTHER_FLOW_ID)
    await run_scan(other_clock)
    assert reversed_calls == ["b", "a"]


async def test_aresta_em_ordem_normal_le_valor_da_mesma_varredura(flow):
    clock = FakeClock()
    source = SpyBlock("a", clock, outputs=("out",))
    sink = SpyBlock("b", clock, inputs=("in",), outputs=("out",))
    await flow(clock, [source, sink], wiring={"b": {"in": ("a", "out")}})

    await run_scan(clock)
    await run_scan(clock)

    assert [sample["in"].v for sample in sink.seen] == [1.0, 2.0]


async def test_aresta_invertida_le_valor_da_varredura_anterior(flow):
    """RF-401: fonte executa depois do destino ⇒ atraso determinístico de 1 varredura."""
    clock = FakeClock()
    source = SpyBlock("a", clock, outputs=("out",))
    sink = SpyBlock("b", clock, inputs=("in",), outputs=("out",))
    await flow(clock, [sink, source], wiring={"b": {"in": ("a", "out")}})

    for _ in range(3):
        await run_scan(clock)

    assert [sample["in"].v for sample in sink.seen] == [None, 1.0, 2.0]
    assert sink.seen[0]["in"].ok is False  # cold start (§3.0), não 0.0 sintético


async def test_payload_de_varredura_bate_com_a_spec(flow, subscribe):
    """§4.2 campo a campo: toda publicação de varredura leva `ports` preenchido."""
    clock = FakeClock()
    source = SpyBlock("a", clock, outputs=("out",), cost=0.002)
    sink = SpyBlock("b", clock, inputs=("in", "solto"))
    raw = await subscribe(channel_flow_status(FLOW_ID))
    await flow(clock, [source, sink], wiring={"b": {"in": ("a", "out")}})

    await run_scan(clock)
    await await_until(lambda: len(raw) >= 2)

    status = FlowStatus.model_validate_json(raw[-1])
    assert status.state == "running"
    assert status.overruns == 0
    assert status.scan_ms == pytest.approx(2.0)
    assert status.ts == EPOCH + timedelta(seconds=TS_SECONDS)
    assert status.ports == {
        "a": {"out": PortValue(v=1.0, ok=True)},
        "b": {"in": PortValue(v=1.0, ok=True), "solto": PortValue(v=None, ok=False)},
    }


async def test_transicoes_de_estado_publicam_ports_vazio(redis_client, subscribe):
    clock = FakeClock()
    block = SpyBlock("a", clock, outputs=("out",))
    raw = await subscribe(channel_flow_status(FLOW_ID))
    task = FlowTask(
        FlowDefinition(flow_id=FLOW_ID, ts_seconds=TS_SECONDS, blocks=(block,), wiring={}),
        redis_client=redis_client,
        clock=clock,
    )
    assert task.state == "stopped"

    await task.start(user="admin")
    await await_until(lambda: len(raw) >= 1)
    assert task.state == "running"
    running = FlowStatus.model_validate_json(raw[0])
    assert running.state == "running"
    assert running.ports == {}

    await task.stop(user="admin", reason="user")
    await await_until(lambda: len(raw) >= 2)
    assert task.state == "stopped"
    stopped = FlowStatus.model_validate_json(raw[1])
    assert stopped.state == "stopped"
    assert stopped.ports == {}


async def test_fail_forcado_publica_failed_e_emite_alarme(flow, subscribe):
    """RF-207: o supervisor derruba o flow de uma conexão caída."""
    clock = FakeClock()
    block = SpyBlock("a", clock, outputs=("out",))
    status_raw = await subscribe(channel_flow_status(FLOW_ID))
    events_raw = await subscribe(CHANNEL_EVENTS)
    task = await flow(clock, [block])

    await task.fail(reason="comm_failure")

    assert task.state == "failed"
    await await_until(lambda: len(status_raw) >= 2)
    assert FlowStatus.model_validate_json(status_raw[-1]).state == "failed"
    await await_until(lambda: len(events_of(events_raw, KIND_FLOW_FAILED)) >= 1)
    failed = events_of(events_raw, KIND_FLOW_FAILED)[0]
    assert failed.severity == "alarm"
    assert failed.origin == f"flow:{FLOW_ID}"
    assert failed.payload["reason"] == "comm_failure"


async def test_excecao_de_bloco_isola_o_flow(flow, subscribe):
    """RF-402: o flow que levanta cai sozinho; o outro segue varrendo e publicando."""
    broken_clock = FakeClock()
    healthy_clock = FakeClock()
    events_raw = await subscribe(CHANNEL_EVENTS)
    healthy_raw = await subscribe(channel_flow_status(OTHER_FLOW_ID))

    broken = await flow(broken_clock, [BoomBlock("x")])
    healthy_block = SpyBlock("g", healthy_clock, outputs=("out",))
    healthy = await flow(healthy_clock, [healthy_block], flow_id=OTHER_FLOW_ID)

    await broken_clock.fire()
    await await_until(lambda: broken.state == "failed")

    await run_scan(healthy_clock)
    await run_scan(healthy_clock)
    assert healthy.state == "running"
    assert len(healthy_block.fired) == 2
    await await_until(lambda: len(healthy_raw) >= 3)  # running + duas varreduras

    failed = events_of(events_raw, KIND_FLOW_FAILED)
    assert len(failed) == 1
    assert failed[0].origin == f"flow:{FLOW_ID}"
    assert "RuntimeError" in failed[0].payload["traceback"]

    await broken.stop(user="admin", reason="user")
    assert broken.state == "failed"  # falha é terminal: só deploy manual retoma (§2.2-6)


async def test_stop_e_idempotente_e_nao_publica_duplicado(redis_client, flow, subscribe):
    clock = FakeClock()
    block = SpyBlock("a", clock, outputs=("out",))
    raw = await subscribe(channel_flow_status(FLOW_ID))
    task = await flow(clock, [block])

    await task.stop(user="admin", reason="user")
    await task.stop(user="admin", reason="user")

    # Marcador no mesmo canal: a ordem do pub/sub garante que nada mais foi publicado antes.
    await redis_client.publish(channel_flow_status(FLOW_ID), '{"marker": true}')
    await await_until(lambda: '{"marker": true}' in raw)

    assert raw.index('{"marker": true}') == 2  # running, stopped, marcador
    assert task.state == "stopped"


async def test_hot_swap_adota_a_definicao_na_fronteira(flow):
    """ADR-011: a varredura corrente termina com a definição antiga; a seguinte usa a nova."""
    clock = FakeClock()
    calls: list[str] = []
    old = SpyBlock("a", clock, outputs=("out",), calls=calls)
    new = SpyBlock("b", clock, outputs=("out",), calls=calls)
    task = await flow(clock, [old])
    staged = FlowDefinition(flow_id=FLOW_ID, ts_seconds=TS_SECONDS, blocks=(new,), wiring={})
    old.on_step = lambda: task.stage(staged)

    await run_scan(clock)
    assert calls == ["a"]  # trocar no meio da varredura seria violar o ADR-011

    await run_scan(clock)
    assert calls == ["a", "b"]


async def test_mudanca_de_ts_reancora_a_grade(flow):
    clock = FakeClock()
    block = SpyBlock("a", clock, outputs=("out",))
    task = await flow(clock, [block], ts_seconds=1.0)

    await run_scan(clock)  # fronteira 1.0 da grade antiga
    task.stage(FlowDefinition(flow_id=FLOW_ID, ts_seconds=0.5, blocks=(block,), wiring={}))
    await run_scan(clock)  # fronteira 2.0: adota e re-ancora t0 aqui
    await run_scan(clock)
    await run_scan(clock)

    assert block.fired == [1.0, 2.0, 2.5, 3.0]


async def test_ts_publicado_e_o_instante_de_disparo(flow, subscribe):
    """§2.2-5: `ts` é a fronteira real de disparo, não o fim da varredura."""
    clock = FakeClock()
    block = SpyBlock("a", clock, outputs=("out",), cost=0.4)
    raw = await subscribe(channel_flow_status(FLOW_ID))
    task = await flow(clock, [block])

    await run_scan(clock)
    await await_until(lambda: len(raw) >= 2)

    status = FlowStatus.model_validate_json(raw[-1])
    assert status.ts == EPOCH + timedelta(seconds=1.0)  # 1.4 seria o fim da varredura
    assert status.scan_ms == pytest.approx(400.0)
    assert task.last_scan_ts == EPOCH + timedelta(seconds=1.0)


async def test_varredura_estourada_publica_o_overrun_da_propria_varredura(flow, subscribe):
    """O contador tem de subir ANTES da publicação: é o campo que o E2E-F3-03 lê.

    Publicar o valor antigo esconderia o estouro até a varredura seguinte — que, justamente
    por causa do salto de fronteiras, pode estar vários Ts à frente.
    """
    clock = FakeClock()
    block = SpyBlock("a", clock, outputs=("out",), cost=2.5)
    raw = await subscribe(channel_flow_status(FLOW_ID))
    await flow(clock, [block])

    await run_scan(clock)
    await await_until(lambda: len(raw) >= 2)

    status = FlowStatus.model_validate_json(raw[-1])
    assert status.scan_ms == pytest.approx(2500.0)  # é a publicação da varredura que estourou
    assert status.overruns == 1


async def test_hot_swap_preserva_porta_que_sobrevive_e_esquece_a_que_saiu(flow, subscribe):
    """A tabela de portas é privada da FlowTask, então a herança na troca é contrato daqui.

    Três destinos numa só troca: porta que sobrevive mantém o valor (senão a aresta invertida
    perderia a varredura anterior por causa de uma edição em outro canto do flow), bloco que
    saiu do grafo desaparece da publicação, e porta nova nasce fria (§3.0).
    """
    clock = FakeClock()
    source = SpyBlock("a", clock, outputs=("out",))
    gone = SpyBlock("g", clock, outputs=("out",))
    sink = SpyBlock("b", clock, inputs=("in",), outputs=("out",))
    fresh = SpyBlock("f", clock, inputs=("solta",), outputs=("out",))
    raw = await subscribe(channel_flow_status(FLOW_ID))
    task = await flow(clock, [source, gone])

    await run_scan(clock)  # a.out e g.out valem 1.0 na tabela
    task.stage(
        FlowDefinition(
            flow_id=FLOW_ID,
            ts_seconds=TS_SECONDS,
            # `b` antes de `a`: aresta invertida, logo `b` só pode ler o valor herdado.
            blocks=(sink, source, fresh),
            wiring={"b": {"in": ("a", "out")}},
        )
    )
    await run_scan(clock)
    await await_until(lambda: len(raw) >= 3)

    assert sink.seen[0]["in"].v == 1.0  # herdado da varredura anterior à troca
    status = FlowStatus.model_validate_json(raw[-1])
    assert "g" not in status.ports  # bloco que saiu do grafo não publica mais
    assert status.ports["f"]["solta"] == PortValue(v=None, ok=False)  # porta nova nasce fria


async def test_inputs_leva_somente_as_portas_com_aresta(flow):
    """Contrato da 1.2: porta declarada e sem aresta não entra no dict entregue ao `step`."""
    clock = FakeClock()
    source = SpyBlock("a", clock, outputs=("out",))
    sink = SpyBlock("b", clock, inputs=("ligada", "solta"), outputs=("out",))
    await flow(clock, [source, sink], wiring={"b": {"ligada": ("a", "out")}})

    await run_scan(clock)

    assert set(sink.seen[0]) == {"ligada"}
    assert sink.seen[0]["ligada"].v == 1.0
