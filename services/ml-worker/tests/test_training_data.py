"""Dados de treino do sensor virtual (RF-587): carga, janela útil, métricas (o corte no tempo é
do test_training_split.py)."""

import numpy as np
import pytest

from ottima_core.softsensor import DATASET_STEPS, pack_dataset
from ottima_ml_worker.training import load_train_data, metrics, select_rows
from ottima_ml_worker.training.data import TrainData


def _rows(values: list[float], ts: list[float], d: int = 2) -> bytes:
    """Linha i com todos os passos iguais a `values[i]`: dá para ver para onde a linha foi."""
    x = np.broadcast_to(np.array(values, dtype=np.float32)[:, None, None], (len(values), 256, d))
    return pack_dataset(x, np.array(values), np.array(ts))


def test_load_concatena_e_ordena_por_tempo():
    a = _rows([1.0, 2.0, 3.0], [30.0, 10.0, 50.0])
    b = _rows([4.0, 5.0], [20.0, 40.0])

    data = load_train_data([a, b])

    assert data.ts.tolist() == [10.0, 20.0, 30.0, 40.0, 50.0]
    assert data.y.tolist() == [2.0, 4.0, 1.0, 5.0, 3.0]
    assert data.x.shape == (5, DATASET_STEPS, 2)
    assert data.x[:, 0, 0].tolist() == data.y.tolist()  # x acompanhou y na ordenação


def test_select_rows_usa_so_os_ultimos_k_passos():
    x = np.zeros((3, DATASET_STEPS, 2), dtype=np.float32)
    x[1, 100, 0] = np.nan  # lacuna no passo 100 de 256
    x[2, -1, 1] = np.nan  # lacuna no último passo
    data = TrainData(x=x, y=np.array([10.0, 11.0, 12.0]), ts=np.arange(3.0))

    x50, y50 = select_rows(data, 50)
    x200, y200 = select_rows(data, 200)

    assert y50.tolist() == [10.0, 11.0]  # o nan do passo 100 está fora dos últimos 50
    assert x50.shape == (2, 50, 2)
    assert y200.tolist() == [10.0]  # e dentro dos últimos 200
    assert x200.shape == (1, 200, 2)


def test_metrics_calcula_r2_rmse_e_mae():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    out = metrics(y, y + np.array([1.0, -1.0, 1.0, -1.0]))

    assert out["rmse"] == pytest.approx(1.0)
    assert out["mae"] == pytest.approx(1.0)
    assert out["r2"] == pytest.approx(1.0 - 4.0 / 5.0)
    assert metrics(y, y)["r2"] == 1.0


def test_metrics_com_alvo_constante_devolve_r2_zero():
    out = metrics(np.full(5, 7.0), np.full(5, 7.1))

    assert out["r2"] == 0.0
    assert out["rmse"] == pytest.approx(0.1)
    assert all(type(v) is float for v in out.values())
