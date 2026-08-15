"""Consulta de tags do projeto: compartilhada entre API e flow-runtime."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.flowgraph import TagRef
from ottima_core.models import OpcConnection, Tag


async def project_tags(session: AsyncSession, project_id: int) -> dict[int, TagRef]:
    """Tags visíveis ao flow: as do projeto dele, via conexão (o `graph_json` não tem FK).

    Uma consulta para o grafo inteiro — o número de nós não pode virar número de queries.
    """
    stmt = (
        select(Tag.id, Tag.connection_id, Tag.direction, Tag.data_type)
        # INNER JOIN é a fronteira do v1 (ADR-033 D5): tag calculada tem `connection_id`
        # NULL e nunca casa aqui, então nunca vira `TagRef` — de propósito, não bug. Trocar
        # por LEFT JOIN quebraria `TagRef.conn_id: int` (obrigatório) no primeiro projeto
        # com tag calculada.
        .join(OpcConnection, OpcConnection.id == Tag.connection_id)
        .where(OpcConnection.project_id == project_id)
    )
    return {
        row.id: TagRef(
            id=row.id,
            conn_id=row.connection_id,
            direction=row.direction,
            data_type=row.data_type,
        )
        for row in await session.execute(stmt)
    }
