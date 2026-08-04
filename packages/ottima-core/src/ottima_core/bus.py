"""Contratos do barramento Redis pub/sub — payloads verbatim do PRD §7.1 (ADR-002).

Canais são FIXOS: criar/alterar canal exige ADR (CLAUDE.md). Consumo real começa na F2.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

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
