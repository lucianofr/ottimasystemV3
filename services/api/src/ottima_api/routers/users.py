"""CRUD de usuários (RF-002, spec §5.5): exclusivo de admin, com guardas de auto-gestão."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, require_admin
from ottima_core.models import User
from ottima_core.schemas.auth import UserOut
from ottima_core.schemas.users import UserCreate, UserUpdate
from ottima_core.security import hash_password

router = APIRouter(dependencies=[Depends(require_admin)])


async def _outro_admin_ativo_existe(db: AsyncSession, alem_de_id: int) -> bool:
    n = await db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == "admin", User.is_active, User.id != alem_de_id)
    )
    return bool(n)


async def _carregar(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return user


@router.get("", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[User]:
    return list(await db.scalars(select(User).order_by(User.username)))


@router.post("", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db)) -> User:
    user = User(
        username=body.username,
        name=body.name,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Nome de usuário já em uso") from None
    await db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)) -> User:
    return await _carregar(db, user_id)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin),
) -> User:
    user = await _carregar(db, user_id)
    rebaixa = body.role == "operator" and user.role == "admin"
    desativa = body.is_active is False and user.is_active
    if user.id == current.id and (rebaixa or desativa):
        raise HTTPException(
            status_code=409, detail="Não é possível rebaixar ou desativar o próprio usuário"
        )
    # Com as regras atuais este ramo é inalcançável: `current` é sempre um admin ativo
    # diferente de `user` (a auto-gestão já foi barrada acima), logo sempre existe outro
    # admin ativo. Mantido como defesa em profundidade caso as guardas acima mudem.
    if (
        (rebaixa or desativa)
        and user.role == "admin"
        and user.is_active
        and not await _outro_admin_ativo_existe(db, user.id)
    ):
        raise HTTPException(
            status_code=409, detail="Não é possível remover o último administrador ativo"
        )
    if body.name is not None:
        user.name = body.name
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Nome de usuário já em uso") from None
    await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin),
) -> None:
    user = await _carregar(db, user_id)
    if user.id == current.id:
        raise HTTPException(status_code=409, detail="Não é possível excluir o próprio usuário")
    # Inalcançável hoje pelo mesmo motivo do PATCH: `current` é um admin ativo distinto de
    # `user`. Mantido como defesa em profundidade caso a guarda de auto-exclusão mude.
    if user.role == "admin" and user.is_active and not await _outro_admin_ativo_existe(db, user.id):
        raise HTTPException(
            status_code=409, detail="Não é possível remover o último administrador ativo"
        )
    await db.delete(user)
    await db.commit()
