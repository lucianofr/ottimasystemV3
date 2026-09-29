"""Variável historiada: porta de bloco gravada ciclicamente em `samples` (RF-308, ADR-041).

Estende uma linha em `tags` com `connection_id IS NULL` (ver `ck_tags_owner` em `tag.py`) —
o id compartilhado é o que faz histórico, `/api/history`, `/ws`, retenção e a lista do TREND
funcionarem sem alteração nenhuma, exatamente como na tag calculada (ADR-033 D1). A diferença
é só quem produz o valor: aqui é o `flow-runtime`, publicando em `flow.values` (ADR-041 D2).

Ciclo de vida (ADR-041 D5): a cascata só corre de `tags.id` para cá. Toda remoção — rota
DELETE, poda no save do flow, remoção do flow — apaga a linha de `tags`, nunca esta linha
isolada; apagar só esta deixaria uma tag órfã, eterna no seletor do TREND e fatal no export.
"""

from sqlalchemy import BigInteger, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base, TimestampMixin


class HistorizedVar(TimestampMixin, Base):
    """Porta `(flow_id, block_id, port)` historiada; `tag_id` é a linha em `tags`."""

    __tablename__ = "historized_vars"

    tag_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    flow_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("flows.id", ondelete="CASCADE"), nullable=False
    )
    block_id: Mapped[str] = mapped_column(Text, nullable=False)
    port: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        # Uma porta é historiada no máximo uma vez: duas tags na mesma série seriam dois
        # nomes para o mesmo dado, com o dobro de linhas em `samples`.
        UniqueConstraint("flow_id", "block_id", "port", name="uq_historized_vars_port"),
        # O runtime carrega os registros por flow no build da definição (hot-swap, ADR-011);
        # a poda do save e o delete do flow varrem pelo mesmo recorte.
        Index("ix_historized_vars_flow_id", "flow_id"),
    )
