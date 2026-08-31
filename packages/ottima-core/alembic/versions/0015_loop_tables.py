"""loop_samples (hypertable + CAgg 1m) e loop_setpoints (ADR-039 secao 4.10)"""

import sqlalchemy as sa
from alembic import op

revision = "0015_loop_tables"
down_revision = "0014_mpc_setpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # loop_samples — amostras dos blocos malha por flow/bloco/var (var_id = pv|sp|out|mode);
    # `v` NULLavel (mesma liberacao da 0013 para valores ausentes).
    op.execute(
        """
        CREATE TABLE loop_samples (
          ts       TIMESTAMPTZ NOT NULL,
          flow_id  BIGINT NOT NULL,
          block_id TEXT NOT NULL,
          var_id   TEXT NOT NULL,
          v        DOUBLE PRECISION NULL
        )
        """
    )
    op.execute(
        "SELECT create_hypertable('loop_samples', 'ts', chunk_time_interval => INTERVAL '1 day')"
    )
    op.execute(
        "CREATE INDEX ix_loop_samples_flow_block_var_ts"
        " ON loop_samples (flow_id, block_id, var_id, ts DESC)"
    )
    op.execute("SELECT add_retention_policy('loop_samples', INTERVAL '1 month')")

    # CAgg 1 min — mesmos TRÊS passos das migrations 0002/0003/0010
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE MATERIALIZED VIEW loop_samples_1m WITH (timescaledb.continuous) AS
            SELECT time_bucket('1 minute', ts) AS bucket,
                   flow_id,
                   block_id,
                   var_id,
                   avg(v) AS v,
                   min(v) AS v_min,
                   max(v) AS v_max
            FROM loop_samples
            GROUP BY bucket, flow_id, block_id, var_id
            WITH NO DATA
            """
        )
        op.execute(
            "SELECT add_continuous_aggregate_policy('loop_samples_1m',"
            " start_offset => INTERVAL '1 hour',"
            " end_offset => INTERVAL '1 minute',"
            " schedule_interval => INTERVAL '1 minute')"
        )
        op.execute("SELECT add_retention_policy('loop_samples_1m', INTERVAL '1 month')")

    # loop_setpoints — valores de operacao que sobrevivem a restart (espelho de 0014).
    op.create_table(
        "loop_setpoints",
        sa.Column(
            "flow_id",
            sa.BigInteger,
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("block_id", sa.Text, nullable=False, primary_key=True),
        sa.Column("sp", sa.Double, nullable=True),
        sa.Column("man_out", sa.Double, nullable=True),
        sa.Column("target", sa.Text, nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("loop_setpoints")
    # remove as jobs antes de derrubar os objetos: mesmo motivo da 0003/0010 ("cache
    # lookup failed for relation" se um job do scheduler correr concorrente com o DROP).
    op.execute("SELECT remove_retention_policy('loop_samples_1m', if_exists => true)")
    op.execute("SELECT remove_continuous_aggregate_policy('loop_samples_1m', if_exists => true)")
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW IF EXISTS loop_samples_1m")
    op.execute("SELECT remove_retention_policy('loop_samples', if_exists => true)")
    op.execute("DROP TABLE IF EXISTS loop_samples")
