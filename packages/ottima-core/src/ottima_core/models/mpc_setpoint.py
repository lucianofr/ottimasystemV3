"""SP do operador do bloco MPC persistido (emenda da decisão A-4 da spec F4; DDL:
migration 0014).

Só o NÚMERO do SP persiste — os modos (LOCAL/REMOTO, MAN/AUTO) seguem voláteis
(RNF-03/ADR-010): boot sempre LOCAL+MAN, e o SP volta como semente de `reset()` do
bloco, clampado aos `sp_limits` vigentes. `ON DELETE CASCADE` em `flows` leva as linhas
junto quando o flow é apagado."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Double, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base


class MpcSetpoint(Base):
    __tablename__ = "mpc_setpoints"

    flow_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("flows.id", ondelete="CASCADE"), primary_key=True
    )
    block_id: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)
    var_id: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)
    value: Mapped[float] = mapped_column(Double, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
