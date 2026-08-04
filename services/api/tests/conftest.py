"""Fixtures da API: settings de teste, app com get_db/get_redis sobrescritos, cliente e usuários."""

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from ottima_api.app import create_app
from ottima_api.deps import get_db, get_redis
from ottima_core.config import Settings
from ottima_core.models import User
from ottima_core.security import hash_password


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    """Settings isoladas do .env local, com segredos determinísticos de teste."""
    return Settings(
        _env_file=None,
        secret_key="segredo-de-teste",
        fernet_key=Fernet.generate_key().decode(),
        token_ttl_hours=1,
        admin_username="admin",
        admin_password="admin-123456",
        admin_name="Administrador",
        # Nenhum teste pode escrever no volume real /certs (default de Settings)
        certs_dir=tmp_path / "certs",
    )


@pytest.fixture
async def app(db_session, redis_client, test_settings):
    """App real com get_db na sessão em SAVEPOINT e get_redis no Redis efêmero dos testes."""
    application = create_app(test_settings)

    async def _get_db():
        yield db_session

    application.dependency_overrides[get_db] = _get_db
    application.dependency_overrides[get_redis] = lambda: redis_client
    return application


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def make_user(db_session):
    """Cria usuários direto no banco da sessão de teste (senha já em Argon2id)."""

    async def _make(
        username: str,
        password: str = "senha-12345",
        role: str = "operator",
        name: str | None = None,
        is_active: bool = True,
    ) -> User:
        u = User(
            username=username,
            name=name or username,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        db_session.add(u)
        await db_session.commit()  # SAVEPOINT do conftest raiz — não vaza
        await db_session.refresh(u)
        return u

    return _make


@pytest.fixture
async def admin_headers(client, make_user):
    await make_user("admin-fx", password="admin-123456", role="admin")
    r = await client.post(
        "/api/auth/login", json={"username": "admin-fx", "password": "admin-123456"}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def operator_headers(client, make_user):
    await make_user("oper-fx", password="oper-123456", role="operator")
    r = await client.post(
        "/api/auth/login", json={"username": "oper-fx", "password": "oper-123456"}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
