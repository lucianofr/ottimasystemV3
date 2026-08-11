"""Contratos do bloco Filtro 1ª ordem contra a solução analítica (RF-531/532, ADR-026).

Mesma discretização ZOH do TFS (`blocks/lag.py` é compartilhado), com uma diferença de
propósito: o TFS simula variável-desvio e parte de zero; este bloco filtra um sinal em EU
absoluta e por isso **parte no valor da primeira amostra** — arrancar de zero filtrando uma
temperatura de 150 °C seria um transiente inventado pelo bloco.
"""

import math

import pytest

from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.first_order import FirstOrderBlock

TS = 0.5  # Ts do critério de aceite da F3 (PRD §8)


def bloco(tau: float, *, ts: float = TS) -> FirstOrderBlock:
    return FirstOrderBlock("f1", tau=tau, ts_seconds=ts)


async def alimenta(block: FirstOrderBlock, valor: float, *, ok: bool = True) -> PortSample:
    return (await block.step({"in": PortSample(valor, ok)}))["out"]


async def rampa(block: FirstOrderBlock, valor: float, n: int) -> list[float]:
    saidas: list[float] = []
    for _ in range(n):
        amostra = await alimenta(block, valor)
        assert amostra.v is not None
        saidas.append(float(amostra.v))
    return saidas


def analitico(y0: float, alvo: float, tau: float, n: int, *, ts: float = TS) -> float:
    return y0 + (alvo - y0) * (1.0 - math.exp(-n * ts / tau))


# --------------------------------------------------------------------------------------
# Partida e resposta
# --------------------------------------------------------------------------------------


async def test_primeira_amostra_sai_sem_filtrar():
    """Partida sem salto: o filtro nasce no valor medido, não em zero."""
    assert (await alimenta(bloco(tau=10.0), 150.0)).v == 150.0


async def test_degrau_apos_a_partida_segue_a_solucao_analitica():
    filtro = bloco(tau=10.0)
    await alimenta(filtro, 100.0)  # partida

    saidas = await rampa(filtro, 120.0, 20)

    for n, y in enumerate(saidas, start=1):
        assert y == pytest.approx(analitico(100.0, 120.0, 10.0, n), rel=1e-12)


async def test_entrada_constante_nao_move_a_saida():
    filtro = bloco(tau=10.0)
    await alimenta(filtro, 42.0)

    assert await rampa(filtro, 42.0, 5) == pytest.approx([42.0] * 5)


async def test_tau_zero_degrada_para_passagem_direta():
    filtro = bloco(tau=0.0)

    assert (await alimenta(filtro, 1.0)).v == 1.0
    assert (await alimenta(filtro, 7.0)).v == 7.0


async def test_tau_desprezivel_degrada_para_passagem_direta():
    """Mesmo limiar do TFS: abaixo de `Ts/10` o estágio vira passagem direta."""
    filtro = bloco(tau=TS / 10 - 1e-9)
    await alimenta(filtro, 0.0)

    assert (await alimenta(filtro, 5.0)).v == 5.0


async def test_tau_no_limiar_continua_dinamico():
    filtro = bloco(tau=TS / 10)
    await alimenta(filtro, 0.0)

    saida = (await alimenta(filtro, 5.0)).v
    assert saida is not None
    assert 0.0 < float(saida) < 5.0


async def test_tau_maior_filtra_mais():
    lento, rapido = bloco(tau=60.0), bloco(tau=2.0)
    await alimenta(lento, 0.0)
    await alimenta(rapido, 0.0)

    saida_lenta = (await alimenta(lento, 10.0)).v
    saida_rapida = (await alimenta(rapido, 10.0)).v

    assert saida_lenta is not None and saida_rapida is not None
    assert float(saida_lenta) < float(saida_rapida)


# --------------------------------------------------------------------------------------
# Regras de base do bloco (spec F3 §3.0, decisão A-6)
# --------------------------------------------------------------------------------------


async def test_cold_start_nao_executa_nem_avanca_o_estado():
    filtro = bloco(tau=10.0)

    saida = (await filtro.step({"in": PortSample(None, False)}))["out"]
    assert saida == PortSample(None, False)

    # A varredura fria não consumiu a partida: a próxima amostra ainda sai sem filtrar.
    assert (await alimenta(filtro, 150.0)).v == 150.0


async def test_invalidez_da_entrada_e_processada_e_propagada():
    filtro = bloco(tau=10.0)
    await alimenta(filtro, 100.0)

    saida = await alimenta(filtro, 120.0, ok=False)

    assert saida.ok is False
    assert saida.v == pytest.approx(analitico(100.0, 120.0, 10.0, 1), rel=1e-12)


async def test_reset_volta_a_partir_do_valor_medido():
    filtro = bloco(tau=10.0)
    await rampa(filtro, 100.0, 5)

    filtro.reset()

    assert (await alimenta(filtro, 20.0)).v == 20.0


async def test_estado_nao_e_compartilhado_entre_instancias():
    a, b = bloco(tau=10.0), bloco(tau=10.0)
    await alimenta(a, 0.0)
    await rampa(a, 100.0, 10)

    assert (await alimenta(b, 5.0)).v == 5.0


def test_portas_declaradas_sao_uma_entrada_e_uma_saida():
    filtro = bloco(tau=10.0)

    assert filtro.input_ports == ("in",)
    assert filtro.output_ports == ("out",)
