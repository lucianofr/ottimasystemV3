"""CRUD de projetos (RF-101, ADR-017): leitura para operador, escrita e ativação para admin."""

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, get_redis, require_admin, require_operator
from ottima_core.bus import KIND_PROJECT_ACTIVATED, publish_event
from ottima_core.models import Project, User
from ottima_core.schemas.projects import ProjectCreate, ProjectOut, ProjectUpdate

# Sem dependência no router: os papéis variam por rota (ADR-015)
router = APIRouter()


async def _carregar(db: AsyncSession, project_id: int) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
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
        raise HTTPException(status_code=409, detail="Nome de projeto já em uso") from None
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
        raise HTTPException(status_code=409, detail="Nome de projeto já em uso") from None
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
    anterior via `flow.commands` (gancho registrado no spec §6.2).
    """
    project = await _carregar(db, project_id)
    # Um único commit no fim: o índice parcial rejeitaria o estado intermediário com 2 ativos
    await db.execute(update(Project).where(Project.is_active).values(is_active=False))
    project.is_active = True
    await db.commit()
    await db.refresh(project)
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
