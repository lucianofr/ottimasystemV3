"""Seed idempotente do primeiro admin (spec F1 §5.3). Uso: python -m ottima_api.seed"""

import asyncio
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.config import Settings, get_settings
from ottima_core.db import create_engine, create_session_factory
from ottima_core.logging import setup_logging
from ottima_core.models import User
from ottima_core.security import hash_password

logger = logging.getLogger("ottima.seed")


async def seed_admin(session: AsyncSession, settings: Settings) -> bool:
    """Cria o admin inicial se a tabela users estiver vazia; True somente quando criou."""
    count = await session.scalar(select(func.count()).select_from(User))
    if count:
        return False
    if not settings.admin_username or not settings.admin_password:
        logger.error(
            "Tabela users vazia e OTTIMA_ADMIN_USERNAME/OTTIMA_ADMIN_PASSWORD ausentes — "
            "nenhum admin criado; corrija o .env e reinicie"
        )
        return False
    session.add(
        User(
            username=settings.admin_username,
            name=settings.admin_name,
            password_hash=hash_password(settings.admin_password),
            role="admin",
        )
    )
    await session.commit()
    logger.info("Admin inicial criado: %s", settings.admin_username)
    return True


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, "api-seed")
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    async with factory() as session:
        await seed_admin(session, settings)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
