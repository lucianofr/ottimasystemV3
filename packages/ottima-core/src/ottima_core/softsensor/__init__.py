"""Sensor virtual: artefato do modelo e inferência numpy dos três métodos (ADR-046)."""

from . import synthetic
from .artifact import (
    BUFFER_STEPS,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_UNPACKED_BYTES,
    METHODS,
    RANGE_MARGIN,
    ArtifactError,
    InputMeta,
    LoadedModel,
    ModelMeta,
    load_model,
    pack_weights,
    unpack_weights,
)
from .forward import predict

__all__ = [
    "BUFFER_STEPS",
    "MAX_ARTIFACT_BYTES",
    "MAX_ARTIFACT_UNPACKED_BYTES",
    "METHODS",
    "RANGE_MARGIN",
    "ArtifactError",
    "InputMeta",
    "LoadedModel",
    "ModelMeta",
    "load_model",
    "pack_weights",
    "predict",
    "synthetic",
    "unpack_weights",
]
