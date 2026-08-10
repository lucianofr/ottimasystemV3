"""Consulta de conexões do projeto: compartilhada entre API e flow-runtime."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.models import OpcConnection


async def conexoes_sem_watchdog(session: AsyncSession, project_id: int) -> dict[int, str]:
    """`conn_id -> nome` das conexões do projeto sem watchdog completo (TD-004).

    Sem os dois node_ids não há handshake — mesma regra de `ConnectionConfig.has_watchdog`
    (`services/opc-worker/src/ottima_opc_worker/state.py`), aplicada aqui sobre o modelo
    ORM: basta faltar um dos dois. Usada tanto pelo aviso do salvar (`services/api`) quanto
    pelo gate de arme do MPC no deploy (`services/flow-runtime`) — uma consulta só, não uma
    segunda regra.
    """
    stmt = select(OpcConnection.id, OpcConnection.name).where(
        OpcConnection.project_id == project_id,
        or_(
            OpcConnection.watchdog_read_node_id.is_(None),
            OpcConnection.watchdog_write_node_id.is_(None),
        ),
    )
    return {row.id: row.name for row in await session.execute(stmt)}
