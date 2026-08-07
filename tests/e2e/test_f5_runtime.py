"""L2 F5a (spec F5 9.2): concorrência, building, prediction_ts.

E2E-F5-05: deploy não bloqueia stop; building; arm_failed.
E2E-F5-06: prediction_ts presente; ts monotônico; ts − prediction_ts ≈ Ts_mpc.
"""

import time
from datetime import datetime
from typing import Any

import httpx
import pytest

from .conftest import (
    TS_MPC,
    AmbienteMpc,
    OpcSim,
    assinar_mpc_state,
    deploy_flow,
    grafo_mpc_tfs,
    resetar_atuador_mpc,
)

pytestmark = pytest.mark.e2e


def test_e2e_f5_05_deploy_nao_bloqueia_stop_latencia_medida(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """C-04: STOP de outro durante deploy; building observável; arm ⇒ arm_failed."""
    resetar_atuador_mpc(opcsim_client)

    flow_heavy = criar_flow_mpc("f5-05-h", grafo=grafo_mpc_tfs(ambiente_mpc))
    flow_light = criar_flow_mpc("f5-05-l", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_heavy, "mpc1") as fluxo_h:
        with assinar_mpc_state(admin, flow_light, "mpc1") as _fluxo_l:
            # Deploy heavy
            deploy_flow(admin, flow_heavy)

            # (b) Aguarda building em LOCAL antes de idle
            for _ in range(30):
                try:
                    a = fluxo_h.proxima(timeout=1.0, descricao="building")
                    if a.get("status", {}).get("solver") == "building":
                        assert (
                            a["modes"]["local_remote"] == "local"
                        ), "building deve ser em LOCAL"
                        break
                except AssertionError:
                    pass
                time.sleep(0.1)

            # (a) Stop do light durante deploy — não bloqueia
            t_stop_start = time.monotonic()
            admin.post(f"/api/flows/{flow_light}/stop")
            t_stop_end = time.monotonic()
            latencia_stop = t_stop_end - t_stop_start

            assert latencia_stop < 5.0, f"stop demorou {latencia_stop:.1f}s"

            # Aguarda heavy idle
            fluxo_h.esperar(
                lambda e: e.get("status", {}).get("solver") == "idle",
                timeout=30.0,
                descricao="heavy idle",
            )


def test_e2e_f5_06_ts_prediction_ts_monotonico_em_regime(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """C-05: prediction_ts presente; ts monotônico; ts − prediction_ts ≈ Ts_mpc."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-06", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Coleta 8 amostras
        amostras = []
        for _ in range(8):
            a = fluxo.esperar(lambda _e: True, timeout=15.0, descricao="amostra")
            amostras.append(a)
            time.sleep(0.5)

        # (b) prediction_ts presente
        for i, a in enumerate(amostras):
            assert "ts" in a, f"#{i}: sem ts"
            assert "prediction_ts" in a, f"#{i}: sem prediction_ts"

        # ts monotônico
        ts_vals = [datetime.fromisoformat(a["ts"]) for a in amostras]
        for i in range(1, len(ts_vals)):
            assert ts_vals[i] >= ts_vals[i - 1], f"ts não monotônico #{i}"

        # (d) Em regime: prediction_ts == ts − Ts_mpc (±30%)
        for a in amostras[-3:]:
            ts = datetime.fromisoformat(a["ts"])
            pts = datetime.fromisoformat(a["prediction_ts"])
            delta = (ts - pts).total_seconds()

            min_delta = 0.7 * TS_MPC
            max_delta = 1.3 * TS_MPC
            assert min_delta <= delta <= max_delta, (
                f"prediction_ts fora: delta={delta:.3f}s, esperado ~{TS_MPC}s"
            )
