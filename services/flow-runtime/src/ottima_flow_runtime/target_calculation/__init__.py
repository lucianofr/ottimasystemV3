"""SSTO — camada de alvos de regime permanente por LP acima do MPC (ADR-026).

Fisicamente separado de `ottima_flow_runtime.mpc`: aqui mora a otimização ECONÔMICA de
regime permanente (para onde a planta deve ir); lá mora o controle DINÂMICO (como chegar
lá). O acoplamento entre os dois é de uma via só — o SSTO devolve alvos, o worker do MPC os
usa como SP. Nada neste pacote importa `mpc.builder`/`mpc.worker`, e o cálculo do move plan
não é tocado.
"""

from ottima_flow_runtime.target_calculation.model import (
    SteadyStateModel,
    build_steady_state_model,
    pair_steady_state_gain,
)

__all__ = [
    "SteadyStateModel",
    "build_steady_state_model",
    "pair_steady_state_gain",
]
