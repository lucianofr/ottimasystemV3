"""Flow (ADR-005/007/011/017; DDL: spec F1 §3.1)."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Integer,
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
        JSONB, nullable=False, server_default=text('\'{"nodes": [], "edges": []}\'::jsonb')
    )
    watchdog_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    watchdog_connection_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("opc_connections.id", ondelete="SET NULL")
    )
    watchdog_read_node_id: Mapped[str | None] = mapped_column(Text)
    watchdog_write_node_id: Mapped[str | None] = mapped_column(Text)
    watchdog_period_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1500")
    )
    watchdog_timeout_s: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("10")
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_flows_project_name"),
        CheckConstraint("ts_seconds IN (0.5,1,2,5,10,30,60)", name="ck_flows_ts"),
        CheckConstraint("desired_state IN ('running','stopped')", name="ck_flows_desired_state"),
        CheckConstraint(
            "watchdog_period_ms BETWEEN 500 AND 5000", name="ck_flows_wd_period"
        ),
        CheckConstraint("watchdog_timeout_s BETWEEN 2 AND 120", name="ck_flows_wd_timeout"),
    )
