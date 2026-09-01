"""fuzzy_surface_lut: superficie compilada, content-addressed (SPEC_FUZZY secao 5.2)"""

import sqlalchemy as sa
from alembic import op

revision = "0016_fuzzy_surface_lut"
down_revision = "0015_loop_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Content-addressed: a PK e o sha256 do texto FLL, SEM FK para flow/bloco.
    #
    # Nao existem revisoes de config no sistema (ADR-011: config vive no `graph_json`), logo
    # nao ha o que referenciar; e enderecar por conteudo dedupa de graca entre blocos que
    # compartilham a mesma base de regras e torna a invalidacao trivial — hash divergente do
    # `.fll` corrente significa LUT velha, que e simplesmente ignorada e regerada (ADR-039
    # D11).
    op.create_table(
        "fuzzy_surface_lut",
        sa.Column("fll_hash", sa.Text, primary_key=True),
        sa.Column("resolution", sa.Integer, nullable=False),
        # float32 em C-order, `resolution * resolution * 4` bytes (65x65 = 16 KB).
        sa.Column("payload", sa.LargeBinary, nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("fuzzy_surface_lut")
