"""Tag calculada (RF-208, ADR-033): script Python do usuário roda em cadência fixa.

Estende uma linha em `tags` com `connection_id IS NULL` (ver `ck_tags_owner` em
`tag.py`) — o id compartilhado é o que faz histórico, `/api/history` e o `/ws`
funcionarem sem alteração nenhuma (ADR-033 D1).
"""

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base, TimestampMixin


class CalculatedTag(TimestampMixin, Base):
    """Script e período de uma tag calculada; `tag_id` é a linha correspondente em `tags`."""

    __tablename__ = "calculated_tags"

    tag_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    period_seconds: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    __table_args__ = (
        CheckConstraint("period_seconds IN (1,2,5,10,30,60)", name="ck_calculated_tags_period"),
    )


class CalculatedTagInput(Base):
    """Mapeamento posicional IN1..INn -> tag de origem (ADR-033 §3).

    Sem `TimestampMixin`: é uma aresta do grafo de dependências, não uma entidade com
    ciclo de vida próprio — reordenar as entradas é recriar as linhas, não atualizá-las.
    """

    __tablename__ = "calculated_tag_inputs"

    calc_tag_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("calculated_tags.tag_id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    source_tag_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tags.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("position BETWEEN 1 AND 8", name="ck_calculated_tag_inputs_position"),
        CheckConstraint("source_tag_id <> calc_tag_id", name="ck_calculated_tag_inputs_not_self"),
    )
