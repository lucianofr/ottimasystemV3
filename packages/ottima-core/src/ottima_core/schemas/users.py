"""Schemas de gestão de usuários (spec F1 §5.5): criação e atualização parcial."""

from typing import Literal

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=1)
    name: str = Field(min_length=1)
    password: str = Field(min_length=8)  # spec §5.1
    role: Literal["admin", "operator"]


class UserUpdate(BaseModel):
    name: str | None = None
    password: str | None = Field(default=None, min_length=8)
    role: Literal["admin", "operator"] | None = None
    is_active: bool | None = None
