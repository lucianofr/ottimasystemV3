"""Treino de um método do sensor virtual (RF-587, SPEC_SENSOR_VIRTUAL §8.1): ajusta nos 80%
iniciais, mede nos 20% finais pelo `predict` compartilhado e grava o reajuste sobre 100%."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from pydantic import BaseModel

from ottima_core.softsensor import (
    InputMeta,
    ModelMeta,
    load_model,
    pack_weights,
    predict,
    window_of,
)

from .data import MIN_TRAIN_ROWS, TrainData, TrainingError, chrono_split, metrics, select_rows
from .esn import fit_esn
from .pls import fit_pls

EpochCallback = Callable[[int, float], None]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InputSeed:
    name: str
    eu: str


def fit(
    method: str,
    x_k: np.ndarray,
    y: np.ndarray,
    hp: BaseModel,
    *,
    epoch_cb: EpochCallback | None = None,
) -> dict[str, np.ndarray]:
    """Pesos no formato do artefato; `x_k` é `[n, k, d]`."""
    if method == "pls":
        return fit_pls(x_k, y, hp)
    if method == "esn":
        return fit_esn(x_k, y, hp)
    from .lstm import fit_lstm  # torch só carrega quando o método é o LSTM

    return fit_lstm(x_k, y, hp, epoch_cb=epoch_cb)


def _finite(weights: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    # O artefato é float32: um peso finito em float64 acima de 3,4e38 viraria inf no `pack_weights`.
    if not all(
        np.isfinite(v).all() and np.isfinite(np.asarray(v, dtype=np.float32)).all()
        for v in weights.values()
    ):
        raise TrainingError(
            "O treino produziu pesos não finitos (o modelo divergiu); "
            "reduza a taxa de aprendizado ou revise o conjunto"
        )
    return weights


def _fit_checked(
    method: str, x_k: np.ndarray, y: np.ndarray, hp: BaseModel, epoch_cb: EpochCallback | None
) -> dict[str, np.ndarray]:
    """`fit` + recusa de pesos não finitos. Sklearn, scipy e numpy levantam `ValueError` com texto
    em inglês, e o runner repassa todo `ValueError` à página: só `TrainingError` passa direto."""
    try:
        return _finite(fit(method, x_k, y, hp, epoch_cb=epoch_cb))
    except TrainingError:
        raise
    except ValueError as exc:
        logger.exception("ajuste do %s falhou", method.upper())
        raise TrainingError(
            f"O ajuste do {method.upper()} falhou com estes dados (ver o log do ml-worker)"
        ) from exc


def train(
    method: str,
    data: TrainData,
    hp: BaseModel,
    *,
    inputs: Sequence[InputSeed],
    output_name: str,
    output_eu: str,
    period_s: float,
    dataset_ids: Sequence[int],
    epoch_cb: EpochCallback | None = None,
) -> tuple[ModelMeta, bytes, dict]:
    """`epoch_cb` recebe as épocas do ajuste nos 80% e, depois, as do reajuste sobre 100%."""
    if data.x.shape[2] != len(inputs):
        raise TrainingError(
            f"O conjunto tem {data.x.shape[2]} entrada(s), "
            f"mas foram informados {len(inputs)} nome(s) de entrada"
        )
    k = window_of(method, hp)
    x, y = select_rows(data, k)
    n = len(y)
    if n < MIN_TRAIN_ROWS:
        raise TrainingError(
            f"São necessárias ao menos {MIN_TRAIN_ROWS} análises utilizáveis "
            f"para a janela de {k} passos; há {n}"
        )
    fit_rows, test_rows = chrono_split(n)
    meta = ModelMeta(
        schema_version=1,
        method=method,
        period_s=period_s,
        inputs=[
            InputMeta(name=seed.name, eu=seed.eu, min=float(lo), max=float(hi))
            for seed, lo, hi in zip(inputs, x.min(axis=(0, 1)), x.max(axis=(0, 1)), strict=True)
        ],
        output_name=output_name,
        output_eu=output_eu,
        hyperparams=hp.model_dump(),
        warmup_steps=k,
        trained_at=datetime.now(UTC),
        dataset_ids=list(dataset_ids),
    )

    weights = _fit_checked(method, x[fit_rows], y[fit_rows], hp, epoch_cb)
    candidate = load_model(0, meta.model_dump(mode="json"), pack_weights(weights))
    predicted = np.array([predict(candidate, window) for window in x[test_rows]])
    if not np.isfinite(predicted).all():
        raise TrainingError("O modelo treinado produziu predições não finitas no teste")

    final = _fit_checked(method, x, y, hp, epoch_cb)
    meta = meta.model_copy(update={"metrics": metrics(y[test_rows], predicted)})
    return (
        meta,
        pack_weights(final),
        {"rows_used": n, "rows_test": test_rows.stop - test_rows.start},
    )
