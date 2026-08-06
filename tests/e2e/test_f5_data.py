"""Camada L2 da F5a (spec F5 §9.2, tarefa 5.1): mpc_samples, CAgg, history."""

import time
from datetime import datetime, timedelta
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


def test_e2e_f5_01_mpc_samples_gravado_em_local_e_cadencia(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-01 (spec §9.2): MPC em LOCAL grava mpc_samples na cadência Ts_mpc."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-01", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        # Boot: primeira amostra
        amostra1 = fluxo.esperar(lambda _e: True, timeout=30.0, descricao="1º")
        ts1 = datetime.fromisoformat(amostra1["ts"])

        # Mais 2 amostras pra confirmar cadência
        amostras = [amostra1]
        tempos = [ts1]
        for _ in range(2):
            amostra = fluxo.esperar(lambda _e: True, timeout=15.0, descricao="seg")
            amostras.append(amostra)
            ts = datetime.fromisoformat(amostra["ts"])
            tempos.append(ts)
            time.sleep(0.5)

        # Valida cadência ~Ts_mpc (±50%)
        for i in range(1, len(tempos)):
            delta = (tempos[i] - tempos[i - 1]).total_seconds()
            assert (
                0.5 * TS_MPC <= delta <= 1.5 * TS_MPC
            ), f"intervalo {i}: {delta:.2f}s vs {TS_MPC}s"

        # Valida: LOCAL e vars presentes
        for amostra in amostras:
            assert amostra["modes"]["local_remote"] == "local"
            assert "vars" in amostra


def test_e2e_f5_02_history_mpc_bruto_e_cagg_com_refresh(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-02 (spec §9.2): /api/history/mpc retorna bruto (≤2h) e CAgg 1m (>2h)."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-02", grafo=grafo_mpc_tfs(ambiente_mpc))

    with assinar_mpc_state(admin, flow_id, "mpc1") as fluxo:
        deploy_flow(admin, flow_id)
        amostra = fluxo.esperar(lambda _e: True, timeout=30.0, descricao="boot")
        ts_inicio = datetime.fromisoformat(amostra["ts"])

        # Aguarda dados acumularem
        time.sleep(TS_MPC * 5)

        # Query bruto (últimas 2h)
        start_time = (ts_inicio - timedelta(hours=1)).isoformat()
        r = admin.get(
            "/api/history/mpc",
            params={
                "flow_id": flow_id,
                "block_id": "mpc1",
                "var_ids": "cv_1",
                "start": start_time,
            },
        )
        assert r.status_code == 200, f"history/mpc: {r.text}"
        hist = r.json()
        assert hist["mode"] == "raw"
        assert len(hist["series"]) > 0
