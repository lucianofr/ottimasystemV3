"""Contratos de `mpc.init_bumpless` — arme/re-arme sem salto (spec F4 §3.6; TDD estrito).

Lista da brief da tarefa 2.3: pós-init a predição em t=0 bate na medida (selfreg E
integrador); a primeira MV do `make_step` dista <= `du_max` do valor vigente (os dois
kinds); bias corrige erro de ganho do modelo (offset absorvido em regime, planta simulada
no próprio teste).
"""

import casadi as ca
import pytest

from ottima_core.flowgraph import MpcConfig
from ottima_flow_runtime.mpc import BuiltMpc, build_mpc, init_bumpless

# --------------------------------------------------------------------------------------
# Fixtures — mesmo idioma de test_mpc_builder.py
# --------------------------------------------------------------------------------------


def _mv(id_: str, *, limits: tuple[float, float] = (0.0, 1000.0), du_max: float = 5.0) -> dict:
    return {
        "id": id_,
        "name": id_,
        "eu": "u",
        "limits": {"min": limits[0], "max": limits[1]},
        "du_max": du_max,
        "initial_value": 0.0,
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


def _par_selfreg(K: float, tau1: float, tau2: float, theta: float) -> dict:
    """Par SOPDT bem acima do limiar `Ts/10` — nunca degenera (mesma nota do
    test_mpc_builder.py: degenerar quebraria a contagem de estados esperada)."""
    return {"enabled": True, "params": {"K": K, "tau1": tau1, "tau2": tau2, "theta": theta}}


def _par_integrating(Ki: float, theta: float) -> dict:
    return {"enabled": True, "params": {"Ki": Ki, "theta": theta}}


def _selfreg_config(*, K: float = 2.0, theta: float = 0.0, du_max: float = 5.0) -> MpcConfig:
    return MpcConfig.model_validate(
        {
            "name": "selfreg",
            "multiplier": 5,
            "variables": {
                "mvs": [_mv("mv_1", limits=(0.0, 1000.0), du_max=du_max)],
                "cvs": [_cv("cv_1", kind="selfreg", sp_limits=(0.0, 2000.0))],
                "constraints": [],
                "dvs": [],
            },
            "models": {"cv_1": {"mv_1": _par_selfreg(K, 20.0, 8.0, theta)}},
        }
    )


def _integrating_config(*, Ki: float = 0.5, theta: float = 0.0, du_max: float = 5.0) -> MpcConfig:
    return MpcConfig.model_validate(
        {
            "name": "integrating",
            "multiplier": 5,
            "variables": {
                "mvs": [_mv("mv_1", limits=(0.0, 1000.0), du_max=du_max)],
                "cvs": [_cv("cv_1", kind="integrating", sp_limits=(0.0, 2000.0))],
                "constraints": [],
                "dvs": [],
            },
            "models": {"cv_1": {"mv_1": _par_integrating(Ki, theta)}},
        }
    )


def _y_pred_t0(built: BuiltMpc, row_id: str) -> float:
    """Avalia `y_{row_id}` (aux do modelo) em `mpc.x0`/`tvp_template[k=0]` diretamente via
    CasADi — decidido pela leitura de `builder.py`: a predição em `t=0` é função só de
    `_x`/`_tvp`, nunca dos `_u` de decisão do otimizador (para os pares dinâmicos cobertos
    por este teste, sem o caso degenerado de ganho puro via `_u` cru)."""
    model = built.mpc.model
    y_expr = model.aux[built.output_expr_name[row_id]]
    f = ca.Function("f", [model.x, model.u, model.z, model.tvp, model.p], [y_expr])
    tvp0 = built.tvp_template["_tvp", 0]
    value = f(built.mpc.x0, model.u(0.0), model.z(0.0), tvp0, model.p(0.0))
    return float(value)


def _first_mv(built: BuiltMpc, mv_id: str) -> float:
    """MV planejada para `k=0` após `make_step` a partir do x0 armado — mesmo padrão de
    `_mv_plan` em test_mpc_builder.py (`opt_x_num` fica populado após o solve)."""
    return float(built.mpc.opt_x_num["_u", 0, 0, mv_id])


# --------------------------------------------------------------------------------------
# Predição em t=0 == y_medido exato (selfreg e integrador)
# --------------------------------------------------------------------------------------


def test_predicao_t0_bate_na_medida_selfreg():
    built = build_mpc(_selfreg_config(), ts_flow=1.0)

    init_bumpless(built, u_now={"mv_1": 30.0}, y_now={"cv_1": 42.0}, d_now={})

    assert _y_pred_t0(built, "cv_1") == pytest.approx(42.0, abs=1e-6)


def test_predicao_t0_bate_na_medida_integrador():
    built = build_mpc(_integrating_config(), ts_flow=1.0)

    init_bumpless(built, u_now={"mv_1": 12.0}, y_now={"cv_1": 77.0}, d_now={})

    assert _y_pred_t0(built, "cv_1") == pytest.approx(77.0, abs=1e-6)


# --------------------------------------------------------------------------------------
# Primeira MV do make_step <= du_max do valor vigente (o "sem salto" do aceite da fase)
# --------------------------------------------------------------------------------------


def test_primeira_mv_sem_salto_selfreg():
    du_max = 5.0
    built = build_mpc(_selfreg_config(K=2.0, du_max=du_max), ts_flow=1.0)
    u_vigente = 30.0
    # x_ss(u=30) sob K=2 -> y em regime = 60; SP = medida atual (nenhum motivo pra mexer).
    init_bumpless(built, u_now={"mv_1": u_vigente}, y_now={"cv_1": 60.0}, d_now={})
    built.tvp_template["_tvp", :, built.sp_tvp_name["cv_1"]] = 60.0

    built.mpc.set_initial_guess()
    built.mpc.make_step(built.mpc.x0)

    assert abs(_first_mv(built, "mv_1") - u_vigente) <= du_max + 1e-4


def test_primeira_mv_sem_salto_integrador():
    du_max = 5.0
    built = build_mpc(_integrating_config(Ki=0.5, du_max=du_max), ts_flow=1.0)
    u_vigente = 12.0
    y_medido = 77.0
    init_bumpless(built, u_now={"mv_1": u_vigente}, y_now={"cv_1": y_medido}, d_now={})
    built.tvp_template["_tvp", :, built.sp_tvp_name["cv_1"]] = y_medido

    built.mpc.set_initial_guess()
    built.mpc.make_step(built.mpc.x0)

    assert abs(_first_mv(built, "mv_1") - u_vigente) <= du_max + 1e-4


# --------------------------------------------------------------------------------------
# Bias corrige erro de ganho do modelo (offset absorvido em regime) — DMC, spec §3.3
# --------------------------------------------------------------------------------------


def test_bias_corrige_erro_de_ganho_do_modelo_em_regime():
    """Modelo do bloco usa K=2.0 (config), mas a "planta real" simulada aqui tem K=2.4 (20%
    de erro de ganho) -- monta a planta como um degrau de 1a ordem simples (mesma forma
    ZOH que `discretize_sopdt` usaria para K real) e roda o loop aberto por vários `Ts_mpc`
    até a planta assentar. Com `init_bumpless` re-armado no estado medido a cada passo (a
    "rotina única de armar/re-armar", spec §3.6), a predição em t=0 tem que seguir a
    medida real via bias -- não o ganho errado do modelo -- em regime."""
    k_model = 2.0
    k_real = 2.4
    tau = 20.0
    theta = 0.0
    ts_mpc = 5.0  # multiplier=5, ts_flow=1.0

    built = build_mpc(_selfreg_config(K=k_model, theta=theta, du_max=1000.0), ts_flow=1.0)

    a_real = float(ca.exp(-ts_mpc / tau))
    b_real = 1.0 - a_real
    u_now = 10.0
    x_real = 0.0

    # Loop aberto: aplica sempre a mesma MV vigente, propaga a "planta real" (ganho 20%
    # maior que o modelo) e re-arma o bumpless a cada passo com a medida real -- até
    # assentar em regime (>> constante de tempo, poucos Ts_mpc bastam para tau=20/ts=5).
    for _ in range(40):
        x_real = a_real * x_real + b_real * u_now
        y_real = k_real * x_real
        init_bumpless(built, u_now={"mv_1": u_now}, y_now={"cv_1": y_real}, d_now={})

    y_real_regime = k_real * u_now  # x_real -> u_now em regime (ganho unitário do estágio)
    assert _y_pred_t0(built, "cv_1") == pytest.approx(y_real_regime, abs=1e-3)

    # Sem bias, o modelo (K=2.0) preveria K*u_now = 20.0 -- a correção é o próprio teste:
    # a predição batendo na planta real (K=2.4 -> 24.0) prova que o bias absorveu o erro.
    assert _y_pred_t0(built, "cv_1") != pytest.approx(k_model * u_now, abs=1.0)
