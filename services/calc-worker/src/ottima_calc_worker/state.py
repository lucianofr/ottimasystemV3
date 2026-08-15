"""Configuração e snapshot em memória das tags calculadas (ADR-033).

Tipos puros, sem I/O: `RunnerConfig` é como o supervisor lê a config de uma tag no banco
(`supervisor.py`); `RunnerHealth` é o snapshot imutável que cada `CalcTagRunner` expõe
para o `/health` (`runner.py`).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    """Configuração de uma tag calculada, tal como o supervisor a lê do banco."""

    tag_id: int
    code: str
    period_seconds: int
    input_tag_ids: tuple[int, ...]

    @property
    def restart_key(self) -> tuple[str, int, tuple[int, ...]]:
        """Tudo que exige reiniciar o runner — e perder o `state` do script — quando muda."""
        return (self.code, self.period_seconds, self.input_tag_ids)


@dataclass(frozen=True, slots=True)
class RunnerHealth:
    """Estado observável de um `CalcTagRunner`; alimenta o `/health` (spec tags-calculadas).

    Imutável de propósito: cada ciclo produz uma instância nova em vez de mutar campos —
    quem lê `runner.health` do `/health` nunca vê um objeto meio atualizado.
    """

    last_publish_ts: datetime | None = None
    # "ok"|"timeout"|"error"|"publish_failed" — None antes do 1o ciclo
    last_status: str | None = None
    consecutive_failures: int = 0
    overrun_count: int = 0

    def to_health(self) -> dict[str, Any]:
        return {
            "last_publish_ts": _iso_utc(self.last_publish_ts),
            "last_status": self.last_status,
            "consecutive_failures": self.consecutive_failures,
            "overrun_count": self.overrun_count,
        }


def _iso_utc(moment: datetime | None) -> str | None:
    """ISO-8601 em UTC; datetime naive é tratado como UTC (o runner só publica aware)."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC).isoformat()
    return moment.astimezone(UTC).isoformat()
