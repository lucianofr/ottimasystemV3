"""Schema de retenção de histórico configurável (ADR-003 revisado)."""

from datetime import datetime

from pydantic import BaseModel, Field

MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 120
MAX_EVENTS_RETENTION_DAYS = 90


class HistoryRetentionOut(BaseModel):
    retention_days: int
    events_retention_days: int
    updated_at: datetime


class HistoryRetentionUpdate(BaseModel):
    """Ambos opcionais: `None` mantém o valor gravado (a página de configurações edita as
    duas retenções em seções independentes)."""

    retention_days: int | None = Field(default=None, ge=MIN_RETENTION_DAYS, le=MAX_RETENTION_DAYS)
    events_retention_days: int | None = Field(
        default=None, ge=MIN_RETENTION_DAYS, le=MAX_EVENTS_RETENTION_DAYS
    )
