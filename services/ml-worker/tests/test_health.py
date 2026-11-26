"""`/health` do ml-worker (ADR-046 D2): sempre 200, `ok` só quando o banco responde."""

from contextlib import suppress

import pytest
from httpx import ASGITransport, AsyncClient

from ottima_ml_worker.main import app, check_database


class StubSessionFactory:
    """Dublê de `async_sessionmaker`: a contagem da fila responde ou explode, como no real."""

    def __init__(self, fail: bool, queued: int = 0):
        self.fail = fail
        self.queued = queued

    def __call__(self) -> "StubSessionFactory":
        return self

    async def __aenter__(self) -> "StubSessionFactory":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def scalar(self, statement) -> int:
        if self.fail:
            raise ConnectionError("sem banco")
        assert "ml_jobs" in str(statement)
        return self.queued


@pytest.fixture(autouse=True)
def app_state_limpo():
    def limpar() -> None:
        for chave in ("db_ok", "queued", "running_id"):
            with suppress(KeyError):
                delattr(app.state, chave)

    limpar()
    yield
    limpar()


async def _health() -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    return r.json()


async def test_health_ok_e_degraded():
    body = await _health()
    assert body["status"] == "degraded", "sem checagem feita, o serviço não se diz saudável"
    assert body["service"] == "ml-worker"
    assert body["job"] == {"running_id": None, "queued": 0}

    await check_database(StubSessionFactory(fail=False, queued=3), app)
    app.state.running_id = 42
    body = await _health()
    assert set(body) == {"status", "service", "version", "job"}
    assert body["status"] == "ok"
    assert body["job"] == {"running_id": 42, "queued": 3}

    await check_database(StubSessionFactory(fail=True), app)
    assert (await _health())["status"] == "degraded"
