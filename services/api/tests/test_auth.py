"""Testes de autenticação: login, /me, expiração de token e seed do admin (RF-001/003)."""

import asyncio

from ottima_api.seed import seed_admin
from ottima_core.security import create_access_token


async def test_login_ok_retorna_token_e_usuario(client, make_user):
    await make_user("lfr", password="senha-forte-1", role="admin", name="Luciano")
    r = await client.post("/api/auth/login", json={"username": "lfr", "password": "senha-forte-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600  # test_settings: 1 h
    assert body["user"]["username"] == "lfr"
    assert body["user"]["role"] == "admin"
    assert "password" not in body["user"] and "password_hash" not in body["user"]


async def test_login_senha_errada_e_usuario_inexistente_mesma_mensagem(client, make_user):
    await make_user("oper1")
    r1 = await client.post("/api/auth/login", json={"username": "oper1", "password": "errada-123"})
    r2 = await client.post("/api/auth/login", json={"username": "ghost", "password": "errada-123"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"] == "Usuário ou senha inválidos"


async def test_login_usuario_inativo_negado(client, make_user):
    await make_user("inativo", password="senha-12345", is_active=False)
    r = await client.post(
        "/api/auth/login", json={"username": "inativo", "password": "senha-12345"}
    )
    assert r.status_code == 401


async def test_me_com_token(client, admin_headers):
    r = await client.get("/api/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


async def test_rota_sem_token_401(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "Não autenticado"


async def test_token_expirado_401(client, make_user, test_settings):
    u = await make_user("expira", role="operator")
    tok = create_access_token(
        user_id=u.id,
        username=u.username,
        role=u.role,
        secret=test_settings.secret_key,
        ttl_hours=0,
    )
    await asyncio.sleep(1.1)  # ttl 0 h: exp == iat, espera passar do segundo
    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Sessão inválida ou expirada"


async def test_seed_cria_admin_uma_unica_vez(db_session, test_settings):
    assert await seed_admin(db_session, test_settings) is True
    assert await seed_admin(db_session, test_settings) is False  # idempotente


async def test_seed_sem_env_nao_cria(db_session, test_settings):
    s = test_settings.model_copy(update={"admin_username": None, "admin_password": None})
    assert await seed_admin(db_session, s) is False
