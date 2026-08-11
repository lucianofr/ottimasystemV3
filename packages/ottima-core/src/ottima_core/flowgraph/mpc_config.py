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

import hashlib
import json
import math
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RowKind = Literal["selfreg", "integrating"]
TargetMode = Literal["rcas", "cas", "rout"]
SolverName = Literal["highs", "osqp", "gurobi"]


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
    """Variável manipulada. Sem `pid` ⇒ MV "direta" (spec §2.1-3).

    Coordenada da porta: ABSOLUTA, a mesma da variável OPC-UA ligada à saída. `limits`
    (curso do atuador), `du_max` e `initial_value` estão todos nessa coordenada.

    `operating_point`: valor desta MV no ponto em que a matriz `models` foi linearizada.
    Os pares são incrementais (`Δy = K·Δu`, `dy/dt = Ki·Δu`), então o modelo interno é
    alimentado com `u − operating_point` — sem isso uma linha integradora acumula
    `Ki·Ts·u_op` por execução e a predição deriva sozinha (TD-003). `0.0` reproduz o
    comportamento anterior, então config salva antes deste campo continua carregando.

    `readback_tag_id`: tag de leitura com a posição REAL da MV. Em LOCAL a saída acompanha
    essa tag (transferência bumpless para REMOTO); em REMOTO ela é o `u_applied` do solve.
    Só faz sentido na MV direta: com `pid`, quem já cumpre esse papel é
    `pid.readback_tag_id`.

    `du_min`: banda morta do atuador, na mesma EU de `du_max`. Movimento pedido menor que
    ela não é aplicado (a válvula não responderia mesmo) — quem quantiza é o worker, para
    o modelo interno nunca divergir do que foi escrito. `0.0` desliga.

    `move_weight`: fator multiplicativo do peso de movimento desta MV no custo do solve.
    `1.0` mantém o comportamento anterior; maior deixa a MV mais preguiçosa que as outras.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    eu: str
    limits: Limits
    du_max: float
    du_min: float = Field(default=0.0, ge=0.0)
    move_weight: float = Field(default=1.0, gt=0.0)
    initial_value: float = 0.0
    operating_point: float = 0.0
    readback_tag_id: int | None = None
    pid: PidBinding | None = None

    @field_validator("id")
    @classmethod
    def _valida_prefixo(cls, value: str) -> str:
        return _exigir_prefixo(value, "mv_", "MV")

    @model_validator(mode="after")
    def _valida_banda_morta(self) -> "MvVar":
        if self.du_min > self.du_max:
            raise ValueError("du_min deve ser menor ou igual a du_max")
        return self


class CvVar(BaseModel):
    """Variável controlada — linha da matriz `models` (spec §2.1-2).

    `priority`: rank do SSTO (ADR-026 §5). Mesma semântica do `ConstraintVar.priority` do
    ADR-019 — **maior = mais importante**; a desistência por inviabilidade é em ordem
    crescente. Só o LP de regime permanente o consome: o objetivo dinâmico segue usando
    `weight`, e o default `1` deixa todas as CVs no mesmo rank (comportamento de antes do
    campo existir).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    eu: str
    kind: RowKind
    tss: float
    weight: float
    sp_limits: Limits
    priority: int = Field(default=1, ge=1)

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
    """Variável de distúrbio — futura = último valor medido, constante no horizonte (§3.2).

    Coordenada da porta: ABSOLUTA, igual à da MV. `operating_point` é o valor desta DV no
    ponto de linearização da matriz `models`; o modelo interno recebe `d − operating_point`.
    É o que permite ligar a medida crua da planta direto na porta, sem bloco de
    condicionamento antes do MPC.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    eu: str
    range: Range | None = None
    operating_point: float = 0.0

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


class EconomicsConfig(BaseModel):
    """Camada econômica do SSTO (ADR-026 §9) — estrutura pronta para a UI futura.

    `costs`: `var_id` (MV, CV ou Restrição) -> preço no objetivo `min cᵀ·ΔMV`. **Negativo
    maximiza** a variável. Preço de linha (CV/Restrição) é projetado no espaço de decisão
    por `c_row·G` na montagem do LP — a variável de decisão continua sendo só `ΔMV`.

    `slack_weight`: peso base da folga das linhas soft; o peso efetivo por linha é
    `slack_weight × priority` (primeira linha de defesa contra inviabilidade, ADR-026 §6).

    `detuning_weight` (ρ): mitigação de **LP flipping** (ADR-026 §8) — `ρ > 0` acrescenta
    `ρ‖ΔMV − ΔMV_anterior‖²` ao objetivo e exige um backend QP. `0.0` mantém LP puro.

    `integrating_tolerance` (ε): meia-faixa da condição de taxa nula das linhas
    integradoras (ADR-026 §4), na EU da linha por segundo.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    costs: dict[str, float] = Field(default_factory=dict)
    slack_weight: float = Field(default=1e3, gt=0.0)
    detuning_weight: float = Field(default=0.0, ge=0.0)
    solver: SolverName = "highs"
    integrating_tolerance: float = Field(default=0.0, ge=0.0)


class MpcConfig(BaseModel):
    """Config do bloco MPC — vive inteiro no `graph_json` (spec §2.1, decisão A-8/A-9).

    `economics` ausente (default) = SSTO desligado: o MPC segue com o SP do operador, o
    caminho da F4 (ADR-026 §10). Campo opcional de propósito — config salva antes desta
    feature continua carregando.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    multiplier: int = Field(ge=1)
    variables: MpcVariables
    models: dict[str, dict[str, PairModel]]
    economics: EconomicsConfig | None = None


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


def economics_config_hash(config: MpcConfig) -> str:
    """SHA-256 da versão do problema econômico (ADR-026 §9): custos, limites e ranks.

    Identifica O PROBLEMA que o SSTO resolveu, não o bloco: renomear o MPC ou mexer num
    parâmetro dinâmico (peso de rastreamento, `du_max`) não produz hash novo — mexer num
    preço, num limite ou num rank produz. É o campo que amarra cada registro de auditoria à
    configuração vigente no instante do solve.

    JSON canônico (`sort_keys`, separadores fixos) para o hash não depender da ordem em que
    as chaves chegaram do `graph_json`.
    """
    economics = config.economics
    payload = {
        "economics": None if economics is None else economics.model_dump(mode="json"),
        "mvs": {mv.id: [mv.limits.min, mv.limits.max] for mv in config.variables.mvs},
        "cvs": {
            cv.id: [cv.sp_limits.min, cv.sp_limits.max, cv.priority] for cv in config.variables.cvs
        },
        "constraints": {
            co.id: [co.range.low, co.range.high, co.priority] for co in config.variables.constraints
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def gain_model_hash(config: MpcConfig) -> str:
    """SHA-256 da matriz `models` — a "referência ao modelo de ganho usado" da auditoria do
    SSTO (ADR-026 §11).

    Separado do `economics_config_hash` de propósito: custo/limite e modelo mudam por
    motivos diferentes (o primeiro é decisão econômica, o segundo é re-identificação da
    planta), e um registro de auditoria precisa distinguir os dois.
    """
    payload = {
        row_id: {
            col_id: {"enabled": pair.enabled, "params": pair.params}
            for col_id, pair in cols.items()
        }
        for row_id, cols in config.models.items()
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
