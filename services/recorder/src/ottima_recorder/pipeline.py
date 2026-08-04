"""Pipeline do recorder: barramento → hypertables (RF-801, ADR-003, spec F2 §6.1–6.6).

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

from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_RECORDER_BACKPRESSURE,
    EventMessage,
    OpcValue,
    publish_event,
)
from ottima_core.models import events_table, samples_table

logger = logging.getLogger(__name__)

VALUES_PATTERN = "opc.values.*"
FLUSH_INTERVAL_S = 1.0
SUBSCRIBE_TIMEOUT_S = 5.0
# Gatilhos de ciclo: buffer com esse tanto de linhas não espera o intervalo para gravar.
SAMPLES_FLUSH_ROWS = 1000
EVENTS_FLUSH_ROWS = 1000
# Teto dos buffers (drop-oldest, spec §6.4) — papel diferente dos gatilhos acima.
SAMPLES_QUEUE_MAX = 100_000
EVENTS_QUEUE_MAX = 10_000
RETRY_INITIAL_S = 1.0
RETRY_MAX_S = 30.0
READ_RETRY_S = 1.0
MAX_BIND_PARAMS = 32_000  # asyncpg aceita no máximo 32767 parâmetros por statement


class _DropOldestBuffer:
    """Buffer com teto: cheio, o mais antigo sai e o descarte é contado (spec §6.4)."""

    def __init__(self, maxlen: int) -> None:
        self._rows: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self.dropped = 0

    def __len__(self) -> int:
        return len(self._rows)

    def append(self, row: dict[str, Any]) -> bool:
        """Enfileira a linha; devolve `True` quando isso expulsou a mais antiga."""
        overflow = len(self._rows) == self._rows.maxlen
        self._rows.append(row)
        if overflow:
            self.dropped += 1
        return overflow

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def drop_written(self, count: int) -> None:
        """Descarta as `count` linhas mais antigas — as que o INSERT já confirmou."""
        for _ in range(min(count, len(self._rows))):
            self._rows.popleft()


class RecorderPipeline:
    """Barramento → hypertables. Único escritor de `samples`/`events` (spec F2 §6)."""

    def __init__(
        self,
        redis_client: Redis,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        flush_interval_s: float = FLUSH_INTERVAL_S,
        samples_flush_rows: int = SAMPLES_FLUSH_ROWS,
        samples_queue_max: int = SAMPLES_QUEUE_MAX,
        events_queue_max: int = EVENTS_QUEUE_MAX,
    ) -> None:
        self._redis = redis_client
        self._session_factory = session_factory
        self._flush_interval_s = flush_interval_s
        self._samples_flush_rows = samples_flush_rows
        self._samples = _DropOldestBuffer(samples_queue_max)
        self._events = _DropOldestBuffer(events_queue_max)
        self._malformed_total = 0
        self._dropped_reported = 0
        self._flush_failures = 0
        self._db_ok = True
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
    def dropped_total(self) -> int:
        """Samples + eventos descartados por overflow desde o início; nunca zera."""
        return self._samples.dropped + self._events.dropped

    @property
    def malformed_total(self) -> int:
        """Payloads que não parsearam: lixo no canal, não pressão — contador separado."""
        return self._malformed_total

    @property
    def db_ok(self) -> bool:
        """Último flush gravou? Começa `True`: sem falha observada, sem degradação."""
        return self._db_ok

    @property
    def last_flush_ts(self) -> datetime | None:
        """Instante do último flush que gravou linhas (flush vazio não conta)."""
        return self._last_flush_ts

    async def start(self) -> None:
        """Assina os canais e sobe as tasks de leitura e de flush; retorna já."""
        if self._read_task is not None:
            return
        self._pubsub = await self._subscribe()
        self._read_task = asyncio.create_task(self._read_loop())
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        """Cancela as tasks, encerra as inscrições e faz o flush final. Idempotente.

        Nenhuma etapa pode abortar o desmonte, e nenhuma falha pode sumir: cancelamento é
        o caminho normal e não vira log de erro; qualquer outra exceção é registrada com a
        etapa que falhou e o desmonte segue.
        """
        stages = (("task de leitura", self._read_task), ("task de flush", self._flush_task))
        for stage, task in stages:
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass  # cancelamento é o desmonte normal, não é falha
            except Exception:
                logger.exception("Desmonte do recorder: %s terminou com erro", stage)
        self._read_task = None
        self._flush_task = None
        await self._close_pubsub()
        try:
            await self.flush()
        except Exception:
            # Banco fora do ar no shutdown: o buffer morre com o processo, mas o encerramento
            # não pode falhar por isso.
            logger.exception("Desmonte do recorder: flush final falhou; lote perdido")

    async def flush(self) -> None:
        """Um ciclo de gravação: eventos primeiro, samples depois.

        Auditoria tem prioridade (spec §6.3). Buffer vazio é no-op: nenhuma transação.
        As linhas só saem do buffer depois do commit: INSERT que falha não perde o lote.
        """
        if not len(self._events) and not len(self._samples):
            return
        try:
            await self._write_buffer(events_table, self._events)
            await self._write_buffer(samples_table, self._samples)
        except Exception:
            self._db_ok = False
            self._flush_failures += 1
            raise
        self._db_ok = True
        self._flush_failures = 0
        self._last_flush_ts = datetime.now(UTC)
        await self._emit_backpressure()

    def ingest_sample(self, raw: str) -> None:
        """Parse e enfileira uma amostra; payload inválido é descartado com log."""
        value = self._parse(OpcValue, raw)
        if value is None:
            return
        overflow = self._samples.append(
            {
                "ts": value.ts,
                "tag_id": value.tag_id,
                "value": value.value,
                "quality": value.quality,
            }
        )
        if overflow:
            # Dado cíclico: fresco vale mais que velho. Bloquear o produtor estouraria o
            # buffer de saída do Redis e derrubaria a subscription (spec §6.4).
            logger.warning(
                "Buffer de samples cheio: amostra mais antiga descartada (total %d)",
                self._samples.dropped,
            )
        if len(self._samples) >= self._samples_flush_rows:
            self._flush_now.set()

    def ingest_event(self, raw: str) -> None:
        """Parse e enfileira um evento; payload inválido é descartado com log."""
        event = self._parse(EventMessage, raw)
        if event is None:
            return
        overflow = self._events.append(
            {
                "ts": event.ts,
                "severity": event.severity,
                "origin": event.origin,
                "message": event.message,
                "payload": event.payload,
            }
        )
        if overflow:
            # Perder auditoria é patológico: o banco está fora há muito tempo (spec §6.4).
            logger.critical(
                "Buffer de eventos cheio: evento mais antigo descartado (total %d)",
                self._events.dropped,
            )
        # Buffer de auditoria cheio também força o ciclo, sem esperar o intervalo.
        if len(self._events) >= EVENTS_FLUSH_ROWS:
            self._flush_now.set()

    def _dispatch(self, message: dict[str, Any]) -> None:
        """O tipo decide o buffer: `pmessage` vem do padrão, `message` do canal `events`.

        Compartilhado com `_await_confirmations`: os dois caminhos de leitura não podem
        divergir sobre o que é dado e o que é confirmação de inscrição.
        """
        if message["type"] == "pmessage":
            self.ingest_sample(message["data"])
        elif message["type"] == "message":
            self.ingest_event(message["data"])

    async def _read_loop(self) -> None:
        """Uma task para as duas inscrições: o tipo da mensagem decide o buffer.

        Redis fora do ar: loga, reassina e segue. O que foi publicado durante a queda se
        perde — perda aceita para dado cíclico (RNF-05).
        """
        while True:
            try:
                if self._pubsub is None:
                    self._pubsub = await self._subscribe()
                async for message in self._pubsub.listen():
                    self._dispatch(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Leitura do barramento falhou; reassinando", exc_info=True)
            await self._close_pubsub()
            await asyncio.sleep(READ_RETRY_S)

    async def _flush_loop(self) -> None:
        """Flush a cada `flush_interval_s`, quando um buffer enche ou no backoff do retry."""
        while True:
            if self._flush_failures:
                # Em retry o gatilho de buffer cheio não vale: martelaria o banco fora do ar.
                await asyncio.sleep(self._retry_delay())
            else:
                with suppress(TimeoutError):
                    async with asyncio.timeout(self._flush_interval_s):
                        await self._flush_now.wait()
                self._flush_now.clear()
            try:
                await self.flush()
            except Exception:
                logger.exception("Falha ao gravar lote; lote mantido no buffer para novo retry")

    def _retry_delay(self) -> float:
        """Backoff 1→30 s, sem jitter: consumidor único, sem tempestade de retry a evitar."""
        return min(RETRY_MAX_S, RETRY_INITIAL_S * 2 ** (self._flush_failures - 1))

    async def _emit_backpressure(self) -> None:
        """Um aviso por recuperação: emitir durante a queda só encheria o outro buffer."""
        delta = self.dropped_total - self._dropped_reported
        if delta <= 0:
            return
        self._dropped_reported = self.dropped_total
        await publish_event(
            self._redis,
            severity="warning",
            origin="recorder",
            message=f"Recorder descartou {delta} mensagens por backpressure",
            kind=KIND_RECORDER_BACKPRESSURE,
            payload={"dropped_total": self.dropped_total, "dropped_since_last": delta},
        )

    async def _write_buffer(self, table: Table, buffer: _DropOldestBuffer) -> None:
        """Grava o conteúdo atual do buffer e só então o remove de lá."""
        rows = buffer.snapshot()
        if not rows:
            return
        dropped_before = buffer.dropped
        await self._write(table, rows)
        # O que o overflow expulsou durante o INSERT já saiu: descontar evita comer linha nova.
        buffer.drop_written(len(rows) - (buffer.dropped - dropped_before))

    async def _write(self, table: Table, rows: list[dict[str, Any]]) -> None:
        """INSERT multi-linha, fatiado no teto de binds do asyncpg; nunca um INSERT por linha."""
        chunk = max(1, MAX_BIND_PARAMS // len(table.columns))
        async with self._session_factory() as session:
            for start in range(0, len(rows), chunk):
                await session.execute(insert(table).values(rows[start : start + chunk]))
            await session.commit()

    def _parse[T: BaseModel](self, model: type[T], raw: str) -> T | None:
        try:
            return model.model_validate_json(raw)
        except ValidationError:
            self._malformed_total += 1
            logger.warning("Payload inválido descartado pelo recorder: %.200s", raw)
            return None

    async def _subscribe(self) -> PubSub:
        pubsub = self._redis.pubsub()
        try:
            await pubsub.psubscribe(VALUES_PATTERN)
            await pubsub.subscribe(CHANNEL_EVENTS)
            await self._await_confirmations(pubsub)
        except BaseException:
            # Falhou antes de virar `self._pubsub`, onde nem `stop()` o alcançaria: sem este
            # fechamento, cada start() que falha vaza conexão e inscrição no servidor.
            # Entregar ao fechamento padrão reaproveita o log de etapa e zera `_pubsub`.
            self._pubsub = pubsub
            await self._close_pubsub()
            raise
        return pubsub

    async def _close_pubsub(self) -> None:
        if self._pubsub is None:
            return
        try:
            await self._pubsub.aclose()  # aclose desfaz as inscrições e devolve a conexão
        except Exception:
            logger.exception("Desmonte do recorder: fechamento do pubsub falhou")
        finally:
            self._pubsub = None

    async def _await_confirmations(self, pubsub: PubSub) -> None:
        """Só volta com as duas inscrições confirmadas: publicação seguinte não se perde.

        O padrão já entrega dado enquanto o `subscribe` é confirmado; essa janela vai para os
        buffers como qualquer outra mensagem, em vez de virar amostra perdida no start.
        """
        pending = {"psubscribe", "subscribe"}
        async with asyncio.timeout(SUBSCRIBE_TIMEOUT_S):
            while pending:
                message = await pubsub.get_message(timeout=SUBSCRIBE_TIMEOUT_S)
                if message is None:
                    continue
                pending.discard(message["type"])
                self._dispatch(message)
