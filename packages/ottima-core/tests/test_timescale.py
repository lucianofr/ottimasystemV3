import asyncio
from datetime import timedelta

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def test_hypertables_criadas(db_engine):
    async with db_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT hypertable_name FROM timescaledb_information.hypertables")
        )
        names = {r[0] for r in rows}
    assert {"samples", "events"} <= names


async def test_retencao_1_mes_nas_tres_estruturas(db_engine):
    # samples, events e samples_1m: cada estrutura tem a sua policy de 1 mês (ADR-003/020).
    # A policy do CAgg é registrada contra a hypertable materializada, cujo nome interno
    # (_materialized_hypertable_N) varia — por isso é descoberto em tempo de execução.
    async with db_engine.connect() as conn:
        materializada = (
            await conn.execute(
                text(
                    "SELECT materialization_hypertable_name"
                    " FROM timescaledb_information.continuous_aggregates"
                    " WHERE view_name = 'samples_1m'"
                )
            )
        ).scalar_one()
        # Filtra pelas três estruturas esperadas: hypertables que a F2 acrescentar não
        # interferem, mas a falta de qualquer uma das três reprova o teste.
        rows = await conn.execute(
            text(
                "SELECT hypertable_name FROM timescaledb_information.jobs"
                " WHERE proc_name = 'policy_retention'"
                " AND (config->>'drop_after')::interval = INTERVAL '1 month'"
                " AND hypertable_name IN (:samples, :events, :materializada)"
            ),
            {"samples": "samples", "events": "events", "materializada": materializada},
        )
        com_retencao = {r[0] for r in rows}
    assert com_retencao == {"samples", "events", materializada}


async def test_chunk_time_interval_das_hypertables(db_engine):
    # Regressão do chunk_time_interval declarado na 0002: 1 dia em samples, 7 dias em events.
    # time_interval vem como interval do Postgres -> comparado com timedelta, não com string.
    async with db_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT hypertable_name, time_interval"
                " FROM timescaledb_information.dimensions"
                " WHERE hypertable_name IN ('samples', 'events') AND column_name = 'ts'"
            )
        )
        intervalos = {r.hypertable_name: r.time_interval for r in rows}
    assert intervalos == {"samples": timedelta(days=1), "events": timedelta(days=7)}


async def test_refresh_policy_do_cagg_registrada(db_engine):
    # Escopado por view_name: a 0003 acrescenta um segundo CAgg (mpc_samples_1m), então
    # contar globalmente por proc_name deixou de identificar só o samples_1m.
    async with db_engine.connect() as conn:
        n = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM timescaledb_information.jobs j"
                    " JOIN timescaledb_information.continuous_aggregates ca"
                    "   ON ca.materialization_hypertable_name = j.hypertable_name"
                    " WHERE j.proc_name = 'policy_refresh_continuous_aggregate'"
                    " AND ca.view_name = 'samples_1m'"
                )
            )
        ).scalar_one()
    assert n == 1


async def test_cagg_agrega_avg_min_max_worst(db_engine):
    # CALL refresh_continuous_aggregate não roda em transação -> conexão AUTOCOMMIT
    async with db_engine.connect() as conn:
        ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await ac.execute(
            text(
                "INSERT INTO samples (ts, tag_id, value, quality) VALUES"
                " ('2026-01-15T10:00:05Z', 999001, 1.0, 0),"
                " ('2026-01-15T10:00:25Z', 999001, 2.0, 0),"
                " ('2026-01-15T10:00:45Z', 999001, 3.0, 2)"
            )
        )
        await ac.execute(text("CALL refresh_continuous_aggregate('samples_1m', NULL, NULL)"))
        row = (
            await ac.execute(
                text(
                    "SELECT avg_value, min_value, max_value, n_samples, worst_quality"
                    " FROM samples_1m WHERE tag_id = 999001"
                )
            )
        ).one()
        await ac.execute(text("DELETE FROM samples WHERE tag_id = 999001"))
    assert float(row.avg_value) == 2.0
    assert float(row.min_value) == 1.0
    assert float(row.max_value) == 3.0
    assert row.n_samples == 3
    assert row.worst_quality == 2


# --- mpc_samples (tarefa 2.1, spec F5 §2.2; F5R-07/08/21) ---


async def test_hypertable_mpc_samples_criada(db_engine):
    async with db_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT hypertable_name FROM timescaledb_information.hypertables")
        )
        names = {r[0] for r in rows}
    assert "mpc_samples" in names


async def test_chunk_time_interval_mpc_samples(db_engine):
    # chunk de 1 dia — intervalo de samples, não os 7 d de events (item 2 da tarefa; F5R-08)
    async with db_engine.connect() as conn:
        intervalo = (
            await conn.execute(
                text(
                    "SELECT time_interval FROM timescaledb_information.dimensions"
                    " WHERE hypertable_name = 'mpc_samples' AND column_name = 'ts'"
                )
            )
        ).scalar_one()
    assert intervalo == timedelta(days=1)


async def test_colunas_tipos_mpc_samples(db_engine):
    async with db_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
                " WHERE table_name = 'mpc_samples'"
            )
        )
        colunas = {r.column_name: (r.data_type, r.is_nullable) for r in rows}
    assert colunas == {
        "ts": ("timestamp with time zone", "NO"),
        "flow_id": ("bigint", "NO"),
        "block_id": ("text", "NO"),
        "var_id": ("text", "NO"),
        "v": ("double precision", "NO"),
        "sp": ("double precision", "YES"),
        "auto": ("boolean", "NO"),
    }


async def test_indice_flow_block_var_ts_em_mpc_samples(db_engine):
    async with db_engine.connect() as conn:
        idx = (
            await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE tablename = 'mpc_samples'"
                    " AND indexname = 'ix_mpc_samples_flow_block_var_ts'"
                )
            )
        ).scalar_one()
    assert "flow_id" in idx
    assert "block_id" in idx
    assert "var_id" in idx
    assert "ts DESC" in idx


async def test_retencao_1_mes_mpc_samples_e_1m(db_engine):
    # mpc_samples E mpc_samples_1m têm cada uma a sua policy de 1 mês (ADR-003, item 3/7)
    async with db_engine.connect() as conn:
        materializada = (
            await conn.execute(
                text(
                    "SELECT materialization_hypertable_name"
                    " FROM timescaledb_information.continuous_aggregates"
                    " WHERE view_name = 'mpc_samples_1m'"
                )
            )
        ).scalar_one()
        rows = await conn.execute(
            text(
                "SELECT hypertable_name FROM timescaledb_information.jobs"
                " WHERE proc_name = 'policy_retention'"
                " AND (config->>'drop_after')::interval = INTERVAL '1 month'"
                " AND hypertable_name IN (:mpc_samples, :materializada)"
            ),
            {"mpc_samples": "mpc_samples", "materializada": materializada},
        )
        com_retencao = {r[0] for r in rows}
    assert com_retencao == {"mpc_samples", materializada}


async def test_refresh_policy_do_cagg_mpc_samples_1m_registrada(db_engine):
    async with db_engine.connect() as conn:
        n = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM timescaledb_information.jobs j"
                    " JOIN timescaledb_information.continuous_aggregates ca"
                    "   ON ca.materialization_hypertable_name = j.hypertable_name"
                    " WHERE j.proc_name = 'policy_refresh_continuous_aggregate'"
                    " AND ca.view_name = 'mpc_samples_1m'"
                )
            )
        ).scalar_one()
    assert n == 1


async def test_cagg_mpc_samples_1m_agrega(db_engine):
    # CALL refresh_continuous_aggregate não roda em transação -> conexão AUTOCOMMIT
    async with db_engine.connect() as conn:
        ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await ac.execute(
            text(
                "INSERT INTO mpc_samples (ts, flow_id, block_id, var_id, v, sp, auto) VALUES"
                " ('2026-01-15T10:00:05Z', 1, 'ctrl1', 'pv', 1.0, 10.0, true),"
                " ('2026-01-15T10:00:25Z', 1, 'ctrl1', 'pv', 2.0, 10.0, false),"
                " ('2026-01-15T10:00:45Z', 1, 'ctrl1', 'pv', 3.0, 10.0, false)"
            )
        )
        await ac.execute(text("CALL refresh_continuous_aggregate('mpc_samples_1m', NULL, NULL)"))
        row = (
            await ac.execute(
                text(
                    "SELECT v, v_min, v_max, sp, auto FROM mpc_samples_1m"
                    " WHERE flow_id = 1 AND block_id = 'ctrl1' AND var_id = 'pv'"
                )
            )
        ).one()
        await ac.execute(text("DELETE FROM mpc_samples WHERE flow_id = 1"))
    assert float(row.v) == 2.0
    assert float(row.v_min) == 1.0
    assert float(row.v_max) == 3.0
    assert float(row.sp) == 10.0
    assert row.auto is True


def test_downgrade_remove_mpc_samples_e_cagg(migrated_database_url):
    # downgrade simétrico (item 8 da tarefa) — desce ATÉ a 0002 e volta ao head para não
    # vazar o estado para os demais testes da mesma sessão de container. Alvo explícito, não
    # `-1`: o passo relativo mudava de significado a cada migration nova acrescentada
    # depois da 0003 (foi o que a 0004 do SSTO quebrou).
    # Síncrono de propósito: alembic.command chama asyncio.run() internamente (env.py) e
    # não pode ser aninhado dentro do loop já ativo de um teste `async def`.
    cfg = Config("packages/ottima-core/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", migrated_database_url)
    try:
        command.downgrade(cfg, "0002_timescale")

        async def checar_ausencia() -> tuple[object, object]:
            engine = create_async_engine(migrated_database_url)
            async with engine.connect() as conn:
                mpc_samples = (
                    await conn.execute(text("SELECT to_regclass('public.mpc_samples')"))
                ).scalar()
                mpc_samples_1m = (
                    await conn.execute(text("SELECT to_regclass('public.mpc_samples_1m')"))
                ).scalar()
            await engine.dispose()
            return mpc_samples, mpc_samples_1m

        mpc_samples, mpc_samples_1m = asyncio.run(checar_ausencia())
        assert mpc_samples is None
        assert mpc_samples_1m is None
    finally:
        command.upgrade(cfg, "head")
