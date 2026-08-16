"""Fixtures compartilhadas dos testes do flow-runtime.

As fixtures de infraestrutura (`redis_client`, `db_session`) continuam vindo do `conftest.py`
da raiz do repositório. Os construtores de grafo, o arreio do supervisor (pool-duplo,
`Collector`, `Harness`) e as constantes usados por `test_supervisor.py` e `test_hotswap.py`
moraram aqui até a tarefa 0.8; agora vivem em `runtime_test_helpers.py` (nome próprio, não
`conftest`, para não colidir com o `opc-worker/tests/conftest.py` quando as duas suítes
rodam num único pytest — débito 8 do plano F4a). Este arquivo mantém só as fixtures: o que
precisa delas importa deste módulo.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# A suíte roda com --import-mode=importlib, que não põe o diretório dos testes no
# sys.path: sem isto os arquivos de teste não conseguem `import runtime_test_helpers`. Tem
# de vir ANTES do import do helper: é o que o torna localizável por nome nu.
_TESTS_DIR = str(Path(__file__).parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from runtime_test_helpers import (  # noqa: E402
    AWAIT_TIMEOUT_S,
    SLOW_POLL_S,
    Collector,
    Harness,
    StubPool,
)

from ottima_core.config import get_settings  # noqa: E402
from ottima_core.snapshot import ValueSnapshot  # noqa: E402
from ottima_flow_runtime.events import build_event_listener  # noqa: E402
from ottima_flow_runtime.mpc.worker import worker_main  # noqa: E402
from ottima_flow_runtime.partition import UNPARTITIONED, Partition  # noqa: E402
from ottima_flow_runtime.state import RuntimeState  # noqa: E402
from ottima_flow_runtime.supervisor import Supervisor  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _sem_particao_no_ambiente() -> None:
    """Falha cedo e claro se `OTTIMA_FLOW_PARTITIONS` vazar do shell para a suíte.

    `main.app` é escolhido no IMPORT do módulo (`_default_app`): com a variável acima de 1, ele
    vira o app do PAI — sem supervisor, sem `flows` — e `test_health.py`,
    `test_health_mpc.py` e `test_supervisor.py` quebram por um motivo que não aparece no
    traceback. Um `export` numa sessão de terminal (ou um `.env` no diretório de trabalho) é
    suficiente para isso acontecer, então a suíte diz o que está errado em vez de deixar
    adivinhar.
    """
    particoes = get_settings().flow_partitions
    if particoes != 1:
        raise pytest.UsageError(
            f"OTTIMA_FLOW_PARTITIONS={particoes} no ambiente da suíte. Os testes assumem o "
            "runtime de um processo (main.app = app de execução). Rode sem essa variável."
        )


# --------------------------------------------------------------------------------------
# Banco: o supervisor tem session_factory próprio, então o cenário é commitado de verdade
# --------------------------------------------------------------------------------------


@pytest.fixture
async def session_factory(
    migrated_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Factory commitada de verdade: o supervisor não vê transação aberta de teste."""
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _truncate(factory)
    try:
        yield factory
    finally:
        await _truncate(factory)
        await engine.dispose()


async def _truncate(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        await session.execute(text("TRUNCATE flows, tags, opc_connections, projects CASCADE"))
        await session.commit()


# --------------------------------------------------------------------------------------
# Duplos e coletores
# --------------------------------------------------------------------------------------


@pytest.fixture
async def collect(redis_client: Redis) -> AsyncIterator[Callable[[str], Awaitable[Collector]]]:
    """Fábrica de assinantes; a inscrição está confirmada quando a fábrica retorna."""
    pumps: list[asyncio.Task[None]] = []
    pubsubs: list[Any] = []

    async def factory(channel: str) -> Collector:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        collector = Collector()
        ready = asyncio.Event()

        async def pump() -> None:
            async for message in pubsub.listen():
                if message["type"] == "subscribe":
                    ready.set()
                elif message["type"] == "message":
                    collector.received.append(message["data"])

        pumps.append(asyncio.create_task(pump()))
        pubsubs.append(pubsub)
        await asyncio.wait_for(ready.wait(), AWAIT_TIMEOUT_S)
        return collector

    yield factory

    for pump_task in pumps:
        pump_task.cancel()
    for pump_task in pumps:
        with suppress(asyncio.CancelledError):
            await pump_task
    for pubsub in pubsubs:
        await pubsub.aclose()


@pytest.fixture
async def harness_factory(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Redis
) -> AsyncIterator[Callable[..., Awaitable[Harness]]]:
    built: list[Harness] = []

    async def factory(
        *,
        poll_interval_s: float = SLOW_POLL_S,
        mpc_worker_target: Callable = worker_main,
        partition: Partition = UNPARTITIONED,
    ) -> Harness:
        state = RuntimeState()
        pool = StubPool()
        snapshot = ValueSnapshot(redis_client)
        supervisor = Supervisor(
            session_factory,
            redis_client,
            state,
            snapshot=snapshot,
            pool=pool,
            poll_interval_s=poll_interval_s,
            mpc_worker_target=mpc_worker_target,
            partition=partition,
        )
        # Mesma composição do lifespan de `main.py`: o assinante de `events` é quem liga o
        # contrato F2 §3.7 ao supervisor, então o arreio tem de montá-lo igual.
        events = build_event_listener(
            redis_client,
            on_comm_failure=supervisor.on_comm_failure,
            on_comm_restored=supervisor.on_comm_restored,
            on_project_activated=supervisor.on_project_activated,
        )
        harness = Harness(supervisor, state, pool, snapshot, redis_client, events)
        built.append(harness)
        await snapshot.start()
        await supervisor.start()
        await events.start()
        return harness

    yield factory

    for harness in built:
        await harness.events.stop()
        await harness.supervisor.stop()
        await harness.snapshot.stop()
