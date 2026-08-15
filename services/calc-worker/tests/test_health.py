"""Testes do `/health` do calc-worker (ADR-033).

O app é um singleton de módulo: cada teste monta o `app.state` que quer e a fixture
autouse limpa o que sobrou, para que a ordem de execução não decida o resultado.
"""

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient, Response

from ottima_calc_worker.main import app, check_database, check_redis
from ottima_calc_worker.state import RunnerHealth

CHAVES_DE_TOPO = {"status", "service", "version", "tags", "script_pool"}
CHAVES_DA_TAG = {"last_publish_ts", "last_status", "consecutive_failures", "overrun_count"}

ULTIMA_PUBLICACAO = datetime(2026, 8, 3, 12, 3, 11, 250000, tzinfo=UTC)


class StubRedis:
    def __init__(self, fail: bool):
        self.fail = fail

    async def ping(self):
        if self.fail:
            raise ConnectionError("sem redis")
        return True


class StubSessionFactory:
    """Dublê de `async_sessionmaker`: o `SELECT 1` é executado ou explode, como no real."""

    def __init__(self, fail: bool):
        self.fail = fail
        self.executados: list[str] = []

    def __call__(self) -> "StubSessionFactory":
        return self

    async def __aenter__(self) -> "StubSessionFactory":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def execute(self, statement) -> None:
        if self.fail:
            raise ConnectionError("sem banco")
        self.executados.append(str(statement))


@dataclass
class _StubRunner:
    health: RunnerHealth


class StubSupervisor:
    """Dublê do supervisor: só o que o handler de `/health` lê (`runners`, `script_pool_stats`)."""

    def __init__(self, runners: dict[int, _StubRunner], pool_stats: dict | None = None) -> None:
        self.runners = runners
        self._pool_stats = pool_stats or {"size": 4, "busy": 0, "respawns": 0}

    def script_pool_stats(self) -> dict:
        return self._pool_stats


@pytest.fixture(autouse=True)
def app_state_limpo():
    """Zera o estado que o lifespan povoaria: sem isto um teste herda o do anterior."""

    def limpar() -> None:
        for chave in ("redis_ok", "db_ok", "supervisor"):
            # starlette.State levanta KeyError (não AttributeError) no del de chave ausente.
            with suppress(KeyError):
                delattr(app.state, chave)

    limpar()
    yield
    limpar()


async def get_health() -> Response:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get("/health")


async def test_health_responde_200_com_nome_do_servico():
    r = await get_health()
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "calc-worker"
    assert body["status"] in {"ok", "degraded"}


async def test_check_redis_marca_estado():
    await check_redis(StubRedis(fail=False), app)
    assert app.state.redis_ok is True
    await check_redis(StubRedis(fail=True), app)
    assert app.state.redis_ok is False


async def test_check_database_marca_estado():
    factory_ok = StubSessionFactory(fail=False)
    await check_database(factory_ok, app)
    assert app.state.db_ok is True
    assert factory_ok.executados == ["SELECT 1"], "a checagem tem de tocar o banco"

    await check_database(StubSessionFactory(fail=True), app)
    assert app.state.db_ok is False


async def test_health_expoe_exatamente_as_chaves_do_corpo():
    app.state.redis_ok = True
    app.state.db_ok = True
    app.state.supervisor = StubSupervisor(
        {900: _StubRunner(RunnerHealth(last_publish_ts=ULTIMA_PUBLICACAO, last_status="ok"))}
    )

    body = (await get_health()).json()

    assert set(body) == CHAVES_DE_TOPO
    assert set(body["tags"]["900"]) == CHAVES_DA_TAG
    assert body["tags"]["900"]["last_status"] == "ok"
    assert body["tags"]["900"]["last_publish_ts"] == ULTIMA_PUBLICACAO.isoformat()
    assert body["script_pool"] == {"size": 4, "busy": 0, "respawns": 0}


async def test_tag_em_falha_nao_degrada_o_status():
    """Timeout/erro de script é condição operacional da tag, não unhealth do serviço —
    mesma regra do opc-worker para um PLC desligado."""
    app.state.redis_ok = True
    app.state.db_ok = True
    app.state.supervisor = StubSupervisor(
        {
            900: _StubRunner(
                RunnerHealth(last_status="timeout", consecutive_failures=9, overrun_count=2)
            )
        }
    )

    body = (await get_health()).json()

    assert body["status"] == "ok", "tag em falha permanente não pode derrubar o /health"
    assert body["tags"]["900"]["consecutive_failures"] == 9


async def test_redis_fora_degrada_o_status():
    app.state.redis_ok = False
    app.state.db_ok = True

    assert (await get_health()).json()["status"] == "degraded"


async def test_banco_fora_degrada_o_status():
    app.state.redis_ok = True
    app.state.db_ok = False

    assert (await get_health()).json()["status"] == "degraded"


async def test_app_sem_lifespan_responde_degradado_e_sem_tags():
    body = (await get_health()).json()
    assert body["status"] == "degraded", "sem checagem feita, o serviço não se diz saudável"
    assert body["tags"] == {}
    assert body["script_pool"] == {}
