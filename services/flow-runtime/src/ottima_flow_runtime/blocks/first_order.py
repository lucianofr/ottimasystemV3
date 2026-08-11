"""Bloco Filtro 1a ordem: suaviza um sinal por atraso de 1a ordem (RF-531/532, ADR-026).

Uma entrada (`in`), uma saída (`out`), parâmetro único `tau` em segundos, discretizado no Ts
do flow pelo mesmo estágio ZOH do TFS (`lag.py`).

**Partida sem salto:** a primeira amostra válida depois do deploy/reset sai sem filtrar e o
estado nasce nela. O TFS parte de zero porque simula variável-desvio; aqui o sinal está na EU
absoluta da planta, e arrancar de zero produziria um transiente que não existe no processo —
o filtro reportaria uma temperatura subindo de 0 a 150 °C que ninguém viu acontecer.
"""

from collections.abc import Mapping
from datetime import datetime

from .base import Block, PortSample, has_cold_input, null_outputs
from .lag import FirstOrderLag

INPUT_PORTS = ("in",)
OUTPUT_PORTS = ("out",)


class FirstOrderBlock(Block):
    """`y[n] = a*y[n-1] + (1-a)*u[n]`, `a = exp(-Ts/tau)`.

    `tau` abaixo de `Ts/10` (inclusive `tau = 0`) degrada para passagem direta — mesma
    convenção do TFS, herdada de `FirstOrderLag`.
    """

    def __init__(self, block_id: str, *, tau: float, ts_seconds: float) -> None:
        super().__init__(block_id)
        # `Flow.ts_seconds` é Numeric(4,1) e chega como Decimal do SQLAlchemy: converte uma
        # vez na fronteira e o resto é float puro (mesmo cuidado do TfsBlock).
        self._lag = FirstOrderLag(float(tau), float(ts_seconds))
        self._started = False

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
        value = float(sample.v)
        if not self._started:
            self._lag.prime(value)
            self._started = True
        # Amostra inválida executa e propaga a flag (decisão A-6): descartá-la congelaria o
        # filtro num valor velho sem que o consumidor a jusante soubesse.
        return {"out": PortSample(self._lag.step(value), sample.ok)}

    def reset(self) -> None:
        self._lag.reset()
        self._started = False
