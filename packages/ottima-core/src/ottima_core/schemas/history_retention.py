"""Schema de retenção de histórico configurável (ADR-003 revisado)."""

from datetime import datetime

from pydantic import BaseModel, Field

MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 120


class HistoryRetentionOut(BaseModel):
    retention_days: int
    updated_at: datetime


class HistoryRetentionUpdate(BaseModel):
    retention_days: int = Field(ge=MIN_RETENTION_DAYS, le=MAX_RETENTION_DAYS)
