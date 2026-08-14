"""Configurações gerais do sistema (RF-805; DDL: migration 0008)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, SmallInteger, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base


class SystemSettings(Base):
    """Linha única (id sempre 1): nível de log aplicado em runtime aos 4 serviços."""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    log_level: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INFO'"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_system_settings_singleton"),
        CheckConstraint(
            "log_level IN ('DEBUG','INFO','WARNING','ERROR','CRITICAL')",
            name="ck_system_settings_log_level",
        ),
    )
