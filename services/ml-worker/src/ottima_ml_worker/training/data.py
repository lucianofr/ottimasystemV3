"""Dados de treino do sensor virtual (RF-587, SPEC_SENSOR_VIRTUAL §8.1): carga dos conjuntos,
janela útil, corte treino/teste no tempo e métricas em unidade de engenharia."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ottima_core.softsensor import unpack_dataset

MIN_TRAIN_ROWS = 20
TEST_FRACTION = 0.2
FOLDS = 3  # dobras da validação do `tune` (`TimeSeriesSplit`)
MIN_VALIDATION_ROWS = (
    2  # com uma só o R² não existe; mais que isso reprovaria conjuntos de 20 linhas
)
# Piso de linhas de ajuste (antes do corte). Sem ele o `TimeSeriesSplit` do `tune` levanta
# ValueError em inglês (poucas linhas) ou valida com menos de `MIN_VALIDATION_ROWS`: ele dá
# `n // (FOLDS + 1)` linhas a cada dobra de validação.
MIN_FIT_ROWS = (FOLDS + 1) * MIN_VALIDATION_ROWS


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


def split_rows(data: TrainData, k: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Últimos `k` passos de cada análise, só das linhas sem lacuna nesses passos, e o corte
    treino/teste, feito UMA vez no tempo e antes da janela: as análises dos últimos 20% do conjunto
    (ao menos 1) são teste, qualquer que seja `k`. Devolve `x`, `y` e `n_fit`: as `n_fit` primeiras
    linhas são o ajuste (e a validação do Optuna), as demais o teste.

    Análises com o mesmo `ts` (conjuntos sobrepostos) ficam do mesmo lado: o corte recua até o
    início do empate. Levanta `TrainingError` se a janela deixa poucas linhas utilizáveis, nenhuma
    no teste ou menos de `MIN_FIT_ROWS` no ajuste: `train` e `tune` recusam as mesmas janelas."""
    x = data.x[:, -k:, :]
    usable = np.isfinite(x).all(axis=(1, 2)) & np.isfinite(data.y)
    x, y = x[usable], data.y[usable]
    window = "1 passo" if k == 1 else f"{k} passos"
    if len(y) < MIN_TRAIN_ROWS:
        raise TrainingError(
            f"São necessárias ao menos {MIN_TRAIN_ROWS} análises utilizáveis "
            f"para a janela de {window}; há {len(y)}"
        )
    n_all = len(data.ts)
    cut_ts = data.ts[n_all - max(1, math.ceil(TEST_FRACTION * n_all))]
    n_fit = int(np.count_nonzero(data.ts[usable] < cut_ts))
    if n_fit == len(y):
        raise TrainingError(
            f"Nenhuma análise utilizável nos {TEST_FRACTION:.0%} finais do conjunto "
            f"para a janela de {window}; revise as lacunas do conjunto"
            f"{' ou reduza a janela' if k > 1 else ''}"
        )
    if n_fit < MIN_FIT_ROWS:
        raise TrainingError(
            f"São necessárias ao menos {MIN_FIT_ROWS} análises utilizáveis antes do corte dos "
            f"{TEST_FRACTION:.0%} finais para a janela de {window}; há {n_fit}"
        )
    return x, y, n_fit


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
