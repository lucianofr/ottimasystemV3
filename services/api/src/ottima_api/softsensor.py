"""Faxina do vínculo bloco -> modelo do sensor virtual no save do flow (spec §7.4, RF-584).

Mesma razão da poda de variável historiada (ADR-041): vínculo de bloco que saiu do grafo (ou
que mudou de tipo) ficaria órfão e, por referenciar o modelo, impediria apagá-lo para sempre.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.flowgraph import SOFT_SENSOR_TYPES, FlowGraph
from ottima_core.models import SoftSensorBinding


async def podar_vinculos_soft_sensor(
    db: AsyncSession,
    flow_id: int,
    grafo: FlowGraph,
    grafo_anterior: Mapping[str, Any] | None = None,
) -> int:
    """Apaga o vínculo de todo `block_id` ausente do grafo recém-salvo, que já não é sensor
    virtual ou cujo tipo mudou em relação ao grafo anterior (inclusive `soft_sensor_pls` ->
    `soft_sensor_esn`: o modelo guardado é de outro método); devolve quantos apagou. Roda na
    transação do save do flow (o rollback do commit desfaz a poda junto). Vínculo de bloco que só
    mudou de rótulo ou de posição fica.

    `grafo_anterior` é o `graph_json` JÁ persistido (JSON cru, sem reparse: grafo antigo ilegível
    não pode derrubar o save). Sem ele, só a ausência e a perda da condição de sensor virtual
    contam. Bloco sem registro no grafo anterior não tem tipo a comparar e fica.
    """
    antigos = {n.get("id"): n.get("type") for n in (grafo_anterior or {}).get("nodes", [])}
    vivos = [
        no.id
        for no in grafo.nodes
        if no.type in SOFT_SENSOR_TYPES and antigos.get(no.id, no.type) == no.type
    ]
    resultado = await db.execute(
        delete(SoftSensorBinding).where(
            SoftSensorBinding.flow_id == flow_id, SoftSensorBinding.block_id.not_in(vivos)
        )
    )
    return resultado.rowcount
