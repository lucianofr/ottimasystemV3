"""Fixtures do ml-worker: banco commitado de verdade (o filho do `spawn` abre a própria conexão
e não enxerga transação aberta de teste) e fábricas mínimas de projeto, tag, conjunto e job."""

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ottima_core.models import (
    LabVariable,
    MlJob,
    OpcConnection,
    Project,
    SoftSensorDataset,
    Tag,
)

Sessions = async_sessionmaker[AsyncSession]
END = datetime.now(UTC).replace(microsecond=0)


async def _truncate(factory: Sessions) -> None:
    async with factory() as session:
        # CASCADE alcança ml_jobs, lab_*, soft_sensor_datasets e tags pela FK em `projects`.
        await session.execute(text("TRUNCATE tags, projects CASCADE"))
        await session.commit()


@pytest.fixture
async def session_factory(migrated_database_url: str) -> AsyncIterator[Sessions]:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _truncate(factory)
    try:
        yield factory
    finally:
        await _truncate(factory)
        await engine.dispose()


async def _add(factory: Sessions, row) -> int:
    async with factory() as session:
        session.add(row)
        await session.commit()
        return row.id


@pytest.fixture
async def project_id(session_factory: Sessions) -> int:
    return await _add(session_factory, Project(name="Projeto", description="", is_active=True))


@pytest.fixture
async def make_tag(session_factory: Sessions, project_id: int) -> Callable[..., Awaitable[int]]:
    connection_id = await _add(
        session_factory,
        OpcConnection(
            project_id=project_id,
            name="Forno 1",
            endpoint="opc.tcp://inexistente:4840",
            security_policy="none",
            security_mode="none",
            auth_mode="anonymous",
        ),
    )

    async def make(name: str, eu: str = "") -> int:
        return await _add(
            session_factory,
            Tag(
                connection_id=connection_id,
                name=name,
                node_id=f"ns=2;s={name}",
                direction="r",
                data_type="float",
                eu=eu,
            ),
        )

    return make


@pytest.fixture
async def lab_variable_id(session_factory: Sessions, project_id: int) -> int:
    return await _add(session_factory, LabVariable(project_id=project_id, name="Viscosidade"))


@pytest.fixture
def make_dataset(
    session_factory: Sessions, project_id: int, lab_variable_id: int
) -> Callable[..., Awaitable[int]]:
    async def make(
        tag_ids: list[int],
        *,
        status: str = "building",
        start_ts: datetime = END - timedelta(hours=1),
        end_ts: datetime | None = END,
        period_s: float = 1.0,
    ) -> int:
        return await _add(
            session_factory,
            SoftSensorDataset(
                project_id=project_id,
                name=f"conjunto-{len(tag_ids)}-{status}-{start_ts.timestamp()}",
                lab_variable_id=lab_variable_id,
                input_tag_ids=tag_ids,
                period_s=period_s,
                start_ts=start_ts,
                end_ts=end_ts,
                status=status,
                created_by="teste",
            ),
        )

    return make


@pytest.fixture
def make_job(session_factory: Sessions, project_id: int) -> Callable[..., Awaitable[int]]:
    async def make(kind: str = "train", *, status: str = "queued", params: dict | None = None):
        return await _add(
            session_factory,
            MlJob(
                project_id=project_id,
                kind=kind,
                status=status,
                params=params or {},
                created_by="teste",
            ),
        )

    return make
