"""Espelho em memória do último valor de cada tag (RF-401, spec F3 §2.1, §3.0).

Uma instância por processo, compartilhada por todos os FlowTasks. O `opc-worker` é o único
que fala OPC-UA (ADR-006): aqui só se consome `opc.values.*`. A leitura (`get`) é síncrona e
O(1) porque roda de dentro do laço de varredura, que não pode bloquear o event loop
(ADR-004); a escrita vem da task de fundo que consome o pubsub.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from ottima_core.bus import OpcValue

logger = logging.getLogger(__name__)

VALUES_PATTERN = "opc.values.*"
"""Um só assinante para todas as conexões: o padrão cobre `opc.values.<conn_id>` inteiro."""

RESUBSCRIBE_RETRY_S = 1.0
"""Freio entre reassinaturas: queda do Redis não pode virar rajada de PSUBSCRIBE."""

SUBSCRIBE_TIMEOUT_S = 5.0
"""Teto do PSUBSCRIBE: o Redis é local ao stack, não confirmar em 5 s é falha real."""


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
    """Espelho do barramento: `psubscribe opc.values.*` → último valor por `tag_id`."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client
        self._values: dict[int, TagValue] = {}
        self._pubsub: PubSub | None = None
        self._task: asyncio.Task[None] | None = None

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
        if self._task is not None and not self._task.done():
            return
        self._pubsub = await self._subscribe()
        self._task = asyncio.create_task(self._read_loop(), name="flow-runtime-snapshot")

    async def stop(self) -> None:
        """Cancela a task e encerra a inscrição. Idempotente e nunca levanta: é desmonte."""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self._close_pubsub()

    async def _read_loop(self) -> None:
        """Laço do padrão; reassina depois de qualquer queda do Redis.

        O que foi publicado durante a queda se perde: o espelho guarda o último valor, e o
        próximo ciclo do `opc-worker` o repõe.
        """
        while True:
            try:
                if self._pubsub is None:
                    self._pubsub = await self._subscribe()
                async for message in self._pubsub.listen():
                    self._ingest(message)
                logger.warning(
                    "Escuta de %s terminou sem erro; reassinando em %.1fs",
                    VALUES_PATTERN,
                    RESUBSCRIBE_RETRY_S,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Assinante de %s caiu; reassinando em %.1fs",
                    VALUES_PATTERN,
                    RESUBSCRIBE_RETRY_S,
                    exc_info=True,
                )
            await self._close_pubsub()
            await asyncio.sleep(RESUBSCRIBE_RETRY_S)

    def _ingest(self, message: Mapping[str, Any]) -> None:
        """Grava o último valor da tag; payload ruim é descartado e o laço segue."""
        if message["type"] != "pmessage":
            return
        raw = message["data"]
        try:
            value = OpcValue.model_validate_json(raw)
        except ValidationError:
            logger.warning("Payload inválido descartado pelo espelho de valores: %.200s", raw)
            return
        self._values[value.tag_id] = TagValue(value=value.value, quality=value.quality, ts=value.ts)

    async def _subscribe(self) -> PubSub:
        pubsub = self._redis.pubsub()
        try:
            await pubsub.psubscribe(VALUES_PATTERN)
            await self._await_confirmation(pubsub)
        except BaseException:
            # Falhou antes de virar `self._pubsub`, onde nem `stop()` o alcançaria: sem este
            # fechamento, cada start() que falha vaza conexão e inscrição no servidor.
            await _close(pubsub)
            raise
        return pubsub

    async def _close_pubsub(self) -> None:
        pubsub, self._pubsub = self._pubsub, None
        if pubsub is not None:
            await _close(pubsub)

    async def _await_confirmation(self, pubsub: PubSub) -> None:
        """Só volta com o PSUBSCRIBE confirmado: a publicação seguinte não se perde.

        O padrão já entrega dado enquanto a inscrição é confirmada; essa janela vai para o
        espelho como qualquer outra mensagem, em vez de virar valor perdido no start.
        """
        async with asyncio.timeout(SUBSCRIBE_TIMEOUT_S):
            while True:
                message = await pubsub.get_message(timeout=SUBSCRIBE_TIMEOUT_S)
                if message is None:
                    continue
                if message["type"] == "psubscribe":
                    return
                self._ingest(message)


async def _close(pubsub: PubSub) -> None:
    """Fecha o assinante sem nunca levantar: é caminho de desmonte."""
    try:
        await pubsub.aclose()  # aclose desfaz a inscrição e devolve a conexão
    except Exception:
        logger.warning("Falha ao fechar o assinante de %s", VALUES_PATTERN, exc_info=True)
