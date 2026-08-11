"""Backends de solver do SSTO — interface plugável (ADR-027 §7).

`SolverBackend` é um `Protocol` runtime-checkable: qualquer objeto com `name` e o `solve`
da assinatura serve, sem herança. Três implementações previstas:

- `HiGHSBackend` — default, `scipy.optimize.linprog(method="highs")`. LP puro.
- `OSQPBackend` — QP do detuning anti-flipping (`solver_qp.py`, ADR-027 §8).
- `GurobiBackend` — stub declarado: a interface suporta o plugin, a implementação não é
  desta fase.

Forma do problema (a mesma para todos os backends):

    min_x  cᵀ·x  [+ ρ‖x − x_ref‖²]     s.a.  A_ub·x ≤ b_ub,  lo ≤ x ≤ hi

Faixa dupla (`L ≤ G·Δ ≤ U`) chega aqui já desdobrada em duas linhas de `A_ub` por
restrição — a tradução é do montador do LP (`ssto.py`), não do backend.
"""

import time
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import numpy as np
from scipy.optimize import linprog

from ottima_core.flowgraph import SolverName

SolverStatus = Literal["optimal", "relaxed", "infeasible", "unbounded", "error"]
"""`relaxed` NUNCA é emitido por um backend: é o status que a camada de inviabilidade
(`ssto.py`) carimba quando chegou a uma solução desistindo de linhas por rank (ADR-027 §6).
Fica no mesmo vocabulário para o registro de auditoria ter um campo só."""

ACTIVE_TOL = 1e-7
"""Folga abaixo da qual uma restrição/limite conta como ATIVO. Numérico puro: o HiGHS
devolve residual da ordem de 1e-12 num vértice exato, e 1e-7 separa isso de uma folga real
sem depender da escala do problema (limites do SSTO são EU de planta, ordem 1..1e3)."""


@dataclass(frozen=True, slots=True, eq=False)
class QuadraticTerm:
    """Termo `ρ‖x − x_ref‖²` do detuning anti-flipping (ADR-027 §8).

    `eq=False`: `reference` é `np.ndarray`.
    """

    weight: float
    reference: np.ndarray


@dataclass(frozen=True, slots=True, eq=False)
class SolverResult:
    """Resposta de um backend — tudo que a auditoria (ADR-027 §11) precisa registrar.

    `duals`: marginais (shadow prices) das linhas de `A_ub`; `bound_duals`, as dos limites
    de variável. Sinal e escala são os do `scipy` (`ineqlin`/`upper`/`lower`), repassados
    sem reinterpretação.

    `active_constraints`/`active_bounds`: índices de linha de `A_ub` e de variável cujo
    resíduo é nulo dentro de `ACTIVE_TOL` — o conjunto ativo do vértice.
    """

    status: SolverStatus
    x: np.ndarray
    objective: float
    active_constraints: tuple[int, ...]
    active_bounds: tuple[int, ...]
    duals: np.ndarray
    bound_duals: np.ndarray
    solver: str
    solve_ms: float
    detail: str = ""


Bounds = tuple[tuple[float | None, float | None], ...]


@runtime_checkable
class SolverBackend(Protocol):
    """Contrato de um backend (ADR-027 §7)."""

    name: str

    def solve(
        self,
        c: np.ndarray,
        a_ub: np.ndarray,
        b_ub: np.ndarray,
        bounds: Bounds,
        quadratic: QuadraticTerm | None = None,
    ) -> SolverResult: ...


def _active_bounds(x: np.ndarray, bounds: Bounds) -> tuple[int, ...]:
    active: list[int] = []
    for i, (lo, hi) in enumerate(bounds):
        at_low = lo is not None and abs(x[i] - lo) <= ACTIVE_TOL
        at_high = hi is not None and abs(x[i] - hi) <= ACTIVE_TOL
        if at_low or at_high:
            active.append(i)
    return tuple(active)


def _empty(status: SolverStatus, solver: str, solve_ms: float, detail: str) -> SolverResult:
    return SolverResult(
        status=status,
        x=np.zeros(0),
        objective=0.0,
        active_constraints=(),
        active_bounds=(),
        duals=np.zeros(0),
        bound_duals=np.zeros(0),
        solver=solver,
        solve_ms=solve_ms,
        detail=detail,
    )


@dataclass(frozen=True, slots=True)
class HiGHSBackend:
    """LP por `scipy.optimize.linprog(method="highs")` — backend default (ADR-027 §7)."""

    name: str = "highs"

    def solve(
        self,
        c: np.ndarray,
        a_ub: np.ndarray,
        b_ub: np.ndarray,
        bounds: Bounds,
        quadratic: QuadraticTerm | None = None,
    ) -> SolverResult:
        if quadratic is not None:
            raise ValueError(
                "HiGHSBackend resolve só LP: termo quadrático (detuning) exige um backend QP"
            )

        t0 = time.perf_counter()
        res = linprog(
            c=c,
            A_ub=a_ub if a_ub.shape[0] else None,
            b_ub=b_ub if a_ub.shape[0] else None,
            bounds=bounds,
            method="highs",
        )
        solve_ms = (time.perf_counter() - t0) * 1000.0

        if res.status == 2:
            return _empty("infeasible", self.name, solve_ms, str(res.message))
        if res.status == 3:
            return _empty("unbounded", self.name, solve_ms, str(res.message))
        if res.status != 0:
            return _empty("error", self.name, solve_ms, str(res.message))

        x = np.asarray(res.x, dtype=float)
        residual = np.asarray(res.ineqlin.residual, dtype=float) if a_ub.shape[0] else np.zeros(0)
        duals = np.asarray(res.ineqlin.marginals, dtype=float) if a_ub.shape[0] else np.zeros(0)
        # Só um dos dois lados pode estar ativo por variável, então somar as duas marginais
        # devolve a marginal do lado que de fato está ativo (a outra é 0).
        bound_duals = np.asarray(res.lower.marginals, dtype=float) + np.asarray(
            res.upper.marginals, dtype=float
        )

        return SolverResult(
            status="optimal",
            x=x,
            objective=float(res.fun),
            active_constraints=tuple(
                int(i) for i in np.flatnonzero(np.abs(residual) <= ACTIVE_TOL)
            ),
            active_bounds=_active_bounds(x, bounds),
            duals=duals,
            bound_duals=bound_duals,
            solver=self.name,
            solve_ms=solve_ms,
        )


@dataclass(frozen=True, slots=True)
class GurobiBackend:
    """Stub declarado (ADR-027 §7): a interface suporta o plugin comercial, a implementação
    não é desta fase."""

    name: str = "gurobi"

    def solve(
        self,
        c: np.ndarray,
        a_ub: np.ndarray,
        b_ub: np.ndarray,
        bounds: Bounds,
        quadratic: QuadraticTerm | None = None,
    ) -> SolverResult:
        raise NotImplementedError("GurobiBackend ainda não implementado (ADR-027 §7)")


_BACKENDS: dict[str, type] = {"highs": HiGHSBackend, "gurobi": GurobiBackend}


def get_backend(name: SolverName) -> SolverBackend:
    """Resolve o backend por nome (`EconomicsConfig.solver`).

    `osqp` é registrado por `solver_qp.py`, importado só quando pedido: o caminho LP puro
    não carrega a biblioteca QP.
    """
    if name == "osqp" and "osqp" not in _BACKENDS:
        from ottima_flow_runtime.target_calculation import solver_qp  # noqa: F401

    if name not in _BACKENDS:
        raise KeyError(f"backend de solver desconhecido: {name!r}")
    return _BACKENDS[name]()


def register_backend(name: str, backend: type) -> None:
    """Registra um backend adicional (usado por `solver_qp.py`)."""
    _BACKENDS[name] = backend
