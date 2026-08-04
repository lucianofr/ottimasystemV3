"""Configuração e snapshot em memória das conexões OPC-UA (spec F2 §2.2-2/3/8).

Tipos puros, sem I/O: a configuração vem do banco (tarefa 1.4) e o snapshot é a fonte
única do `/health` do worker (tarefa 1.5).
"""

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal


class ConnectionState(StrEnum):
    """Estados da máquina de conexão (spec §2.2-2)."""

    CONNECTING = "connecting"
    UP = "up"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TagConfig:
    """Tag configurada de uma conexão."""

    id: int
    name: str
    node_id: str
    direction: Literal["r", "w"]
    data_type: Literal["float", "int", "bool"]


@dataclass(frozen=True, slots=True)
class ConnectionConfig:
    """Configuração de uma conexão OPC-UA, tal como o worker a enxerga."""

    id: int
    project_id: int
    name: str
    endpoint: str
    security_policy: str  # "none" | "basic256sha256"
    security_mode: str  # "none" | "sign" | "sign_and_encrypt"
    auth_mode: str  # "anonymous" | "user_password" | "certificate"
    auth_username: str | None
    auth_password_enc: str | None  # token Fernet — NUNCA logado, NUNCA em snapshot
    server_cert_file: str | None
    watchdog_read_node_id: str | None
    watchdog_write_node_id: str | None
    watchdog_period_ms: int
    tags: tuple[TagConfig, ...]

    @property
    def has_watchdog(self) -> bool:
        """Só há watchdog com o par de node_ids: sem os dois não há handshake (ADR-009)."""
        return bool(self.watchdog_read_node_id and self.watchdog_write_node_id)

    @property
    def session_key(self) -> tuple:
        """Tudo que exige recriar a sessão asyncua quando muda (tarefa 1.4)."""
        return tuple(getattr(self, f.name) for f in fields(self) if f.name != "tags")

    @property
    def tags_key(self) -> tuple:
        """Conjunto de tags em ordem estável: muda ⇒ recria só a subscription (tarefa 1.4)."""
        return tuple(sorted(self.tags, key=lambda tag: tag.id))


@dataclass(slots=True)
class TagSnapshot:
    """Último valor conhecido de uma tag."""

    ts: datetime
    value: float
    quality: int
    # Relógio de parede da publicação, distinto de `ts` (timestamp da fonte): existe para
    # exibição e diagnóstico, nunca para medir decurso.
    published_at: datetime
    # `time.monotonic()` da publicação: é o ÚNICO campo usado para medir decurso (o
    # heartbeat, tarefa 1.3, decide por ele). Ajuste de NTP para trás não o afeta.
    published_monotonic: float


@dataclass(slots=True)
class ConnectionSnapshot:
    """Estado observável de uma conexão; alimenta o `/health` (spec §2.2-8)."""

    name: str
    state: ConnectionState = ConnectionState.CONNECTING
    watchdog_alive: bool = False
    session_up_since: datetime | None = None
    last_publish_ts: datetime | None = None
    tags_subscribed: int = 0
    monitored_errors: int = 0
    write_errors: int = 0
    last_values: dict[int, TagSnapshot] = field(default_factory=dict)

    def to_health(self) -> dict[str, Any]:
        """Projeção do snapshot no formato do `/health`, já serializável em JSON.

        `last_values` fica de fora de propósito: o `/health` é diagnóstico de conexão,
        não canal de dados de processo.
        """
        return {
            "name": self.name,
            "state": self.state.value,
            "watchdog_alive": self.watchdog_alive,
            "session_up_since": _iso_utc(self.session_up_since),
            "last_publish_ts": _iso_utc(self.last_publish_ts),
            "tags_subscribed": self.tags_subscribed,
            "monitored_errors": self.monitored_errors,
            "write_errors": self.write_errors,
        }


@dataclass(slots=True)
class WorkerState:
    """Snapshot em memória do worker inteiro; a fonte do /health (spec §2.2-8)."""

    connections: dict[int, ConnectionSnapshot] = field(default_factory=dict)


def _iso_utc(moment: datetime | None) -> str | None:
    """ISO-8601 em UTC; datetime naive é tratado como UTC (o worker só grava aware)."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC).isoformat()
    return moment.astimezone(UTC).isoformat()
