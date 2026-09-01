"""Amostragem da superficie de controle (SPEC_FUZZY secao 5.1)."""

import numpy as np

from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL
from ottima_core.flowgraph.fuzzy_surface import sample_surface


def test_superficie_default_65x65_sem_nan_e_com_origem_zero() -> None:
    grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL, resolution=65)
    assert grade.shape == (65, 65) and grade.dtype == np.float32
    assert not np.isnan(grade).any()
    centro = grade[32, 32]  # (e_n=0, de_n=0)
    assert abs(float(centro)) <= 0.02


def test_sinal_consistente_no_eixo_do_erro() -> None:
    grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL, resolution=65)
    assert float(grade[32, 64]) > 0.0  # e_n = +1 -> du_n > 0
    assert float(grade[32, 0]) < 0.0  # e_n = -1 -> du_n < 0


def test_eixo_0_e_de_e_eixo_1_e_erro() -> None:
    """A orientacao e contrato do heatmap: linha = de_n, coluna = e_n.

    Trocar os eixos passaria calado num FLL simetrico; o default nao e simetrico em `de`
    (as regras de antecipacao derivativa so existem na faixa `e is ZE`), e e isso que este
    teste explora.
    """
    grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL, resolution=65)
    # em e_n = 0, `de` decide o sinal: de_n = +1 pede subida, de_n = -1 pede descida
    assert float(grade[64, 32]) > 0.0
    assert float(grade[0, 32]) < 0.0
    # ja na coluna de e_n = +1 nenhuma regra depende de `de`: a coluna e constante
    coluna = grade[:, 64]
    assert float(coluna.max() - coluna.min()) == 0.0


def test_resolucao_configuravel_mantem_a_malha_alinhada() -> None:
    """Toda resolucao impar tem no seu centro exato o ponto (0, 0) — o repouso da malha."""
    for resolution in (33, 65, 129):
        grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL, resolution=resolution)
        assert grade.shape == (resolution, resolution)
        assert abs(float(grade[resolution // 2, resolution // 2])) <= 0.02


def test_superficie_com_buraco_devolve_nan_em_vez_de_mascarar() -> None:
    """Sem regra na regiao, `du` e NaN: e o que o portao NO_NAN e o alarme do kernel leem."""
    com_buraco = FUZZY_LOOP_DEFAULT_FLL
    for regra in ("  rule: if e is PP then du is PP\n", "  rule: if e is PG then du is PG\n"):
        com_buraco = com_buraco.replace(regra, "")
    grade = sample_surface(com_buraco)
    assert np.isnan(grade).any()
    assert not np.isnan(grade[:, :32]).any()  # o lado negativo do erro segue coberto
