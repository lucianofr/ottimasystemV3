"""Sensor virtual: artefato do modelo e inferência numpy dos três métodos (ADR-046)."""

from . import synthetic
from .artifact import (
    BUFFER_STEPS,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_UNPACKED_BYTES,
    METHODS,
    PERIOD_TOLERANCE,
    RANGE_MARGIN,
    ArtifactError,
    InputMeta,
    LoadedModel,
    ModelMeta,
    load_model,
    model_steps,
    pack_weights,
    unpack_weights,
)
from .forward import predict
from .grid import grid_instants, load_grid, staleness_limit_s
from .window import Evaluation, Reason, SampleBuffer, evaluate

__all__ = [
    "BUFFER_STEPS",
    "MAX_ARTIFACT_BYTES",
    "MAX_ARTIFACT_UNPACKED_BYTES",
    "METHODS",
    "PERIOD_TOLERANCE",
    "RANGE_MARGIN",
    "ArtifactError",
    "Evaluation",
    "InputMeta",
    "LoadedModel",
    "ModelMeta",
    "Reason",
    "SampleBuffer",
    "evaluate",
    "grid_instants",
    "load_grid",
    "load_model",
    "model_steps",
    "pack_weights",
    "predict",
    "staleness_limit_s",
    "synthetic",
    "unpack_weights",
]
