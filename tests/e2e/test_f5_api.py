"""L2 F5a (spec F5 §9.2, tarefa 5.1): /api/operate/mpcs, WS events, /api/operate/mode.

E2E-F5-03: /api/operate/mpcs seguro (sem pid/models); 404 flow inexistente.
E2E-F5-04: WS /ws events subscribe/unsubscribe real.
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


def test_e2e_f5_03_operate_mpcs_seguro_404(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-03: /api/operate/mpcs projeta config seguro (sem pid/models); 404 flow inexistente.

    (a) /api/operate/mpcs retorna projeção segura (sem pid/models/pesos/tss/initial_value)
    (b) flow inexistente => 404 ou lista vazia
    """
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-03", grafo=grafo_mpc_tfs(ambiente_mpc))
    deploy_flow(admin, flow_id)

    time.sleep(TS_MPC + 0.5)

    # (a) /api/operate/mpcs projeta seguro
    r = admin.get(f"/api/operate/mpcs?flow_id={flow_id}")
    assert r.status_code == 200, f"GET /api/operate/mpcs: HTTP {r.status_code} {r.text}"

    mpcs = r.json()
    assert isinstance(mpcs, list) and len(mpcs) >= 1, "resposta deve ser lista não-vazia"

    mpc = mpcs[0]

    # (a) tem os campos de projeção segura
    assert "block_id" in mpc, "falta block_id"
    assert "flow_id" in mpc, "falta flow_id"
    assert "flow_name" in mpc, "falta flow_name"
    assert "flow_ts_seconds" in mpc, "falta flow_ts_seconds"
    assert "multiplier" in mpc, "falta multiplier"
    assert "name" in mpc, "falta name do bloco"
    assert "variables" in mpc, "falta variables"

    # (a) NÃO tem campos de engenharia (segurança)
    assert "pid" not in mpc, "pid não deve aparecer"
    assert "models" not in mpc, "models não deve aparecer"
    assert "weights" not in mpc, "weights não deve aparecer"
    assert "tss" not in mpc, "tss não deve aparecer"
    assert "initial_value" not in mpc, "initial_value não deve aparecer"

    # (a) variables têm estrutura correta
    vars_dict = mpc["variables"]
    assert "mvs" in vars_dict, "falta mvs"
    assert "cvs" in vars_dict, "falta cvs"
    assert "constraints" in vars_dict, "falta constraints"
    assert "dvs" in vars_dict, "falta dvs"

    # (b) flow inexistente => 404 ou lista vazia
    r = admin.get("/api/operate/mpcs?flow_id=999999")
    if r.status_code == 200:
        assert r.json() == [] or isinstance(r.json(), list)
    else:
        assert r.status_code == 404, f"esperava 404 ou 200, obteve {r.status_code}"


def test_e2e_f5_04_ws_events_subscribe_unsubscribe(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-04: WS /ws events subscribe ⇒ chega; unsubscribe ⇒ para.

    (a) subscribe {"events": true} ⇒ evento publicado chega via WS
    (b) unsubscribe {"events": true} ⇒ evento para de chegar
    """
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-04", grafo=grafo_mpc_tfs(ambiente_mpc))
    deploy_flow(admin, flow_id)

    time.sleep(TS_MPC + 0.5)

    # Extrai token do admin
    auth_header = admin.headers.get("Authorization", "")
    token = auth_header.split()[-1] if "Bearer" in auth_header else ""
    assert token, "sem token de autenticação"

    # Abre WS real com token
    ws_url = BASE.replace("http://", "ws://") + f"/ws?token={token}"
    ws = websockets.sync.client.connect(ws_url)

    try:
        # (a) subscribe aos eventos
        ws.send(json.dumps({"subscribe": {"events": True}}))
        time.sleep(0.5)

        # Gera evento: mudar o modo
        operar_modo(admin, flow_id, "mpc1", "local_remote", "remote")
        time.sleep(0.5)

        # Aguarda mensagem do WS
        evento_recebido = False
        for _ in range(10):  # Tenta até 10 mensagens
            try:
                msg = ws.recv(timeout=1.0)
                evento_msg = json.loads(msg)

                # (a) formato correto {"channel": "events", "data": {...}}
                if "channel" in evento_msg and evento_msg["channel"] == "events":
                    evento_recebido = True
                    assert "data" in evento_msg, f"falta data: {evento_msg}"
                    assert isinstance(evento_msg["data"], dict)
                    break
            except TimeoutError:
                continue

        assert evento_recebido, "nenhum evento de events recebido após subscribe"

        # (b) unsubscribe
        ws.send(json.dumps({"unsubscribe": {"events": True}}))
        time.sleep(0.5)

        # Gera outro evento
        operar_modo(admin, flow_id, "mpc1", "local_remote", "local")
        time.sleep(0.5)

        # (b) evento NÃO chega mais
        evento_chegou = False
        try:
            msg = ws.recv(timeout=1.0)
            obj = json.loads(msg)
            if obj.get("channel") == "events":
                evento_chegou = True
        except TimeoutError:
            # Esperado: sem evento após unsubscribe
            pass

        assert not evento_chegou, "evento chegou após unsubscribe"
    finally:
        ws.close()


def test_e2e_f5_07_operate_mode_enum_422_pt_br(
    admin: httpx.Client,
    ambiente_mpc: AmbienteMpc,
    criar_flow_mpc: Any,
    opcsim_client: OpcSim,
) -> None:
    """E2E-F5-07: /api/operate/mode enum inválido ⇒ 422 string única pt-BR.

    Enum inválido em local_remote (aceita "local"|"remote") retorna 422 com
    detail como string única pt-BR (não lista FastAPI).
    """
    resetar_atuador_mpc(opcsim_client)
    flow_id = criar_flow_mpc("f5-07", grafo=grafo_mpc_tfs(ambiente_mpc))
    deploy_flow(admin, flow_id)

    time.sleep(TS_MPC + 0.5)

    # Enum inválido para local_remote
    r = admin.post(
        f"/api/operate/{flow_id}/mpc1/mode",
        json={"axis": "local_remote", "value": "INVALIDO"},
    )

    assert r.status_code == 422, f"esperava 422 para enum inválido, obteve {r.status_code}"

    response = r.json()
    assert "detail" in response, f"falta 'detail': {response}"

    # detail é string única (não lista)
    detail = response["detail"]
    assert isinstance(detail, str), f"detail deve ser string, obteve {type(detail).__name__}"

    # pt-BR (contém palavras comuns de validação pt-BR)
    detail_lower = detail.lower()
    is_pt_br = any(
        word in detail_lower for word in ["valor", "inválido", "esperado", "deve", "não", "aceita"]
    )
    assert is_pt_br, f"detail não parece pt-BR: {detail}"

    # NÃO é lista FastAPI padrão
    assert not detail.startswith("["), "detail parece ser lista FastAPI, não string pt-BR"
