"""Schemas de autenticação (spec F1 §5.1): entrada de login e saída de usuário/token."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    """Usuário exposto pela API — nunca inclui password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    name: str
    role: Literal["admin", "operator"]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LoginOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut
