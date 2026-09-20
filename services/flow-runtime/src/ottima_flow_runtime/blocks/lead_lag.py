"""Bloco Lead-Lag: compensação dinâmica `gain*(tau_lead*s + 1)/(tau_lag*s + 1)`.

Uma entrada (`in`), uma saída (`out`), discretizado no Ts do flow pelo MESMO estágio ZOH do
TFS e do Filtro 1ª ordem (`lag.py`) — nenhuma equação de diferenças nova aqui. A identidade

    K*(tau_l*s + 1)/(tau_g*s + 1) = K*[ r + (1 - r)/(tau_g*s + 1) ],   r = tau_l/tau_g

decompõe o bloco em passagem direta ponderada por `r` mais um lag unitário ponderado por
`1 - r`. O denominador é, por construção, bit a bit o dos outros dois blocos — o mesmo pacto
que o docstring de `lag.py` registra.

**Partida sem salto:** a primeira amostra válida depois de deploy/reset prima o lag e a saída
é `gain*u`. Mesmo motivo do ADR-026: o sinal está na EU absoluta da planta, e arrancar de zero
inventaria um transiente que não existe no processo. Ligada a `bias_in` (ADR-039 D10), essa
invenção seria um degrau na válvula.

**Não-finito nunca entra na recorrência.** Um `nan` no estado do lag deixaria a saída `nan`
para sempre, mesmo depois de o sinal se recuperar: a varredura retém a última saída boa com
`min(UNCERTAIN, q_in)` e sai BAD quando nunca houve uma (ADR-043 D7) — é o `_retido` do
`pid.py`. A decisão A-6 do `first_order` ("executa e propaga") continua valendo para amostra
INVÁLIDA de valor finito, cujo efeito o lag lava sozinho na varredura seguinte.

**Degradação sub-Ts:** `tau_lag < Ts/10` faz o `FirstOrderLag` virar passagem direta, e a
saída colapsa em `gain*u`. Com a razão limitada a 10 no parse, `tau_lead` também é sub-Ts
nessa faixa: nenhuma das duas dinâmicas é resolvível na amostragem, e `gain*u` é a resposta
honesta — não um ganho de alta frequência ilimitado.
"""

import math
from collections.abc import Mapping
from datetime import datetime

from ottima_core.signal import Quality

from .base import Block, Signal, has_cold_input, null_outputs
from .lag import FirstOrderLag

INPUT_PORTS = ("in",)
OUTPUT_PORTS = ("out",)


class LeadLagBlock(Block):
    def __init__(
        self,
        block_id: str,
        *,
        gain: float,
        tau_lead: float,
        tau_lag: float,
        ts_seconds: float,
    ) -> None:
        super().__init__(block_id)
        # `Flow.ts_seconds` é Numeric(4,1) e chega como Decimal do SQLAlchemy: converte uma
        # vez na fronteira e o resto é float puro (mesmo cuidado do TfsBlock).
        self._gain = float(gain)
        # `tau_lag > 0` é garantido pelo parse: a divisão não precisa de guarda aqui.
        self._r = float(tau_lead) / float(tau_lag)
        self._lag = FirstOrderLag(float(tau_lag), float(ts_seconds))
        self._started = False
        self._ultima_boa: float | None = None

    @property
    def input_ports(self) -> tuple[str, ...]:
        return INPUT_PORTS

    @property
    def output_ports(self) -> tuple[str, ...]:
        return OUTPUT_PORTS

    async def step(
        self, inputs: Mapping[str, Signal], *, ts: datetime | None = None
    ) -> dict[str, Signal]:
        if has_cold_input(inputs):
            return null_outputs(OUTPUT_PORTS)

        sample = inputs["in"]
        valor = float(sample.v)
        if not math.isfinite(valor):
            if self._ultima_boa is None:
                # Sem valor retido anterior é BAD, nunca UNCERTAIN (ADR-043 D7): ausência de
                # dado não é retenção.
                return null_outputs(OUTPUT_PORTS)
            # Teto `min(UNCERTAIN, ...)`: entrada BAD retida permanece BAD (monotonicidade).
            return {"out": Signal(self._ultima_boa, quality=min(Quality.UNCERTAIN, sample.quality))}

        if not self._started:
            self._lag.prime(valor)
            self._started = True
        saida = self._gain * (self._r * valor + (1.0 - self._r) * self._lag.step(valor))
        self._ultima_boa = saida
        # Amostra inválida de valor finito executa e propaga a flag (decisão A-6, como o
        # `first_order`): descartá-la congelaria o compensador sem o consumidor saber.
        return {"out": Signal(saida, quality=sample.quality)}

    def reset(self) -> None:
        self._lag.reset()
        self._started = False
        self._ultima_boa = None
