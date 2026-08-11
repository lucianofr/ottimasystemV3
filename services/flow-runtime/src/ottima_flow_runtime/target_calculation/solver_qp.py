"""Backend QP (OSQP) — mitigação de LP flipping por detuning (ADR-027 §7/§8).

**Por que existe:** a solução de um LP vive num VÉRTICE do politopo. Quando o vetor de
custos fica quase paralelo a uma aresta — situação comum quando duas MVs têm preço parecido
— ruído de medida ou um ajuste marginal de limite fazem o ótimo saltar de um vértice a outro,
e os alvos passam a oscilar entre extremos sem que nada relevante tenha mudado na planta.
Isso é o *LP flipping*, e é propriedade da geometria do LP, não defeito do solver.

O detuning acrescenta `ρ‖ΔMV − ΔMV_anterior‖²` ao objetivo. O problema deixa de ser um LP:
o ótimo passa a poder cair no INTERIOR de uma face, e a solução vira contínua na
perturbação — entre dois vértices igualmente ótimos, vence o mais próximo do que já estava
em vigor. Não é "suavização" genérica de sinal (não há filtro nem constante de tempo aqui):
é a quebra de empate que o LP puro não tem.

`ρ` é do config (`EconomicsConfig.detuning_weight`), e `ρ = 0` devolve o LP puro — a escolha
entre estabilidade e ótimo econômico estrito é do usuário, não deste módulo.

Forma do OSQP: `min ½ zᵀPz + qᵀz` s.a. `l ≤ Az ≤ u`. Ele não tem limite de variável
separado, então os limites viram linhas de identidade empilhadas sob `A_ub` — o que também
deixa as marginais dos limites saírem no mesmo vetor de duais.
"""

import time

import numpy as np
import osqp
import scipy.sparse as sparse

from ottima_flow_runtime.target_calculation.solver import (
    ACTIVE_TOL,
    Bounds,
    QuadraticTerm,
    SolverResult,
    SolverStatus,
    register_backend,
)

_SETTINGS = {
    "verbose": False,
    "eps_abs": 1e-9,
    "eps_rel": 1e-9,
    "polishing": True,
    "max_iter": 20_000,
}
"""Tolerâncias apertadas e `polishing` ligado de propósito: no default (1e-3) o OSQP devolve
o alvo com erro visível em EU de planta, e alvo com folga de arredondamento vira movimento
espúrio de MV no ciclo seguinte."""

_STATUS: dict[str, SolverStatus] = {
    "solved": "optimal",
    "solved inaccurate": "optimal",
    "primal infeasible": "infeasible",
    "primal infeasible inaccurate": "infeasible",
    "dual infeasible": "unbounded",
    "dual infeasible inaccurate": "unbounded",
}


class OSQPBackend:
    """QP por OSQP — backend do detuning anti-flipping (ADR-027 §8).

    Aceita `quadratic=None`: sem termo quadrático o problema é o mesmo LP (`P = 0`), o que
    mantém o backend utilizável quando o usuário escolhe `solver="osqp"` e ainda não ligou
    o detuning.
    """

    name = "osqp"

    def solve(
        self,
        c: np.ndarray,
        a_ub: np.ndarray,
        b_ub: np.ndarray,
        bounds: Bounds,
        quadratic: QuadraticTerm | None = None,
    ) -> SolverResult:
        n = len(bounds)
        n_rows = a_ub.shape[0]

        p = np.zeros((n, n))
        q = np.array(c, dtype=float)
        if quadratic is not None:
            m = quadratic.reference.size
            # `½ zᵀPz` do OSQP contra `ρ‖z − ref‖²`: P = 2ρI e q recebe −2ρ·ref. O termo
            # constante `ρ‖ref‖²` é omitido (não muda o argmin) — quem compara valores de
            # objetivo entre backends precisa saber disso.
            p[:m, :m] = 2.0 * quadratic.weight * np.eye(m)
            q[:m] = q[:m] - 2.0 * quadratic.weight * quadratic.reference

        lower_bounds = np.array([-np.inf if lo is None else lo for lo, _ in bounds], dtype=float)
        upper_bounds = np.array([np.inf if hi is None else hi for _, hi in bounds], dtype=float)
        a_full = sparse.csc_matrix(np.vstack([a_ub, np.eye(n)]) if n_rows else np.eye(n))
        l_full = np.concatenate([np.full(n_rows, -np.inf), lower_bounds])
        u_full = np.concatenate([b_ub, upper_bounds])

        problem = osqp.OSQP()
        problem.setup(sparse.csc_matrix(p), q, a_full, l_full, u_full, **_SETTINGS)
        t0 = time.perf_counter()
        res = problem.solve()
        solve_ms = (time.perf_counter() - t0) * 1000.0

        status = _STATUS.get(str(res.info.status), "error")
        if status != "optimal":
            return SolverResult(
                status=status,
                x=np.zeros(0),
                objective=0.0,
                active_constraints=(),
                active_bounds=(),
                duals=np.zeros(0),
                bound_duals=np.zeros(0),
                solver=self.name,
                solve_ms=solve_ms,
                detail=str(res.info.status),
            )

        x = np.asarray(res.x, dtype=float)
        duals = np.asarray(res.y, dtype=float)
        residual = u_full - a_full @ x
        active = np.abs(residual) <= ACTIVE_TOL

        return SolverResult(
            status="optimal",
            x=x,
            objective=float(res.info.obj_val),
            active_constraints=tuple(int(i) for i in np.flatnonzero(active[:n_rows])),
            active_bounds=tuple(int(i) for i in np.flatnonzero(active[n_rows:])),
            duals=duals[:n_rows],
            bound_duals=duals[n_rows:],
            solver=self.name,
            solve_ms=solve_ms,
        )


register_backend("osqp", OSQPBackend)
