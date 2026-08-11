"""Bloco Filtro Kalman: estima o valor verdadeiro de um sinal ruidoso (RF-531/533, ADR-026).

Uma entrada (`in`), uma saída (`out`). Modelo de passeio aleatório escalar — o valor
verdadeiro anda sozinho entre varreduras e a medição o vê com ruído:

    x[k] = x[k-1] + w,  w ~ N(0, q)
    z[k] = x[k]   + v,  v ~ N(0, r)

**A interface não fala em variância.** A config traz dois desvios padrão na EU do próprio
sinal (`measurement_noise`, `process_noise`), que o engenheiro lê direto de uma tendência; o
quadrado acontece aqui dentro, uma vez, na construção.

**Partida:** `x` nasce na primeira amostra válida com `P = r` — a covariância que ele de fato
tem depois de uma única medição. Partir de `x = 0` com `P` grande daria o mesmo regime
permanente por um caminho pior: um transiente inventado nas primeiras varreduras.

Aritmética escalar com `math`: são dois estados, e o bloco roda inline no laço de varredura.
"""

from collections.abc import Mapping
from datetime import datetime

from .base import Block, PortSample, has_cold_input, null_outputs

INPUT_PORTS = ("in",)
OUTPUT_PORTS = ("out",)


class KalmanBlock(Block):
    """Predição + correção escalares por varredura.

    `process_noise` é por varredura (não por segundo): trocar o Ts do flow muda o significado
    do parâmetro, e é assim que o PRD (RF-533) o define — a alternativa, `q` por segundo
    escalado pelo Ts, esconderia do usuário a única grandeza que ele consegue estimar
    olhando a tendência ("quanto isso anda de uma amostra para a outra").
    """

    def __init__(self, block_id: str, *, measurement_noise: float, process_noise: float) -> None:
        super().__init__(block_id)
        self._r = float(measurement_noise) ** 2
        self._q = float(process_noise) ** 2
        self._x: float | None = None
        self._p = 0.0

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
        measurement = float(sample.v)
        if self._x is None:
            self._x, self._p = measurement, self._r
        else:
            predicted = self._p + self._q
            # `r > 0` (validado no save, ADR-026), então o divisor nunca zera nem com q=0.
            gain = predicted / (predicted + self._r)
            self._x += gain * (measurement - self._x)
            self._p = (1.0 - gain) * predicted
        # Amostra inválida executa e propaga a flag (decisão A-6).
        return {"out": PortSample(self._x, sample.ok)}

    def reset(self) -> None:
        self._x = None
        self._p = 0.0
