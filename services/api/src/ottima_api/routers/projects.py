"""CRUD de projetos (RF-101, ADR-017): leitura para operador, escrita e ativação para admin."""

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, get_redis, require_admin, require_operator
from ottima_api.messages import MSG_PROJETO_NAO_ENCONTRADO, MSG_PROJETO_NOME_EM_USO
from ottima_api.validacao import formatar_problemas
from ottima_core.bus import KIND_PROJECT_ACTIVATED, KIND_PROJECT_EXPORTED, publish_event
from ottima_core.models import Flow, OpcConnection, Project, Tag, User
from ottima_core.portability import ReferenciaTagInvalida, montar_bundle
from ottima_core.schemas.projects import ProjectCreate, ProjectOut, ProjectUpdate

# Sem dependência no router: os papéis variam por rota (ADR-015)
router = APIRouter()

_SLUG_SEP = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    """Reduz o nome do projeto a `[a-z0-9-]` para o filename do export (spec §3.1-2):
    minúsculas, sequências fora de a-z0-9 colapsadas num único hífen, hífens das pontas
    removidos. Nome que reduz a vazio cai em `projeto`."""
    slug = _SLUG_SEP.sub("-", name.lower()).strip("-")
    return slug or "projeto"


async def _carregar(db: AsyncSession, project_id: int) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=MSG_PROJETO_NAO_ENCONTRADO)
    return project


@router.get("", response_model=list[ProjectOut], dependencies=[Depends(require_operator)])
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[Project]:
    return list(await db.scalars(select(Project).order_by(Project.name)))


@router.post("", response_model=ProjectOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)) -> Project:
    """Projetos nascem inativos (ADR-017): a ativação é um passo explícito."""
    project = Project(name=body.name, description=body.description)
    db.add(project)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_PROJETO_NOME_EM_USO) from None
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut, dependencies=[Depends(require_operator)])
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)) -> Project:
    return await _carregar(db, project_id)


@router.patch("/{project_id}", response_model=ProjectOut, dependencies=[Depends(require_admin)])
async def update_project(
    project_id: int, body: ProjectUpdate, db: AsyncSession = Depends(get_db)
) -> Project:
    project = await _carregar(db, project_id)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=MSG_PROJETO_NOME_EM_USO) from None
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)) -> None:
    project = await _carregar(db, project_id)
    if project.is_active:
        # CASCADE removeria conexões/tags/flows do projeto em operação (spec §6.2)
        raise HTTPException(status_code=409, detail="Desative o projeto antes de excluí-lo")
    await db.delete(project)
    await db.commit()


@router.post("/{project_id}/activate", response_model=ProjectOut)
async def activate_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> Project:
    """Transação única: desativa o atual e ativa o alvo (ADR-017; índice parcial garante 1 ativo).

    F1 apenas persiste; a partir da F3 este endpoint também encerra a execução do projeto
    anterior via `flow.commands` (gancho registrado no spec §6.2). Reativar o projeto que já
    é o ativo continua respondendo 200 com o projeto, mas **não** republica o evento.
    """
    project = await _carregar(db, project_id)
    # Lido antes do UPDATE em massa abaixo, que apaga a informação. Reativar quem já é o ativo
    # não é transição, e desde a F3 o evento é destrutivo: o supervisor do flow-runtime para
    # TODOS os flows rodando ao recebê-lo (spec §2.2-8, gancho RF-101). Sem esta guarda, um
    # clique em "ativar" no projeto vigente derrubaria a planta em silêncio.
    ja_era_o_ativo = project.is_active
    # Um único commit no fim: o índice parcial rejeitaria o estado intermediário com 2 ativos
    await db.execute(update(Project).where(Project.is_active).values(is_active=False))
    project.is_active = True
    await db.commit()
    await db.refresh(project)
    if ja_era_o_ativo:
        return project
    # Depois do commit: evento sobre ativação que falhou envenenaria a reconciliação do worker
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Projeto '{project.name}' ativado",
        kind=KIND_PROJECT_ACTIVATED,
        payload={"project_id": project.id, "name": project.name},
    )
    return project


@router.get("/{project_id}/export")
async def export_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> Response:
    """Arquivo de projeto (bundle) para portabilidade entre instalações (spec §3.1).

    `require_admin`: mesmo sem segredos, o bundle revela a topologia OPC completa da
    planta (RF-102, PRD §2). Exporta **qualquer** projeto por id, não só o ativo.
    """
    project = await _carregar(db, project_id)
    connections = list(
        await db.scalars(select(OpcConnection).where(OpcConnection.project_id == project_id))
    )
    # Tags pelas conexões do projeto, nunca por uma consulta independente: `ref_por_id`
    # (ottima_core.portability.bundle) indexa por `connection.id` e propaga `KeyError` se
    # alguma tag carregada apontar para uma conexão fora deste conjunto (revisão da 1.3) —
    # o join garante que toda tag aqui pertence a uma das `connections` acima.
    tags = list(
        await db.scalars(
            select(Tag)
            .join(OpcConnection, Tag.connection_id == OpcConnection.id)
            .where(OpcConnection.project_id == project_id)
        )
    )
    flows = list(await db.scalars(select(Flow).where(Flow.project_id == project_id)))
    try:
        bundle = montar_bundle(
            project=project,
            connections=connections,
            tags=tags,
            flows=flows,
            exported_at=datetime.now(UTC),
        )
    except ReferenciaTagInvalida as exc:
        # Referência que não resolve aborta com 422, nunca exporta bundle quebrado (§2.2-5).
        raise HTTPException(
            status_code=422,
            detail=formatar_problemas(exc.problemas, cabecalho="Export recusado"),
        ) from None

    # Depois de montar o bundle: evento sobre export que falhou (422 acima) poluiria a
    # auditoria com uma ação que não aconteceu. A própria justificativa do RBAC é a
    # sensibilidade da topologia — export sem evento seria exfiltração silenciosa (SEC-05).
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Projeto '{project.name}' exportado",
        kind=KIND_PROJECT_EXPORTED,
        payload={"project_id": project.id, "name": project.name},
    )
    return Response(
        content=bundle.model_dump_json(),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{_slug(project.name)}.ottima.json"'
        },
    )
