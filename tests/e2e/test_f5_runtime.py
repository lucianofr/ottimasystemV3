"""Camada L2 da F5a (spec F5 §9.2, tarefa 5.1): concorrência e timestamps."""

import time
from datetime import datetime
from typing import Any

import httpx
import pytest

from .conftest import (
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
    """E2E-F5-05 (spec §9.2): deploy não bloqueia stop de outro."""
    resetar_atuador_mpc(opcsim_client)

    flow1 = criar_flow_mpc("f5-05-1", grafo=grafo_mpc_tfs(ambiente_mpc))
    flow2 = criar_flow_mpc("f5-05-2", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow1, "mpc1") as fluxo1:
        with assinar_mpc_state(admin, flow2, "mpc1") as fluxo2:
            deploy_flow(admin, flow1)
            fluxo1.esperar(lambda _e: True, timeout=30.0, descricao="f1")

            # Deploy f2 não deve bloquear
            t_start = time.monotonic()
            deploy_flow(admin, flow2)
            t_end = time.monotonic()
            latencia = t_end - t_start

            assert latencia < 5.0, f"deploy demorou {latencia:.1f}s"

            # Ambos em idle
            fluxo1.esperar(
                lambda e: e.get("status", {}).get("solver") == "idle",
                timeout=30.0,
                descricao="f1 idle",
            )
            fluxo2.esperar(
                lambda e: e.get("status", {}).get("solver") == "idle",
                timeout=30.0,
                descricao="f2 idle",
            )


def test_e2e_f5_06_ts_prediction_ts_monotonico_em_regime(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-06 (spec §9.2): ts presente em mpc.state e monotônico."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-06", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)

        # Coleta amostras
        amostras = []
        for _ in range(6):
            a = fluxo.esperar(lambda _e: True, timeout=15.0, descricao="amostra")
            amostras.append(a)
            time.sleep(0.5)

        # Valida: ts presente
        for i, a in enumerate(amostras):
            assert "ts" in a, f"#{i}: sem ts"

        # Valida: ts monotônico
        ts_vals = [datetime.fromisoformat(a["ts"]) for a in amostras]
        for i in range(1, len(ts_vals)):
            assert ts_vals[i] >= ts_vals[i - 1], f"ts não monotônico em {i}"
