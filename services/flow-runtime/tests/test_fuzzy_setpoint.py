"""SP do operador no bloco `fuzzy` (RF-541 revisado): com `setpoint` configurado, a ÚLTIMA
variável de entrada do FLL recebe o SP (não uma porta do canvas), o quadro publicado ganha
`sp` e a entrada sintética `SP`, e o comando `fuzzy_sp` muda só esse estado em runtime.

`SP_FLL` é uma superfície identidade no eixo do SP: com qualquer `pv` interior, o agregado
ponderado dos singletons 0/100 dá exatamente `sp` — hand-calc por linearidade das pertinências
triangulares, sem resolver integral nenhuma.
"""

from collections.abc import Awaitable, Callable

import pytest

from ottima_core.bus import FuzzyState
from ottima_core.signal import Quality
from ottima_flow_runtime.blocks.base import Signal
from ottima_flow_runtime.blocks.fuzzy import FuzzyBlock

SP_FLL = """Engine: sp_teste
InputVariable: pv
  enabled: true
  range: 0.000 100.000
  lock-range: true
  term: baixa Triangle 0.000 0.000 100.000
  term: alta Triangle 0.000 100.000 100.000
InputVariable: sp
  enabled: true
  range: 0.000 100.000
  lock-range: true
  term: baixa Triangle 0.000 0.000 100.000
  term: alta Triangle 0.000 100.000 100.000
OutputVariable: mv
  enabled: true
  range: 0.000 100.000
  lock-range: true
  aggregation: none
  defuzzifier: WeightedAverage
  default: nan
  lock-previous: false
  term: zero Constant 0.000
  term: cem Constant 100.000
RuleBlock: regras
  enabled: true
  conjunction: AlgebraicProduct
  disjunction: Maximum
  implication: AlgebraicProduct
  activation: General
  rule: if pv is baixa and sp is baixa then mv is zero
  rule: if pv is baixa and sp is alta then mv is cem
  rule: if pv is alta and sp is baixa then mv is zero
  rule: if pv is alta and sp is alta then mv is cem
"""


async def passo(block: FuzzyBlock, valor: float) -> Signal:
    return (await block.step({"IN1": Signal(valor, quality=Quality.GOOD)}))["OUT1"]


def coletor() -> tuple[list[FuzzyState], Callable[[FuzzyState], Awaitable[None]]]:
    quadros: list[FuzzyState] = []

    async def publish(estado: FuzzyState) -> None:
        quadros.append(estado)

    return quadros, publish


async def test_sp_alimenta_a_ultima_variavel_e_sai_no_quadro():
    quadros, publish = coletor()
    block = FuzzyBlock(
        "fz1", fll=SP_FLL, n_inputs=1, n_outputs=1, setpoint=75.0, publish=publish,
        state_min_interval_s=0.0,
    )

    saida = await passo(block, 25.0)

    assert saida.v == pytest.approx(75.0, abs=0.01)
    quadro = quadros[-1]
    assert quadro.sp == 75.0
    assert [v.port for v in quadro.inputs] == ["IN1", "SP"]
    assert quadro.inputs[1].v == 75.0
    assert quadro.inputs[1].name == "sp"


async def test_comando_muda_so_o_sp_sem_reinstanciar():
    quadros, publish = coletor()
    block = FuzzyBlock(
        "fz1", fll=SP_FLL, n_inputs=1, n_outputs=1, setpoint=75.0, publish=publish,
        state_min_interval_s=0.0,
    )
    await passo(block, 25.0)

    block.setpoint = 25.0
    saida = await passo(block, 25.0)

    assert saida.v == pytest.approx(25.0, abs=0.01)
    assert quadros[-1].sp == 25.0


async def test_sem_setpoint_o_quadro_nao_tem_sp_nem_entrada_sintetica():
    quadros, publish = coletor()
    block = FuzzyBlock(
        "fz1", fll=SP_FLL, n_inputs=2, n_outputs=1, publish=publish, state_min_interval_s=0.0
    )

    saida = await block.step(
        {
            "IN1": Signal(25.0, quality=Quality.GOOD),
            "IN2": Signal(75.0, quality=Quality.GOOD),
        }
    )

    assert saida["OUT1"].v == pytest.approx(75.0, abs=0.01)
    assert quadros[-1].sp is None
    assert [v.port for v in quadros[-1].inputs] == ["IN1", "IN2"]


def test_contagem_de_entradas_casa_com_o_setpoint():
    # FLL de 2 entradas com setpoint: espera 2 portas + 1 SP = 3 -> recusa.
    with pytest.raises(ValueError, match="n_inputs=3"):
        FuzzyBlock("fz1", fll=SP_FLL, n_inputs=2, n_outputs=1, setpoint=50.0)
    # FLL de 2 entradas sem setpoint: espera as 2 portas verbatim -> recusa n_inputs=1.
    with pytest.raises(ValueError, match="espera n_inputs=1"):
        FuzzyBlock("fz1", fll=SP_FLL, n_inputs=1, n_outputs=1)
