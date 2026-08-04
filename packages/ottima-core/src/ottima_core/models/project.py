"""Projeto (ADR-017; DDL: spec F1 §3.1)."""

from sqlalchemy import BigInteger, Boolean, Identity, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base, TimestampMixin


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        # ADR-017: no máximo 1 projeto ativo — garantido no banco (spec §3.1)
        Index(
            "uq_projects_single_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )
