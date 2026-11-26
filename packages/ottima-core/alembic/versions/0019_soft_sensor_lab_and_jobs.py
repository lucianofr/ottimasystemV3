"""sensor virtual: laboratório, conjunto de treino e fila de jobs (ADR-046 D1/D7, spec §7)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019_soft_sensor_lab_and_jobs"
down_revision = "0018_soft_sensor"
branch_labels = None
depends_on = None


def _timestamp(name: str) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def upgrade() -> None:
    op.create_table(
        "lab_variables",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("eu", sa.Text, nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.UniqueConstraint("project_id", "name", name="uq_lab_variables_project_name"),
    )
    op.create_table(
        "lab_samples",
        sa.Column(
            "lab_variable_id",
            sa.BigInteger,
            sa.ForeignKey("lab_variables.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("sampled_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("value", sa.Double, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("created_by", sa.Text, nullable=False),
        _timestamp("created_at"),
        sa.CheckConstraint("source IN ('manual','csv')", name="ck_lab_samples_source"),
    )
    op.create_table(
        "soft_sensor_datasets",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column(
            "lab_variable_id",
            sa.BigInteger,
            sa.ForeignKey("lab_variables.id"),
            nullable=False,
        ),
        sa.Column("input_tag_ids", postgresql.ARRAY(sa.BigInteger), nullable=False),
        sa.Column("period_s", sa.Double, nullable=False),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text, nullable=False, server_default="collecting"),
        sa.Column("stats", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "inputs_meta", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("data", sa.LargeBinary),
        sa.Column("created_by", sa.Text, nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.UniqueConstraint("project_id", "name", name="uq_soft_sensor_datasets_project_name"),
        sa.CheckConstraint(
            "period_s IN (1,2,5,10,30,60,300,600)", name="ck_soft_sensor_datasets_period"
        ),
        sa.CheckConstraint(
            "status IN ('collecting','building','ready','failed')",
            name="ck_soft_sensor_datasets_status",
        ),
    )
    op.create_table(
        "ml_jobs",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("params", postgresql.JSONB, nullable=False),
        sa.Column(
            "progress", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("result", postgresql.JSONB),
        sa.Column("error", sa.Text),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Text, nullable=False),
        _timestamp("created_at"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('dataset_build','train','tune')", name="ck_ml_jobs_kind"),
        sa.CheckConstraint(
            "status IN ('queued','running','done','failed','cancelled')", name="ck_ml_jobs_status"
        ),
    )
    op.create_index("ix_ml_jobs_status_id", "ml_jobs", ["status", "id"])


def downgrade() -> None:
    # Ordem inversa das FKs: jobs e conjuntos antes das análises e da variável.
    op.drop_table("ml_jobs")
    op.drop_table("soft_sensor_datasets")
    op.drop_table("lab_samples")
    op.drop_table("lab_variables")
