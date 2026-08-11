"""Contrato de auditoria do SSTO no barramento (ADR-027 §11).

Decisão normativa que estes testes travam: **nenhum canal novo**. O registro viaja como
campo opcional de `MpcState`, no canal `mpc.state.<flow_id>.<block_id>` que já existe, e o
recorder — único escritor de hypertable — o materializa. Quadro sem SSTO continua idêntico
ao de antes (campo ausente), o que mantém o consumo da F5 intacto.
"""

from datetime import UTC, datetime

from ottima_core.bus import MpcModes, MpcPrediction, MpcState, MpcStatus, MpcVarState, SstoRun
from ottima_core.flowgraph import MpcConfig, gain_model_hash

TS = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _state(ssto: SstoRun | None) -> MpcState:
    return MpcState(
        ts=TS,
        modes=MpcModes(local_remote="remote", man_auto="auto"),
        status=MpcStatus(solver="ok", overruns=0, last_solve_ms=1.0, armed=True, input_valid=True),
        vars={"mv_a": MpcVarState(v=1.0)},
        cost=0.0,
        prediction=MpcPrediction(ts=TS, t=[], cv=[], mv=[]),
        ssto=ssto,
    )


def _run() -> SstoRun:
    return SstoRun(
        run_id="7f3c1a9e-0000-4000-8000-000000000001",
        config_hash="a" * 64,
        model_hash="b" * 64,
        status="relaxed",
        solver="highs",
        solve_ms=0.8,
        objective=-42.0,
        mv={"mv_a": 40.0},
        cv_ss={"cv_a": 80.0},
        bias={"cv_a": 1.0},
        dv={"dv_a": 5.0},
        costs={"mv_a": -1.0},
        delta_mv={"mv_a": 10.0},
        mv_target={"mv_a": 50.0},
        cv_target={"cv_a": 100.0},
        given_up=["co_b"],
        active_constraints=["cv_a:high"],
        duals={"cv_a:high": -0.5},
    )


def test_mpc_state_sem_ssto_continua_valido_e_omite_o_campo():
    state = _state(None)

    assert state.ssto is None
    assert "ssto" not in state.model_dump(exclude_none=True)


def test_mpc_state_com_ssto_faz_round_trip_no_canal():
    original = _state(_run())

    replicado = MpcState.model_validate_json(original.model_dump_json())

    assert replicado.ssto is not None
    assert replicado.ssto.status == "relaxed"
    assert replicado.ssto.given_up == ["co_b"]
    assert replicado.ssto.duals == {"cv_a:high": -0.5}
    assert replicado.ssto.mv_target == {"mv_a": 50.0}


def test_registro_carrega_a_referencia_do_modelo_de_ganho():
    """ "Referência ao modelo de ganho usado" (ADR-027 §11): o hash da matriz `models`, para
    o registro nunca ficar órfão de qual modelo produziu aquele alvo."""
    run = _run()

    assert len(run.model_hash) == 64
    assert run.model_hash != run.config_hash


def _config(k: float) -> MpcConfig:
    return MpcConfig.model_validate(
        {
            "name": "MPC",
            "multiplier": 1,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_a",
                        "name": "a",
                        "eu": "%",
                        "limits": {"min": 0.0, "max": 100.0},
                        "du_max": 1.0,
                    }
                ],
                "cvs": [
                    {
                        "id": "cv_a",
                        "name": "a",
                        "eu": "degC",
                        "kind": "selfreg",
                        "tss": 100.0,
                        "weight": 1.0,
                        "sp_limits": {"min": 0.0, "max": 100.0},
                    }
                ],
                "constraints": [],
                "dvs": [],
            },
            "models": {
                "cv_a": {
                    "mv_a": {
                        "enabled": True,
                        "params": {"K": k, "tau1": 10.0, "tau2": 0.0, "theta": 0.0},
                    }
                }
            },
        }
    )


def test_gain_model_hash_muda_com_o_ganho():
    assert gain_model_hash(_config(2.0)) != gain_model_hash(_config(2.5))


def test_gain_model_hash_e_estavel():
    assert gain_model_hash(_config(2.0)) == gain_model_hash(_config(2.0))
