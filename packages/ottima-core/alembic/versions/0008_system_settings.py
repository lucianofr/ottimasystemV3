"""retenção de events configurável + singleton de configurações do sistema (RF-803/805)

(a) `history_retention_settings` ganha `events_retention_days` (1–90, default 30) e a
política fixa de `events` (1 month, migration 0002) é reprogramada para o default novo;
(b) nasce o singleton `system_settings` com o nível de log dos serviços (ADR-020/RF-805).
"""

from alembic import op

revision = "0008_system_settings"
down_revision = "0007_flow_watchdog_timeout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE history_retention_settings
          ADD COLUMN events_retention_days SMALLINT NOT NULL DEFAULT 30
            CHECK (events_retention_days BETWEEN 1 AND 90)
        """
    )
    op.execute(
        """
        CREATE TABLE system_settings (
          id         SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
          log_level  TEXT NOT NULL DEFAULT 'INFO'
            CHECK (log_level IN ('DEBUG','INFO','WARNING','ERROR','CRITICAL')),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("INSERT INTO system_settings (id, log_level) VALUES (1, 'INFO')")
    # A política fixa de 0002 (1 month) passa a refletir a coluna nova (default 30 dias).
    op.execute("SELECT remove_retention_policy('events', if_exists => true)")
    op.execute("SELECT add_retention_policy('events', INTERVAL '30 days')")


def downgrade() -> None:
    op.execute("SELECT remove_retention_policy('events', if_exists => true)")
    op.execute("SELECT add_retention_policy('events', INTERVAL '1 month')")
    op.execute("DROP TABLE IF EXISTS system_settings")
    op.execute("ALTER TABLE history_retention_settings DROP COLUMN events_retention_days")
