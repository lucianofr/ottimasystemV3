"""Modelo tipado do `graph_json` de um flow — forma e tipagem estática do JSONB (RF-302/307).

`parse_graph` levanta `GraphParseError` com a lista completa de problemas estruturais. A
semântica que precisa de contexto (tags do projeto, Ts do flow, topologia) é
`ottima_core.flowgraph.validate.validate_graph` — ver `ottima_core/flowgraph/__init__.py`
para a divisão de responsabilidade completa do pacote.
"""

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ottima_core.flowgraph.fll_defaults import FUZZY_LOOP_DEFAULT_FLL, MAX_FUZZY_LOOPS

NodeType = Literal[
    "opc_read",
    "opc_write",
    "constant",
    "script",
    "fuzzy",
    "tfs",
    "mpc",
    "first_order",
    "kalman",
    "pid",
    "pid_loop",
    "fuzzy_loop",
    "scaler",
    "integrator",
    "bus_publish",
    "bus_subscribe",
    "lead_lag",
    "dead_time",
]
NODE_TYPES: tuple[str, ...] = (
    "opc_read",
    "opc_write",
    "constant",
    "script",
    "fuzzy",
    "tfs",
    "mpc",
    "first_order",
    "kalman",
    "pid",
    "pid_loop",
    "fuzzy_loop",
    "scaler",
    "integrator",
    "bus_publish",
    "bus_subscribe",
    "lead_lag",
    "dead_time",
)

MAX_SCRIPT_PORTS = 8  # spec §3.3
# Teto do texto FLL (RF-541, ADR-029): exports reais do QtFuzzyLite ficam na casa dos KB;
# o teto protege o parse/is_ready e limita o número de regras/termos processados (FUZZY-SEC).
MAX_FUZZY_FLL_LENGTH = 200_000

_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "opc_read": ("tag_id",),
    "opc_write": ("tag_id",),
    "constant": ("value",),
    "script": ("n_inputs", "n_outputs", "code", "output_eu"),
    "fuzzy": ("fll", "n_inputs", "n_outputs", "output_eu", "setpoint", "sp_source"),
    "tfs": ("matrix", "output_eu", "y0"),
    # `economics` é opcional (ADR-027 §9): `_parse_mpc_config` só repassa as chaves
    # presentes, então config salva antes do SSTO continua parseando.
    "mpc": ("name", "multiplier", "variables", "models", "economics"),
    "first_order": ("tau",),
    "kalman": ("measurement_noise", "process_noise"),
    "pid": (
        "kc",
        "ti_seconds",
        "td_seconds",
        "setpoint",
        "output_min",
        "output_max",
        "auto_mode",
        "proportional_on_measurement",
        "differential_on_measurement",
        "starting_output",
    ),
    "pid_loop": (
        "permitted",
        "normal",
        "shed_opt",
        "shed_no_return",
        "direct_acting",
        "sp_pv_track_in_man",
        "use_pv_for_bkcal",
        "track_enable",
        "track_in_manual",
        "sp_hi_lim",
        "sp_lo_lim",
        "sp_rate_up",
        "sp_rate_dn",
        "out_hi_lim",
        "out_lo_lim",
        "out_rate_up",
        "out_rate_dn",
        "out_scale_lo",
        "out_scale_hi",
        "out_startup",
        "pv_ftime",
        "trk_val",
        "lo_val",
        "ff_scale_lo",
        "ff_scale_hi",
        "ff_gain",
        "ff_enable",
        "kc",
        "ti_seconds",
        "td_seconds",
        "n",
        "beta",
        "gamma",
        "gap_band",
        "gap_gain",
    ),
    "fuzzy_loop": (
        "permitted",
        "normal",
        "shed_opt",
        "shed_no_return",
        "direct_acting",
        "sp_pv_track_in_man",
        "use_pv_for_bkcal",
        "track_enable",
        "track_in_manual",
        "sp_hi_lim",
        "sp_lo_lim",
        "sp_rate_up",
        "sp_rate_dn",
        "out_hi_lim",
        "out_lo_lim",
        "out_rate_up",
        "out_rate_dn",
        "out_scale_lo",
        "out_scale_hi",
        "out_startup",
        "pv_ftime",
        "trk_val",
        "lo_val",
        "ff_scale_lo",
        "ff_scale_hi",
        "ff_gain",
        "ff_enable",
        "n_loops",
        "ke",
        "kde",
        "ku",
        "tf_de",
        "fll",
        "lut_enabled",
        "lut_resolution",
    ),
    "scaler": ("in_min", "in_max", "out_min", "out_max"),
    "integrator": ("time_base",),
    "bus_publish": ("key",),
    "bus_subscribe": ("key",),
    "lead_lag": ("gain", "tau_lead", "tau_lag"),
    "dead_time": ("theta",),
}
# Blocos de filtro (ADR-026): config é só um punhado de escalares, e o valor do dicionário
# diz se o campo exige positivo estrito (divisor) ou apenas não-negativo.
_FILTER_KEYS: dict[str, dict[str, bool]] = {
    "first_order": {"tau": False},
    "kalman": {"measurement_noise": True, "process_noise": False},
}
_PARAM_KEYS: dict[str, tuple[str, ...]] = {
    "sopdt": ("K", "tau1", "tau2", "theta"),
    "iopdt": ("Ki", "theta"),
}
_GAIN_KEYS = frozenset({"K", "Ki"})  # únicos params que podem ser negativos
# `opc_read` aceita tag `w` (readback: o último valor escrito, ex.: lógica de incremento
# sobre a MV) — o opc-worker já publica a série das tags `w` legíveis (CurrentRead).
_TAG_DIRECTION: dict[str, tuple[str, ...]] = {"opc_read": ("r", "w"), "opc_write": ("w",)}


# --------------------------------------------------------------------------------------
# Modelo
# --------------------------------------------------------------------------------------


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class TagConfig(BaseModel):
    """Config de `opc_read` e `opc_write` — idêntica; quem discrimina é `FlowNode.type`."""

    model_config = ConfigDict(extra="forbid")

    tag_id: int


class ScriptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_inputs: int = Field(ge=0, le=MAX_SCRIPT_PORTS)
    n_outputs: int = Field(ge=0, le=MAX_SCRIPT_PORTS)
    code: str
    output_eu: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valida_output_eu(self) -> "ScriptConfig":
        """Chave de `output_eu` só existe se houver a porta correspondente (spec §4.1) —
        depende de `n_outputs`, por isso model_validator e não field_validator."""
        validas = {f"OUT{i}" for i in range(1, self.n_outputs + 1)}
        invalidas = sorted(set(self.output_eu) - validas)
        if invalidas:
            raise ValueError(
                f"'output_eu' referencia porta(s) inexistente(s) para n_outputs="
                f"{self.n_outputs}: {', '.join(invalidas)}"
            )
        return self


class FuzzyConfig(BaseModel):
    """Bloco Fuzzy (RF-541): motor de inferência definido em FLL (FuzzyLite Language).

    `fll` chega como texto cru — `parse_graph` nunca valida o CONTEÚDO do FLL (só forma,
    mesmo padrão do `mpc`, ver comentário de `MpcRawConfig`); a validação semântica roda em
    `validate_graph` via import lazy de `fuzzylite` (ADR-029).
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    fll: str = Field(max_length=MAX_FUZZY_FLL_LENGTH)
    n_inputs: int = Field(ge=1, le=MAX_SCRIPT_PORTS)
    n_outputs: int = Field(ge=1, le=MAX_SCRIPT_PORTS)
    output_eu: dict[str, str] = Field(default_factory=dict)
    #: SP do bloco (RF-541 revisado, PRD 3.1): habilitado, o FLL declara UMA variável de
    #: entrada a mais, a última, que recebe o SP — e é ela que fecha a lei de controle com
    #: erro nulo sem ação integral (modelo inverso + trim). A FONTE do SP é `sp_source`:
    #: `"operador"` (comando `fuzzy_sp` da página FUZZY, semente neste `setpoint`) ou
    #: `"entrada"` (porta `sp` do bloco, fio vindo ex.: de um `opc_read`). Sem SP (`None`
    #: nos dois), é o bloco de sempre: portas mapeadas verbatim às variáveis do FLL.
    setpoint: float | None = None
    sp_source: Literal["operador", "entrada"] | None = None

    @property
    def sp_ativo(self) -> bool:
        """SP habilitado por qualquer das duas fontes (a contagem do FLL depende disso)."""
        return self.sp_source == "entrada" or self.setpoint is not None

    @property
    def sp_da_entrada(self) -> bool:
        return self.sp_source == "entrada"

    @model_validator(mode="after")
    def _valida_output_eu(self) -> "FuzzyConfig":
        """Chave de `output_eu` só existe se houver a porta correspondente — depende de
        `n_outputs`, por isso model_validator e não field_validator (mesmo padrão do
        `ScriptConfig`)."""
        validas = {f"OUT{i}" for i in range(1, self.n_outputs + 1)}
        invalidas = sorted(set(self.output_eu) - validas)
        if invalidas:
            raise ValueError(
                f"'output_eu' referencia porta(s) inexistente(s) para n_outputs="
                f"{self.n_outputs}: {', '.join(invalidas)}"
            )
        return self

    @model_validator(mode="after")
    def _valida_fonte_do_sp(self) -> "FuzzyConfig":
        """Fonte e semente coerentes: `entrada` não carrega semente do operador; `operador`
        exige a semente (é ela que arma a barra da página e o primeiro scan)."""
        if self.sp_source == "entrada" and self.setpoint is not None:
            raise ValueError(
                "com sp_source='entrada' o setpoint deve ficar vazio: o SP vem da porta 'sp'"
            )
        if self.sp_source == "operador" and self.setpoint is None:
            raise ValueError(
                "sp_source='operador' exige o setpoint inicial (é a semente do SP do operador)"
            )
        return self


class SopdtParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    K: float
    tau1: float = Field(ge=0)
    tau2: float = Field(ge=0)
    theta: float = Field(ge=0)


class IopdtParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    Ki: float
    theta: float = Field(ge=0)


class TfsElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    kind: Literal["sopdt", "iopdt"]
    params: SopdtParams | IopdtParams


TFS_DEFAULT_Y0 = 50.0
"""Valor inicial de cada saída do TFS. A planta simulada raramente parte de zero, e 50 é o
meio da faixa em que MV/PV costumam estar expressas (%)."""


class TfsConfig(BaseModel):
    """`matrix[J][K]` é a contribuição de `uK` para `yJ` (spec §3.4), sempre 2x2.

    `y0` é a condição inicial de `[y1, y2]`: o estado dos elementos nasce no regime que
    produz esse valor, nunca um somatório deslocado. Em linha auto-regulada (SOPDT) só o
    transiente de partida muda e o ganho estático segue mandando no valor final; em linha
    com IOPDT o integrador não tem ganho estático, então `y0` é o nível de onde ele passa a
    integrar. Elemento sem memória (`K = 0`, ou `tau < Ts/10` com `theta = 0`) é um ganho
    puro e não tem estado onde guardar `y0` — a parcela dele parte de `K*u`.
    """

    model_config = ConfigDict(extra="forbid")

    matrix: list[list[TfsElement]]
    output_eu: dict[str, str] = Field(default_factory=dict)
    y0: list[float] = Field(
        default_factory=lambda: [TFS_DEFAULT_Y0, TFS_DEFAULT_Y0], min_length=2, max_length=2
    )

    @field_validator("output_eu")
    @classmethod
    def _valida_output_eu(cls, value: dict[str, str]) -> dict[str, str]:
        """Portas fixas do bloco `tfs` (spec §3.4): y1/y2, sem depender de outro campo."""
        invalidas = sorted(set(value) - {"y1", "y2"})
        if invalidas:
            raise ValueError(
                f"'output_eu' referencia porta(s) inexistente(s): {', '.join(invalidas)}"
            )
        return value


class FirstOrderConfig(BaseModel):
    """Bloco Filtro 1ª ordem (RF-532): `tau` em segundos. `tau = 0` é passagem direta."""

    model_config = ConfigDict(extra="forbid")

    tau: float = Field(ge=0)


class KalmanConfig(BaseModel):
    """Bloco Filtro Kalman (RF-533): dois desvios padrão na EU do sinal, nunca variâncias.

    `measurement_noise` é positivo estrito porque entra no divisor do ganho; `process_noise`
    pode ser zero (modela valor verdadeiro constante).
    """

    model_config = ConfigDict(extra="forbid")

    measurement_noise: float = Field(gt=0)
    process_noise: float = Field(ge=0)


class ScalerConfig(BaseModel):
    """Bloco Scaler: reescala linear de `in`∈[`in_min`,`in_max`] para [`out_min`,`out_max`].

    `strict=True` reprova string/bool num campo de escala (mesma rejeição manual dos
    filtros); `allow_inf_nan=False` protege o ganho `(out_max-out_min)/(in_max-in_min)`.
    `in_max > in_min` porque a faixa de entrada é o divisor; a de saída pode inverter
    (ação reversa, ex.: 4-20 mA → 100-0 %).
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    in_min: float = Field(allow_inf_nan=False)
    in_max: float = Field(allow_inf_nan=False)
    out_min: float = Field(allow_inf_nan=False)
    out_max: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def _faixa_de_entrada(self) -> "ScalerConfig":
        if self.in_max <= self.in_min:
            raise ValueError("in_max precisa ser maior que in_min")
        # Ganho derivado também precisa ser finito: faixas patológicas (~1e308 de largura
        # ou divisor denormal) transbordam a divisão e o bloco emitiria ±inf com ok=True.
        ganho = (self.out_max - self.out_min) / (self.in_max - self.in_min)
        if not math.isfinite(ganho):
            raise ValueError("escala resulta em ganho não-finito")
        return self


class IntegratorConfig(BaseModel):
    """Bloco Integrator (totalizador): acumula `in` no tempo do flow.

    `time_base` é a EU de tempo da entrada: "s" (por segundo), "min" (por minuto) ou
    "h" (por hora). O incremento por varredura é `in * Ts / fator`, com fator 1/60/3600 —
    o Ts vem do scheduler, única autoridade de tempo do laço (ADR-031).
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    time_base: Literal["s", "min", "h"]


MAX_LEAD_LAG_RATIO = 10.0
"""Teto de `tau_lead/tau_lag`. A razão `r` é o REALCE de alta frequência relativo ao ganho DC:
em regime (s→0) o ganho do bloco é `gain`; em alta frequência (s→∞) é `gain*r`. A saída do
lead-lag tipicamente alimenta `bias_in`, somada DEPOIS do integrador (ADR-039 D10) — ruído no
distúrbio medido chega à válvula multiplicado por `r`, sem atenuação integral. 10 é a ordem
de grandeza que o DeltaV pratica; acima disso a saída é cascatear dois blocos, como o ADR-026
já decidiu para filtro de ordem superior. `gain` fica FORA do teto porque ele limita o realce
relativo, não o ganho absoluto: `gain` negativo e grande em módulo (ex. `gain = -3`) é
legítimo e não diz nada sobre ruído."""


class LeadLagConfig(BaseModel):
    """Bloco Lead-Lag: `gain * (tau_lead*s + 1)/(tau_lag*s + 1)`, discretizado no Ts do flow.

    `gain` aceita QUALQUER sinal: ganho de feedforward negativo é rotineiro (distúrbio que
    empurra a CV para cima pede correção para baixo na válvula), e `gain = 0` desliga o
    feedforward sem apagar o bloco do canvas.

    `tau_lag > 0` porque é divisor tanto na razão quanto na discretização — `tau_lag = 0` com
    `tau_lead > 0` é função de transferência imprópria (derivador puro), NÃO passagem direta:
    a convenção `tau = 0` do ADR-026 não vale aqui. `tau_lead = 0` é lag puro, legítimo.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    gain: float = Field(allow_inf_nan=False)
    tau_lead: float = Field(ge=0.0, allow_inf_nan=False)
    tau_lag: float = Field(gt=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _razao_lead_lag(self) -> "LeadLagConfig":
        if self.tau_lead / self.tau_lag > MAX_LEAD_LAG_RATIO:
            raise ValueError(
                f"tau_lead/tau_lag precisa ser no máximo {MAX_LEAD_LAG_RATIO:g} — a razão é o "
                "realce de alta frequência relativo ao ganho DC; para mais, cascateie dois blocos"
            )
        return self


class DeadTimeConfig(BaseModel):
    """Bloco Tempo morto: atrasa `in` em `theta` segundos.

    `theta` é o mesmo termo dos modelos SOPDT/IOPDT (GLOSSARY) e vira `round(theta/Ts)`
    amostras, com o mesmo arredondamento half-even do TFS. O teto da fila depende do Ts, que
    o parse não conhece: mora em `validate.py`, ao lado do teto do TFS.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    theta: float = Field(ge=0.0, allow_inf_nan=False)


class ConstantConfig(BaseModel):
    """Bloco Constante: uma saída `out` com o valor fixo de `value`, sem entradas.

    `strict=True` reprova string/bool (mesma rejeição dos demais utilitários — `True` é
    `int` em Python e viraria 1.0 em silêncio); `allow_inf_nan=False` porque `inf`/`nan`
    contaminariam todo bloco a jusante com `ok=True`.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    value: float = Field(allow_inf_nan=False)


BUS_TYPES: frozenset[str] = frozenset({"bus_publish", "bus_subscribe"})
"""Os dois blocos de barramento (ADR-042) — mesma config, sentidos opostos."""

BUS_KEY_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
"""Charset da `key` de barramento (ADR-042 D8): sem ponto, sem glob, sem espaço — legível em
log e em payload, e nunca ambígua com a sintaxe de canal/padrão do Redis."""


class BusKeyConfig(BaseModel):
    """Config dos blocos `bus_publish` e `bus_subscribe` (ADR-042): só a `key` da variável.

    Um modelo para os dois tipos porque a config é a MESMA — quem discrimina o sentido é
    `FlowNode.type` (mesma relação de `TagConfig` com `opc_read`/`opc_write`). O assinante
    não tem campo de tempo de propósito: a validade vem do `period_s` que o publicador
    carimba no payload (D4).
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(pattern=BUS_KEY_PATTERN)


class PidConfig(BaseModel):
    """Bloco PID (RF-551, ADR-031): controlador ISA, motor `simple-pid` por baixo.

    A config é forma ISA — `out = Kc * [e + (1/Ti)*integral(e dt) + Td*de/dt]` — convertida
    uma única vez para os ganhos paralelos que o `simple-pid` espera (`Kp=kc`,
    `Ki=kc/ti_seconds`, `Kd=kc*td_seconds`) na construção do bloco em tempo de execução.
    `ti_seconds = 0` desliga a ação integral (Ki=0, convenção documentada — evita divisão
    por zero e permite controle P/PD); `td_seconds = 0` desliga a ação derivativa.
    """

    model_config = ConfigDict(extra="forbid")

    kc: float
    ti_seconds: float = Field(ge=0)
    td_seconds: float = Field(ge=0)
    setpoint: float
    output_min: float | None = None
    output_max: float | None = None
    auto_mode: bool = True
    proportional_on_measurement: bool = False
    differential_on_measurement: bool = True
    starting_output: float


class LoopBaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    permitted: list[str] = Field(default_factory=lambda: ["oos", "man", "auto"])
    normal: str = "auto"
    shed_opt: Literal["shed_to_auto", "shed_to_man", "shed_to_normal"] = "shed_to_auto"
    shed_no_return: bool = False
    direct_acting: bool = False
    sp_pv_track_in_man: bool = True
    use_pv_for_bkcal: bool = False
    track_enable: bool = False
    track_in_manual: bool = False
    sp_hi_lim: float
    sp_lo_lim: float
    sp_rate_up: float | None = Field(default=None, gt=0)
    sp_rate_dn: float | None = Field(default=None, gt=0)
    out_hi_lim: float = 100.0
    out_lo_lim: float = 0.0
    out_rate_up: float | None = Field(default=None, gt=0)
    out_rate_dn: float | None = Field(default=None, gt=0)
    out_scale_lo: float = 0.0
    out_scale_hi: float = 100.0
    out_startup: float = 0.0
    pv_ftime: float = Field(default=0.0, ge=0)
    trk_val: float = 0.0
    lo_val: float = 0.0
    ff_scale_lo: float = 0.0
    ff_scale_hi: float = 100.0
    ff_gain: float = 1.0
    ff_enable: bool = False

    @model_validator(mode="after")
    def _faixas(self) -> "LoopBaseConfig":
        if self.sp_lo_lim >= self.sp_hi_lim:
            raise ValueError("sp_lo_lim precisa ser menor que sp_hi_lim")
        if self.out_lo_lim >= self.out_hi_lim:
            raise ValueError("out_lo_lim precisa ser menor que out_hi_lim")
        if self.out_scale_lo >= self.out_scale_hi:
            raise ValueError("out_scale_lo precisa ser menor que out_scale_hi")
        if not (self.out_lo_lim <= self.out_startup <= self.out_hi_lim):
            raise ValueError("out_startup precisa estar entre out_lo_lim e out_hi_lim")
        modos = {"oos", "iman", "lo", "man", "auto", "cas", "rcas", "rout"}
        invalidos = sorted(set(self.permitted) - modos)
        if invalidos:
            raise ValueError(f"modos invalidos em permitted: {', '.join(invalidos)}")
        if self.normal not in {"man", "auto", "cas", "rcas"}:
            raise ValueError("normal precisa ser man, auto, cas ou rcas")
        return self


class PidLoopConfig(LoopBaseConfig):
    kc: float = Field(gt=0)
    ti_seconds: float = Field(default=0.0, ge=0)
    td_seconds: float = Field(default=0.0, ge=0)
    n: float = Field(default=8.0, gt=0)
    beta: float = Field(default=1.0, ge=0, le=1)
    gamma: float = Field(default=0.0, ge=0, le=1)
    gap_band: float = Field(default=0.0, ge=0)
    gap_gain: float = Field(default=1.0, ge=0, le=1)


class FuzzyLoopConfig(LoopBaseConfig):
    """Fuzzy Malha multicanal (SPEC_FUZZY secao 6.2, v2 MIMO): `n_loops` canais de controle
    compartilham UMA base de regras FLL e os ganhos do kernel; cada canal tem seu PV
    (porta `pv_i`), seu SP (faceplate) e sua saida (porta `out_i`).

    `ke`/`kde`/`ku`/`tf_de` sao classe de SINTONIA (hot-swap in-place, F10); `fll` e
    `n_loops` estao em `LOOP_STRUCTURAL_KEYS` e portanto re-instanciam o bloco (F11).
    `lut_resolution` tem teto de servidor (FUZZY-SEC): 257 pontos por eixo sao 66k
    avaliacoes por save — POR CANAL.

    Modos remotos/cascata (cas/rcas/rout/iman/lo) nao existem no v2: as portas do bloco
    sao `pv_1..pv_n`/`out_1..out_n` e o modo e resolvido por bloco, nao por canal.
    """

    n_loops: int = Field(default=1, ge=1, le=MAX_FUZZY_LOOPS)
    ke: float = Field(gt=0)  # 1/EU; 1/ke e a faixa de erro coberta sem saturar
    kde: float = Field(default=0.0, ge=0)  # s/EU; 0 desliga a acao derivativa
    ku: float = Field(gt=0)  # %span/s; sentido SO via direct_acting
    tf_de: float = Field(default=1.0, gt=0)  # s
    fll: str = Field(default=FUZZY_LOOP_DEFAULT_FLL, max_length=MAX_FUZZY_FLL_LENGTH)
    lut_enabled: bool = False
    lut_resolution: int = Field(default=65, ge=33, le=257)

    @model_validator(mode="after")
    def _modos_sem_cascata(self) -> "FuzzyLoopConfig":
        """`permitted` restrito a {oos, man, auto}: sem portas cas_in/rcas_in/rout_in/
        bkcal_in/lo_in_d no v2, um modo remoto em permitted seria inalcançavel na melhor
        hipotese e um erro de save confuso na pior (`_check_loop_nodes` exige a porta)."""
        invalidos = sorted(set(self.permitted) - {"oos", "man", "auto"})
        if invalidos:
            raise ValueError(
                "fuzzy_loop aceita apenas os modos oos/man/auto em permitted "
                f"(sem cascata no v2): {', '.join(invalidos)}"
            )
        if self.normal not in {"man", "auto"}:
            raise ValueError("normal precisa ser man ou auto no fuzzy_loop")
        return self


LOOP_STRUCTURAL_KEYS: frozenset[str] = frozenset(
    {"type", "fll", "n_loops", "out_scale_lo", "out_scale_hi"}
)


def loop_structural(functional: dict[str, Any]) -> dict[str, Any]:
    """Subconjunto ESTRUTURAL do functional_config (ADR-039 D11): mudou -> re-instancia."""
    return {k: v for k, v in functional.items() if k in LOOP_STRUCTURAL_KEYS}


class MpcRawConfig(BaseModel):
    """Payload bruto do bloco `mpc` (spec §2.1).

    A forma tipada e travada (ids `mv_`/`cv_`/`co_`/`dv_`, `pid` opcional, `params` genérico)
    nasce em `MpcConfig` (tarefa 1.1); esta classe só preserva as 4 chaves de `data` sem
    tipar o conteúdo aninhado, porque a completude por `kind` de linha (spec §2.2-3) precisa
    do resto do bloco — contexto que só `validate_graph` tem. `MpcConfig.model_validate`
    roda lá (tarefa 1.2 do plano F4a) e os 422 saem pelo canal `ValidationResult.errors`,
    nunca por `GraphParseError` — `parse_graph` nunca reprova um `mpc` por conteúdo, só por
    forma alheia ao bloco (chave desconhecida em `data`, `exec_order` ausente etc.).
    """

    model_config = ConfigDict(extra="allow")


NodeConfig = (
    TagConfig
    | ScriptConfig
    | FuzzyConfig
    | TfsConfig
    | MpcRawConfig
    | FirstOrderConfig
    | KalmanConfig
    | PidConfig
    | PidLoopConfig
    | FuzzyLoopConfig
    | ScalerConfig
    | IntegratorConfig
    | ConstantConfig
    | BusKeyConfig
    | LeadLagConfig
    | DeadTimeConfig
)


class FlowNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: NodeType
    position: Position
    exec_order: int = Field(ge=1)
    label: str = ""
    config: NodeConfig

    def functional_config(self) -> dict[str, Any]:
        """Identidade funcional do bloco, para o hot-swap (ADR-024, spec §4.1-3).

        `exec_order`, `label` e `position` ficam de fora de propósito: mudá-los não altera o
        que o bloco calcula, então o estado interno sobrevive ao swap (ADR-011).
        """
        return {"type": self.type, **self.config.model_dump()}


class FlowEdge(BaseModel):
    # As chaves do JSON são as do React Flow (camelCase); do lado Python valem os nomes
    # snake_case do projeto.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    source: str
    target: str
    source_handle: str = Field(alias="sourceHandle")
    target_handle: str = Field(alias="targetHandle")
    # ADR-040: não-nulo ⇒ ARESTA DE REALIMENTAÇÃO — a "quebra explícita" do RF-302. Um campo
    # só, e não par `flag`+`valor`: aresta de realimentação sem condição inicial não é
    # representável. Isenta da detecção de ciclo e do aviso de inversão (D2) e é a condição
    # inicial do atraso unitário: a porta de ORIGEM nasce com este valor em vez de `COLD`
    # (D4), senão `has_cold_input` trava o laço inválido para sempre.
    feedback_init: float | None = None

    @property
    def is_feedback(self) -> bool:
        return self.feedback_init is not None


class FlowGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[FlowNode]
    edges: list[FlowEdge]

    def node(self, node_id: str) -> FlowNode:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)


class GraphParseError(ValueError):
    """Problemas estruturais do `graph_json`. `errors` traz todos, não só o primeiro."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


# --------------------------------------------------------------------------------------
# parse_graph
# --------------------------------------------------------------------------------------


def _is_int(value: object) -> bool:
    # bool é subclasse de int em Python: True não é um exec_order nem um tag_id.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def parse_graph(data: dict) -> FlowGraph:
    """Valida a forma do `graph_json` e devolve o modelo tipado.

    Levanta `GraphParseError` com **todos** os problemas estruturais encontrados, para que o
    usuário corrija de uma vez em lugar de descobrir um por save.
    """
    if not isinstance(data, dict):
        raise GraphParseError(["graph_json deve ser um objeto com 'nodes' e 'edges'"])

    errors: list[str] = []
    raw_nodes = data.get("nodes")
    raw_edges = data.get("edges")
    if not isinstance(raw_nodes, list):
        errors.append("graph_json: 'nodes' é obrigatório e deve ser uma lista")
    if not isinstance(raw_edges, list):
        errors.append("graph_json: 'edges' é obrigatório e deve ser uma lista")
    if errors:
        raise GraphParseError(errors)

    nodes = _parse_nodes(raw_nodes, errors)
    edges = _parse_edges(raw_edges, errors)
    if errors:
        raise GraphParseError(errors)
    return FlowGraph(nodes=nodes, edges=edges)


def _parse_nodes(raw_nodes: list, errors: list[str]) -> list[FlowNode]:
    nodes: list[FlowNode] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            errors.append(f"nó na posição {index}: deve ser um objeto")
            continue
        node_id = raw.get("id")
        if not isinstance(node_id, str) or not node_id:
            errors.append(f"nó na posição {index}: 'id' deve ser uma string não-vazia")
            continue
        if node_id in seen:
            errors.append(f"id de nó duplicado: '{node_id}'")
            continue
        seen.add(node_id)
        node = _parse_node(node_id, raw, errors)
        if node is not None:
            nodes.append(node)
    return nodes


def _parse_node(node_id: str, raw: dict, errors: list[str]) -> FlowNode | None:
    where = f"nó '{node_id}'"
    node_type = raw.get("type")
    if node_type not in NODE_TYPES:
        errors.append(
            f"{where}: tipo '{node_type}' não é um bloco válido; use um de: {', '.join(NODE_TYPES)}"
        )
        return None

    position = _parse_position(where, raw.get("position"), errors)

    data = raw.get("data")
    if not isinstance(data, dict):
        errors.append(f"{where}: 'data' é obrigatório e deve ser um objeto")
        return None

    exec_order = data.get("exec_order")
    if not _is_int(exec_order) or exec_order < 1:
        errors.append(f"{where}: 'exec_order' é obrigatório e deve ser um inteiro maior que 0")
        exec_order = None

    label = data.get("label", "")
    if not isinstance(label, str):
        errors.append(f"{where}: 'label' deve ser uma string")
        label = ""

    # O editor é a única fonte deste JSON: chave extra em 'data' é bug de versão do frontend,
    # não campo opcional. Aceitar em silêncio esconderia o bug até o runtime tropeçar nele.
    allowed = {"exec_order", "label", *_CONFIG_KEYS[node_type]}
    for key in sorted(set(data) - allowed):
        errors.append(f"{where}: chave desconhecida em 'data': '{key}'")

    config = _parse_config(where, node_type, data, errors)
    if config is None or position is None or exec_order is None:
        return None
    return FlowNode(
        id=node_id,
        type=node_type,
        position=position,
        exec_order=exec_order,
        label=label,
        config=config,
    )


def _parse_position(where: str, raw: object, errors: list[str]) -> Position | None:
    if not isinstance(raw, dict) or not all(_is_number(raw.get(axis)) for axis in ("x", "y")):
        errors.append(f"{where}: 'position' deve ser um objeto com 'x' e 'y' numéricos")
        return None
    return Position(x=float(raw["x"]), y=float(raw["y"]))


def _parse_config(where: str, node_type: str, data: dict, errors: list[str]) -> NodeConfig | None:
    if node_type in _TAG_DIRECTION:
        tag_id = data.get("tag_id")
        if not _is_int(tag_id) or tag_id < 1:
            errors.append(f"{where}: 'tag_id' é obrigatório e deve ser um inteiro positivo")
            return None
        return TagConfig(tag_id=tag_id)
    if node_type == "script":
        return _parse_script_config(where, data, errors)
    if node_type == "fuzzy":
        return _parse_fuzzy_config(where, data, errors)
    if node_type == "mpc":
        return _parse_mpc_config(data)
    if node_type == "pid":
        return _parse_pid_config(where, data, errors)
    if node_type == "pid_loop":
        return _parse_loop_config(where, node_type, PidLoopConfig, data, errors)
    if node_type == "fuzzy_loop":
        return _parse_loop_config(where, node_type, FuzzyLoopConfig, data, errors)
    if node_type == "scaler":
        return _parse_loop_config(where, node_type, ScalerConfig, data, errors)
    if node_type == "integrator":
        return _parse_loop_config(where, node_type, IntegratorConfig, data, errors)
    if node_type == "constant":
        return _parse_loop_config(where, node_type, ConstantConfig, data, errors)
    if node_type in BUS_TYPES:
        return _parse_loop_config(where, node_type, BusKeyConfig, data, errors)
    if node_type == "lead_lag":
        return _parse_loop_config(where, node_type, LeadLagConfig, data, errors)
    if node_type == "dead_time":
        return _parse_loop_config(where, node_type, DeadTimeConfig, data, errors)
    if node_type in _FILTER_KEYS:
        return _parse_filter_config(where, node_type, data, errors)
    return _parse_tfs_config(where, data, errors)


def _parse_filter_config(
    where: str, node_type: str, data: dict, errors: list[str]
) -> FirstOrderConfig | KalmanConfig | None:
    """Config dos blocos de filtro (ADR-026): só escalares finitos, um erro por campo.

    Exigir finitude importa tanto quanto o sinal: `tau = inf` viraria `exp(-Ts/inf) = 1` (um
    filtro que nunca responde) e `nan` contaminaria a recorrência inteira em silêncio.
    """
    expected = _FILTER_KEYS[node_type]
    values: dict[str, float] = {}
    for key, strictly_positive in expected.items():
        value = data.get(key)
        if not _is_number(value) or not math.isfinite(value):
            errors.append(f"{where}: '{key}' é obrigatório e deve ser um número finito")
        elif strictly_positive and value <= 0:
            errors.append(f"{where}: '{key}' deve ser maior que zero")
        elif not strictly_positive and value < 0:
            errors.append(f"{where}: '{key}' não pode ser negativo")
        else:
            values[key] = float(value)

    if len(values) != len(expected):
        return None
    return FirstOrderConfig(**values) if node_type == "first_order" else KalmanConfig(**values)


def _parse_pid_config(where: str, data: dict, errors: list[str]) -> PidConfig | None:
    """Config do bloco PID (RF-551, ADR-031): forma ISA, um erro por campo, nunca
    curto-circuita — mesmo padrão de `_parse_filter_config`/`_parse_fuzzy_config`.

    `kc`, `setpoint` e `starting_output` são obrigatórios e aceitam qualquer sinal;
    `ti_seconds`/`td_seconds` são obrigatórios e não-negativos (zero desliga a ação
    correspondente); `output_min`/`output_max`/`auto_mode`/`proportional_on_measurement`/
    `differential_on_measurement` são opcionais — ausentes usam o default do `PidConfig`.
    """
    ok = True
    values: dict[str, object] = {}

    for key in ("kc", "setpoint", "starting_output"):
        value = data.get(key)
        if not _is_number(value) or not math.isfinite(value):
            errors.append(f"{where}: '{key}' é obrigatório e deve ser um número finito")
            ok = False
        else:
            values[key] = float(value)

    for key in ("ti_seconds", "td_seconds"):
        value = data.get(key)
        if not _is_number(value) or not math.isfinite(value):
            errors.append(f"{where}: '{key}' é obrigatório e deve ser um número finito")
            ok = False
        elif value < 0:
            errors.append(f"{where}: '{key}' não pode ser negativo")
            ok = False
        else:
            values[key] = float(value)

    for key in ("output_min", "output_max"):
        raw = data.get(key)
        if raw is None:
            values[key] = None
        elif not _is_number(raw) or not math.isfinite(raw):
            errors.append(f"{where}: '{key}' deve ser None ou um número finito")
            ok = False
        else:
            values[key] = float(raw)

    for key, default in (
        ("auto_mode", True),
        ("proportional_on_measurement", False),
        ("differential_on_measurement", True),
    ):
        if key not in data:
            values[key] = default
        elif not isinstance(data[key], bool):
            errors.append(f"{where}: '{key}' deve ser um booleano")
            ok = False
        else:
            values[key] = data[key]

    output_min, output_max = values.get("output_min"), values.get("output_max")
    if isinstance(output_min, float) and isinstance(output_max, float) and output_min >= output_max:
        errors.append(f"{where}: 'output_min' deve ser menor que 'output_max'")
        ok = False

    starting_output = values.get("starting_output")
    if (
        isinstance(output_min, float)
        and isinstance(output_max, float)
        and isinstance(starting_output, float)
        and not output_min <= starting_output <= output_max
    ):
        errors.append(f"{where}: 'starting_output' deve estar entre 'output_min' e 'output_max'")
        ok = False

    # Ganhos DERIVADOS da conversão ISA -> paralela (ADR-031): cada campo é finito
    # isoladamente, mas `kc/ti_seconds` e `kc*td_seconds` ainda podem estourar para `inf`
    # por overflow IEEE-754 (ex.: ti_seconds = 1e-320). O bloco jamais deixaria esse valor
    # chegar ao PLC — o guard de finitude do `step()` o barra —, mas o `_integral` do
    # simple-pid ficaria envenenado com `inf`/`nan` para sempre (o `_clamp` da lib não
    # resgata `nan`: comparação com `nan` é sempre falsa), e a malha ficaria presa em
    # `ok=False` até um reset, com UM único `write_suppressed` no histórico e silêncio
    # depois. Falhar aqui, no save, é 422 em vez de perda silenciosa de controle.
    kc = values.get("kc")
    ti_seconds, td_seconds = values.get("ti_seconds"), values.get("td_seconds")
    if isinstance(kc, float) and isinstance(ti_seconds, float) and isinstance(td_seconds, float):
        ki = kc / ti_seconds if ti_seconds > 0 else 0.0
        if not math.isfinite(ki):
            errors.append(
                f"{where}: 'kc' e 'ti_seconds' produzem um ganho integral não finito "
                f"(Ki = kc/ti_seconds); aumente 'ti_seconds' ou reduza 'kc'"
            )
            ok = False
        if not math.isfinite(kc * td_seconds):
            errors.append(
                f"{where}: 'kc' e 'td_seconds' produzem um ganho derivativo não finito "
                f"(Kd = kc*td_seconds); reduza 'td_seconds' ou 'kc'"
            )
            ok = False

    if not ok:
        return None
    return PidConfig(**values)


def _parse_loop_config(
    where: str, node_type: str, modelo: type[BaseModel], data: dict, errors: list[str]
) -> NodeConfig | None:
    """Config via modelo pydantic (malhas ADR-039, scaler, integrator): um erro por problema."""
    payload = {key: data[key] for key in _CONFIG_KEYS[node_type] if key in data}
    try:
        return modelo.model_validate(payload)
    except ValidationError as exc:
        for erro in exc.errors():
            campo = ".".join(str(loc) for loc in erro["loc"])
            # Validador de modelo (loc vazio) não tem campo: a msg já nomeia o problema.
            if campo == "":
                errors.append(f"{where}: {erro['msg']}")
            else:
                errors.append(f"{where}: '{campo}': {erro['msg']}")
        return None


def _parse_mpc_config(data: dict) -> MpcRawConfig:
    """Bloco `mpc` (spec §2.1): repassa as chaves previstas em `data` sem validar o
    conteúdo — `_parse_node` já garante que só chaves de `_CONFIG_KEYS['mpc']` chegam
    aqui (chave desconhecida já é erro de parse); a tipagem via `MpcConfig` mora em
    `validate_graph` (tarefa 1.2).
    """
    payload = {key: data[key] for key in _CONFIG_KEYS["mpc"] if key in data}
    return MpcRawConfig(**payload)


def _parse_output_eu(where: str, data: dict, errors: list[str]) -> dict[str, str] | None:
    """`output_eu` é opcional por porta (spec §4.1): ausente vira `{}` (compat. retroativa);
    presente precisa ser um objeto porta -> unidade de engenharia em texto."""
    if "output_eu" not in data:
        return {}
    output_eu = data["output_eu"]
    if not isinstance(output_eu, dict) or any(not isinstance(v, str) for v in output_eu.values()):
        errors.append(
            f"{where}: 'output_eu' deve ser um objeto que mapeia porta para unidade de "
            "engenharia (texto)"
        )
        return None
    return output_eu


def _parse_script_config(where: str, data: dict, errors: list[str]) -> ScriptConfig | None:
    counts: dict[str, int] = {}
    for field in ("n_inputs", "n_outputs"):
        value = data.get(field)
        if not _is_int(value) or not 0 <= value <= MAX_SCRIPT_PORTS:
            errors.append(
                f"{where}: '{field}' é obrigatório e deve ser um inteiro entre 0 e "
                f"{MAX_SCRIPT_PORTS}"
            )
        else:
            counts[field] = value

    code = data.get("code")
    if not isinstance(code, str):
        errors.append(f"{where}: 'code' é obrigatório e deve ser uma string")
        return None

    output_eu = _parse_output_eu(where, data, errors)
    if len(counts) != 2 or output_eu is None:
        return None
    try:
        return ScriptConfig(
            n_inputs=counts["n_inputs"],
            n_outputs=counts["n_outputs"],
            code=code,
            output_eu=output_eu,
        )
    except ValidationError as erro:
        errors.append(f"{where}: {erro.errors()[0]['ctx']['error']}")
        return None


def _parse_fuzzy_config(where: str, data: dict, errors: list[str]) -> FuzzyConfig | None:
    """Config do bloco Fuzzy (RF-541): mesma validação manual de `_parse_script_config`, mas
    a contagem de portas é 1..`MAX_SCRIPT_PORTS` (nunca 0 — um motor sem entrada ou saída não
    tem sentido) e `code` vira `fll`. Aqui só se valida a FORMA (string) do FLL; o CONTEÚDO
    (sintaxe FuzzyLite, contagem de variáveis, `is_ready()`) é `validate.py::_valida_fuzzy`,
    com import lazy de `fuzzylite` (ADR-029).
    """
    counts: dict[str, int] = {}
    for field in ("n_inputs", "n_outputs"):
        value = data.get(field)
        if not _is_int(value) or not 1 <= value <= MAX_SCRIPT_PORTS:
            errors.append(
                f"{where}: '{field}' é obrigatório e deve ser um inteiro entre 1 e "
                f"{MAX_SCRIPT_PORTS}"
            )
        else:
            counts[field] = value

    fll = data.get("fll")
    if not isinstance(fll, str):
        errors.append(f"{where}: 'fll' é obrigatório e deve ser uma string")
        return None
    if len(fll) > MAX_FUZZY_FLL_LENGTH:
        errors.append(
            f"{where}: 'fll' excede o teto de {MAX_FUZZY_FLL_LENGTH} caracteres "
            f"({len(fll)} enviados)"
        )
        return None

    output_eu = _parse_output_eu(where, data, errors)
    # `setpoint` ausente ou `null` = bloco sem SP (comportamento de sempre). Presente, tem de
    # ser número finito: o modelo recusa nan/inf, mas aqui a mensagem precisa nomear o campo.
    setpoint = data.get("setpoint")
    if setpoint is not None and (
        isinstance(setpoint, bool)
        or not isinstance(setpoint, (int, float))
        or not math.isfinite(setpoint)
    ):
        errors.append(f"{where}: 'setpoint' deve ser um número finito ou ausente/null")
        return None
    # `sp_source` ausente/null = sem SP ou legado (setpoint cheio implica operador). Valor
    # fora do vocabulário é erro nomeado aqui; a coerência fonte×semente é do model_validator.
    sp_source = data.get("sp_source")
    if sp_source is not None and sp_source not in ("operador", "entrada"):
        errors.append(
            f"{where}: 'sp_source' deve ser 'operador', 'entrada' ou ausente/null "
            f"(recebeu {sp_source!r})"
        )
        return None
    if len(counts) != 2 or output_eu is None:
        return None
    try:
        return FuzzyConfig(
            fll=fll,
            n_inputs=counts["n_inputs"],
            n_outputs=counts["n_outputs"],
            output_eu=output_eu,
            setpoint=None if setpoint is None else float(setpoint),
            sp_source=sp_source,
        )
    except ValidationError as erro:
        errors.append(f"{where}: {erro.errors()[0]['ctx']['error']}")
        return None


def _parse_tfs_config(where: str, data: dict, errors: list[str]) -> TfsConfig | None:
    matrix = data.get("matrix")
    if (
        not isinstance(matrix, list)
        or len(matrix) != 2
        or any(not isinstance(row, list) or len(row) != 2 for row in matrix)
    ):
        errors.append(
            f"{where}: 'matrix' é obrigatória e deve ser 2x2 (linhas y1..y2 por colunas u1..u2)"
        )
        return None

    rows: list[list[TfsElement]] = []
    complete = True
    for j, row in enumerate(matrix):
        parsed: list[TfsElement] = []
        for k, raw in enumerate(row):
            element = _parse_tfs_element(f"{where}: elemento y{j + 1}/u{k + 1}", raw, errors)
            if element is None:
                complete = False
            else:
                parsed.append(element)
        rows.append(parsed)
    if not complete:
        return None

    output_eu = _parse_output_eu(where, data, errors)
    if output_eu is None:
        return None
    y0 = _parse_tfs_y0(where, data, errors)
    if y0 is None:
        return None
    try:
        return TfsConfig(matrix=rows, output_eu=output_eu, y0=y0)
    except ValidationError as erro:
        errors.append(f"{where}: {erro.errors()[0]['ctx']['error']}")
        return None


def _parse_tfs_y0(where: str, data: dict, errors: list[str]) -> list[float] | None:
    """Condição inicial de `[y1, y2]`. Ausente cai no default (compat. retroativa: flow
    salvo antes do campo continua parseando, igual ao `output_eu`)."""
    raw = data.get("y0")
    if raw is None:
        return [TFS_DEFAULT_Y0, TFS_DEFAULT_Y0]
    if not isinstance(raw, list) or len(raw) != 2:
        errors.append(
            f"{where}: 'y0' deve ser uma lista [y1, y2] com o valor inicial de cada saída"
        )
        return None
    values: list[float] = []
    for index, value in enumerate(raw):
        if not _is_number(value) or not math.isfinite(value):
            errors.append(f"{where}: 'y0[{index}]' deve ser um número finito")
        else:
            values.append(float(value))
    return values if len(values) == 2 else None


def _parse_tfs_element(where: str, raw: object, errors: list[str]) -> TfsElement | None:
    if not isinstance(raw, dict):
        errors.append(f"{where}: deve ser um objeto com 'enabled', 'kind' e 'params'")
        return None
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        errors.append(f"{where}: 'enabled' é obrigatório e deve ser booleano")
        return None
    kind = raw.get("kind")
    if kind not in _PARAM_KEYS:
        errors.append(f"{where}: 'kind' deve ser 'sopdt' ou 'iopdt'")
        return None
    params = raw.get("params")
    if not isinstance(params, dict):
        errors.append(f"{where}: 'params' é obrigatório e deve ser um objeto")
        return None

    expected = _PARAM_KEYS[kind]
    values: dict[str, float] = {}
    for extra in sorted(set(params) - set(expected)):
        errors.append(f"{where}: '{extra}' não é um parâmetro de '{kind}'")
    for key in expected:
        value = params.get(key)
        # Exigir finitude também em theta: ele entra em round(theta/Ts) na regra de teto,
        # onde inf/nan estouraria com OverflowError/ValueError em vez de virar um 422.
        if not _is_number(value) or not math.isfinite(value):
            errors.append(f"{where}: '{key}' é obrigatório e deve ser um número finito")
        elif key not in _GAIN_KEYS and value < 0:
            # tau = 0 é legal (spec §3.4 degrada para passagem direta); negativo é não-físico.
            errors.append(f"{where}: '{key}' não pode ser negativo")
        else:
            values[key] = float(value)

    if len(values) != len(expected) or len(params) != len(expected):
        return None
    built = SopdtParams(**values) if kind == "sopdt" else IopdtParams(**values)
    return TfsElement(enabled=enabled, kind=kind, params=built)


def _parse_edges(raw_edges: list, errors: list[str]) -> list[FlowEdge]:
    edges: list[FlowEdge] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_edges):
        if not isinstance(raw, dict):
            errors.append(f"aresta na posição {index}: deve ser um objeto")
            continue
        edge_id = raw.get("id")
        if not isinstance(edge_id, str) or not edge_id:
            errors.append(f"aresta na posição {index}: 'id' deve ser uma string não-vazia")
            continue
        if edge_id in seen:
            errors.append(f"id de aresta duplicado: '{edge_id}'")
            continue
        seen.add(edge_id)

        fields: dict[str, str] = {}
        for key in ("source", "target", "sourceHandle", "targetHandle"):
            value = raw.get(key)
            if not isinstance(value, str) or not value:
                errors.append(f"aresta '{edge_id}': '{key}' deve ser uma string não-vazia")
            else:
                fields[key] = value
        seed = raw.get("feedback_init")
        if seed is not None and (not _is_number(seed) or not math.isfinite(seed)):
            errors.append(
                f"aresta '{edge_id}': 'feedback_init' deve ser um número finito — é a"
                " condição inicial da aresta de realimentação (ADR-040); omita a chave numa"
                " aresta comum"
            )
            continue
        if len(fields) == 4:
            edges.append(
                FlowEdge(
                    id=edge_id,
                    source=fields["source"],
                    target=fields["target"],
                    source_handle=fields["sourceHandle"],
                    target_handle=fields["targetHandle"],
                    feedback_init=None if seed is None else float(seed),
                )
            )
    return edges
