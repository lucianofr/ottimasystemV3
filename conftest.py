"""Fixtures compartilhadas (spec F1 §9): Timescale real via testcontainers,
migrations Alembic e isolamento por SAVEPOINT."""

import pytest
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.community.redis import RedisContainer
from testcontainers.postgres import PostgresContainer

TIMESCALE_IMAGE = "timescale/timescaledb:2.17.2-pg17"  # mesma imagem do compose (paridade)
REDIS_IMAGE = "redis:7.4-alpine"  # mesma imagem do compose (paridade)


@pytest.fixture(scope="session")
def timescale_container():
    with PostgresContainer(
        TIMESCALE_IMAGE,
        username="ottima",
        password="ottima",
        dbname="ottima_test",
        driver="asyncpg",
    ) as pg:
        yield pg


@pytest.fixture(scope="session")
def migrated_database_url(timescale_container) -> str:
    url = timescale_container.get_connection_url()
    cfg = Config("packages/ottima-core/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")  # valida as migrations em toda execução de testes
    return url


@pytest.fixture
async def db_engine(migrated_database_url):
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Transação externa + sessão em SAVEPOINT: commit dentro do teste não vaza (spec §9)."""
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer(REDIS_IMAGE) as container:
        yield container


@pytest.fixture(scope="session")
def redis_url(redis_container) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(redis_container.port)
    return f"redis://{host}:{port}/0"


@pytest.fixture
async def redis_client(redis_url):
    """decode_responses=True é contrato da F2: todo consumidor recebe str, não bytes."""
    client = Redis.from_url(redis_url, decode_responses=True)
    await client.flushdb()  # isolamento entre testes
    yield client
    await client.aclose()
