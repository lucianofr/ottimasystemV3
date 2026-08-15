"""Tag OPC ou tag calculada (RF-203/RF-208; DDL: spec F1 §3.1, ADR-033)."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base, TimestampMixin


class Tag(TimestampMixin, Base):
    """Tag OPC ou tag calculada (RF-203/RF-208; DDL: spec F1 §3.1, ADR-033)."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    connection_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("opc_connections.id", ondelete="CASCADE")
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    data_type: Mapped[str] = mapped_column(Text, nullable=False)
    eu: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))

    __table_args__ = (
        # NULL é distinto no Postgres: não restringe as calculadas (connection_id sempre NULL).
        UniqueConstraint("connection_id", "name", name="uq_tags_connection_name"),
        # Nome único por projeto só entre as calculadas (parcial: tag OPC pode repetir nome
        # de conexão para conexão, seu escopo de unicidade é `uq_tags_connection_name` acima).
        Index(
            "uq_tags_project_name",
            "project_id",
            "name",
            unique=True,
            postgresql_where=text("connection_id IS NULL"),
        ),
        CheckConstraint("direction IN ('r','w')", name="ck_tags_direction"),
        CheckConstraint("data_type IN ('float','int','bool')", name="ck_tags_data_type"),
        # Uma tag é OPC (dona = conexão, tem node_id) ou calculada (dona = projeto, sem
        # node_id) — nunca as duas nem nenhuma (ADR-033 D1).
        CheckConstraint(
            "(connection_id IS NOT NULL AND project_id IS NULL     AND node_id IS NOT NULL)"
            " OR (connection_id IS NULL AND project_id IS NOT NULL AND node_id IS NULL)",
            name="ck_tags_owner",
        ),
    )
