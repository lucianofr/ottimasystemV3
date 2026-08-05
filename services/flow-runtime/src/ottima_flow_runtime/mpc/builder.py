"""Montagem do-mpc do bloco MPC (spec F4 §3.2-3.5; TDD estrito).

`build_mpc` monta o `Model('discrete')` + `MPC` do do-mpc a partir de `MpcConfig`: agregação
LTI bloco-diagonal por par habilitado (`discretize_sopdt`/`discretize_iopdt`, tarefa 2.1),
atraso como shift register na entrada de cada par, estado aumentado `u_prev` por MV (Δu duro
e Nc — o do-mpc não tem horizonte de controle nativo, spec §3.5), DVs/bias/SP como `_tvp`
(constantes no horizonte a cada execução) e `du_max` por passo como `_tvp` HORIZONTE-VARIANTE
(mesmo mecanismo de constraint por passo do do-mpc, usado para materializar Δu≡0 para k≥Nc sem
tocar API privada).

Objetivo normalizado por span, com slack dominante por construção (spec §3.4, ADR-019):
Restrição vence CV porque `w_slack` é ordens de grandeza maior que `w_cv`, nunca o contrário.

Estado interno de execução (x, bias "vigente", u_prev "vigente", warm start) é do worker
(F4b/2.3-2.4) — este módulo só monta o controller e devolve os nomes/índices que o worker
precisa para escrever nele a cada execução (via `BuiltMpc.tvp_template`, mutável).
"""

from dataclasses import dataclass

import casadi as ca
import casadi.tools as castools
from do_mpc.controller import MPC
from do_mpc.model import Model

from ottima_core.flowgraph import Horizons, MpcConfig, derive_horizons

from .discretize import discretize_iopdt, discretize_sopdt

R_DELTA_U = 0.1
"""Peso do termo `R_Δu·Δu²_norm` do objetivo (spec F4 §3.4) — constante nomeada: a spec fixa
o valor, não é ajustável por bloco (não há aba de config para isso)."""

SLACK_WEIGHT_MULTIPLIER = 1e4
"""Multiplicador de `w_slack = 1e4 × max(w_cv, 1.0) × priority` (spec F4 §3.4, ADR-019) — a
dominância da Restrição sobre o CV é por construção: precisa ser grande o bastante para que
QUALQUER violação de faixa custe mais que o pior erro de SP possível."""


@dataclass(frozen=True, slots=True, eq=False)
class BuiltMpc:
    """Controller do-mpc pronto + metadados de índice para o worker (spec F4 §3, §5.1).

    `mpc`: controller já com `.setup()` chamado — pronto para `x0`/`set_initial_guess`/
    `make_step`. Estado (x, bias "vigente", u_prev "vigente", warm start) é do worker.

    `tvp_template`: struct MUTÁVEL do do-mpc (`get_tvp_template`). O padrão de `du_max` por
    passo (Δu duro + Nc, spec §3.5) já vem preenchido pelo builder — é dado de config, nunca
    muda em runtime. O worker escreve `sp_tvp_name`/`bias_tvp_name`/`dv_tvp_name` NESSE MESMO
    objeto antes de cada `make_step`; `set_tvp_fun` sempre devolve a mesma referência, então a
    escrita fica visível na próxima chamada sem recriar o modelo.

    `eq=False`: `tvp_template` é uma struct do CasADi — `==` entre duas instâncias não devolve
    um `bool` (mesmo motivo do `PairSS(eq=False)` em `discretize.py`).
    """

    mpc: MPC
    horizons: Horizons
    prediction_rows: tuple[str, ...]
    """Ordem das linhas de predição: CVs (ordem do config) depois Restrições (spec §5.1)."""
    mv_order: tuple[str, ...]
    """Ordem das MVs (ordem do config, spec §5.1) — também a ordem real em `model.u`."""
    output_index: dict[str, int]
    """var_id (CV/Restrição) -> posição em `prediction_rows`."""
    input_index: dict[str, int]
    """var_id (MV) -> posição em `mv_order`."""
    spans: dict[str, float]
    """var_id (CV/Restrição/MV) -> span de normalização (spec §3.4)."""
    u_prev_state_name: dict[str, str]
    """mv_id -> nome do estado `u_prev` aumentado (init bumpless, tarefa 2.3)."""
    output_expr_name: dict[str, str]
    """row_id (CV/Restrição) -> nome da expressão aux `y` agregada (`model.aux[...]`)."""
    sp_tvp_name: dict[str, str]
    """cv_id -> nome do `_tvp` de SP (escrito pelo worker em `tvp_template`)."""
    bias_tvp_name: dict[str, str]
    """row_id (CV/Restrição) -> nome do `_tvp` de bias (escrito pelo worker, DMC §3.3)."""
    dv_tvp_name: dict[str, str]
    """dv_id -> nome do `_tvp` de DV (escrito pelo worker; futura = último valor medido)."""
    tvp_template: castools.structure3.DMStruct


def build_mpc(config: MpcConfig, ts_flow: float) -> BuiltMpc:
    """Monta o `do_mpc.controller.MPC` do bloco (spec F4 §3.2-3.5)."""
    cvs = config.variables.cvs
    constraints = config.variables.constraints
    mvs = config.variables.mvs
    dvs = config.variables.dvs

    row_ids = [v.id for v in (*cvs, *constraints)]
    row_kind = {v.id: v.kind for v in (*cvs, *constraints)}

    horizons = derive_horizons(config.multiplier, ts_flow, [v.tss for v in (*cvs, *constraints)])
    ts_mpc = horizons.ts_mpc

    model = Model("discrete")

    mv_symbol = {mv.id: model.set_variable("_u", mv.id) for mv in mvs}
    dv_symbol = {dv.id: model.set_variable("_tvp", dv.id) for dv in dvs}
    col_symbol = {**mv_symbol, **dv_symbol}
    bias_symbol = {row_id: model.set_variable("_tvp", f"bias_{row_id}") for row_id in row_ids}
    for cv in cvs:
        model.set_variable("_tvp", f"sp_{cv.id}")
    for mv in mvs:
        model.set_variable("_tvp", f"dumax_{mv.id}")
    for co in constraints:
        model.set_variable("_u", f"slack_{co.id}")
    for mv in mvs:
        model.set_variable("_x", f"uprev_{mv.id}")

    rhs: dict[str, ca.SX] = {f"uprev_{mv.id}": mv_symbol[mv.id] for mv in mvs}
    output_expr_name: dict[str, str] = {}

    for row_id in row_ids:
        kind = row_kind[row_id]
        row_expr = 0
        for col_id, pair_cfg in config.models.get(row_id, {}).items():
            if not pair_cfg.enabled:
                continue
            params = pair_cfg.params
            if kind == "selfreg":
                pair = discretize_sopdt(
                    params["K"], params["tau1"], params["tau2"], params["theta"], ts_mpc
                )
            else:
                pair = discretize_iopdt(params["Ki"], params["theta"], ts_mpc)

            pair_input = col_symbol[col_id]
            for i in range(1, pair.delay + 1):
                name = f"delay_{row_id}_{col_id}_{i}"
                state = model.set_variable("_x", name)
                rhs[name] = pair_input
                pair_input = state

            n = pair.a.shape[0]
            if n == 0:
                # Só ocorre para `selfreg` (SOPDT): os dois estágios abaixo do limiar
                # `Ts/DIRECT_PASS_RATIO` simultaneamente (carryover da tarefa 2.1 — IOPDT
                # nunca degenera, `discretize_iopdt` sempre devolve 1 estado). `PairSS` sem
                # termo direto não representa esse ganho puro (`y=c@x=0` sempre); o ganho
                # entra aqui como alimentação direta na saída agregada da linha.
                row_expr += params["K"] * pair_input
                continue

            names = [f"x_{row_id}_{col_id}_{i}" for i in range(n)]
            state_syms = [model.set_variable("_x", name) for name in names]
            x_vec = ca.vertcat(*state_syms)
            x_next = pair.a @ x_vec + pair.b * pair_input
            for i, name in enumerate(names):
                rhs[name] = x_next[i]
            row_expr += (pair.c @ x_vec)[0]

        output_expr_name[row_id] = f"y_{row_id}"
        model.set_expression(f"y_{row_id}", row_expr + bias_symbol[row_id])

    for name, expr in rhs.items():
        model.set_rhs(name, expr)

    model.setup()

    mpc = MPC(model)
    mpc.settings.n_horizon = horizons.np
    mpc.settings.t_step = horizons.ts_mpc
    mpc.settings.n_robust = 0
    mpc.settings.supress_ipopt_output()

    spans: dict[str, float] = {}
    for cv in cvs:
        spans[cv.id] = cv.sp_limits.max - cv.sp_limits.min
    for co in constraints:
        spans[co.id] = co.range.high - co.range.low
    for mv in mvs:
        spans[mv.id] = mv.limits.max - mv.limits.min

    max_w_cv = max((cv.weight for cv in cvs), default=1.0)

    cv_cost = ca.DM(0)
    for cv in cvs:
        y = model.aux[f"y_{cv.id}"]
        sp = model.tvp[f"sp_{cv.id}"]
        cv_cost = cv_cost + cv.weight * ((y - sp) / spans[cv.id]) ** 2

    slack_cost = ca.DM(0)
    for co in constraints:
        s = model.u[f"slack_{co.id}"]
        w_slack = SLACK_WEIGHT_MULTIPLIER * max_w_cv * co.priority
        slack_cost = slack_cost + w_slack * (s / spans[co.id]) ** 2

    du_cost = ca.DM(0)
    for mv in mvs:
        u = model.u[mv.id]
        uprev = model.x[f"uprev_{mv.id}"]
        du_cost = du_cost + R_DELTA_U * ((u - uprev) / spans[mv.id]) ** 2

    mpc.set_objective(mterm=cv_cost, lterm=cv_cost + slack_cost + du_cost)

    for mv in mvs:
        mpc.bounds["lower", "_u", mv.id] = mv.limits.min
        mpc.bounds["upper", "_u", mv.id] = mv.limits.max

        u = model.u[mv.id]
        uprev = model.x[f"uprev_{mv.id}"]
        dumax = model.tvp[f"dumax_{mv.id}"]
        mpc.set_nl_cons(f"du_pos_{mv.id}", u - uprev - dumax, ub=0.0)
        mpc.set_nl_cons(f"du_neg_{mv.id}", -(u - uprev) - dumax, ub=0.0)

    for co in constraints:
        mpc.bounds["lower", "_u", f"slack_{co.id}"] = 0.0

        y = model.aux[f"y_{co.id}"]
        s = model.u[f"slack_{co.id}"]
        mpc.set_nl_cons(f"range_hi_{co.id}", y - co.range.high - s, ub=0.0)
        mpc.set_nl_cons(f"range_lo_{co.id}", co.range.low - y - s, ub=0.0)

    tvp_template = mpc.get_tvp_template()
    for mv in mvs:
        name = f"dumax_{mv.id}"
        for k in range(horizons.np + 1):
            tvp_template["_tvp", k, name] = mv.du_max if k < horizons.nc else 0.0
    mpc.set_tvp_fun(lambda _t_now: tvp_template)

    mpc.setup()

    cv_ids = tuple(cv.id for cv in cvs)
    co_ids = tuple(co.id for co in constraints)
    prediction_rows = cv_ids + co_ids
    mv_order = tuple(mv.id for mv in mvs)

    return BuiltMpc(
        mpc=mpc,
        horizons=horizons,
        prediction_rows=prediction_rows,
        mv_order=mv_order,
        output_index={var_id: i for i, var_id in enumerate(prediction_rows)},
        input_index={var_id: i for i, var_id in enumerate(mv_order)},
        spans=spans,
        u_prev_state_name={mv.id: f"uprev_{mv.id}" for mv in mvs},
        output_expr_name=output_expr_name,
        sp_tvp_name={cv.id: f"sp_{cv.id}" for cv in cvs},
        bias_tvp_name={row_id: f"bias_{row_id}" for row_id in row_ids},
        dv_tvp_name={dv.id: dv.id for dv in dvs},
        tvp_template=tvp_template,
    )
