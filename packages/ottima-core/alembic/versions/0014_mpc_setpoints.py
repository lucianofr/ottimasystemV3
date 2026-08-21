"""SP do operador do bloco MPC persistido (emenda da decisão A-4 da spec F4)

O SP escrito pelo operador em AUTO sobrevive a restart/redeploy/stop-start: uma linha
por `(flow_id, block_id, var_id)` com o valor já clampado. Os MODOS seguem voláteis
(boot sempre LOCAL+MAN, RNF-03/ADR-010 intactos) — só o NÚMERO persiste.
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_mpc_setpoints"
down_revision = "0013_samples_value_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mpc_setpoints",
        sa.Column(
            "flow_id",
            sa.BigInteger,
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("block_id", sa.Text, nullable=False, primary_key=True),
        sa.Column("var_id", sa.Text, nullable=False, primary_key=True),
        sa.Column("value", sa.Double, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("mpc_setpoints")
