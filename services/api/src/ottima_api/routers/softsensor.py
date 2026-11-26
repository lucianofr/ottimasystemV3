"""Rotas `/api/softsensor`: consulta de blocos e modelos do sensor virtual (RF-584; spec §8.4).

Só leitura nesta entrega. Escopo é o projeto ativo, como `GET /api/operate/mpcs`: sem projeto
ativo a lista é vazia, nunca 404. `weights` (até 8 MB por modelo) nunca sai daqui: a projeção
de modelos seleciona colunas, sem a entidade, e tira o resto do `meta` do artefato.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, require_operator
from ottima_core.flowgraph import SOFT_SENSOR_METHOD, GraphParseError, parse_graph
from ottima_core.models import Flow, Project, SoftSensorBinding, SoftSensorModel

logger = logging.getLogger(__name__)

router = APIRouter()


class SoftSensorBlockOut(BaseModel):
    """Um bloco de sensor virtual e o seu vínculo. `desired_model_id` é o que a API gravou;
    só `active_model_id` e `candidate_model_id` são estado (os grava o runtime, spec §5.6)."""

    flow_id: int
    flow_name: str
    block_id: str
    label: str  # `label` do nó; cai para o `block_id` quando o canvas não nomeou o bloco
    method: str
    n_inputs: int
    desired_model_id: int | None = None
    active_model_id: int | None = None
    candidate_model_id: int | None = None


class SoftSensorModelOut(BaseModel):
    id: int
    name: str
    method: str
    period_s: float
    n_inputs: int
    warmup_steps: int | None = None
    metrics: dict[str, float] = {}
    input_names: list[str] = []
    created_at: datetime


@router.get(
    "/blocks", response_model=list[SoftSensorBlockOut], dependencies=[Depends(require_operator)]
)
async def list_blocks(db: AsyncSession = Depends(get_db)) -> list[SoftSensorBlockOut]:
    project_id = await db.scalar(select(Project.id).where(Project.is_active))
    if project_id is None:
        return []
    flows = list(
        await db.scalars(select(Flow).where(Flow.project_id == project_id).order_by(Flow.name))
    )
    vinculos = {
        (v.flow_id, v.block_id): v
        for v in await db.scalars(
            select(SoftSensorBinding).where(SoftSensorBinding.flow_id.in_([f.id for f in flows]))
        )
    }
    saida: list[SoftSensorBlockOut] = []
    for flow in flows:
        try:
            graph = parse_graph(flow.graph_json)
        except GraphParseError:
            # Melhor-esforço, como `_fuzzy_nodes`: um flow ilegível não derruba a lista.
            logger.warning("Flow %s ('%s') com graph_json inválido; ignorado", flow.id, flow.name)
            continue
        for node in graph.nodes:
            metodo = SOFT_SENSOR_METHOD.get(node.type)
            if metodo is None:
                continue
            vinculo = vinculos.get((flow.id, node.id))
            saida.append(
                SoftSensorBlockOut(
                    flow_id=flow.id,
                    flow_name=flow.name,
                    block_id=node.id,
                    label=node.label or node.id,
                    method=metodo,
                    n_inputs=node.config.n_inputs,
                    desired_model_id=vinculo.desired_model_id if vinculo else None,
                    active_model_id=vinculo.active_model_id if vinculo else None,
                    candidate_model_id=vinculo.candidate_model_id if vinculo else None,
                )
            )
    return saida


@router.get(
    "/models", response_model=list[SoftSensorModelOut], dependencies=[Depends(require_operator)]
)
async def list_models(db: AsyncSession = Depends(get_db)) -> list[SoftSensorModelOut]:
    project_id = await db.scalar(select(Project.id).where(Project.is_active))
    if project_id is None:
        return []
    linhas = await db.execute(
        select(
            SoftSensorModel.id,
            SoftSensorModel.name,
            SoftSensorModel.method,
            SoftSensorModel.period_s,
            SoftSensorModel.n_inputs,
            SoftSensorModel.meta,
            SoftSensorModel.created_at,
        )
        .where(SoftSensorModel.project_id == project_id)
        .order_by(SoftSensorModel.id.desc())
    )
    return [
        SoftSensorModelOut(
            id=m.id,
            name=m.name,
            method=m.method,
            period_s=m.period_s,
            n_inputs=m.n_inputs,
            warmup_steps=m.meta.get("warmup_steps"),
            metrics=m.meta.get("metrics", {}),
            input_names=[i["name"] for i in m.meta.get("inputs", [])],
            created_at=m.created_at,
        )
        for m in linhas
    ]
