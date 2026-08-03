"""tabelas relacionais F1 (spec F1 §3.1)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_relational"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("username", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
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
        sa.CheckConstraint("role IN ('admin','operator')", name="ck_users_role"),
    )
    op.create_index("uq_users_username", "users", [sa.text("lower(username)")], unique=True)

    op.create_table(
        "projects",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("false")),
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
    )
    op.create_index(
        "uq_projects_single_active",
        "projects",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "opc_connections",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("endpoint", sa.Text, nullable=False),
        sa.Column("security_policy", sa.Text, nullable=False, server_default=sa.text("'none'")),
        sa.Column("security_mode", sa.Text, nullable=False, server_default=sa.text("'none'")),
        sa.Column("auth_mode", sa.Text, nullable=False, server_default=sa.text("'anonymous'")),
        sa.Column("auth_username", sa.Text),
        sa.Column("auth_password_enc", sa.Text),
        sa.Column("server_cert_file", sa.Text),
        sa.Column("watchdog_read_node_id", sa.Text),
        sa.Column("watchdog_write_node_id", sa.Text),
        sa.Column(
            "watchdog_period_ms", sa.Integer, nullable=False, server_default=sa.text("1500")
        ),
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
        sa.UniqueConstraint("project_id", "name", name="uq_opc_connections_project_name"),
        sa.CheckConstraint(
            "security_policy IN ('none','basic256sha256')", name="ck_opc_connections_policy"
        ),
        sa.CheckConstraint(
            "security_mode IN ('none','sign','sign_and_encrypt')", name="ck_opc_connections_mode"
        ),
        sa.CheckConstraint(
            "auth_mode IN ('anonymous','user_password','certificate')",
            name="ck_opc_connections_auth",
        ),
        sa.CheckConstraint(
            "watchdog_period_ms BETWEEN 500 AND 5000", name="ck_opc_connections_wd_period"
        ),
        sa.CheckConstraint(
            "(security_policy = 'none' AND security_mode = 'none')"
            " OR (security_policy <> 'none' AND security_mode <> 'none')",
            name="ck_opc_connections_policy_mode",
        ),
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "connection_id",
            sa.BigInteger,
            sa.ForeignKey("opc_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("node_id", sa.Text, nullable=False),
        sa.Column("direction", sa.Text, nullable=False),
        sa.Column("data_type", sa.Text, nullable=False),
        sa.Column("eu", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("description", sa.Text, nullable=False, server_default=sa.text("''")),
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
        sa.UniqueConstraint("connection_id", "name", name="uq_tags_connection_name"),
        sa.CheckConstraint("direction IN ('r','w')", name="ck_tags_direction"),
        sa.CheckConstraint("data_type IN ('float','int','bool')", name="ck_tags_data_type"),
    )

    op.create_table(
        "flows",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "project_id",
            sa.BigInteger,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("ts_seconds", sa.Numeric(4, 1), nullable=False),
        sa.Column("desired_state", sa.Text, nullable=False, server_default=sa.text("'stopped'")),
        sa.Column(
            "graph_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{\"nodes\": [], \"edges\": []}'::jsonb"),
        ),
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
        sa.UniqueConstraint("project_id", "name", name="uq_flows_project_name"),
        sa.CheckConstraint("ts_seconds IN (0.5,1,2,5,10,30,60)", name="ck_flows_ts"),
        sa.CheckConstraint("desired_state IN ('running','stopped')", name="ck_flows_desired_state"),
    )


def downgrade() -> None:
    op.drop_table("flows")
    op.drop_table("tags")
    op.drop_table("opc_connections")
    op.drop_index("uq_projects_single_active", table_name="projects")
    op.drop_table("projects")
    op.drop_index("uq_users_username", table_name="users")
    op.drop_table("users")
