"""Snapshot em memória dos flows; fonte única do `/health` (spec F3 §2.2-10, RNF-07).

Espelha `opc-worker/state.py`: tipos puros, sem I/O. A diferença é a origem do dado. O
`ConnectionSnapshot` do worker é um objeto que o runtime da conexão muta, enquanto a
`FlowTask` (tarefa 1.4) já publica as métricas como propriedades — então aqui o snapshot é
uma **projeção tirada na hora da leitura**, e não uma cópia que alguém precise manter em dia:
`scan_ms` e `last_scan_ts` mudam a cada varredura, e um espelho atualizado pela passada de
watermark chegaria ao `/health` com até 10 s de atraso.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


class FlowMetrics(Protocol):
    """O que o `/health` precisa de um flow rodando; a `FlowTask` satisfaz isto."""

    @property
    def state(self) -> str: ...

    @property
    def scan_ms(self) -> float: ...

    @property
    def overruns(self) -> int: ...

    @property
    def last_scan_ts(self) -> datetime | None: ...


@dataclass(frozen=True, slots=True)
class FlowSnapshot:
    """Estado observável de um flow, congelado no instante da leitura."""

    state: str
    scan_ms: float
    overruns: int
    last_scan_ts: datetime | None

    @classmethod
    def of(cls, metrics: FlowMetrics) -> FlowSnapshot:
        return cls(
            state=metrics.state,
            scan_ms=metrics.scan_ms,
            overruns=metrics.overruns,
            last_scan_ts=metrics.last_scan_ts,
        )

    def to_health(self) -> dict[str, Any]:
        """Projeção no formato do `/health` (§2.2-10), já serializável em JSON."""
        return {
            "state": self.state,
            "scan_ms": self.scan_ms,
            "overruns": self.overruns,
            "last_scan_ts": _iso_utc(self.last_scan_ts),
        }


class RuntimeState:
    """Snapshot em memória do runtime inteiro; a fonte do `/health`.

    Guarda as `FlowTask` vivas, não cópias: quem as registra e as esquece é o supervisor,
    dono do ciclo de vida. Flow parado ou em falha **continua** registrado — falha é condição
    operacional que o operador precisa ver no corpo do `/health` (§2.2-10). Sai do mapa só
    quando deixa de existir para o supervisor (deletado do banco ou desmonte do serviço).
    """

    def __init__(self) -> None:
        self._sources: dict[int, FlowMetrics] = {}

    def track(self, flow_id: int, metrics: FlowMetrics) -> None:
        self._sources[flow_id] = metrics

    def forget(self, flow_id: int) -> None:
        self._sources.pop(flow_id, None)

    @property
    def flows(self) -> dict[int, FlowSnapshot]:
        """Projeção fresca de todos os flows conhecidos."""
        return {flow_id: FlowSnapshot.of(metrics) for flow_id, metrics in self._sources.items()}


def _iso_utc(moment: datetime | None) -> str | None:
    """ISO-8601 em UTC; datetime naive é tratado como UTC (o runtime só grava aware)."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC).isoformat()
    return moment.astimezone(UTC).isoformat()
