"""Schemas de projetos (RF-101, ADR-017): criação, atualização parcial e saída."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PendingSecretOut(BaseModel):
    """Pendência de segredo de uma conexão importada (spec F6 §3.2-8, decisão A-4)."""

    connection_name: str
    needs_password: bool
    needs_server_certificate: bool
    needs_app_certificate: bool


class ProjectImportIn(BaseModel):
    """`bundle` é `dict` de propósito: a validação em camadas do arquivo de projeto
    acontece no router de import (tarefa 2.3), não aqui."""

    name: str | None = None
    bundle: dict


class ProjectImportOut(BaseModel):
    project: ProjectOut
    pending_secrets: list[PendingSecretOut]
