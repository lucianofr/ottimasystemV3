"""Schemas de flows (RF-302/306/307): CRUD do diagrama de blocos e envelope do save."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Único registro do conjunto de Ts do ADR-007; é o mesmo do CHECK de `flows.ts_seconds`.
TsSeconds = Literal[0.5, 1, 2, 5, 10, 30, 60]
DesiredState = Literal["running", "stopped"]

# `flows.id` e `flows.project_id` são BIGINT: id fora da faixa é 422 no schema/rota, nunca
# erro de driver virando 5xx (mesma defesa de `MAX_TAG_ID` em routers/history.py).
MAX_BIGINT = 2**63 - 1


class FlowCreate(BaseModel):
    project_id: int = Field(ge=1, le=MAX_BIGINT)
    name: str = Field(min_length=1)
    ts_seconds: TsSeconds


class FlowUpdate(BaseModel):
    # `graph_json` entra como dict e é validado pelo `flowgraph` no handler: modelá-lo aqui
    # criaria uma segunda fonte de verdade sobre a forma do grafo, com erro fora do pt-BR.
    name: str | None = Field(default=None, min_length=1)
    graph_json: dict


class FlowOut(BaseModel):
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
