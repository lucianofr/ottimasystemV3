"""Bloco Barramento-Assinar: a saída `out` é o último valor publicado na `key` (ADR-042).

Mesma forma do OPC-Read (nenhuma entrada, saída `out`, leitura síncrona de um espelho em
memória), trocando o `ValueSnapshot` por `ExchangeSnapshot`: quem assina o Redis é o espelho
do processo, um por `flow-runtime`, nunca o bloco (ADR-004 — `step()` não faz round-trip).

A validade é por IDADE e é automática (D4): o quadro traz o `period_s` do publicador, e um
valor mais velho que `3 × period_s` sai com `ok=False`. Os dois estados de ausência são
distintos de propósito:

- `key` **nunca publicada** ⇒ `PortSample(None, False)`: cold start, congela o bloco a
  jusante por `has_cold_input`.
- `key` publicada e **expirada** ⇒ `PortSample(último valor, ok=False)`: valor conhecido +
  flag de invalidez, exatamente o que o OPC-Read faz com `quality != 0` (decisão A-6).

Sem a expiração, parar o flow publicador deixaria este bloco entregando o último valor com
`ok=True` para sempre, e um MPC a jusante controlaria sobre um dado morto.
"""

import math
from collections.abc import Mapping
from datetime import UTC, datetime

from ottima_core.snapshot import ExchangeSnapshot

from .base import Block, PortSample

OUTPUT_PORTS = ("out",)

STALE_PERIODS = 3.0
"""Margem de validade em múltiplos do Ts do publicador (ADR-042 D4): duas varreduras
perdidas ainda passam; a terceira invalida."""


class BusSubscribeBlock(Block):
    """Nenhuma entrada; saída `out` (bivalente)."""

    def __init__(self, block_id: str, *, key: str, snapshot: ExchangeSnapshot) -> None:
        super().__init__(block_id)
        self._key = key
        self._snapshot = snapshot

    @property
    def output_ports(self) -> tuple[str, ...]:
        return OUTPUT_PORTS

    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        value = self._snapshot.get(self._key)
        if value is None:
            return {"out": PortSample(None, False)}

        agora = ts if ts is not None else datetime.now(UTC)
        idade = (agora - value.ts).total_seconds()
        # `period_s` chega do publicador: patológico (≤0, nan, inf) não pode virar tolerância
        # infinita nem invalidez permanente — cai no pior caso conservador (expira sempre).
        limite = STALE_PERIODS * value.period_s
        fresco = math.isfinite(limite) and limite > 0 and idade <= limite
        return {"out": PortSample(value.v, value.ok and fresco)}
