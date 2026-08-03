async def _conexao(client, headers) -> int:
    p = (await client.post("/api/projects", json={"name": "TagsProj"}, headers=headers)).json()
    c = await client.post(
        "/api/connections",
        json={"project_id": p["id"], "name": "plc", "endpoint": "opc.tcp://x:4840"},
        headers=headers,
    )
    return c.json()["id"]


async def test_cria_lista_filtra(client, admin_headers, operator_headers):
    cid = await _conexao(client, admin_headers)
    for nome, direcao in [("FT-101", "r"), ("FV-101", "w")]:
        r = await client.post(
            "/api/tags",
            json={
                "connection_id": cid,
                "name": nome,
                "node_id": f"ns=2;s={nome}",
                "direction": direcao,
                "data_type": "float",
                "eu": "m3/h",
            },
            headers=admin_headers,
        )
        assert r.status_code == 201
    todos = (await client.get(f"/api/tags?connection_id={cid}", headers=operator_headers)).json()
    assert len(todos) == 2
    leitura = (
        await client.get(f"/api/tags?connection_id={cid}&direction=r", headers=operator_headers)
    ).json()
    assert [t["name"] for t in leitura] == ["FT-101"]


async def test_nome_duplicado_na_conexao_409(client, admin_headers):
    cid = await _conexao(client, admin_headers)
    corpo = {
        "connection_id": cid, "name": "TI-100", "node_id": "ns=2;i=1",
        "direction": "r", "data_type": "float",
    }
    assert (await client.post("/api/tags", json=corpo, headers=admin_headers)).status_code == 201
    r = await client.post("/api/tags", json=corpo, headers=admin_headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "Nome de tag já em uso nesta conexão"


async def test_validacoes_e_papeis(client, admin_headers, operator_headers):
    cid = await _conexao(client, admin_headers)
    r = await client.post(
        "/api/tags",
        json={"connection_id": cid, "name": "X", "node_id": "n",
              "direction": "z", "data_type": "float"},
        headers=admin_headers,
    )
    assert r.status_code == 422  # direction inválida
    r = await client.post(
        "/api/tags",
        json={"connection_id": cid, "name": "X", "node_id": "n",
              "direction": "r", "data_type": "float"},
        headers=operator_headers,
    )
    assert r.status_code == 403
    assert (await client.get("/api/tags/99999", headers=admin_headers)).status_code == 404


async def test_patch_e_delete(client, admin_headers):
    cid = await _conexao(client, admin_headers)
    t = (
        await client.post(
            "/api/tags",
            json={"connection_id": cid, "name": "PT-1", "node_id": "ns=2;i=9",
                  "direction": "r", "data_type": "float"},
            headers=admin_headers,
        )
    ).json()
    r = await client.patch(f"/api/tags/{t['id']}", json={"eu": "bar"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["eu"] == "bar"
    assert (await client.delete(f"/api/tags/{t['id']}", headers=admin_headers)).status_code == 204
