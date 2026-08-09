"""Mesa de casos de `ottima_core.flowgraph.mpc_config` (spec F4 §2.1/§2.2-5/§2.2-7, RF-601..608).

`MpcConfig` espelha o esqueleto normativo da spec F4 §2.1 verbatim. `derive_horizons` e
`mpc_state_dimension` são funções puras (§2.2-5/§2.2-7); a política de bloqueio (422) sobre os
valores que elas expõem é da tarefa 1.2 do plano F4a — aqui só provamos que os valores são
computados corretamente e permanecem observáveis quando fora dos tetos.
"""

import pytest
from pydantic import ValidationError

from ottima_core.flowgraph import MpcConfig, derive_horizons, mpc_state_dimension


def mpc_skeleton() -> dict:
    """Esqueleto normativo verbatim de `docs/specs/F4-mpc.md` §2.1."""
    return {
        "name": "MPC da coluna",
        "multiplier": 5,
        "variables": {
            "mvs": [
                {
                    "id": "mv_x7k2",
                    "name": "Vazão de refluxo",
                    "eu": "m3/h",
                    "limits": {"min": 0.0, "max": 100.0},
                    "du_max": 5.0,
                    "initial_value": 0.0,
                    "pid": {
                        "write_tag_id": 12,
                        "target_mode": "rcas",
                        "mode_cmd_tag_id": 13,
                        "mode_read_tag_id": 14,
                        "readback_tag_id": 15,
                        "mode_values": {"auto": 1, "target": 3},
                    },
                }
            ],
            "cvs": [
                {
                    "id": "cv_a1b2",
                    "name": "Temperatura de topo",
                    "eu": "C",
                    "kind": "selfreg",
                    "tss": 600.0,
                    "weight": 1.0,
                    "sp_limits": {"min": 80.0, "max": 120.0},
                }
            ],
            "constraints": [
                {
                    "id": "co_c3d4",
                    "name": "Nível do vaso",
                    "eu": "%",
                    "kind": "integrating",
                    "tss": 900.0,
                    "range": {"low": 20.0, "high": 80.0},
                    "priority": 1,
                }
            ],
            "dvs": [{"id": "dv_e5f6", "name": "Vazão de carga", "eu": "m3/h"}],
        },
        "models": {
            "cv_a1b2": {
                "mv_x7k2": {
                    "enabled": True,
                    "params": {"K": 1.2, "tau1": 120.0, "tau2": 30.0, "theta": 15.0},
                }
            }
        },
    }


# --------------------------------------------------------------------------------------
# MpcConfig — parse do esqueleto §2.1
# --------------------------------------------------------------------------------------


def test_esqueleto_verbatim_parseia_todos_os_campos():
    config = MpcConfig.model_validate(mpc_skeleton())

    assert config.name == "MPC da coluna"
    assert config.multiplier == 5

    mv = config.variables.mvs[0]
    assert mv.id == "mv_x7k2"
    assert mv.name == "Vazão de refluxo"
    assert mv.eu == "m3/h"
    assert mv.limits.min == 0.0
    assert mv.limits.max == 100.0
    assert mv.du_max == 5.0
    assert mv.initial_value == 0.0
    assert mv.pid is not None
    assert mv.pid.write_tag_id == 12
    assert mv.pid.target_mode == "rcas"
    assert mv.pid.mode_cmd_tag_id == 13
    assert mv.pid.mode_read_tag_id == 14
    assert mv.pid.readback_tag_id == 15
    assert mv.pid.mode_values.auto == 1
    assert mv.pid.mode_values.target == 3

    cv = config.variables.cvs[0]
    assert cv.id == "cv_a1b2"
    assert cv.name == "Temperatura de topo"
    assert cv.eu == "C"
    assert cv.kind == "selfreg"
    assert cv.tss == 600.0
    assert cv.weight == 1.0
    assert cv.sp_limits.min == 80.0
    assert cv.sp_limits.max == 120.0

    constraint = config.variables.constraints[0]
    assert constraint.id == "co_c3d4"
    assert constraint.name == "Nível do vaso"
    assert constraint.eu == "%"
    assert constraint.kind == "integrating"
    assert constraint.tss == 900.0
    assert constraint.range.low == 20.0
    assert constraint.range.high == 80.0
    assert constraint.priority == 1

    dv = config.variables.dvs[0]
    assert dv.id == "dv_e5f6"
    assert dv.name == "Vazão de carga"
    assert dv.eu == "m3/h"

    pair = config.models["cv_a1b2"]["mv_x7k2"]
    assert pair.enabled is True
    assert pair.params == {"K": 1.2, "tau1": 120.0, "tau2": 30.0, "theta": 15.0}


def test_mv_sem_pid_e_direta():
    data = mpc_skeleton()
    data["variables"]["mvs"][0]["pid"] = None
    config = MpcConfig.model_validate(data)
    assert config.variables.mvs[0].pid is None


@pytest.mark.parametrize(
    ("caminho", "categoria", "id_invalido"),
    [
        (("variables", "mvs", 0), "mv_", "cv_x7k2"),
        (("variables", "cvs", 0), "cv_", "mv_a1b2"),
        (("variables", "constraints", 0), "co_", "cv_c3d4"),
        (("variables", "dvs", 0), "dv_", "mv_e5f6"),
    ],
)
def test_id_com_prefixo_errado_e_rejeitado(caminho, categoria, id_invalido):
    data = mpc_skeleton()
    grupo, lista, indice = caminho
    data[grupo][lista][indice]["id"] = id_invalido
    with pytest.raises(ValidationError, match=categoria):
        MpcConfig.model_validate(data)


# --------------------------------------------------------------------------------------
# DvVar.range — spec §4.2, RF-702
# --------------------------------------------------------------------------------------


def test_dv_sem_range_e_valida_com_none():
    data = mpc_skeleton()
    config = MpcConfig.model_validate(data)
    assert config.variables.dvs[0].range is None


def test_dv_com_range_valida():
    data = mpc_skeleton()
    data["variables"]["dvs"][0]["range"] = {"low": 0.0, "high": 100.0}
    config = MpcConfig.model_validate(data)
    assert config.variables.dvs[0].range.low == 0.0
    assert config.variables.dvs[0].range.high == 100.0


def test_dv_com_range_incompleto_e_rejeitado():
    data = mpc_skeleton()
    data["variables"]["dvs"][0]["range"] = {"low": 0.0}
    with pytest.raises(ValidationError):
        MpcConfig.model_validate(data)


def test_dv_com_range_low_maior_que_high_e_aceito_como_a_restricao():
    """`Range` não valida `low < high` neste nível (regra semântica de `validate.py`,
    tarefa 1.2 do plano F4a) — mesmo comportamento hoje aceito pela Restrição, replicado
    sem introduzir regra nova."""
    data = mpc_skeleton()
    data["variables"]["constraints"][0]["range"] = {"low": 80.0, "high": 20.0}
    data["variables"]["dvs"][0]["range"] = {"low": 80.0, "high": 20.0}
    config = MpcConfig.model_validate(data)
    assert config.variables.constraints[0].range.low > config.variables.constraints[0].range.high
    assert config.variables.dvs[0].range.low > config.variables.dvs[0].range.high


# --------------------------------------------------------------------------------------
# derive_horizons — spec §2.2-5, RF-603
# --------------------------------------------------------------------------------------


def test_derive_horizons_caso_do_brief():
    horizons = derive_horizons(multiplier=5, ts_flow=1.0, tss=[600.0])

    assert horizons.ts_mpc == 5.0
    assert horizons.np == 120  # ceil(600/5)
    assert horizons.nc == 30  # max(2, ceil(120/4))


def test_derive_horizons_expoe_np_abaixo_do_piso():
    # Ts_mpc = 10*100 = 1000; Np = ceil(600/1000) = 1 < 2 — o piso 422 é decisão da tarefa 1.2.
    horizons = derive_horizons(multiplier=10, ts_flow=100.0, tss=[600.0])
    assert horizons.np == 1
    assert horizons.np < 2


def test_derive_horizons_expoe_np_acima_do_teto():
    # Ts_mpc = 1*1 = 1; Np = ceil(1000/1) = 1000 > 120 — o teto 422 é decisão da tarefa 1.2.
    horizons = derive_horizons(multiplier=1, ts_flow=1.0, tss=[1000.0])
    assert horizons.np == 1000
    assert horizons.np > 120


# --------------------------------------------------------------------------------------
# mpc_state_dimension — spec §2.2-7
# --------------------------------------------------------------------------------------


def two_by_two_config(*, theta_extra: float = 0.0) -> dict:
    """2 CVs selfreg (SOPDT) x 2 MVs, todos os 4 pares habilitados, sem `pid` (MVs diretas).

    Conta à mão (theta=0 em todos os pares): 2 linhas x 2 colunas x 2 estados/par = 8,
    mais n_MVs(2) = 10. `theta_extra` acrescenta tempo morto a um único par, para provar
    `round(theta/Ts_mpc)`.
    """

    def mv(id_: str) -> dict:
        return {
            "id": id_,
            "name": id_,
            "eu": "u",
            "limits": {"min": 0.0, "max": 1.0},
            "du_max": 1.0,
            "initial_value": 0.0,
            "pid": None,
        }

    def cv(id_: str) -> dict:
        return {
            "id": id_,
            "name": id_,
            "eu": "y",
            "kind": "selfreg",
            "tss": 10.0,
            "weight": 1.0,
            "sp_limits": {"min": 0.0, "max": 1.0},
        }

    def par(theta: float) -> dict:
        return {"enabled": True, "params": {"K": 1.0, "tau1": 1.0, "tau2": 0.0, "theta": theta}}

    return {
        "name": "2x2",
        "multiplier": 1,
        "variables": {
            "mvs": [mv("mv_1"), mv("mv_2")],
            "cvs": [cv("cv_1"), cv("cv_2")],
            "constraints": [],
            "dvs": [],
        },
        "models": {
            "cv_1": {"mv_1": par(theta_extra), "mv_2": par(0.0)},
            "cv_2": {"mv_1": par(0.0), "mv_2": par(0.0)},
        },
    }


def test_mpc_state_dimension_2x2_sem_tempo_morto():
    config = MpcConfig.model_validate(two_by_two_config())
    assert mpc_state_dimension(config, ts_mpc=1.0) == 10  # 2*2*2 + 2


def test_mpc_state_dimension_soma_amostras_de_atraso_banker():
    # theta=2.5, Ts_mpc=1.0 -> round(2.5) = 2 pelo banker's (half-even) do Python.
    config = MpcConfig.model_validate(two_by_two_config(theta_extra=2.5))
    assert mpc_state_dimension(config, ts_mpc=1.0) == 12  # 10 + 2


def test_mpc_state_dimension_ignora_par_desabilitado():
    data = two_by_two_config()
    data["models"]["cv_1"]["mv_2"]["enabled"] = False
    config = MpcConfig.model_validate(data)
    assert mpc_state_dimension(config, ts_mpc=1.0) == 8  # um par a menos: -2 estados
