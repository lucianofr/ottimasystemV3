"""Protocolos do kernel de controle (ADR-039 secao 4.5) e o stub dos testes S.

Dois protocolos: `ControlKernel` (SISO — `pid_loop`) e `MultiControlKernel` (multicanal —
`fuzzy_loop` v2 MIMO, um motor de inferencia compartilhado por N canais). O shell despacha
por `isinstance(kernel, MultiControlKernel)`; um kernel multicanal avalia TODOS os canais
num unico `process()` do motor, porque as regras cruzam canais.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class ControlKernel(Protocol):
    def compute(self, sp: float, pv: float, dt: float) -> float:
        """Retorna du/dt em % do span de OUT por segundo.

        Pode retornar NaN para sinalizar que o algoritmo nao produziu resultado valido
        neste scan. O shell trata NaN mantendo a saida e alarmando; nunca propaga NaN.
        """
        ...

    def align(self, u: float, sp: float, pv: float) -> None:
        """Realinha o historico interno para o estado corrente.

        Chamado pelo shell a cada scan em que compute() nao executa. Apos align(), a
        proxima chamada a compute() nao pode produzir transiente de historico obsoleto.
        """
        ...

    def reset(self) -> None:
        """Descarta todo historico interno."""
        ...

    def validate(self) -> list[str]:
        """Lista de erros de configuracao. Vazia = kernel apto a operar."""
        ...


@runtime_checkable
class MultiControlKernel(Protocol):
    """Kernel multicanal: um bloco com N malhas (fuzzy_loop v2, SPEC_FUZZY §3.2 v2).

    Mesmo contrato do `ControlKernel`, vetorizado por canal: `compute_all` devolve uma
    lista de `du/dt` (%span/s) na ordem dos canais; NaN numa posicao = sem resultado
    valido naquele canal. `align_all` realinha o historico de todos os canais de uma vez
    (o estado do motor e compartilhado).
    """

    def compute_all(self, sps: Sequence[float], pvs: Sequence[float], dt: float) -> list[float]: ...

    def align_all(
        self, us: Sequence[float], sps: Sequence[float], pvs: Sequence[float]
    ) -> None: ...

    def reset(self) -> None: ...

    def validate(self) -> list[str]: ...


class StubKernel:
    """Kernel deterministico dos testes de aceitacao do shell (ADR-039 secao 7).

    `compute` devolve `gain * (sp - pv) + rate` — um P puro em forma incremental, o
    suficiente para fechar malha nos cenarios S sem depender de PID/Fuzzy reais.
    """

    def __init__(self, *, gain: float = 0.0, rate: float = 0.0) -> None:
        self.gain = gain
        self.rate = rate
        self.align_calls: list[tuple[float, float, float]] = []
        self.errors: list[str] = []

    def compute(self, sp: float, pv: float, dt: float) -> float:  # noqa: ARG002
        return self.gain * (sp - pv) + self.rate

    def align(self, u: float, sp: float, pv: float) -> None:
        self.align_calls.append((u, sp, pv))

    def reset(self) -> None:
        self.align_calls.clear()

    def validate(self) -> list[str]:
        return list(self.errors)
