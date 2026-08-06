"""Espelho em memória do último valor de cada tag (RF-401, spec F3 §2.1, §3.0).

Uma instância por processo, compartilhada por todos os FlowTasks. O `opc-worker` é o único
que fala OPC-UA (ADR-006): aqui só se consome `opc.values.*`. A leitura (`get`) é síncrona e
O(1) porque roda de dentro do laço de varredura, que não pode bloquear o event loop
(ADR-004); a escrita vem da task de fundo que consome o pubsub.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError
from redis.asyncio import Redis

from ottima_core.bus import OpcValue
from ottima_core.pubsub import PatternListener

logger = logging.getLogger(__name__)

VALUES_PATTERN = "opc.values.*"
"""Um só assinante para todas as conexões: o padrão cobre `opc.values.<conn_id>` inteiro."""


@dataclass(frozen=True, slots=True)
class TagValue:
    """Último valor conhecido de uma tag, como veio do barramento.

    `value` continua `float` mesmo para tag booleana: a conversão pertence ao bloco OPC-Read,
    que conhece o `data_type` da tag.
    """

    value: float
    quality: int  # 0=good, 1=uncertain, 2=bad (spec F1 §3.2)
    ts: datetime


class ValueSnapshot:
    """Espelho do barramento: padrão `opc.values.*` → último valor por `tag_id`."""

    def __init__(self, redis_client: Redis) -> None:
        self._values: dict[int, TagValue] = {}
        self._listener = PatternListener(
            redis_client, VALUES_PATTERN, self._ingest, name="flow-runtime-snapshot"
        )

    def get(self, tag_id: int) -> TagValue | None:
        """Último valor da tag, ou `None` se ela nunca publicou.

        `None` é o cold start da spec §3.0 e a invalidez do §3.1 — nunca um `0.0` nem um
        `TagValue` sintético: só o bloco OPC-Read decide o que fazer com a ausência.
        """
        return self._values.get(tag_id)

    async def start(self) -> None:
        """Assina o padrão e sobe a task de leitura; retorna já. Idempotente.

        O PSUBSCRIBE acontece aqui, e não dentro da task: quem chamou `start()` precisa poder
        publicar em seguida sem perder a mensagem.
        """
        await self._listener.start()

    async def stop(self) -> None:
        """Cancela a task e encerra a inscrição. Idempotente e nunca levanta: é desmonte."""
        await self._listener.stop()

    async def _ingest(self, channel: str, raw: str) -> None:
        """Grava o último valor da tag; payload ruim é descartado e o laço segue."""
        try:
            value = OpcValue.model_validate_json(raw)
        except ValidationError:
            logger.warning("Payload inválido descartado pelo espelho de valores: %.200s", raw)
            return
        self._values[value.tag_id] = TagValue(value=value.value, quality=value.quality, ts=value.ts)
