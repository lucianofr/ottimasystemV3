"""Portoes de validacao da superficie (SPEC_FUZZY secao 5.3). F4 na camada dos portoes."""

import numpy as np

from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL
from ottima_core.flowgraph.fuzzy_surface import sample_surface
from ottima_core.flowgraph.lut_gates import run_lut_gates


def test_default_fll_passa_em_todos_os_portoes() -> None:
    assert run_lut_gates(sample_surface(FUZZY_LOOP_DEFAULT_FLL)) == []


def test_f4_sinal_invertido_bloqueia() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace(
        "rule: if e is PG then du is PG", "rule: if e is PG then du is NG"
    )
    assert "SIGN_CONSISTENCY" in run_lut_gates(sample_surface(fll))


def test_f4_sinal_invertido_no_lado_negativo_tambem_bloqueia() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace(
        "rule: if e is NG then du is NG", "rule: if e is NG then du is PG"
    )
    assert "SIGN_CONSISTENCY" in run_lut_gates(sample_surface(fll))


def test_nan_bloqueia() -> None:
    grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL).copy()
    grade[10, 10] = np.nan
    assert run_lut_gates(grade) == ["NO_NAN"]


def test_origem_fora_de_zero_bloqueia() -> None:
    grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL) + np.float32(0.5)
    assert "ORIGIN_ZERO" in run_lut_gates(grade)


def test_ganho_negativo_local_bloqueia_por_monotonicidade() -> None:
    grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL).copy()
    grade[:, 40] = grade[:, 20]  # degrau para tras no meio da subida
    erros = run_lut_gates(grade)
    assert "MONOTONIC_E" in erros


def test_ganho_excessivo_bloqueia() -> None:
    """Superficie tipo rele (degrau em e_n = 0): ganho local infinito, malha instavel."""
    resolution = 65
    eixo = np.linspace(-1.0, 1.0, resolution)
    degrau = np.sign(eixo).astype(np.float32)
    grade = np.tile(degrau, (resolution, 1))
    erros = run_lut_gates(grade)
    assert "BOUNDED_GAIN" in erros
    assert "CONTINUITY" in erros


def test_zona_morta_larga_bloqueia() -> None:
    """Superficie quase plana fora da origem: offset permanente em regime."""
    resolution = 65
    eixo = np.linspace(-1.0, 1.0, resolution)
    quase_plana = (eixo * 0.001).astype(np.float32)
    grade = np.tile(quase_plana, (resolution, 1))
    assert "NO_DEAD_ZONE" in run_lut_gates(grade)


def test_direct_acting_espelha_o_criterio_de_sinal() -> None:
    """Em acao direta a superficie correta e a espelhada — e o portao tem de saber disso."""
    grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL)
    assert run_lut_gates(grade, direct_acting=False) == []
    assert "SIGN_CONSISTENCY" in run_lut_gates(grade, direct_acting=True)
    assert run_lut_gates(-grade, direct_acting=True) == []


def test_antecipacao_derivativa_nao_e_confundida_com_sinal_invertido() -> None:
    """Regressao do critério: fora da linha `de_n = 0` a antecipação legítima inverte `du`.

    Com o erro subindo rápido (`de_n > 0`), a base de regras do default manda recuar ANTES
    de `e_n` chegar a zero — o cruzamento de zero de `du_n` desloca proporcionalmente a
    `de_n` (medido: `de_n = 0.25` cruza em `e_n = -0.125`; `de_n = 1` em `-0.28`). Avaliar
    sinal fora dessa linha reprovaria qualquer base com regra de `de`, incluindo a default.
    """
    grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL)
    eixo = np.linspace(-1.0, 1.0, 65)
    linha_de_alto = grade[eixo >= 0.25, :]
    # existe de fato celula com e_n < 0 e du_n > 0 fora da linha de_n = 0 ...
    assert (linha_de_alto[:, eixo < -0.02] > 0.02).any()
    # ... e o portao NAO a trata como inversao de sinal
    assert run_lut_gates(grade) == []
