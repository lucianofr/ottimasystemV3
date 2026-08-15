"""tag calculada: script Python do usuário em cadência fixa (RF-208, ADR-033)"""

import sqlalchemy as sa
from alembic import op

revision = "0012_calculated_tags"
down_revision = "0011_opc_polling_period"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tags
          ALTER COLUMN connection_id DROP NOT NULL,
          ALTER COLUMN node_id       DROP NOT NULL,
          ADD COLUMN project_id BIGINT REFERENCES projects(id) ON DELETE CASCADE,
          ADD CONSTRAINT ck_tags_owner CHECK (
            (connection_id IS NOT NULL AND project_id IS NULL     AND node_id IS NOT NULL)
            OR (connection_id IS NULL AND project_id IS NOT NULL AND node_id IS NULL)
          )
        """
    )
    # Parcial: nome único por projeto só entre as tags calculadas (connection_id IS NULL).
    # Uma tag OPC continua livre para repetir nome entre conexões diferentes — seu escopo
    # de unicidade é uq_tags_connection_name, que este índice não toca.
    op.create_index(
        "uq_tags_project_name",
        "tags",
        ["project_id", "name"],
        unique=True,
        postgresql_where=sa.text("connection_id IS NULL"),
    )

    op.create_table(
        "calculated_tags",
        sa.Column(
            "tag_id",
            sa.BigInteger,
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("period_seconds", sa.SmallInteger, nullable=False),
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
        sa.CheckConstraint("period_seconds IN (1,2,5,10,30,60)", name="ck_calculated_tags_period"),
    )

    op.create_table(
        "calculated_tag_inputs",
        sa.Column(
            "calc_tag_id",
            sa.BigInteger,
            sa.ForeignKey("calculated_tags.tag_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.SmallInteger, primary_key=True),
        sa.Column(
            "source_tag_id",
            sa.BigInteger,
            sa.ForeignKey("tags.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.CheckConstraint("position BETWEEN 1 AND 8", name="ck_calculated_tag_inputs_position"),
        sa.CheckConstraint(
            "source_tag_id <> calc_tag_id", name="ck_calculated_tag_inputs_not_self"
        ),
    )
    # ON DELETE RESTRICT na origem não protege sozinho contra seq scan: sem índice, apagar
    # uma tag usada como entrada varre calculated_tag_inputs inteira para checar a FK.
    op.create_index(
        "ix_calculated_tag_inputs_source_tag_id", "calculated_tag_inputs", ["source_tag_id"]
    )


def downgrade() -> None:
    # connection_id/node_id voltando a NOT NULL com linhas calculadas ainda presentes falha
    # com um erro opaco do Postgres ("column contains null values"). Recusar aqui, cedo e em
    # pt-BR, poupa quem está fazendo rollback de caçar isso às 3h.
    conn = op.get_bind()
    (quantidade,) = conn.execute(sa.text("SELECT count(*) FROM calculated_tags")).one()
    if quantidade:
        raise RuntimeError(
            f"Downgrade da 0012 recusado: existem {quantidade} tag(s) calculada(s) no banco. "
            "Apague as tags calculadas antes de rodar este downgrade."
        )

    op.drop_index("ix_calculated_tag_inputs_source_tag_id", table_name="calculated_tag_inputs")
    op.drop_table("calculated_tag_inputs")
    op.drop_table("calculated_tags")
    op.drop_index("uq_tags_project_name", table_name="tags")
    op.execute(
        """
        ALTER TABLE tags
          DROP CONSTRAINT ck_tags_owner,
          DROP COLUMN project_id,
          ALTER COLUMN connection_id SET NOT NULL,
          ALTER COLUMN node_id       SET NOT NULL
        """
    )
