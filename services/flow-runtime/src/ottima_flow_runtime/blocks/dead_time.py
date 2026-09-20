"""Bloco Tempo morto: atrasa `in` em `theta` segundos.

Fila de `d = round(theta/Ts)` amostras, arredondamento banker's (half-even) — a MESMA
convenção do TFS (`blocks/tfs.py::_Element`) e do modelo interno do MPC, para que o mesmo
theta vire o mesmo número de amostras nos três códigos. `d = 0` é passagem direta pelo par
append/popleft, sem desvio no caminho quente.

**Relógio nominal, não medido.** A fila anda um slot por `step()`; em overrun o scheduler
pula fronteiras (`_settle_grid`) e `step()` NÃO é chamado nelas, de modo que o atraso efetivo
DILATA em tempo de parede. É assumido: todo bloco de dinâmica da casa embute Ts constante e o
scheduler é a única autoridade de tempo do laço (`pid.py`). O desvio é transitório e nada
acumula — diferente do `integrator.py`, cujo erro seria permanente na conciliação de massa, e
é por isso que só ele mede `dt` de parede. Fique registrada a direção que machuca: tempo morto
dilatado entrega o feedforward ATRASADO, e feedforward atrasado age como um segundo distúrbio
em vez de cancelar o primeiro.

**A fila transporta `Signal`, não `float`:** a saída é a amostra de `d` varreduras atrás e
carrega a qualidade DAQUELA amostra, não a da entrada corrente. É a diferença estrutural para
a fila do TFS, onde a qualidade da linha é resolvida por `min()` fora dela.

**Nunca zero-fill.** A fila nasce cheia da primeira amostra válida. O `deque([0.0] * d)` do
`_Element` é correto lá porque o TFS simula variável-desvio; num bloco autônomo sobre EU
absoluta seria um degrau por `d` varreduras — o próprio `_Element.prime()` já escreve a regra
("senão o atraso injetaria zeros e derrubaria a saída na partida").
"""

import math
from collections import deque
from collections.abc import Mapping
from datetime import datetime

from .base import Block, Signal, has_cold_input, null_outputs

INPUT_PORTS = ("in",)
OUTPUT_PORTS = ("out",)


class DeadTimeBlock(Block):
    def __init__(self, block_id: str, *, theta: float, ts_seconds: float) -> None:
        super().__init__(block_id)
        # `ts_seconds` chega como Decimal do SQLAlchemy: converte uma vez na fronteira
        # (mesmo cuidado do TfsBlock/FirstOrderBlock).
        self._samples = round(float(theta) / float(ts_seconds))
        self._queue: deque[Signal] = deque()

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
        if self._samples and not self._queue:
            self._queue.extend([sample] * self._samples)
        self._queue.append(sample)
        atrasada = self._queue.popleft()

        valor = float(atrasada.v)
        if not math.isfinite(valor):
            return null_outputs(OUTPUT_PORTS)
        return {"out": Signal(valor, quality=atrasada.quality)}

    def reset(self) -> None:
        self._queue.clear()
