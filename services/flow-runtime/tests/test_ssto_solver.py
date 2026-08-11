"""Mesa de casos dos backends de solver do SSTO (ADR-027 §7).

Cobre o **caso obrigatório 1** do brief (objetivo trivial: custo único numa MV, limites
folgados ⇒ a MV vai ao limite esperado) e a superfície da interface plugável: status,
marginais (shadow prices), conjunto ativo e o stub do Gurobi.
"""

import numpy as np
import pytest

from ottima_flow_runtime.target_calculation.solver import (
    GurobiBackend,
    HiGHSBackend,
    QuadraticTerm,
    SolverBackend,
    get_backend,
)

NO_ROWS = np.zeros((0, 1))
NO_RHS = np.zeros(0)


def test_highs_e_um_solverbackend():
    """A interface é `Protocol` runtime-checkable: o registro aceita qualquer backend que
    cumpra a assinatura, sem herança."""
    assert isinstance(HiGHSBackend(), SolverBackend)


# ---------------------------------------------------------------------------------------
# Caso obrigatório 1 — objetivo trivial
# ---------------------------------------------------------------------------------------


def test_custo_positivo_leva_a_variavel_ao_limite_inferior():
    """`min c·x` com `c > 0` e limites folgados: a solução é o limite INFERIOR."""
    result = HiGHSBackend().solve(np.array([1.0]), NO_ROWS, NO_RHS, ((-5.0, 10.0),))

    assert result.status == "optimal"
    assert result.x == pytest.approx(np.array([-5.0]))
    assert result.objective == pytest.approx(-5.0)


def test_custo_negativo_leva_a_variavel_ao_limite_superior():
    """Preço negativo = maximizar (ADR-027 §9): a solução vai ao limite SUPERIOR."""
    result = HiGHSBackend().solve(np.array([-2.0]), NO_ROWS, NO_RHS, ((-5.0, 10.0),))

    assert result.status == "optimal"
    assert result.x == pytest.approx(np.array([10.0]))
    assert result.objective == pytest.approx(-20.0)


def test_limite_de_variavel_ativo_aparece_no_conjunto_ativo():
    result = HiGHSBackend().solve(
        np.array([1.0, -1.0]), NO_ROWS.repeat(2, axis=1), NO_RHS, ((0.0, 4.0), (0.0, 4.0))
    )

    assert result.active_bounds == (0, 1)
    assert result.active_constraints == ()


def test_restricao_de_linha_ativa_traz_shadow_price():
    """`max x` sujeito a `x ≤ 3` (limite de variável folgado em 10): a restrição de linha é
    quem segura o ótimo, e a marginal dela é não nula."""
    result = HiGHSBackend().solve(
        np.array([-1.0]), np.array([[1.0]]), np.array([3.0]), ((0.0, 10.0),)
    )

    assert result.x == pytest.approx(np.array([3.0]))
    assert result.active_constraints == (0,)
    assert result.duals[0] != 0.0


def test_solver_e_tempo_vem_preenchidos():
    result = HiGHSBackend().solve(np.array([1.0]), NO_ROWS, NO_RHS, ((0.0, 1.0),))

    assert result.solver == "highs"
    assert result.solve_ms >= 0.0


# ---------------------------------------------------------------------------------------
# Status não-ótimos
# ---------------------------------------------------------------------------------------


def test_problema_inviavel_devolve_status_infeasible():
    """`x ≤ −1` com `x ≥ 0`: sem interseção."""
    result = HiGHSBackend().solve(
        np.array([1.0]), np.array([[1.0]]), np.array([-1.0]), ((0.0, 10.0),)
    )

    assert result.status == "infeasible"
    assert result.x.size == 0


def test_problema_ilimitado_devolve_status_unbounded():
    result = HiGHSBackend().solve(np.array([1.0]), NO_ROWS, NO_RHS, ((None, None),))

    assert result.status == "unbounded"


# ---------------------------------------------------------------------------------------
# Plugabilidade
# ---------------------------------------------------------------------------------------


def test_gurobi_e_stub_declarado():
    with pytest.raises(NotImplementedError):
        GurobiBackend().solve(np.array([1.0]), NO_ROWS, NO_RHS, ((0.0, 1.0),))


def test_highs_recusa_termo_quadratico():
    """LP não resolve QP: o detuning (ADR-027 §8) exige backend QP — falhar alto é melhor
    que ignorar o termo em silêncio e devolver um vértice."""
    with pytest.raises(ValueError, match="quadr"):
        HiGHSBackend().solve(
            np.array([1.0]),
            NO_ROWS,
            NO_RHS,
            ((0.0, 1.0),),
            QuadraticTerm(weight=1.0, reference=np.array([0.0])),
        )


def test_registro_resolve_backend_por_nome():
    assert get_backend("highs").name == "highs"
    assert get_backend("gurobi").name == "gurobi"


def test_registro_rejeita_nome_desconhecido():
    with pytest.raises(KeyError):
        get_backend("cplex")  # type: ignore[arg-type]
