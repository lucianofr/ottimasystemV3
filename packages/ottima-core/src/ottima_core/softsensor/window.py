"""Buffer de amostras por modelo e regra de qualidade da saída (RF-583, ADR-046 D5; spec §5.3-5.4).

O bloco chama `evaluate` a cada passo de modelo. Aqui só existe o que o modelo decide sozinho;
"manter o último valor calculado" (★ do §5.4) e a qualidade entre passos são do bloco.
"""

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from ottima_core.signal import Quality

from .artifact import BUFFER_STEPS, RANGE_MARGIN, LoadedModel
from .forward import predict

Reason = Literal["ok", "incomplete", "bad_sample", "non_finite", "uncertain", "extrapolating"]


class SampleBuffer:
    """Anel das últimas `capacity` amostras do período de UM modelo: valores crus + qualidade.

    Invariante: valor não finito (ou porta sem valor) está sempre gravado como `nan` com BAD.
    As linhas guardadas nunca são alteradas, então `copy` pode compartilhá-las.
    """

    def __init__(self, n_inputs: int, capacity: int = BUFFER_STEPS) -> None:
        self.n_inputs = n_inputs
        self._rows: deque[tuple[np.ndarray, Quality]] = deque(maxlen=capacity)

    def _row(self, values: Sequence[float | None], quality: Quality) -> tuple[np.ndarray, Quality]:
        row = np.array(values, dtype=np.float64)  # None vira nan
        if row.shape != (self.n_inputs,):
            raise ValueError(f"amostra com forma {row.shape}, esperado ({self.n_inputs},)")
        finite = np.isfinite(row)
        if finite.all():
            return row, quality
        return np.where(finite, row, np.nan), Quality.BAD

    def push(self, values: Sequence[float | None], quality: Quality) -> None:
        self._rows.append(self._row(values, quality))

    def preload(self, values: np.ndarray, qualities: Sequence[Quality]) -> None:
        """Substitui o conteúdo; `values` é `[n, n_inputs]`, mais antiga primeiro."""
        if len(values) != len(qualities):
            raise ValueError(f"{len(values)} linhas para {len(qualities)} qualidades")
        rows = [self._row(v, q) for v, q in zip(values, qualities, strict=True)]
        self._rows.clear()
        self._rows.extend(rows)  # além da capacidade, ficam as mais novas

    def __len__(self) -> int:
        return len(self._rows)

    def last(self, k: int) -> tuple[np.ndarray, tuple[Quality, ...]] | None:
        """As `k` mais recentes, da mais antiga para a mais nova; `None` se houver menos de `k`."""
        if k < 1:
            raise ValueError(f"k deve ser >= 1, recebido {k}")
        if len(self._rows) < k:
            return None
        rows = list(self._rows)[-k:]
        return np.stack([v for v, _ in rows]), tuple(q for _, q in rows)

    def copy(self) -> "SampleBuffer":
        dup = SampleBuffer(self.n_inputs, self._rows.maxlen)
        dup._rows.extend(self._rows)
        return dup


@dataclass(frozen=True)
class Evaluation:
    value: float | None
    quality: Quality
    reason: Reason


def evaluate(model: LoadedModel, buffer: SampleBuffer) -> Evaluation:
    """Spec §5.4, nesta ordem; só a janela de `warmup_steps` amostras conta."""
    window = buffer.last(model.meta.warmup_steps)
    if window is None:
        return Evaluation(None, Quality.BAD, "incomplete")
    x, qualities = window
    if Quality.BAD in qualities:
        return Evaluation(None, Quality.BAD, "bad_sample")
    value = predict(model, x)  # ValueError se o buffer não tem as portas do modelo
    if not math.isfinite(value):
        return Evaluation(None, Quality.BAD, "non_finite")
    lo = np.array([i.min for i in model.meta.inputs])
    hi = np.array([i.max for i in model.meta.inputs])
    margin = RANGE_MARGIN * (hi - lo)
    if ((x < lo - margin) | (x > hi + margin)).any():
        return Evaluation(value, Quality.UNCERTAIN, "extrapolating")
    if Quality.UNCERTAIN in qualities:
        return Evaluation(value, Quality.UNCERTAIN, "uncertain")
    return Evaluation(value, Quality.GOOD, "ok")
