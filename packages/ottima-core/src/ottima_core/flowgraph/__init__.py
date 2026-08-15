"""Modelo tipado do `graph_json` de um flow + validação compartilhada (RF-302/307, ADR-024).

Uma implementação, dois consumidores (spec F3 §2.1): a API valida no save (422) e o runtime
valida ao montar a definição *staged* do hot-swap. Núcleo puro — nada de SQLAlchemy nem de
`services/` aqui: o chamador traduz linhas do banco em `TagRef`.

Pacote dividido por responsabilidade (débito 6 do plano F4a — teto de linhas por arquivo):

- `parse.py` cuida da **forma** (estrutura e tipagem estática do JSONB) e levanta
  `GraphParseError` com a lista completa de problemas;
- `validate.py` cuida da **semântica que precisa de contexto** (tags do projeto, Ts do
  flow, topologia) e nunca levanta por conteúdo de grafo — devolve `ValidationResult`.

Import público inalterado: `from ottima_core.flowgraph import ...` continua funcionando para
todo consumidor; ninguém fora deste pacote deve importar `ottima_core.flowgraph.parse` ou
`ottima_core.flowgraph.validate` diretamente.
"""

from ottima_core.flowgraph.mpc_config import (
    ConstraintObjective,
    ConstraintVar,
    CvObjective,
    CvVar,
    DvVar,
    EconomicsConfig,
    Horizons,
    Limits,
    ModeValues,
    MpcConfig,
    MpcVariables,
    MvObjective,
    MvVar,
    PairModel,
    PidBinding,
    Range,
    RowKind,
    SolverName,
    TargetMode,
    derive_horizons,
    economics_config_hash,
    gain_model_hash,
    mpc_state_dimension,
    optimization_enabled,
)
from ottima_core.flowgraph.parse import (
    MAX_SCRIPT_PORTS,
    NODE_TYPES,
    FirstOrderConfig,
    FlowEdge,
    FlowGraph,
    FlowNode,
    FuzzyConfig,
    GraphParseError,
    IopdtParams,
    KalmanConfig,
    MpcRawConfig,
    NodeConfig,
    NodeType,
    PidConfig,
    Position,
    ScriptConfig,
    SopdtParams,
    TagConfig,
    TfsConfig,
    TfsElement,
    parse_graph,
)
from ottima_core.flowgraph.validate import (
    MAX_DELAY_SAMPLES,
    PortKind,
    TagRef,
    ValidationResult,
    validate_graph,
)

__all__ = [
    "MAX_DELAY_SAMPLES",
    "MAX_SCRIPT_PORTS",
    "NODE_TYPES",
    "ConstraintObjective",
    "ConstraintVar",
    "CvObjective",
    "CvVar",
    "DvVar",
    "EconomicsConfig",
    "FirstOrderConfig",
    "FlowEdge",
    "FlowGraph",
    "FlowNode",
    "FuzzyConfig",
    "GraphParseError",
    "Horizons",
    "IopdtParams",
    "KalmanConfig",
    "Limits",
    "ModeValues",
    "MpcConfig",
    "MpcRawConfig",
    "MpcVariables",
    "MvObjective",
    "MvVar",
    "NodeConfig",
    "NodeType",
    "PairModel",
    "PidBinding",
    "PidConfig",
    "PortKind",
    "Position",
    "Range",
    "RowKind",
    "ScriptConfig",
    "SolverName",
    "SopdtParams",
    "TagConfig",
    "TagRef",
    "TargetMode",
    "TfsConfig",
    "TfsElement",
    "ValidationResult",
    "derive_horizons",
    "economics_config_hash",
    "gain_model_hash",
    "mpc_state_dimension",
    "optimization_enabled",
    "parse_graph",
    "validate_graph",
]
