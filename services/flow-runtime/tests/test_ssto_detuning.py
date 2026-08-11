"""Caso obrigatório 5 do brief — LP flipping e detuning (ADR-027 §8).

Montagem degenerada: duas MVs com o MESMO ganho na CV e preços quase iguais. O vetor de
custos fica paralelo à aresta `G·ΔMV = limite`, e todo ponto dela é ótimo. Com LP puro, uma
diferença de 1e-6 no preço decide entre dois vértices a 100 unidades de distância — é o
flipping. Com detuning, o desempate passa a ser a proximidade da solução anterior, e a
mesma perturbação move o alvo muito pouco.
"""

import numpy as np
import pytest

from ottima_core.flowgraph import MpcConfig
from ottima_flow_runtime.target_calculation.solver import QuadraticTerm, get_backend
from ottima_flow_runtime.target_calculation.solver_qp import OSQPBackend
from ottima_flow_runtime.target_calculation.ssto import SstoInput, SteadyStateOptimizer

TS = 1.0


def _config(*, delta_preco: float, detuning: float) -> MpcConfig:
    """1 CV × 2 MVs de ganho idêntico: a CV limita `Δa + Δb ≤ 100`."""
    return MpcConfig.model_validate(
        {
            "name": "degenerado",
            "multiplier": 1,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_a",
                        "name": "a",
                        "eu": "%",
                        "limits": {"min": 0.0, "max": 100.0},
                        "du_max": 10.0,
                    },
                    {
                        "id": "mv_b",
                        "name": "b",
                        "eu": "%",
                        "limits": {"min": 0.0, "max": 100.0},
                        "du_max": 10.0,
                    },
                ],
                "cvs": [
                    {
                        "id": "cv_a",
                        "name": "cv",
                        "eu": "y",
                        "kind": "selfreg",
                        "tss": 100.0,
                        "weight": 1.0,
                        "sp_limits": {"min": 0.0, "max": 100.0},
                    }
                ],
                "constraints": [],
                "dvs": [],
            },
            "models": {
                "cv_a": {
                    "mv_a": {
                        "enabled": True,
                        "params": {"K": 1.0, "tau1": 10.0, "tau2": 0.0, "theta": 0.0},
                    },
                    "mv_b": {
                        "enabled": True,
                        "params": {"K": 1.0, "tau1": 10.0, "tau2": 0.0, "theta": 0.0},
                    },
                }
            },
            "economics": {
                "enabled": True,
                "costs": {"mv_a": -1.0, "mv_b": -1.0 - delta_preco},
                "detuning_weight": detuning,
                "solver": "osqp" if detuning > 0 else "highs",
            },
        }
    )


ANTERIOR = {"mv_a": 50.0, "mv_b": 50.0}
"""Solução do ciclo anterior: o meio da aresta ótima — equidistante dos dois vértices."""


def _entrada() -> SstoInput:
    return SstoInput(
        u={"mv_a": 0.0, "mv_b": 0.0},
        d={},
        d_prev=None,
        bias={"cv_a": 0.0},
        delta_mv_prev=ANTERIOR,
    )


def _solucao(*, delta_preco: float, detuning: float) -> np.ndarray:
    ssto = SteadyStateOptimizer(_config(delta_preco=delta_preco, detuning=detuning), TS)
    result = ssto.solve(_entrada())
    return np.array([result.delta_mv["mv_a"], result.delta_mv["mv_b"]])


def test_lp_puro_salta_de_vertice_com_perturbacao_minima():
    """Sem detuning: 2e-6 de diferença de preço troca o vértice inteiro."""
    barato_b = _solucao(delta_preco=+1e-6, detuning=0.0)
    barato_a = _solucao(delta_preco=-1e-6, detuning=0.0)

    salto = float(np.linalg.norm(barato_b - barato_a))
    assert salto > 100.0
    # Cada solução é um vértice puro: tudo numa MV, nada na outra.
    assert barato_b == pytest.approx(np.array([0.0, 100.0]), abs=1e-6)
    assert barato_a == pytest.approx(np.array([100.0, 0.0]), abs=1e-6)


def test_com_detuning_a_mesma_perturbacao_quase_nao_move_o_alvo():
    barato_b = _solucao(delta_preco=+1e-6, detuning=0.05)
    barato_a = _solucao(delta_preco=-1e-6, detuning=0.05)

    salto = float(np.linalg.norm(barato_b - barato_a))
    assert salto < 1.0


def test_detuning_puxa_a_solucao_para_perto_da_anterior():
    """O empate passa a ser resolvido pela proximidade do que já estava em vigor."""
    solucao = _solucao(delta_preco=0.0, detuning=0.05)

    assert solucao == pytest.approx(np.array([50.0, 50.0]), abs=1e-3)
    # Continua na fronteira ótima: o detuning desempata, não abre mão do ótimo econômico.
    assert solucao.sum() == pytest.approx(100.0, abs=1e-3)


def test_detuning_nao_relaxa_limite_de_mv():
    """Nem com peso alto o QP viola o limite duro (ADR-027 §5)."""
    result = SteadyStateOptimizer(_config(delta_preco=0.0, detuning=10.0), TS).solve(
        SstoInput(
            u={"mv_a": 0.0, "mv_b": 0.0},
            d={},
            d_prev=None,
            bias={"cv_a": 0.0},
            delta_mv_prev={"mv_a": 500.0, "mv_b": 500.0},
        )
    )

    assert result.mv_target["mv_a"] <= 100.0 + 1e-6
    assert result.mv_target["mv_b"] <= 100.0 + 1e-6


def test_primeira_execucao_sem_solucao_anterior_usa_o_zero_como_referencia():
    result = SteadyStateOptimizer(_config(delta_preco=0.0, detuning=10.0), TS).solve(
        SstoInput(
            u={"mv_a": 0.0, "mv_b": 0.0}, d={}, d_prev=None, bias={"cv_a": 0.0}, delta_mv_prev=None
        )
    )

    # Referência no zero e peso alto: o LP quer mover, o detuning segura perto de não mexer.
    assert abs(result.delta_mv["mv_a"]) < 10.0
    assert abs(result.delta_mv["mv_b"]) < 10.0


# ---------------------------------------------------------------------------------------
# Backend QP
# ---------------------------------------------------------------------------------------


def test_osqp_resolve_qp_simples():
    """`min ‖x − 3‖²` com `x ≤ 1.5` ⇒ x = 1.5."""
    result = OSQPBackend().solve(
        np.zeros(1),
        np.array([[1.0]]),
        np.array([1.5]),
        ((-10.0, 10.0),),
        QuadraticTerm(weight=1.0, reference=np.array([3.0])),
    )

    assert result.status == "optimal"
    assert result.x == pytest.approx(np.array([1.5]), abs=1e-6)
    assert result.active_constraints == (0,)


def test_osqp_sem_termo_quadratico_resolve_o_lp():
    result = OSQPBackend().solve(np.array([1.0]), np.zeros((0, 1)), np.zeros(0), ((-5.0, 10.0),))

    assert result.status == "optimal"
    assert result.x == pytest.approx(np.array([-5.0]), abs=1e-6)


def test_osqp_detecta_inviabilidade():
    result = OSQPBackend().solve(
        np.array([1.0]), np.array([[1.0]]), np.array([-1.0]), ((0.0, 10.0),)
    )

    assert result.status == "infeasible"


def test_registro_resolve_osqp_por_nome():
    assert get_backend("osqp").name == "osqp"


def test_detuning_com_highs_e_reprovado_no_boot():
    """Fail fast: config inconsistente derruba a montagem, não o ciclo."""
    raw = _config(delta_preco=0.0, detuning=0.5).model_dump()
    raw["economics"]["solver"] = "highs"

    with pytest.raises(ValueError, match="QP"):
        SteadyStateOptimizer(MpcConfig.model_validate(raw), TS)
