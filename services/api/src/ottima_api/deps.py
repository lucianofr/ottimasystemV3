"""Dependências base da API: settings do app e sessão de banco por request."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.config import Settings


def get_app_settings(request: Request) -> Settings:
    """Settings resolvidas na criação do app (create_app)."""
    return request.app.state.settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Sessão por request, da factory criada no lifespan; sobrescrita nos testes."""
    async with request.app.state.session_factory() as session:
        yield session
