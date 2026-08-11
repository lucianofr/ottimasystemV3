"""Retenção configurável de histórico de variáveis de processo (ADR-003 revisado).

Reprograma as retention policies nativas do TimescaleDB no mesmo idioma já usado pelas
migrations 0002/0003 (remove + add, não `alter_job`/jsonb) e força liberação imediata de
espaço via `drop_chunks` — sem esperar o próximo ciclo agendado do job. `events` fica de
fora (ADR-020: log de alarmes, não variável de processo).
"""

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, get_redis, require_admin, require_operator
from ottima_core.bus import KIND_HISTORY_RETENTION_CHANGED, publish_event
from ottima_core.models import HistoryRetentionSettings, User
from ottima_core.schemas.history_retention import HistoryRetentionOut, HistoryRetentionUpdate

router = APIRouter()

# Hypertables de variável de processo (brutas + seus continuous aggregates de 1 min).
_HYPERTABLES = ("samples", "samples_1m", "mpc_samples", "mpc_samples_1m")


async def _linha(db: AsyncSession) -> HistoryRetentionSettings:
    # Seed da migration 0006 garante a linha única (id=1); não há rota de DELETE.
    return await db.get_one(HistoryRetentionSettings, 1)


@router.get(
    "/history-retention",
    response_model=HistoryRetentionOut,
    dependencies=[Depends(require_operator)],
)
async def get_history_retention(db: AsyncSession = Depends(get_db)) -> HistoryRetentionSettings:
    return await _linha(db)


@router.put("/history-retention", response_model=HistoryRetentionOut)
async def update_history_retention(
    body: HistoryRetentionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> HistoryRetentionSettings:
    settings = await _linha(db)
    dias_antigos = settings.retention_days
    settings.retention_days = body.retention_days
    for hypertable in _HYPERTABLES:
        await db.execute(text(f"SELECT remove_retention_policy('{hypertable}', if_exists => true)"))
        await db.execute(
            text(f"SELECT add_retention_policy('{hypertable}', make_interval(days => :days))"),
            {"days": body.retention_days},
        )
        # Sem isto, encolher a janela só valeria a partir do próximo ciclo agendado do
        # scheduler do Timescale — o pedido é liberar espaço já.
        await db.execute(
            text(f"SELECT drop_chunks('{hypertable}', older_than => make_interval(days => :days))"),
            {"days": body.retention_days},
        )
    await db.commit()
    await db.refresh(settings)
    # Auditoria (ADR-020): a mutação apaga histórico permanentemente nas 4 estruturas —
    # sempre depois do commit, nunca antes (mesmo padrão de tags.py/projects.py).
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Retenção de histórico alterada de {dias_antigos} para {body.retention_days} dias",
        kind=KIND_HISTORY_RETENTION_CHANGED,
        payload={"retention_days_old": dias_antigos, "retention_days_new": body.retention_days},
    )
    return settings
