"""Auditoria da API no canal `events` (ADR-020, spec F2 §7.2): o que emite e o que não emite.

Os eventos daqui são também a dica de reconciliação do opc-worker (spec F2 §2.2-1): `kind`
errado ou evento sobre mutação que falhou envenenaria a reconciliação, por isso cada teste
assere o payload inteiro e não só a chegada da mensagem.
"""

from redis.asyncio import Redis

from ottima_api.deps import get_redis

CONEXAO = {"name": "CLP 1", "endpoint": "opc.tcp://10.0.0.5:4840"}
TAG = {"name": "TI-101", "node_id": "ns=2;s=TI-101", "direction": "r", "data_type": "float"}


async def _admin_id(client, headers) -> int:
    return (await client.get("/api/auth/me", headers=headers)).json()["id"]


async def _projeto(client, headers, name: str) -> int:
    r = await client.post("/api/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()["id"]


async def _conexao(client, headers, project_id: int) -> int:
    r = await client.post(
        "/api/connections", json={"project_id": project_id, **CONEXAO}, headers=headers
    )
    assert r.status_code == 201
    return r.json()["id"]


async def test_ativacao_de_projeto_emite_project_activated(client, admin_headers, eventos):
    uid = await _admin_id(client, admin_headers)
    pid = await _projeto(client, admin_headers, "Forno")

    r = await client.post(f"/api/projects/{pid}/activate", headers=admin_headers)
    assert r.status_code == 200

    (ev,) = await eventos()  # criar o projeto não emite; só a ativação
    assert ev["severity"] == "info"
    assert ev["origin"] == f"user:{uid}"
    assert ev["payload"] == {"kind": "project_activated", "project_id": pid, "name": "Forno"}


async def test_alteracao_de_retencao_emite_history_retention_changed(
    client, admin_headers, eventos
):
    uid = await _admin_id(client, admin_headers)

    r = await client.put(
        "/api/history-retention", json={"retention_days": 45}, headers=admin_headers
    )
    assert r.status_code == 200

    (ev,) = await eventos()
    assert ev["severity"] == "info"
    assert ev["origin"] == f"user:{uid}"
    assert ev["payload"] == {
        "kind": "history_retention_changed",
        "retention_days_old": 30,
        "retention_days_new": 45,
        "events_retention_days_old": 30,
        "events_retention_days_new": 30,
    }


async def test_ciclo_de_conexao_emite_created_updated_deleted(client, admin_headers, eventos):
    uid = await _admin_id(client, admin_headers)
    pid = await _projeto(client, admin_headers, "ProjConn")
    cid = await _conexao(client, admin_headers, pid)

    r = await client.patch(f"/api/connections/{cid}", json={"name": "CLP 2"}, headers=admin_headers)
    assert r.status_code == 200
    exclusao = await client.delete(f"/api/connections/{cid}", headers=admin_headers)
    assert exclusao.status_code == 204

    criado, atualizado, excluido = await eventos()
    assert [e["severity"] for e in (criado, atualizado, excluido)] == ["info"] * 3
    assert [e["origin"] for e in (criado, atualizado, excluido)] == [f"user:{uid}"] * 3
    assert criado["payload"] == {
        "kind": "connection_created",
        "conn_id": cid,
        "project_id": pid,
        "name": "CLP 1",
    }
    assert atualizado["payload"] == {
        "kind": "connection_updated",
        "conn_id": cid,
        "project_id": pid,
        "name": "CLP 2",
    }
    # `name` do deleted é o nome que a conexão tinha: capturado antes do delete
    assert excluido["payload"] == {
        "kind": "connection_deleted",
        "conn_id": cid,
        "project_id": pid,
        "name": "CLP 2",
    }


async def test_ciclo_de_tag_emite_created_updated_deleted(client, admin_headers, eventos):
    uid = await _admin_id(client, admin_headers)
    pid = await _projeto(client, admin_headers, "ProjTag")
    cid = await _conexao(client, admin_headers, pid)
    assert [e["payload"]["kind"] for e in await eventos()] == ["connection_created"]

    criacao = await client.post(
        "/api/tags", json={"connection_id": cid, **TAG}, headers=admin_headers
    )
    assert criacao.status_code == 201
    tid = criacao.json()["id"]
    r = await client.patch(f"/api/tags/{tid}", json={"name": "TI-102"}, headers=admin_headers)
    assert r.status_code == 200
    assert (await client.delete(f"/api/tags/{tid}", headers=admin_headers)).status_code == 204

    criado, atualizado, excluido = await eventos()
    assert [e["severity"] for e in (criado, atualizado, excluido)] == ["info"] * 3
    assert [e["origin"] for e in (criado, atualizado, excluido)] == [f"user:{uid}"] * 3
    assert criado["payload"] == {
        "kind": "tag_created",
        "tag_id": tid,
        "conn_id": cid,
        "name": "TI-101",
    }
    assert atualizado["payload"] == {
        "kind": "tag_updated",
        "tag_id": tid,
        "conn_id": cid,
        "name": "TI-102",
    }
    assert excluido["payload"] == {
        "kind": "tag_deleted",
        "tag_id": tid,
        "conn_id": cid,
        "name": "TI-102",
    }


async def test_sem_efeito_operacional_nao_emite(client, admin_headers, eventos):
    """CRUD de users, CRUD de projects sem ativação e qualquer GET: canal silencioso (§7.2)."""
    pid = await _projeto(client, admin_headers, "SemEvento")
    assert (
        await client.patch(
            f"/api/projects/{pid}", json={"name": "Renomeado"}, headers=admin_headers
        )
    ).status_code == 200
    assert (await client.delete(f"/api/projects/{pid}", headers=admin_headers)).status_code == 204

    criacao = await client.post(
        "/api/users",
        json={
            "username": "auditado",
            "name": "Auditado",
            "password": "senha-12345",
            "role": "operator",
        },
        headers=admin_headers,
    )
    assert criacao.status_code == 201
    uid = criacao.json()["id"]
    assert (
        await client.patch(f"/api/users/{uid}", json={"name": "Outro"}, headers=admin_headers)
    ).status_code == 200
    assert (await client.delete(f"/api/users/{uid}", headers=admin_headers)).status_code == 204

    for rota in ("/api/projects", "/api/connections", "/api/tags", "/api/users", "/api/events"):
        assert (await client.get(rota, headers=admin_headers)).status_code == 200

    assert await eventos() == []


async def test_mutacao_que_falha_nao_emite(client, admin_headers, eventos):
    pid = await _projeto(client, admin_headers, "Falha")
    await _conexao(client, admin_headers, pid)

    duplicada = await client.post(
        "/api/connections", json={"project_id": pid, **CONEXAO}, headers=admin_headers
    )
    assert duplicada.status_code == 409
    inexistente = await client.patch("/api/tags/99999", json={"eu": "bar"}, headers=admin_headers)
    assert inexistente.status_code == 404

    kinds = [e["payload"]["kind"] for e in await eventos()]
    assert kinds == ["connection_created"]  # só a mutação que chegou ao commit


async def test_rbac_intacto_nas_rotas_que_auditam(client, admin_headers, operator_headers, eventos):
    """Trocar `dependencies=[require_admin]` pelo parâmetro nomeado não pode afrouxar o RBAC."""
    pid = await _projeto(client, admin_headers, "Rbac")
    cid = await _conexao(client, admin_headers, pid)
    tid = (
        await client.post("/api/tags", json={"connection_id": cid, **TAG}, headers=admin_headers)
    ).json()["id"]

    negadas = (
        await client.post(f"/api/projects/{pid}/activate", headers=operator_headers),
        await client.post(
            "/api/connections",
            json={"project_id": pid, "name": "CLP X", "endpoint": "opc.tcp://x:4840"},
            headers=operator_headers,
        ),
        await client.patch(
            f"/api/connections/{cid}", json={"name": "CLP Y"}, headers=operator_headers
        ),
        await client.delete(f"/api/connections/{cid}", headers=operator_headers),
        await client.post(
            "/api/tags",
            json={
                "connection_id": cid,
                "name": "TI-999",
                "node_id": "n",
                "direction": "r",
                "data_type": "float",
            },
            headers=operator_headers,
        ),
        await client.patch(f"/api/tags/{tid}", json={"eu": "bar"}, headers=operator_headers),
        await client.delete(f"/api/tags/{tid}", headers=operator_headers),
    )
    assert [r.status_code for r in negadas] == [403] * 7

    leituras = (
        await client.get(f"/api/projects/{pid}", headers=operator_headers),
        await client.get("/api/connections", headers=operator_headers),
        await client.get(f"/api/connections/{cid}", headers=operator_headers),
        await client.get("/api/tags", headers=operator_headers),
        await client.get(f"/api/tags/{tid}", headers=operator_headers),
    )
    assert [r.status_code for r in leituras] == [200] * 5

    kinds = [e["payload"]["kind"] for e in await eventos()]
    assert kinds == ["connection_created", "tag_created"]  # nada do operador emitiu


async def test_falha_do_redis_nao_quebra_a_api(client, app, admin_headers):
    """Evento é telemetria: barramento fora do ar não pode derrubar a mutação (ADR-004)."""
    pid = await _projeto(client, admin_headers, "RedisMorto")
    morto = Redis.from_url("redis://127.0.0.1:1/0", decode_responses=True)
    app.dependency_overrides[get_redis] = lambda: morto
    try:
        r = await client.post(
            "/api/connections", json={"project_id": pid, **CONEXAO}, headers=admin_headers
        )
    finally:
        await morto.aclose()
    assert r.status_code == 201
