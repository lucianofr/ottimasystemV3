"""Sensor virtual: variável de laboratório e suas análises (ADR-046 D1; spec §7.1; DDL: 0019).

A variável NÃO é linha em `tags`: entraria no seletor do canvas e no TREND com série vazia, e as
análises são retroativas, não podem sumir com a retenção. `LabSample.sampled_at` é o instante
da COLETA da amostra, nunca o da digitação."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base, TimestampMixin


class LabVariable(TimestampMixin, Base):
    __tablename__ = "lab_variables"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    eu: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_lab_variables_project_name"),)


class LabSample(Base):
    __tablename__ = "lab_samples"

    lab_variable_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lab_variables.id", ondelete="CASCADE"), primary_key=True
    )
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value: Mapped[float] = mapped_column(Double, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (CheckConstraint("source IN ('manual','csv')", name="ck_lab_samples_source"),)
