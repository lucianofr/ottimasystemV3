"""SSTO: montagem e resolução do LP de alvos de regime permanente (ADR-026 §2/§5/§6).

Problema (ADR-026 §2), com `x = [ΔMV, s]`:

    min  cᵀ·ΔMV + wᵀ·s
    s.a. L ≤ CVˢˢ_livre + G·ΔMV ≤ U   (folga `s ≥ 0` nos DOIS lados, por linha)
         ΔMV_L ≤ ΔMV ≤ ΔMV_U          (HARD — nunca relaxado)

`CVˢˢ_livre = base(u, d_prev) + Gd·ΔDV` é o regime permanente previsto **sem mover a MV**:
`base` já traz a correção por bias (DMC) do worker, e `Gd·ΔDV` é o degrau de DV desde a
execução anterior. As duas parcelas somadas dão o mesmo número que `G(u−op) + Gd(d−op) +
bias`; ficam separadas porque a auditoria (e o caso 3 do brief) precisam enxergar o
feedforward de regime como termo próprio.

**Classe de variável (ADR-026 §5), invariante do módulo:**
- MV é a ÚNICA variável de decisão, e o limite dela é duro em todo caminho de código;
- CV/Restrição são linhas — limite soft, com folga penalizada e rank;
- DV entra só por `Gd·ΔDV`. Não há caminho em que uma DV vire coluna de decisão: o vetor de
  decisão é construído a partir de `model.mv_ids`, e preço configurado num id de DV
  simplesmente não encontra coluna onde entrar.

**Inviabilidade em duas linhas de defesa (ADR-026 §6):** a folga penalizada resolve o caso
comum; quando ela estoura `SLACK_TOL`, a linha VIOLADA de menor `priority` é removida do
conjunto de restrições e o LP roda de novo, repetindo até sobrar só o que cabe. Cada
remoção é registrada em ordem. Limite de MV nunca entra nessa conta.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from ottima_core.flowgraph import MpcConfig, economics_config_hash
from ottima_flow_runtime.target_calculation.model import (
    SteadyStateModel,
    build_steady_state_model,
)
from ottima_flow_runtime.target_calculation.solver import (
    QuadraticTerm,
    SolverBackend,
    SolverResult,
    SolverStatus,
    get_backend,
)

SLACK_TOL = 1e-6
"""Folga acima da qual uma linha conta como VIOLADA e vira candidata a desistência. Abaixo
disso é resíduo numérico do solver, não violação de faixa."""


@dataclass(frozen=True, slots=True, eq=False)
class SstoInput:
    """Instantâneo de entrada de uma execução do SSTO.

    `u`: MV efetivamente aplicada (o mesmo `u_applied` que o worker usa no bias — nunca o
    plano comandado). `d`: DV medida agora. `d_prev`: DV da execução anterior (`None` na
    primeira ⇒ `ΔDV = 0`). `bias`: correção DMC por linha. `delta_mv_prev`: solução anterior,
    consumida só pelo detuning anti-flipping (ADR-026 §8).
    """

    u: Mapping[str, float]
    d: Mapping[str, float]
    d_prev: Mapping[str, float] | None
    bias: Mapping[str, float]
    delta_mv_prev: Mapping[str, float] | None


@dataclass(frozen=True, slots=True, eq=False)
class SstoResult:
    """Resultado de uma execução — a fonte do registro de auditoria (ADR-026 §11)."""

    status: SolverStatus
    delta_mv: dict[str, float]
    mv_target: dict[str, float]
    cv_target: dict[str, float]
    """Alvo por LINHA (CV e Restrição). Em linha `integrating` o valor é uma TAXA [EU/s],
    não um nível — quem consome precisa olhar o `kind` antes de usá-lo como SP."""
    cv_ss_free: dict[str, float]
    dv_shift: dict[str, float]
    slacks: dict[str, float]
    costs: dict[str, float]
    """Vetor `c` de fato usado, já com os preços de linha projetados por `c_row·G`."""
    objective: float
    given_up: tuple[str, ...]
    active_constraints: tuple[str, ...]
    active_mv_bounds: tuple[str, ...]
    duals: dict[str, float]
    config_hash: str
    solver: str
    solve_ms: float
    detail: str = ""


class SteadyStateOptimizer:
    """Otimizador de alvos de um bloco MPC (ADR-026 §2).

    Instância longa: monta `G`/`Gd`, limites, ranks e o vetor de custos UMA vez, no boot do
    worker, e reaproveita a cada execução. Toda a variação de ciclo entra por `SstoInput`.
    """

    def __init__(
        self, config: MpcConfig, ts_mpc: float, backend: SolverBackend | None = None
    ) -> None:
        economics = config.economics
        if economics is None or not economics.enabled:
            raise ValueError("SSTO desabilitado neste bloco: 'economics.enabled' é falso")
        if economics.detuning_weight > 0.0 and economics.solver == "highs":
            # Falha no boot do worker, não a cada ciclo: o HiGHS recusaria o termo
            # quadrático em runtime, e um MPC que sobe só para morrer no 1º solve é pior
            # que um deploy reprovado.
            raise ValueError(
                "detuning_weight > 0 exige um backend QP: use solver='osqp' (ADR-026 §8)"
            )

        self._economics = economics
        self._model = build_steady_state_model(config, ts_mpc)
        self._config_hash = economics_config_hash(config)
        self._backend = backend if backend is not None else get_backend(economics.solver)

        rows = [*config.variables.cvs, *config.variables.constraints]
        epsilon = economics.integrating_tolerance
        self._row_priority = {var.id: var.priority for var in rows}
        self._row_order = {var.id: i for i, var in enumerate(rows)}
        self._row_limits: dict[str, tuple[float, float]] = {}
        for var in rows:
            if var.kind == "integrating":
                # Linha integradora não tem nível de regime: o que se exige é taxa nula
                # dentro de ±ε (ADR-026 §4).
                self._row_limits[var.id] = (-epsilon, epsilon)
            elif hasattr(var, "sp_limits"):
                self._row_limits[var.id] = (var.sp_limits.min, var.sp_limits.max)
            else:
                self._row_limits[var.id] = (var.range.low, var.range.high)

        self._mv_limits = {mv.id: (mv.limits.min, mv.limits.max) for mv in config.variables.mvs}
        self._costs = self._build_costs()

    @property
    def decision_ids(self) -> tuple[str, ...]:
        """Variáveis de decisão do LP — só MVs, sempre (ADR-026 §5)."""
        return self._model.mv_ids

    @property
    def model(self) -> SteadyStateModel:
        return self._model

    @property
    def config_hash(self) -> str:
        return self._config_hash

    def _build_costs(self) -> np.ndarray:
        """`c = c_mv + Σ_i c_row_i · G_i` (ADR-026 §9).

        Preço de linha é projetado no espaço de decisão em vez de virar variável nova: a
        decisão continua sendo só `ΔMV`, como a formulação exige. Preço em id que não é MV
        nem linha (uma DV, por exemplo) não encontra coluna e não afeta nada.
        """
        costs = self._economics.costs
        c = np.array([costs.get(mv_id, 0.0) for mv_id in self._model.mv_ids], dtype=float)
        row_costs = np.array(
            [costs.get(row_id, 0.0) for row_id in self._model.row_ids], dtype=float
        )
        return c + row_costs @ self._model.g

    def solve(self, entrada: SstoInput) -> SstoResult:
        """Uma execução completa: monta, resolve e — se preciso — desiste por rank."""
        model = self._model
        d_prev = entrada.d_prev if entrada.d_prev is not None else entrada.d
        base = model.base(u=entrada.u, d=d_prev, bias=entrada.bias)
        delta_dv = np.array(
            [entrada.d[dv_id] - d_prev[dv_id] for dv_id in model.dv_ids], dtype=float
        )
        dv_shift = model.gd @ delta_dv
        cv_ss_free = base + dv_shift

        bounds = tuple(
            (
                self._mv_limits[mv_id][0] - entrada.u[mv_id],
                self._mv_limits[mv_id][1] - entrada.u[mv_id],
            )
            for mv_id in model.mv_ids
        )
        quadratic = self._quadratic_term(entrada)

        kept = list(model.row_ids)
        given_up: list[str] = []
        while True:
            raw = self._solve_once(kept, cv_ss_free, bounds, quadratic)
            if raw.status in ("optimal", "relaxed"):
                slacks = self._slacks(raw, kept)
                violated = [row_id for row_id in kept if slacks[row_id] > SLACK_TOL]
                if not violated:
                    return self._build_result(raw, kept, given_up, cv_ss_free, dv_shift, entrada)
                candidates = violated
            else:
                if not kept:
                    return self._failed_result(raw, given_up, cv_ss_free, dv_shift, entrada)
                candidates = kept

            victim = min(
                candidates, key=lambda row_id: (self._row_priority[row_id], self._row_order[row_id])
            )
            kept.remove(victim)
            given_up.append(victim)

    def _quadratic_term(self, entrada: SstoInput) -> QuadraticTerm | None:
        """Detuning anti-flipping (ADR-026 §8): `ρ‖ΔMV − ΔMV_anterior‖²`.

        Sem solução anterior (primeira execução após deploy/rearme) a referência é o zero —
        que é o próprio "não se mexer", o ponto de partida honesto.
        """
        rho = self._economics.detuning_weight
        if rho <= 0.0:
            return None
        previous = entrada.delta_mv_prev or {}
        reference = np.array(
            [previous.get(mv_id, 0.0) for mv_id in self._model.mv_ids], dtype=float
        )
        return QuadraticTerm(weight=rho, reference=reference)

    def _solve_once(
        self,
        kept: list[str],
        cv_ss_free: np.ndarray,
        bounds: tuple[tuple[float | None, float | None], ...],
        quadratic: QuadraticTerm | None,
    ) -> SolverResult:
        """LP/QP de UMA rodada, com o conjunto de linhas `kept` (ADR-026 §6)."""
        model = self._model
        n_mv = len(model.mv_ids)
        n_slack = len(kept)
        row_index = {row_id: i for i, row_id in enumerate(model.row_ids)}

        a_ub = np.zeros((2 * n_slack, n_mv + n_slack))
        b_ub = np.zeros(2 * n_slack)
        for k, row_id in enumerate(kept):
            i = row_index[row_id]
            low, high = self._row_limits[row_id]
            a_ub[2 * k, :n_mv] = model.g[i]
            a_ub[2 * k, n_mv + k] = -1.0
            b_ub[2 * k] = high - cv_ss_free[i]
            a_ub[2 * k + 1, :n_mv] = -model.g[i]
            a_ub[2 * k + 1, n_mv + k] = -1.0
            b_ub[2 * k + 1] = cv_ss_free[i] - low

        c = np.concatenate(
            [
                self._costs,
                np.array(
                    [self._economics.slack_weight * self._row_priority[row_id] for row_id in kept],
                    dtype=float,
                ),
            ]
        )
        full_bounds = (*bounds, *(((0.0, None),) * n_slack))
        return self._backend.solve(c, a_ub, b_ub, full_bounds, quadratic)

    def _slacks(self, raw: SolverResult, kept: list[str]) -> dict[str, float]:
        n_mv = len(self._model.mv_ids)
        return {row_id: float(raw.x[n_mv + k]) for k, row_id in enumerate(kept)}

    def _build_result(
        self,
        raw: SolverResult,
        kept: list[str],
        given_up: list[str],
        cv_ss_free: np.ndarray,
        dv_shift: np.ndarray,
        entrada: SstoInput,
    ) -> SstoResult:
        model = self._model
        n_mv = len(model.mv_ids)
        delta = np.asarray(raw.x[:n_mv], dtype=float)
        targets = cv_ss_free + model.g @ delta

        slacks = dict.fromkeys(model.row_ids, 0.0)
        slacks.update(self._slacks(raw, kept))

        labels = self._constraint_labels(kept)
        active = tuple(labels[i] for i in raw.active_constraints if i < len(labels))
        active_mv = tuple(model.mv_ids[i] for i in raw.active_bounds if i < n_mv)
        duals = {labels[i]: float(raw.duals[i]) for i in range(len(labels))}

        return SstoResult(
            status="relaxed" if given_up else "optimal",
            delta_mv={mv_id: float(delta[j]) for j, mv_id in enumerate(model.mv_ids)},
            mv_target={
                mv_id: float(entrada.u[mv_id] + delta[j]) for j, mv_id in enumerate(model.mv_ids)
            },
            cv_target={row_id: float(targets[i]) for i, row_id in enumerate(model.row_ids)},
            cv_ss_free={row_id: float(cv_ss_free[i]) for i, row_id in enumerate(model.row_ids)},
            dv_shift={row_id: float(dv_shift[i]) for i, row_id in enumerate(model.row_ids)},
            slacks=slacks,
            costs={mv_id: float(self._costs[j]) for j, mv_id in enumerate(model.mv_ids)},
            objective=raw.objective,
            given_up=tuple(given_up),
            active_constraints=active,
            active_mv_bounds=active_mv,
            duals=duals,
            config_hash=self._config_hash,
            solver=raw.solver,
            solve_ms=raw.solve_ms,
            detail=raw.detail,
        )

    def _failed_result(
        self,
        raw: SolverResult,
        given_up: list[str],
        cv_ss_free: np.ndarray,
        dv_shift: np.ndarray,
        entrada: SstoInput,
    ) -> SstoResult:
        """Nem sem nenhuma linha o problema fecha (limites de MV inconsistentes ou falha do
        solver): ΔMV = 0 e status honesto. Quem chama cai no fallback — SP do operador."""
        model = self._model
        return SstoResult(
            status=raw.status,
            delta_mv=dict.fromkeys(model.mv_ids, 0.0),
            mv_target={mv_id: float(entrada.u[mv_id]) for mv_id in model.mv_ids},
            cv_target={row_id: float(cv_ss_free[i]) for i, row_id in enumerate(model.row_ids)},
            cv_ss_free={row_id: float(cv_ss_free[i]) for i, row_id in enumerate(model.row_ids)},
            dv_shift={row_id: float(dv_shift[i]) for i, row_id in enumerate(model.row_ids)},
            slacks=dict.fromkeys(model.row_ids, 0.0),
            costs={mv_id: float(self._costs[j]) for j, mv_id in enumerate(model.mv_ids)},
            objective=0.0,
            given_up=tuple(given_up),
            active_constraints=(),
            active_mv_bounds=(),
            duals={},
            config_hash=self._config_hash,
            solver=raw.solver,
            solve_ms=raw.solve_ms,
            detail=raw.detail,
        )

    def _constraint_labels(self, kept: list[str]) -> list[str]:
        """Rótulo por linha de `A_ub`, na mesma ordem em que foram montadas."""
        labels: list[str] = []
        for row_id in kept:
            labels.append(f"{row_id}:high")
            labels.append(f"{row_id}:low")
        return labels
