"""Consulta do log de eventos (RF-803): filtros combináveis, ts desc, leitura de operador."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, require_operator
from ottima_core.models import events_table
from ottima_core.schemas.events import EventOut

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000

router = APIRouter()


def _as_utc(value: datetime | None) -> datetime | None:
    """ISO-8601 sem offset vale como UTC; a coluna é timestamptz e não aceita naive."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


@router.get("", response_model=list[EventOut], dependencies=[Depends(require_operator)])
async def list_events(
    severity: Literal["info", "warning", "alarm"] | None = None,
    origin: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
) -> list[EventOut]:
    """Eventos mais recentes primeiro; sem paginação (padrão F1 §6.1)."""
    start, end = _as_utc(start), _as_utc(end)
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="start deve ser anterior a end")
    stmt = select(events_table).order_by(events_table.c.ts.desc()).limit(limit)
    if severity is not None:
        stmt = stmt.where(events_table.c.severity == severity)
    if origin is not None:
        stmt = stmt.where(events_table.c.origin == origin)
    if start is not None:
        stmt = stmt.where(events_table.c.ts >= start)
    if end is not None:
        stmt = stmt.where(events_table.c.ts <= end)
    rows = await db.execute(stmt)
    return [EventOut(**linha) for linha in rows.mappings()]
