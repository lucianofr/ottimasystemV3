"""Retenção configurável de histórico de variáveis (ADR-003 revisado; DDL: migration 0006)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, SmallInteger, func, text
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base


class HistoryRetentionSettings(Base):
    """Linha única (id sempre 1): janela de retenção das hypertables de variáveis de processo."""

    __tablename__ = "history_retention_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    retention_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("30")
    )
    events_retention_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("30")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_history_retention_settings_singleton"),
        CheckConstraint(
            "retention_days BETWEEN 1 AND 120", name="ck_history_retention_settings_days"
        ),
        CheckConstraint(
            "events_retention_days BETWEEN 1 AND 90",
            name="ck_history_retention_settings_events_days",
        ),
    )
