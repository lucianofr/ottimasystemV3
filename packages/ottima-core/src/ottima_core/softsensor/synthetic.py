"""Artefatos sintéticos e determinísticos para testes (PLS, ESN, LSTM).

Não treinam nada: pesos fixos (ou semeados) que exercitam o contrato do artefato e a conta de
`forward.predict`. Devolvem `(ModelMeta, bytes)`, o mesmo par que o banco guarda.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import numpy as np

from .artifact import InputMeta, ModelMeta, pack_weights

_TRAINED_AT = datetime(2026, 1, 1, tzinfo=UTC)  # fixo: dois artefatos iguais têm metadados iguais


def _meta(
    method: str,
    n_inputs: int,
    period_s: float,
    warmup_steps: int,
    hyperparams: dict[str, float],
    ranges: Sequence[tuple[float, float]] | None = None,
) -> ModelMeta:
    ranges = ranges if ranges is not None else [(-1e6, 1e6)] * n_inputs
    return ModelMeta(
        schema_version=1,
        method=method,
        period_s=period_s,
        inputs=[InputMeta(name=f"x{i}", min=lo, max=hi) for i, (lo, hi) in enumerate(ranges)],
        output_name="y",
        hyperparams=hyperparams,
        warmup_steps=warmup_steps,
        trained_at=_TRAINED_AT,
    )


def _normalization(n_inputs: int) -> dict[str, np.ndarray]:
    return {
        "x_mean": np.zeros(n_inputs),
        "x_std": np.ones(n_inputs),
        "y_mean": np.zeros(1),
        "y_std": np.ones(1),
    }


def pls(
    w: Sequence[float],
    b: float,
    *,
    period_s: float = 1.0,
    ranges: Sequence[tuple[float, float]] | None = None,
) -> tuple[ModelMeta, bytes]:
    meta = _meta("pls", len(w), period_s, 1, {}, ranges)
    return meta, pack_weights({"w": np.array(w), "b": np.array([b])})


def esn(
    n_inputs: int,
    *,
    units: int = 20,
    warmup: int = 5,
    seed: int = 42,
    period_s: float = 1.0,
) -> tuple[ModelMeta, bytes]:
    rng = np.random.default_rng(seed)
    W = rng.normal(size=(units, units))
    W *= 0.9 / np.max(np.abs(np.linalg.eigvals(W)))  # raio espectral 0.9
    weights = {
        "W": W,
        "Win": rng.uniform(-1, 1, size=(units, n_inputs)),
        "bias": rng.uniform(-1, 1, size=units),
        "Wout": rng.normal(size=units),
        "b_out": np.zeros(1),
        "lr": np.array([0.3]),
        **_normalization(n_inputs),
    }
    hyper = {"units": units, "spectral_radius": 0.9, "leak_rate": 0.3, "warmup": warmup}
    return _meta("esn", n_inputs, period_s, warmup, hyper), pack_weights(weights)


def lstm(
    n_inputs: int,
    *,
    units: int = 4,
    layers: int = 2,
    sequence_length: int = 3,
    seed: int = 42,
    period_s: float = 1.0,
) -> tuple[ModelMeta, bytes]:
    rng = np.random.default_rng(seed)
    weights = {"fc_w": rng.normal(scale=0.5, size=units), "fc_b": rng.normal(scale=0.5, size=1)}
    for k in range(layers):
        weights |= {  # portões i, f, g, o em blocos de `units` linhas (ordem do PyTorch)
            f"w_ih_{k}": rng.normal(scale=0.5, size=(4 * units, n_inputs if k == 0 else units)),
            f"w_hh_{k}": rng.normal(scale=0.5, size=(4 * units, units)),
            f"b_ih_{k}": rng.normal(scale=0.5, size=4 * units),
            f"b_hh_{k}": rng.normal(scale=0.5, size=4 * units),
        }
    hyper = {"units": units, "layers": layers, "sequence_length": sequence_length}
    meta = _meta("lstm", n_inputs, period_s, sequence_length, hyper)
    return meta, pack_weights(weights | _normalization(n_inputs))
