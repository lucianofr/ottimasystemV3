"""Dependências base da API: settings do app, sessão de banco e usuário autenticado."""

from collections.abc import AsyncIterator

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.config import Settings
from ottima_core.models import User
from ottima_core.security import decode_access_token


def get_app_settings(request: Request) -> Settings:
    """Settings resolvidas na criação do app (create_app)."""
    return request.app.state.settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Sessão por request, da factory criada no lifespan; sobrescrita nos testes."""
    async with request.app.state.session_factory() as session:
        yield session


_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> User:
    """Usuário do Bearer token; 401 sem token, com token inválido/expirado ou inativo."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Não autenticado")
    try:
        payload = decode_access_token(creds.credentials, secret=settings.secret_key)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada") from None
    user = await db.get(User, int(payload["sub"]))  # sub é string por contrato do JWT
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")
    return user


async def require_operator(user: User = Depends(get_current_user)) -> User:
    return user  # admin e operator (ADR-015: admin faz tudo; operador enxerga tudo)


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Ação restrita a administradores")
    return user
