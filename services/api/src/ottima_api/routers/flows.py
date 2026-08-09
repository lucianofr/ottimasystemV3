"""CRUD de flows (RF-302/306/307): leitura para operador, escrita para admin (ADR-015)."""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, get_redis, require_admin, require_operator
from ottima_api.messages import MSG_FLOW_NAO_ENCONTRADO, MSG_PROJETO_NAO_ENCONTRADO
from ottima_core.bus import (
    CHANNEL_FLOW_COMMANDS,
    KIND_FLOW_CREATED,
    KIND_FLOW_DELETED,
    KIND_FLOW_UPDATED,
    FlowCommand,
    publish_event,
)
from ottima_core.flowgraph import GraphParseError, parse_graph, validate_graph
from ottima_core.models import Flow, Project, User
from ottima_core.schemas.flows import (
    MAX_BIGINT,
    FlowCreate,
    FlowDetail,
    FlowOut,
    FlowSaved,
    FlowUpdate,
)
from ottima_core.tags import project_tags

logger = logging.getLogger(__name__)

# Sem dependência no router: os papéis variam por rota (ADR-015)
router = APIRouter()

# Id acima da faixa do BIGINT é 422 na borda; chegar ao driver viraria 5xx.
FlowId = Annotated[int, Path(ge=1, le=MAX_BIGINT)]
ProjectFilter = Annotated[int | None, Query(ge=1, le=MAX_BIGINT)]

MSG_NOME_EM_USO = "Nome de flow já em uso neste projeto"
MSG_RODANDO = "Flow em execução; pare o flow antes de excluir"

# As mensagens do flowgraph já usam "; " internamente (a de ciclo, por exemplo), então o
# separador entre reprovações precisa ser outro para o engenheiro ver onde uma termina.
SEPARADOR_REPROVACOES = " | "


async def _carregar(db: AsyncSession, flow_id: int) -> Flow:
    flow = await db.get(Flow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=MSG_FLOW_NAO_ENCONTRADO)
    return flow


def _reprovado(mensagens: list[str]) -> HTTPException:
    """422 de domínio com `detail` string, como no resto da API.

    Lista aqui seria invisível na tela: o cliente descarta `detail` que não seja string
    (frontend/src/lib/api.ts) e mostraria "Erro inesperado" no lugar da reprovação.
    """
    return HTTPException(status_code=422, detail=SEPARADOR_REPROVACOES.join(mensagens))


async def _publicar_evento(
    redis_client: Redis,
    user: User,
    kind: str,
    acao: str,
    *,
    flow_id: int,
    project_id: int,
    name: str,
) -> None:
    """Auditoria do CRUD (ADR-020, §4.3) — sempre depois do commit, nunca antes.

    `origin` é o usuário, como em `tags.py`/`projects.py`/`connections.py`, e o `flow_id` vai
    no payload. Os eventos de estado (`flow_deployed`/`flow_stopped`/`flow_failed`) são do
    runtime, que os emite ao materializar o efeito com `origin=flow:<id>` (§2.2-7): a lista do
    frontend deriva o último estado justamente daquele filtro e não pode casar CRUD.
    """
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Flow '{name}' {acao}",
        kind=kind,
        payload={"flow_id": flow_id, "project_id": project_id, "name": name},
    )


async def _publicar_comando(redis_client: Redis, user: User, flow_id: int, cmd: str) -> None:
    """Publica em `flow.commands` depois do commit; falha de publicação não derruba a rota.

    Comando é intenção (spec §5.1) e não gera evento aqui: quem audita o efeito é o runtime,
    ao materializá-lo (§2.2-7). Comando perdido = nada aconteceu: o `desired_state` já gravado
    fica divergente do estado publicado até alguém recomandar, porque `desired_state` é
    exibição e nunca é auto-aplicado (RF-306, ADR-017) — nem o watermark deploya sozinho.
    O `reload` é a exceção coberta: o watermark de 10 s pega o `updated_at` novo do flow
    rodando (§2.2-9).
    """
    comando = FlowCommand(
        flow_id=flow_id, cmd=cmd, args={}, user=f"user:{user.id}", ts=datetime.now(UTC)
    )
    try:
        await redis_client.publish(CHANNEL_FLOW_COMMANDS, comando.model_dump_json())
    except Exception:
        logger.exception("Falha ao publicar comando '%s' do flow %s", cmd, flow_id)


@router.get("", response_model=list[FlowOut], dependencies=[Depends(require_operator)])
async def list_flows(
    project_id: ProjectFilter = None, db: AsyncSession = Depends(get_db)
) -> list[Flow]:
    """Lista leve (spec §5.1): `graph_json` só sai no detalhe."""
    stmt = select(Flow).order_by(Flow.name)
    if project_id is not None:
        stmt = stmt.where(Flow.project_id == project_id)
    return list(await db.scalars(stmt))


@router.post("", response_model=FlowDetail, status_code=201)
async def create_flow(
    body: FlowCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> Flow:
    """Flow nasce parado (ADR-017) e com grafo vazio; o desenho chega pelo PUT."""
    if await db.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail=MSG_PROJETO_NAO_ENCONTRADO)
    flow = Flow(**body.model_dump(), graph_json={"nodes": [], "edges": []})
    db.add(flow)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_NOME_EM_USO) from None
    await db.refresh(flow)
    await _publicar_evento(
        redis_client,
        user,
        KIND_FLOW_CREATED,
        "criado",
        flow_id=flow.id,
        project_id=flow.project_id,
        name=flow.name,
    )
    return flow


@router.get("/{flow_id}", response_model=FlowDetail, dependencies=[Depends(require_operator)])
async def get_flow(flow_id: FlowId, db: AsyncSession = Depends(get_db)) -> Flow:
    return await _carregar(db, flow_id)


@router.put("/{flow_id}", response_model=FlowSaved)
async def update_flow(
    flow_id: FlowId,
    body: FlowUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
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
        graph, await project_tags(db, flow.project_id), float(flow.ts_seconds)
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
    await _publicar_evento(
        redis_client,
        user,
        KIND_FLOW_UPDATED,
        "atualizado",
        flow_id=flow.id,
        project_id=flow.project_id,
        name=flow.name,
    )
    # Dica de hot-swap (§4.1-1) só para flow rodando: parado, o save é apenas persistência e o
    # deploy futuro lê o grafo vigente (§4.1-2) — `reload` viraria comando de task inexistente.
    if flow.desired_state == "running":
        await _publicar_comando(redis_client, user, flow_id, "reload")
    return FlowSaved(flow=FlowDetail.model_validate(flow), warnings=resultado.warnings)


@router.delete("/{flow_id}", status_code=204)
async def delete_flow(
    flow_id: FlowId,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> None:
    flow = await _carregar(db, flow_id)
    if flow.desired_state == "running":
        raise HTTPException(status_code=409, detail=MSG_RODANDO)
    # Identidade capturada antes do delete: depois o objeto não é mais legível
    project_id, name = flow.project_id, flow.name
    await db.delete(flow)
    await db.commit()
    await _publicar_evento(
        redis_client,
        user,
        KIND_FLOW_DELETED,
        "excluído",
        flow_id=flow_id,
        project_id=project_id,
        name=name,
    )


async def _comandar(
    db: AsyncSession,
    redis_client: Redis,
    user: User,
    flow_id: int,
    desired_state: str,
    cmd: str,
) -> Response:
    """Estado desejado e comando andam juntos (spec §5.1, RF-306): grava, commita, publica.

    Idempotência é do runtime (§2.2-7, RNF-05): a API conhece só o estado desejado, então
    deploy de flow já rodando grava e publica igual — o runtime trata como no-op.
    """
    flow = await _carregar(db, flow_id)
    flow.desired_state = desired_state
    await db.commit()
    await _publicar_comando(redis_client, user, flow_id, cmd)
    # Sem corpo: um campo de estado aqui seria lido como confirmação, e o comando é só
    # intenção — quem confirma é o `flow.status` do runtime (DESIGN.md, Regra do Estado
    # Publicado).
    return Response(status_code=202)


@router.post("/{flow_id}/deploy", status_code=202)
async def deploy_flow(
    flow_id: FlowId,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> Response:
    return await _comandar(db, redis_client, user, flow_id, "running", "deploy")


@router.post("/{flow_id}/stop", status_code=202)
async def stop_flow(
    flow_id: FlowId,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> Response:
    return await _comandar(db, redis_client, user, flow_id, "stopped", "stop")
