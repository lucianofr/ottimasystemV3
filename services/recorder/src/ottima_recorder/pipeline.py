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
from sqlalchemy import Table, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_RECORDER_BACKPRESSURE,
    EventMessage,
    FuzzyState,
    MpcState,
    OpcValue,
    publish_event,
)
from ottima_core.config import get_settings
from ottima_core.models import (
    events_table,
    fuzzy_samples_table,
    mpc_samples_table,
    samples_table,
    ssto_runs_table,
)
from ottima_core.pubsub import ChannelListener, PatternListener

logger = logging.getLogger(__name__)

VALUES_PATTERN = "opc.values.*"
MPC_STATE_PATTERN = "mpc.state.*"
FUZZY_STATE_PATTERN = "fuzzy.state.*"
FLUSH_INTERVAL_S = 1.0
# Gatilhos de ciclo: buffer com esse tanto de linhas não espera o intervalo para gravar.
SAMPLES_FLUSH_ROWS = 1000
EVENTS_FLUSH_ROWS = 1000
# Teto dos buffers (drop-oldest, spec §6.4) — papel diferente dos gatilhos acima.
SAMPLES_QUEUE_MAX = 100_000
EVENTS_QUEUE_MAX = 10_000
# Uma linha por EXECUÇÃO do SSTO (ADR-027 §11), não por variável: no pior caso (Ts_mpc de
# 0,5 s) são ~7 mil linhas por hora de banco fora do ar, então o teto de eventos serve.
SSTO_QUEUE_MAX = 10_000
# Mesma ordem de grandeza de samples: um bloco fuzzy publica um quadro por varredura.
FUZZY_QUEUE_MAX = 100_000
RETRY_INITIAL_S = 1.0
RETRY_MAX_S = 30.0
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
    """Barramento → hypertables. Único escritor de `samples`/`events`/`mpc_samples`/
    `fuzzy_samples` (spec F2 §6, F5 §2.3, ADR-030).

    Quatro assinaturas independentes (`opc.values.*`, `events`, `mpc.state.*` e
    `fuzzy.state.*`), cada uma no seu próprio `PatternListener`/`ChannelListener` do laço
    resiliente compartilhado — os quatro tipos de dado têm buffers, tetos e contadores de
    descarte próprios (spec §6.4), então nada aqui depende de ordem entre canal e padrão:
    uma conexão a menos era só economia, não contrato.
    """

    def __init__(
        self,
        redis_client: Redis,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        flush_interval_s: float = FLUSH_INTERVAL_S,
        samples_flush_rows: int = SAMPLES_FLUSH_ROWS,
        samples_queue_max: int = SAMPLES_QUEUE_MAX,
        events_queue_max: int = EVENTS_QUEUE_MAX,
        mpc_queue_max: int | None = None,
        ssto_queue_max: int = SSTO_QUEUE_MAX,
        fuzzy_queue_max: int = FUZZY_QUEUE_MAX,
    ) -> None:
        self._redis = redis_client
        self._session_factory = session_factory
        self._flush_interval_s = flush_interval_s
        self._samples_flush_rows = samples_flush_rows
        self._samples = _DropOldestBuffer(samples_queue_max)
        self._events = _DropOldestBuffer(events_queue_max)
        # Sem override explícito, o teto vem de `Settings.mpc_queue_max` (spec F5 §2.3-3).
        self._mpc = _DropOldestBuffer(
            mpc_queue_max if mpc_queue_max is not None else get_settings().mpc_queue_max
        )
        self._ssto = _DropOldestBuffer(ssto_queue_max)
        self._fuzzy = _DropOldestBuffer(fuzzy_queue_max)
        self._malformed_total = 0
        self._dropped_reported = 0
        self._flush_failures = 0
        self._db_ok = True
        self._last_flush_ts: datetime | None = None
        self._flush_now = asyncio.Event()
        self._events_listener = ChannelListener(
            redis_client, CHANNEL_EVENTS, self._on_event, name="recorder-events"
        )
        self._samples_listener = PatternListener(
            redis_client, VALUES_PATTERN, self._on_sample, name="recorder-samples"
        )
        self._mpc_listener = PatternListener(
            redis_client, MPC_STATE_PATTERN, self._on_mpc_state, name="recorder-mpc"
        )
        self._fuzzy_listener = PatternListener(
            redis_client, FUZZY_STATE_PATTERN, self._on_fuzzy_state, name="recorder-fuzzy"
        )
        self._flush_task: asyncio.Task[None] | None = None

    @property
    def buffered_samples(self) -> int:
        return len(self._samples)

    @property
    def buffered_events(self) -> int:
        return len(self._events)

    @property
    def buffered_mpc_samples(self) -> int:
        return len(self._mpc)

    @property
    def buffered_ssto_runs(self) -> int:
        return len(self._ssto)

    @property
    def buffered_fuzzy_samples(self) -> int:
        return len(self._fuzzy)

    @property
    def dropped_total(self) -> int:
        """Samples+eventos+mpc_samples+ssto_runs+fuzzy_samples descartados por overflow;
        nunca zera.
        """
        return (
            self._samples.dropped
            + self._events.dropped
            + self._mpc.dropped
            + self._ssto.dropped
            + self._fuzzy.dropped
        )

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
        """Assina os canais e sobe as tasks de leitura e de flush; retorna já. Idempotente."""
        if self._flush_task is not None:
            return
        try:
            await self._events_listener.start()
            await self._samples_listener.start()
            await self._mpc_listener.start()
            await self._fuzzy_listener.start()
        except BaseException:
            # Uma das assinaturas falhou depois de outra já ter subido: sem este desmonte
            # cruzado, a que deu certo ficaria pendurada no servidor — não há laço de fundo
            # ainda rodando para reassiná-la ou fechá-la sozinha.
            await self._events_listener.stop()
            await self._samples_listener.stop()
            await self._mpc_listener.stop()
            await self._fuzzy_listener.stop()
            raise
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        """Cancela as tasks, encerra as inscrições e faz o flush final. Idempotente.

        Nenhuma etapa pode abortar o desmonte, e nenhuma falha pode sumir: cancelamento é
        o caminho normal e não vira log de erro; qualquer outra exceção é registrada com a
        etapa que falhou e o desmonte segue.
        """
        task, self._flush_task = self._flush_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass  # cancelamento é o desmonte normal, não é falha
            except Exception:
                logger.exception("Desmonte do recorder: task de flush terminou com erro")
        await self._events_listener.stop()
        await self._samples_listener.stop()
        await self._mpc_listener.stop()
        await self._fuzzy_listener.stop()
        try:
            await self.flush()
        except Exception:
            # Banco fora do ar no shutdown: o buffer morre com o processo, mas o encerramento
            # não pode falhar por isso.
            logger.exception("Desmonte do recorder: flush final falhou; lote perdido")

    async def flush(self) -> None:
        """Um ciclo de gravação: eventos, ssto_runs, samples, mpc_samples, fuzzy_samples.

        Auditoria tem prioridade (spec §6.3) — e o registro do SSTO (ADR-027 §11) é
        auditoria, não telemetria: vai logo depois dos eventos, à frente do dado cíclico.
        Buffer vazio é no-op: nenhuma transação. As linhas só saem do buffer depois do
        commit: INSERT que falha não perde o lote.
        """
        if (
            not len(self._events)
            and not len(self._samples)
            and not len(self._mpc)
            and not len(self._ssto)
            and not len(self._fuzzy)
        ):
            return
        try:
            await self._write_buffer(events_table, self._events)
            await self._write_buffer(ssto_runs_table, self._ssto)
            await self._write_buffer(samples_table, self._samples)
            await self._write_buffer(mpc_samples_table, self._mpc)
            await self._write_buffer(fuzzy_samples_table, self._fuzzy)
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

    def ingest_mpc_state(self, channel: str, raw: str) -> None:
        """Parse e enfileira um estado MPC; payload inválido é descartado com log.

        Uma linha por `var_id` (spec F5 §2.2-1); `flow_id`/`block_id` saem do nome do canal
        (`mpc.state.<flow_id>.<block_id>`), `ts`/`vars` do payload; `sp` fica `None` quando a
        variável não publica `sp` (só CV tem — `MpcVarState.sp`).
        """
        state = self._parse(MpcState, raw)
        if state is None:
            return
        flow_id_raw, block_id = channel.removeprefix("mpc.state.").split(".", 1)
        auto = state.modes.local_remote == "remote" and state.modes.man_auto == "auto"
        self._ingest_ssto_run(int(flow_id_raw), block_id, state)
        for var_id, var in state.vars.items():
            overflow = self._mpc.append(
                {
                    "ts": state.ts,
                    "flow_id": int(flow_id_raw),
                    "block_id": block_id,
                    "var_id": var_id,
                    "v": var.v,
                    "sp": var.sp,
                    "auto": auto,
                }
            )
            if overflow:
                # Dado cíclico do MPC: fresco vale mais que velho, mesmo raciocínio de samples.
                logger.warning(
                    "Buffer de mpc_samples cheio: amostra mais antiga descartada (total %d)",
                    self._mpc.dropped,
                )

    def _ingest_ssto_run(self, flow_id: int, block_id: str, state: MpcState) -> None:
        """Enfileira o registro de auditoria do SSTO, quando o quadro traz um (ADR-027 §11).

        UMA linha por execução — granularidade diferente de `mpc_samples` (uma por
        variável). Quadro sem `ssto` (SSTO desligado, fora de AUTO) não gera linha.
        """
        run = state.ssto
        if run is None:
            return
        overflow = self._ssto.append(
            {"ts": state.ts, "flow_id": flow_id, "block_id": block_id, **run.model_dump()}
        )
        if overflow:
            # Mesma gravidade de perder evento: é registro de auditoria, não dado cíclico.
            logger.critical(
                "Buffer de ssto_runs cheio: registro mais antigo descartado (total %d)",
                self._ssto.dropped,
            )

    def ingest_fuzzy_state(self, channel: str, raw: str) -> None:
        """Parse e enfileira um estado fuzzy; payload inválido é descartado com log.

        Uma linha por entrada/saída com `v` não-nulo (RF-542: `nan`/`inf` viram `None` na
        origem e não geram linha); `var_id` é a porta (`IN1..INn`/`OUT1..OUTn`, ADR-029) —
        `flow_id`/`block_id` saem do nome do canal (`fuzzy.state.<flow_id>.<block_id>`),
        `ts` do payload.
        """
        state = self._parse(FuzzyState, raw)
        if state is None:
            return
        flow_id_raw, block_id = channel.removeprefix("fuzzy.state.").split(".", 1)
        for var in (*state.inputs, *state.outputs):
            if var.v is None:
                continue
            overflow = self._fuzzy.append(
                {
                    "ts": state.ts,
                    "flow_id": int(flow_id_raw),
                    "block_id": block_id,
                    "var_id": var.port,
                    "v": var.v,
                }
            )
            if overflow:
                # Dado cíclico do fuzzy: fresco vale mais que velho, mesmo raciocínio de samples.
                logger.warning(
                    "Buffer de fuzzy_samples cheio: amostra mais antiga descartada (total %d)",
                    self._fuzzy.dropped,
                )

    async def _on_sample(self, channel: str, raw: str) -> None:
        self.ingest_sample(raw)

    async def _on_event(self, raw: str) -> None:
        self.ingest_event(raw)

    async def _on_mpc_state(self, channel: str, raw: str) -> None:
        self.ingest_mpc_state(channel, raw)

    async def _on_fuzzy_state(self, channel: str, raw: str) -> None:
        self.ingest_fuzzy_state(channel, raw)

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
