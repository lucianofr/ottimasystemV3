"""Usuário do sistema (RF-101/102; DDL: spec F1 §3.1)."""

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Identity, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        CheckConstraint("role IN ('admin','operator')", name="ck_users_role"),
        Index("uq_users_username", text("lower(username)"), unique=True),
    )
