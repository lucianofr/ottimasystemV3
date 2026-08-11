"""Schemas de flows (RF-302/306/307): CRUD do diagrama de blocos e envelope do save."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Único registro do conjunto de Ts do ADR-007; é o mesmo do CHECK de `flows.ts_seconds`.
TsSeconds = Literal[0.5, 1, 2, 5, 10, 30, 60]
DesiredState = Literal["running", "stopped"]

# `flows.id` e `flows.project_id` são BIGINT: id fora da faixa é 422 no schema/rota, nunca
# erro de driver virando 5xx (mesma defesa de `MAX_TAG_ID` em routers/history.py).
MAX_BIGINT = 2**63 - 1


def erro_watchdog_flow(
    enabled: bool,
    connection_id: int | None,
    read_node_id: str | None,
    write_node_id: str | None,
) -> str | None:
    """Coerência do watchdog por flow (ADR-009 revisado): habilitado exige conexão + os dois
    node_ids, e leitura/escrita não podem ser o mesmo node — quem inverte o bit é o DCS/PLC
    (watchdogA := watchdogB copiado pelo ottima); um nó só nunca alterna (trava)."""
    if not enabled:
        return None
    if connection_id is None or not read_node_id or not write_node_id:
        return "Watchdog habilitado exige conexão e os dois node_ids (leitura e escrita)"
    if read_node_id == write_node_id:
        return "Watchdog exige node_ids de leitura e escrita distintos"
    return None


class _FlowWatchdogFields(BaseModel):
    watchdog_enabled: bool = False
    watchdog_connection_id: int | None = None
    watchdog_read_node_id: str | None = None
    watchdog_write_node_id: str | None = None
    watchdog_period_ms: int = Field(default=1500, ge=500, le=5000)


class FlowCreate(BaseModel):
    project_id: int = Field(ge=1, le=MAX_BIGINT)
    name: str = Field(min_length=1)
    ts_seconds: TsSeconds


class FlowUpdate(BaseModel):
    # `graph_json` entra como dict e é validado pelo `flowgraph` no handler: modelá-lo aqui
    # criaria uma segunda fonte de verdade sobre a forma do grafo, com erro fora do pt-BR.
    # `None` mantém o grafo salvo: o diálogo de propriedades troca nome/Ts sem tocar no desenho.
    # Watchdog segue a mesma convenção: `None` mantém o valor gravado; o diálogo de
    # propriedades sempre envia os cinco campos juntos quando o usuário mexe neles.
    name: str | None = Field(default=None, min_length=1)
    ts_seconds: TsSeconds | None = None
    graph_json: dict | None = None
    watchdog_enabled: bool | None = None
    watchdog_connection_id: int | None = None
    watchdog_read_node_id: str | None = None
    watchdog_write_node_id: str | None = None
    watchdog_period_ms: int | None = Field(default=None, ge=500, le=5000)


class FlowOut(_FlowWatchdogFields):
    """Linha da lista (spec §5.1): sem `graph_json`, que por flow pode ser grande."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    ts_seconds: float
    desired_state: DesiredState
    updated_at: datetime


class FlowDetail(FlowOut):
    graph_json: dict


class FlowSaved(BaseModel):
    """Resposta do PUT (spec §5.2): avisos de inversão acompanham o flow gravado."""

    flow: FlowDetail
    warnings: list[str] = Field(default_factory=list)
