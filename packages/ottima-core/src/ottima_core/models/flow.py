"""Flow (ADR-005/007/011/017; DDL: spec F1 §3.1)."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base, TimestampMixin


class Flow(TimestampMixin, Base):
    """Flow (ADR-005/007/011/017; DDL: spec F1 §3.1). CRUD chega na F3."""

    __tablename__ = "flows"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    ts_seconds: Mapped[float] = mapped_column(Numeric(4, 1), nullable=False)
    desired_state: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'stopped'")
    )
    graph_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{\"nodes\": [], \"edges\": []}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_flows_project_name"),
        CheckConstraint("ts_seconds IN (0.5,1,2,5,10,30,60)", name="ck_flows_ts"),
        CheckConstraint("desired_state IN ('running','stopped')", name="ck_flows_desired_state"),
    )
