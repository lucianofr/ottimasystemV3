"""Pipeline do recorder: barramento → hypertables (RF-801, ADR-003, spec F2 §6.1–6.3).

Dumb pipe: o que chega no barramento é gravado verbatim. Não interpreta `kind`, não filtra
severidade e não valida `tag_id` contra `tags` (amostra órfã grava — spec F1 §3.4-2).
"""

import asyncio
import logging
from collections import deque
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from sqlalchemy import Table, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import CHANNEL_EVENTS, EventMessage, OpcValue
from ottima_core.models import events_table, samples_table

logger = logging.getLogger(__name__)

VALUES_PATTERN = "opc.values.*"
FLUSH_INTERVAL_S = 1.0
SAMPLES_FLUSH_ROWS = 1000
EVENTS_FLUSH_ROWS = 1000
SUBSCRIBE_TIMEOUT_S = 5.0


class RecorderPipeline:
    """Barramento → hypertables. Único escritor de `samples`/`events` (spec F2 §6)."""

    def __init__(
        self,
        redis_client: Redis,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        flush_interval_s: float = FLUSH_INTERVAL_S,
        samples_flush_rows: int = SAMPLES_FLUSH_ROWS,
    ) -> None:
        self._redis = redis_client
        self._session_factory = session_factory
        self._flush_interval_s = flush_interval_s
        self._samples_flush_rows = samples_flush_rows
        self._samples: deque[dict[str, Any]] = deque()
        self._events: deque[dict[str, Any]] = deque()
        self._malformed_total = 0
        self._last_flush_ts: datetime | None = None
        self._flush_now = asyncio.Event()
        self._pubsub: PubSub | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None

    @property
    def buffered_samples(self) -> int:
        return len(self._samples)

    @property
    def buffered_events(self) -> int:
        return len(self._events)

    @property
    def last_flush_ts(self) -> datetime | None:
        """Instante do último flush que gravou linhas (flush vazio não conta)."""
        return self._last_flush_ts

    async def start(self) -> None:
        """Assina os canais e sobe as tasks de leitura e de flush; retorna já."""
        if self._read_task is not None:
            return
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(VALUES_PATTERN)
        await pubsub.subscribe(CHANNEL_EVENTS)
        await self._await_confirmations(pubsub)
        self._pubsub = pubsub
        self._read_task = asyncio.create_task(self._read_loop())
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        """Cancela as tasks, encerra as inscrições e faz o flush final. Idempotente."""
        for task in (self._read_task, self._flush_task):
            if task is None:
                continue
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._read_task = None
        self._flush_task = None
        if self._pubsub is not None:
            await self._pubsub.aclose()  # aclose desfaz as inscrições e devolve a conexão
            self._pubsub = None
        await self.flush()

    async def flush(self) -> None:
        """Um ciclo de gravação: eventos primeiro, samples depois.

        Auditoria tem prioridade (spec §6.3). Buffer vazio é no-op: nenhuma transação.
        """
        events = _drain(self._events)
        samples = _drain(self._samples)
        if not events and not samples:
            return
        if events:
            await self._write(events_table, events)
        if samples:
            await self._write(samples_table, samples)
        self._last_flush_ts = datetime.now(UTC)

    def ingest_sample(self, raw: str) -> None:
        """Parse e enfileira uma amostra; payload inválido é descartado com log."""
        value = self._parse(OpcValue, raw)
        if value is None:
            return
        self._samples.append(
            {
                "ts": value.ts,
                "tag_id": value.tag_id,
                "value": value.value,
                "quality": value.quality,
            }
        )
        if len(self._samples) >= self._samples_flush_rows:
            self._flush_now.set()

    def ingest_event(self, raw: str) -> None:
        """Parse e enfileira um evento; payload inválido é descartado com log."""
        event = self._parse(EventMessage, raw)
        if event is None:
            return
        self._events.append(
            {
                "ts": event.ts,
                "severity": event.severity,
                "origin": event.origin,
                "message": event.message,
                "payload": event.payload,
            }
        )
        # Buffer de auditoria cheio também força o ciclo, sem esperar o intervalo.
        if len(self._events) >= EVENTS_FLUSH_ROWS:
            self._flush_now.set()

    async def _read_loop(self) -> None:
        """Uma task para as duas inscrições: o tipo da mensagem decide o buffer."""
        assert self._pubsub is not None
        async for message in self._pubsub.listen():
            if message["type"] == "pmessage":
                self.ingest_sample(message["data"])
            elif message["type"] == "message":
                self.ingest_event(message["data"])

    async def _flush_loop(self) -> None:
        """Flush a cada `flush_interval_s` ou quando um buffer sinaliza que encheu."""
        while True:
            with suppress(TimeoutError):
                async with asyncio.timeout(self._flush_interval_s):
                    await self._flush_now.wait()
            self._flush_now.clear()
            try:
                await self.flush()
            except Exception:
                # Retry/backpressure é da tarefa 3.2; aqui basta não derrubar o loop (ADR-004).
                logger.exception("Falha ao gravar lote no banco; lote descartado")

    async def _write(self, table: Table, rows: list[dict[str, Any]]) -> None:
        """Um único INSERT multi-linha por tabela; nunca um INSERT por linha."""
        async with self._session_factory() as session:
            await session.execute(insert(table).values(rows))
            await session.commit()

    def _parse[T: BaseModel](self, model: type[T], raw: str) -> T | None:
        try:
            return model.model_validate_json(raw)
        except ValidationError:
            self._malformed_total += 1
            logger.warning("Payload inválido descartado pelo recorder: %.200s", raw)
            return None

    @staticmethod
    async def _await_confirmations(pubsub: PubSub) -> None:
        """Só volta com as duas inscrições confirmadas: publicação seguinte não se perde."""
        pending = {"psubscribe", "subscribe"}
        async with asyncio.timeout(SUBSCRIBE_TIMEOUT_S):
            while pending:
                message = await pubsub.get_message(timeout=SUBSCRIBE_TIMEOUT_S)
                if message is not None:
                    pending.discard(message["type"])


def _drain(buffer: deque[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(buffer)
    buffer.clear()
    return rows
