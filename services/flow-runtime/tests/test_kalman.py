"""Contratos do bloco Filtro Kalman (RF-531/533, ADR-026).

Filtro escalar de passeio aleatório. Os dois casos de regime fechado abaixo são o que trava
a implementação numa igualdade, e não numa aproximação:

- **`process_noise = 0`** ⇒ o valor verdadeiro é constante e o filtro degenera na **média
  cumulativa** das amostras (K_n = 1/n), qualquer que seja `measurement_noise`.
- **Ganho de regime**: com `P⁺` estacionário, `P = rq/(P+q)` ⇒ `P = (√(q²+4rq) − q)/2` e
  `K∞ = (P+q)/(P+q+r)`. Com `q = r = 1` isso dá exatamente `(√5 − 1)/2`.
"""

import math

import pytest

from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.kalman import KalmanBlock


def bloco(*, measurement_noise: float = 1.0, process_noise: float = 0.1) -> KalmanBlock:
    return KalmanBlock("k1", measurement_noise=measurement_noise, process_noise=process_noise)


async def alimenta(block: KalmanBlock, valor: float, *, ok: bool = True) -> PortSample:
    return (await block.step({"in": PortSample(valor, ok)}))["out"]


async def valor(block: KalmanBlock, medida: float) -> float:
    amostra = await alimenta(block, medida)
    assert amostra.v is not None
    return float(amostra.v)


def ganho_de_regime(q: float, r: float) -> float:
    p = (math.sqrt(q * q + 4.0 * r * q) - q) / 2.0
    return (p + q) / (p + q + r)


# --------------------------------------------------------------------------------------
# Estimação
# --------------------------------------------------------------------------------------


async def test_primeira_amostra_inicializa_o_estimador():
    """Sem transiente artificial: o estimador nasce na medição, não em zero."""
    assert await valor(bloco(), 150.0) == 150.0


async def test_processo_constante_degenera_na_media_cumulativa():
    filtro = bloco(measurement_noise=2.0, process_noise=0.0)
    medidas = [10.0, 12.0, 8.0, 14.0, 6.0]

    saidas = [await valor(filtro, medida) for medida in medidas]

    esperado = [sum(medidas[: n + 1]) / (n + 1) for n in range(len(medidas))]
    assert saidas == pytest.approx(esperado, rel=1e-12)


async def test_ganho_converge_para_o_regime():
    filtro = bloco(measurement_noise=1.0, process_noise=1.0)
    await valor(filtro, 0.0)
    for _ in range(200):
        await valor(filtro, 0.0)

    # Fração do erro de medição absorvida numa varredura = ganho vigente.
    depois = await valor(filtro, 1.0)

    assert depois == pytest.approx(ganho_de_regime(q=1.0, r=1.0), rel=1e-9)
    assert depois == pytest.approx((math.sqrt(5.0) - 1.0) / 2.0, rel=1e-9)


async def test_medicao_mais_ruidosa_filtra_mais():
    limpo = bloco(measurement_noise=0.1, process_noise=1.0)
    ruidoso = bloco(measurement_noise=10.0, process_noise=1.0)
    await valor(limpo, 0.0)
    await valor(ruidoso, 0.0)

    assert await valor(limpo, 100.0) > await valor(ruidoso, 100.0)


async def test_processo_mais_agil_filtra_menos():
    agil = bloco(measurement_noise=1.0, process_noise=10.0)
    lento = bloco(measurement_noise=1.0, process_noise=0.01)
    await valor(agil, 0.0)
    await valor(lento, 0.0)

    assert await valor(agil, 100.0) > await valor(lento, 100.0)


async def test_saida_nunca_ultrapassa_a_medicao():
    """`0 < K <= 1`: o estimador caminha na direção da medição, sem sobrepassar."""
    filtro = bloco(measurement_noise=1.0, process_noise=1.0)
    await valor(filtro, 0.0)

    for _ in range(50):
        assert 0.0 <= await valor(filtro, 10.0) <= 10.0


async def test_os_dois_campos_sao_desvio_padrao_e_nao_variancia():
    """Contrato da interface (ADR-026): dobrar `measurement_noise` equivale a quadruplicar a
    variância `r`. O ganho de regime tem que casar com `r = measurement_noise²`."""
    filtro = bloco(measurement_noise=2.0, process_noise=1.0)
    await valor(filtro, 0.0)
    for _ in range(200):
        await valor(filtro, 0.0)

    assert await valor(filtro, 1.0) == pytest.approx(ganho_de_regime(q=1.0, r=4.0), rel=1e-9)


# --------------------------------------------------------------------------------------
# Regras de base do bloco (spec F3 §3.0, decisão A-6)
# --------------------------------------------------------------------------------------


async def test_cold_start_nao_executa_nem_avanca_o_estado():
    filtro = bloco()

    saida = (await filtro.step({"in": PortSample(None, False)}))["out"]
    assert saida == PortSample(None, False)

    assert await valor(filtro, 150.0) == 150.0


async def test_invalidez_da_entrada_e_processada_e_propagada():
    filtro = bloco(measurement_noise=1.0, process_noise=1.0)
    await valor(filtro, 0.0)

    saida = await alimenta(filtro, 10.0, ok=False)

    assert saida.ok is False
    assert saida.v is not None and float(saida.v) > 0.0


async def test_reset_volta_a_inicializar_na_proxima_amostra():
    filtro = bloco()
    for _ in range(10):
        await valor(filtro, 100.0)

    filtro.reset()

    assert await valor(filtro, 20.0) == 20.0


async def test_estado_nao_e_compartilhado_entre_instancias():
    a, b = bloco(), bloco()
    for _ in range(10):
        await valor(a, 100.0)

    assert await valor(b, 5.0) == 5.0


def test_portas_declaradas_sao_uma_entrada_e_uma_saida():
    filtro = bloco()

    assert filtro.input_ports == ("in",)
    assert filtro.output_ports == ("out",)
