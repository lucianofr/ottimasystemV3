"""Sensor virtual: modelo treinado e vínculo bloco -> modelo (ADR-046 D6; spec §7.4; DDL: 0018).

`weights` guarda o artefato `.npz` (até 8 MB) e é `deferred`: listagens de modelos e de blocos
são consultadas por polling e não podem trazer o blob. Quem precisa dos pesos (carga no deploy,
comando de troca, export) pede com `undefer(SoftSensorModel.weights)`.

As três FKs do vínculo para o modelo NÃO têm `ON DELETE` (default `NO ACTION`): apagar um modelo
vinculado é recusado, mas a cascata do projeto, que apaga flows (e vínculos) e modelos no mesmo
comando, passa — `RESTRICT` é checado na hora e a barraria. `input_tag_ids` é array, sem FK:
tag apagada vira id órfão e quem lê trata."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from ottima_core.models.base import Base, TimestampMixin


class SoftSensorModel(TimestampMixin, Base):
    __tablename__ = "soft_sensor_models"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    period_s: Mapped[float] = mapped_column(Double, nullable=False)
    n_inputs: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    input_tag_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, server_default=text("'{}'")
    )
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False)
    weights: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_soft_sensor_models_project_name"),
        CheckConstraint("method IN ('pls','esn','lstm')", name="ck_soft_sensor_models_method"),
    )


class SoftSensorBinding(Base):
    """Vínculo `(flow_id, block_id)` -> modelo. `desired_model_id` é gravado pela API;
    `active_model_id` e `candidate_model_id`, só pelo runtime (spec §5.6)."""

    __tablename__ = "soft_sensor_bindings"

    flow_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("flows.id", ondelete="CASCADE"), primary_key=True
    )
    block_id: Mapped[str] = mapped_column(Text, primary_key=True)
    desired_model_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("soft_sensor_models.id")
    )
    active_model_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("soft_sensor_models.id")
    )
    candidate_model_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("soft_sensor_models.id")
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
