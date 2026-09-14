"""CRUD de variável historiada (RF-308, ADR-041): leitura para operador, escrita para admin
(ADR-015). Porta de bloco marcada no editor de flow para ser gravada ciclicamente em
`samples` — mesma forma de tag calculada (ADR-033 D1), produtor é o flow-runtime.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, get_redis, require_admin, require_operator
from ottima_api.historized import (
    derivar_nomes,
    problema_de_porta,
    publicar_comando,
    remover_variaveis_historiadas,
)
from ottima_api.messages import MSG_FLOW_NAO_ENCONTRADO
from ottima_core.bus import (
    KIND_HISTORIZED_VAR_CREATED,
    KIND_HISTORIZED_VAR_DELETED,
    publish_event,
)
from ottima_core.flowgraph import FlowGraph, GraphParseError, parse_graph
from ottima_core.models import Flow, HistorizedVar, Tag, User
from ottima_core.schemas.flows import MAX_BIGINT
from ottima_core.schemas.historized_vars import HistorizedVarCreate, HistorizedVarOut

# Sem dependência no router: os papéis variam por rota (ADR-015)
router = APIRouter()

MSG_NAO_ENCONTRADA = "Variável historiada não encontrada"
MSG_GRAFO_NAO_SALVO = (
    "Flow ainda não tem um grafo salvo; salve o desenho antes de historiar uma porta"
)
MSG_PORTA_JA_HISTORIADA = "Esta porta já está historiada"
MSG_NOME_EM_USO = "Nome de tag já em uso neste projeto"

FlowIdQuery = Annotated[int, Query(ge=1, le=MAX_BIGINT)]


async def _carregar_flow(db: AsyncSession, flow_id: int) -> Flow:
    flow = await db.get(Flow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=MSG_FLOW_NAO_ENCONTRADO)
    return flow


async def _grafo_salvo(flow: Flow) -> FlowGraph:
    """Parse do `graph_json` JÁ GRAVADO do flow — mesmo padrão de `flows.py::_validar_grafo`
    (CPU-bound fora do event loop). Grafo vazio (flow recém-criado, ADR-017) é tratado como
    "flow precisa ser salvo antes": não há bloco nenhum para historiar."""
    try:
        grafo = await asyncio.to_thread(parse_graph, flow.graph_json)
    except GraphParseError:
        raise HTTPException(status_code=422, detail=MSG_GRAFO_NAO_SALVO) from None
    if not grafo.nodes:
        raise HTTPException(status_code=422, detail=MSG_GRAFO_NAO_SALVO)
    return grafo


def _validar_porta(grafo: FlowGraph, block_id: str, port: str) -> None:
    """422 do Contract (ADR-041 D7). A regra mora em `historized.problema_de_porta` — a
    mesma que a poda do save e o import de bundle consultam; aqui só vira status HTTP."""
    problema = problema_de_porta(grafo, block_id, port)
    if problema is not None:
        raise HTTPException(status_code=422, detail=problema)


@router.get("", response_model=list[HistorizedVarOut], dependencies=[Depends(require_operator)])
async def list_historized_vars(
    flow_id: FlowIdQuery, db: AsyncSession = Depends(get_db)
) -> list[HistorizedVarOut]:
    stmt = (
        select(HistorizedVar, Tag.name, Tag.eu)
        .join(Tag, Tag.id == HistorizedVar.tag_id)
        .where(HistorizedVar.flow_id == flow_id)
        .order_by(HistorizedVar.block_id, HistorizedVar.port)
    )
    return [
        HistorizedVarOut(
            tag_id=hv.tag_id,
            flow_id=hv.flow_id,
            block_id=hv.block_id,
            port=hv.port,
            name=name,
            eu=eu,
        )
        for hv, name, eu in (await db.execute(stmt)).all()
    ]


@router.post("", response_model=HistorizedVarOut, status_code=201)
async def create_historized_var(
    body: HistorizedVarCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> HistorizedVarOut:
    flow = await _carregar_flow(db, body.flow_id)
    grafo = await _grafo_salvo(flow)
    _validar_porta(grafo, body.block_id, body.port)

    ja_existe = await db.scalar(
        select(HistorizedVar.tag_id).where(
            HistorizedVar.flow_id == body.flow_id,
            HistorizedVar.block_id == body.block_id,
            HistorizedVar.port == body.port,
        )
    )
    if ja_existe is not None:
        raise HTTPException(status_code=409, detail=MSG_PORTA_JA_HISTORIADA)

    label = grafo.node(body.block_id).label
    nome_preferido, nome_alternativo = derivar_nomes(flow.name, label, body.block_id, body.port)

    # SAVEPOINT por tentativa, não `rollback()`: aqui o erro NÃO é terminal (o vizinho
    # `calculated_tags.py` pode dar rollback porque levanta 409 na hora), e a rota precisa
    # seguir viva para tentar o nome alternativo (ADR-041 D6). `rollback()` mataria a
    # transação inteira do request — e, na suíte, o SAVEPOINT externo do conftest.
    async def _inserir_tag(nome: str) -> Tag | None:
        nova = Tag(
            project_id=flow.project_id,
            name=nome,
            node_id=None,
            direction="r",
            data_type="float",
            eu=body.eu,
        )
        try:
            async with db.begin_nested():
                db.add(nova)
                await db.flush()
        except IntegrityError:
            return None
        return nova

    tag = await _inserir_tag(nome_preferido)
    if tag is None and nome_alternativo != nome_preferido:
        tag = await _inserir_tag(nome_alternativo)
    if tag is None:
        raise HTTPException(status_code=409, detail=MSG_NOME_EM_USO)

    hv = HistorizedVar(tag_id=tag.id, flow_id=flow.id, block_id=body.block_id, port=body.port)
    db.add(hv)
    try:
        await db.commit()
    except IntegrityError:
        # A pré-checagem de `ja_existe` não é exclusão mútua: dois POST concorrentes para a
        # MESMA porta passam os dois por ela, e `uq_historized_vars_port` decide no commit.
        # Sem isto o perdedor vira 500 em vez do 409 que a mensagem já prevê.
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_PORTA_JA_HISTORIADA) from None
    await db.refresh(tag)

    saida = HistorizedVarOut(
        tag_id=tag.id,
        flow_id=flow.id,
        block_id=body.block_id,
        port=body.port,
        name=tag.name,
        eu=tag.eu,
    )
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Variável historiada '{tag.name}' criada",
        kind=KIND_HISTORIZED_VAR_CREATED,
        payload={
            "tag_id": tag.id,
            "flow_id": flow.id,
            "block_id": body.block_id,
            "port": body.port,
        },
    )
    # Mesma dica de hot-swap do PUT de flows.py (§4.1-1): só para flow rodando, senão o
    # `reload` viraria comando de task inexistente.
    if flow.desired_state == "running":
        await publicar_comando(redis_client, user, flow.id, "reload")
    return saida


@router.delete("/{tag_id}", status_code=204)
async def delete_historized_var(
    tag_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> None:
    hv = await db.get(HistorizedVar, tag_id)
    if hv is None:
        raise HTTPException(status_code=404, detail=MSG_NAO_ENCONTRADA)
    flow_id, block_id, port = hv.flow_id, hv.block_id, hv.port
    tag = await db.get(Tag, tag_id)
    name = tag.name if tag is not None else ""
    flow = await _carregar_flow(db, flow_id)

    # Remoção sempre pela linha de `tags` (ADR-041 D5) — nunca `db.delete(hv)` isolado, senão
    # a tag sobrevive órfã no seletor do TREND e fatal no export.
    await remover_variaveis_historiadas(db, [tag_id])
    await db.commit()
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Variável historiada '{name}' excluída",
        kind=KIND_HISTORIZED_VAR_DELETED,
        payload={"tag_id": tag_id, "flow_id": flow_id, "block_id": block_id, "port": port},
    )
    if flow.desired_state == "running":
        await publicar_comando(redis_client, user, flow_id, "reload")
