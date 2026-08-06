"""Bloco TFS: matriz 2x2 de funções de transferência (RF-521/522, ADR-022, spec F3 §3.4).

Discretização ZOH no Ts do flow (RF-522). SOPDT = dois estágios de 1a ordem exatos em série
com o ganho K aplicado no final; IOPDT = integrador retangular. Tempo morto é uma fila de
atraso na **entrada** do elemento, com `d = round(theta/Ts)` amostras.

**Fase da recorrência — atualiza-e-emite:** na varredura n o elemento consome a entrada (já
atrasada pela fila) e emite a resposta *daquela* fronteira. Um degrau unitário aplicado a
partir da varredura 1 produz portanto `y[n] = K*(1 - a^n)`, que é exatamente
`K*(1 - e^(-n*Ts/tau))` — a comparação com a solução analítica é igualdade, não aproximação.
Não há laço algébrico possível: ciclo é rejeitado na validação do grafo.

Aritmética escalar com `math`: são dois estados por elemento, e `numpy` só somaria overhead
por chamada num caminho que roda inline no laço de varredura, sensível a jitter (§2.2-4).
"""

import math
from collections import deque
from collections.abc import Mapping, Sequence
from datetime import datetime

from ottima_core.flowgraph import IopdtParams, SopdtParams, TfsElement

from .base import Block, PortSample, has_cold_input, null_outputs

INPUT_PORTS = ("u1", "u2")
OUTPUT_PORTS = ("y1", "y2")

DIRECT_PASS_RATIO = 10.0
"""`tau < Ts/10` degrada o estágio para passagem direta (§3.4, robustez numérica)."""


class _FirstOrder:
    """Estágio de 1a ordem exato no ZOH: `x <- a*x + (1-a)*u`.

    Abaixo de `Ts/DIRECT_PASS_RATIO` o estágio vira passagem direta: nessa faixa `a` já é
    indistinguível de zero na amostragem do flow, e `tau == 0` (constante legítima na config)
    dividiria por zero.
    """

    __slots__ = ("_a", "_x")

    def __init__(self, tau: float, ts: float) -> None:
        self._a = math.exp(-ts / tau) if tau >= ts / DIRECT_PASS_RATIO else None
        self._x = 0.0

    def step(self, u: float) -> float:
        if self._a is None:
            return u
        self._x = self._a * self._x + (1.0 - self._a) * u
        return self._x

    def reset(self) -> None:
        self._x = 0.0


class _Sopdt:
    """Dois estágios de 1a ordem em série; ganho K aplicado no final da cascata."""

    __slots__ = ("_k", "_stages")

    def __init__(self, params: SopdtParams, ts: float) -> None:
        self._k = params.K
        self._stages = (_FirstOrder(params.tau1, ts), _FirstOrder(params.tau2, ts))

    def step(self, u: float) -> float:
        for stage in self._stages:
            u = stage.step(u)
        return self._k * u

    def reset(self) -> None:
        for stage in self._stages:
            stage.reset()


class _Iopdt:
    """Integrador retangular: `acc += Ki*Ts*u`; a saída é o próprio acumulador."""

    __slots__ = ("_acc", "_gain")

    def __init__(self, params: IopdtParams, ts: float) -> None:
        self._gain = params.Ki * ts
        self._acc = 0.0

    def step(self, u: float) -> float:
        self._acc += self._gain * u
        return self._acc

    def reset(self) -> None:
        self._acc = 0.0


class _Element:
    """Fila de atraso na entrada + núcleo dinâmico de um elemento habilitado da matriz.

    Com `d = 0` a fila nasce vazia e o par append/popleft devolve a própria amostra, o que
    dispensa um desvio no caminho quente.
    """

    __slots__ = ("_kernel", "_queue", "_samples")

    def __init__(self, config: TfsElement, ts: float) -> None:
        params = config.params
        self._kernel: _Sopdt | _Iopdt = (
            _Sopdt(params, ts) if isinstance(params, SopdtParams) else _Iopdt(params, ts)
        )
        # Arredondamento banker's (half-even) do round() do Python: a mesma convenção da
        # validação do TFS (ottima_core.flowgraph.validate) e do futuro modelo interno do
        # MPC (F4b) — o mesmo theta precisa virar o mesmo número de amostras nos dois
        # códigos de propósito (spec F4 §3.1; fecha débito m2 da spec F4 §8).
        self._samples = round(params.theta / ts)
        self._queue: deque[float] = deque([0.0] * self._samples)

    def step(self, u: float) -> float:
        self._queue.append(u)
        return self._kernel.step(self._queue.popleft())

    def reset(self) -> None:
        self._queue = deque([0.0] * self._samples)
        self._kernel.reset()


class TfsBlock(Block):
    """Entradas `u1,u2`; saídas `y1,y2`. `matrix[J][K]` = contribuição de `uK` para `yJ`.

    `yJ` é a soma das contribuições **habilitadas** da linha J. Elemento desabilitado não tem
    estado e não consome entrada; linha inteira desabilitada dá `yJ = 0.0` com `ok=True` —
    ganho zero é um valor legítimo, não invalidez (ADR-022).
    """

    def __init__(
        self, block_id: str, *, matrix: Sequence[Sequence[TfsElement]], ts_seconds: float
    ) -> None:
        super().__init__(block_id)
        # `Flow.ts_seconds` é Numeric(4,1) e chega como Decimal do SQLAlchemy: `Decimal*float`
        # levanta TypeError, então a fronteira converte uma vez e o resto é float puro.
        ts = float(ts_seconds)
        self._rows = [
            [_Element(cell, ts) if cell.enabled else None for cell in row] for row in matrix
        ]

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

        outputs: dict[str, PortSample] = {}
        for index, row in enumerate(self._rows):
            total = 0.0
            ok = True
            for column, element in enumerate(row):
                if element is None:
                    continue
                # Coluna ausente de `inputs` é coluna sem aresta: só é legal quando nenhum
                # elemento dela está habilitado, e nesse caso não contribui nem bloqueia.
                sample = inputs.get(INPUT_PORTS[column])
                if sample is None:
                    continue
                total += element.step(float(sample.v))
                ok = ok and sample.ok
            outputs[OUTPUT_PORTS[index]] = PortSample(total, ok)
        return outputs

    def reset(self) -> None:
        for row in self._rows:
            for element in row:
                if element is not None:
                    element.reset()
