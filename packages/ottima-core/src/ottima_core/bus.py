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
    value: float
    source: str
    ts: datetime


class FlowStatus(BaseModel):
    state: Literal["running", "stopped", "failed"]
    scan_ms: float
    overruns: int
    ts: datetime


class FlowCommand(BaseModel):
    flow_id: int
    cmd: str
    args: dict[str, Any]
    user: str
    ts: datetime


class MpcPrediction(BaseModel):
    t: list[float]
    cv: list[list[float]]
    mv: list[list[float]]


class MpcState(BaseModel):
    modes: dict[str, str]
    status: dict[str, Any]
    vars: dict[str, float]
    cost: float
    prediction: MpcPrediction


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
