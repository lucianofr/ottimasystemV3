"""Recorder: `MpcState.ssto` → hypertable `ssto_runs` (ADR-027 §11).

O recorder segue dumb pipe: não interpreta o registro, só o materializa. Quadro sem `ssto`
não gera linha nenhuma — o campo é opcional e a maioria dos quadros (SSTO desligado, fora de
AUTO) não o traz.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ottima_core.bus import (
    MpcModes,
    MpcPrediction,
    MpcState,
    MpcStatus,
    MpcVarState,
    SstoRun,
    channel_mpc_state,
)
from ottima_core.models import mpc_samples_table, ssto_runs_table
from ottima_recorder.pipeline import RecorderPipeline

BASE_TS = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _run(status: str = "relaxed") -> SstoRun:
    return SstoRun(
        run_id="7f3c1a9e-0000-4000-8000-000000000001",
        config_hash="a" * 64,
        model_hash="b" * 64,
        status=status,
        solver="highs",
        solve_ms=0.9,
        objective=-12.5,
        mv={"mv_a": 40.0},
        cv_ss={"cv_a": 80.0},
        bias={"cv_a": 1.5},
        dv={"dv_a": 3.0},
        costs={"mv_a": -1.0},
        delta_mv={"mv_a": 10.0},
        mv_target={"mv_a": 50.0},
        cv_target={"cv_a": 100.0},
        given_up=["co_b"],
        active_constraints=["cv_a:high"],
        duals={"cv_a:high": -0.25},
    )


def _state(*, offset: int = 0, ssto: SstoRun | None) -> MpcState:
    ts = BASE_TS + timedelta(seconds=offset)
    return MpcState(
        ts=ts,
        modes=MpcModes(local_remote="remote", man_auto="auto"),
        status=MpcStatus(solver="ok", overruns=0, last_solve_ms=1.0, armed=True, input_valid=True),
        vars={"mv_a": MpcVarState(v=40.0)},
        cost=0.0,
        prediction=MpcPrediction(ts=ts, t=[], cv=[], mv=[]),
        ssto=ssto,
    )


@pytest.fixture
async def session_factory(migrated_database_url):
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with factory() as session:
        await session.execute(delete(ssto_runs_table))
        await session.execute(delete(mpc_samples_table))
        await session.commit()
    await engine.dispose()


@pytest.fixture
async def pipeline(redis_client, session_factory):
    return RecorderPipeline(redis_client, session_factory)


async def test_quadro_com_ssto_gera_uma_linha_de_auditoria(pipeline, session_factory):
    pipeline.ingest_mpc_state(channel_mpc_state(7, "mpc1"), _state(ssto=_run()).model_dump_json())

    assert pipeline.buffered_ssto_runs == 1
    await pipeline.flush()

    async with session_factory() as session:
        row = (await session.execute(select(ssto_runs_table))).one()
    assert row.flow_id == 7
    assert row.block_id == "mpc1"
    assert row.ts == BASE_TS
    assert row.status == "relaxed"
    assert row.given_up == ["co_b"]
    assert row.duals == {"cv_a:high": -0.25}
    assert row.mv_target == {"mv_a": 50.0}
    assert row.model_hash == "b" * 64


async def test_quadro_sem_ssto_nao_gera_linha(pipeline, session_factory):
    pipeline.ingest_mpc_state(channel_mpc_state(7, "mpc1"), _state(ssto=None).model_dump_json())

    assert pipeline.buffered_ssto_runs == 0
    await pipeline.flush()

    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(ssto_runs_table))
    assert total == 0


async def test_uma_linha_por_execucao_mesmo_com_varias_variaveis(pipeline, session_factory):
    """`mpc_samples` tem uma linha por variável; `ssto_runs` tem UMA por execução — a
    granularidade dos dois é diferente de propósito."""
    state = _state(ssto=_run())
    state = state.model_copy(
        update={"vars": {"mv_a": MpcVarState(v=1.0), "cv_a": MpcVarState(v=2.0, sp=3.0)}}
    )
    pipeline.ingest_mpc_state(channel_mpc_state(9, "mpc2"), state.model_dump_json())

    assert pipeline.buffered_ssto_runs == 1
    assert pipeline.buffered_mpc_samples == 2


async def test_registros_de_execucoes_seguidas_se_acumulam(pipeline, session_factory):
    for offset in range(3):
        pipeline.ingest_mpc_state(
            channel_mpc_state(7, "mpc1"), _state(offset=offset, ssto=_run()).model_dump_json()
        )
    await pipeline.flush()

    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(ssto_runs_table))
    assert total == 3


async def test_descarte_por_overflow_e_contado(redis_client, session_factory):
    """Teto próprio, drop-oldest e contador — mesma disciplina dos demais buffers (§6.4)."""
    pipeline = RecorderPipeline(redis_client, session_factory, ssto_queue_max=2)
    for offset in range(3):
        pipeline.ingest_mpc_state(
            channel_mpc_state(7, "mpc1"), _state(offset=offset, ssto=_run()).model_dump_json()
        )

    assert pipeline.buffered_ssto_runs == 2
    assert pipeline.dropped_total >= 1
