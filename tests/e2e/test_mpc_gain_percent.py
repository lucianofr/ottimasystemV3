"""E2E — ganho %/% no sistema fechado (RF-602 revisado, RF-609).

Dois flows MPC↔TFS idênticos exceto o `span` da MV (100 vs 50), mesmo `K=1` (%/%): o ganho
efetivo em EU dobra no flow B. O observável determinístico é o vetor `costs` do SSTO
(publicado no `mpc.state` de toda execução em AUTO com variável otimizada): com a CV em
`maximize`, o preço da linha é projetado por `c_row·G` — e `G` é o ganho de regime JÁ
convertido (`K × span_cv/span_mv`), então `costs["mv_pid"]` de B é 2× o de A, sem
depender de dinâmica de malha nem de tolerância de solver dinâmico. O 2× exato do ganho é
provado em unidade (`test_gain_percent_span.py`); aqui a prova é de sistema: a conversão
chega inteira no solve real.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest

from opcsim import NODE_WD_FROM_SYSTEM_2, NODE_WD_TO_SYSTEM_2

from .conftest import (
    AmbienteMpc,
    armar_auto_com_retentativa,
    armar_remoto_direto,
    assinar_mpc_state,
    deploy_flow,
    esperar_flow_watchdog,
    grafo_mpc_tfs,
    resetar_atuador_mpc,
)

pytestmark = pytest.mark.e2e


def _grafo_com_span(ambiente: AmbienteMpc, span_mv: float) -> dict[str, Any]:
    """Grafo malha padrão, com span da MV parametrizado e CV em `maximize` (liga o SSTO)."""
    grafo = grafo_mpc_tfs(ambiente)
    dados = grafo["nodes"][3]["data"]  # node mpc1
    for mv in dados["variables"]["mvs"]:
        mv["span"] = span_mv
    for cv in dados["variables"]["cvs"]:
        cv["objective"] = "maximize"
    return grafo


def _custo_mv_pid(admin: httpx.Client, flow_id: int, block_id: str, fluxo: Any) -> float:
    """Arma até AUTO e devolve o `costs[mv_pid]` da primeira execução do SSTO (o runtime
    publica o `ssto` uma vez por ciclo e depois `null` — o `esperar` filtra o quadro cheio)."""
    armar_remoto_direto(admin, fluxo, flow_id, block_id)
    armar_auto_com_retentativa(admin, fluxo, flow_id, block_id)
    quadro = fluxo.esperar(
        lambda e: e.get("ssto") is not None and "mv_pid" in e["ssto"]["costs"],
        timeout=30.0,
        descricao="primeira execução do SSTO com costs",
    )
    return float(quadro["ssto"]["costs"]["mv_pid"])


def _criar_flow_b(admin: httpx.Client, ambiente: AmbienteMpc, span_mv: float) -> int:
    """Flow B por fora da fábrica: a fábrica amarra o watchdog ao par 1, já ocupado pelo
    flow A — dois flows no mesmo par não sobem juntos no rig. O opcsim expõe um segundo
    par (`*_2`), como na planta real (cada flow tem o seu)."""
    r = admin.post(
        "/api/flows",
        json={
            "project_id": ambiente.project_id,
            "name": f"gain-b-{uuid4().hex[:8]}",
            "ts_seconds": 2,
        },
    )
    assert r.status_code == 201, r.text
    flow_id = int(r.json()["id"])
    r = admin.put(f"/api/flows/{flow_id}", json={"graph_json": _grafo_com_span(ambiente, span_mv)})
    assert r.status_code == 200, r.text
    r = admin.put(
        f"/api/flows/{flow_id}",
        json={
            "watchdog_enabled": True,
            "watchdog_connection_id": ambiente.conn_id,
            "watchdog_read_node_id": NODE_WD_TO_SYSTEM_2,
            "watchdog_write_node_id": NODE_WD_FROM_SYSTEM_2,
            "watchdog_period_ms": 1000,
        },
    )
    assert r.status_code == 200, r.text
    esperar_flow_watchdog(flow_id, ambiente.conn_id)
    return flow_id


def test_ganho_percentual_dobra_com_span_da_mv(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: Any,
) -> None:
    resetar_atuador_mpc(opcsim_client)
    flow_a = criar_flow_mpc("gain-a", grafo=_grafo_com_span(ambiente_mpc, 100.0))
    flow_b = _criar_flow_b(admin, ambiente_mpc, 50.0)
    try:
        with assinar_mpc_state(admin, flow_a, "mpc1") as fluxo_a:
            deploy_flow(admin, flow_a)
            fluxo_a.esperar(
                lambda e: e["modes"]["local_remote"] == "local",
                timeout=30.0,
                descricao="flow A em LOCAL",
            )
            custo_a = _custo_mv_pid(admin, flow_a, "mpc1", fluxo_a)

        with assinar_mpc_state(admin, flow_b, "mpc1") as fluxo_b:
            deploy_flow(admin, flow_b)
            fluxo_b.esperar(
                lambda e: e["modes"]["local_remote"] == "local",
                timeout=30.0,
                descricao="flow B em LOCAL",
            )
            custo_b = _custo_mv_pid(admin, flow_b, "mpc1", fluxo_b)
    finally:
        admin.post(f"/api/flows/{flow_b}/stop")
        admin.delete(f"/api/flows/{flow_b}")

    # c = −(1/span_cv)·G (maximize): span_mv 50 ⇒ G dobra ⇒ |custo| dobra (sinal preservado).
    assert custo_a < 0
    assert custo_b == pytest.approx(2.0 * custo_a, rel=0.01)
