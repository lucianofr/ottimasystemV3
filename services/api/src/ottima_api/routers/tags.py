"""CRUD de tags OPC (RF-203): leitura para operador, escrita para admin (ADR-015)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, require_admin, require_operator
from ottima_core.models import OpcConnection, Tag
from ottima_core.schemas.tags import TagCreate, TagOut, TagUpdate

router = APIRouter()


async def _carregar(db: AsyncSession, tag_id: int) -> Tag:
    tag = await db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag não encontrada")
    return tag


@router.get("", response_model=list[TagOut], dependencies=[Depends(require_operator)])
async def list_tags(
    connection_id: int | None = None,
    direction: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[Tag]:
    """Lista tags; `direction` inválida apenas não casa nada (sem 422 no filtro)."""
    stmt = select(Tag).order_by(Tag.name)
    if connection_id is not None:
        stmt = stmt.where(Tag.connection_id == connection_id)
    if direction is not None:
        stmt = stmt.where(Tag.direction == direction)
    return list(await db.scalars(stmt))


@router.post("", response_model=TagOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_tag(body: TagCreate, db: AsyncSession = Depends(get_db)) -> Tag:
    if await db.get(OpcConnection, body.connection_id) is None:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    tag = Tag(**body.model_dump())
    db.add(tag)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Nome de tag já em uso nesta conexão"
        ) from None
    await db.refresh(tag)
    return tag


@router.get("/{tag_id}", response_model=TagOut, dependencies=[Depends(require_operator)])
async def get_tag(tag_id: int, db: AsyncSession = Depends(get_db)) -> Tag:
    return await _carregar(db, tag_id)


@router.patch("/{tag_id}", response_model=TagOut, dependencies=[Depends(require_admin)])
async def update_tag(tag_id: int, body: TagUpdate, db: AsyncSession = Depends(get_db)) -> Tag:
    tag = await _carregar(db, tag_id)
    for campo, valor in body.model_dump(exclude_unset=True).items():
        setattr(tag, campo, valor)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Nome de tag já em uso nesta conexão"
        ) from None
    await db.refresh(tag)
    return tag


@router.delete("/{tag_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_tag(tag_id: int, db: AsyncSession = Depends(get_db)) -> None:
    tag = await _carregar(db, tag_id)
    await db.delete(tag)
    await db.commit()
