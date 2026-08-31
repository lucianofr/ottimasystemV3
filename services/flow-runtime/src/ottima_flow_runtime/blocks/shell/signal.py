"""Signal: valor + status na mesma porta (ADR-039 secao 4.1).

`Signal` ESTENDE o PortSample existente: todo consumidor legado le `v`/`ok` sem saber de
quality; blocos malha leem o status completo. Promocao implicita nas arestas via
`as_signal` — sem blocos conversores. UNCERTAIN e tratado como GOOD na v1 (STATUS_OPTS:
ADR-039 secao 9).
"""

from dataclasses import dataclass
from enum import IntEnum

from ottima_flow_runtime.blocks.base import PortSample


class Quality(IntEnum):
    BAD = 0
    UNCERTAIN = 1
    GOOD = 2


class Substatus(IntEnum):
    NON_SPECIFIC = 0
    INIT_REQUEST = 1  # IR: o bloco a jusante nao esta aceitando cascata
    NOT_INVITED = 2  # reservado ao CONTROL_SELECTOR (ADR-039 secao 9)
    LOCAL_OVERRIDE = 3
    SENSOR_FAILURE = 4
    CONFIG_ERROR = 5
    DEVICE_FAILURE = 6


@dataclass(frozen=True, slots=True)
class Signal(PortSample):
    quality: Quality = Quality.BAD
    substatus: Substatus = Substatus.NON_SPECIFIC
    hi_limited: bool = False
    lo_limited: bool = False

    @property
    def is_good(self) -> bool:
        return self.quality is not Quality.BAD

    @property
    def init_request(self) -> bool:
        return self.substatus is Substatus.INIT_REQUEST


def make_signal(
    value: float | None,
    quality: Quality,
    *,
    substatus: Substatus = Substatus.NON_SPECIFIC,
    hi_limited: bool = False,
    lo_limited: bool = False,
) -> Signal:
    """Constroi um Signal mantendo o invariante `ok == (quality != BAD)`."""
    return Signal(
        v=value,
        ok=quality is not Quality.BAD,
        quality=quality,
        substatus=substatus,
        hi_limited=hi_limited,
        lo_limited=lo_limited,
    )


def as_signal(sample: PortSample) -> Signal:
    """Promocao implicita da aresta: (v, ok) -> Signal; Signal passa intacto."""
    if isinstance(sample, Signal):
        return sample
    return Signal(v=sample.v, ok=sample.ok, quality=Quality.GOOD if sample.ok else Quality.BAD)
