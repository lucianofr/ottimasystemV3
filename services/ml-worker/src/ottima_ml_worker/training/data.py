"""Dados de treino do sensor virtual (RF-587, SPEC_SENSOR_VIRTUAL §8.1): carga dos conjuntos,
janela útil, divisão em ordem de tempo e métricas em unidade de engenharia."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ottima_core.softsensor import unpack_dataset

MIN_TRAIN_ROWS = 20


class TrainingError(ValueError):
    """Falha esperada do treino; a mensagem (pt-BR) vira o `error` do job."""


@dataclass(frozen=True)
class TrainData:
    """Análises em ordem crescente de `ts`; `x` é `[n, 256, d]` com `nan` nas lacunas."""

    x: np.ndarray
    y: np.ndarray
    ts: np.ndarray


def load_train_data(blobs: Sequence[bytes]) -> TrainData:
    parts = [unpack_dataset(blob) for blob in blobs]
    x, y, ts = (np.concatenate([p[i] for p in parts]) for i in range(3))
    order = np.argsort(ts, kind="stable")
    return TrainData(x=x[order], y=y[order], ts=ts[order])


def select_rows(data: TrainData, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Últimos `k` passos de cada análise, só das linhas sem lacuna nesses passos."""
    x = data.x[:, -k:, :]
    usable = np.isfinite(x).all(axis=(1, 2)) & np.isfinite(data.y)
    return x[usable], data.y[usable]


def chrono_split(n: int, test_fraction: float = 0.2) -> tuple[slice, slice]:
    """Treino = primeiras linhas, teste = últimas (ao menos 1): nunca embaralha."""
    n_test = max(1, math.ceil(test_fraction * n))
    return slice(0, n - n_test), slice(n - n_test, n)


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    err = np.asarray(y_pred, dtype=np.float64) - y_true
    constant = y_true.max() == y_true.min()  # exato; a variância de um constante pode vir ~1e-30
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return {
        "r2": 0.0 if constant else 1.0 - float(err @ err) / ss_tot,
        "rmse": float(np.sqrt(np.mean(err**2))),
        "mae": float(np.mean(np.abs(err))),
    }


def scaling(x_k: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Média e desvio de `x` (por entrada, sobre linhas e passos) e de `y`; desvio zero vira 1,
    como a inferência compartilhada o trata."""
    flat = x_k.reshape(-1, x_k.shape[-1]).astype(np.float64)
    x_std = flat.std(axis=0)
    y_std = float(y.std())
    return flat.mean(axis=0), np.where(x_std == 0.0, 1.0, x_std), float(y.mean()), y_std or 1.0
