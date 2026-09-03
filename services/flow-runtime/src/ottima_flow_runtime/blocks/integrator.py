"""Bloco Integrator (totalizador): acumula `in` no tempo do flow.

`out += in * Ts / fator` por varredura, com fator 1/60/3600 conforme `time_base`
("s"/"min"/"h") — a EU de tempo em que a entrada está expressa (ex.: vazão em kg/min).
O Ts vem do scheduler, única autoridade de tempo do laço (ADR-031): nada de relógio de
parede, que tornaria o total sensível a jitter e overrun.

Porta `reset` (opcional): valor ≠ 0 zera o total e a varredura sai 0, SEM acumular a
amostra daquela varredura — o comando de zerar vence a integração. `reset` conectado e
ainda sem valor (cold) não é comando. Deploy/stop zera o total via `reset()` do ciclo de
vida (bloco novo nasce zerado, §4.1-3).
"""

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from .base import Block, PortSample, null_outputs

INPUT_PORTS = ("in", "reset")
OUTPUT_PORTS = ("out",)

_FATORES: dict[str, float] = {"s": 1.0, "min": 60.0, "h": 3600.0}


class IntegratorBlock(Block):
    def __init__(
        self, block_id: str, *, time_base: Literal["s", "min", "h"], ts_seconds: float
    ) -> None:
        super().__init__(block_id)
        # `ts_seconds` chega como Decimal do SQLAlchemy: converte uma vez na fronteira
        # (mesmo cuidado do TfsBlock/FirstOrderBlock).
        self._incremento_por_unidade = float(ts_seconds) / _FATORES[time_base]
        self._total = 0.0

    @property
    def input_ports(self) -> tuple[str, ...]:
        return INPUT_PORTS

    @property
    def output_ports(self) -> tuple[str, ...]:
        return OUTPUT_PORTS

    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        sample = inputs["in"]
        # Cold start é julgado só pela entrada integrada: `reset` frio (None) significa
        # "sem comando", não varredura nula.
        if sample.v is None:
            return null_outputs(OUTPUT_PORTS)

        reset = inputs.get("reset")
        # Comando de zerar exige qualidade boa: perder o total por causa de uma amostra
        # corrompida na ponta do `reset` é pior que ignorar o comando.
        if reset is not None and reset.ok and reset.v:
            self._total = 0.0
            return {"out": PortSample(0.0, sample.ok)}

        valor = float(sample.v)
        # Amostra inf/nan não entra no acumulador: inf grudaria para sempre (inf+x=inf)
        # e nan contaminaria todo total futuro — um estado que nunca se cura sozinho.
        # Retém o último total e marca a saída inválida nesta varredura.
        if not math.isfinite(valor):
            return {"out": PortSample(self._total, False)}

        self._total += valor * self._incremento_por_unidade
        # Amostra inválida acumula e propaga a flag (decisão A-6).
        return {"out": PortSample(self._total, sample.ok)}

    def reset(self) -> None:
        self._total = 0.0
