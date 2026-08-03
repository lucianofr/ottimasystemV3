from sqlalchemy import select

from ottima_core.models import User


async def test_admin_cria_usuario_operador(client, admin_headers, db_session):
    r = await client.post(
        "/api/users",
        json={
            "username": "op1",
            "name": "Operador 1",
            "password": "senha-12345",
            "role": "operator",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "operator"
    assert "password" not in body and "password_hash" not in body
    stored = await db_session.scalar(select(User).where(User.username == "op1"))
    assert stored.password_hash.startswith("$argon2id$")


async def test_senha_curta_rejeitada(client, admin_headers):
    r = await client.post(
        "/api/users",
        json={"username": "op2", "name": "X", "password": "curta12", "role": "operator"},
        headers=admin_headers,
    )
    assert r.status_code == 422  # min 8 (spec §5.1)


async def test_operador_nao_acessa_users(client, operator_headers):
    assert (await client.get("/api/users", headers=operator_headers)).status_code == 403
    r = await client.post(
        "/api/users",
        json={"username": "x", "name": "X", "password": "senha-12345", "role": "operator"},
        headers=operator_headers,
    )
    assert r.status_code == 403


async def test_username_duplicado_409_case_insensitive(client, admin_headers, make_user):
    await make_user("Fulano")
    r = await client.post(
        "/api/users",
        json={"username": "fulano", "name": "F", "password": "senha-12345", "role": "operator"},
        headers=admin_headers,
    )
    assert r.status_code == 409


async def test_nao_excluir_o_proprio_usuario(client, admin_headers):
    me = (await client.get("/api/auth/me", headers=admin_headers)).json()
    r = await client.delete(f"/api/users/{me['id']}", headers=admin_headers)
    assert r.status_code == 409


async def test_nao_rebaixar_nem_desativar_ultimo_admin(client, admin_headers):
    me = (await client.get("/api/auth/me", headers=admin_headers)).json()
    r1 = await client.patch(
        f"/api/users/{me['id']}", json={"role": "operator"}, headers=admin_headers
    )
    r2 = await client.patch(
        f"/api/users/{me['id']}", json={"is_active": False}, headers=admin_headers
    )
    assert r1.status_code == 409
    assert r2.status_code == 409


async def test_excluir_ultimo_admin_negado_mas_operador_pode(client, admin_headers, make_user):
    op = await make_user("descartavel", role="operator")
    assert (await client.delete(f"/api/users/{op.id}", headers=admin_headers)).status_code == 204


async def test_patch_troca_senha_e_novo_login_funciona(client, admin_headers, make_user):
    u = await make_user("troca", password="senha-antiga-1")
    r = await client.patch(
        f"/api/users/{u.id}", json={"password": "senha-nova-12"}, headers=admin_headers
    )
    assert r.status_code == 200
    ok = await client.post(
        "/api/auth/login", json={"username": "troca", "password": "senha-nova-12"}
    )
    assert ok.status_code == 200


async def test_404_usuario_inexistente(client, admin_headers):
    assert (await client.get("/api/users/99999", headers=admin_headers)).status_code == 404
