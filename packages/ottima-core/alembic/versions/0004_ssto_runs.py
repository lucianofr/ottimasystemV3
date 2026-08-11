"""hypertable ssto_runs — auditoria imutável do SSTO (ADR-026 §11; RF-903)"""

from alembic import op

revision = "0004_ssto_runs"
down_revision = "0003_mpc_samples"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Uma linha por execução do SSTO. Só INSERT: o registro é auditoria, nunca é corrigido
    # (ADR-026 §11). Vetores em JSONB porque a dimensão (nº de MVs/linhas) é config do
    # bloco, não schema; escalares de filtro ficam em coluna própria.
    op.execute(
        """
        CREATE TABLE ssto_runs (
          ts                 TIMESTAMPTZ NOT NULL,
          flow_id            BIGINT NOT NULL,
          block_id           TEXT NOT NULL,
          run_id             TEXT NOT NULL,
          config_hash        TEXT NOT NULL,
          model_hash         TEXT NOT NULL,
          status             TEXT NOT NULL,
          solver             TEXT NOT NULL,
          solve_ms           DOUBLE PRECISION NOT NULL,
          objective          DOUBLE PRECISION NOT NULL,
          mv                 JSONB NOT NULL,
          cv_ss              JSONB NOT NULL,
          bias               JSONB NOT NULL,
          dv                 JSONB NOT NULL,
          costs              JSONB NOT NULL,
          delta_mv           JSONB NOT NULL,
          mv_target          JSONB NOT NULL,
          cv_target          JSONB NOT NULL,
          given_up           JSONB NOT NULL,
          active_constraints JSONB NOT NULL,
          duals              JSONB NOT NULL
        )
        """
    )
    op.execute(
        "SELECT create_hypertable('ssto_runs', 'ts', chunk_time_interval => INTERVAL '1 day')"
    )
    op.execute("CREATE INDEX ix_ssto_runs_flow_block_ts ON ssto_runs (flow_id, block_id, ts DESC)")
    # Retenção pela policy do Timescale, nunca por código de limpeza (ADR-003).
    op.execute("SELECT add_retention_policy('ssto_runs', INTERVAL '1 month')")


def downgrade() -> None:
    # Remove a job antes de derrubar a tabela: a 1ª execução do scheduler pode correr com o
    # DROP e invalidar o catálogo (mesmo cuidado da 0003).
    op.execute("SELECT remove_retention_policy('ssto_runs', if_exists => true)")
    op.execute("DROP TABLE IF EXISTS ssto_runs")
