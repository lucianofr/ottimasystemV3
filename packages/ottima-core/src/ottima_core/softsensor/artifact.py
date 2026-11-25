"""Artefato do modelo do sensor virtual (RF-581, ADR-046 D3; spec §6).

Contrato entre quem treina (ml-worker), quem opera (flow-runtime) e o export: metadados
(`ModelMeta`) mais um `.npz` de pesos em float32, lido SEMPRE com `allow_pickle=False`.
"""

import io
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

METHODS: tuple[str, ...] = ("pls", "esn", "lstm")
BUFFER_STEPS = 256
RANGE_MARGIN = 0.05
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_UNPACKED_BYTES = 32 * 1024 * 1024  # teto do descomprimido: contém zip bomb


class ArtifactError(ValueError):
    """Artefato ilegível, fora do teto, com metadados inválidos ou pesos incoerentes."""


class InputMeta(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)  # config não propaga a modelos aninhados

    name: str
    eu: str = ""
    min: float
    max: float


class ModelMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: Literal[1]
    method: Literal["pls", "esn", "lstm"]
    period_s: float = Field(gt=0)
    inputs: list[InputMeta] = Field(min_length=1, max_length=32)
    output_name: str
    output_eu: str = ""
    hyperparams: dict[str, float]
    warmup_steps: int = Field(ge=1, le=BUFFER_STEPS)
    metrics: dict[str, float] = {}
    trained_at: datetime
    dataset_ids: list[int] = []


def _check_limits(blob: bytes) -> None:
    """Rejeição precoce, antes de ler qualquer entrada: bytes do blob e bytes DECLARADOS.

    O `file_size` do diretório central é dado pelo autor do zip e pode mentir: este teste só
    recusa cedo o artefato honesto e grande. O que limita a leitura de verdade está em
    `unpack_weights`: `zf.open` para a leitura em `file_size` e `read_array` lê em blocos.
    """
    if len(blob) > MAX_ARTIFACT_BYTES:
        raise ArtifactError(
            f"artefato de {len(blob)} bytes passa do teto de {MAX_ARTIFACT_BYTES} bytes"
        )
    # BadZipFile (truncado ou não-zip) sobe para quem chama, que embrulha em ArtifactError.
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        unpacked = sum(info.file_size for info in zf.infolist())
    if unpacked > MAX_ARTIFACT_UNPACKED_BYTES:
        raise ArtifactError(
            f"artefato descomprimido de {unpacked} bytes passa do teto de "
            f"{MAX_ARTIFACT_UNPACKED_BYTES} bytes"
        )


def pack_weights(arrays: Mapping[str, np.ndarray]) -> bytes:
    f32 = {k: np.asarray(v, dtype=np.float32) for k, v in arrays.items()}
    raw = sum(v.nbytes for v in f32.values())
    if raw > MAX_ARTIFACT_UNPACKED_BYTES:  # antes de comprimir centenas de MB à toa
        raise ArtifactError(
            f"pesos descomprimidos de {raw} bytes passam do teto de "
            f"{MAX_ARTIFACT_UNPACKED_BYTES} bytes"
        )
    buf = io.BytesIO()
    np.savez_compressed(buf, **f32)
    blob = buf.getvalue()
    _check_limits(blob)  # nunca grava o que unpack_weights recusaria (cabeçalhos .npy incluídos)
    return blob


def unpack_weights(blob: bytes) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    try:
        _check_limits(blob)
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for info in zf.infolist():
                if not info.filename.endswith(".npy"):
                    raise ArtifactError(f"entrada {info.filename!r} do artefato não é .npy")
                # Não usar np.load: se o magic do .npy não bate, ele cai em `zip.read(chave)`,
                # que descomprime a entrada inteira de uma vez, ignorando o `file_size` forjado.
                # `zf.open` + `read_array` lê em blocos e para em `file_size`; magic ruim falha.
                with zf.open(info) as fh:
                    out[info.filename.removesuffix(".npy")] = np.lib.format.read_array(
                        fh, allow_pickle=False
                    )
    except ArtifactError:
        raise
    except Exception as exc:  # zip truncado, não-npz, magic ruim, pickle recusado, CRC
        raise ArtifactError(f"artefato de pesos ilegível: {exc}") from exc
    if any(v.dtype.kind not in "fiu" for v in out.values()):
        raise ArtifactError("artefato de pesos com array não numérico")
    return out


@dataclass(frozen=True, eq=False)  # eq=False: `==` sobre dict de arrays levanta ValueError
class LoadedModel:
    model_id: int
    meta: ModelMeta
    weights: dict[str, np.ndarray]

    @property
    def n_inputs(self) -> int:
        return len(self.meta.inputs)


_FIXED_KEYS = {
    "pls": ("w", "b"),
    "esn": ("W", "Win", "bias", "Wout", "b_out", "lr", "x_mean", "x_std", "y_mean", "y_std"),
}
_LSTM_LAYER_KEY = re.compile(r"(?:w_ih|w_hh|b_ih|b_hh)_(\d{1,4})")
_LSTM_LAYER_PARTS = ("w_ih", "w_hh", "b_ih", "b_hh")
_LSTM_TAIL = ("fc_w", "fc_b", "x_mean", "x_std", "y_mean", "y_std")


def _lstm_layers(weights: Mapping[str, np.ndarray]) -> int:
    # Maior índice visto, não contagem: camada com chave faltando é erro, não camada a menos.
    indices = [int(m[1]) for k in weights if (m := _LSTM_LAYER_KEY.fullmatch(k))]
    layers = max(indices) + 1 if indices else 0
    if not 1 <= layers <= len(weights):  # sem camadas, ou índice absurdo (não gera chaves demais)
        raise ArtifactError(f"pesos lstm com {layers} camadas (chaves w_ih/w_hh/b_ih/b_hh_k)")
    return layers


def _required_keys(method: str, weights: Mapping[str, np.ndarray]) -> tuple[str, ...]:
    if method != "lstm":
        return _FIXED_KEYS[method]
    layers = _lstm_layers(weights)
    return (
        *(f"{p}_{k}" for k in range(layers) for p in _LSTM_LAYER_PARTS),
        *_LSTM_TAIL,
    )


def _expected_shapes(method: str, n: int, weights: Mapping[str, np.ndarray]) -> dict[str, tuple]:
    one = (1,)
    norm = {"x_mean": (n,), "x_std": (n,), "y_mean": one, "y_std": one}
    if method == "pls":
        return {"w": (n,), "b": one}
    if method == "esn":
        u = weights["Wout"].size  # unidades vêm do vetor de saída; o resto é conferido contra u
        return {
            "W": (u, u),
            "Win": (u, n),
            "bias": (u,),
            "Wout": (u,),
            "b_out": one,
            "lr": one,
            **norm,
        }
    u = weights["fc_w"].size
    shapes = {"fc_w": (u,), "fc_b": one, **norm}
    for k in range(_lstm_layers(weights)):
        shapes |= {
            f"w_ih_{k}": (4 * u, n if k == 0 else u),
            f"w_hh_{k}": (4 * u, u),
            f"b_ih_{k}": (4 * u,),
            f"b_hh_{k}": (4 * u,),
        }
    return shapes


def load_model(model_id: int, meta: Mapping[str, Any], blob: bytes) -> LoadedModel:
    """Valida metadados, chaves exigidas do método e formas contra `n_inputs`; pesos em float64."""
    try:
        parsed = ModelMeta.model_validate(dict(meta))
    except ValidationError as exc:
        raise ArtifactError(f"metadados do modelo inválidos: {exc}") from exc
    weights = unpack_weights(blob)
    ausentes = [k for k in _required_keys(parsed.method, weights) if k not in weights]
    if ausentes:
        raise ArtifactError(f"pesos {parsed.method} sem as chaves {ausentes}")
    esperado = _expected_shapes(parsed.method, len(parsed.inputs), weights)
    erradas = [
        f"{k}: esperado {shape}, veio {weights[k].shape}"
        for k, shape in esperado.items()
        if weights[k].shape != shape
    ]
    if erradas:
        raise ArtifactError(f"pesos {parsed.method} com forma incoerente: {'; '.join(erradas)}")
    return LoadedModel(model_id, parsed, {k: v.astype(np.float64) for k, v in weights.items()})
