"""Sensor virtual: fila de jobs do ml-worker (ADR-046 D7; spec §7.5; DDL: 0019).

Única fila do sistema (ADR-004): a API só grava linhas; o ml-worker consulta por
`(status, id)` e executa um job por vez."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base


class MlJob(Base):
    __tablename__ = "ml_jobs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    progress: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("kind IN ('dataset_build','train','tune')", name="ck_ml_jobs_kind"),
        CheckConstraint(
            "status IN ('queued','running','done','failed','cancelled')", name="ck_ml_jobs_status"
        ),
        Index("ix_ml_jobs_status_id", "status", "id"),
    )
