"""Worker do MPC — processo filho dedicado por bloco (spec F4 §3.3/§3.6/§4.9/§5.1; ADR-004).

`worker_main` é o alvo do `spawn` (decisão A-3): monta o `do_mpc.controller.MPC` a partir do
`MpcConfig` recebido como JSON (o controller não é picklável — por isso o build acontece NO
filho, nunca no pai) e entra num laço `conn.recv()` respondendo `SolveRequest` -> `SolveResult`.
Nada aqui assume `asyncio` — é o escape hatch do event loop, mesmo espírito do
`script_pool._worker_main` (RF-511..514, ADR-018/004, F3 decisão A-4), mas SEM pool: a
tarefa 1.2 (fora deste módulo) é quem sobe/mata/reaproveita o processo.

Protocolo pelo `Pipe` duplex:
    1. Boot: `conn.send(("ready", n_x))` assim que o controller estiver pronto.
    2. Loop: cada mensagem recebida é uma `SolveRequest`; a resposta é sempre uma
       `SolveResult` (nunca uma exceção crua — `_handle` isola falhas por pedido, spec §4.9).
    3. `conn.recv()` devolvendo `None` ou o pipe fechando (EOF) encerra o laço.

Realimentação por bias (DMC, spec §3.3) — sem estimador de estados:
    A cada pedido SEM `reinit`, o worker propaga o modelo em malha aberta com o `u`
    EFETIVAMENTE aplicado (nunca o plano do próprio MPC) via `do_mpc.simulator.Simulator`
    (mesma classe que o do-mpc usa para simular modelos discretos — `Simulator.setup`
    resolve `model._rhs_fun` internamente para `model_type == 'discrete'`; usar a classe
    pública em vez de tocar `_rhs_fun` aqui mantém o worker na API documentada do do-mpc).
    Com o `x` recém-propagado, `bias := y_medido − C·x` por linha (CV/Restrição): `C·x` é a
    própria expressão `y_{row_id}` do modelo (builder.py, aux `model.aux[...]`) avaliada com
    o `_tvp` de bias zerado — mesmo truque de avaliação direta via `casadi.Function` que
    `test_mpc_bumpless.py` usa em `_y_pred_t0`, só que aqui embrulhado numa função reutilizável
    por request. `SP`/`DV` (constantes no horizonte, DV futura = último valor medido) são
    escritos no `tvp_template` do MPC em TODO pedido — `init_bumpless` só escreve bias.

    Com `reinit=True` (MAN->AUTO, respawn, rebuild — spec §3.6), o worker chama
    `init_bumpless` ANTES do solve: ele já cobre bias + x + `set_initial_guess`, então o
    worker só sincroniza o próprio estado de propagação (`x_current`) com o que o bumpless
    armou, para que o PRÓXIMO pedido sem `reinit` propague a partir do lugar certo.

Predição (spec §5.1) — `t = [0, Ts_mpc, ..., Np*Ts_mpc]` (Np+1 pontos):
    CV/Restrição: `y_{row_id}` avaliada em CADA passo do horizonte via
    `mpc.opt_x_num['_x', k, 0, -1]` (estado previsto no passo k — mesmo acessor do teste de
    `du_max`/`Nc` em `test_mpc_builder.py`, com `-1` de índice de colocação: modelo discreto
    sem colocação, único ponto) e `mpc.opt_x_num['_u', k, 0]` (decisão no passo k); o ponto
    terminal (`k=Np`) não tem `u_Np` decidido — reusa `u_{Np-1}` (a MV não muda depois de
    `Nc`, `Δu≡0` por construção do builder, spec §3.5, então isso é exato, não aproximado,
    sempre que `Nc < Np`; nos casos-limite com `Nc == Np` é a MV do último passo decidido,
    igual ao que o plano físico realmente aplicaria dali em diante).
    MV: primeiro ponto = `u_prev` vigente em `x0` (estado `uprev_{mv_id}`, o valor que ESTAVA
    em vigor entrando neste ciclo); os demais Np pontos = `mpc.opt_x_num['_u', k, 0, mv_id]`
    — mesmo padrão de `_mv_plan` em `test_mpc_builder.py`, generalizado do repouso (`u_-1=0`)
    para o `u_prev` real do ciclo.

Custo: `mpc.nlp['f']` é a MESMA expressão simbólica passada ao `nlpsol` interno do do-mpc
    (`do_mpc.optimizer.Optimizer.solve`, `self.nlp = {'x': ..., 'f': self._nlp_obj, ...}`);
    avaliada em `(mpc.opt_x_num, mpc.opt_p_num)` (a solução e os parâmetros exatos do solve
    que acabou de rodar) reproduz o mesmo valor que o solver devolveria em `r['f']` — do-mpc
    não expõe esse valor como atributo público, então a `casadi.Function` construída uma vez
    no boot é o jeito de recuperá-lo sem reimplementar a soma dos termos do objetivo.
"""

from __future__ import annotations

import logging
import time
import traceback
import uuid
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import TYPE_CHECKING, Final

import casadi as ca
import casadi.tools as castools
from do_mpc.simulator import Simulator

from ottima_core.bus import SstoRun
from ottima_core.flowgraph import CvVar, MpcConfig, gain_model_hash

from .builder import BuiltMpc, build_mpc
from .bumpless import init_bumpless

if TYPE_CHECKING:
    # Import só de tipo: `target_calculation` puxa `scipy.optimize`, e o boot do worker é
    # caminho crítico do arme (spec §3.6). Bloco com `economics` desligado — a maioria —
    # não paga esse import; quem paga é `_build_runtime`, sob demanda.
    from ..target_calculation.ssto import SstoResult, SteadyStateOptimizer

logger = logging.getLogger(__name__)

_READY: Final[str] = "ready"


@dataclass(frozen=True)
class SolveRequest:
    """Pedido de solve — picklável (cruza o `Pipe`, spec F4b §Interfaces internas)."""

    y: dict[str, float]
    u_applied: dict[str, float]
    d: dict[str, float]
    sp: dict[str, float]
    reinit: bool


@dataclass(frozen=True)
class SolveResult:
    """Resposta de solve — picklável. Ordem das linhas de `prediction_cv`/`prediction_mv`
    é `built.prediction_rows`/`built.mv_order` (CVs depois Restrições, ordem do config; MVs
    na ordem do config — spec §5.1)."""

    u_plan: dict[str, float]
    prediction_t: list[float]
    prediction_cv: list[list[float]]
    prediction_mv: list[list[float]]
    cost: float
    status: str
    wall_ms: float
    detail: str = ""
    ssto: SstoRun | None = None
    """Registro da execução do SSTO deste ciclo (ADR-027 §11), quando a camada rodou.
    `None` = SSTO desligado neste bloco ou falha isolada antes de produzir registro."""


@dataclass(slots=True)
class _Runtime:
    """Estado vivo do worker entre execuções — nunca cruza o `Pipe` (só `SolveResult` cruza).

    `sim_tvp`: struct MUTÁVEL do `Simulator` (mesmo padrão de `built.tvp_template` no
    builder — `set_tvp_fun` sempre devolve a mesma referência). Só carrega DVs: bias/SP/dumax
    não entram no `rhs` do modelo (só em aux/custo/restrições), então ficam sempre zerados
    aqui — o que é exatamente o que a avaliação de `C·x` do bias precisa (ver `_write_bias`).
    `x_current`: estado agregado vigente (DM achatado, compatível com `mpc.make_step` e com
    `Simulator.x0`) — a mesma variável serve de x0 do MPC e de x0 do propagador.
    `du_min`: mv_id -> banda morta do atuador (`MvVar.du_min`), lida uma vez no boot — a
    quantização pós-solve (`_aplicar_banda_morta`, TD-007) é a única consumidora.
    """

    built: BuiltMpc
    simulator: Simulator
    sim_tvp: castools.structure3.DMStruct
    row_fun: dict[str, ca.Function]
    cost_fun: ca.Function
    x_current: ca.DM
    du_min: dict[str, float]
    ssto: SteadyStateOptimizer | None = None
    """Camada de alvos (ADR-027). `None` = `economics` ausente/desligado ⇒ caminho da F4."""
    cvs: tuple[CvVar, ...] = ()
    """CVs do config — o SSTO só entrega alvo de NÍVEL para as `selfreg` (ADR-027 §4), e o
    clamp final usa `sp_limits`."""
    model_hash: str = ""
    ssto_dv_prev: dict[str, float] | None = None
    """DV da execução anterior do SSTO: âncora do `ΔDV` do ciclo (ADR-027 §2)."""
    ssto_delta_prev: dict[str, float] | None = None
    """ΔMV da execução anterior: referência do detuning anti-flipping (ADR-027 §8)."""


def _build_runtime(config: MpcConfig, ts_flow: float) -> _Runtime:
    """Boot: monta o controller + o propagador + as funções de avaliação reutilizadas em
    todo pedido (uma `casadi.Function` por linha de predição, mais o custo)."""
    built = build_mpc(config, ts_flow)
    model = built.mpc.model

    row_fun = {
        row_id: ca.Function(
            f"y_{row_id}",
            [model.x, model.u, model.z, model.tvp, model.p],
            [model.aux[built.output_expr_name[row_id]]],
        )
        for row_id in built.prediction_rows
    }
    cost_fun = ca.Function("cost", [built.mpc.opt_x, built.mpc.opt_p], [built.mpc.nlp["f"]])

    simulator = Simulator(model)
    simulator.settings.t_step = built.horizons.ts_mpc
    sim_tvp = model.tvp(0.0)
    simulator.set_tvp_fun(lambda _t_now: sim_tvp)
    simulator.setup()

    # Guia o `x0` de repouso como estado/chute inicial do MPC: sem isto, o PRIMEIRO
    # `make_step` sem `reinit` prévio acha o `set_initial_guess` nunca chamado e o do-mpc
    # entra num `time.sleep(5)` de aviso (`_mpc.py`) — 5s por ciclo estouraria QUALQUER
    # orçamento de solve (RF-606/624). `reinit=True` sempre re-arma via `init_bumpless`
    # (que já chama `set_initial_guess`), então isto só importa para o caso-limite do
    # primeiro pedido chegar sem `reinit`.
    built.mpc.x0 = model.x(0.0)
    built.mpc.set_initial_guess()

    economics = config.economics
    ssto = None
    if economics is not None and economics.enabled:
        from ..target_calculation.ssto import SteadyStateOptimizer

        ssto = SteadyStateOptimizer(config, built.horizons.ts_mpc)

    return _Runtime(
        built=built,
        simulator=simulator,
        sim_tvp=sim_tvp,
        row_fun=row_fun,
        cost_fun=cost_fun,
        x_current=model.x(0.0).cat,
        du_min={mv.id: mv.du_min for mv in config.variables.mvs},
        ssto=ssto,
        cvs=tuple(config.variables.cvs),
        model_hash=gain_model_hash(config),
    )


def _propagate(
    runtime: _Runtime, request: SolveRequest
) -> tuple[ca.DM, castools.structure3.DMStruct]:
    """Propaga o modelo em malha aberta com `u_applied` (spec §3.3) via `Simulator.make_step`
    — devolve o novo `x` (achatado) e o `_u` usado (para a avaliação de bias em seguida)."""
    model = runtime.built.mpc.model
    for dv_id, tvp_name in runtime.built.dv_tvp_name.items():
        runtime.sim_tvp[tvp_name] = request.d[dv_id]

    u0 = model.u(0.0)
    for mv_id in runtime.built.mv_order:
        u0[mv_id] = request.u_applied[mv_id]

    runtime.simulator.x0 = runtime.x_current
    runtime.simulator.make_step(u0)
    return runtime.simulator.x0.cat, u0


def _write_bias(
    runtime: _Runtime, request: SolveRequest, x: ca.DM, u0: castools.structure3.DMStruct
) -> None:
    """`bias := y_medido − C·x` por linha (spec §3.3), escrito em TODO o horizonte do
    `tvp_template` do MPC (mesmo padrão de `init_bumpless`, builder.py)."""
    model = runtime.built.mpc.model
    z0 = model.z(0.0)
    p0 = model.p(0.0)
    for row_id, bias_name in runtime.built.bias_tvp_name.items():
        c_dot_x = float(runtime.row_fun[row_id](x, u0, z0, runtime.sim_tvp, p0))
        bias = request.y[row_id] - c_dot_x
        runtime.built.tvp_template["_tvp", :, bias_name] = bias


def _apply_tvp(built: BuiltMpc, request: SolveRequest, sp: dict[str, float]) -> None:
    """SP e DV (constantes no horizonte, spec §3.2/§3.4) — escritos em TODO pedido, mesmo em
    `reinit` (`init_bumpless` só escreve `bias`, nunca SP/DV).

    `sp` é o SP EFETIVO do ciclo: o alvo do SSTO quando a camada rodou, o SP do operador no
    fallback (ADR-027 §10). Único ponto do worker que a camada econômica toca.
    """
    for cv_id, tvp_name in built.sp_tvp_name.items():
        built.tvp_template["_tvp", :, tvp_name] = sp[cv_id]
    for dv_id, tvp_name in built.dv_tvp_name.items():
        built.tvp_template["_tvp", :, tvp_name] = request.d[dv_id]


def _current_bias(runtime: _Runtime) -> dict[str, float]:
    """Bias vigente por linha, lido do `tvp_template` DEPOIS do passo de realimentação.

    Serve tanto ao caminho normal (`_write_bias`) quanto ao `reinit` (`init_bumpless`
    escreve o bias por dentro): ler do template é o único jeito de o SSTO enxergar o mesmo
    número que o controlador vai usar, sem duplicar o cálculo.
    """
    return {
        row_id: float(runtime.built.tvp_template["_tvp", 0, bias_name])
        for row_id, bias_name in runtime.built.bias_tvp_name.items()
    }


def _effective_sp(runtime: _Runtime, request: SolveRequest, result: SstoResult) -> dict[str, float]:
    """SP por CV: alvo do SSTO quando utilizável, SP do operador no resto (ADR-027 §10).

    Fica com o SP do operador quando:
    - o SSTO não fechou (`infeasible`/`error`) — fallback, o dinâmico não para por isso;
    - a CV é `integrating` — ali o LP decide TAXA, não nível (ADR-027 §4); usar a taxa como
      SP seria erro de unidade.

    O clamp em `sp_limits` é defesa em profundidade: o LP já respeita a faixa, mas um alvo
    fora dela nunca pode chegar ao controlador (é a mesma faixa que `_command_sp` aplica ao
    SP manual).
    """
    if result.status not in ("optimal", "relaxed"):
        return dict(request.sp)
    sp: dict[str, float] = {}
    for cv in runtime.cvs:
        alvo = result.cv_target.get(cv.id)
        if cv.kind != "selfreg" or alvo is None:
            sp[cv.id] = request.sp[cv.id]
            continue
        sp[cv.id] = min(max(alvo, cv.sp_limits.min), cv.sp_limits.max)
    return sp


def _audit_record(
    runtime: _Runtime, request: SolveRequest, result: SstoResult, bias: dict[str, float]
) -> SstoRun:
    """Registro imutável da execução (ADR-027 §11) — viaja no `SolveResult` e sobe no
    `MpcState`, sem canal novo."""
    return SstoRun(
        run_id=str(uuid.uuid4()),
        config_hash=result.config_hash,
        model_hash=runtime.model_hash,
        status=result.status,
        solver=result.solver,
        solve_ms=result.solve_ms,
        objective=result.objective,
        mv=dict(request.u_applied),
        cv_ss=result.cv_ss_free,
        bias=bias,
        dv=dict(request.d),
        costs=result.costs,
        delta_mv=result.delta_mv,
        mv_target=result.mv_target,
        cv_target=result.cv_target,
        given_up=list(result.given_up),
        active_constraints=list(result.active_constraints),
        duals=result.duals,
    )


def _run_ssto(runtime: _Runtime, request: SolveRequest) -> tuple[dict[str, float], SstoRun | None]:
    """Camada de alvos do ciclo (ADR-027 §1): roda no MESMO ciclo, antes do `make_step`.

    Fronteira dura: qualquer falha inesperada do otimizador cai no SP do operador e o MPC
    dinâmico segue — a camada econômica nunca pode derrubar o controle.
    """
    if runtime.ssto is None:
        return dict(request.sp), None

    # Local: o módulo já está carregado (o otimizador existe), mas o import de topo é só de
    # tipo — ver a nota em `TYPE_CHECKING`.
    from ..target_calculation.ssto import SstoInput

    bias = _current_bias(runtime)
    try:
        result = runtime.ssto.solve(
            SstoInput(
                u=request.u_applied,
                d=request.d,
                d_prev=runtime.ssto_dv_prev,
                bias=bias,
                delta_mv_prev=runtime.ssto_delta_prev,
            )
        )
    except Exception:  # noqa: BLE001 - fronteira entre camadas: SSTO nunca derruba o MPC
        logger.exception("SSTO falhou; ciclo cai no SP do operador")
        return dict(request.sp), None

    runtime.ssto_dv_prev = dict(request.d)
    runtime.ssto_delta_prev = dict(result.delta_mv)
    return _effective_sp(runtime, request, result), _audit_record(runtime, request, result, bias)


def _extract_prediction(
    runtime: _Runtime,
) -> tuple[list[float], list[list[float]], list[list[float]]]:
    """`t`/`cv`/`mv` da predição (spec §5.1) — ver docstring do módulo para a convenção do
    ponto terminal (`k=Np`, sem `u_Np` decidido)."""
    built = runtime.built
    mpc = built.mpc
    n_p = built.horizons.np
    ts_mpc = built.horizons.ts_mpc
    t = [k * ts_mpc for k in range(n_p + 1)]

    z0 = mpc.model.z(0.0)
    p0 = mpc.model.p(0.0)
    prediction_cv: list[list[float]] = []
    for row_id in built.prediction_rows:
        f_row = runtime.row_fun[row_id]
        values: list[float] = []
        for k in range(n_p + 1):
            x_k = mpc.opt_x_num["_x", k, 0, -1]
            u_k = mpc.opt_x_num["_u", min(k, n_p - 1), 0]
            tvp_k = built.tvp_template["_tvp", k]
            values.append(float(f_row(x_k, u_k, z0, tvp_k, p0)))
        prediction_cv.append(values)

    prediction_mv: list[list[float]] = []
    for mv_id in built.mv_order:
        first = float(mpc.opt_x_num["_x", 0, 0, -1, built.u_prev_state_name[mv_id]])
        rest = [float(mpc.opt_x_num["_u", k, 0, mv_id]) for k in range(n_p)]
        prediction_mv.append([first, *rest])

    return t, prediction_cv, prediction_mv


def _aplicar_banda_morta(
    runtime: _Runtime, u_plan: dict[str, float], prediction_mv: list[list[float]]
) -> None:
    """Banda morta do atuador (`MvVar.du_min`, TD-007) — quantizada AQUI e só aqui: se o
    bloco também descartasse movimentos pequenos, o modelo interno (que já viu o Δu do
    solve) e o valor de fato escrito na planta divergiriam com o tempo.

    Movimento menor que `du_min` não é aplicado (a válvula não responderia mesmo): o
    primeiro passo do plano publicado (`u_plan[mv]`/`prediction_mv[k][1]`) volta a ser o
    `u_prev` vigente — o mesmo `registrador uprev_{mv}` que ancora o Δu do solve
    (`prediction_mv[k][0]`, `_extract_prediction`). Como esse registrador é recalculado a
    CADA pedido a partir do `u_applied` que o chamador reporta (nunca acumulado aqui), o
    valor quantizado devolvido agora É o `u_applied` do PRÓXIMO pedido — fechar o loop pela
    resposta é a única fonte de verdade, sem estado extra para o worker manter e derivar.

    A cauda da predição (`k >= 2`, índice `>= 2` de cada lista) fica como o solver
    devolveu: só o primeiro movimento é de fato aplicado (receding horizon) — requantizar
    a cauda equivaleria a resolver o solve de novo, o que o próximo ciclo já faz.
    """
    for i, mv_id in enumerate(runtime.built.mv_order):
        du_min = runtime.du_min[mv_id]
        if du_min <= 0.0:
            continue
        u_prev = prediction_mv[i][0]
        if abs(u_plan[mv_id] - u_prev) < du_min:
            u_plan[mv_id] = u_prev
            prediction_mv[i][1] = u_prev


def empty_result(*, status: str, detail: str = "", wall_ms: float) -> SolveResult:
    return SolveResult(
        u_plan={},
        prediction_t=[],
        prediction_cv=[],
        prediction_mv=[],
        cost=0.0,
        status=status,
        wall_ms=wall_ms,
        detail=detail,
    )


def _solve(runtime: _Runtime, request: SolveRequest) -> SolveResult:
    """Um ciclo completo de execução (spec §3.3/§3.6/§4.9): estado, solve cronometrado,
    extração da predição/custo."""
    built = runtime.built
    if request.reinit:
        init_bumpless(built, u_now=request.u_applied, y_now=request.y, d_now=request.d)
        runtime.x_current = built.mpc.x0.cat
    else:
        x_new, u0 = _propagate(runtime, request)
        _write_bias(runtime, request, x_new, u0)
        runtime.x_current = x_new

    # Ordem obrigatória (ADR-027 §1): bias atualizado -> SSTO -> `tvp` -> `make_step`. O
    # LP parte da predição já corrigida pela medida deste ciclo, nunca da anterior.
    sp, ssto_run = _run_ssto(runtime, request)
    _apply_tvp(built, request, sp)

    t0 = time.perf_counter()
    built.mpc.make_step(runtime.x_current)
    wall_ms = (time.perf_counter() - t0) * 1000.0

    success = bool(built.mpc.solver_stats.get("success", False))
    status = "ok" if success else "no_convergence"
    detail = "" if success else str(built.mpc.solver_stats.get("return_status") or "")

    u_plan = {mv_id: float(built.mpc.opt_x_num["_u", 0, 0, mv_id]) for mv_id in built.mv_order}
    prediction_t, prediction_cv, prediction_mv = _extract_prediction(runtime)
    _aplicar_banda_morta(runtime, u_plan, prediction_mv)
    cost = float(runtime.cost_fun(built.mpc.opt_x_num, built.mpc.opt_p_num))

    return SolveResult(
        u_plan=u_plan,
        prediction_t=prediction_t,
        prediction_cv=prediction_cv,
        prediction_mv=prediction_mv,
        cost=cost,
        status=status,
        wall_ms=wall_ms,
        detail=detail,
        ssto=ssto_run,
    )


def _handle(runtime: _Runtime, request: SolveRequest) -> SolveResult:
    """Isola falhas de UM pedido (spec: exceção no solve -> `status='error'`, worker segue
    vivo) — mesmo padrão de `script_pool._run_script`: `except Exception` amplo, nunca deixa
    o laço do worker morrer por um pedido malformado ou por uma falha do solver."""
    try:
        return _solve(runtime, request)
    except Exception as exc:  # noqa: BLE001 - fronteira do processo: nunca deixa o laço morrer
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return empty_result(status="error", detail=detail, wall_ms=0.0)


def worker_main(conn: Connection, config_json: str, ts_flow: float) -> None:
    """Alvo do `spawn` (nível de módulo: `spawn` precisa importá-lo, mesmo padrão de
    `script_pool._worker_main`). Nada aqui assume `asyncio` (ADR-004)."""
    config = MpcConfig.model_validate_json(config_json)
    runtime = _build_runtime(config, ts_flow)
    conn.send((_READY, runtime.built.mpc.model.n_x))
    try:
        while True:
            request = conn.recv()
            if request is None:
                return
            conn.send(_handle(runtime, request))
    except (EOFError, OSError, KeyboardInterrupt):
        return
    finally:
        conn.close()
