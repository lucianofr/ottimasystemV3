"""Recorder: `fuzzy.state.*` → hypertable `fuzzy_samples` (FUZZY OPERATE, ADR-030).

O recorder segue dumb pipe: uma linha por entrada/saída com `v` não-nulo, sem interpretar a
coleção de termos linguísticos — `var_id` é a porta (`IN1..INn`/`OUT1..OUTn`, ADR-029), não o
nome da variável do FLL.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ottima_core.bus import FuzzyState, FuzzyTermDegree, FuzzyVarState, channel_fuzzy_state
from ottima_core.models import fuzzy_samples_table
from ottima_recorder.pipeline import RecorderPipeline

BASE_TS = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _var(port: str, v: float | None) -> FuzzyVarState:
    return FuzzyVarState(
        port=port, name=port, v=v, terms=[FuzzyTermDegree(term="baixo", degree=0.4)]
    )


def _state(
    *,
    offset: int = 0,
    inputs: list[FuzzyVarState] | None = None,
    outputs: list[FuzzyVarState] | None = None,
) -> FuzzyState:
    return FuzzyState(
        ts=BASE_TS + timedelta(seconds=offset),
        ok=True,
        inputs=inputs if inputs is not None else [_var("IN1", 25.0)],
        rules=[0.4, 0.0],
        outputs=outputs if outputs is not None else [_var("OUT1", 50.0)],
    )


@pytest.fixture
async def session_factory(migrated_database_url):
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with factory() as session:
        await session.execute(delete(fuzzy_samples_table))
        await session.commit()
    await engine.dispose()


@pytest.fixture
async def pipeline(redis_client, session_factory):
    return RecorderPipeline(redis_client, session_factory)


async def test_estado_gera_uma_linha_por_porta_com_v_nao_nulo(pipeline, session_factory):
    """Contract: `var_id` = porta; entradas e saídas juntas, no mesmo INSERT (`_write_buffer`)."""
    state = _state(inputs=[_var("IN1", 25.0), _var("IN2", None)], outputs=[_var("OUT1", 50.0)])
    pipeline.ingest_fuzzy_state(channel_fuzzy_state(7, "fz1"), state.model_dump_json())

    assert pipeline.buffered_fuzzy_samples == 2  # IN2 (v=None) não entra no buffer
    await pipeline.flush()

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(fuzzy_samples_table).order_by(fuzzy_samples_table.c.var_id)
            )
        ).all()
    by_var = {row.var_id: row for row in rows}
    assert set(by_var) == {"IN1", "OUT1"}
    assert (by_var["IN1"].v, by_var["OUT1"].v) == (25.0, 50.0)
    for row in rows:
        assert (row.ts, row.flow_id, row.block_id) == (state.ts, 7, "fz1")


async def test_v_none_em_todas_as_portas_nao_gera_linha(pipeline, session_factory):
    state = _state(inputs=[_var("IN1", None)], outputs=[_var("OUT1", None)])
    pipeline.ingest_fuzzy_state(channel_fuzzy_state(7, "fz1"), state.model_dump_json())

    assert pipeline.buffered_fuzzy_samples == 0
    await pipeline.flush()

    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(fuzzy_samples_table))
    assert total == 0


async def test_payload_malformado_nao_derruba_o_pipeline(pipeline, session_factory):
    channel = channel_fuzzy_state(9, "fz1")
    pipeline.ingest_fuzzy_state(channel, "{lixo")
    assert pipeline.buffered_fuzzy_samples == 0
    assert pipeline.malformed_total == 1

    # o loop segue vivo depois do descarte
    primeira = _state()
    pipeline.ingest_fuzzy_state(channel, primeira.model_dump_json())
    segunda = _state(offset=1, inputs=[_var("IN1", 99.0)], outputs=[_var("OUT1", 1.0)])
    pipeline.ingest_fuzzy_state(channel, segunda.model_dump_json())
    await pipeline.flush()

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(fuzzy_samples_table)
                .where(fuzzy_samples_table.c.var_id == "IN1")
                .order_by(fuzzy_samples_table.c.ts)
            )
        ).all()
    assert [r.v for r in rows] == [primeira.inputs[0].v, segunda.inputs[0].v]


async def test_descarte_por_overflow_e_contado(redis_client, session_factory):
    """Teto próprio, drop-oldest e contador — mesma disciplina dos demais buffers (§6.4)."""
    pipeline = RecorderPipeline(redis_client, session_factory, fuzzy_queue_max=2)
    channel = channel_fuzzy_state(7, "fz1")
    for offset in range(3):
        pipeline.ingest_fuzzy_state(
            channel,
            _state(
                offset=offset, inputs=[_var("IN1", float(offset))], outputs=[]
            ).model_dump_json(),
        )

    assert pipeline.buffered_fuzzy_samples == 2
    assert pipeline.dropped_total >= 1
