"""timeout do watchdog configurável por flow (RF-206 revisado: FREEZE_THRESHOLD_S vira coluna)"""

from alembic import op

revision = "0007_flow_watchdog_timeout"
down_revision = "0006_history_retention_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE flows
          ADD COLUMN watchdog_timeout_s INTEGER NOT NULL DEFAULT 10,
          ADD CONSTRAINT ck_flows_wd_timeout CHECK (watchdog_timeout_s BETWEEN 2 AND 120)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE flows
          DROP CONSTRAINT ck_flows_wd_timeout,
          DROP COLUMN watchdog_timeout_s
        """
    )
