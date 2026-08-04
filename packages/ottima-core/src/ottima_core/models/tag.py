"""Tag OPC (RF-203; DDL: spec F1 §3.1)."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base, TimestampMixin


class Tag(TimestampMixin, Base):
    """Tag OPC (RF-203; DDL: spec F1 §3.1)."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("opc_connections.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    data_type: Mapped[str] = mapped_column(Text, nullable=False)
    eu: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))

    __table_args__ = (
        UniqueConstraint("connection_id", "name", name="uq_tags_connection_name"),
        CheckConstraint("direction IN ('r','w')", name="ck_tags_direction"),
        CheckConstraint("data_type IN ('float','int','bool')", name="ck_tags_data_type"),
    )
