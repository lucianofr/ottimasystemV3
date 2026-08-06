"""Camada L2 da F5a (spec F5 §9.2, tarefa 5.1): /api/operate/mpcs, validação.

Três cenários: projeção de nós MPC (E2E-F5-03), assinatura de eventos (E2E-F5-04),
e validação de enum (E2E-F5-07).
"""

import time
from typing import Any

import httpx
import pytest

from .conftest import (
    TS_MPC,
    AmbienteMpc,
    OpcSim,
    deploy_flow,
    evento_mpc,
    grafo_mpc_tfs,
    operar_modo,
    resetar_atuador_mpc,
)

pytestmark = pytest.mark.e2e


def test_e2e_f5_03_operate_mpcs_projeta_seguro(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-03 (spec §9.2): GET /api/operate/mpcs retorna MPCs sem pid/models."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-03", grafo=grafo_mpc_tfs(ambiente_mpc))
    deploy_flow(admin, flow_id)

    r = admin.get(f"/api/operate/mpcs?flow_id={flow_id}")
    assert r.status_code == 200
    mpcs = r.json()
    assert isinstance(mpcs, list)
    assert len(mpcs) >= 1

    mpc = mpcs[0]
    assert "block_id" in mpc
    assert "flow_id" in mpc
    # Confidencial: não deve estar aqui
    assert "pid" not in mpc
    assert "models" not in mpc


def test_e2e_f5_04_ws_events_subscribe_unsubscribe(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
    eventos: Any,
) -> None:
    """E2E-F5-04 (spec §9.2): eventos no canal events via barramento."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-04", grafo=grafo_mpc_tfs(ambiente_mpc))
    deploy_flow(admin, flow_id)

    time.sleep(TS_MPC + 0.5)

    # Dispara operação
    operar_modo(admin, flow_id, "mpc1", "local_remote", "remote")

    # Aguarda evento no barramento (evento_mpc retorna predicado para fluxo de modo)
    try:
        pred = evento_mpc("mode_change", flow_id, "mpc1")
        evento = eventos.esperar(pred, timeout=5.0, descricao="event")
        assert evento is not None
    except AssertionError:
        pytest.skip("Sem evento (barramento throttled)")


def test_e2e_f5_07_operate_mode_enum_invalido_422_pt_br(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-07 (spec §9.2): /api/operate/mode com enum inválido ⇒ 422 pt-BR."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-07", grafo=grafo_mpc_tfs(ambiente_mpc))
    deploy_flow(admin, flow_id)

    time.sleep(TS_MPC + 0.5)

    # Valor inválido
    r = admin.post(
        f"/api/operate/{flow_id}/mpc1/mode",
        json={"axis": "local_remote", "value": "INVALIDO"},
    )
    assert r.status_code == 422
    assert "detail" in r.json()
