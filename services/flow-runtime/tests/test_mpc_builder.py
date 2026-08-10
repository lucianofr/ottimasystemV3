"""Contratos de `mpc.builder.build_mpc` — montagem do-mpc (spec F4 §3.2-3.5; TDD estrito).

Cobre a lista da brief da tarefa 2.2: dimensão do modelo agregado, Δu duro (saturação do
plano), Nc (bloqueio de movimentos), precedência Restrição>CV (ADR-019, RF-605 — o teste
central da fase) e bounds duros de MV nunca violados.
"""

import casadi as ca
import pytest
from do_mpc.simulator import Simulator

from ottima_core.flowgraph import MpcConfig, mpc_state_dimension
from ottima_flow_runtime.mpc.builder import BuiltMpc, build_mpc

# --------------------------------------------------------------------------------------
# Fixtures — configs mínimas via MpcConfig.model_validate (mesmo idioma de test_mpc_config.py)
# --------------------------------------------------------------------------------------


def _mv(
    id_: str,
    *,
    limits: tuple[float, float] = (0.0, 1000.0),
    du_max: float = 50.0,
    operating_point: float = 0.0,
) -> dict:
    return {
        "id": id_,
        "name": id_,
        "eu": "u",
        "limits": {"min": limits[0], "max": limits[1]},
        "du_max": du_max,
        "initial_value": 0.0,
        "operating_point": operating_point,
        "pid": None,
    }


def _cv(
    id_: str,
    *,
    kind: str = "selfreg",
    sp_limits: tuple[float, float] = (0.0, 200.0),
    tss: float = 50.0,
    weight: float = 1.0,
) -> dict:
    return {
        "id": id_,
        "name": id_,
        "eu": "y",
        "kind": kind,
        "tss": tss,
        "weight": weight,
        "sp_limits": {"min": sp_limits[0], "max": sp_limits[1]},
    }


def _co(
    id_: str,
    *,
    range_: tuple[float, float] = (-1000.0, 50.0),
    tss: float = 50.0,
    priority: int = 1,
) -> dict:
    return {
        "id": id_,
        "name": id_,
        "eu": "y",
        "kind": "selfreg",
        "tss": tss,
        "range": {"low": range_[0], "high": range_[1]},
        "priority": priority,
    }


def _dv(id_: str, *, operating_point: float = 0.0) -> dict:
    return {"id": id_, "name": id_, "eu": "d", "operating_point": operating_point}


def _par(K: float, tau1: float, tau2: float, theta: float) -> dict:
    """Par SOPDT bem acima do limiar `Ts/10` — nunca degenera (mpc_state_dimension assume 2
    estados fixos por par selfreg; degenerar quebraria a igualdade com o modelo montado)."""
    return {"enabled": True, "params": {"K": K, "tau1": tau1, "tau2": tau2, "theta": theta}}


def _par_integrating(Ki: float, theta: float) -> dict:
    return {"enabled": True, "params": {"Ki": Ki, "theta": theta}}


def _solve(built: BuiltMpc, *, sp: dict[str, float] | None = None) -> None:
    """Preenche SP no `tvp_template` (constante no horizonte) e roda 1 `make_step` a partir
    do repouso (x0 = 0 em todos os estados, inclusive `u_prev`)."""
    for cv_id, value in (sp or {}).items():
        built.tvp_template["_tvp", :, built.sp_tvp_name[cv_id]] = value

    mpc = built.mpc
    x0 = mpc.model.x(0.0)
    mpc.x0 = x0
    mpc.set_initial_guess()
    mpc.make_step(x0)
    assert mpc.solver_stats["success"], mpc.solver_stats.get("return_status")


# --------------------------------------------------------------------------------------
# Dimensões — nº de estados do modelo montado == mpc_state_dimension(config, ts_mpc)
# --------------------------------------------------------------------------------------


def test_dimensao_do_modelo_bate_com_mpc_state_dimension_2x2_com_theta():
    config = MpcConfig.model_validate(
        {
            "name": "2x2-theta",
            "multiplier": 5,
            "variables": {
                "mvs": [_mv("mv_1"), _mv("mv_2")],
                "cvs": [_cv("cv_1"), _cv("cv_2")],
                "constraints": [],
                "dvs": [],
            },
            "models": {
                "cv_1": {
                    "mv_1": _par(1.0, 20.0, 8.0, 10.0),
                    "mv_2": _par(1.0, 20.0, 8.0, 10.0),
                },
                "cv_2": {
                    "mv_1": _par(1.0, 20.0, 8.0, 10.0),
                    "mv_2": _par(1.0, 20.0, 8.0, 10.0),
                },
            },
        }
    )

    built = build_mpc(config, ts_flow=1.0)

    assert built.mpc.model.n_x == mpc_state_dimension(config, ts_mpc=built.horizons.ts_mpc)


def test_dimensao_do_modelo_bate_com_mpc_state_dimension_com_dv():
    config = MpcConfig.model_validate(
        {
            "name": "com-dv",
            "multiplier": 5,
            "variables": {
                "mvs": [_mv("mv_1")],
                "cvs": [_cv("cv_1")],
                "constraints": [],
                "dvs": [_dv("dv_1")],
            },
            "models": {
                "cv_1": {
                    "mv_1": _par(1.0, 20.0, 8.0, 0.0),
                    "dv_1": _par(1.0, 15.0, 6.0, 0.0),
                }
            },
        }
    )

    built = build_mpc(config, ts_flow=1.0)

    assert built.mpc.model.n_x == mpc_state_dimension(config, ts_mpc=built.horizons.ts_mpc)


# --------------------------------------------------------------------------------------
# Δu duro + Nc — degrau de SP grande, sem Restrição nem DV
# --------------------------------------------------------------------------------------


def _du_config() -> MpcConfig:
    return MpcConfig.model_validate(
        {
            "name": "du-nc",
            "multiplier": 5,
            "variables": {
                "mvs": [_mv("mv_1", limits=(0.0, 1000.0), du_max=0.1)],
                "cvs": [_cv("cv_1", sp_limits=(0.0, 2000.0), tss=50.0)],
                "constraints": [],
                "dvs": [],
            },
            "models": {"cv_1": {"mv_1": _par(1.0, 20.0, 8.0, 0.0)}},
        }
    )


def _mv_plan(built: BuiltMpc, mv_id: str) -> list[float]:
    """Plano completo de MV (u_{-1}=0 do x0 de repouso, seguido de u_0..u_{Np-1})."""
    controller = built.mpc
    return [0.0] + [
        float(controller.opt_x_num["_u", k, 0, mv_id]) for k in range(built.horizons.np)
    ]


def test_du_max_satura_o_plano_de_mv():
    built = build_mpc(_du_config(), ts_flow=1.0)
    _solve(built, sp={"cv_1": 2000.0})

    plan = _mv_plan(built, "mv_1")
    du_max = 0.1
    deltas = [plan[k + 1] - plan[k] for k in range(built.horizons.np)]

    # nenhum passo do plano viola o Δu duro (RF-604) — a primeira MV dista <= du_max do
    # inicial, e cada passo seguinte também.
    for delta in deltas:
        assert delta <= du_max + 1e-6

    # SP inalcançável em poucos passos de 0.1 -> o otimizador satura o(s) primeiro(s)
    # movimento(s) livre(s) (k < Nc) no teto duro, provando que o Δu é de fato ativo.
    assert deltas[0] == pytest.approx(du_max, abs=1e-4)


def test_nc_bloqueia_movimento_apos_nc_passos():
    built = build_mpc(_du_config(), ts_flow=1.0)
    _solve(built, sp={"cv_1": 2000.0})

    plan = _mv_plan(built, "mv_1")
    nc = built.horizons.nc

    for k in range(nc, built.horizons.np):
        assert plan[k + 1] == pytest.approx(plan[k], abs=1e-6)


# --------------------------------------------------------------------------------------
# Precedência (ADR-019, RF-605) — o teste central da fase
# --------------------------------------------------------------------------------------


def _precedence_config() -> MpcConfig:
    """1 MV aciona CV (ganho 1) e Restrição (ganho 2) em paralelo. SP do CV (60) só é
    alcançável em `u=60`, mas a esse `u` a Restrição (faixa até 50) já estaria em `y=120`
    -- a faixa satura bem antes (`u=25` -> `y_co=50`), deixando o CV bem abaixo do SP."""
    return MpcConfig.model_validate(
        {
            "name": "precedencia",
            "multiplier": 5,
            "variables": {
                "mvs": [_mv("mv_1", limits=(0.0, 1000.0), du_max=10.0)],
                "cvs": [_cv("cv_1", sp_limits=(0.0, 1000.0), tss=50.0, weight=1.0)],
                "constraints": [_co("co_1", range_=(-1000.0, 50.0), tss=50.0, priority=1)],
                "dvs": [],
            },
            "models": {
                "cv_1": {"mv_1": _par(1.0, 20.0, 8.0, 0.0)},
                "co_1": {"mv_1": _par(2.0, 15.0, 6.0, 0.0)},
            },
        }
    )


def test_precedencia_restricao_vence_cv():
    built = build_mpc(_precedence_config(), ts_flow=1.0)
    _solve(built, sp={"cv_1": 60.0})

    controller = built.mpc
    np_ = built.horizons.np

    slack_name = "slack_co_1"
    slacks = [float(controller.opt_x_num["_u", k, 0, slack_name]) for k in range(np_)]
    assert max(slacks) == pytest.approx(0.0, abs=0.1)

    y_cv_final = float(controller.opt_aux_num["_aux", np_ - 1, 0, "y_cv_1"])
    sp_error = 60.0 - y_cv_final
    assert sp_error > 10.0


# --------------------------------------------------------------------------------------
# Bounds duros de MV — nunca violados mesmo com SP extremo
# --------------------------------------------------------------------------------------


def test_bounds_duros_de_mv_nunca_violados_com_sp_extremo():
    config = MpcConfig.model_validate(
        {
            "name": "bounds",
            "multiplier": 5,
            "variables": {
                "mvs": [_mv("mv_1", limits=(0.0, 10.0), du_max=5.0)],
                "cvs": [_cv("cv_1", sp_limits=(0.0, 1e7), tss=50.0)],
                "constraints": [],
                "dvs": [],
            },
            "models": {"cv_1": {"mv_1": _par(1.0, 20.0, 8.0, 0.0)}},
        }
    )
    built = build_mpc(config, ts_flow=1.0)
    _solve(built, sp={"cv_1": 1e6})

    controller = built.mpc
    for k in range(built.horizons.np):
        u_k = float(controller.opt_x_num["_u", k, 0, "mv_1"])
        assert -1e-6 <= u_k <= 10.0 + 1e-6


# --------------------------------------------------------------------------------------
# Par puro-ganho (n=0) via coluna MV sem atraso — fix round 1 (revisão)
# --------------------------------------------------------------------------------------


def test_par_puro_ganho_via_mv_sem_atraso_nao_quebra_o_mterm():
    """SOPDT duplamente degenerado (τ1,τ2 << Ts/10) alimentando um CV por uma coluna MV sem
    atraso injeta um símbolo `_u` cru na saída da linha (`row_expr`). Essa saída alimenta o
    `mterm` do do-mpc (via `cv_cost`), cuja assinatura fixa é `[_x, _tvp, _p]` — sem `_u`.
    Reproduzia `RuntimeError: ... variables [mv_1] are free` em `set_objective` antes do fix.
    A config passa pela validação semântica (só exige K != 0, tau1 > 0, tau2 >= 0, theta >=
    0) — não é um caso rejeitado em 1.2."""
    config = MpcConfig.model_validate(
        {
            "name": "puro-ganho",
            "multiplier": 5,
            "variables": {
                "mvs": [_mv("mv_1")],
                "cvs": [_cv("cv_1")],
                "constraints": [],
                "dvs": [],
            },
            "models": {"cv_1": {"mv_1": _par(1.0, 0.01, 0.01, 0.0)}},
        }
    )

    built = build_mpc(config, ts_flow=1.0)

    assert built.mpc.model.n_x == 1  # só o u_prev da MV — o par n=0 não cria estado dinâmico

    _solve(built, sp={"cv_1": 10.0})


# --------------------------------------------------------------------------------------
# Ponto de operação por coluna (TD-003) — o modelo é incremental, a porta é absoluta
# --------------------------------------------------------------------------------------


def _propaga(built: BuiltMpc, *, u: dict[str, float], d: dict[str, float], passos: int) -> ca.DM:
    """Propaga o modelo agregado em malha aberta a partir do repouso, com entradas
    CONSTANTES — mesmo caminho do worker em produção (`mpc/worker.py::_propagate`)."""
    model = built.mpc.model
    simulator = Simulator(model)
    simulator.settings.t_step = built.horizons.ts_mpc
    sim_tvp = model.tvp(0.0)
    for dv_id, value in d.items():
        sim_tvp[dv_id] = value
    simulator.set_tvp_fun(lambda _t_now: sim_tvp)
    simulator.setup()

    u0 = model.u(0.0)
    for mv_id, value in u.items():
        u0[mv_id] = value
    simulator.x0 = model.x(0.0).cat
    for _ in range(passos):
        simulator.make_step(u0)
    return simulator.x0.cat


def _y_em(built: BuiltMpc, row_id: str, x: ca.DM, d: dict[str, float]) -> float:
    """Saída agregada da linha avaliada num `x` arbitrário, com bias zerado (`tvp` novo) —
    é a contribuição CRUA do modelo, sem a correção que mascararia o desvio de coordenada."""
    model = built.mpc.model
    tvp = model.tvp(0.0)
    for dv_id, value in d.items():
        tvp[dv_id] = value
    f = ca.Function(
        "y",
        [model.x, model.u, model.z, model.tvp, model.p],
        [model.aux[built.output_expr_name[row_id]]],
    )
    return float(f(x, model.u(0.0), model.z(0.0), tvp, model.p(0.0)))


def _config_integradora(*, mv_op: float = 0.0, dv_op: float | None = None) -> MpcConfig:
    dvs = [] if dv_op is None else [_dv("dv_1", operating_point=dv_op)]
    pares = {"mv_1": _par_integrating(0.01, 0.0)}
    if dv_op is not None:
        pares["dv_1"] = _par_integrating(0.02, 0.0)
    return MpcConfig.model_validate(
        {
            "name": "ponto-de-operacao",
            "multiplier": 5,
            "variables": {
                "mvs": [_mv("mv_1", limits=(0.0, 100.0), operating_point=mv_op)],
                "cvs": [_cv("cv_1", kind="integrating")],
                "constraints": [],
                "dvs": dvs,
            },
            "models": {"cv_1": pares},
        }
    )


def test_coluna_mv_parada_no_ponto_de_operacao_nao_deriva_a_linha_integradora():
    """O par IOPDT é incremental — `dy/dt = Ki·(u − u_op)`. Com a MV parada no ponto de
    operação do modelo, a linha não pode acumular taxa nenhuma. Lendo `u` cru, o modelo
    injeta `Ki·Ts·u_op` por passo e a predição desce (ou sobe) sozinha para sempre: é o
    TD-003, a razão pela qual o flow da campanha precisou somar constantes FORA do bloco."""
    u_op = 52.0
    built = build_mpc(_config_integradora(mv_op=u_op), ts_flow=1.0)

    x = _propaga(built, u={"mv_1": u_op}, d={}, passos=10)

    assert _y_em(built, "cv_1", x, d={}) == pytest.approx(0.0, abs=1e-9)


def test_coluna_dv_parada_no_ponto_de_operacao_nao_deriva_a_linha_integradora():
    """Mesma regra da MV para a coluna de distúrbio: a DV entra no modelo em desvio do
    ponto de operação, então a medida absoluta pode ser ligada direto ao bloco — sem
    Script de condicionamento antes da porta."""
    u_op, d_op = 52.0, 50.0
    built = build_mpc(_config_integradora(mv_op=u_op, dv_op=d_op), ts_flow=1.0)

    x = _propaga(built, u={"mv_1": u_op}, d={"dv_1": d_op}, passos=10)

    assert _y_em(built, "cv_1", x, d={"dv_1": d_op}) == pytest.approx(0.0, abs=1e-9)


def test_bounds_de_mv_permanecem_na_coordenada_absoluta_da_planta():
    """O ponto de operação é do MODELO, não da porta: `limits` continua sendo o curso
    físico do atuador, e o otimizador nunca pode planejar fora dele (aqui o SP extremo
    empurra a MV para cima, contra o teto de 100 %)."""
    built = build_mpc(_config_integradora(mv_op=52.0), ts_flow=1.0)

    _solve(built, sp={"cv_1": 1e6})

    # `bound_relax_factor` do IPOPT afrouxa o bound por ~1e-8 RELATIVO à escala da variável
    # (com limits até 100 %, ~1e-6 absoluto) — a folga do teste acompanha essa escala, senão
    # o assert mede o solver, não a coordenada.
    folga = 1e-6 * 100.0
    for k in range(built.horizons.np):
        u_k = float(built.mpc.opt_x_num["_u", k, 0, "mv_1"])
        assert -folga <= u_k <= 100.0 + folga
