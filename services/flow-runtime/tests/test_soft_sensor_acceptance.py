"""Sensor virtual no flow: saída inválida não cai no portão frio (spec §5.4 ★, §5.5).

Prova de malha SEM o MPC. O que o sensor virtual controla é entregar `v` retido com qualidade
BAD depois do primeiro resultado: `v = None` é o sinal de cold start, e um consumidor que usa
`has_cold_input` (o portão do MPC, `blocks/mpc.py`) sairia por ele em vez de tratar a entrada
como inválida. O que o MPC faz com uma CV de valor retido e qualidade ruim já é coberto em
`test_mpc_block.py`; o cenário L2 com MPC real entra na SV-3 (E2E-SV3-04).

Os três primeiros testes montam o flow em memória (`FlowTask` com relógio falso, molde de
`test_realimentacao.py`); a troca de modelo e o hot-swap só existem no supervisor, então usam o
arreio dele.
"""

from collections.abc import Mapping

import pytest
from redis.asyncio import Redis
from runtime_test_helpers import await_until, save_graph
from test_realimentacao import EspiaBlock, FonteBlock
from test_scheduler import FakeClock, run_scan
from test_soft_sensor_command import HARNESS_TS, _activate, _deployed, _flow_graph

from ottima_core.bus import channel_flow_status
from ottima_core.signal import Quality
from ottima_core.softsensor import SampleBuffer, load_model, synthetic
from ottima_flow_runtime.blocks.base import Block, Signal, has_cold_input
from ottima_flow_runtime.blocks.constant import ConstantBlock
from ottima_flow_runtime.blocks.soft_sensor import SoftSensorBlock
from ottima_flow_runtime.scheduler import FlowDefinition, FlowTask

GOOD, BAD = Quality.GOOD, Quality.BAD
FLOW_ID = 41
TS = 1.0  # Ts do flow em memória (o mesmo de `test_realimentacao`); period_s sintético = 1.0

LSTM_K3 = synthetic.lstm(1, sequence_length=3)
FIACAO_LSTM = {"ss": {"IN1": ("fonte", "out")}, "espia": {"in": ("ss", "out")}}


@pytest.fixture
async def montar(redis_client: Redis):
    """FlowTask em memória já rodando e dormindo na primeira fronteira (como `malha`)."""
    tasks: list[FlowTask] = []

    async def factory(
        clock: FakeClock,
        blocks: list[Block],
        wiring: Mapping[str, Mapping[str, tuple[str, str]]],
    ) -> FlowTask:
        definition = FlowDefinition(
            flow_id=FLOW_ID, ts_seconds=TS, blocks=tuple(blocks), wiring=wiring
        )
        task = FlowTask(definition, redis_client=redis_client, clock=clock)
        tasks.append(task)
        await task.start(user="admin")
        await clock.next_deadline()
        return task

    yield factory

    for task in tasks:
        await task.stop(user="admin", reason="user")


async def _nada(*_args: object, **_kwargs: object) -> None:
    """`emit_event` e `persist` do bloco: aqui só importa o que sai pela porta."""


def _sensor(par: tuple, *, n_inputs: int, prewarm: SampleBuffer | None = None) -> SoftSensorBlock:
    meta, blob = par
    return SoftSensorBlock(
        "ss",
        n_inputs=n_inputs,
        ts_seconds=TS,
        model=load_model(1, meta.model_dump(), blob),
        prewarm=prewarm,
        missing_reason=None,
        emit_event=_nada,
        persist=_nada,
    )


def _janela_cheia() -> SampleBuffer:
    """Histórico íntegro (spec §5.7): a janela K=3 já chega cheia de dado bom na 1a varredura."""
    buffer = SampleBuffer(1)
    buffer.preload([[0.1]] * 3, [GOOD] * 3)
    return buffer


async def test_flow_com_pls_estima_a_cada_varredura(montar):
    clock = FakeClock()
    espia = EspiaBlock("espia")
    await montar(
        clock,
        [
            ConstantBlock("c1", value=3.0),
            ConstantBlock("c2", value=4.0),
            _sensor(synthetic.pls([2.0, -1.0], 0.5), n_inputs=2),
            espia,
        ],
        {
            "ss": {"IN1": ("c1", "out"), "IN2": ("c2", "out")},
            "espia": {"in": ("ss", "out")},
        },
    )

    for _ in range(5):
        await run_scan(clock)

    assert [s.v for s in espia.visto] == pytest.approx([2.5] * 5)  # 2*3 - 1*4 + 0.5
    assert [s.quality for s in espia.visto] == [GOOD] * 5


async def test_entrada_bad_no_meio_entrega_valor_retido_e_nao_none(montar):
    clock = FakeClock()
    espia = EspiaBlock("espia")
    fonte = FonteBlock(
        "fonte",
        [
            Signal(0.1, quality=GOOD),
            Signal(0.2, quality=GOOD),
            Signal(None, quality=BAD),  # a pior forma de entrada ruim: sem nem o valor
            *[Signal(0.3 + 0.1 * k, quality=GOOD) for k in range(4)],
        ],
    )
    await montar(
        clock,
        [fonte, _sensor(LSTM_K3, n_inputs=1, prewarm=_janela_cheia()), espia],
        FIACAO_LSTM,
    )

    for _ in range(7):
        await run_scan(clock)

    vistos = espia.visto
    # A amostra BAD fica na janela K=3 por três varreduras (a 3a, a 4a e a 5a).
    assert [s.quality for s in vistos] == [GOOD, GOOD, BAD, BAD, BAD, GOOD, GOOD]
    retido = vistos[1].v
    assert retido is not None and retido != vistos[0].v  # o valor andou com a entrada
    assert [s.v for s in vistos[2:5]] == [retido] * 3  # valor RETIDO, nunca None
    assert vistos[5].v not in (None, retido)  # saiu da janela: valor novo
    assert not any(has_cold_input({"cv": s}) for s in vistos)


async def test_primeiro_aquecimento_sem_prewarm_e_cold(montar):
    clock = FakeClock()
    espia = EspiaBlock("espia")
    fonte = FonteBlock("fonte", [Signal(0.1, quality=GOOD)])
    await montar(clock, [fonte, _sensor(LSTM_K3, n_inputs=1), espia], FIACAO_LSTM)

    for _ in range(4):
        await run_scan(clock)

    # Antes do primeiro resultado `None` É o cold start (§5.4): o portão frio vale, e só ele.
    assert [has_cold_input({"cv": s}) for s in espia.visto] == [True, True, False, False]
    assert [s.quality for s in espia.visto] == [BAD, BAD, GOOD, GOOD]


def _saidas(status) -> list:
    """`ss.out` de cada varredura publicada em `flow.status`."""
    return [scan.ports["ss"]["out"] for scan in status.scans()]


async def test_troca_de_modelo_no_flow_rodando_nunca_piora_a_qualidade(
    harness_factory, session_factory, collect
):
    # c1=1, c2=2: o modelo 1 (w=[1,1]) estima 3.0; o modelo 2 (w=[2,2]) estima 6.0.
    pls_1 = synthetic.pls([1.0, 1.0], 0.0, period_s=HARNESS_TS)
    pls_2 = synthetic.pls([2.0, 2.0], 0.0, period_s=HARNESS_TS)
    harness, scenario, _ = await _deployed(harness_factory, session_factory, pls_1, pls_2)
    flow_id, (_, modelo_2) = scenario["flow_id"], scenario["models"]
    status = await collect(channel_flow_status(flow_id))

    def varreduras(valor: float) -> int:
        return sum(1 for saida in _saidas(status) if saida.v == pytest.approx(valor))

    await await_until(lambda: varreduras(3.0) >= 2)
    await _activate(harness, session_factory, flow_id, modelo_2)
    await await_until(lambda: varreduras(6.0) >= 2)

    saidas = _saidas(status)
    assert [saida.quality for saida in saidas] == [GOOD] * len(saidas)  # nunca piorou
    valores = [round(saida.v, 6) for saida in saidas]
    assert set(valores) == {3.0, 6.0}
    assert valores == sorted(valores)  # uma só virada, sem volta ao modelo 1


async def test_hot_swap_que_nao_mexe_no_bloco_mantem_modelo_e_buffer(
    harness_factory, session_factory, collect
):
    # LSTM K=3: com PLS (K=1) "sem novo aquecimento" seria vazio. O histórico do projeto de
    # teste é vazio, então o primeiro aquecimento é pago uma vez, antes do reload.
    lstm = synthetic.lstm(2, sequence_length=3, period_s=HARNESS_TS)
    harness, scenario, bloco = await _deployed(
        harness_factory, session_factory, lstm, tipo="soft_sensor_lstm"
    )
    flow_id = scenario["flow_id"]
    status = await collect(channel_flow_status(flow_id))
    await await_until(lambda: any(saida.v is not None for saida in _saidas(status)))

    # Muda só o `c1` (a constante que alimenta o sensor); o nó `ss` fica funcionalmente igual.
    novo = _flow_graph("soft_sensor_lstm")
    [c1] = [n for n in novo["nodes"] if n["id"] == "c1"]
    c1["data"]["value"] = 0.5
    await save_graph(session_factory, flow_id, novo)
    await harness.command("reload", flow_id)

    def c1_novo() -> int:  # prova que o reload foi ADOTADO, não ignorado
        return sum(1 for scan in status.scans() if scan.ports["c1"]["out"].v == 0.5)

    await await_until(lambda: c1_novo() >= 3)

    assert harness.supervisor._runtimes[flow_id].blocks["ss"][1] is bloco  # noqa: SLF001
    saidas = _saidas(status)
    primeira = next(i for i, saida in enumerate(saidas) if saida.v is not None)
    assert [(saida.v is not None, saida.quality) for saida in saidas[primeira:]] == [
        (True, GOOD)
    ] * len(saidas[primeira:])
