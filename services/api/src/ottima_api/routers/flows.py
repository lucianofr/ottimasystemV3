"""CRUD de flows (RF-302/306/307): leitura para operador, escrita para admin (ADR-015)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, require_admin, require_operator
from ottima_core.flowgraph import GraphParseError, TagRef, parse_graph, validate_graph
from ottima_core.models import Flow, OpcConnection, Project, Tag
from ottima_core.schemas.flows import (
    MAX_BIGINT,
    FlowCreate,
    FlowDetail,
    FlowOut,
    FlowSaved,
    FlowUpdate,
)

# Sem dependência no router: os papéis variam por rota (ADR-015)
router = APIRouter()

# Id acima da faixa do BIGINT é 422 na borda; chegar ao driver viraria 5xx.
FlowId = Annotated[int, Path(ge=1, le=MAX_BIGINT)]
ProjectFilter = Annotated[int | None, Query(ge=1, le=MAX_BIGINT)]

MSG_NAO_ENCONTRADO = "Flow não encontrado"
MSG_NOME_EM_USO = "Nome de flow já em uso neste projeto"
MSG_RODANDO = "Flow em execução; pare o flow antes de excluir"

# As mensagens do flowgraph já usam "; " internamente (a de ciclo, por exemplo), então o
# separador entre reprovações precisa ser outro para o engenheiro ver onde uma termina.
SEPARADOR_REPROVACOES = " | "


async def _carregar(db: AsyncSession, flow_id: int) -> Flow:
    flow = await db.get(Flow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=MSG_NAO_ENCONTRADO)
    return flow


def _reprovado(mensagens: list[str]) -> HTTPException:
    """422 de domínio com `detail` string, como no resto da API.

    Lista aqui seria invisível na tela: o cliente descarta `detail` que não seja string
    (frontend/src/lib/api.ts) e mostraria "Erro inesperado" no lugar da reprovação.
    """
    return HTTPException(status_code=422, detail=SEPARADOR_REPROVACOES.join(mensagens))


async def _tags_do_projeto(db: AsyncSession, project_id: int) -> dict[int, TagRef]:
    """Tags visíveis ao flow: as do projeto dele, via conexão (o `graph_json` não tem FK).

    Uma consulta para o grafo inteiro — o número de nós não pode virar número de queries.
    """
    stmt = (
        select(Tag.id, Tag.connection_id, Tag.direction, Tag.data_type)
        .join(OpcConnection, OpcConnection.id == Tag.connection_id)
        .where(OpcConnection.project_id == project_id)
    )
    return {
        row.id: TagRef(
            id=row.id,
            conn_id=row.connection_id,
            direction=row.direction,
            data_type=row.data_type,
        )
        for row in await db.execute(stmt)
    }


@router.get("", response_model=list[FlowOut], dependencies=[Depends(require_operator)])
async def list_flows(
    project_id: ProjectFilter = None, db: AsyncSession = Depends(get_db)
) -> list[Flow]:
    """Lista leve (spec §5.1): `graph_json` só sai no detalhe."""
    stmt = select(Flow).order_by(Flow.name)
    if project_id is not None:
        stmt = stmt.where(Flow.project_id == project_id)
    return list(await db.scalars(stmt))


@router.post("", response_model=FlowDetail, status_code=201, dependencies=[Depends(require_admin)])
async def create_flow(body: FlowCreate, db: AsyncSession = Depends(get_db)) -> Flow:
    """Flow nasce parado (ADR-017) e com grafo vazio; o desenho chega pelo PUT."""
    if await db.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    flow = Flow(**body.model_dump(), graph_json={"nodes": [], "edges": []})
    db.add(flow)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_NOME_EM_USO) from None
    await db.refresh(flow)
    return flow


@router.get("/{flow_id}", response_model=FlowDetail, dependencies=[Depends(require_operator)])
async def get_flow(flow_id: FlowId, db: AsyncSession = Depends(get_db)) -> Flow:
    return await _carregar(db, flow_id)


@router.put("/{flow_id}", response_model=FlowSaved, dependencies=[Depends(require_admin)])
async def update_flow(
    flow_id: FlowId, body: FlowUpdate, db: AsyncSession = Depends(get_db)
) -> FlowSaved:
    """Valida o grafo antes de gravar (spec §5.2); avisos de inversão não bloqueiam (RF-307)."""
    flow = await _carregar(db, flow_id)
    try:
        graph = parse_graph(body.graph_json)
    except GraphParseError as erro:
        raise _reprovado(erro.errors) from None

    # `ts_seconds` é Numeric(4,1): SQLAlchemy devolve Decimal e a validação faz aritmética
    # com o Ts (teto de atraso do TFS), onde Decimal com float levanta TypeError.
    resultado = validate_graph(
        graph, await _tags_do_projeto(db, flow.project_id), float(flow.ts_seconds)
    )
    if resultado.errors:
        raise _reprovado(resultado.errors)

    if body.name is not None:
        flow.name = body.name
    # Gravado verbatim: o editor é o dono do JSON e guarda nele estado de layout que a
    # validação ignora de propósito.
    flow.graph_json = body.graph_json
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_NOME_EM_USO) from None
    await db.refresh(flow)
    return FlowSaved(flow=FlowDetail.model_validate(flow), warnings=resultado.warnings)


@router.delete("/{flow_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_flow(flow_id: FlowId, db: AsyncSession = Depends(get_db)) -> None:
    flow = await _carregar(db, flow_id)
    if flow.desired_state == "running":
        raise HTTPException(status_code=409, detail=MSG_RODANDO)
    await db.delete(flow)
    await db.commit()
