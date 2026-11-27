"""Corte treino/teste do sensor virtual (RF-587, SPEC_SENSOR_VIRTUAL §8.1): feito UMA vez no tempo,
sobre todas as análises do conjunto e antes da janela, para `train` e `tune` enxergarem o mesmo."""

import numpy as np
import pytest

from ottima_core.softsensor import DATASET_STEPS
from ottima_ml_worker.training import TrainData, TrainingError
from ottima_ml_worker.training.data import split_rows


def _gapped(n: int = 40) -> TrainData:
    """`y` é o índice da análise, para ver para onde cada uma foi. Lacuna no passo -56 das
    análises 5..9 (perdem-nas só janelas de 56+ passos) e no passo -6 da penúltima (6+ passos)."""
    x = np.zeros((n, DATASET_STEPS, 2), dtype=np.float32)
    x[5:10, -56, 0] = np.nan
    x[n - 2, -6, 1] = np.nan
    return TrainData(x=x, y=np.arange(n, dtype=float), ts=np.arange(n, dtype=float) * 10)


@pytest.mark.parametrize("k", [1, 5, 6, 55, 56, 100])
def test_corte_e_um_so_para_qualquer_janela(k):
    """40 análises: as 8 últimas (32..39) são teste, com a janela que for."""
    x, y, n_fit = split_rows(_gapped(), k)

    assert x.shape == (len(y), k, 2)
    assert y[:n_fit].tolist() == [i for i in range(32) if not (5 <= i < 10 and k >= 56)]
    assert y[n_fit:].tolist() == [i for i in range(32, 40) if not (i == 38 and k >= 6)]


def test_analises_com_o_mesmo_ts_ficam_do_mesmo_lado():
    """Dois conjuntos sobrepostos repetem `ts`: o corte recua até o início do empate."""
    data = _gapped(30)  # 20% de 30 = 6 teste, corte por posição na análise 24
    data.ts[23:27] = 230.0  # empate nas análises 23..26 (o corte cairia no meio dele)

    _, y, n_fit = split_rows(data, 1)

    assert y[:n_fit].tolist() == list(range(23))
    assert y[n_fit:].tolist() == list(range(23, 30))


def test_janela_sem_analise_de_teste_utilizavel_falha_com_mensagem():
    data = _gapped(30)
    data.x[24:, -40, 0] = np.nan  # os 20% finais (24..29) sem passo íntegro em 40 passos

    assert split_rows(data, 39)[2] == 24
    with pytest.raises(TrainingError) as raised:
        split_rows(data, 40)

    assert str(raised.value) == (
        "Nenhuma análise utilizável nos 20% finais do conjunto para a janela de 40 passos; "
        "revise as lacunas do conjunto ou reduza a janela"
    )


def test_poucas_analises_antes_do_corte_falha_com_mensagem():
    """26 utilizáveis no total, mas só 7 antes do corte: o `TimeSeriesSplit(3)` do tune exige 8."""
    data = _gapped(100)
    data.x[:73, -40, 0] = np.nan

    with pytest.raises(TrainingError) as raised:
        split_rows(data, 40)

    assert str(raised.value) == (
        "São necessárias ao menos 8 análises utilizáveis antes do corte dos 20% finais "
        "para a janela de 40 passos; há 7"
    )


def test_lacuna_no_trecho_de_ajuste_nao_reprova_conjunto_com_20_utilizaveis():
    """21 análises (5 de teste) e uma lacuna no ajuste: 20 utilizáveis, 15 de ajuste."""
    data = _gapped(21)
    data.x[3, -3, 0] = np.nan

    x, y, n_fit = split_rows(data, 5)

    assert (len(y), n_fit) == (20, 15)
    assert x.shape == (20, 5, 2)


def test_poucas_analises_utilizaveis_falha_com_a_mensagem_do_minimo():
    data = _gapped(30)
    data.x[:17, -50, 0] = np.nan

    with pytest.raises(TrainingError) as raised:
        split_rows(data, 50)

    assert str(raised.value) == (
        "São necessárias ao menos 20 análises utilizáveis para a janela de 50 passos; há 12"
    )


def test_janela_de_um_passo_vai_no_singular_e_nao_sugere_reduzi_la():
    sem_teste = _gapped(30)
    sem_teste.x[24:, -1, 0] = np.nan
    poucas = _gapped(30)
    poucas.x[:18, -1, 0] = np.nan

    with pytest.raises(TrainingError) as raised:
        split_rows(sem_teste, 1)
    assert str(raised.value) == (
        "Nenhuma análise utilizável nos 20% finais do conjunto para a janela de 1 passo; "
        "revise as lacunas do conjunto"
    )
    with pytest.raises(TrainingError) as raised:
        split_rows(poucas, 1)
    assert str(raised.value) == (
        "São necessárias ao menos 20 análises utilizáveis para a janela de 1 passo; há 12"
    )
