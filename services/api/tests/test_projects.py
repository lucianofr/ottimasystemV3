import pytest


async def _criar(client, headers, name: str) -> dict:
    r = await client.post("/api/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


async def test_crud_basico_e_papeis(client, admin_headers, operator_headers):
    p = await _criar(client, admin_headers, "Planta A")
    assert p["is_active"] is False  # projetos nascem inativos (ADR-017)
    r = await client.get("/api/projects", headers=operator_headers)
    assert r.status_code == 200 and len(r.json()) == 1  # operador enxerga tudo
    assert (
        await client.post("/api/projects", json={"name": "X"}, headers=operator_headers)
    ).status_code == 403


async def test_ativacao_e_troca_atomica(client, admin_headers):
    a = await _criar(client, admin_headers, "A")
    b = await _criar(client, admin_headers, "B")
    assert (
        await client.post(f"/api/projects/{a['id']}/activate", headers=admin_headers)
    ).status_code == 200
    assert (
        await client.post(f"/api/projects/{b['id']}/activate", headers=admin_headers)
    ).status_code == 200
    projetos = (await client.get("/api/projects", headers=admin_headers)).json()
    ativos = [p for p in projetos if p["is_active"]]
    assert len(ativos) == 1 and ativos[0]["id"] == b["id"]  # nunca 2 ativos (ADR-017)


async def test_delete_de_projeto_ativo_409(client, admin_headers):
    p = await _criar(client, admin_headers, "Ativo")
    await client.post(f"/api/projects/{p['id']}/activate", headers=admin_headers)
    r = await client.delete(f"/api/projects/{p['id']}", headers=admin_headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "Desative o projeto antes de excluí-lo"


@pytest.mark.skip(reason="ativado na Task 10")
async def test_delete_cascateia_conexoes(client, admin_headers):
    p = await _criar(client, admin_headers, "ComConexao")
    c = await client.post(
        "/api/connections",
        json={"project_id": p["id"], "name": "plc1", "endpoint": "opc.tcp://10.0.0.5:4840"},
        headers=admin_headers,
    )
    assert c.status_code == 201
    apagado = await client.delete(f"/api/projects/{p['id']}", headers=admin_headers)
    assert apagado.status_code == 204
    r = await client.get(f"/api/connections?project_id={p['id']}", headers=admin_headers)
    assert r.json() == []


async def test_nome_duplicado_409_e_404(client, admin_headers):
    await _criar(client, admin_headers, "Unico")
    r = await client.post("/api/projects", json={"name": "Unico"}, headers=admin_headers)
    assert r.status_code == 409
    assert (await client.get("/api/projects/99999", headers=admin_headers)).status_code == 404
