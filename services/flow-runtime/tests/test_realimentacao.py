"""Aresta de realimentação: malha fechada dentro do canvas (ADR-040).

O defeito original era de editor — `TFS.y1 -> PID.pv` era recusado como ciclo — mas a
correção é de runtime: sem a condição inicial da aresta, o laço não fica só frio, fica
inválido PARA SEMPRE. `has_cold_input` faz todo bloco devolver `null_outputs` enquanto uma
entrada conectada for `v=None`, e num ciclo essa invalidez se auto-alimenta. Por isso os
testes aqui usam os blocos REAIS (PID e TFS), não duplos: é o portão de cold start deles que
fecha o laço, e um duplo permissivo não reproduziria o travamento.

O relógio é o `FakeClock` de `test_scheduler.py` (mesma suíte, `tests/` está no `sys.path`):
o tempo só anda quando o teste manda, então a série de varreduras é exata.
"""

from collections.abc import Mapping
from datetime import datetime

import pytest
from redis.asyncio import Redis
from test_scheduler import FakeClock, run_scan

from ottima_core.flowgraph import SopdtParams, TfsElement
from ottima_core.signal import Quality
from ottima_flow_runtime.blocks.base import Block, Signal
from ottima_flow_runtime.blocks.pid import PidBlock
from ottima_flow_runtime.blocks.tfs import TfsBlock
from ottima_flow_runtime.scheduler import FlowDefinition, FlowTask

FLOW_ID = 41
TS = 1.0
SP = 50.0

# `wiring` da malha do print do defeito: PID (exec 1) escreve na planta, a planta realimenta
# a PV do PID. A aresta `TFS.y1 -> PID.pv` é a que fecha o ciclo.
WIRING: Mapping[str, Mapping[str, tuple[str, str]]] = {
    "pid": {"pv": ("tfs", "y1")},
    "tfs": {"u1": ("pid", "out")},
}


def _off() -> TfsElement:
    return TfsElement(
        enabled=False, kind="sopdt", params=SopdtParams(K=1.0, tau1=1.0, tau2=0.0, theta=0.0)
    )


def _planta() -> TfsBlock:
    """1×1 auto-regulada, ganho 1, τ=5 s: sobe monotonicamente para `u` e assenta."""
    linha = TfsElement(
        enabled=True, kind="sopdt", params=SopdtParams(K=1.0, tau1=5.0, tau2=0.0, theta=0.0)
    )
    return TfsBlock("tfs", matrix=[[linha, _off()], [_off(), _off()]], ts_seconds=TS, y0=[0.0, 0.0])


def _controlador() -> PidBlock:
    return PidBlock(
        "pid",
        kc=2.0,
        ti_seconds=10.0,
        td_seconds=0.0,
        setpoint=SP,
        output_min=0.0,
        output_max=100.0,
        auto_mode=True,
        proportional_on_measurement=False,
        differential_on_measurement=False,
        starting_output=0.0,
        ts_seconds=TS,
    )


class FonteBlock(Block):
    """Saída roteirizada por varredura: prova o desarme da semente sem depender de dinâmica."""

    def __init__(self, block_id: str, roteiro: list[Signal]) -> None:
        super().__init__(block_id)
        self._roteiro = roteiro
        self._n = 0

    @property
    def input_ports(self) -> tuple[str, ...]:
        return ()

    @property
    def output_ports(self) -> tuple[str, ...]:
        return ("out",)

    async def step(
        self, inputs: Mapping[str, Signal], *, ts: datetime | None = None
    ) -> dict[str, Signal]:
        amostra = self._roteiro[min(self._n, len(self._roteiro) - 1)]
        self._n += 1
        return {"out": amostra}


class EspiaBlock(Block):
    """Registra o que chegou na entrada, varredura por varredura."""

    def __init__(self, block_id: str) -> None:
        super().__init__(block_id)
        self.visto: list[Signal] = []

    @property
    def input_ports(self) -> tuple[str, ...]:
        return ("in",)

    @property
    def output_ports(self) -> tuple[str, ...]:
        return ()

    async def step(
        self, inputs: Mapping[str, Signal], *, ts: datetime | None = None
    ) -> dict[str, Signal]:
        self.visto.append(inputs["in"])
        return {}


@pytest.fixture
async def malha(redis_client: Redis):
    """FlowTask já rodando e dormindo na primeira fronteira."""
    tasks: list[FlowTask] = []

    async def factory(
        clock: FakeClock,
        blocks: list[Block],
        *,
        wiring: Mapping[str, Mapping[str, tuple[str, str]]],
        seeds: Mapping[tuple[str, str], float] | None = None,
        flow_id: int = FLOW_ID,
    ) -> FlowTask:
        task = FlowTask(
            FlowDefinition(
                flow_id=flow_id,
                ts_seconds=TS,
                blocks=tuple(blocks),
                wiring=wiring,
                seeds=seeds or {},
            ),
            redis_client=redis_client,
            clock=clock,
        )
        tasks.append(task)
        await task.start(user="admin")
        await clock.next_deadline()
        return task

    yield factory

    for task in tasks:
        await task.stop(user="admin", reason="user")


def _serie(task: FlowTask, bloco: str, porta: str) -> float | None:
    return task._port_values()[bloco][porta].v  # noqa: SLF001 — tabela publicada do flow


async def test_malha_sem_semente_trava_invalida_para_sempre(malha):
    """O defeito que a condição inicial existe para evitar (ADR-040 D4).

    Sem semente a invalidez do cold start circula pelo ciclo e se auto-alimenta: não é uma
    varredura fria, é um laço morto. Se este teste passar a ver número, a semente virou
    dispensável e a D4 precisa ser relida — não é para "consertar" o assert.
    """
    clock = FakeClock()
    task = await malha(clock, [_controlador(), _planta()], wiring=WIRING)

    for _ in range(20):
        await run_scan(clock)

    assert _serie(task, "pid", "out") is None
    assert _serie(task, "tfs", "y1") is None


async def test_semente_na_pv_fecha_a_malha_e_o_pid_leva_a_planta_ao_sp(malha):
    """PID↔TFS 100% no canvas: a PV sai da condição inicial e converge para o SP."""
    clock = FakeClock()
    task = await malha(
        clock, [_controlador(), _planta()], wiring=WIRING, seeds={("pid", "pv"): 0.0}
    )

    pv: list[float] = []
    for _ in range(120):
        await run_scan(clock)
        valor = _serie(task, "tfs", "y1")
        assert valor is not None, "a malha caiu para inválida depois de ter partido"
        pv.append(valor)

    # A semente entra na PV, não na saída da planta: no scan 1 o PID já vê erro de 50,
    # satura em 100 e a planta (τ=5, Ts=1) anda 1−e^(−1/5) ≈ 18% do degrau.
    assert pv[0] == pytest.approx(100.0 * (1 - 2.718281828 ** (-TS / 5.0)), rel=0.01)
    assert pv[5] > pv[0], "a malha não evoluiu: o laço não fechou"
    assert pv[-1] == pytest.approx(SP, abs=0.5), f"não convergiu ao SP: {pv[-1]}"
    assert min(pv) >= 0.0 and max(pv) <= 100.0, f"saiu da faixa física do atuador: {pv[:10]}"


async def test_semente_na_outra_aresta_do_ciclo_tambem_parte(malha):
    """Ordem de desenho não pode decidir se a malha parte.

    Quem marca a aresta é o gesto do usuário: desenhar `TFS.y1 -> PID.pv` primeiro faz a
    marca cair em `PID.out -> TFS.u1` (é ela que fecha o ciclo). A semente é da porta de
    DESTINO da aresta marcada, então aqui ela entra em `TFS.u1` — e o laço tem de partir
    igual, uma varredura atrás.
    """
    clock = FakeClock()
    task = await malha(
        clock, [_controlador(), _planta()], wiring=WIRING, seeds={("tfs", "u1"): 0.0}
    )

    for _ in range(120):
        await run_scan(clock)

    assert _serie(task, "tfs", "y1") == pytest.approx(SP, abs=0.5)


async def test_semente_desarma_e_invalidez_volta_a_propagar(malha):
    """Semente é de PARTIDA, não fallback: sinal ruim depois da partida não é mascarado."""
    clock = FakeClock()
    fonte = FonteBlock(
        "fonte",
        [Signal(None), Signal(7.0, quality=Quality.GOOD), Signal(None)],
    )
    espia = EspiaBlock("espia")
    await malha(
        clock,
        [fonte, espia],
        wiring={"espia": {"in": ("fonte", "out")}},
        seeds={("espia", "in"): 99.0},
    )

    for _ in range(3):
        await run_scan(clock)

    assert [(amostra.v, amostra.ok) for amostra in espia.visto] == [
        (99.0, True),  # origem fria ⇒ condição inicial
        (7.0, True),  # primeira amostra com valor ⇒ desarma
        (None, False),  # origem ruim depois disso propaga, sem voltar à semente
    ]
