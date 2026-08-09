"""Modelo tipado do config do bloco MPC + derivação pura de horizontes/dimensão (spec F4 §2).

`MpcConfig` espelha o esqueleto normativo da spec F4 §2.1 — o config inteiro vive no nó React
Flow do `graph_json`, como Script/TFS (decisão A-8/A-9). Este módulo cuida só da **forma**
(RF-601/602/604, ADR-013): ids estáveis com prefixo por categoria, `pid` opcional por MV,
`params` genéricos do par. A forma exata dos `params` por `kind` da linha e a completude são
validação semântica — `ottima_core.flowgraph.validate` (tarefa 1.2 do plano F4a).

`derive_horizons` e `mpc_state_dimension` são funções puras (spec §2.2-5/§2.2-7, RF-603/608):
computam e devolvem o valor, sem aplicar as reprovações 422 (Np<2, Np>120) — essas são
política da validação semântica, que enxerga o resultado devolvido aqui e decide.
"""

import math
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RowKind = Literal["selfreg", "integrating"]
TargetMode = Literal["rcas", "cas", "rout"]


def _exigir_prefixo(value: str, prefixo: str, categoria: str) -> str:
    """Confere o prefixo estável do id por categoria (spec §2.1-1); mensagem pt-BR vira 422."""
    if not value.startswith(prefixo):
        raise ValueError(f"id de {categoria} deve começar com '{prefixo}' (recebido: {value!r})")
    return value


class Limits(BaseModel):
    """Faixa `{min, max}` — limites de MV (`limits`) ou setpoint de CV (`sp_limits`)."""

    model_config = ConfigDict(extra="forbid")

    min: float
    max: float


class Range(BaseModel):
    """Faixa `{low, high}` de uma Restrição."""

    model_config = ConfigDict(extra="forbid")

    low: float
    high: float


class ModeValues(BaseModel):
    """Valores de modo do PID — `auto` devolve, `target` assume (spec §2.1-4)."""

    model_config = ConfigDict(extra="forbid")

    auto: int
    target: int


class PidBinding(BaseModel):
    """Amarração de tags do PID de uma MV (spec §2.1-3, RF-604)."""

    model_config = ConfigDict(extra="forbid")

    write_tag_id: int
    target_mode: TargetMode
    mode_cmd_tag_id: int
    mode_read_tag_id: int | None = None
    readback_tag_id: int
    mode_values: ModeValues


class MvVar(BaseModel):
    """Variável manipulada. Sem `pid` ⇒ MV "direta" (spec §2.1-3)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    eu: str
    limits: Limits
    du_max: float
    initial_value: float = 0.0
    pid: PidBinding | None = None

    @field_validator("id")
    @classmethod
    def _valida_prefixo(cls, value: str) -> str:
        return _exigir_prefixo(value, "mv_", "MV")


class CvVar(BaseModel):
    """Variável controlada — linha da matriz `models` (spec §2.1-2)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    eu: str
    kind: RowKind
    tss: float
    weight: float
    sp_limits: Limits

    @field_validator("id")
    @classmethod
    def _valida_prefixo(cls, value: str) -> str:
        return _exigir_prefixo(value, "cv_", "CV")


class ConstraintVar(BaseModel):
    """Restrição — também linha da matriz `models`; soft constraint na montagem (spec §3.4)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    eu: str
    kind: RowKind
    tss: float
    range: Range
    priority: int = Field(ge=1)

    @field_validator("id")
    @classmethod
    def _valida_prefixo(cls, value: str) -> str:
        return _exigir_prefixo(value, "co_", "Restrição")


class DvVar(BaseModel):
    """Variável de distúrbio — futura = último valor medido, constante no horizonte (§3.2)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    eu: str
    range: Range | None = None

    @field_validator("id")
    @classmethod
    def _valida_prefixo(cls, value: str) -> str:
        return _exigir_prefixo(value, "dv_", "DV")


class MpcVariables(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mvs: list[MvVar]
    cvs: list[CvVar]
    constraints: list[ConstraintVar]
    dvs: list[DvVar]


class PairModel(BaseModel):
    """Par `models[linha][coluna]` (spec §2.1-2); `params` genérico — completude é da 1.2."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    params: dict[str, float]


class MpcConfig(BaseModel):
    """Config do bloco MPC — vive inteiro no `graph_json` (spec §2.1, decisão A-8/A-9)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    multiplier: int = Field(ge=1)
    variables: MpcVariables
    models: dict[str, dict[str, PairModel]]


class Horizons(BaseModel):
    """Horizontes derivados do multiplicador, Ts do flow e TSS das linhas (spec §2.2-5)."""

    model_config = ConfigDict(extra="forbid")

    ts_mpc: float
    np: int
    nc: int


def derive_horizons(multiplier: int, ts_flow: float, tss: Sequence[float]) -> Horizons:
    """Deriva `Ts_mpc`, `Np` e `Nc` (spec §2.2-5, RF-603).

    Função pura: devolve `Np` bruto, mesmo fora do teto `[2, 120]` — a reprovação 422
    (Np<2 / Np>120) é decisão de política da validação semântica (tarefa 1.2), que enxerga o
    valor devolvido aqui e decide.
    """
    ts_mpc = multiplier * ts_flow
    np_ = math.ceil(max(tss) / ts_mpc)
    nc = max(2, math.ceil(np_ / 4))
    return Horizons(ts_mpc=ts_mpc, np=np_, nc=nc)


def mpc_state_dimension(config: MpcConfig, ts_mpc: float) -> int:
    """Dimensão do estado agregado do modelo do-mpc (spec §2.2-7).

    Soma, por par HABILITADO da matriz `models`: 2 estados se a linha é `selfreg` (SOPDT), 1
    se `integrating` (IOPDT); mais `round(theta/Ts_mpc)` amostras de atraso — arredondamento
    banker's do `round()` do Python, a mesma convenção do TFS (spec §3.1, fecha débito m2);
    mais uma por MV (estado aumentado `u_prev`, §3.5 — o bias é `_tvp` e não conta).
    """
    row_kind: dict[str, RowKind] = {
        var.id: var.kind for var in (*config.variables.cvs, *config.variables.constraints)
    }
    dimension = len(config.variables.mvs)
    for row_id, cols in config.models.items():
        kind = row_kind[row_id]
        for pair in cols.values():
            if not pair.enabled:
                continue
            dimension += 2 if kind == "selfreg" else 1
            dimension += round(pair.params["theta"] / ts_mpc)
    return dimension
