"""Bloco Integrator (totalizador): acumula `in` no tempo do flow.

`out += in * dt / fator` por varredura, com fator 1/60/3600 conforme `time_base`
("s"/"min"/"h") — a EU de tempo em que a entrada está expressa (ex.: vazão em kg/min).

O `dt` é medido entre os `ts` que o scheduler entrega a cada varredura (`fired_ts`), não o
Ts nominal: em overrun o scheduler PULA fronteiras de grade sem compensação, e integrar o
Ts nominal subcontaria em silêncio — erro acumulado num totalizador é o defeito que o
operador enxerga na conciliação de massa. Como `fired_ts` é hora de parede, um salto de
NTP ou um dt absurdo (`dt <= 0` ou `dt > 10×Ts`) congela o total e marca a varredura
inválida em vez de somar um delta corrupto. A primeira varredura com valor só inicia o
relógio: sem dt conhecido, não há o que acumular.

Qualidade: amostra `ok=False` ou não-finita NÃO acumula — congela o total e emite
`ok=False`. A decisão A-6 ("executa e propaga") vale para filtro, cujo estado se lava
sozinho; no totalizador o erro seria permanente (mesmo argumento do `_integral` em
`pid.py`).

Porta `reset` (opcional): valor ≠ 0 com qualidade boa zera o total e a varredura sai 0,
SEM acumular a amostra daquela varredura — o comando de zerar vence a integração. Reset
sem qualidade (`ok=False`) não zera: perder o total por amostra corrompida é pior que
ignorar o comando. `reset` frio (None) não é comando. Deploy/stop zera o total via
`reset()` do ciclo de vida (bloco novo nasce zerado, §4.1-3).
"""

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from ottima_core.signal import Quality

from .base import Block, Signal, null_outputs

INPUT_PORTS = ("in", "reset")
OUTPUT_PORTS = ("out",)

_FATORES: dict[str, float] = {"s": 1.0, "min": 60.0, "h": 3600.0}

_MAX_DT_FATOR = 10.0
"""Teto do dt aceito, em múltiplos do Ts do flow: acima disso é salto de relógio (NTP) ou
parada longa — somar seria integrar um delta corrupto; congela e marca inválido."""


class IntegratorBlock(Block):
    def __init__(
        self, block_id: str, *, time_base: Literal["s", "min", "h"], ts_seconds: float
    ) -> None:
        super().__init__(block_id)
        # `ts_seconds` chega como Decimal do SQLAlchemy: converte uma vez na fronteira
        # (mesmo cuidado do TfsBlock/FirstOrderBlock).
        self._ts = float(ts_seconds)
        self._fator = _FATORES[time_base]
        self._total = 0.0
        self._ultimo_ts: datetime | None = None

    @property
    def input_ports(self) -> tuple[str, ...]:
        return INPUT_PORTS

    @property
    def output_ports(self) -> tuple[str, ...]:
        return OUTPUT_PORTS

    async def step(
        self, inputs: Mapping[str, Signal], *, ts: datetime | None = None
    ) -> dict[str, Signal]:
        sample = inputs["in"]
        # Cold start é julgado só pela entrada integrada: `reset` frio (None) significa
        # "sem comando", não varredura nula.
        if sample.v is None:
            return null_outputs(OUTPUT_PORTS)

        reset = inputs.get("reset")
        if reset is not None and reset.ok and reset.v:
            self._total = 0.0
            self._ultimo_ts = ts
            return {"out": Signal(0.0, quality=sample.quality)}

        valor = float(sample.v)
        if not sample.ok or not math.isfinite(valor):
            # A brecha fica de fora do total E fora do relógio: reancora o ts para a
            # amostra boa seguinte não "cobrir" o intervalo ruim com o valor novo.
            # Teto `min(UNCERTAIN, sample.quality)` (ADR-043 D7): amostra GOOD com valor
            # não-finito retida vira UNCERTAIN; amostra BAD retida permanece BAD.
            if ts is not None:
                self._ultimo_ts = ts
            return {"out": Signal(self._total, quality=min(Quality.UNCERTAIN, sample.quality))}

        if ts is None:
            # Fora do scheduler (teste unitário de pureza): cai no Ts nominal.
            dt = self._ts
        elif self._ultimo_ts is None:
            self._ultimo_ts = ts
            return {"out": Signal(self._total, quality=sample.quality)}
        else:
            dt = (ts - self._ultimo_ts).total_seconds()
            self._ultimo_ts = ts
            if dt <= 0 or dt > _MAX_DT_FATOR * self._ts:
                # Teto `min(UNCERTAIN, sample.quality)` (ADR-043 D7): salto de relógio
                # congela o total; amostra GOOD retida vira UNCERTAIN, BAD permanece BAD.
                return {"out": Signal(self._total, quality=min(Quality.UNCERTAIN, sample.quality))}

        self._total += valor * dt / self._fator
        return {"out": Signal(self._total, quality=Quality.GOOD)}

    def reset(self) -> None:
        self._total = 0.0
        self._ultimo_ts = None
