"""sensor virtual: modelos treinados e vínculo bloco -> modelo (ADR-046 D6, spec §7.4)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_soft_sensor"
down_revision = "0017_loop_setpoints_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soft_sensor_models",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("method", sa.Text, nullable=False),
        sa.Column("period_s", sa.Double, nullable=False),
        sa.Column("n_inputs", sa.SmallInteger, nullable=False),
        sa.Column(
            "input_tag_ids",
            postgresql.ARRAY(sa.BigInteger),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("meta", postgresql.JSONB, nullable=False),
        sa.Column("weights", sa.LargeBinary, nullable=False),
        sa.Column("created_by", sa.Text, nullable=False),
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
        sa.UniqueConstraint("project_id", "name", name="uq_soft_sensor_models_project_name"),
        sa.CheckConstraint("method IN ('pls','esn','lstm')", name="ck_soft_sensor_models_method"),
    )
    # As três FKs para o modelo ficam SEM `ON DELETE` (NO ACTION) e DEFERRABLE INITIALLY
    # DEFERRED: a checagem roda no COMMIT, depois que as cascatas terminam. Apagar um modelo
    # vinculado continua recusado, mas a cascata do projeto (flows+vínculos e modelos no mesmo
    # comando) passa: a ordem entre as duas cascatas é a dos triggers de RI (alfabética pelo
    # nome `RI_ConstraintTrigger_a_<oid>`) e, com a dos modelos primeiro, uma checagem imediata
    # ainda vê o vínculo de pé. RESTRICT e NO ACTION não adiado são imediatos: mesmo defeito.
    op.create_table(
        "soft_sensor_bindings",
        sa.Column(
            "flow_id",
            sa.BigInteger,
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("block_id", sa.Text, primary_key=True),
        sa.Column(
            "desired_model_id",
            sa.BigInteger,
            sa.ForeignKey("soft_sensor_models.id", deferrable=True, initially="DEFERRED"),
        ),
        sa.Column(
            "active_model_id",
            sa.BigInteger,
            sa.ForeignKey("soft_sensor_models.id", deferrable=True, initially="DEFERRED"),
        ),
        sa.Column(
            "candidate_model_id",
            sa.BigInteger,
            sa.ForeignKey("soft_sensor_models.id", deferrable=True, initially="DEFERRED"),
        ),
        sa.Column("updated_by", sa.Text, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    # Vínculos primeiro: referenciam os modelos.
    op.drop_table("soft_sensor_bindings")
    op.drop_table("soft_sensor_models")
