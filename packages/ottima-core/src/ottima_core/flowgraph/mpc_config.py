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

# Função objetivo por variável (ADR-027 §9 estendido): cada opção vira um termo do LP do
# SSTO (ver ssto.py — tabela de semântica no cabeçalho do módulo). `none` (default) =
# comportamento anterior, config salva antes da feature carrega idêntico.
MvObjective = Literal["none", "maximize", "minimize", "psv", "equalize"]
CvObjective = Literal["none", "maximize", "minimize", "observe_limit", "target", "psv"]
ConstraintObjective = Literal["none", "maximize", "minimize"]

# Ação de falha por variável (RF-613): avaliada só em REMOTO, com debounce de 2 execuções.
# MV não tem o que simular (sem modelo próprio); linha (CV/Restrição) pode segurar o valor
# previsto por até `fail_timeout_s` antes de cair na ação final (`simulate_*`).
MvFailAction = Literal["no_action", "shed_local", "manual"]
RowFailAction = Literal[
    "no_action", "shed_local", "manual", "simulate_manual", "simulate_shed_local"
]

# Portas fixas de saída (decisão A-10 REVISTA 2026-08-17, spec F4 §2.1-5): ao contrário das
# demais portas do bloco (uma por variável configurada), estas duas SEMPRE existem — mesmo
# no nó recém-criado sem nenhuma MV/CV — porque refletem os eixos de MODO do bloco (RF-621),
# não uma variável do usuário. Único ponto de definição da string: `validate.py`
# (`_output_handles`) e `services/flow-runtime/.../blocks/mpc.py` (`output_ports`,
# `_compute_outputs`) importam daqui — nunca literais duplicados.
#
# Valor sempre numérico (decisão A-5: toda porta do MPC é numérica, nunca bool): 1.0/0.0.
# `MPC_PORT_LOCAL`: 1.0 em LOCAL, 0.0 em REMOTO. `MPC_PORT_AUTO`: 1.0 em AUTO (dentro de
# REMOTO), 0.0 em MAN. Saem nulas junto com as demais saídas sob cold start das entradas
# (padrão F3 §3.0) — mesma regra de invalidez de toda porta do bloco numa varredura ruim.
MPC_PORT_LOCAL = "local"
MPC_PORT_AUTO = "auto"
MPC_FIXED_OUTPUT_PORTS: tuple[str, str] = (MPC_PORT_LOCAL, MPC_PORT_AUTO)


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
    (curso do atuador), `max_rate` e `initial_value` estão todos nessa coordenada.

    `zero`/`span`: faixa de instrumento `[zero, zero+span]` (RF-609). Os ganhos da matriz
    `models` são declarados adimensionais (%/%: ΔCV%/ΔMV%), e o motor converte para EU
    multiplicando por `span_linha/span_coluna` — os defaults 0/100 dão razão 1, então
    config salva antes do campo continua bit a bit igual. O faceplate usa a faixa como
    escala da barra.

    `operating_point`: valor desta MV no ponto em que a matriz `models` foi linearizada.
    Os pares são incrementais (`Δy = K·Δu`, `dy/dt = Ki·Δu`), então o modelo interno é
    alimentado com `u − operating_point` — sem isso uma linha integradora acumula
    `Ki·Ts·u_op` por execução e a predição deriva sozinha (TD-003). `0.0` reproduz o
    comportamento anterior, então config salva antes deste campo continua carregando.

    `readback_tag_id`: tag de leitura com a posição REAL da MV. Em LOCAL a saída acompanha
    essa tag (transferência bumpless para REMOTO); em REMOTO ela é o `u_applied` do solve.
    Só faz sentido na MV direta: com `pid`, quem já cumpre esse papel é
    `pid.readback_tag_id`.

    `max_rate`: taxa máxima de variação da MV, em EU/s (RF-604 revisado — era `du_max` em
    EU/ciclo; o Δu por ciclo do solve é `max_rate × Ts_mpc`).

    `du_min`: banda morta do atuador, na mesma EU da MV. Movimento pedido menor que
    ela não é aplicado (a válvula não responderia mesmo) — quem quantiza é o worker, para
    o modelo interno nunca divergir do que foi escrito. `0.0` desliga. A coerência
    `du_min ≤ max_rate × Ts_mpc` só é decidível com o Ts_mpc e passa a ser checada no
    build do bloco (falha de build = caminho de erro de config existente).

    `move_weight`: fator multiplicativo do peso de movimento desta MV no custo do solve.
    `1.0` mantém o comportamento anterior; maior deixa a MV mais preguiçosa que as outras.

    `fail_action`: o que fazer quando a MV fica indisponível em REMOTO (RF-613), com
    debounce de 2 execuções. `no_action` (default) = comportamento anterior.

    `local_shed_mode`: valor escrito na tag `mode_cmd` em QUALQUER devolução da MV ao
    controle local (shed global, shed por fail action, comando REMOTO→LOCAL). `None`
    mantém `pid.mode_values.auto`. Só faz sentido com PID.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    eu: str
    description: str = Field(default="", max_length=14)
    zero: float = 0.0
    span: float = Field(default=100.0, gt=0.0)
    limits: Limits
    # Sem `gt` aqui de propósito: a regra `max_rate > 0` vive em `_check_mpc_numbers` com
    # mensagem pt-BR (mesma arquitetura do antigo `du_max` — um `gt` no Pydantic trocaria o
    # 422 legível pela localização do campo).
    max_rate: float
    du_min: float = Field(default=0.0, ge=0.0)
    move_weight: float = Field(default=1.0, gt=0.0)
    initial_value: float = 0.0
    operating_point: float = 0.0
    readback_tag_id: int | None = None
    pid: PidBinding | None = None
    objective: MvObjective = "none"
    """Função objetivo desta MV no SSTO. `psv` ancora a MV no valor preferido; `equalize`
    nivela todas as MVs marcadas em fração da escala (grupo único, validado em
    `MpcVariables`)."""
    psv: float | None = None
    """Valor preferido da MV quando `objective == "psv"`, na coordenada absoluta da porta
    (mesma de `limits`/`initial_value`). `None` fora do PSV — ver validators abaixo."""
    fail_action: MvFailAction = "no_action"
    local_shed_mode: int | None = None

    @field_validator("id")
    @classmethod
    def _valida_prefixo(cls, value: str) -> str:
        return _exigir_prefixo(value, "mv_", "MV")

    @model_validator(mode="after")
    def _valida_psv(self) -> "MvVar":
        if self.objective == "psv":
            if self.psv is None or not (self.limits.min <= self.psv <= self.limits.max):
                raise ValueError("PSV exige um valor preferido dentro dos limites da MV")
        elif self.psv is not None:
            raise ValueError("psv só vale com objetivo PSV")
        return self

    @model_validator(mode="after")
    def _valida_local_shed_mode(self) -> "MvVar":
        if self.local_shed_mode is not None and self.pid is None:
            raise ValueError("local_shed_mode exige MV com PID")
        return self


class CvVar(BaseModel):
    """Variável controlada — linha da matriz `models` (spec §2.1-2).

    `priority`: rank do SSTO (ADR-027 §5). Mesma semântica do `ConstraintVar.priority` do
    ADR-019 — **maior = mais importante**; a desistência por inviabilidade é em ordem
    crescente. Só o LP de regime permanente o consome: o objetivo dinâmico segue usando
    `weight`, e o default `1` deixa todas as CVs no mesmo rank (comportamento de antes do
    campo existir).

    `zero`/`span`: faixa de instrumento `[zero, zero+span]` (RF-609) — base da conversão
    %/% → EU dos ganhos e da escala do faceplate.

    `traj_tau_s`: τ da trajetória de referência exponencial até o SP (RF-611). `0.0` =
    degrau, o comportamento de sempre.

    `track_sp`: fora de AUTO, o SP rastreia o PV (transferência bumpless). `True` =
    comportamento anterior; `False` segura o SP do operador em MAN (RF-612).

    `fail_action`/`fail_timeout_s`: ação em entrada inválida prolongada (RF-613);
    `simulate_*` segura o valor previsto por até `fail_timeout_s` antes da ação final.

    `sp_range_pct`: banda do SP no SSTO (RF-615, emenda ADR-027 §4) — por `kind` da
    linha: `selfreg` trava o alvo em `SP ± pct/100 × span` (nível); `integrating` vira
    ε de taxa `pct/100 × span/tss` (linha não tem nível de regime — RF-615 revisado).
    `None` = sem banda por linha (comportamento anterior: `selfreg` livre nos
    `sp_limits`; `integrating` cai no `economics.integrating_tolerance` do bloco).

    `remote_sp_tag_id`: tag OPC-UA de SP remoto (RF-614) — a cada varredura o SP vem da
    tag (clamp em `sp_limits`); `None` = SP local do operador.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    eu: str
    description: str = Field(default="", max_length=14)
    zero: float = 0.0
    span: float = Field(default=100.0, gt=0.0)
    kind: RowKind
    tss: float
    weight: float
    sp_limits: Limits
    priority: int = Field(default=1, ge=1)
    objective: CvObjective = "none"
    """Função objetivo desta CV no SSTO. Âncoras (`target`/`psv`/`observe_limit`) usam o SP
    do operador; `maximize`/`minimize` viram preço linear na linha projetada por `c_row·G`."""
    traj_tau_s: float = Field(default=0.0, ge=0.0)
    track_sp: bool = True
    fail_action: RowFailAction = "no_action"
    fail_timeout_s: float = Field(default=60.0, gt=0.0)
    sp_range_pct: float | None = Field(default=None, gt=0.0, le=100.0)
    remote_sp_tag_id: int | None = None

    @field_validator("id")
    @classmethod
    def _valida_prefixo(cls, value: str) -> str:
        return _exigir_prefixo(value, "cv_", "CV")

    @model_validator(mode="after")
    def _valida_objetivo_selfreg(self) -> "CvVar":
        if self.objective != "none" and self.kind != "selfreg":
            # Linha integradora decide TAXA no LP (ADR-027 §4), não nível — um objetivo
            # econômico de nível não tem o que ancorar ali.
            raise ValueError("Objetivo econômico exige linha autorregulável (selfreg)")
        return self


class ConstraintVar(BaseModel):
    """Restrição — também linha da matriz `models`; soft constraint na montagem (spec §3.4).

    `zero`/`span`: faixa de instrumento `[zero, zero+span]` (RF-609). `fail_action`/
    `fail_timeout_s`: RF-613, mesma semântica da CV.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    eu: str
    description: str = Field(default="", max_length=14)
    zero: float = 0.0
    span: float = Field(default=100.0, gt=0.0)
    kind: RowKind
    tss: float
    range: Range
    priority: int = Field(ge=1)
    objective: ConstraintObjective = "none"
    """Função objetivo desta Restrição no SSTO — só preço linear (`maximize`/`minimize`)."""
    fail_action: RowFailAction = "no_action"
    fail_timeout_s: float = Field(default=60.0, gt=0.0)

    @field_validator("id")
    @classmethod
    def _valida_prefixo(cls, value: str) -> str:
        return _exigir_prefixo(value, "co_", "Restrição")

    @model_validator(mode="after")
    def _valida_objetivo_selfreg(self) -> "ConstraintVar":
        if self.objective != "none" and self.kind != "selfreg":
            raise ValueError("Objetivo econômico exige linha autorregulável (selfreg)")
        return self


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
    zero: float = 0.0
    span: float = Field(default=100.0, gt=0.0)
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

    @model_validator(mode="after")
    def _valida_equalize(self) -> "MpcVariables":
        # Equalize é um GRUPO único (todas as MVs marcadas nivelam entre si): exatamente 1
        # marcada é um grupo de um membro só, que não equaliza nada — quase sempre um clique
        # errado; zero é ausência do recurso, dois ou mais é o caso legítimo.
        if sum(1 for mv in self.mvs if mv.objective == "equalize") == 1:
            raise ValueError("Equalize exige pelo menos duas MVs com esse objetivo")
        return self


class PairModel(BaseModel):
    """Par `models[linha][coluna]` (spec §2.1-2); `params` genérico — completude é da 1.2."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    params: dict[str, float]


class EconomicsConfig(BaseModel):
    """Camada econômica do SSTO (ADR-027 §9) — estrutura pronta para a UI futura.

    `costs`: `var_id` (MV, CV ou Restrição) -> preço no objetivo `min cᵀ·ΔMV`. **Negativo
    maximiza** a variável. Preço de linha (CV/Restrição) é projetado no espaço de decisão
    por `c_row·G` na montagem do LP — a variável de decisão continua sendo só `ΔMV`.

    `slack_weight`: peso base da folga das linhas soft; o peso efetivo por linha é
    `slack_weight × priority` (primeira linha de defesa contra inviabilidade, ADR-027 §6).

    `detuning_weight` (ρ): mitigação de **LP flipping** (ADR-027 §8) — `ρ > 0` acrescenta
    `ρ‖ΔMV − ΔMV_anterior‖²` ao objetivo e exige um backend QP. `0.0` mantém LP puro.

    `integrating_tolerance` (ε): meia-faixa PADRÃO da condição de taxa nula das linhas
    integradoras (ADR-027 §4), na EU da linha por segundo — vale para toda CV/Restrição
    integradora sem `sp_range_pct` própria (RF-615 revisado); com `sp_range_pct`, a CV
    usa o ε dela, derivado de `pct/100 × span/tss`.
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
    caminho da F4 (ADR-027 §10). Campo opcional de propósito — config salva antes desta
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


def optimization_enabled(config: MpcConfig) -> bool:
    """SSTO deve rodar neste bloco (ADR-027 §10 revisado): substitui o gate `economics.enabled`
    puro — a camada de alvos também é exigida por qualquer variável com `objective != "none"`,
    mesmo sem bloco `economics`. `economics.costs` continua sendo preço cru ADITIVO aos
    termos derivados do objetivo (retrocompat de config salvo).
    """
    economics = config.economics
    if economics is not None and economics.enabled:
        return True
    variables = config.variables
    return any(
        var.objective != "none" for var in (*variables.mvs, *variables.cvs, *variables.constraints)
    )


def economics_config_hash(config: MpcConfig) -> str:
    """SHA-256 da versão do problema econômico (ADR-027 §9): custos, limites e ranks.

    Identifica O PROBLEMA que o SSTO resolveu, não o bloco: renomear o MPC ou mexer num
    parâmetro dinâmico (peso de rastreamento, `max_rate`) não produz hash novo — mexer num
    preço, num limite, num span ou num rank produz. É o campo que amarra cada registro de
    auditoria à
    configuração vigente no instante do solve.

    JSON canônico (`sort_keys`, separadores fixos) para o hash não depender da ordem em que
    as chaves chegaram do `graph_json`.
    """
    economics = config.economics
    payload = {
        "economics": None if economics is None else economics.model_dump(mode="json"),
        "mvs": {
            mv.id: [mv.limits.min, mv.limits.max, mv.zero, mv.span, mv.objective, mv.psv]
            for mv in config.variables.mvs
        },
        "cvs": {
            cv.id: [
                cv.sp_limits.min,
                cv.sp_limits.max,
                cv.zero,
                cv.span,
                cv.sp_range_pct,
                cv.priority,
                cv.objective,
            ]
            for cv in config.variables.cvs
        },
        "constraints": {
            co.id: [co.range.low, co.range.high, co.zero, co.span, co.priority, co.objective]
            for co in config.variables.constraints
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def gain_model_hash(config: MpcConfig) -> str:
    """SHA-256 da matriz `models` — a "referência ao modelo de ganho usado" da auditoria do
    SSTO (ADR-027 §11).

    Separado do `economics_config_hash` de propósito: custo/limite e modelo mudam por
    motivos diferentes (o primeiro é decisão econômica, o segundo é re-identificação da
    planta), e um registro de auditoria precisa distinguir os dois.
    """
    payload = {
        "models": {
            row_id: {
                col_id: {"enabled": pair.enabled, "params": pair.params}
                for col_id, pair in cols.items()
            }
            for row_id, cols in config.models.items()
        },
        # O ganho declarado é %/% (RF-602 revisado): o span de cada variável muda o ganho
        # efetivo em EU, então entra na identidade do modelo.
        "spans": {
            var.id: var.span
            for var in (
                *config.variables.mvs,
                *config.variables.cvs,
                *config.variables.constraints,
                *config.variables.dvs,
            )
        },
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
