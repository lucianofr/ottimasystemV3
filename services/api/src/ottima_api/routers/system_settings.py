"""Configurações gerais do sistema (RF-805): nível de log aplicado em runtime.

O PUT persiste no singleton `system_settings` e aplica no root logger DESTE processo já;
os demais serviços convergem em até ~10 s pelo `watch_log_level` (ottima_core.logging).
"""

import logging

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, get_redis, require_admin, require_operator
from ottima_core.bus import KIND_SYSTEM_LOG_LEVEL_CHANGED, publish_event
from ottima_core.models import SystemSettings, User
from ottima_core.schemas.system_settings import SystemSettingsOut, SystemSettingsUpdate

logger = logging.getLogger(__name__)

router = APIRouter()


async def _linha(db: AsyncSession) -> SystemSettings:
    # Seed da migration 0008 garante a linha única (id=1); não há rota de DELETE.
    return await db.get_one(SystemSettings, 1)


@router.get(
    "/system-settings",
    response_model=SystemSettingsOut,
    dependencies=[Depends(require_operator)],
)
async def get_system_settings(db: AsyncSession = Depends(get_db)) -> SystemSettings:
    return await _linha(db)


@router.put("/system-settings", response_model=SystemSettingsOut)
async def update_system_settings(
    body: SystemSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> SystemSettings:
    settings = await _linha(db)
    anterior = settings.log_level
    settings.log_level = body.log_level
    await db.commit()
    await db.refresh(settings)
    # Aplica já neste processo; os workers seguem pelo watch (sem canal novo — ADR do bus).
    logging.getLogger().setLevel(body.log_level)
    logger.info("Nível de log alterado de %s para %s", anterior, body.log_level)
    # Auditoria (ADR-020): sempre depois do commit, nunca antes.
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Nível de log alterado de {anterior} para {body.log_level}",
        kind=KIND_SYSTEM_LOG_LEVEL_CHANGED,
        payload={"log_level": body.log_level, "user": user.username},
    )
    return settings
