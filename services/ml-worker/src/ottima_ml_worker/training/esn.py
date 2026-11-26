"""ESN (RF-587): reservatório em numpy e saída por regressão ridge. A recorrência é a de
`ottima_core.softsensor.forward._esn`, em lote sobre todas as linhas."""

import numpy as np
from pydantic import BaseModel
from sklearn.linear_model import Ridge

from .data import scaling


def reservoir_states(
    xs: np.ndarray, W: np.ndarray, Win: np.ndarray, bias: np.ndarray, lr: float
) -> np.ndarray:
    """Estado final `[m, units]` de cada janela padronizada `xs` `[m, k, d]`, do estado zero."""
    s = np.zeros((len(xs), len(W)))
    for t in range(xs.shape[1]):  # a entrada entra passo a passo: `[m, k, units]` não cabe em 500
        s = (1.0 - lr) * s + lr * np.tanh(s @ W.T + xs[:, t] @ Win.T + bias)
    return s


def _f32(a: np.ndarray | float) -> np.ndarray:
    """O artefato é float32: o ridge tem de ajustar os estados que a inferência vai produzir."""
    return np.asarray(a, dtype=np.float32).astype(np.float64)


def fit_esn(x_k: np.ndarray, y: np.ndarray, hp: BaseModel) -> dict[str, np.ndarray]:
    d = x_k.shape[-1]
    rng = np.random.default_rng(hp.seed)
    sparse_w = (rng.random((hp.units, hp.units)) < hp.rc_connectivity) * rng.normal(
        size=(hp.units, hp.units)
    )
    radius = np.abs(np.linalg.eigvals(sparse_w)).max()
    if radius > 0:
        sparse_w *= hp.sr / radius
    win = (
        (rng.random((hp.units, d)) < hp.input_connectivity)
        * rng.uniform(-1.0, 1.0, size=(hp.units, d))
        * hp.input_scaling
    )
    bias = rng.uniform(-1.0, 1.0, size=hp.units)
    x_mean, x_std, y_mean, y_std = scaling(x_k, y)

    w, win, bias, lr = _f32(sparse_w), _f32(win), _f32(bias), _f32(hp.lr)
    x_mean, x_std = _f32(x_mean), _f32(x_std)
    states = reservoir_states((x_k - x_mean) / x_std, w, win, bias, float(lr))
    readout = Ridge(alpha=hp.ridge).fit(states, (y - y_mean) / y_std)
    return {
        "W": w,
        "Win": win,
        "bias": bias,
        "Wout": readout.coef_,
        "b_out": np.array([readout.intercept_]),
        "lr": lr.reshape(1),
        "x_mean": x_mean,
        "x_std": x_std,
        "y_mean": np.array([y_mean]),
        "y_std": np.array([y_std]),
    }
