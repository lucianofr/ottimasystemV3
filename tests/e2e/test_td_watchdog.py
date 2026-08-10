"""L2 do fechamento de tech debts — conexão sem watchdog é somente leitura (TD-004).

Cenário E2E-TD-06. `writes.py` recusa TODA escrita numa conexão sem watchdog, e até esta
entrega o único sinal era um `write_rejected` de severidade warning: numa MV direta o bloco
MPC seguia com `u_applied = _mv_last`, ACREDITANDO que o comando chegou. O modelo interno
divergia da planta sem detecção e sem alarme (na campanha: 10 min com 4 escritas recusadas
por varredura).

A causa é 100% estática — está na configuração da conexão — então ela é barrada onde dá
para barrar: aviso no salvar e recusa no arme. O gate aqui prova as duas pontas.
"""

from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from opcsim import NODE_SINE, NODE_W_FLOAT

from .conftest import (
    OPCSIM_URL,
    RUN_ID,
    EventStream,
    assinar_mpc_state,
    deploy_flow,
    esperar_conexao,
    evento_mpc,
    operar_modo,
)

pytestmark = pytest.mark.e2e

BLOCO = "mpc_sem_wd"


@pytest.fixture(scope="module")
def conexao_sem_watchdog(admin: httpx.Client) -> Iterator[dict[str, Any]]:
    """Projeto ativo com uma conexão SEM watchdog e o par de tags r/w que o cenário usa.

    Escopo de módulo, mesmo padrão de `ambiente_mpc`: o teardown devolve a ativação à
    sentinela antes de excluir, porque excluir o projeto ativo é 409.
    """
    from .conftest import _ativar_sentinela  # noqa: PLC0415

    sufixo = f"td-wd-{RUN_ID}"
    resposta = admin.post("/api/projects", json={"name": f"td04-{sufixo}"})
    assert resposta.status_code == 201, f"criação do projeto: HTTP {resposta.status_code}"
    projeto = resposta.json()
    try:
        assert admin.post(f"/api/projects/{projeto['id']}/activate").status_code == 200
        nome_conexao = f"opcsim-sem-wd-{sufixo}"
        resposta = admin.post(
            "/api/connections",
            json={
                "project_id": projeto["id"],
                "name": nome_conexao,
                "endpoint": OPCSIM_URL,
                "security_policy": "none",
                "security_mode": "none",
                "auth_mode": "anonymous",
            },
        )
        assert resposta.status_code == 201, (
            f"criação da conexão sem watchdog: HTTP {resposta.status_code} {resposta.text}"
        )
        conn_id = int(resposta.json()["id"])
        assert resposta.json()["watchdog_read_node_id"] is None, (
            "a conexão do cenário precisa nascer SEM watchdog"
        )
        tags: dict[str, int] = {}
        for nome, node_id, direcao in (
            ("cv-fonte", NODE_SINE, "r"),
            ("mv-destino", NODE_W_FLOAT, "w"),
        ):
            criada = admin.post(
                "/api/tags",
                json={
                    "connection_id": conn_id,
                    "name": f"{nome}-{sufixo}",
                    "node_id": node_id,
                    "direction": direcao,
                    "data_type": "float",
                },
            )
            assert criada.status_code == 201, (
                f"criação da tag {nome}: HTTP {criada.status_code} {criada.text}"
            )
            tags[nome] = int(criada.json()["id"])
        # Sem watchdog não há `watchdog_alive` para esperar: a conexão sobe do mesmo jeito e
        # é justamente por isso que ela passa despercebida hoje.
        esperar_conexao(conn_id, watchdog_alive=None)
        yield {"project_id": projeto["id"], "conn_id": conn_id, "nome": nome_conexao, **tags}
    finally:
        _ativar_sentinela(admin)
        admin.delete(f"/api/projects/{projeto['id']}")


def grafo_mv_direta(tag_cv: int, tag_mv: int) -> dict[str, Any]:
    """MPC com UMA MV direta cuja saída vai a um `opc_write` — o caminho em que a recusa de
    escrita é invisível para o bloco (com `pid`, quem recusa é a tag do PID)."""
    mpc = {
        "id": BLOCO,
        "type": "mpc",
        "position": {"x": 0.0, "y": 0.0},
        "data": {
            "exec_order": 2,
            "name": "MPC sem watchdog",
            "multiplier": 1,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_1",
                        "name": "MV direta",
                        "eu": "%",
                        "limits": {"min": 0.0, "max": 100.0},
                        "du_max": 5.0,
                        "initial_value": 0.0,
                    }
                ],
                "cvs": [
                    {
                        "id": "cv_1",
                        "name": "CV",
                        "eu": "C",
                        "kind": "selfreg",
                        "tss": 10.0,
                        "weight": 1.0,
                        "sp_limits": {"min": 0.0, "max": 100.0},
                    }
                ],
                "constraints": [],
                "dvs": [],
            },
            "models": {
                "cv_1": {
                    "mv_1": {
                        "enabled": True,
                        "params": {"K": 1.0, "tau1": 2.0, "tau2": 0.5, "theta": 0.0},
                    }
                }
            },
        },
    }
    nodes = [
        {
            "id": "cv_fonte",
            "type": "opc_read",
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": 1, "tag_id": tag_cv},
        },
        mpc,
        {
            "id": "mv_destino",
            "type": "opc_write",
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": 3, "tag_id": tag_mv},
        },
    ]
    edges = [
        {
            "id": "e1",
            "source": "cv_fonte",
            "sourceHandle": "out",
            "target": BLOCO,
            "targetHandle": "cv_1",
        },
        {
            "id": "e2",
            "source": BLOCO,
            "sourceHandle": "mv_1",
            "target": "mv_destino",
            "targetHandle": "in",
        },
    ]
    return {"nodes": nodes, "edges": edges}


@pytest.fixture
def criar_flow_sem_watchdog(
    admin: httpx.Client, conexao_sem_watchdog: dict[str, Any]
) -> Iterator[Callable[[dict[str, Any]], tuple[int, list[str]]]]:
    """Cria o flow e devolve `(flow_id, warnings do PUT)`; teardown para e exclui."""
    criados: list[int] = []

    def criar(grafo: dict[str, Any]) -> tuple[int, list[str]]:
        resposta = admin.post(
            "/api/flows",
            json={
                "project_id": conexao_sem_watchdog["project_id"],
                "name": f"td-06-{RUN_ID}",
                "ts_seconds": 1,
            },
        )
        assert resposta.status_code == 201, f"criação do flow: HTTP {resposta.status_code}"
        flow_id = int(resposta.json()["id"])
        criados.append(flow_id)
        salvo = admin.put(f"/api/flows/{flow_id}", json={"graph_json": grafo})
        assert salvo.status_code == 200, f"PUT do grafo: HTTP {salvo.status_code} {salvo.text}"
        return flow_id, list(salvo.json()["warnings"])

    try:
        yield criar
    finally:
        for flow_id in reversed(criados):
            admin.post(f"/api/flows/{flow_id}/stop")
            admin.delete(f"/api/flows/{flow_id}")


def test_e2e_td_06_salvar_avisa_e_armar_e_recusado(
    admin: httpx.Client,
    conexao_sem_watchdog: dict[str, Any],
    criar_flow_sem_watchdog: Callable[[dict[str, Any]], tuple[int, list[str]]],
    eventos: EventStream,
) -> None:
    """E2E-TD-06: o salvar avisa e o arme é recusado — nas duas pontas, antes da planta."""
    grafo = grafo_mv_direta(conexao_sem_watchdog["cv-fonte"], conexao_sem_watchdog["mv-destino"])
    flow_id, avisos = criar_flow_sem_watchdog(grafo)

    nome_conexao = conexao_sem_watchdog["nome"]
    casou = [aviso for aviso in avisos if nome_conexao in aviso and "watchdog" in aviso]
    assert casou, (
        f"o PUT não avisou sobre a conexão '{nome_conexao}' sem watchdog; avisos: {avisos}"
    )

    with assinar_mpc_state(admin, flow_id, BLOCO) as fluxo:
        deploy_flow(admin, flow_id)
        fluxo.esperar(
            lambda estado: estado["status"]["solver"] != "building",
            timeout=60.0,
            descricao="host do MPC pronto",
        )

        operar_modo(admin, flow_id, BLOCO, "local_remote", "remote")
        falha = eventos.esperar(
            evento_mpc("mpc_arm_failed", flow_id, BLOCO),
            timeout=30.0,
            descricao="mpc_arm_failed por alvo de escrita sem watchdog",
        )
        assert falha["payload"]["reason"] == "write_target_sem_watchdog", (
            f"motivo inesperado no arm_failed: {falha['payload']}"
        )

        # O bloco não pode ficar em REMOTO nem por um quadro: em REMOTO ele passaria a
        # comandar contra uma conexão que recusa toda escrita.
        quadros = fluxo.coletar(
            quantidade=4,
            timeout=30.0,
            descricao="quadros depois da tentativa de arme",
        )

    estados = [quadro["modes"]["local_remote"] for quadro in quadros]
    assert all(estado == "local" for estado in estados), (
        f"o bloco armou apesar do alvo de escrita sem watchdog: {estados}"
    )
