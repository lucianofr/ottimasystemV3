"""Fixtures da API: settings de teste, app com get_db sobrescrito e cliente ASGI."""

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from ottima_api.app import create_app
from ottima_api.deps import get_db
from ottima_core.config import Settings


@pytest.fixture
def test_settings() -> Settings:
    """Settings isoladas do .env local, com segredos determinísticos de teste."""
    return Settings(
        _env_file=None,
        secret_key="segredo-de-teste",
        fernet_key=Fernet.generate_key().decode(),
        token_ttl_hours=1,
        admin_username="admin",
        admin_password="admin-123456",
        admin_name="Administrador",
    )


@pytest.fixture
async def app(db_session, test_settings):
    """App real com get_db apontando para a sessão em SAVEPOINT dos testes."""
    application = create_app(test_settings)

    async def _get_db():
        yield db_session

    application.dependency_overrides[get_db] = _get_db
    return application


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
