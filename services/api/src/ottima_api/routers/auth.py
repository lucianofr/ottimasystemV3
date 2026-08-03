"""Rotas de autenticação: login por usuário/senha e usuário corrente (spec F1 §5.1)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_app_settings, get_current_user, get_db
from ottima_core.config import Settings
from ottima_core.models import User
from ottima_core.schemas.auth import LoginIn, LoginOut, UserOut
from ottima_core.security import create_access_token, verify_password

router = APIRouter()


@router.post("/login", response_model=LoginOut)
async def login(
    body: LoginIn,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> LoginOut:
    user = await db.scalar(select(User).where(func.lower(User.username) == body.username.lower()))
    if user is None or not verify_password(body.password, user.password_hash) or not user.is_active:
        # mensagem única: não revelar se o usuário existe (spec §5.1)
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        secret=settings.secret_key,
        ttl_hours=settings.token_ttl_hours,
    )
    return LoginOut(
        access_token=token,
        expires_in=settings.token_ttl_hours * 3600,
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
