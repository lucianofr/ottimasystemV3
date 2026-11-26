"""Sensor virtual: conjunto de treino (ADR-046 D1; spec §7.3; DDL: 0019).

`data` guarda o conjunto congelado (até 64 MiB) e é `deferred`: as listagens são consultadas por
polling e não podem trazer o blob. Quem precisa do conteúdo pede com
`undefer(SoftSensorDataset.data)`.

A FK para `lab_variables` NÃO tem `ON DELETE` (variável usada por conjunto não pode ser apagada).
Diferente de `soft_sensor.py`, não precisa ser adiada: conjunto e variável são ambos filhos DIRETOS
de `projects`, e a cascata do projeto passa seja qual for a ordem dos triggers de RI (o defeito do
vínculo vinha de a cascata dos flows ser de dois níveis).

`input_tag_ids` é array, sem FK: tag apagada vira id órfão e quem lê trata."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    LargeBinary,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base, TimestampMixin


class SoftSensorDataset(TimestampMixin, Base):
    __tablename__ = "soft_sensor_datasets"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    lab_variable_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lab_variables.id"), nullable=False
    )
    input_tag_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    period_s: Mapped[float] = mapped_column(Double, nullable=False)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="collecting")
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    inputs_meta: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_soft_sensor_datasets_project_name"),
        CheckConstraint(
            "period_s IN (1,2,5,10,30,60,300,600)", name="ck_soft_sensor_datasets_period"
        ),
        CheckConstraint(
            "status IN ('collecting','building','ready','failed')",
            name="ck_soft_sensor_datasets_status",
        ),
    )
