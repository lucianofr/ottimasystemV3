"""Conexão OPC-UA (RF-201/206, ADR-009/021; DDL: spec F1 §3.1)."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base, TimestampMixin


class OpcConnection(TimestampMixin, Base):
    """Conexão OPC-UA (RF-201/206, ADR-009/021; DDL: spec F1 §3.1)."""

    __tablename__ = "opc_connections"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    security_policy: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'none'")
    )
    security_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'"))
    auth_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'anonymous'"))
    auth_username: Mapped[str | None] = mapped_column(Text)
    auth_password_enc: Mapped[str | None] = mapped_column(Text)  # token Fernet — nunca em response
    server_cert_file: Mapped[str | None] = mapped_column(Text)  # arquivo no volume certs
    polling_period_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1000")
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_opc_connections_project_name"),
        CheckConstraint(
            "security_policy IN ('none','basic256sha256')", name="ck_opc_connections_policy"
        ),
        CheckConstraint(
            "security_mode IN ('none','sign','sign_and_encrypt')", name="ck_opc_connections_mode"
        ),
        CheckConstraint(
            "auth_mode IN ('anonymous','user_password','certificate')",
            name="ck_opc_connections_auth",
        ),
        CheckConstraint(
            "(security_policy = 'none' AND security_mode = 'none')"
            " OR (security_policy <> 'none' AND security_mode <> 'none')",
            name="ck_opc_connections_policy_mode",
        ),
        CheckConstraint(
            "polling_period_ms BETWEEN 100 AND 60000", name="ck_opc_connections_polling_period"
        ),
    )
