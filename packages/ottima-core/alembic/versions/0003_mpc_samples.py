"""hypertable mpc_samples com CAgg 1 min (spec F5 §2.2; F5R-07/08/21)"""

from alembic import op

revision = "0003_mpc_samples"
down_revision = "0002_timescale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # mpc_samples (RF-703, ADR-003) — amostras dos blocos MPC por flow/bloco/variável
    op.execute(
        """
        CREATE TABLE mpc_samples (
          ts       TIMESTAMPTZ NOT NULL,
          flow_id  BIGINT NOT NULL,
          block_id TEXT NOT NULL,
          var_id   TEXT NOT NULL,
          v        DOUBLE PRECISION NOT NULL,
          sp       DOUBLE PRECISION,
          auto     BOOLEAN NOT NULL
        )
        """
    )
    op.execute(
        "SELECT create_hypertable('mpc_samples', 'ts', chunk_time_interval => INTERVAL '1 day')"
    )
    op.execute(
        "CREATE INDEX ix_mpc_samples_flow_block_var_ts"
        " ON mpc_samples (flow_id, block_id, var_id, ts DESC)"
    )
    op.execute("SELECT add_retention_policy('mpc_samples', INTERVAL '1 month')")

    # CAgg 1 min (RF-703) — mesmos TRÊS passos da 0002 (F5R-07)
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE MATERIALIZED VIEW mpc_samples_1m WITH (timescaledb.continuous) AS
            SELECT time_bucket('1 minute', ts) AS bucket,
                   flow_id,
                   block_id,
                   var_id,
                   avg(v)        AS v,
                   min(v)        AS v_min,
                   max(v)        AS v_max,
                   avg(sp)       AS sp,
                   bool_or(auto) AS auto
            FROM mpc_samples
            GROUP BY bucket, flow_id, block_id, var_id
            WITH NO DATA
            """
        )
        op.execute(
            "SELECT add_continuous_aggregate_policy('mpc_samples_1m',"
            " start_offset => INTERVAL '1 hour',"
            " end_offset => INTERVAL '1 minute',"
            " schedule_interval => INTERVAL '1 minute')"
        )
        op.execute("SELECT add_retention_policy('mpc_samples_1m', INTERVAL '1 month')")


def downgrade() -> None:
    # remove as jobs antes de derrubar os objetos: a 1ª execução de retention/refresh do
    # scheduler do TimescaleDB pode disparar quase imediato após a policy ser criada, e
    # correr com o DROP causa "cache lookup failed for relation" (catálogo invalidado
    # por DDL concorrente do job).
    op.execute("SELECT remove_retention_policy('mpc_samples_1m', if_exists => true)")
    op.execute("SELECT remove_continuous_aggregate_policy('mpc_samples_1m', if_exists => true)")
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW IF EXISTS mpc_samples_1m")
    op.execute("SELECT remove_retention_policy('mpc_samples', if_exists => true)")
    op.execute("DROP TABLE IF EXISTS mpc_samples")
