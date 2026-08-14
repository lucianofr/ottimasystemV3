"""hypertable fuzzy_samples com CAgg 1 min (FUZZY OPERATE, espelho de 0003_mpc_samples)"""

from alembic import op

revision = "0010_fuzzy_samples"
down_revision = "0009_mpc_max_rate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # fuzzy_samples — amostras dos blocos fuzzy por flow/bloco/porta (`var_id` = porta
    # IN1..INn/OUT1..OUTn, ADR-029); sem `sp`/`auto` (conceitos de MPC, não de fuzzy).
    op.execute(
        """
        CREATE TABLE fuzzy_samples (
          ts       TIMESTAMPTZ NOT NULL,
          flow_id  BIGINT NOT NULL,
          block_id TEXT NOT NULL,
          var_id   TEXT NOT NULL,
          v        DOUBLE PRECISION NOT NULL
        )
        """
    )
    op.execute(
        "SELECT create_hypertable('fuzzy_samples', 'ts', chunk_time_interval => INTERVAL '1 day')"
    )
    op.execute(
        "CREATE INDEX ix_fuzzy_samples_flow_block_var_ts"
        " ON fuzzy_samples (flow_id, block_id, var_id, ts DESC)"
    )
    op.execute("SELECT add_retention_policy('fuzzy_samples', INTERVAL '1 month')")

    # CAgg 1 min — mesmos TRÊS passos das migrations 0002/0003
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE MATERIALIZED VIEW fuzzy_samples_1m WITH (timescaledb.continuous) AS
            SELECT time_bucket('1 minute', ts) AS bucket,
                   flow_id,
                   block_id,
                   var_id,
                   avg(v) AS v,
                   min(v) AS v_min,
                   max(v) AS v_max
            FROM fuzzy_samples
            GROUP BY bucket, flow_id, block_id, var_id
            WITH NO DATA
            """
        )
        op.execute(
            "SELECT add_continuous_aggregate_policy('fuzzy_samples_1m',"
            " start_offset => INTERVAL '1 hour',"
            " end_offset => INTERVAL '1 minute',"
            " schedule_interval => INTERVAL '1 minute')"
        )
        op.execute("SELECT add_retention_policy('fuzzy_samples_1m', INTERVAL '1 month')")


def downgrade() -> None:
    # remove as jobs antes de derrubar os objetos: mesmo motivo da 0003 ("cache lookup
    # failed for relation" se um job do scheduler correr concorrente com o DROP).
    op.execute("SELECT remove_retention_policy('fuzzy_samples_1m', if_exists => true)")
    op.execute("SELECT remove_continuous_aggregate_policy('fuzzy_samples_1m', if_exists => true)")
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW IF EXISTS fuzzy_samples_1m")
    op.execute("SELECT remove_retention_policy('fuzzy_samples', if_exists => true)")
    op.execute("DROP TABLE IF EXISTS fuzzy_samples")
