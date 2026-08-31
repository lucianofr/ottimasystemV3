"""Valores de operacao de blocos malha que sobrevivem a restart (ADR-039 secao 4.10;
DDL: migration 0015).

Upsert do valor corrente por (flow_id, block_id) — espelho de mpc_setpoint.py. SP e
MAN_OUT sao restaurados no deploy como semente; TARGET e persistido para auditoria, mas o
boot e sempre MAN (re-engajar e ato do operador). `ON DELETE CASCADE` em `flows` leva as
linhas junto quando o flow e apagado."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Double, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base


class LoopSetpoint(Base):
    __tablename__ = "loop_setpoints"

    flow_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("flows.id", ondelete="CASCADE"), primary_key=True
    )
    block_id: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)
    sp: Mapped[float | None] = mapped_column(Double, nullable=True)
    man_out: Mapped[float | None] = mapped_column(Double, nullable=True)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
