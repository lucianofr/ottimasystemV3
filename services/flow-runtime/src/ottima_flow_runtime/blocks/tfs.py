"""Bloco TFS: matriz 2x2 de funções de transferência (RF-521/522, ADR-022, spec F3 §3.4).

Discretização ZOH no Ts do flow (RF-522). SOPDT = dois estágios de 1a ordem exatos em série
com o ganho K aplicado no final; IOPDT = integrador retangular. Tempo morto é uma fila de
atraso na **entrada** do elemento, com `d = round(theta/Ts)` amostras.

**Fase da recorrência — atualiza-e-emite:** na varredura n o elemento consome a entrada (já
atrasada pela fila) e emite a resposta *daquela* fronteira. Um degrau unitário aplicado a
partir da varredura 1 produz portanto `y[n] = K*(1 - a^n)`, que é exatamente
`K*(1 - e^(-n*Ts/tau))` — a comparação com a solução analítica é igualdade, não aproximação.
Laço algébrico continua impossível, mas não por ausência de ciclo: desde o ADR-040 o grafo
aceita ciclo com quebra explícita (aresta de realimentação), e a malha PID↔TFS é o caso de
uso. O que o impede é o atraso: a aresta que fecha o laço entrega o valor da varredura
anterior (ADR-024), ou a condição inicial dela enquanto a origem nunca produziu valor.

Aritmética escalar com `math`: são dois estados por elemento, e `numpy` só somaria overhead
por chamada num caminho que roda inline no laço de varredura, sensível a jitter (§2.2-4).
"""

from collections import deque
from collections.abc import Mapping, Sequence
from datetime import datetime

from ottima_core.flowgraph import IopdtParams, SopdtParams, TfsElement

from .base import Block, PortSample, has_cold_input, null_outputs

# O estágio de 1a ordem mora em `lag.py` desde o ADR-026, compartilhado com o bloco Filtro 1a
# ordem. `DIRECT_PASS_RATIO` continua reexportado daqui: `mpc/discretize.py` documenta e
# testa o limiar contra `blocks.tfs`.
from .lag import DIRECT_PASS_RATIO, FirstOrderLag

__all__ = ["DIRECT_PASS_RATIO", "INPUT_PORTS", "OUTPUT_PORTS", "TfsBlock"]

INPUT_PORTS = ("u1", "u2")
OUTPUT_PORTS = ("y1", "y2")


class _Sopdt:
    """Dois estágios de 1a ordem em série; ganho K aplicado no final da cascata."""

    __slots__ = ("_k", "_stages")

    def __init__(self, params: SopdtParams, ts: float) -> None:
        self._k = params.K
        self._stages = (FirstOrderLag(params.tau1, ts), FirstOrderLag(params.tau2, ts))

    def step(self, u: float) -> float:
        for stage in self._stages:
            u = stage.step(u)
        return self._k * u

    def prime(self, y: float) -> float:
        """Parte a cascata emitindo `y`; devolve a entrada equivalente em regime permanente.

        Em regime permanente os dois estágios valem a entrada, então `u_eq = y/K` em ambos.
        Com `K = 0` o elemento é mudo por construção: nenhum estado produz `y`, e a cascata
        parte de zero.
        """
        u_eq = y / self._k if self._k != 0.0 else 0.0
        for stage in self._stages:
            stage.prime(u_eq)
        return u_eq

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

    def prime(self, y: float) -> float:
        """O acumulador é a própria saída; integrador parado exige entrada nula, então a
        fila de atraso nasce em zero."""
        self._acc = y
        return 0.0

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

    def prime(self, y: float) -> None:
        """Condição inicial: o núcleo parte emitindo `y` e a fila de atraso nasce cheia da
        entrada equivalente — senão o atraso injetaria zeros e derrubaria a saída na
        partida."""
        self._queue = deque([self._kernel.prime(y)] * self._samples)

    def reset(self) -> None:
        self._queue = deque([0.0] * self._samples)
        self._kernel.reset()


class TfsBlock(Block):
    """Entradas `u1,u2`; saídas `y1,y2`. `matrix[J][K]` = contribuição de `uK` para `yJ`.

    `yJ` é a soma das contribuições **habilitadas** da linha J. Elemento desabilitado não tem
    estado e não consome entrada; linha inteira desabilitada dá `yJ = 0.0` com `ok=True` —
    ganho zero é um valor legítimo, não invalidez (ADR-022).

    `y0` é a condição inicial de `[y1, y2]` — a planta simulada quase nunca parte de zero.
    O estado nasce no regime que produz esse valor; NÃO é um offset somado à saída, então
    linha auto-regulada (SOPDT) mantém o valor final em `K*u` e só muda o transiente de
    partida. Linha com IOPDT não tem ganho estático: `y0` é o nível de onde o integrador
    passa a integrar, e permanece somado. Elemento sem memória — `K = 0`, ou `tau < Ts/10`
    com `theta = 0`, que `FirstOrderLag` degrada para passagem direta — é ganho puro e não
    tem onde guardar `y0`: a parcela dele parte direto de `K*u`. Linha inteira desabilitada
    continua em `0.0` (não há modelo nenhum para dar condição inicial).
    """

    def __init__(
        self,
        block_id: str,
        *,
        matrix: Sequence[Sequence[TfsElement]],
        ts_seconds: float,
        y0: Sequence[float],
    ) -> None:
        super().__init__(block_id)
        # `Flow.ts_seconds` é Numeric(4,1) e chega como Decimal do SQLAlchemy: `Decimal*float`
        # levanta TypeError, então a fronteira converte uma vez e o resto é float puro.
        ts = float(ts_seconds)
        self._rows = [
            [_Element(cell, ts) if cell.enabled else None for cell in row] for row in matrix
        ]
        self._y0 = [float(value) for value in y0]
        self._prime()

    def _prime(self) -> None:
        """Condição inicial da linha J: `y0[J]` dividido igualmente entre os elementos
        habilitados, de modo que a soma da linha comece exatamente em `y0[J]`.

        A divisão é arbitrária (nada na config diz qual elemento "segura" o valor de
        partida) mas irrelevante no regime permanente: cada elemento converge para a sua
        contribuição `K*u`, então só o transiente inicial depende do rateio. Elemento com
        `K = 0` não consegue segurar a sua parcela e a linha parte abaixo de `y0[J]` — é um
        elemento sem efeito nenhum, degenerado por definição.
        """
        for row, y0 in zip(self._rows, self._y0, strict=True):
            active = [element for element in row if element is not None]
            if not active:
                continue
            share = y0 / len(active)
            for element in active:
                element.prime(share)

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
        """Volta à condição inicial — `y0`, não zero: `reset()` é o desmonte do flow, e
        partir de novo é partir do mesmo ponto de operação da primeira varredura."""
        for row in self._rows:
            for element in row:
                if element is not None:
                    element.reset()
        self._prime()
