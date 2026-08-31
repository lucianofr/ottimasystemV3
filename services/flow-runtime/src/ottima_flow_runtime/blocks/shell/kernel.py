"""Protocolo do kernel de controle (ADR-039 secao 4.5) e o stub dos testes S."""

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
