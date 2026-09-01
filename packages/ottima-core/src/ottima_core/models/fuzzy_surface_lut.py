"""Superficie de controle compilada de um `fuzzy_loop` (SPEC_FUZZY secao 5.2).

Content-addressed: a chave e o sha256 do texto FLL, sem FK para flow ou bloco. Nao existem
revisoes de config no sistema (ADR-011), logo nao ha o que referenciar; enderecar por
conteudo dedupa entre blocos com a mesma base de regras e torna a invalidacao trivial (hash
divergente do `.fll` corrente = LUT velha, ignorada e regerada).
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ottima_core.models.base import Base


class FuzzySurfaceLut(Base):
    __tablename__ = "fuzzy_surface_lut"

    fll_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    resolution: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    """float32 em C-order: `resolution * resolution * 4` bytes (65x65 = 16 KB)."""

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
