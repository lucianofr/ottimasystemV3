"""Contratos do barramento Redis pub/sub — payloads verbatim do PRD §7.1 (ADR-002).

Canais são FIXOS: criar/alterar canal exige ADR (CLAUDE.md). Consumo real começa na F2.
"""

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

CHANNEL_OPC_WRITES = "opc.writes"
CHANNEL_FLOW_COMMANDS = "flow.commands"
CHANNEL_EVENTS = "events"


def channel_opc_values(conn_id: int) -> str:
    return f"opc.values.{conn_id}"


def channel_flow_status(flow_id: int) -> str:
    return f"flow.status.{flow_id}"


def channel_mpc_state(flow_id: int, block_id: str) -> str:
    return f"mpc.state.{flow_id}.{block_id}"


class OpcValue(BaseModel):
    tag_id: int
    ts: datetime
    value: float
    quality: int  # 0=good, 1=uncertain, 2=bad (spec F1 §3.2)


class OpcWrite(BaseModel):
    conn_id: int
    tag_id: int
    flow_id: int
    value: float
    source: str
    ts: datetime


class PortValue(BaseModel):
    """Valor de uma porta de bloco numa varredura (spec F3 §4.2, decisão A-3)."""

    # União em modo smart do Pydantic v2: `True` continua bool e `42.5` continua float no
    # round-trip. O canvas desenha lâmpada para bool e número para float; coerção seria defeito.
    v: float | bool | None
    ok: bool  # False = valor inválido; o canvas dessatura e rotula (decisão #6)


class FlowStatus(BaseModel):
    state: Literal["running", "stopped", "failed"]
    scan_ms: float
    overruns: int
    ts: datetime
    # Default vazio serve só à publicação imediata de transição de estado (§2.2-5), que não
    # tem varredura atrás; toda publicação de varredura preenche `ports` (§4.2).
    ports: dict[str, dict[str, PortValue]] = {}


class FlowCommand(BaseModel):
    flow_id: int
    cmd: str
    args: dict[str, Any]
    user: str
    ts: datetime


class MpcVarState(BaseModel):
    """Estado publicado de uma variável do MPC (spec F4 §5.1) — `sp` só existe em CV
    (em AUTO, o SP congelado; fora, o SP rastreado por PV-tracking).

    `status` só existe em MV: a disponibilidade dela no ciclo publicado (ADR-028,
    `rcas_ok`/`local_override`/`bad_quality`/`out_of_service`). Campo OPCIONAL com default
    `None` de propósito — é aditivo ao payload de `mpc.state.*` (PRD §7.1) e nenhum
    consumidor existente (recorder, `/ws` da API, faceplates) precisa mudar para continuar
    validando. Não é persistido: `mpc_samples` (migration 0003) segue com as colunas de
    sempre; a auditoria das transições vive no log de eventos (ADR-020,
    `mpc_mv_status_changed`), no mesmo espírito do ADR-016 para predições.
    """

    v: float
    sp: float | None = None
    status: str | None = None


class MpcModes(BaseModel):
    local_remote: Literal["local", "remote"]
    man_auto: Literal["man", "auto"]


class MpcStatus(BaseModel):
    solver: Literal["ok", "overrun", "error", "building", "idle"]
    overruns: int
    last_solve_ms: float
    armed: bool  # armed = (local_remote == "remote"), spec F4 §5.1
    input_valid: bool


class MpcPrediction(BaseModel):
    """`ts` (UTC, spec F5 §2.1-2) é o instante da fronteira em que o solve que produziu esta
    predição foi despachado — âncora do overlay, nunca `MpcState.ts` (F5R-01)."""

    ts: datetime
    t: list[float]
    cv: list[list[float]]
    mv: list[list[float]]


class SstoRun(BaseModel):
    """Registro imutável de uma execução do SSTO (ADR-027 §11, RF-903).

    Viaja como campo opcional de `MpcState` — **sem canal novo** (ADR-002): o recorder, que
    já assina `mpc.state.*` e é o único escritor de hypertable, o materializa em
    `ssto_runs`. Quadro sem SSTO omite o campo e continua idêntico ao da F5.

    Carrega os dois hashes que amarram o registro ao que produziu aquele alvo:
    `config_hash` (custos, limites, ranks) e `model_hash` (a matriz de ganho usada).

    `cv_target` de linha `integrating` é uma TAXA [EU/s], não um nível (ADR-027 §4).
    """

    run_id: str
    config_hash: str
    model_hash: str
    status: Literal["optimal", "relaxed", "infeasible", "unbounded", "error"]
    solver: str
    solve_ms: float
    objective: float
    mv: dict[str, float]
    cv_ss: dict[str, float]
    bias: dict[str, float]
    dv: dict[str, float]
    costs: dict[str, float]
    delta_mv: dict[str, float]
    mv_target: dict[str, float]
    cv_target: dict[str, float]
    given_up: list[str]
    """CVs/Restrições desistidas, NA ORDEM em que a desistência ocorreu (ADR-027 §6)."""
    active_constraints: list[str]
    duals: dict[str, float]


class MpcState(BaseModel):
    """Publicado em `mpc.state.<flow_id>.<block_id>` a cada execução (spec F4 §5.1, RF-625).

    `ts` (UTC, spec F5 §2.1-1) é obrigatório de propósito — o recorder (F5 §2.3) depende dele
    como âncora de gravação; quadro fora de AUTO publica `prediction.ts == ts` e
    `prediction.t == []` (spec F5 §2.1-2).

    `ssto` só aparece nos quadros em que a camada de alvos de fato rodou (ADR-027 §11).
    """

    ts: datetime
    modes: MpcModes
    status: MpcStatus
    vars: dict[str, MpcVarState]
    cost: float
    prediction: MpcPrediction
    ssto: SstoRun | None = None


class EventMessage(BaseModel):
    ts: datetime
    severity: Literal["info", "warning", "alarm"]
    origin: str
    message: str
    payload: dict[str, Any]


# Vocabulário `kind` do canal `events` (spec F2 §7.3, ADR-020). Consumidores fazem match
# por `kind`; `message` é texto pt-BR para humanos e pode mudar sem quebrar ninguém.
KIND_COMM_FAILURE = "comm_failure"
KIND_COMM_RESTORED = "comm_restored"
KIND_OPC_WRITE = "opc_write"
KIND_WRITE_BLOCKED = "write_blocked"
KIND_WRITE_REJECTED = "write_rejected"
KIND_TAG_SUBSCRIBE_ERROR = "tag_subscribe_error"
KIND_RECORDER_BACKPRESSURE = "recorder_backpressure"
KIND_PROJECT_ACTIVATED = "project_activated"
KIND_CONNECTION_CREATED = "connection_created"
KIND_CONNECTION_UPDATED = "connection_updated"
KIND_CONNECTION_DELETED = "connection_deleted"
KIND_TAG_CREATED = "tag_created"
KIND_TAG_UPDATED = "tag_updated"
KIND_TAG_DELETED = "tag_deleted"

# Vocabulário `kind` novo da F3 (spec F3 §4.3).
KIND_FLOW_DEPLOYED = "flow_deployed"
KIND_FLOW_STOPPED = "flow_stopped"
KIND_FLOW_FAILED = "flow_failed"
KIND_FLOW_OVERRUN = "flow_overrun"
KIND_SCRIPT_TIMEOUT = "script_timeout"
KIND_SCRIPT_ERROR = "script_error"
KIND_WRITE_SUPPRESSED = "write_suppressed"
KIND_RELOAD_REJECTED = "reload_rejected"
KIND_DEPLOY_REJECTED = "deploy_rejected"
KIND_FLOW_CREATED = "flow_created"
KIND_FLOW_UPDATED = "flow_updated"
KIND_FLOW_DELETED = "flow_deleted"

# Vocabulário `kind` novo do MPC (spec F4 §5.3).
KIND_MPC_MODE_CHANGED = "mpc_mode_changed"
KIND_MPC_SP_WRITTEN = "mpc_sp_written"
KIND_MPC_MV_WRITTEN = "mpc_mv_written"
KIND_MPC_OVERRUN = "mpc_overrun"
KIND_MPC_SOLVER_ERROR = "mpc_solver_error"
KIND_MPC_SHED = "mpc_shed"
KIND_MPC_MV_STATUS_CHANGED = "mpc_mv_status_changed"
KIND_MPC_ARM_FAILED = "mpc_arm_failed"
KIND_MPC_INPUT_INVALID = "mpc_input_invalid"
# SSTO (ADR-027 §10): a camada de alvos não fechou e o ciclo caiu no SP do operador. O
# relaxamento por rank NÃO gera evento — é operação normal e fica registrado em
# `ssto_runs.given_up`; alarme por varredura afogaria o log de eventos (ADR-020).
KIND_SSTO_INFEASIBLE = "ssto_infeasible"

# Vocabulário `kind` novo da F5 (spec F5 §7.2-2, F5R-02b).
KIND_SCRIPT_RECOVERED = "script_recovered"  # severity "info"

# Vocabulário `kind` novo da F6 (spec F6 §3.1-4/§3.2-9).
KIND_PROJECT_EXPORTED = "project_exported"  # severity "info"
KIND_PROJECT_IMPORTED = "project_imported"  # severity "info"

# Retomada automática após `comm_restored` (TD-005, ADR-025).
KIND_FLOW_RESUMED = "flow_resumed"  # severity "info"

# Retenção de histórico configurável (ADR-003 revisado).
KIND_HISTORY_RETENTION_CHANGED = "history_retention_changed"  # severity "info"


async def publish_event(
    redis_client: Redis,
    *,
    severity: Literal["info", "warning", "alarm"],
    origin: str,
    message: str,
    kind: str,
    payload: dict[str, Any] | None = None,
    ts: datetime | None = None,
) -> EventMessage:
    """Publisher canônico do canal `events` (spec F2 §7.1, ADR-020).

    Única forma de emitir evento: garante `kind` no payload e `ts` em UTC aware.
    Falha de publicação não propaga — evento é telemetria e não pode derrubar um loop
    de controle (ADR-004/009).
    """
    if ts is None:
        ts = datetime.now(UTC)
    elif ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    else:
        ts = ts.astimezone(UTC)

    # `kind` primeiro e vencendo um homônimo do chamador: divergência silenciosa entre o
    # argumento e o dict quebraria o match dos consumidores.
    final_payload = {"kind": kind, **{k: v for k, v in (payload or {}).items() if k != "kind"}}
    event = EventMessage(
        ts=ts, severity=severity, origin=origin, message=message, payload=final_payload
    )
    try:
        await redis_client.publish(CHANNEL_EVENTS, event.model_dump_json())
    except Exception:
        logger.exception("Falha ao publicar evento no canal %s: %s", CHANNEL_EVENTS, message)
    return event
