"""período de varredura configurável por conexão OPC-UA (ADR-032: subscription vira polling)"""

from alembic import op

revision = "0011_opc_polling_period"
down_revision = "0010_fuzzy_samples"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE opc_connections
          ADD COLUMN polling_period_ms INTEGER NOT NULL DEFAULT 1000,
          ADD CONSTRAINT ck_opc_connections_polling_period
            CHECK (polling_period_ms BETWEEN 100 AND 60000)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE opc_connections
          DROP CONSTRAINT ck_opc_connections_polling_period,
          DROP COLUMN polling_period_ms
        """
    )
