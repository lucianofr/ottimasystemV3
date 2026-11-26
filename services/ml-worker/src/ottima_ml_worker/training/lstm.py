"""LSTM (RF-587): PyTorch em CPU, Adam, MSE e parada antecipada. O export segue a ordem de
portões i, f, g, o do PyTorch, a que `forward._lstm` assume."""

import math
from collections.abc import Callable

import numpy as np
import torch
from pydantic import BaseModel
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from ottima_core.config import get_settings

from .data import scaling

PATIENCE = 10


class Net(nn.Module):
    def __init__(self, d: int, units: int, layers: int) -> None:
        super().__init__()
        self.lstm = nn.LSTM(d, units, num_layers=layers, batch_first=True)
        self.fc = nn.Linear(units, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.fc(out[:, -1]).squeeze(-1)  # só o último passo da última camada


def _numpy(t: torch.Tensor) -> np.ndarray:
    return t.detach().cpu().numpy().astype(np.float64)


def export_weights(
    net: Net, x_mean: np.ndarray, x_std: np.ndarray, y_mean: float, y_std: float
) -> dict[str, np.ndarray]:
    weights = {
        f"{key}_{k}": _numpy(getattr(net.lstm, f"{name}_l{k}"))
        for k in range(net.lstm.num_layers)
        for name, key in (
            ("weight_ih", "w_ih"),
            ("weight_hh", "w_hh"),
            ("bias_ih", "b_ih"),
            ("bias_hh", "b_hh"),
        )
    }
    return weights | {
        "fc_w": _numpy(net.fc.weight[0]),
        "fc_b": _numpy(net.fc.bias),
        "x_mean": x_mean,
        "x_std": x_std,
        "y_mean": np.array([y_mean]),
        "y_std": np.array([y_std]),
    }


def fit_lstm(
    x_k: np.ndarray,
    y: np.ndarray,
    hp: BaseModel,
    *,
    epoch_cb: Callable[[int, float], None] | None = None,
) -> dict[str, np.ndarray]:
    """`epoch_cb(epoch, perda média da época)`, com `epoch` a partir de 1."""
    torch.set_num_threads(get_settings().ml_threads)
    torch.manual_seed(0)  # sem semente nos hiperparâmetros: a mesma entrada dá o mesmo modelo
    x_mean, x_std, y_mean, y_std = scaling(x_k, y)
    xs = torch.tensor((x_k - x_mean) / x_std, dtype=torch.float32)
    ys = torch.tensor((y - y_mean) / y_std, dtype=torch.float32)
    net = Net(x_k.shape[-1], hp.units, hp.layers)
    optimizer = torch.optim.Adam(net.parameters(), lr=hp.lr)
    loader = DataLoader(TensorDataset(xs, ys), batch_size=hp.batch_size, shuffle=True)

    best, stale = math.inf, 0
    for epoch in range(1, hp.epochs + 1):
        total = 0.0
        for xb, yb in loader:
            optimizer.zero_grad()
            loss = nn.functional.mse_loss(net(xb), yb)
            loss.backward()
            optimizer.step()
            total += loss.item() * len(xb)
        mean_loss = total / len(xs)
        if epoch_cb is not None:
            epoch_cb(epoch, mean_loss)
        best, stale = (mean_loss, 0) if mean_loss < best else (best, stale + 1)
        if stale >= PATIENCE:
            break
    return export_weights(net, x_mean, x_std, y_mean, y_std)
