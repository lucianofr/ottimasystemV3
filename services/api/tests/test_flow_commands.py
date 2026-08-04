"""Deploy/stop e auditoria de flows (RF-306/405 · ADR-015/020 · spec F3 §5.1/§4.1/§4.3).

Três contratos ficam travados aqui: o comando de intenção sai em `flow.commands` depois do
commit, a auditoria de CRUD sai no `events` com `origin=user:<id>`, e a API **não** emite os
eventos de estado do runtime (§2.2-7).
"""

import json

import pytest
from redis.asyncio import Redis

from ottima_core.bus import CHANNEL_FLOW_COMMANDS
from ottima_core.models import Flow

GRAFO_VAZIO = {"nodes": [], "edges": []}
GRAFO_INVALIDO = {"nodes": []}  # sem 'edges': reprovado já no parse (spec §5.2)
KINDS_DO_RUNTIME = {"flow_deployed", "flow_stopped", "flow_failed"}


@pytest.fixture
async def comandos(redis_url):
    """Assinante de `flow.commands` num segundo cliente, como faz o flow-runtime (§2.2-7).

    Entrega um callable que drena, na ordem de chegada, o que foi publicado desde a chamada
    anterior; o timeout cobre o trânsito pelo Redis real.
    """
    sub = Redis.from_url(redis_url, decode_responses=True)
    pubsub = sub.pubsub()
    await pubsub.subscribe(CHANNEL_FLOW_COMMANDS)
    await pubsub.get_message(timeout=5)  # confirmação do SUBSCRIBE: só então o servidor entrega

    async def recebidos() -> list[dict]:
        msgs = []
        while (
            m := await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        ) is not None:
            msgs.append(json.loads(m["data"]))
        return msgs

    yield recebidos
    await pubsub.aclose()
    await sub.aclose()


async def _projeto(client, headers, nome: str) -> int:
    r = await client.post("/api/projects", json={"name": nome}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _criar_flow(client, headers, pid: int, nome: str) -> dict:
    r = await client.post(
        "/api/flows", json={"project_id": pid, "name": nome, "ts_seconds": 1}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _flow(client, headers, nome: str) -> dict:
    """Flow em projeto próprio: nenhum teste desta mesa depende de vizinhança de projeto."""
    return await _criar_flow(client, headers, await _projeto(client, headers, f"P-{nome}"), nome)


async def _id_do_usuario(client, headers) -> int:
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _marcar_rodando(db_session, flow_id: int) -> None:
    """Estado desejado montado no banco: o assunto do teste é o gatilho do PUT, não o /deploy."""
    linha = await db_session.get(Flow, flow_id)
    linha.desired_state = "running"
    await db_session.commit()
    # `updated_at` tem onupdate SQL: sem o refresh o atributo fica expirado e a leitura
    # síncrona do response_model tentaria IO fora do greenlet.
    await db_session.refresh(linha)


async def _estado_no_banco(db_session, flow_id: int) -> str:
    db_session.expire_all()  # força SELECT: o assert é sobre a linha no banco, não sobre o cache
    linha = await db_session.get(Flow, flow_id)
    return linha.desired_state


def _kinds(recebidos: list[dict]) -> list[str]:
    return [e["payload"]["kind"] for e in recebidos]


# ------------------------------------------------------------------- deploy / stop (§5.1)


async def test_deploy_seta_desired_state_e_publica_comando(
    client, admin_headers, db_session, comandos
):
    flow = await _flow(client, admin_headers, "Deploy")
    await comandos()

    r = await client.post(f"/api/flows/{flow['id']}/deploy", headers=admin_headers)
    assert r.status_code == 202, r.text
    # Corpo vazio: campo de estado aqui seria lido como confirmação, e o comando é intenção
    assert r.content == b""
    assert await _estado_no_banco(db_session, flow["id"]) == "running"

    publicados = await comandos()
    assert len(publicados) == 1, publicados
    esperado_user = f"user:{await _id_do_usuario(client, admin_headers)}"
    assert publicados[0]["cmd"] == "deploy"
    assert publicados[0]["flow_id"] == flow["id"]
    assert publicados[0]["args"] == {}
    assert publicados[0]["user"] == esperado_user
    assert publicados[0]["ts"]


async def test_stop_seta_desired_state_e_publica_comando(
    client, admin_headers, db_session, comandos
):
    flow = await _flow(client, admin_headers, "Stop")
    deploy = await client.post(f"/api/flows/{flow['id']}/deploy", headers=admin_headers)
    assert deploy.status_code == 202, deploy.text
    await comandos()

    r = await client.post(f"/api/flows/{flow['id']}/stop", headers=admin_headers)
    assert r.status_code == 202, r.text
    assert await _estado_no_banco(db_session, flow["id"]) == "stopped"

    publicados = await comandos()
    assert len(publicados) == 1, publicados
    assert publicados[0]["cmd"] == "stop"
    assert publicados[0]["flow_id"] == flow["id"]


async def test_deploy_em_flow_ja_rodando_publica_de_novo(
    client, admin_headers, db_session, comandos
):
    """Idempotência é do runtime (§2.2-7, RNF-05): a API conhece só o estado desejado."""
    flow = await _flow(client, admin_headers, "Redeploy")
    await _marcar_rodando(db_session, flow["id"])
    await comandos()

    r = await client.post(f"/api/flows/{flow['id']}/deploy", headers=admin_headers)
    assert r.status_code == 202, r.text
    assert await _estado_no_banco(db_session, flow["id"]) == "running"
    assert [c["cmd"] for c in await comandos()] == ["deploy"]


async def test_deploy_e_stop_em_flow_inexistente_404_sem_comando(client, admin_headers, comandos):
    await comandos()
    for rota in ("deploy", "stop"):
        r = await client.post(f"/api/flows/987654/{rota}", headers=admin_headers)
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "Flow não encontrado"
    assert await comandos() == []


async def test_deploy_e_stop_exigem_admin_e_nao_publicam(
    client, admin_headers, operator_headers, comandos
):
    flow = await _flow(client, admin_headers, "Rbac")
    await comandos()

    for rota in ("deploy", "stop"):
        proibido = await client.post(f"/api/flows/{flow['id']}/{rota}", headers=operator_headers)
        assert proibido.status_code == 403, proibido.text
        sem_token = await client.post(f"/api/flows/{flow['id']}/{rota}")
        assert sem_token.status_code == 401, sem_token.text
    assert await comandos() == []


async def test_api_nao_emite_evento_de_estado_de_flow(client, admin_headers, eventos, comandos):
    """Contrato §2.2-7: `flow_deployed`/`flow_stopped`/`flow_failed` são do runtime.

    Ele os emite ao materializar o efeito; comando perdido = nada aconteceu = nenhum evento.
    Emitir aqui "para garantir" duplicaria a auditoria e enganaria a lista do frontend, que
    deriva o último estado desses eventos filtrando por `origin=flow:<id>`.
    """
    flow = await _flow(client, admin_headers, "SemAuditoria")
    await eventos()
    await comandos()

    for rota in ("deploy", "stop"):
        r = await client.post(f"/api/flows/{flow['id']}/{rota}", headers=admin_headers)
        assert r.status_code == 202, r.text

    assert [c["cmd"] for c in await comandos()] == ["deploy", "stop"]
    recebidos = await eventos()
    assert KINDS_DO_RUNTIME.isdisjoint(_kinds(recebidos)), recebidos
    # Deploy/stop não são mutação de CRUD: nada de novo no canal de eventos
    assert recebidos == []


# --------------------------------------------------------------- auditoria de CRUD (§4.3)


async def test_post_emite_flow_created(client, admin_headers, eventos):
    pid = await _projeto(client, admin_headers, "Criado")
    await eventos()

    criado = await _criar_flow(client, admin_headers, pid, "Malha")

    recebidos = await eventos()
    assert len(recebidos) == 1, recebidos
    assert recebidos[0]["payload"] == {
        "kind": "flow_created",
        "flow_id": criado["id"],
        "project_id": pid,
        "name": "Malha",
    }
    assert recebidos[0]["origin"] == f"user:{await _id_do_usuario(client, admin_headers)}"
    assert recebidos[0]["severity"] == "info"
    assert "Malha" in recebidos[0]["message"]


async def test_put_em_flow_parado_emite_updated_e_nao_publica_reload(
    client, admin_headers, eventos, comandos
):
    flow = await _flow(client, admin_headers, "Parado")
    await eventos()
    await comandos()

    r = await client.put(
        f"/api/flows/{flow['id']}", json={"graph_json": GRAFO_VAZIO}, headers=admin_headers
    )
    assert r.status_code == 200, r.text

    recebidos = await eventos()
    assert _kinds(recebidos) == ["flow_updated"], recebidos
    assert recebidos[0]["payload"]["flow_id"] == flow["id"]
    # Flow parado: o save é só persistência e o deploy futuro lê o vigente (§4.1-2) —
    # `reload` viraria comando de uma task que não existe
    assert await comandos() == []


async def test_put_em_flow_rodando_emite_updated_e_publica_reload(
    client, admin_headers, db_session, eventos, comandos
):
    flow = await _flow(client, admin_headers, "Hotswap")
    await _marcar_rodando(db_session, flow["id"])
    await eventos()
    await comandos()

    r = await client.put(
        f"/api/flows/{flow['id']}", json={"graph_json": GRAFO_VAZIO}, headers=admin_headers
    )
    assert r.status_code == 200, r.text

    assert _kinds(await eventos()) == ["flow_updated"]
    publicados = await comandos()
    assert len(publicados) == 1, publicados
    assert publicados[0]["cmd"] == "reload"
    assert publicados[0]["flow_id"] == flow["id"]


async def test_put_reprovado_nao_emite_evento_nem_comando(
    client, admin_headers, db_session, eventos, comandos
):
    """422 é "nada aconteceu": flow rodando de propósito, para o `reload` aparecer se vazasse."""
    flow = await _flow(client, admin_headers, "Reprovado")
    await _marcar_rodando(db_session, flow["id"])
    await eventos()
    await comandos()

    r = await client.put(
        f"/api/flows/{flow['id']}", json={"graph_json": GRAFO_INVALIDO}, headers=admin_headers
    )
    assert r.status_code == 422, r.text

    assert await eventos() == []
    assert await comandos() == []


async def test_delete_emite_flow_deleted(client, admin_headers, eventos):
    flow = await _flow(client, admin_headers, "Excluido")
    await eventos()

    r = await client.delete(f"/api/flows/{flow['id']}", headers=admin_headers)
    assert r.status_code == 204, r.text

    recebidos = await eventos()
    assert len(recebidos) == 1, recebidos
    assert recebidos[0]["payload"] == {
        "kind": "flow_deleted",
        "flow_id": flow["id"],
        "project_id": flow["project_id"],
        "name": flow["name"],
    }


async def test_delete_bloqueado_por_409_nao_emite(client, admin_headers, db_session, eventos):
    flow = await _flow(client, admin_headers, "Bloqueado")
    await _marcar_rodando(db_session, flow["id"])
    await eventos()

    r = await client.delete(f"/api/flows/{flow['id']}", headers=admin_headers)
    assert r.status_code == 409, r.text
    assert await eventos() == []


async def test_mutacao_que_falha_no_banco_nao_emite_evento(
    client, admin_headers, db_session, eventos, comandos
):
    """A auditoria sai depois do commit: gravação que morre no banco não audita nada.

    Renomear para um nome já usado no projeto passa a validação e só falha no INSERT/UPDATE
    (a unicidade é do DDL da F1), então é este o caminho que prova a ordem.
    """
    pid = await _projeto(client, admin_headers, "Ordem")
    await _criar_flow(client, admin_headers, pid, "Alfa")
    beta = await _criar_flow(client, admin_headers, pid, "Beta")
    await _marcar_rodando(db_session, beta["id"])
    await eventos()
    await comandos()

    r = await client.put(
        f"/api/flows/{beta['id']}",
        json={"name": "Alfa", "graph_json": GRAFO_VAZIO},
        headers=admin_headers,
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Nome de flow já em uso neste projeto"

    assert await eventos() == []
    assert await comandos() == []
