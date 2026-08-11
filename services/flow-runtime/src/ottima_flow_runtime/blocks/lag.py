"""Estágio de atraso de 1ª ordem exato no ZOH: `x <- a*x + (1-a)*u`.

Compartilhado por dois propósitos distintos: os estágios em série do bloco TFS (ADR-022,
spec F3 §3.4) e o bloco Filtro 1ª ordem (ADR-026). Um único código garante que a simulação e
o filtro tenham, por construção, a mesma resposta ao degrau — o mesmo motivo pelo qual
`mpc/discretize.py` repete o limiar de passagem direta em vez de inventar outro.

Aritmética escalar com `math`: é um estado por instância, e `numpy` só somaria overhead por
chamada num caminho que roda inline no laço de varredura, sensível a jitter (§2.2-4).
"""

import math

DIRECT_PASS_RATIO = 10.0
"""`tau < Ts/10` degrada o estágio para passagem direta (§3.4, robustez numérica)."""


class FirstOrderLag:
    """Abaixo de `Ts/DIRECT_PASS_RATIO` o estágio vira passagem direta: nessa faixa `a` já é
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

    def prime(self, u: float) -> None:
        """Parte o estágio já no valor `u`, sem transiente.

        O TFS nunca chama: lá o estado é variável-desvio e parte de zero por definição. Quem
        usa é o filtro de sinal, que trabalha na EU absoluta da planta e não pode inventar
        uma rampa de zero até o valor real na primeira varredura (ADR-026).
        """
        self._x = u

    def reset(self) -> None:
        self._x = 0.0
