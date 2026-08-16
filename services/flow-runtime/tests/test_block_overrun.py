"""Bloco que estoura o orçamento individual publica `block_overrun` nomeando o culpado (ARCH-11).

Complementa `test_isolamento_temporal.py`: aquele prova o EFEITO COLATERAL do defeito aberto
(a fronteira do flow vizinho é perdida — hoje `xfail(strict=True)` permanente, porque medir
não corrige a perda). Este prova só a OBSERVABILIDADE nova: o scheduler cronometra cada
`block.step()` individualmente e nomeia o bloco quando ele, sozinho, já estoura o orçamento —
100% do `Ts` do próprio flow (`scheduler.py::BLOCK_BUDGET_FRACTION`), o único limiar que não
depende de suposição nenhuma sobre quantos blocos irmãos dividem o ciclo.

Relógio real (`SystemClock`), como `test_isolamento_temporal.py`: o `FakeClock` de
`test_scheduler.py` não produz custo de verdade dentro de um `time.sleep` (`clock.advance` é
virtual), então não exerceria o cronômetro que o scheduler realmente usa.
"""

import time
from collections.abc import Mapping
from datetime import datetime

from redis.asyncio import Redis

from ottima_core.bus import CHANNEL_EVENTS, KIND_BLOCK_OVERRUN, EventMessage
from ottima_flow_runtime.blocks.base import Block, PortSample
from ottima_flow_runtime.scheduler import FlowDefinition, FlowTask

FLOW_ID = 601
TS_S = 0.1
"""Orçamento por bloco = 100% do Ts = 100 ms (`BLOCK_BUDGET_FRACTION` em scheduler.py)."""

CUSTO_S = 0.2
"""~200 ms: 2x o orçamento de 100 ms, estoura sem ambiguidade de tolerância de máquina."""

JANELA_S = 1.0
"""Tempo de parede observado após o disparo: cabe várias fronteiras de sobra do flow."""


class BlocoQuenteUmaVez(Block):
    """Gasta ~200 ms na primeira varredura só; nas seguintes, custo zero.

    Uma varredura já basta para provar o evento; manter as seguintes baratas é o que torna
    "exatamente um `block_overrun`" uma asserção determinística, não uma corrida contra o
    rearme (que também dispara de novo se o bloco voltar a estourar depois de se recuperar).
    """

    def __init__(self, block_id: str) -> None:
        super().__init__(block_id)
        self.execucoes = 0

    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        self.execucoes += 1
        if self.execucoes == 1:
            time.sleep(CUSTO_S)  # noqa: ASYNC251 — custo síncrono real, o sujeito do teste
        return {}


async def test_bloco_que_estoura_orcamento_emite_block_overrun_nomeando_o_culpado(
    redis_client: Redis,
):
    bloco = BlocoQuenteUmaVez("quente")
    definition = FlowDefinition(flow_id=FLOW_ID, ts_seconds=TS_S, blocks=(bloco,), wiring={})
    task = FlowTask(definition, redis_client=redis_client)

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_EVENTS)
    await pubsub.get_message(timeout=5.0)  # confirmação de inscrição, não conta como evento

    eventos: list[EventMessage] = []
    await task.start(user="teste")
    try:
        deadline = time.monotonic() + JANELA_S
        while time.monotonic() < deadline:
            msg = await pubsub.get_message(timeout=0.1)
            if msg and msg["type"] == "message":
                evento = EventMessage.model_validate_json(msg["data"])
                if evento.payload.get("kind") == KIND_BLOCK_OVERRUN:
                    eventos.append(evento)
    finally:
        await task.stop(user="teste", reason="user")
        await pubsub.aclose()

    assert bloco.execucoes >= 1, "o bloco não chegou a varrer: o cenário não se montou"
    assert len(eventos) == 1, f"esperado exatamente 1 block_overrun, saíram {len(eventos)}"
    evento = eventos[0]
    assert evento.payload["block_id"] == "quente"
    assert evento.payload["flow_id"] == FLOW_ID
    assert evento.severity == "warning"
    assert evento.origin == f"flow:{FLOW_ID}"
    assert evento.payload["block_ms"] > evento.payload["budget_ms"]
