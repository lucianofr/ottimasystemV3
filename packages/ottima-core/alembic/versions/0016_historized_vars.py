"""variável historiada: porta de bloco gravada em `samples` (RF-308, ADR-041)"""

import sqlalchemy as sa
from alembic import op

revision = "0016_historized_vars"
down_revision = "0015_loop_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Sem sequence própria: a chave é `tags.id` (ADR-041 D1) — uma tabela com id próprio
    # gravando em `samples` colidiria com o id de tag na mesma série (ADR-033 D1).
    op.create_table(
        "historized_vars",
        sa.Column(
            "tag_id",
            sa.BigInteger,
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "flow_id",
            sa.BigInteger,
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("block_id", sa.Text, nullable=False),
        sa.Column("port", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("flow_id", "block_id", "port", name="uq_historized_vars_port"),
    )
    # ON DELETE CASCADE em `flow_id` sem índice varre a tabela inteira a cada delete de flow;
    # o runtime também carrega os registros por flow no build da definição.
    op.create_index("ix_historized_vars_flow_id", "historized_vars", ["flow_id"])


def downgrade() -> None:
    # As linhas de `tags` das variáveis historiadas (connection_id NULL, sem calculated_tags)
    # sobreviveriam ao drop da tabela e ficariam órfãs — invisíveis na tela Tags e fatais no
    # export. Apagar aqui é a única forma de o rollback deixar o banco coerente.
    op.execute(
        """
        DELETE FROM tags
        WHERE id IN (SELECT tag_id FROM historized_vars)
        """
    )
    op.drop_index("ix_historized_vars_flow_id", table_name="historized_vars")
    op.drop_table("historized_vars")
