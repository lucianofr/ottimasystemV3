"""Carga (RNF-02) — `make_step` de um MPC 2x2 (Np=60) dentro de 70% do Ts_mpc de referência
(spec F4 §9.2/§10, PRD §9-1; plano F4a tarefa 2.4).

Derivação de Np=60 (spec §2.2-5, `derive_horizons`):
    Ts_mpc = multiplier * ts_flow = 5 * 1.0 = 5.0 s
    Np = ceil(max(tss) / Ts_mpc) = ceil(300.0 / 5.0) = 60   (TSS das duas CVs = 300.0 s)
    Nc = max(2, ceil(Np / 4)) = max(2, 15) = 15

Orçamento de referência (RNF-02): 70% x Ts_mpc = 0.7 x 5.0 s = 3.5 s — teto para média E p95
de `make_step` (hardware de referência).

Este teste é `slow` (fora do run default, spec `pyproject.toml`): mede o solve de um MPC
2x2 SOPDT plenamente acoplado (2 MVs x 2 CVs, 4 pares habilitados), montado uma única vez
(`build_mpc` + `init_bumpless`), depois cronometra `N_TIMED` execuções de `make_step` (wall
clock, `time.perf_counter`), descartando `N_WARMUP` execuções iniciais. Determinístico: sem
rede, valores fixos, IPOPT já silenciado pelo builder (`mpc.settings.supress_ipopt_output()`,
`builder.py`).
"""

import math
import statistics
import time
from collections.abc import Sequence

import pytest

from ottima_core.flowgraph import MpcConfig
from ottima_flow_runtime.mpc import build_mpc, init_bumpless

MULTIPLIER = 5
TS_FLOW = 1.0
TSS_CV = 300.0
"""TSS das duas CVs — `max(tss) / Ts_mpc = 300.0 / 5.0 = 60` (Np exato, ver docstring)."""

REFERENCE_TS_MPC_S = 5.0
"""Ts_mpc de referência do RNF-02 (spec §9.2) — igual ao Ts_mpc montado aqui (5*1.0)."""

BUDGET_S = 0.7 * REFERENCE_TS_MPC_S
"""70% do Ts_mpc de referência — teto de média E p95 de `make_step` (RNF-02)."""

N_WARMUP = 3
N_TIMED = 30


def _mv(id_: str, *, max_rate: float = 50.0) -> dict:
    return {
        "id": id_,
        "name": id_,
        "eu": "u",
        "limits": {"min": 0.0, "max": 1000.0},
        "max_rate": max_rate,
        "initial_value": 0.0,
        "pid": None,
    }


def _cv(id_: str, *, tss: float) -> dict:
    return {
        "id": id_,
        "name": id_,
        "eu": "y",
        "kind": "selfreg",
        "tss": tss,
        "weight": 1.0,
        "sp_limits": {"min": 0.0, "max": 2000.0},
    }


def _pair(K: float) -> dict:
    """Par SOPDT bem acima do limiar `Ts/10` (tau1=20.0, tau2=8.0 >> 0.5) — nunca degenera
    para ganho puro (mesma nota de `test_mpc_bumpless.py`/`test_mpc_builder.py`)."""
    return {"enabled": True, "params": {"K": K, "tau1": 20.0, "tau2": 8.0, "theta": 0.0}}


def _config_2x2() -> MpcConfig:
    """2 MVs x 2 CVs, matriz `models` plenamente acoplada (4 pares habilitados) — pior caso
    de carga do do-mpc para o mesmo Np/Nc (mais estados que um par diagonal)."""
    return MpcConfig.model_validate(
        {
            "name": "carga_2x2",
            "multiplier": MULTIPLIER,
            "variables": {
                "mvs": [_mv("mv_1"), _mv("mv_2")],
                "cvs": [_cv("cv_1", tss=TSS_CV), _cv("cv_2", tss=TSS_CV)],
                "constraints": [],
                "dvs": [],
            },
            "models": {
                "cv_1": {"mv_1": _pair(2.0), "mv_2": _pair(1.2)},
                "cv_2": {"mv_1": _pair(0.8), "mv_2": _pair(1.5)},
            },
        }
    )


def _percentile(values: Sequence[float], p: float) -> float:
    """Interpolação linear sobre os valores ordenados (sem numpy) — p95 determinístico."""
    ordered = sorted(values)
    rank = p * (len(ordered) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[int(rank)]
    weight = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * weight


@pytest.mark.slow
def test_carga_make_step_2x2_np60_sob_70pct_ts_mpc(capsys: pytest.CaptureFixture[str]) -> None:
    built = build_mpc(_config_2x2(), ts_flow=TS_FLOW)
    assert built.horizons.np == 60
    assert built.horizons.ts_mpc == pytest.approx(REFERENCE_TS_MPC_S)

    init_bumpless(
        built,
        u_now={"mv_1": 30.0, "mv_2": 20.0},
        y_now={"cv_1": 500.0, "cv_2": 500.0},
        d_now={},
    )
    built.tvp_template["_tvp", :, built.sp_tvp_name["cv_1"]] = 550.0
    built.tvp_template["_tvp", :, built.sp_tvp_name["cv_2"]] = 480.0

    times: list[float] = []
    for i in range(N_WARMUP + N_TIMED):
        start = time.perf_counter()
        built.mpc.make_step(built.mpc.x0)
        elapsed = time.perf_counter() - start
        if i >= N_WARMUP:
            times.append(elapsed)

    mean_s = statistics.mean(times)
    p95_s = _percentile(times, 0.95)
    max_s = max(times)

    with capsys.disabled():
        print(
            f"\n[RNF-02] make_step 2x2 Np=60 — mean={mean_s:.4f}s p95={p95_s:.4f}s "
            f"max={max_s:.4f}s (orçamento={BUDGET_S:.1f}s, N={N_TIMED}, warmup={N_WARMUP})"
        )

    assert mean_s < BUDGET_S, f"media {mean_s:.4f}s >= orcamento {BUDGET_S:.1f}s"
    assert p95_s < BUDGET_S, f"p95 {p95_s:.4f}s >= orcamento {BUDGET_S:.1f}s"


@pytest.mark.slow
def test_primeiro_solve_frio_de_bloco_com_atraso_longo_cabe_no_orcamento() -> None:
    """A classe de falha do campo (2026-09-11, flow 987): θ=91 s contra Ts_mpc=2 s dá ~46
    estados de atraso por par (n_x=83), e o PRIMEIRO `make_step` da vida do worker (frio, sem
    warm start) é o mais caro — se ele estourar 0,7×Ts_mpc, o kill+respawn da spec §4.2
    reinicia o worker antes do primeiro solve concluir e a espiral de `building` nunca
    termina (76 respawns, zero solves, na planta).

    O gate RNF-02 acima NÃO pega isso: descarta `N_WARMUP=3` execuções (nunca mede o solve
    frio), usa orçamento de Ts_mpc=5 s e matriz sem cadeia de atraso. Este teste mede o
    solve FRIO, na forma que falhou: Ts_mpc=2 s (multiplier=1), Np=60, θ até 91 s — o mesmo
    orçamento que `MpcHost._deadline_s` aplica ao vivo.
    """
    from ottima_flow_runtime.mpc.worker import SolveRequest, _build_runtime, _solve

    config = MpcConfig.model_validate(
        {
            "name": "campo_flow_987",
            "multiplier": 1,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_chns",
                        "name": "FV-201",
                        "eu": "%",
                        "span": 100,
                        "limits": {"min": 10, "max": 100},
                        "max_rate": 10,
                        "du_min": 0,
                        "initial_value": 50,
                    },
                    {
                        "id": "mv_fdou",
                        "name": "FV-202",
                        "eu": "%",
                        "span": 100,
                        "limits": {"min": 10, "max": 100},
                        "max_rate": 10,
                        "du_min": 0,
                        "initial_value": 50,
                    },
                ],
                "cvs": [
                    {
                        "id": "cv_nivel",
                        "name": "LT-201",
                        "eu": "%",
                        "kind": "integrating",
                        "tss": 120,
                        "weight": 2,
                        "span": 100,
                        "sp_limits": {"min": 45, "max": 65},
                    },
                    {
                        "id": "cv_refluxo",
                        "name": "Refluxo",
                        "eu": "%",
                        "kind": "selfreg",
                        "tss": 120,
                        "weight": 1,
                        "span": 100,
                        "sp_limits": {"min": 0, "max": 100},
                    },
                ],
                "constraints": [
                    {
                        "id": "co_vazao",
                        "name": "FT-204",
                        "eu": "m3/h",
                        "kind": "selfreg",
                        "tss": 120,
                        "span": 20,
                        "range": {"low": 0, "high": 20},
                        "priority": 1,
                    }
                ],
                "dvs": [],
            },
            "models": {
                "co_vazao": {
                    "mv_chns": {
                        "enabled": True,
                        "params": {"K": 0.061, "tau1": 16, "tau2": 0, "theta": 4},
                    },
                    "mv_fdou": {
                        "enabled": True,
                        "params": {"K": 1.023, "tau1": 13.5, "tau2": 0, "theta": 3.5},
                    },
                },
                "cv_refluxo": {
                    "mv_chns": {
                        "enabled": True,
                        "params": {"K": -1.491, "tau1": 1.6, "tau2": 0.6, "theta": 6},
                    },
                    "mv_fdou": {
                        "enabled": True,
                        "params": {"K": -2.058, "tau1": 1.6, "tau2": 0.6, "theta": 2.6},
                    },
                },
                "cv_nivel": {
                    "mv_chns": {"enabled": True, "params": {"Ki": 0.2275, "theta": 91}},
                    "mv_fdou": {"enabled": True, "params": {"Ki": -0.1796, "theta": 38}},
                },
            },
        }
    )
    runtime = _build_runtime(config, ts_flow=2.0)
    assert runtime.built.horizons.np == 60
    assert runtime.built.horizons.ts_mpc == pytest.approx(2.0)

    request = SolveRequest(
        y={"cv_nivel": 13.2, "cv_refluxo": 52.4, "co_vazao": 2.4},
        u_applied={"mv_chns": 50.0, "mv_fdou": 50.0},
        d={},
        sp={"cv_nivel": 55.0, "cv_refluxo": 55.0},
        reinit=True,
    )
    t0 = time.perf_counter()
    result = _solve(runtime, request)
    cold_s = time.perf_counter() - t0
    budget_s = 0.7 * runtime.built.horizons.ts_mpc

    assert result.status == "ok"
    assert cold_s < budget_s, (
        f"primeiro solve FRIO levou {cold_s:.3f}s >= orçamento {budget_s:.1f}s — o worker "
        f"morreria no primeiro ciclo e entraria na espiral de respawn (caso flow 987)"
    )
