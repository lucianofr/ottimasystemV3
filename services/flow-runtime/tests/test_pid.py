"""Contratos do bloco PID contra a conversão ISA -> paralela e a disciplina de finitude
(RF-551..553, ADR-031).

`simple-pid` roda na forma paralela (Kp, Ki, Kd); a config do bloco é ISA
(`kc, ti_seconds, td_seconds`). O caso mais importante deste arquivo prova que a
conversão feita na construção reproduz exatamente a saída de uma varredura -- o resto
cobre a disciplina de entrada/saída não-finita compartilhada com o bloco Fuzzy (ADR-029)
e a diferença entre reconstruir o controlador e chamar `PID.reset()` (que não restaura
`starting_output`).
"""

import math

import pytest

from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.pid import PidBlock

TS = 0.5  # Ts do critério de aceite da F3 (PRD §8)


def bloco(**overrides) -> PidBlock:
    defaults = dict(
        kc=1.0,
        ti_seconds=0.0,
        td_seconds=0.0,
        setpoint=0.0,
        output_min=None,
        output_max=None,
        auto_mode=True,
        proportional_on_measurement=False,
        differential_on_measurement=True,
        starting_output=0.0,
        ts_seconds=TS,
    )
    defaults.update(overrides)
    return PidBlock("p1", **defaults)


async def alimenta(
    block: PidBlock, pv: float, *, sp: float | None = None, ok: bool = True
) -> PortSample:
    inputs = {"pv": PortSample(pv, ok)}
    if sp is not None:
        inputs["sp"] = PortSample(sp, ok)
    return (await block.step(inputs))["out"]


async def passo(block: PidBlock, pv: float, n: int, *, sp: float | None = None) -> list[float]:
    saidas: list[float] = []
    for _ in range(n):
        saidas.append((await alimenta(block, pv, sp=sp)).v)
    return saidas


# --------------------------------------------------------------------------------------
# Conversão ISA -> paralela
# --------------------------------------------------------------------------------------


async def test_conversao_isa_reproduz_a_formula_fechada():
    """kc=2, Ti=60s, Td=0: prova a conversão, não um número mágico."""
    controlador = bloco(kc=2.0, ti_seconds=60.0, td_seconds=0.0, setpoint=50.0)
    saida = await alimenta(controlador, 45.0)
    erro = 50.0 - 45.0
    esperado = 2.0 * (erro + (1.0 / 60.0) * erro * TS)
    assert saida.v == pytest.approx(esperado, rel=1e-12)


async def test_ti_zero_desliga_a_integral():
    """Ti=0 é P puro (convenção documentada): saída não cresce em varreduras idênticas."""
    controlador = bloco(kc=3.0, ti_seconds=0.0, td_seconds=0.0, setpoint=10.0)
    saidas = await passo(controlador, 4.0, 5)
    assert saidas == pytest.approx([3.0 * (10.0 - 4.0)] * 5)


async def test_td_positivo_contribui_acao_derivativa_numa_rampa():
    sem_derivada = bloco(kc=1.0, ti_seconds=0.0, td_seconds=0.0, setpoint=100.0)
    com_derivada = bloco(kc=1.0, ti_seconds=0.0, td_seconds=5.0, setpoint=100.0)
    for i, pv in enumerate((10.0, 20.0, 30.0)):
        saida_sem = await alimenta(sem_derivada, pv)
        saida_com = await alimenta(com_derivada, pv)
        if i > 0:
            assert saida_com.v != pytest.approx(saida_sem.v)


async def test_kc_negativo_inverte_o_sinal_da_saida():
    direta = bloco(kc=1.0, ti_seconds=0.0, td_seconds=0.0, setpoint=10.0)
    reversa = bloco(kc=-1.0, ti_seconds=0.0, td_seconds=0.0, setpoint=10.0)
    saida_direta = await alimenta(direta, 6.0)
    saida_reversa = await alimenta(reversa, 6.0)
    assert saida_direta.v == pytest.approx(-saida_reversa.v)


# --------------------------------------------------------------------------------------
# Limites e anti-windup
# --------------------------------------------------------------------------------------


async def test_limites_de_saida_prendem_a_saida_e_a_integral_nao_windup():
    controlador = bloco(
        kc=10.0,
        ti_seconds=1.0,
        td_seconds=0.0,
        setpoint=1000.0,
        output_min=-5.0,
        output_max=5.0,
    )
    saidas = await passo(controlador, 0.0, 50)
    assert all(-5.0 <= v <= 5.0 for v in saidas)
    # Sem anti-windup a integral explodiria e a saída demoraria a sair da saturação
    # quando o erro mudasse de sinal -- aqui ela responde na varredura seguinte.
    saida_saturada = (await alimenta(controlador, 0.0)).v
    saida_apos_inversao = (await alimenta(controlador, 2000.0)).v
    assert saida_apos_inversao < saida_saturada


# --------------------------------------------------------------------------------------
# Setpoint via porta `sp`
# --------------------------------------------------------------------------------------


async def test_porta_sp_sobrepoe_o_setpoint_da_config():
    controlador = bloco(kc=1.0, ti_seconds=0.0, td_seconds=0.0, setpoint=10.0)
    saida = await alimenta(controlador, 0.0, sp=50.0)
    assert saida.v == pytest.approx(50.0)


async def test_sem_porta_sp_usa_o_setpoint_da_config():
    controlador = bloco(kc=1.0, ti_seconds=0.0, td_seconds=0.0, setpoint=10.0)
    saida = await alimenta(controlador, 0.0)
    assert saida.v == pytest.approx(10.0)


# --------------------------------------------------------------------------------------
# Regras de base do bloco (spec F3 §3.0, decisão A-6) e disciplina de finitude
# --------------------------------------------------------------------------------------


async def test_cold_start_nao_executa():
    controlador = bloco()
    saida = (await controlador.step({"pv": PortSample(None, False)}))["out"]
    assert saida.v is None
    assert saida.ok is False


async def test_pv_nao_finito_nao_envenena_a_integral():
    """Regressão do caminho mais perigoso: nan não pode grudar na integral para sempre."""
    limpo = bloco(kc=1.0, ti_seconds=2.0, td_seconds=0.0, setpoint=10.0)
    contaminado = bloco(kc=1.0, ti_seconds=2.0, td_seconds=0.0, setpoint=10.0)

    for controlador in (limpo, contaminado):
        await alimenta(controlador, 4.0)
        await alimenta(controlador, 5.0)

    for _ in range(3):
        saida_ruim = await alimenta(contaminado, math.nan)
        assert saida_ruim.ok is False

    saida_limpa = await alimenta(limpo, 6.0)
    saida_recuperada = await alimenta(contaminado, 6.0)
    assert math.isfinite(saida_recuperada.v)
    assert saida_recuperada.v == pytest.approx(saida_limpa.v)


async def test_pv_nao_finito_retem_a_ultima_saida_boa():
    controlador = bloco(kc=1.0, ti_seconds=0.0, td_seconds=0.0, setpoint=10.0)
    boa = await alimenta(controlador, 4.0)
    ruim = await alimenta(controlador, math.nan)
    assert ruim.v == pytest.approx(boa.v)
    assert ruim.ok is False


async def test_sp_nao_finito_retem_a_ultima_saida_boa():
    controlador = bloco(kc=1.0, ti_seconds=0.0, td_seconds=0.0, setpoint=10.0)
    boa = await alimenta(controlador, 4.0)
    ruim = await alimenta(controlador, 4.0, sp=math.nan)
    assert ruim.v == pytest.approx(boa.v)
    assert ruim.ok is False


async def test_entrada_invalida_e_finita_e_processada_e_propagada():
    """Decisão A-6: `ok=False` com valor finito ainda executa o controlador e propaga."""
    controlador = bloco(kc=1.0, ti_seconds=0.0, td_seconds=0.0, setpoint=10.0)
    saida = await alimenta(controlador, 4.0, ok=False)
    assert saida.v == pytest.approx(1.0 * (10.0 - 4.0))
    assert saida.ok is False


async def test_auto_mode_desligado_nunca_emite_ok_true():
    controlador = bloco(kc=1.0, ti_seconds=0.0, td_seconds=0.0, setpoint=10.0, auto_mode=False)
    saida = await alimenta(controlador, 4.0)
    assert saida.v is None
    assert saida.ok is False


# --------------------------------------------------------------------------------------
# Reset
# --------------------------------------------------------------------------------------


async def test_reset_zera_a_integral_e_restaura_starting_output():
    controlador = bloco(kc=1.0, ti_seconds=2.0, td_seconds=0.0, setpoint=10.0, starting_output=3.0)
    fresco = bloco(kc=1.0, ti_seconds=2.0, td_seconds=0.0, setpoint=10.0, starting_output=3.0)

    await passo(controlador, 4.0, 5)
    controlador.reset()

    saida_pos_reset = await alimenta(controlador, 4.0)
    saida_fresca = await alimenta(fresco, 4.0)
    assert saida_pos_reset.v == pytest.approx(saida_fresca.v)


# --------------------------------------------------------------------------------------
# Isolamento entre instâncias e contrato de portas
# --------------------------------------------------------------------------------------


async def test_estado_nao_e_compartilhado_entre_instancias():
    a = bloco(kc=1.0, ti_seconds=2.0, td_seconds=0.0, setpoint=10.0)
    b = bloco(kc=1.0, ti_seconds=2.0, td_seconds=0.0, setpoint=10.0)
    await passo(a, 4.0, 5)
    saida_b = await alimenta(b, 4.0)
    # `b` na PRIMEIRA varredura: Kc*(e + e*Ts/Ti) — a integral vale um único Ts, não a
    # acumulada das 5 varreduras de `a`. Forma fechada, não número mágico.
    erro = 10.0 - 4.0
    assert saida_b.v == pytest.approx(1.0 * (erro + erro * TS / 2.0))


def test_portas_declaradas_sao_pv_sp_e_out():
    controlador = bloco()
    assert controlador.input_ports == ("pv", "sp")
    assert controlador.output_ports == ("out",)
