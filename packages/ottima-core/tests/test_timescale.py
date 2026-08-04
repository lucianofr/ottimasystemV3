from datetime import timedelta

from sqlalchemy import text


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
    async with db_engine.connect() as conn:
        n = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM timescaledb_information.jobs"
                    " WHERE proc_name = 'policy_refresh_continuous_aggregate'"
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
