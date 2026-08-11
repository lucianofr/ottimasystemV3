"""Schemas do arquivo de projeto (bundle) — forma normativa do export/import (spec F6 §2.1-4).

Todos os modelos são fechados (`extra="forbid"`) e não carregam ids, timestamps ou
segredos (spec §2.3): o bundle é o contrato que circula entre instalações, nunca um
espelho dos schemas `Create`/`Out` que expõem estado interno do banco.
"""

from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from ottima_core.schemas.connections import (
    AuthMode,
    SecurityMode,
    SecurityPolicy,
    erro_auth_username,
    erro_policy_mode,
)
from ottima_core.schemas.flows import DesiredState, TsSeconds, erro_watchdog_flow
from ottima_core.schemas.tags import DataType, Direction

SCHEMA_VERSION: Final[int] = 1


class BundleTagRef(BaseModel):
    """Referência de tag dentro do grafo (spec §2.2-2): objeto, nunca a string "conexao/tag"."""

    model_config = ConfigDict(extra="forbid")

    connection: str
    tag: str


class BundleProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""


class BundleConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    endpoint: str
    security_policy: SecurityPolicy = "none"
    security_mode: SecurityMode = "none"
    auth_mode: AuthMode = "anonymous"
    auth_username: str | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> "BundleConnection":
        """Mesmas regras de policy de ConnectionCreate; auth exige só usuário (§2.1-2)."""
        erro = erro_policy_mode(self.security_policy, self.security_mode) or erro_auth_username(
            self.auth_mode, self.auth_username
        )
        if erro:
            raise ValueError(erro)
        return self


class BundleTag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection: str
    name: str
    node_id: str
    direction: Direction
    data_type: DataType
    eu: str = ""
    description: str = ""


class BundleFlow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    ts_seconds: TsSeconds
    desired_state: DesiredState = "stopped"
    graph: dict
    watchdog_enabled: bool = False
    watchdog_connection: str | None = None
    """Nome da conexão (spec §2.2-2, mesma convenção de `BundleTagRef`), não o id — o id
    não sobrevive ao transplante entre instalações."""
    watchdog_read_node_id: str | None = None
    watchdog_write_node_id: str | None = None
    watchdog_period_ms: int = 1500

    @model_validator(mode="after")
    def _coerencia(self) -> "BundleFlow":
        """Mesma regra de `erro_watchdog_flow`, sobre o `connection_id` resolvido por nome —
        aqui só confere presença/distinção; a existência do nome é camada 3 (bundle.py)."""
        erro = erro_watchdog_flow(
            self.watchdog_enabled,
            0 if self.watchdog_connection else None,
            self.watchdog_read_node_id,
            self.watchdog_write_node_id,
        )
        if erro:
            raise ValueError(erro)
        return self


class ProjectBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    exported_at: datetime
    project: BundleProject
    connections: list[BundleConnection]
    tags: list[BundleTag]
    flows: list[BundleFlow]
