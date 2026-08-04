"""hypertables, retenção 1 mês e continuous aggregate 1 min (spec F1 §3.2/§3.3)"""

from alembic import op

revision = "0002_timescale"
down_revision = "0001_relational"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # samples (ADR-003, RF-801) — sem FK em tag_id (spec §3.4 decisão N2)
    op.execute(
        """
        CREATE TABLE samples (
          ts      TIMESTAMPTZ NOT NULL,
          tag_id  BIGINT NOT NULL,
          value   DOUBLE PRECISION NOT NULL,
          quality SMALLINT NOT NULL DEFAULT 0
        )
        """
    )
    op.execute("SELECT create_hypertable('samples', 'ts', chunk_time_interval => INTERVAL '1 day')")
    op.execute("CREATE INDEX ix_samples_tag_ts ON samples (tag_id, ts DESC)")
    op.execute("SELECT add_retention_policy('samples', INTERVAL '1 month')")

    # events (ADR-020) — payload verbatim do canal `events` (PRD §7.1)
    op.execute(
        """
        CREATE TABLE events (
          ts       TIMESTAMPTZ NOT NULL,
          severity TEXT NOT NULL CHECK (severity IN ('info','warning','alarm')),
          origin   TEXT NOT NULL,
          message  TEXT NOT NULL,
          payload  JSONB NOT NULL DEFAULT '{}'
        )
        """
    )
    op.execute("SELECT create_hypertable('events', 'ts', chunk_time_interval => INTERVAL '7 days')")
    op.execute("CREATE INDEX ix_events_severity_ts ON events (severity, ts DESC)")
    op.execute("CREATE INDEX ix_events_origin_ts ON events (origin, ts DESC)")
    op.execute("SELECT add_retention_policy('events', INTERVAL '1 month')")

    # CAgg 1 min (RF-801/802; colunas além de avg: spec §3.4 decisão N1)
    # CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous) não roda em transação
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE MATERIALIZED VIEW samples_1m WITH (timescaledb.continuous) AS
            SELECT time_bucket('1 minute', ts) AS bucket,
                   tag_id,
                   avg(value)   AS avg_value,
                   min(value)   AS min_value,
                   max(value)   AS max_value,
                   count(*)     AS n_samples,
                   max(quality) AS worst_quality
            FROM samples
            GROUP BY bucket, tag_id
            WITH NO DATA
            """
        )
        op.execute(
            "SELECT add_continuous_aggregate_policy('samples_1m',"
            " start_offset => INTERVAL '1 hour',"
            " end_offset => INTERVAL '1 minute',"
            " schedule_interval => INTERVAL '1 minute')"
        )
        op.execute("SELECT add_retention_policy('samples_1m', INTERVAL '1 month')")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW IF EXISTS samples_1m")
    op.execute("DROP TABLE IF EXISTS events")
    op.execute("DROP TABLE IF EXISTS samples")
