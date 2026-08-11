"""SSTO: montagem e resolução do LP de alvos de regime permanente (ADR-027 §2/§5/§6).

Problema (ADR-027 §2), com `x = [ΔMV, s]`:

    min  cᵀ·ΔMV + wᵀ·s
    s.a. L ≤ CVˢˢ_livre + G·ΔMV ≤ U   (folga `s ≥ 0` nos DOIS lados, por linha)
         ΔMV_L ≤ ΔMV ≤ ΔMV_U          (HARD — nunca relaxado)

`CVˢˢ_livre = base(u, d_prev) + Gd·ΔDV` é o regime permanente previsto **sem mover a MV**:
`base` já traz a correção por bias (DMC) do worker, e `Gd·ΔDV` é o degrau de DV desde a
execução anterior. As duas parcelas somadas dão o mesmo número que `G(u−op) + Gd(d−op) +
bias`; ficam separadas porque a auditoria (e o caso 3 do brief) precisam enxergar o
feedforward de regime como termo próprio.

**Classe de variável (ADR-027 §5), invariante do módulo:**
- MV é a ÚNICA variável de decisão, e o limite dela é duro em todo caminho de código;
- CV/Restrição são linhas — limite soft, com folga penalizada e rank;
- DV entra só por `Gd·ΔDV`. Não há caminho em que uma DV vire coluna de decisão: o vetor de
  decisão é construído a partir de `model.mv_ids`, e preço configurado num id de DV
  simplesmente não encontra coluna onde entrar.

**Inviabilidade em duas linhas de defesa (ADR-027 §6):** a folga penalizada resolve o caso
comum; quando ela estoura `SLACK_TOL`, a linha VIOLADA de menor `priority` é removida do
conjunto de restrições e o LP roda de novo, repetindo até sobrar só o que cabe. Cada
remoção é registrada em ordem. Limite de MV nunca entra nessa conta.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from ottima_core.flowgraph import (
    EconomicsConfig,
    MpcConfig,
    economics_config_hash,
    optimization_enabled,
)
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

# Pesos da função objetivo por variável (ADR-027 §9 estendido). A ordem de dominância é
# deliberada e fixa: `folga-de-limite (slack_weight×priority, ≥1e3 por EU cru) ≫ target ≫
# max/min (1.0/span) ≫ psv = equalize ≫ observe_limit`. `target` é a preferência forte do
# otimizador (vence qualquer preço); `psv`/`equalize` são preferências fracas — cedem a
# qualquer preço de max/min e só decidem o grau de liberdade que sobraria solto; `observe_limit`
# é o mais fraco de todos: só se move o necessário para viabilizar as restrições.
# Nota de escala: os tiers assumem spans ≳ 0.1 EU; um span minúsculo amplifica o peso
# efetivo (`W/span`) e pode inverter a dominância frente ao `slack_weight` (que é por EU cru).
W_TARGET = 50.0
W_PSV = 0.1
W_OBSERVE = 0.01
W_EQUALIZE = 0.1

_CV_ANCHOR_WEIGHT = {"target": W_TARGET, "psv": W_PSV, "observe_limit": W_OBSERVE}
"""Peso por span da âncora L1 de CV, por `objective` (validadores garantem `kind=selfreg`).
`maximize`/`minimize` NÃO estão aqui: são preço linear puro, montado em `_build_costs`."""


@dataclass(frozen=True, slots=True, eq=False)
class SstoInput:
    """Instantâneo de entrada de uma execução do SSTO.

    `u`: MV efetivamente aplicada (o mesmo `u_applied` que o worker usa no bias — nunca o
    plano comandado). `d`: DV medida agora. `d_prev`: DV da execução anterior (`None` na
    primeira ⇒ `ΔDV = 0`). `bias`: correção DMC por linha. `delta_mv_prev`: solução anterior,
    consumida só pelo detuning anti-flipping (ADR-027 §8).

    `frozen_mvs`: MVs fora do comando do MPC neste ciclo (ADR-028, mesmo conjunto que
    `SolveRequest.frozen_mvs`) — o LP as trata como `ΔMV ≡ 0` (`solve`, limites clampados em
    `(0, 0)`), nunca como variável de decisão livre: um `cv_target`/`mv_target` que
    pressupusesse movimento de uma MV congelada seria um alvo que o MPC dinâmico jamais
    alcança (ela está com `dumax = 0` no horizonte inteiro, TD-014). Default vazio preserva
    o comportamento pré-ADR-028 bit a bit para quem monta `SstoInput` sem o campo. O
    detuning anti-flipping (`_quadratic_term`) não precisa de tratamento à parte: com
    `ΔMV ≡ 0` forçado pelo limite, a penalidade `ρ‖ΔMV − ΔMV_anterior‖²` não muda o
    resultado da MV congelada — só contribui um termo constante ao objetivo por um ciclo,
    até `ΔMV_anterior` dela também zerar."""

    u: Mapping[str, float]
    d: Mapping[str, float]
    d_prev: Mapping[str, float] | None
    bias: Mapping[str, float]
    delta_mv_prev: Mapping[str, float] | None
    frozen_mvs: frozenset[str] = frozenset()
    sp: Mapping[str, float] | None = None
    """SP do operador por CV (o mesmo `SolveRequest.sp` do ciclo) — âncora dos objetivos de
    CV `target`/`psv`/`observe_limit`. `None` (testes antigos, chamadas defensivas) ⇒ as
    âncoras de CV são PULADAS naquele solve: âncora sem referência seria um alvo inventado,
    pior que nenhum. O worker sempre fornece."""


@dataclass(frozen=True, slots=True, eq=False)
class SstoResult:
    """Resultado de uma execução — a fonte do registro de auditoria (ADR-027 §11)."""

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
    """Otimizador de alvos de um bloco MPC (ADR-027 §2).

    Instância longa: monta `G`/`Gd`, limites, ranks e o vetor de custos UMA vez, no boot do
    worker, e reaproveita a cada execução. Toda a variação de ciclo entra por `SstoInput`.
    """

    def __init__(
        self, config: MpcConfig, ts_mpc: float, backend: SolverBackend | None = None
    ) -> None:
        if not optimization_enabled(config):
            raise ValueError(
                "SSTO desabilitado neste bloco: nem 'economics.enabled' nem nenhuma "
                "variável com função objetivo"
            )
        economics = config.economics if config.economics is not None else EconomicsConfig()
        # Só há otimização por objetivo de variável (sem bloco economics): os defaults de
        # `EconomicsConfig` (`slack_weight`, `solver='highs'`, sem detuning) se aplicam.
        if economics.detuning_weight > 0.0 and economics.solver == "highs":
            # Falha no boot do worker, não a cada ciclo: o HiGHS recusaria o termo
            # quadrático em runtime, e um MPC que sobe só para morrer no 1º solve é pior
            # que um deploy reprovado.
            raise ValueError(
                "detuning_weight > 0 exige um backend QP: use solver='osqp' (ADR-027 §8)"
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
                # dentro de ±ε (ADR-027 §4).
                self._row_limits[var.id] = (-epsilon, epsilon)
            elif hasattr(var, "sp_limits"):
                self._row_limits[var.id] = (var.sp_limits.min, var.sp_limits.max)
            else:
                self._row_limits[var.id] = (var.range.low, var.range.high)

        self._mv_limits = {mv.id: (mv.limits.min, mv.limits.max) for mv in config.variables.mvs}

        # ---- Estruturas da função objetivo por variável (pré-computadas uma vez) ----
        # Spans sempre > 0 (validado por `_check_mpc_numbers` no save; defesa aqui assume).
        self._mv_span = {
            mv.id: mv.limits.max - mv.limits.min for mv in config.variables.mvs
        }
        self._row_span: dict[str, float] = {}
        for var in rows:
            if hasattr(var, "sp_limits"):
                self._row_span[var.id] = var.sp_limits.max - var.sp_limits.min
            else:
                self._row_span[var.id] = var.range.high - var.range.low
        # CVs ancoradas no SP do operador: (row_id, peso por span), na ordem do config.
        self._cv_anchors: list[tuple[str, float]] = [
            (cv.id, peso)
            for cv in config.variables.cvs
            if cv.objective in _CV_ANCHOR_WEIGHT
            for peso in (_CV_ANCHOR_WEIGHT[cv.objective],)
        ]
        # MVs com valor preferido: (mv_id, psv), na ordem do config.
        self._mv_psv: list[tuple[str, float]] = [
            (mv.id, mv.psv)
            for mv in config.variables.mvs
            if mv.objective == "psv" and mv.psv is not None
        ]
        # Grupo equalize (único, ADR-027 §9 estendido): todas as MVs marcadas, na ordem do
        # config — o par de folgas é (1ª, i-ésima), então a ordem define as linhas.
        self._equalize_ids: tuple[str, ...] = tuple(
            mv.id for mv in config.variables.mvs if mv.objective == "equalize"
        )
        # Mapas de preço linear por id (max/min) — consumidos por `_build_costs`.
        self._mv_objective = {mv.id: mv.objective for mv in config.variables.mvs}
        self._row_objective = {var.id: var.objective for var in rows}

        self._costs = self._build_costs()

    @property
    def decision_ids(self) -> tuple[str, ...]:
        """Variáveis de decisão do LP — só MVs, sempre (ADR-027 §5)."""
        return self._model.mv_ids

    @property
    def model(self) -> SteadyStateModel:
        return self._model

    @property
    def config_hash(self) -> str:
        return self._config_hash

    def _build_costs(self) -> np.ndarray:
        """`c = c_mv + Σ_i c_row_i · G_i` (ADR-027 §9).

        Preço de linha é projetado no espaço de decisão em vez de virar variável nova: a
        decisão continua sendo só `ΔMV`, como a formulação exige. Preço em id que não é MV
        nem linha (uma DV, por exemplo) não encontra coluna e não afeta nada.

        ADITIVO ao `economics.costs` legado, o preço derivado do `objective` enum:
        `maximize` = `−1.0/span`, `minimize` = `+1.0/span` (a coluna da MV, ou a linha da
        CV/Restrição projetada pelo mesmo mecanismo). Config sem objetivos reproduz o vetor
        de antes bit a bit.
        """
        costs = self._economics.costs
        c = np.array([costs.get(mv_id, 0.0) for mv_id in self._model.mv_ids], dtype=float)
        for mv_id, span in self._mv_span.items():
            objective = self._mv_objective.get(mv_id, "none")
            if objective == "maximize":
                c[self._model.mv_ids.index(mv_id)] -= 1.0 / span
            elif objective == "minimize":
                c[self._model.mv_ids.index(mv_id)] += 1.0 / span
        row_costs = np.array(
            [costs.get(row_id, 0.0) for row_id in self._model.row_ids], dtype=float
        )
        for row_id, span in self._row_span.items():
            objective = self._row_objective.get(row_id, "none")
            if objective == "maximize":
                row_costs[self._model.row_ids.index(row_id)] -= 1.0 / span
            elif objective == "minimize":
                row_costs[self._model.row_ids.index(row_id)] += 1.0 / span
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

        # MV congelada (ADR-028): `ΔMV ≡ 0`, mesmo mecanismo do `dumax = 0` do MPC dinâmico
        # (`worker.py::_apply_tvp`) — clampar o LIMITE, não excluir a coluna, mantém a
        # montagem estrutural idêntica (`n_mv` não muda) e a MV congelada segue entrando na
        # predição de `cv_ss_free` pelo `u` real medido (TD-014).
        bounds = tuple(
            (0.0, 0.0)
            if mv_id in entrada.frozen_mvs
            else (
                self._mv_limits[mv_id][0] - entrada.u[mv_id],
                self._mv_limits[mv_id][1] - entrada.u[mv_id],
            )
            for mv_id in model.mv_ids
        )
        quadratic = self._quadratic_term(entrada)

        # Âncoras de CV: alvo = SP do operador clampado nos limites da linha. Sem `sp` na
        # entrada (SstoInput montado sem o campo) as âncoras são puladas neste ciclo.
        anchor_targets: dict[str, float] = {}
        if entrada.sp is not None:
            for cv_id, _peso in self._cv_anchors:
                if cv_id not in entrada.sp:
                    continue
                low, high = self._row_limits[cv_id]
                anchor_targets[cv_id] = min(max(entrada.sp[cv_id], low), high)

        kept = list(model.row_ids)
        given_up: list[str] = []
        while True:
            raw = self._solve_once(kept, cv_ss_free, bounds, quadratic, entrada, anchor_targets)
            if raw.status in ("optimal", "relaxed"):
                slacks = self._slacks(raw, kept)
                violated = [row_id for row_id in kept if slacks[row_id] > SLACK_TOL]
                if not violated:
                    return self._build_result(
                        raw, kept, given_up, cv_ss_free, dv_shift, entrada, anchor_targets
                    )
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
        """Detuning anti-flipping (ADR-027 §8): `ρ‖ΔMV − ΔMV_anterior‖²`.

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
        entrada: SstoInput,
        anchor_targets: dict[str, float],
    ) -> SolverResult:
        """LP/QP de UMA rodada, com o conjunto de linhas `kept` (ADR-027 §6).

        Layout de colunas, nesta ordem: `[ΔMV | s_kept | dev±_âncoras_CV | dev±_psv_MV |
        dev±_equalize]`. Linhas de `A_ub`: primeiro as `2·len(kept)` de limite de linha
        (as únicas que entram no loop de desistência), depois os pares das preferências —
        âncoras de CV, PSV de MV e equalize. Preferências NUNCA entram no loop de
        desistência: a folga `dev` absorve qualquer conflito, então elas não podem causar
        inviabilidade (são desejos, não limites).
        """
        model = self._model
        n_mv = len(model.mv_ids)
        n_slack = len(kept)
        row_index = {row_id: i for i, row_id in enumerate(model.row_ids)}

        anchors = [
            (cv_id, peso) for cv_id, peso in self._cv_anchors if cv_id in anchor_targets
        ]
        n_anchor = len(anchors)
        n_psv = len(self._mv_psv)
        n_eq_pairs = max(0, len(self._equalize_ids) - 1)

        n_dev = 2 * (n_anchor + n_psv + n_eq_pairs)
        n_col = n_mv + n_slack + n_dev
        n_pref_rows = 2 * (n_anchor + n_psv + n_eq_pairs)

        a_ub = np.zeros((2 * n_slack + n_pref_rows, n_col))
        b_ub = np.zeros(2 * n_slack + n_pref_rows)
        for k, row_id in enumerate(kept):
            i = row_index[row_id]
            low, high = self._row_limits[row_id]
            a_ub[2 * k, :n_mv] = model.g[i]
            a_ub[2 * k, n_mv + k] = -1.0
            b_ub[2 * k] = high - cv_ss_free[i]
            a_ub[2 * k + 1, :n_mv] = -model.g[i]
            a_ub[2 * k + 1, n_mv + k] = -1.0
            b_ub[2 * k + 1] = cv_ss_free[i] - low

        c = np.zeros(n_col)
        c[: n_mv + n_slack] = np.concatenate(
            [
                self._costs,
                np.array(
                    [self._economics.slack_weight * self._row_priority[row_id] for row_id in kept],
                    dtype=float,
                ),
            ]
        )

        col_dev = n_mv + n_slack
        row = 2 * n_slack

        # Âncora de CV (dev⁺/dev⁻ ≥ 0): `G_i·ΔMV − dev⁺ ≤ a_i − cv_ss_free_i` e simétrico.
        for cv_id, peso in anchors:
            i = row_index[cv_id]
            alvo = anchor_targets[cv_id]
            a_ub[row, :n_mv] = model.g[i]
            a_ub[row, col_dev] = -1.0
            b_ub[row] = alvo - cv_ss_free[i]
            a_ub[row + 1, :n_mv] = -model.g[i]
            a_ub[row + 1, col_dev + 1] = -1.0
            b_ub[row + 1] = cv_ss_free[i] - alvo
            c[col_dev] = c[col_dev + 1] = peso / self._row_span[cv_id]
            col_dev += 2
            row += 2

        # PSV de MV (dev⁺/dev⁻ ≥ 0): `Δu_j − dev⁺ ≤ psv_j − u_j` e simétrico.
        for mv_id, psv in self._mv_psv:
            j = model.mv_ids.index(mv_id)
            u_atual = entrada.u[mv_id]
            a_ub[row, j] = 1.0
            a_ub[row, col_dev] = -1.0
            b_ub[row] = psv - u_atual
            a_ub[row + 1, j] = -1.0
            a_ub[row + 1, col_dev + 1] = -1.0
            b_ub[row + 1] = u_atual - psv
            c[col_dev] = c[col_dev + 1] = W_PSV / self._mv_span[mv_id]
            col_dev += 2
            row += 2

        # Equalize: nível em fração da escala `(u + Δu − min)/span` igual entre os membros.
        # Para i = 2..k: `αᵢΔuᵢ − α₁Δu₁ − e⁺ ≤ rᵢ` com
        # `rᵢ = (u₁−min₁)/span₁ − (uᵢ−minᵢ)/spanᵢ`, e o simétrico com `e⁻`. Adimensional:
        # os dois lados são frações de escala, então o peso não divide por span.
        if n_eq_pairs > 0:
            ids = self._equalize_ids
            j1 = model.mv_ids.index(ids[0])
            u1, lo1 = entrada.u[ids[0]], self._mv_limits[ids[0]][0]
            alfa1 = 1.0 / self._mv_span[ids[0]]
            frac1 = (u1 - lo1) * alfa1
            for outro in ids[1:]:
                ji = model.mv_ids.index(outro)
                ui, loi = entrada.u[outro], self._mv_limits[outro][0]
                alfai = 1.0 / self._mv_span[outro]
                residuo = frac1 - (ui - loi) * alfai
                a_ub[row, ji] = alfai
                a_ub[row, j1] = -alfa1
                a_ub[row, col_dev] = -1.0
                b_ub[row] = residuo
                a_ub[row + 1, ji] = -alfai
                a_ub[row + 1, j1] = alfa1
                a_ub[row + 1, col_dev + 1] = -1.0
                b_ub[row + 1] = -residuo
                c[col_dev] = c[col_dev + 1] = W_EQUALIZE
                col_dev += 2
                row += 2

        full_bounds = (*bounds, *(((0.0, None),) * (n_slack + n_dev)))
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
        anchor_targets: dict[str, float],
    ) -> SstoResult:
        model = self._model
        n_mv = len(model.mv_ids)
        delta = np.asarray(raw.x[:n_mv], dtype=float)
        targets = cv_ss_free + model.g @ delta

        slacks = dict.fromkeys(model.row_ids, 0.0)
        slacks.update(self._slacks(raw, kept))

        labels = self._constraint_labels(kept, set(anchor_targets))
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

    def _constraint_labels(self, kept: list[str], anchor_ids: set[str]) -> list[str]:
        """Rótulo por linha de `A_ub`, na MESMA ordem em que foram montadas em `_solve_once`:
        limites de linha (`kept`), depois âncoras de CV (só as presentes neste solve — SP
        ausente pula a âncora), PSV de MV e equalize."""
        labels: list[str] = []
        for row_id in kept:
            labels.append(f"{row_id}:high")
            labels.append(f"{row_id}:low")
        for cv_id, _peso in self._cv_anchors:
            if cv_id not in anchor_ids:
                continue
            labels.append(f"{cv_id}:anchor_high")
            labels.append(f"{cv_id}:anchor_low")
        for mv_id, _psv in self._mv_psv:
            labels.append(f"{mv_id}:psv_high")
            labels.append(f"{mv_id}:psv_low")
        if len(self._equalize_ids) > 1:
            primeiro = self._equalize_ids[0]
            for outro in self._equalize_ids[1:]:
                labels.append(f"eq:{primeiro}:{outro}:high")
                labels.append(f"eq:{primeiro}:{outro}:low")
        return labels
