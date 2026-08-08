"""Schemas de conexões OPC-UA (RF-201, ADR-009/021): senha só entra, nunca sai (spec §5.4)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SecurityPolicy = Literal["none", "basic256sha256"]
SecurityMode = Literal["none", "sign", "sign_and_encrypt"]
AuthMode = Literal["anonymous", "user_password", "certificate"]


def erro_policy_mode(security_policy: str, security_mode: str) -> str | None:
    """Regra de coerência policy x mode; vale para ConnectionCreate e para o bundle (§2.1-2)."""
    if (security_policy == "none") != (security_mode == "none"):
        return "SecurityPolicy None exige modo None; Basic256Sha256 exige Sign ou SignAndEncrypt"
    return None


def erro_watchdog(read_node_id: str | None, write_node_id: str | None) -> str | None:
    """Regra de coerência do watchdog; vale para ConnectionCreate e para o bundle (spec §2.1-2)."""
    if (read_node_id is None) != (write_node_id is None):
        return "Watchdog exige os dois node_ids (leitura e escrita) ou nenhum"
    return None


def erro_auth_username(auth_mode: str, auth_username: str | None) -> str | None:
    """Regra de coerência de autenticação só do bundle: exige usuário, nunca senha (spec §2.1-2)."""
    if auth_mode == "user_password" and not auth_username:
        return "Autenticação usuário/senha exige usuário"
    return None


class _ConnectionFields(BaseModel):
    name: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    security_policy: SecurityPolicy = "none"
    security_mode: SecurityMode = "none"
    auth_mode: AuthMode = "anonymous"
    auth_username: str | None = None
    server_cert_file: str | None = None
    watchdog_read_node_id: str | None = None
    watchdog_write_node_id: str | None = None
    watchdog_period_ms: int = Field(default=1500, ge=500, le=5000)  # ADR-009


class ConnectionCreate(_ConnectionFields):
    project_id: int
    auth_password: str | None = None  # write-only (spec §5.4)

    @model_validator(mode="after")
    def _coerencia(self) -> "ConnectionCreate":
        """Regras de coerência; o ValueError vira 422 no FastAPI."""
        erro = erro_policy_mode(self.security_policy, self.security_mode)
        if erro:
            raise ValueError(erro)
        if self.auth_mode == "user_password" and (not self.auth_username or not self.auth_password):
            raise ValueError("Autenticação usuário/senha exige usuário e senha")
        erro = erro_watchdog(self.watchdog_read_node_id, self.watchdog_write_node_id)
        if erro:
            raise ValueError(erro)
        return self


class ConnectionUpdate(BaseModel):
    """Atualização parcial; a coerência é checada no router sobre o estado final."""

    name: str | None = Field(default=None, min_length=1)
    endpoint: str | None = Field(default=None, min_length=1)
    security_policy: SecurityPolicy | None = None
    security_mode: SecurityMode | None = None
    auth_mode: AuthMode | None = None
    auth_username: str | None = None
    auth_password: str | None = None  # None = manter a senha atual
    server_cert_file: str | None = None
    watchdog_read_node_id: str | None = None
    watchdog_write_node_id: str | None = None
    watchdog_period_ms: int | None = Field(default=None, ge=500, le=5000)


class ConnectionOut(_ConnectionFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    has_password: bool
    created_at: datetime
    updated_at: datetime
