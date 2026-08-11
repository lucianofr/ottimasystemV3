"""tabela singleton de retenção de histórico configurável (ADR-003 revisado)"""

from alembic import op

revision = "0006_history_retention_settings"
down_revision = "0005_flow_watchdog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE history_retention_settings (
          id             SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
          retention_days SMALLINT NOT NULL DEFAULT 30
            CHECK (retention_days BETWEEN 1 AND 120),
          updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Seed único: preserva o comportamento atual (~1 mês) até um admin ajustar (ADR-003 revisado).
    op.execute("INSERT INTO history_retention_settings (id, retention_days) VALUES (1, 30)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS history_retention_settings")
