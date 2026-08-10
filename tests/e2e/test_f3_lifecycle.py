"""Camada L2 da F3 (spec §7.2): ciclo de vida dos flows e canal ao vivo do canvas.

Cobre E2E-F3-07..09 — `comm_failure` derrubando só os flows da conexão caída (RF-207),
`project_activated` parando todos e o boot parado do runtime depois de um restart (RF-101/104,
ADR-017), e o WebSocket `/ws` com `ports` e recusa de token inválido (RF-305). Os cenários de
motor e blocos estão em `test_f3_engine.py`.

Este é o único módulo que reinicia um serviço do compose, e só o `flow-runtime`: é o gatilho do
boot parado que o E2E-F3-08 precisa provar.
"""

import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
import redis
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

from ottima_core.bus import (
    KIND_FLOW_FAILED,
    KIND_FLOW_RESUMED,
    KIND_FLOW_STOPPED,
    channel_flow_status,
)

from .conftest import BASE, RUN_ID, Ambiente, EventStream, compose, esperar_conexao
from .f3_support import (
    aresta,
    assinantes_de_status,
    ativar_projeto,
    bloco,
    de_varredura,
    deploy,
    esperar_runtime_saudavel,
    esperar_todos,
    evento_de_flow,
    fabrica_de_flows,
    flow_no_runtime,
    grafo_script_tfs,
    id_da_sentinela,
    montar_grafo,
)

pytestmark = pytest.mark.e2e


@pytest.fixture
def assinar_status(redis_bus: redis.Redis) -> Iterator[Any]:
    yield from assinantes_de_status(redis_bus)


@pytest.fixture
def criar_flow(admin: httpx.Client, projeto_com_conexao: Ambiente) -> Iterator[Any]:
    yield from fabrica_de_flows(admin, projeto_com_conexao)


# --------------------------------------------------------------------------------------
# E2E-F3-07 — RF-207: comm_failure derruba só os flows da conexão
# --------------------------------------------------------------------------------------


def test_e2e_f3_07_comm_failure_derruba_so_os_flows_da_conexao(
    admin: httpx.Client,
    projeto_com_conexao: Ambiente,
    criar_flow: Any,
    eventos: EventStream,
    assinar_status: Any,
    congelar_watchdog: Callable[[bool], None],
) -> None:
    """RF-207/ADR-009: flow com tag vai a `failed`; flow puro segue; a comunicação voltando
    retoma o flow sozinho (ADR-025/TD-005)."""
    ambiente = projeto_com_conexao
    esperar_conexao(ambiente.conn_id, timeout=120.0)

    grafo_com_tag = montar_grafo(
        [
            bloco("leitura", "opc_read", 1, tag_id=ambiente.static),
            bloco("escrita", "opc_write", 2, tag_id=ambiente.w_float),
        ],
        [aresta("leitura", "out", "escrita", "in")],
    )
    flow_tag = criar_flow("f3-07-com-tag", grafo=grafo_com_tag)
    flow_puro = criar_flow("f3-07-sem-tag", grafo=grafo_script_tfs(1.0))
    status_tag = assinar_status(flow_tag)
    status_puro = assinar_status(flow_puro)

    deploy(admin, flow_tag)
    deploy(admin, flow_puro)
    status_tag.esperar(de_varredura, timeout=30.0, descricao="flow com tag varrendo")
    status_puro.esperar(de_varredura, timeout=30.0, descricao="flow Script+TFS varrendo")

    congelar_watchdog(True)
    falha = eventos.esperar(
        evento_de_flow(KIND_FLOW_FAILED, flow_tag),
        timeout=60.0,
        descricao="flow_failed do flow que referencia tag da conexão",
    )
    assert falha["severity"] == "alarm"
    assert falha["payload"]["reason"] == "comm_failure"
    parada = status_tag.esperar(
        lambda s: s["state"] != "running",
        timeout=30.0,
        descricao="flow.status do flow derrubado",
    )
    assert parada["state"] == "failed"
    assert parada["ports"] == {}, "transição publica `ports` vazio (§4.2)"

    # O flow sem tag nenhuma não pertence ao conjunto de conn_ids da conexão caída (§2.2-8).
    seguindo = status_puro.coletar(
        quantidade=4, timeout=30.0, descricao="flow Script+TFS após a queda da conexão"
    )
    assert all(a["state"] == "running" for a in seguindo), (
        "comm_failure derrubou flow que não referencia a conexão"
    )

    congelar_watchdog(False)
    esperar_conexao(ambiente.conn_id, timeout=180.0)

    # ADR-025 (TD-005): `comm_restored` com `desired_state == "running"` retoma o flow SEM
    # comando manual. Antes desta decisão o assert aqui era o oposto (`silencio() == []`,
    # "só deploy retoma"): na campanha de 14 h isso obrigou um supervisor externo a religar
    # os flows a cada piscada de OPC. O ADR-017 segue valendo para BOOT, que é outro caminho.
    eventos.esperar(
        evento_de_flow(KIND_FLOW_RESUMED, flow_tag),
        timeout=120.0,
        descricao="flow_resumed da retomada automática pós comm_restored",
    )
    retomado = status_tag.esperar(
        de_varredura, timeout=60.0, descricao="varredura após a retomada automática"
    )
    assert retomado["state"] == "running"
    assert flow_no_runtime(flow_tag)["state"] == "running"
    print("\nE2E-F3-07: failed(comm_failure) só no flow da conexão; retomada automática")


# --------------------------------------------------------------------------------------
# E2E-F3-08 — project_activated e boot parado (RF-101/104, ADR-017)
# --------------------------------------------------------------------------------------


def test_e2e_f3_08_project_activated_para_tudo_e_boot_fica_parado(
    admin: httpx.Client,
    projeto_com_conexao: Ambiente,
    criar_flow: Any,
    eventos: EventStream,
    assinar_status: Any,
) -> None:
    """RF-101/104: ativar projeto para todos os flows; restart do runtime não sobe nenhum."""
    ambiente = projeto_com_conexao
    primeiro = criar_flow("f3-08-a", grafo=grafo_script_tfs(1.0))
    segundo = criar_flow("f3-08-b", grafo=grafo_script_tfs(2.0))
    status = {flow_id: assinar_status(flow_id) for flow_id in (primeiro, segundo)}

    for flow_id in (primeiro, segundo):
        deploy(admin, flow_id)
    for flow_id, fluxo in status.items():
        fluxo.esperar(de_varredura, timeout=30.0, descricao=f"flow {flow_id} varrendo")

    ativar_projeto(admin, id_da_sentinela(admin))
    paradas = esperar_todos(
        eventos,
        {
            f"flow_stopped:{flow_id}": evento_de_flow(KIND_FLOW_STOPPED, flow_id)
            for flow_id in (primeiro, segundo)
        },
        timeout=60.0,
        descricao="flow_stopped de todos os flows após project_activated",
    )
    for evento in paradas.values():
        assert evento["payload"]["reason"] == "project_activated"
    for flow_id, fluxo in status.items():
        parada = fluxo.esperar(
            lambda s: s["state"] != "running",
            timeout=30.0,
            descricao=f"flow.status stopped do flow {flow_id}",
        )
        assert parada["state"] == "stopped"

    # RF-306/ADR-017: o runtime materializou a parada e não tocou o banco. `desired_state`
    # continua 'running' — é exibição, e é justamente o que o boot não pode auto-aplicar.
    for flow_id in (primeiro, segundo):
        assert admin.get(f"/api/flows/{flow_id}").json()["desired_state"] == "running"

    compose("restart", "flow-runtime", timeout=180.0)
    saude = esperar_runtime_saudavel()
    rodando = {
        flow_id: dados for flow_id, dados in saude["flows"].items() if dados["state"] == "running"
    }
    assert rodando == {}, f"o boot subiu flow apesar do ADR-017: {rodando}"
    for flow_id in (primeiro, segundo):
        assert str(flow_id) not in saude["flows"], "flow conhecido pelo runtime logo após o boot"
    for flow_id, fluxo in status.items():
        ocioso = fluxo.silencio()
        assert ocioso == [], f"flow {flow_id} varrendo depois do restart: {ocioso}"
    print(
        f"\nE2E-F3-08: project_activated parou {len(paradas)} flows; após o restart "
        f"health.flows={saude['flows']} com desired_state='running' no banco"
    )

    # Devolve a ativação ao projeto do módulo: os cenários seguintes precisam dele ativo.
    ativar_projeto(admin, ambiente.project_id)
    esperar_conexao(ambiente.conn_id, timeout=180.0)


def abrir_ws(url: str) -> Any:
    """Abre o WebSocket ou falha com o diagnóstico, em vez de um traceback de handshake.

    A porta publicada é a do nginx (ADR-023), único caminho do host até a API: se o upgrade
    não acontece ali, o `/ws` do spec §5.3 não existe para cliente nenhum, canvas incluído.
    """
    try:
        return connect(url, open_timeout=15)
    except InvalidStatus as erro:
        raise AssertionError(
            f"o nginx recusou o upgrade com HTTP {erro.response.status_code} em {url}; "
            "spec §5.3 exige `GET /ws` na porta publicada"
        ) from None


# --------------------------------------------------------------------------------------
# E2E-F3-09 — WebSocket /ws (RF-305)
# --------------------------------------------------------------------------------------


def test_e2e_f3_09_websocket_entrega_ports_e_recusa_token_invalido(
    admin: httpx.Client, criar_flow: Any, assinar_status: Any
) -> None:
    """RF-305/§5.3: `subscribe` recebe `flow.status` com `ports`; token inválido é recusado."""
    flow_id = criar_flow("f3-09-ws", grafo=grafo_script_tfs(1.0))
    status = assinar_status(flow_id)
    deploy(admin, flow_id)
    status.esperar(de_varredura, timeout=30.0, descricao="flow do cenário do WS varrendo")

    url = f"{BASE.replace('http://', 'ws://').rstrip('/')}/ws"
    token = admin.headers["Authorization"].removeprefix("Bearer ")
    canal = channel_flow_status(flow_id)

    with abrir_ws(f"{url}?token={token}") as ws:
        ws.send(json.dumps({"subscribe": {"flow_status": [flow_id]}}))
        limite = time.monotonic() + 30.0
        quadro = None
        while time.monotonic() < limite:
            candidato = json.loads(ws.recv(timeout=15))
            if candidato.get("channel") == canal and candidato["data"]["ports"]:
                quadro = candidato
                break
        assert quadro is not None, "nenhum flow.status com `ports` chegou pelo WebSocket"

    dados = quadro["data"]
    assert dados["state"] == "running"
    assert set(dados["ports"]) == {"calculo", "planta"}, dados["ports"]
    assert dados["ports"]["planta"]["y1"]["ok"] is True

    with pytest.raises(ConnectionClosed) as recusa:
        with abrir_ws(f"{url}?token=token-invalido-{RUN_ID}") as ws:
            ws.recv(timeout=15)
    assert recusa.value.rcvd is not None and recusa.value.rcvd.code == 1008, (
        f"esperado fechamento 1008 por token inválido: {recusa.value!r}"
    )
    print("\nE2E-F3-09: fanout com `ports` entregue e token inválido fechado com 1008")
