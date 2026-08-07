"""L2 F5a (spec F5 9.2): /api/operate/mpcs, WS events, validação enum.

E2E-F5-03: /api/operate/mpcs seguro; 404 flow inexistente.
E2E-F5-04: WS /ws real, subscribe/unsubscribe eventos.
E2E-F5-07: /api/operate/mode enum inválido ⇒ 422 pt-BR string.
"""

import json
import time
from typing import Any

import httpx
import pytest
import websockets.sync.client

from .conftest import (
    BASE,
    TS_MPC,
    AmbienteMpc,
    OpcSim,
    deploy_flow,
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
    """I-01: /api/operate/mpcs sem pid/models; 404 flow inexistente."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-03", grafo=grafo_mpc_tfs(ambiente_mpc))
    deploy_flow(admin, flow_id)

    # (a) Projeção segura
    r = admin.get(f"/api/operate/mpcs?flow_id={flow_id}")
    assert r.status_code == 200
    mpcs = r.json()
    assert isinstance(mpcs, list) and len(mpcs) >= 1
    mpc = mpcs[0]
    assert "block_id" in mpc
    assert "flow_id" in mpc
    assert "pid" not in mpc
    assert "models" not in mpc

    # (b) I-01: 404 flow inexistente
    r = admin.get("/api/operate/mpcs?flow_id=999999")
    assert r.status_code == 404


def test_e2e_f5_04_ws_events_subscribe_unsubscribe(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """C-03: WS /ws real, subscribe/unsubscribe eventos. Sem skips."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-04", grafo=grafo_mpc_tfs(ambiente_mpc))
    deploy_flow(admin, flow_id)

    time.sleep(TS_MPC + 0.5)

    # Extrai token
    auth_header = admin.headers.get("Authorization", "")
    token = auth_header.split()[-1] if "Bearer" in auth_header else ""
    assert token, "sem token"

    # Abre WS real
    ws_url = BASE.replace("http://", "ws://") + f"/ws?token={token}"
    ws = websockets.sync.client.connect(ws_url)

    try:
        # Subscribe a eventos
        ws.send(json.dumps({"subscribe": {"events": True}}))
        time.sleep(0.5)

        # Dispara operação pra gerar evento
        operar_modo(admin, flow_id, "mpc1", "local_remote", "remote")
        time.sleep(0.5)

        # Aguarda evento chegar
        ws.settimeout(5.0)
        msg = ws.recv()
        evento = json.loads(msg)
        assert (
            "channel" in evento and evento["channel"] == "events"
        ), f"evento inválido: {evento}"

        # Unsubscribe
        ws.send(json.dumps({"unsubscribe": {"events": True}}))
        time.sleep(0.5)

        # Dispara outra operação — não deve chegar evento
        operar_modo(admin, flow_id, "mpc1", "local_remote", "local")
        time.sleep(0.5)

        # Tenta receber (deve dar timeout)
        ws.settimeout(1.0)
        try:
            ws.recv()
            pytest.fail("Evento após unsubscribe")
        except TimeoutError:
            # Esperado: sem unsubscribe, sem eventos
            pass
    finally:
        ws.close()


def test_e2e_f5_07_operate_mode_enum_invalido_422_pt_br(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """I-02: /api/operate/mode enum inválido ⇒ 422 string pt-BR."""
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-07", grafo=grafo_mpc_tfs(ambiente_mpc))
    deploy_flow(admin, flow_id)

    time.sleep(TS_MPC + 0.5)

    # Enum inválido
    r = admin.post(
        f"/api/operate/{flow_id}/mpc1/mode",
        json={"axis": "local_remote", "value": "INVALIDO"},
    )
    assert r.status_code == 422

    response = r.json()
    assert "detail" in response

    # I-02: string pt-BR, não lista
    detail = response["detail"]
    assert isinstance(detail, str), f"detail tipo={type(detail)}"
    assert len(detail) > 0
    # Verifica se tem caracteres pt-BR
    assert (
        "valor" in detail.lower()
        or "inválido" in detail.lower()
        or "esperado" in detail.lower()
    ), f"não pt-BR: {detail}"
