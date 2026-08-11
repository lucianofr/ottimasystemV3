"""watchdog migra de opc_connections para flows (ADR-009 revisado: granularidade por flow)"""

from alembic import op

revision = "0005_flow_watchdog"
down_revision = "0004_ssto_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE opc_connections
          DROP CONSTRAINT ck_opc_connections_wd_period,
          DROP COLUMN watchdog_read_node_id,
          DROP COLUMN watchdog_write_node_id,
          DROP COLUMN watchdog_period_ms
        """
    )
    op.execute(
        """
        ALTER TABLE flows
          ADD COLUMN watchdog_enabled BOOLEAN NOT NULL DEFAULT false,
          ADD COLUMN watchdog_connection_id BIGINT
            REFERENCES opc_connections(id) ON DELETE SET NULL,
          ADD COLUMN watchdog_read_node_id TEXT,
          ADD COLUMN watchdog_write_node_id TEXT,
          ADD COLUMN watchdog_period_ms INTEGER NOT NULL DEFAULT 1500,
          ADD CONSTRAINT ck_flows_wd_period CHECK (watchdog_period_ms BETWEEN 500 AND 5000)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE flows
          DROP CONSTRAINT ck_flows_wd_period,
          DROP COLUMN watchdog_read_node_id,
          DROP COLUMN watchdog_write_node_id,
          DROP COLUMN watchdog_period_ms,
          DROP COLUMN watchdog_connection_id,
          DROP COLUMN watchdog_enabled
        """
    )
    op.execute(
        """
        ALTER TABLE opc_connections
          ADD COLUMN watchdog_read_node_id TEXT,
          ADD COLUMN watchdog_write_node_id TEXT,
          ADD COLUMN watchdog_period_ms INTEGER NOT NULL DEFAULT 1500,
          ADD CONSTRAINT ck_opc_connections_wd_period
            CHECK (watchdog_period_ms BETWEEN 500 AND 5000)
        """
    )
