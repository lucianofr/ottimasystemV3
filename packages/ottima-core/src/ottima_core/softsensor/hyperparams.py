"""Hiperparâmetros do sensor virtual (RF-587, RF-588, ADR-046): schema, default, limite e faixa
do Optuna numa fonte só. A API, o `ml-worker` e a UI (via `contracts_export`) leem daqui — nenhum
número é digitado duas vezes."""

from collections.abc import Mapping
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class PlsHyperparams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_components: int = Field(3, ge=1, le=50)


class EsnHyperparams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    units: int = Field(500, ge=10, le=500)
    sr: float = Field(0.9, gt=0, le=2.0)
    lr: float = Field(0.3, gt=0, le=1.0)
    rc_connectivity: float = Field(0.1, gt=0, le=1.0)
    input_connectivity: float = Field(0.1, gt=0, le=1.0)
    input_scaling: float = Field(1.0, gt=0, le=5.0)
    ridge: float = Field(1e-6, ge=0, le=1.0)
    warmup: int = Field(100, ge=1, le=256)
    seed: int = Field(42, ge=0, le=99999)


class LstmHyperparams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    units: int = Field(64, ge=8, le=256)
    layers: int = Field(2, ge=1, le=4)
    epochs: int = Field(100, ge=1, le=500)
    batch_size: Literal[8, 16, 32, 64] = 32
    sequence_length: int = Field(10, ge=2, le=256)
    lr: float = Field(1e-3, gt=0, le=0.1)


HYPERPARAMS: dict[str, type[BaseModel]] = {
    "pls": PlsHyperparams,
    "esn": EsnHyperparams,
    "lstm": LstmHyperparams,
}

# Faixas do Optuna (spec §8.2); `kind` em int / float / log (escala log) / choice. O teto efetivo
# de `pls.n_components` é `min(n_entradas, n_linhas - 1, 20)`, aplicado onde o estudo é montado.
SEARCH_SPACE: dict[str, dict[str, dict[str, Any]]] = {
    "pls": {
        "n_components": {"kind": "int", "low": 1, "high": 20},
    },
    "esn": {
        "units": {"kind": "int", "low": 100, "high": 500},
        "sr": {"kind": "float", "low": 0.1, "high": 1.5},
        "rc_connectivity": {"kind": "float", "low": 0.01, "high": 0.99},
        "input_connectivity": {"kind": "float", "low": 0.01, "high": 0.99},
        "lr": {"kind": "float", "low": 0.01, "high": 1.0},
        "ridge": {"kind": "log", "low": 1e-8, "high": 1e-1},
        "input_scaling": {"kind": "float", "low": 0.1, "high": 3.0},
        "warmup": {"kind": "int", "low": 10, "high": 200},
    },
    "lstm": {
        "units": {"kind": "int", "low": 16, "high": 256},
        "layers": {"kind": "int", "low": 1, "high": 4},
        "epochs": {"kind": "int", "low": 30, "high": 200},
        "batch_size": {"kind": "choice", "choices": [8, 16, 32, 64]},
        "sequence_length": {"kind": "int", "low": 3, "high": 50},
        "lr": {"kind": "log", "low": 1e-4, "high": 1e-2},
    },
}

# Campo que define a janela de amostras por método; `pls` não tem (janela 1).
_WINDOW_FIELD = {"esn": "warmup", "lstm": "sequence_length"}


def _describe(model: type[BaseModel], error: Mapping[str, Any]) -> str:
    """Texto pt-BR de um erro do Pydantic; tipo não mapeado cai na mensagem original."""
    ctx = error.get("ctx") or {}
    match error["type"]:
        case "less_than_equal":
            return f"deve ser no máximo {ctx['le']}"
        case "greater_than_equal":
            return f"deve ser no mínimo {ctx['ge']}"
        case "greater_than":
            return f"deve ser maior que {ctx['gt']}"
        case "extra_forbidden":
            return "não existe para este método"
        case "literal_error":
            choices = get_args(model.model_fields[error["loc"][0]].annotation)
            return f"deve ser um de {', '.join(map(str, choices))}"
        case "int_type" | "int_parsing" | "int_from_float":
            return "deve ser um número inteiro"
        case "float_type" | "float_parsing":
            return "deve ser um número"
        case _:
            return str(error["msg"])


def parse_hyperparams(method: str, raw: Mapping[str, Any] | None) -> BaseModel:
    """Valida `raw` contra o schema do método; `None`/`{}` dão os defaults.

    `ValidationError` vira `ValueError` em pt-BR: o runner de jobs mostra esse texto ao usuário."""
    model = HYPERPARAMS.get(method)
    if model is None:
        raise ValueError(f"Método de sensor virtual desconhecido: '{method}'")
    try:
        return model.model_validate(raw or {})
    except ValidationError as exc:
        raise ValueError(
            "; ".join(
                f"Hiperparâmetro '{error['loc'][0]}' do método {method}: {_describe(model, error)}"
                if error["loc"]
                else f"Hiperparâmetros do método {method}: devem ser um objeto"
                for error in exc.errors()
            )
        ) from None


def window_of(method: str, hp: BaseModel) -> int:
    """Amostras de histórico por predição: pls 1; esn `warmup`; lstm `sequence_length`."""
    return 1 if method == "pls" else int(getattr(hp, _WINDOW_FIELD[method]))
