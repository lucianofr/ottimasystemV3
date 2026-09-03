"""Bloco Scaler: reescala linear de `in`∈[`in_min`,`in_max`] para [`out_min`,`out_max`].

Sem estado: `out = out_min + (in - in_min) * ganho`, ganho pré-computado no construtor
(`in_max > in_min` garantido pelo parse). A faixa de saída pode ser invertida (ação
reversa, ex.: 4-20 mA → 100-0 %).

Duas regras de borda, mesma convenção dos filtros/PID:

- **Fora da faixa de entrada ⇒ clamp** em [`out_min`,`out_max`] (na ordem que for): um
  spike de sensor nunca vira escrita OPC além da escala de saída.
- **Amostra não-finita (inf/nan) ⇒ saída nula e inválida**, nunca `nan`/`inf` com
  `ok=True` contaminando o consumidor a jusante (convenção `fuzzy.py`/`pid.py::_retido`).
"""

import math
from collections.abc import Mapping
from datetime import datetime

from .base import Block, PortSample, has_cold_input, null_outputs

INPUT_PORTS = ("in",)
OUTPUT_PORTS = ("out",)


class ScalerBlock(Block):
    def __init__(
        self,
        block_id: str,
        *,
        in_min: float,
        in_max: float,
        out_min: float,
        out_max: float,
    ) -> None:
        super().__init__(block_id)
        self._ganho = (float(out_max) - float(out_min)) / (float(in_max) - float(in_min))
        self._in_min = float(in_min)
        self._out_min = float(out_min)
        self._out_max = float(out_max)

    @property
    def input_ports(self) -> tuple[str, ...]:
        return INPUT_PORTS

    @property
    def output_ports(self) -> tuple[str, ...]:
        return OUTPUT_PORTS

    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        if has_cold_input(inputs):
            return null_outputs(OUTPUT_PORTS)

        sample = inputs["in"]
        valor = float(sample.v)
        if not math.isfinite(valor):
            return null_outputs(OUTPUT_PORTS)

        escalado = self._out_min + (valor - self._in_min) * self._ganho
        lo, hi = min(self._out_min, self._out_max), max(self._out_min, self._out_max)
        escalado = min(max(escalado, lo), hi)  # clamp na faixa de saída, em qualquer sentido
        # Amostra inválida executa e propaga a flag (decisão A-6), como nos filtros.
        return {"out": PortSample(escalado, sample.ok)}
