"""Faxina do vínculo bloco -> modelo do sensor virtual no save do flow (spec §7.4, RF-584).

Mesma razão da poda de variável historiada (ADR-041): vínculo de bloco que saiu do grafo (ou
que deixou de ser sensor virtual) ficaria órfão e, por referenciar o modelo, impediria apagá-lo
para sempre.
"""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.flowgraph import SOFT_SENSOR_TYPES, FlowGraph
from ottima_core.models import SoftSensorBinding


async def podar_vinculos_soft_sensor(db: AsyncSession, flow_id: int, grafo: FlowGraph) -> int:
    """Apaga o vínculo de todo `block_id` ausente do grafo recém-salvo ou cujo nó já não é de
    sensor virtual; devolve quantos apagou. Roda na transação do save do flow (o rollback do
    commit desfaz a poda junto). Vínculo de bloco que só mudou de rótulo ou de posição fica."""
    vivos = [no.id for no in grafo.nodes if no.type in SOFT_SENSOR_TYPES]
    resultado = await db.execute(
        delete(SoftSensorBinding).where(
            SoftSensorBinding.flow_id == flow_id, SoftSensorBinding.block_id.not_in(vivos)
        )
    )
    return resultado.rowcount
