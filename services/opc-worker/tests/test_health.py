"""Testes do `/health` do opc-worker (RNF-07, spec F2 §2.2-8).

O app é um singleton de módulo: cada teste monta o `app.state` que quer e a fixture
autouse limpa o que sobrou, para que a ordem de execução não decida o resultado.
"""

from contextlib import suppress
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient, Response

from ottima_opc_worker.main import app, check_database, check_redis
from ottima_opc_worker.state import ConnectionSnapshot, ConnectionState, WorkerState

CHAVES_DE_TOPO = {"status", "service", "version", "connections"}
# As oito chaves por conexão da spec §2.2-8 — nem uma a mais, nem uma a menos.
CHAVES_DA_CONEXAO = {
    "name",
    "state",
    "flow_watchdog_alive",
    "session_up_since",
    "last_publish_ts",
    "tags_subscribed",
    "monitored_errors",
    "write_errors",
}

SESSAO_DESDE = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
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


@pytest.fixture(autouse=True)
def app_state_limpo():
    """Zera o estado que o lifespan povoaria: sem isto um teste herda o do anterior."""

    def limpar() -> None:
        for chave in ("redis_ok", "db_ok", "worker_state", "supervisor"):
            # starlette.State levanta KeyError (não AttributeError) no del de chave ausente.
            with suppress(KeyError):
                delattr(app.state, chave)

    limpar()
    yield
    limpar()


async def get_health() -> Response:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get("/health")


def state_com_duas_conexoes() -> WorkerState:
    """Uma conexão saudável e uma caída: o `/health` tem de mostrar as duas."""
    return WorkerState(
        connections={
            1: ConnectionSnapshot(
                name="Forno 1",
                state=ConnectionState.UP,
                flow_watchdog_alive={101: True},
                session_up_since=SESSAO_DESDE,
                last_publish_ts=ULTIMA_PUBLICACAO,
                tags_subscribed=4,
            ),
            2: ConnectionSnapshot(
                name="Forno 2",
                state=ConnectionState.FAILED,
                flow_watchdog_alive={202: False},
                tags_subscribed=0,
                monitored_errors=3,
                write_errors=1,
            ),
        }
    )


async def test_health_responde_200_com_nome_do_servico():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "opc-worker"
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


async def test_health_expoe_exatamente_as_chaves_da_spec():
    app.state.redis_ok = True
    app.state.db_ok = True
    app.state.worker_state = state_com_duas_conexoes()

    r = await get_health()

    assert r.status_code == 200
    body = r.json()
    assert set(body) == CHAVES_DE_TOPO
    assert body["service"] == "opc-worker"
    assert body["version"] == "0.1.0"
    assert set(body["connections"]) == {"1", "2"}, "conn_id serializado como string"
    for saude in body["connections"].values():
        assert set(saude) == CHAVES_DA_CONEXAO
    assert body["connections"]["1"]["name"] == "Forno 1"
    assert body["connections"]["1"]["state"] == "up"
    assert body["connections"]["1"]["tags_subscribed"] == 4
    assert body["connections"]["2"]["monitored_errors"] == 3
    assert body["connections"]["2"]["write_errors"] == 1


async def test_conexao_opc_caida_nao_degrada_o_status():
    app.state.redis_ok = True
    app.state.db_ok = True
    app.state.worker_state = state_com_duas_conexoes()

    r = await get_health()

    assert r.status_code == 200
    body = r.json()
    assert body["connections"]["2"]["state"] == "failed"
    assert body["connections"]["2"]["flow_watchdog_alive"] == {"202": False}
    assert body["status"] == "ok", "PLC desligado é alarme, não unhealth do serviço"


async def test_redis_fora_degrada_o_status():
    app.state.redis_ok = False
    app.state.db_ok = True
    app.state.worker_state = state_com_duas_conexoes()

    r = await get_health()

    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


async def test_banco_fora_degrada_o_status():
    app.state.redis_ok = True
    app.state.db_ok = False
    app.state.worker_state = state_com_duas_conexoes()

    r = await get_health()

    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


async def test_app_sem_lifespan_responde_sem_conexoes():
    r = await get_health()

    assert r.status_code == 200
    body = r.json()
    assert body["connections"] == {}
    assert body["status"] == "degraded", "sem checagem feita, o serviço não se diz saudável"


async def test_timestamps_saem_em_iso_utc_ou_nulos():
    app.state.redis_ok = True
    app.state.db_ok = True
    app.state.worker_state = state_com_duas_conexoes()

    body = (await get_health()).json()

    viva = body["connections"]["1"]
    assert viva["session_up_since"] == SESSAO_DESDE.isoformat()
    assert viva["last_publish_ts"] == ULTIMA_PUBLICACAO.isoformat()
    assert datetime.fromisoformat(viva["last_publish_ts"]).utcoffset().total_seconds() == 0

    caida = body["connections"]["2"]
    assert caida["session_up_since"] is None
    assert caida["last_publish_ts"] is None
