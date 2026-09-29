"""Bloco Constant: fonte fixa sem entrada, `out` sempre no valor configurado.

Sem estado e sem porta de entrada — não há aresta possível para tornar a varredura cold
nem valor externo capaz de contaminar a saída. `value` já chega validado finito pelo parse
(`ConstantConfig.value: float = Field(allow_inf_nan=False)`), então não existe caminho para
`nan`/`inf`: toda varredura emite `ok=True`.
"""

from collections.abc import Mapping
from datetime import datetime

from ottima_core.signal import Quality

from .base import Block, Signal

OUTPUT_PORTS = ("out",)


class ConstantBlock(Block):
    def __init__(self, block_id: str, *, value: float) -> None:
        super().__init__(block_id)
        self._value = float(value)

    @property
    def output_ports(self) -> tuple[str, ...]:
        return OUTPUT_PORTS

    async def step(
        self, inputs: Mapping[str, Signal], *, ts: datetime | None = None
    ) -> dict[str, Signal]:
        return {"out": Signal(self._value, quality=Quality.GOOD)}
