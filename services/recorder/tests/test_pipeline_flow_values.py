"""Recorder: `flow.values` → hypertable `samples` (variável historiada, ADR-041 D2).

O recorder segue dumb pipe: canal próprio porque o produtor é o flow-runtime (não o
calc-worker), mas o payload é o mesmo `OpcValue` de `calc.values` e o caminho de gravação é
literalmente o mesmo `ingest_sample` — sem resolver `historized_vars`, sem decidir cadência
(o throttle por Ts_flow já vem aplicado na origem, ADR-041 D3), sem tabela nem buffer novos.

Engine e `session_factory` dedicados (não as fixtures em SAVEPOINT): o pipeline commita por
conta própria e o teste precisa ver o dado commitado.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ottima_core.bus import CHANNEL_FLOW_VALUES, OpcValue
from ottima_core.models import samples_table
from ottima_recorder.pipeline import RecorderPipeline
from testkit.await_until import await_until

BASE_TS = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

# Todas as assinaturas de `RecorderPipeline.start()`/`stop()` (spec §6): o teste de
# start/stop varre esta lista, então um oitavo canal futuro sem entrada aqui falha alto.
_LISTENER_ATTRS = (
    "_events_listener",
    "_samples_listener",
    "_calc_listener",
    "_flow_listener",
    "_mpc_listener",
    "_fuzzy_listener",
    "_loop_listener",
)


def _value(tag_id: int, *, offset: int = 0, value: float = 1.5, quality: int = 0) -> OpcValue:
    return OpcValue(
        tag_id=tag_id, ts=BASE_TS + timedelta(seconds=offset), value=value, quality=quality
    )


@pytest.fixture
async def session_factory(migrated_database_url):
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    async with factory() as session:
        await session.execute(delete(samples_table))
        await session.commit()
    await engine.dispose()


@pytest.fixture
async def make_pipeline(redis_client):
    """Fábrica de pipelines já iniciados; para todos no teardown."""
    started: list[RecorderPipeline] = []

    async def _make(factory: Any, **kwargs: Any) -> RecorderPipeline:
        pipeline = RecorderPipeline(redis_client, factory, **kwargs)
        await pipeline.start()
        started.append(pipeline)
        return pipeline

    yield _make
    for pipeline in started:
        await pipeline.stop()


async def wait_rows(factory: Any, expected: int) -> None:
    async def chegou() -> bool:
        async with factory() as session:
            total = await session.scalar(select(func.count()).select_from(samples_table))
        return total >= expected

    await await_until(chegou)


async def test_flow_values_quality_boa_grava_o_value(redis_client, session_factory, make_pipeline):
    """Porta historiada publica em `flow.values`, mesmo formato `OpcValue`: reusa
    `_on_sample`/`ingest_sample` e a hypertable `samples`, sem tabela nem buffer novos."""
    await make_pipeline(session_factory)
    valor = _value(101, value=42.5, quality=0)
    await redis_client.publish(CHANNEL_FLOW_VALUES, valor.model_dump_json())

    await wait_rows(session_factory, 1)
    async with session_factory() as session:
        row = (await session.execute(select(samples_table))).one()

    assert (row.tag_id, row.value, row.quality) == (valor.tag_id, valor.value, 0)


async def test_flow_values_quality_ruim_grava_value_null(
    redis_client, session_factory, make_pipeline
):
    """`quality=2` (ADR-037): porta de entrada COLD chega assim (ADR-041 D4) e grava NULL,
    nunca o `0.0` de placeholder do payload."""
    await make_pipeline(session_factory)
    valor = _value(102, value=0.0, quality=2)
    await redis_client.publish(CHANNEL_FLOW_VALUES, valor.model_dump_json())

    await wait_rows(session_factory, 1)
    async with session_factory() as session:
        row = (await session.execute(select(samples_table))).one()

    assert (row.tag_id, row.value, row.quality) == (valor.tag_id, None, 2)


async def test_flow_values_malformado_nao_derruba_o_pipeline(
    redis_client, session_factory, make_pipeline
):
    pipeline = await make_pipeline(session_factory)
    await redis_client.publish(CHANNEL_FLOW_VALUES, "{lixo")

    valida = _value(103, value=9.0)
    await redis_client.publish(CHANNEL_FLOW_VALUES, valida.model_dump_json())
    await wait_rows(session_factory, 1)

    async with session_factory() as session:
        row = (await session.execute(select(samples_table))).one()
    assert (row.tag_id, row.value) == (valida.tag_id, valida.value)
    assert pipeline.malformed_total == 1


async def test_start_e_stop_assinam_e_desassinam_os_sete_listeners(redis_client, session_factory):
    """Sete canais (`opc.values.*`, `calc.values`, `flow.values`, `events`, `mpc.state.*`,
    `fuzzy.state.*`, `loop.state.*`), cada um com sua própria task viva depois de `start()`
    e desfeita depois de `stop()` — nenhum caminho de desmonte parcial."""
    pipeline = RecorderPipeline(redis_client, session_factory)
    await pipeline.start()
    try:
        for attr in _LISTENER_ATTRS:
            listener = getattr(pipeline, attr)
            assert listener._task is not None and not listener._task.done()
            assert listener._pubsub is not None
    finally:
        await pipeline.stop()

    for attr in _LISTENER_ATTRS:
        listener = getattr(pipeline, attr)
        assert listener._task is None
        assert listener._pubsub is None
