"""samples.value aceita NULL: quality=2 (BAD) grava NULL no lugar do valor bruto (ADR-037)"""

from alembic import op

revision = "0013_samples_value_nullable"
down_revision = "0012_calculated_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE samples ALTER COLUMN value DROP NOT NULL")


def downgrade() -> None:
    # amostras já gravadas com NULL (quality=2, ADR-037) impedem o SET NOT NULL direto —
    # mesmo raciocínio de qualquer downgrade que reaperta uma constraint relaxada.
    op.execute("DELETE FROM samples WHERE value IS NULL")
    op.execute("ALTER TABLE samples ALTER COLUMN value SET NOT NULL")
