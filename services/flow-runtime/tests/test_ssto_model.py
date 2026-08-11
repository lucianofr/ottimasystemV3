"""Mesa de casos do modelo de regime permanente do SSTO (ADR-026 §3/§4).

O ponto normativo deste módulo: **não existe segundo modelo de ganho**. `G`/`Gd` saem do
`PairSS` JÁ DISCRETIZADO que o controlador usa (`mpc/discretize.py`), nunca de uma segunda
leitura de `params`. Os testes provam a equivalência numérica (`c(I−a)⁻¹b == K` no SOPDT,
`(c·b)/Ts == Ki` no IOPDT) em vez de assumi-la.
"""

import numpy as np
import pytest

from ottima_core.flowgraph import MpcConfig
from ottima_flow_runtime.mpc.discretize import discretize_iopdt, discretize_sopdt
from ottima_flow_runtime.target_calculation.model import (
    build_steady_state_model,
    pair_steady_state_gain,
)

TS = 1.0


def _mv(id_: str, *, operating_point: float = 0.0) -> dict:
    return {
        "id": id_,
        "name": id_,
        "eu": "%",
        "limits": {"min": 0.0, "max": 100.0},
        "du_max": 5.0,
        "operating_point": operating_point,
    }


def _cv(id_: str, *, kind: str = "selfreg") -> dict:
    return {
        "id": id_,
        "name": id_,
        "eu": "degC",
        "kind": kind,
        "tss": 100.0,
        "weight": 1.0,
        "sp_limits": {"min": 0.0, "max": 200.0},
    }


def _co(id_: str, *, priority: int = 1) -> dict:
    return {
        "id": id_,
        "name": id_,
        "eu": "bar",
        "kind": "selfreg",
        "tss": 100.0,
        "range": {"low": 0.0, "high": 10.0},
        "priority": priority,
    }


def _dv(id_: str, *, operating_point: float = 0.0) -> dict:
    return {"id": id_, "name": id_, "eu": "m3/h", "operating_point": operating_point}


def _sopdt(k: float, *, tau1: float = 10.0, tau2: float = 5.0, theta: float = 0.0) -> dict:
    return {"enabled": True, "params": {"K": k, "tau1": tau1, "tau2": tau2, "theta": theta}}


def _iopdt(ki: float, *, theta: float = 0.0) -> dict:
    return {"enabled": True, "params": {"Ki": ki, "theta": theta}}


def _config(
    *,
    mvs: list[dict],
    cvs: list[dict],
    constraints: list[dict] | None = None,
    dvs: list[dict] | None = None,
    models: dict,
) -> MpcConfig:
    return MpcConfig.model_validate(
        {
            "name": "MPC de teste",
            "multiplier": 1,
            "variables": {
                "mvs": mvs,
                "cvs": cvs,
                "constraints": constraints or [],
                "dvs": dvs or [],
            },
            "models": models,
        }
    )


# ---------------------------------------------------------------------------------------
# Ganho de um par: derivado do PairSS, não de params
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("k", [2.5, -1.75, 0.0])
@pytest.mark.parametrize("tau1,tau2", [(10.0, 5.0), (10.0, 0.0), (0.0, 8.0)])
def test_ganho_dc_do_sopdt_e_o_proprio_K(k: float, tau1: float, tau2: float):
    """`c(I−a)⁻¹b == K` para SOPDT — inclusive quando um dos estágios degrada para
    passagem direta (`tau < Ts/10`, `discretize_sopdt`)."""
    pair = discretize_sopdt(k, tau1, tau2, 0.0, TS)

    assert pair_steady_state_gain(pair, direct_gain=None, kind="selfreg", ts=TS) == pytest.approx(k)


def test_ganho_do_par_degenerado_vem_do_direct_gain():
    """Os DOIS estágios em passagem direta ⇒ `n=0`: o `PairSS` não representa o ganho puro
    (`y = c@x = 0` sempre) e o `K` chega pelo `direct_gain`, mesma convenção do builder."""
    pair = discretize_sopdt(3.0, 0.0, 0.0, 0.0, TS)
    assert pair.a.shape[0] == 0

    assert pair_steady_state_gain(pair, direct_gain=3.0, kind="selfreg", ts=TS) == pytest.approx(
        3.0
    )


@pytest.mark.parametrize("ki", [0.5, -0.25])
@pytest.mark.parametrize("ts", [1.0, 4.0])
def test_ganho_do_iopdt_e_a_taxa_de_rampa_Ki(ki: float, ts: float):
    """Linha integradora não tem ganho estático finito (ADR-026 §4): o que o LP usa é a
    taxa de rampa `Ki` [EU/(EU·s)], recuperada do `PairSS` como `(c·b)/Ts`."""
    pair = discretize_iopdt(ki, 0.0, ts)

    assert pair_steady_state_gain(
        pair, direct_gain=None, kind="integrating", ts=ts
    ) == pytest.approx(ki)


def test_ganho_ignora_o_tempo_morto():
    """Atraso não muda regime permanente — o `PairSS` do par com `theta` grande tem o mesmo
    ganho DC (o atraso vira shift register, fora de `(a, b, c)`)."""
    sem_atraso = discretize_sopdt(2.0, 10.0, 5.0, 0.0, TS)
    com_atraso = discretize_sopdt(2.0, 10.0, 5.0, 30.0, TS)

    assert pair_steady_state_gain(
        sem_atraso, direct_gain=None, kind="selfreg", ts=TS
    ) == pytest.approx(pair_steady_state_gain(com_atraso, direct_gain=None, kind="selfreg", ts=TS))


# ---------------------------------------------------------------------------------------
# Matrizes G e Gd
# ---------------------------------------------------------------------------------------


def test_g_e_gd_seguem_a_ordem_do_config():
    """Linhas: CVs e depois Restrições (mesma ordem de `BuiltMpc.prediction_rows`).
    Colunas de `G`: MVs; colunas de `Gd`: DVs — nunca misturadas."""
    config = _config(
        mvs=[_mv("mv_a"), _mv("mv_b")],
        cvs=[_cv("cv_a")],
        constraints=[_co("co_a")],
        dvs=[_dv("dv_a")],
        models={
            "cv_a": {"mv_a": _sopdt(2.0), "mv_b": _sopdt(-1.0), "dv_a": _sopdt(0.5)},
            "co_a": {"mv_a": _sopdt(3.0), "mv_b": _sopdt(4.0), "dv_a": _sopdt(-0.25)},
        },
    )

    model = build_steady_state_model(config, TS)

    assert model.row_ids == ("cv_a", "co_a")
    assert model.mv_ids == ("mv_a", "mv_b")
    assert model.dv_ids == ("dv_a",)
    assert model.g == pytest.approx(np.array([[2.0, -1.0], [3.0, 4.0]]))
    assert model.gd == pytest.approx(np.array([[0.5], [-0.25]]))


def test_par_desabilitado_ou_ausente_vira_zero():
    config = _config(
        mvs=[_mv("mv_a"), _mv("mv_b")],
        cvs=[_cv("cv_a")],
        models={
            "cv_a": {
                "mv_a": _sopdt(2.0),
                "mv_b": {
                    "enabled": False,
                    "params": {"K": 9.0, "tau1": 1.0, "tau2": 1.0, "theta": 0.0},
                },
            }
        },
    )

    model = build_steady_state_model(config, TS)

    assert model.g == pytest.approx(np.array([[2.0, 0.0]]))


def test_linha_integradora_usa_taxa_de_rampa_na_matriz():
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_lvl", kind="integrating")],
        models={"cv_lvl": {"mv_a": _iopdt(0.4)}},
    )

    model = build_steady_state_model(config, TS)

    assert model.row_kind["cv_lvl"] == "integrating"
    assert model.g == pytest.approx(np.array([[0.4]]))


def test_sem_dv_a_matriz_gd_tem_zero_colunas():
    config = _config(mvs=[_mv("mv_a")], cvs=[_cv("cv_a")], models={"cv_a": {"mv_a": _sopdt(1.0)}})

    model = build_steady_state_model(config, TS)

    assert model.gd.shape == (1, 0)


# ---------------------------------------------------------------------------------------
# Base de regime permanente
# ---------------------------------------------------------------------------------------


def test_base_de_linha_autorregulavel_e_G_u_mais_Gd_d_mais_bias():
    config = _config(
        mvs=[_mv("mv_a", operating_point=20.0)],
        cvs=[_cv("cv_a")],
        dvs=[_dv("dv_a", operating_point=5.0)],
        models={"cv_a": {"mv_a": _sopdt(2.0), "dv_a": _sopdt(0.5)}},
    )
    model = build_steady_state_model(config, TS)

    base = model.base(u={"mv_a": 30.0}, d={"dv_a": 9.0}, bias={"cv_a": 1.5})

    # 2.0*(30−20) + 0.5*(9−5) + 1.5
    assert base == pytest.approx(np.array([23.5]))


def test_base_de_linha_integradora_e_a_taxa_atual_sem_bias():
    """Bias corrige NÍVEL; a linha integradora entra no LP pela TAXA (ADR-026 §4), então o
    bias de nível não a desloca — somá-lo ali seria erro de unidade (EU vs EU/s)."""
    config = _config(
        mvs=[_mv("mv_a", operating_point=20.0)],
        cvs=[_cv("cv_lvl", kind="integrating")],
        models={"cv_lvl": {"mv_a": _iopdt(0.4)}},
    )
    model = build_steady_state_model(config, TS)

    base = model.base(u={"mv_a": 25.0}, d={}, bias={"cv_lvl": 99.0})

    assert base == pytest.approx(np.array([0.4 * 5.0]))
