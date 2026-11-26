"""Rotas `/api/softsensor`: consulta de blocos e modelos do sensor virtual (RF-584; spec §8.4).

Só leitura aqui (treino, otimização e exclusão de modelo estão em `softsensor_lab`). Escopo é o
projeto ativo, como `GET /api/operate/mpcs`: sem projeto ativo a lista é vazia, nunca 404.
`weights` (até 8 MB por modelo) nunca sai daqui: a projeção de modelos seleciona colunas, sem a
entidade, e tira o resto do `meta` do artefato.
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Literal

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
    ts_seconds: float  # Ts do flow
    desired_model_id: int | None = None
    active_model_id: int | None = None
    candidate_model_id: int | None = None
    # Do modelo EM USO (`active_model_id`); `None` sem ele
    active_input_names: list[str] | None = None
    warmup_s: float | None = None


class SoftSensorUseOut(BaseModel):
    """Um bloco que referencia o modelo. `pending`: pedido (`desired`) que o runtime ainda não
    atendeu, sem candidato em curso (spec §5.6: "aguardando o runtime")."""

    flow_id: int
    flow_name: str
    block_id: str
    state: Literal["active", "candidate", "pending"]


class SoftSensorModelOut(BaseModel):
    id: int
    name: str
    method: str
    period_s: float
    n_inputs: int
    warmup_steps: int | None = None
    warmup_s: float | None = None
    hyperparams: dict[str, float] = {}
    metrics: dict[str, float] = {}
    input_names: list[str] = []
    in_use: list[SoftSensorUseOut] = []
    created_at: datetime


def _warmup_s(meta: dict, period_s: float) -> float | None:
    passos = meta.get("warmup_steps")
    return None if passos is None else passos * period_s


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
    # Só `meta` e `period_s` do modelo em uso: os pesos ficam no banco
    em_uso = {
        m.id: m
        for m in await db.execute(
            select(SoftSensorModel.id, SoftSensorModel.period_s, SoftSensorModel.meta).where(
                SoftSensorModel.id.in_(
                    [v.active_model_id for v in vinculos.values() if v.active_model_id is not None]
                )
            )
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
            ativo = em_uso.get(vinculo.active_model_id) if vinculo else None
            saida.append(
                SoftSensorBlockOut(
                    flow_id=flow.id,
                    flow_name=flow.name,
                    block_id=node.id,
                    label=node.label or node.id,
                    method=metodo,
                    n_inputs=node.config.n_inputs,
                    ts_seconds=float(flow.ts_seconds),  # Numeric(4,1): SQLAlchemy devolve Decimal
                    desired_model_id=vinculo.desired_model_id if vinculo else None,
                    active_model_id=vinculo.active_model_id if vinculo else None,
                    candidate_model_id=vinculo.candidate_model_id if vinculo else None,
                    active_input_names=(
                        [i["name"] for i in ativo.meta.get("inputs", [])] if ativo else None
                    ),
                    warmup_s=_warmup_s(ativo.meta, ativo.period_s) if ativo else None,
                )
            )
    return saida


async def _usos_por_modelo(
    db: AsyncSession, project_id: int
) -> defaultdict[int, list[SoftSensorUseOut]]:
    """Blocos do projeto que referenciam cada modelo, em ordem de flow e bloco. Colunas, não a
    entidade do vínculo (o runtime o grava por fora)."""
    usos: defaultdict[int, list[SoftSensorUseOut]] = defaultdict(list)
    vinculos = await db.execute(
        select(
            SoftSensorBinding.flow_id,
            SoftSensorBinding.block_id,
            SoftSensorBinding.desired_model_id,
            SoftSensorBinding.active_model_id,
            SoftSensorBinding.candidate_model_id,
            Flow.name.label("flow_name"),
        )
        .join(Flow, Flow.id == SoftSensorBinding.flow_id)
        .where(Flow.project_id == project_id)
        .order_by(Flow.name, Flow.id, SoftSensorBinding.block_id)
    )
    for v in vinculos:
        estados: dict[int, str] = {}  # um modelo, um estado por bloco: `active` vence `candidate`
        if (
            v.desired_model_id is not None
            and v.desired_model_id != v.active_model_id
            and v.candidate_model_id is None
        ):
            estados[v.desired_model_id] = "pending"
        if v.candidate_model_id is not None:
            estados[v.candidate_model_id] = "candidate"
        if v.active_model_id is not None:
            estados[v.active_model_id] = "active"
        for model_id, estado in estados.items():
            usos[model_id].append(
                SoftSensorUseOut(
                    flow_id=v.flow_id, flow_name=v.flow_name, block_id=v.block_id, state=estado
                )
            )
    return usos


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
    usos = await _usos_por_modelo(db, project_id)
    return [
        SoftSensorModelOut(
            id=m.id,
            name=m.name,
            method=m.method,
            period_s=m.period_s,
            n_inputs=m.n_inputs,
            warmup_steps=m.meta.get("warmup_steps"),
            warmup_s=_warmup_s(m.meta, m.period_s),
            hyperparams=m.meta.get("hyperparams", {}),
            metrics=m.meta.get("metrics", {}),
            input_names=[i["name"] for i in m.meta.get("inputs", [])],
            in_use=usos[m.id],
            created_at=m.created_at,
        )
        for m in linhas
    ]
