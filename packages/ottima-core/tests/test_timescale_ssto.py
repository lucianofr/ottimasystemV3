"""Hypertable `ssto_runs` — auditoria imutável do SSTO (ADR-027 §11, migration 0004).

Mesma disciplina das demais hypertables (ADR-003): chunk de 1 dia, retenção de 1 mês por
policy do Timescale (nunca limpeza manual em código) e índice por `flow_id, block_id, ts`.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from ottima_core.models import ssto_runs_table

TS = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


async def test_hypertable_ssto_runs_criada(db_engine):
    async with db_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT hypertable_name FROM timescaledb_information.hypertables")
        )
        names = {r[0] for r in rows}
    assert "ssto_runs" in names


async def test_chunk_time_interval_ssto_runs(db_engine):
    async with db_engine.connect() as conn:
        intervalo = (
            await conn.execute(
                text(
                    "SELECT time_interval FROM timescaledb_information.dimensions"
                    " WHERE hypertable_name = 'ssto_runs' AND column_name = 'ts'"
                )
            )
        ).scalar_one()
    assert intervalo == timedelta(days=1)


async def test_colunas_tipos_ssto_runs(db_engine):
    async with db_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
                " WHERE table_name = 'ssto_runs'"
            )
        )
        colunas = {r.column_name: (r.data_type, r.is_nullable) for r in rows}
    assert colunas == {
        "ts": ("timestamp with time zone", "NO"),
        "flow_id": ("bigint", "NO"),
        "block_id": ("text", "NO"),
        "run_id": ("text", "NO"),
        "config_hash": ("text", "NO"),
        "model_hash": ("text", "NO"),
        "status": ("text", "NO"),
        "solver": ("text", "NO"),
        "solve_ms": ("double precision", "NO"),
        "objective": ("double precision", "NO"),
        "mv": ("jsonb", "NO"),
        "cv_ss": ("jsonb", "NO"),
        "bias": ("jsonb", "NO"),
        "dv": ("jsonb", "NO"),
        "costs": ("jsonb", "NO"),
        "delta_mv": ("jsonb", "NO"),
        "mv_target": ("jsonb", "NO"),
        "cv_target": ("jsonb", "NO"),
        "given_up": ("jsonb", "NO"),
        "active_constraints": ("jsonb", "NO"),
        "duals": ("jsonb", "NO"),
    }


async def test_retencao_1_mes_ssto_runs(db_engine):
    async with db_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT schedule_interval, config FROM timescaledb_information.jobs"
                " WHERE proc_name = 'policy_retention' AND hypertable_name = 'ssto_runs'"
            )
        )
        jobs = rows.fetchall()
    assert len(jobs) == 1
    assert jobs[0].config["drop_after"] == "1 mon"


async def test_indice_flow_block_ts_em_ssto_runs(db_engine):
    async with db_engine.connect() as conn:
        idx = (
            await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE tablename = 'ssto_runs'"
                    " AND indexname = 'ix_ssto_runs_flow_block_ts'"
                )
            )
        ).scalar_one()
    assert "flow_id" in idx
    assert "block_id" in idx
    assert "ts DESC" in idx


def test_downgrade_remove_ssto_runs(migrated_database_url):
    """Downgrade simétrico da 0004. Síncrono de propósito: `alembic.command` chama
    `asyncio.run()` no `env.py` e não pode aninhar no loop de um teste `async def`."""
    cfg = Config("packages/ottima-core/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", migrated_database_url)
    try:
        command.downgrade(cfg, "0003_mpc_samples")

        async def checar_ausencia() -> object:
            engine = create_async_engine(migrated_database_url)
            async with engine.connect() as conn:
                existe = (
                    await conn.execute(text("SELECT to_regclass('public.ssto_runs')"))
                ).scalar()
            await engine.dispose()
            return existe

        assert asyncio.run(checar_ausencia()) is None
    finally:
        command.upgrade(cfg, "head")


async def test_grava_e_le_um_registro_completo(db_session):
    """Round-trip dos vetores em JSONB: o registro tem de voltar do banco idêntico ao que
    entrou — auditoria com número truncado não é auditoria."""
    linha = {
        "ts": TS,
        "flow_id": 7,
        "block_id": "mpc1",
        "run_id": "7f3c1a9e-0000-4000-8000-000000000001",
        "config_hash": "a" * 64,
        "model_hash": "b" * 64,
        "status": "relaxed",
        "solver": "highs",
        "solve_ms": 0.83,
        "objective": -42.5,
        "mv": {"mv_a": 40.0},
        "cv_ss": {"cv_a": 80.0},
        "bias": {"cv_a": 1.25},
        "dv": {"dv_a": 5.0},
        "costs": {"mv_a": -1.0},
        "delta_mv": {"mv_a": 10.0},
        "mv_target": {"mv_a": 50.0},
        "cv_target": {"cv_a": 100.0},
        "given_up": ["co_b", "co_c"],
        "active_constraints": ["cv_a:high"],
        "duals": {"cv_a:high": -0.5},
    }
    await db_session.execute(ssto_runs_table.insert().values(**linha))

    row = (await db_session.execute(select(ssto_runs_table))).one()

    assert row.given_up == ["co_b", "co_c"]
    assert row.duals == {"cv_a:high": -0.5}
    assert row.bias == {"cv_a": 1.25}
    assert row.status == "relaxed"
