"""Consumidor do canal `opc.writes`: pipeline, gate de escrita e auditoria (spec F2 §4).

O consumidor recebe o *mapping vivo* de runtimes do supervisor (tarefa 1.4) e resolve
`conn_id` a cada mensagem: conexão criada depois da subida do worker já é atendida sem
reinscrição no canal.

Nenhum caminho do pipeline levanta exceção para o laço — escrita reprovada é descarte com
evento, e payload malformado é descarte com log. Um consumidor que morre calado deixaria
o sistema aceitando comandos que nunca chegam ao PLC.

As escritas do próprio watchdog (`watchdog.py`) vão direto ao node pelo client e não
passam por aqui: o bypass do gate exigido pela spec §3.4 é garantido por construção, não
por uma exceção codificada neste módulo.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Literal

from asyncua import ua
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from ottima_core.bus import (
    CHANNEL_OPC_WRITES,
    KIND_OPC_WRITE,
    KIND_WRITE_BLOCKED,
    KIND_WRITE_REJECTED,
    OpcWrite,
    publish_event,
)

from .connection import ConnectionRuntime
from .security import describe_exception
from .state import ConnectionState, TagConfig

logger = logging.getLogger(__name__)

RESUBSCRIBE_RETRY_S = 1.0
"""Freio entre reassinaturas do canal: queda do Redis não pode virar rajada de SUBSCRIBE."""

BLOCKED_WINDOW_S = 0.5
"""Janela de acumulação do `write_blocked` de um período de falha (spec §4.2-c).

O bloqueio em si é imediato; o que espera é só o evento. Sem a janela, o `suppressed`
do payload nasceria sempre zero e o operador não teria a ordem de grandeza dos descartes
— um MPC bloqueado descarta na sua cadência, não uma vez.
"""

RejectReason = Literal["unknown_connection", "unknown_tag", "tag_not_writable", "no_watchdog"]
BlockReason = Literal["session_down", "watchdog_dead"]

# Texto pt-BR para humanos; consumidores fazem match por `kind`/`reason` (spec §7.3).
_REJECT_TEXT: dict[str, str] = {
    "unknown_connection": "conexão fora do projeto ativo ou sem runtime",
    "unknown_tag": "tag não pertence à conexão",
    "tag_not_writable": "tag é de leitura (direction='r')",
    "no_watchdog": "conexão sem watchdog configurado é read-only de fato",
}
_BLOCK_TEXT: dict[str, str] = {
    "session_down": "sessão OPC-UA fora do ar",
    "watchdog_dead": "watchdog sem alternância",
}

# Todo VariantType inteiro do OPC-UA: o payload traz float e o node pode ser qualquer um
# deles (escrever Int64 num node Int32 dá BadTypeMismatch, spec §4.3).
_INTEGER_VARIANTS = frozenset(
    {
        ua.VariantType.SByte,
        ua.VariantType.Byte,
        ua.VariantType.Int16,
        ua.VariantType.UInt16,
        ua.VariantType.Int32,
        ua.VariantType.UInt32,
        ua.VariantType.Int64,
        ua.VariantType.UInt64,
    }
)


def coerce_value(value: float, variant_type: ua.VariantType) -> bool | int | float:
    """Converte o `value` float do payload para o VariantType real do node (spec §4.3)."""
    if variant_type is ua.VariantType.Boolean:
        return value != 0.0
    if variant_type in _INTEGER_VARIANTS:
        return int(round(value))
    return float(value)


@dataclass(slots=True)
class _BlockedPeriod:
    """Descartes de uma conexão dentro de um mesmo período de gate fechado."""

    first: OpcWrite
    reason: BlockReason
    conn_name: str
    # `gate_generation` do runtime quando o período abriu: o gate reabrir e fechar de novo
    # avança o contador e prova que o período seguinte é OUTRO, mesmo que nenhuma escrita
    # tenha chegado na janela aberta (spec §4.2-c).
    generation: int
    dropped: int = 0
    emitted: bool = False
    task: asyncio.Task[None] | None = None


@dataclass(slots=True)
class _RejectMemory:
    """Recusas já avisadas de uma conexão, válidas enquanto a configuração dela não muda."""

    # `id()` do runtime + conjunto de tags: runtime novo ou `apply_tags` mudam a impressão
    # digital e rearmam o aviso. Guardar o `id()` (e não o objeto) evita segurar um runtime
    # morto vivo; no pior caso de endereço reciclado com as mesmas tags, um aviso duplicado
    # deixa de ser emitido — inofensivo.
    fingerprint: tuple[int, tuple] | None
    seen: set[tuple[int, str]] = field(default_factory=set)


class WriteConsumer:
    """Consome o canal fixo `opc.writes` e roteia para os runtimes (spec §4)."""

    def __init__(
        self,
        redis_client: Redis,
        runtimes: Mapping[int, ConnectionRuntime],
        *,
        blocked_window_s: float = BLOCKED_WINDOW_S,
    ) -> None:
        self._redis = redis_client
        self._runtimes = runtimes
        self._blocked_window_s = blocked_window_s
        self._task: asyncio.Task[None] | None = None
        self._pubsub: PubSub | None = None
        self._blocked: dict[int, _BlockedPeriod] = {}
        self._rejected: dict[int, _RejectMemory] = {}

    async def start(self) -> None:
        """Assina o canal e cria a task de consumo; retorna já. Idempotente.

        O SUBSCRIBE acontece aqui, e não dentro da task: quem chamou `start()` precisa
        poder publicar em seguida sem perder a mensagem. Redis fora do ar na subida não
        pode impedir o worker de subir (o `/health` degradado é contrato do RNF-07): a
        inscrição fica a cargo do laço, que já reassina.
        """
        if self._task is not None and not self._task.done():
            return
        if self._pubsub is None:
            try:
                await self._subscribe()
            except Exception:
                logger.warning(
                    "Não foi possível assinar %s na subida; a task reassina",
                    CHANNEL_OPC_WRITES,
                    exc_info=True,
                )
        self._task = asyncio.create_task(self._consume(), name="opc-writes")

    async def stop(self) -> None:
        """Cancela a task, a inscrição e os avisos pendentes. Idempotente."""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        for period in self._blocked.values():
            await _cancel(period.task)
        self._blocked.clear()
        await self._drop_pubsub()

    async def handle(self, write: OpcWrite) -> None:
        """Pipeline §4.2 completo para uma escrita. Público para teste direto.

        A ordem das checagens é normativa (spec §4.2) e não pode ser reordenada: recusa de
        configuração vem antes de bloqueio de segurança, porque só a primeira é culpa de
        quem configurou.
        """
        runtime = self._runtimes.get(write.conn_id)
        if runtime is None:
            await self._reject(write, None, "unknown_connection")
            return

        tag = next((t for t in runtime.config.tags if t.id == write.tag_id), None)
        if tag is None:
            await self._reject(write, runtime, "unknown_tag")
            return
        if tag.direction != "w":
            await self._reject(write, runtime, "tag_not_writable")
            return

        # Conexão sem o par de node_ids do watchdog é read-only por configuração (§3.5):
        # o gate nunca abriria, então recusar é mais honesto do que bloquear para sempre.
        if not runtime.config.has_watchdog:
            await self._reject(write, runtime, "no_watchdog")
            return

        blocked = self._gate_reason(runtime)
        if blocked is not None:
            await self._block(write, runtime, blocked)
            return

        # O rearme do dedupe NÃO acontece aqui: ele é dirigido por `runtime.gate_generation`,
        # que avança na aresta real de recuperação. Rearmar na chegada de uma escrita
        # silenciaria o alarme quando a conexão falhasse de novo sem que nenhuma escrita
        # tivesse passado pela janela aberta.
        await self._execute(write, runtime, tag)

    @staticmethod
    def _gate_reason(runtime: ConnectionRuntime) -> BlockReason | None:
        """Gate §3.4: sessão `up` ∧ `watchdog_alive`; devolve o motivo quando fechado."""
        if runtime.state is not ConnectionState.UP or runtime.client is None:
            return "session_down"
        if not runtime.snapshot.watchdog_alive:
            return "watchdog_dead"
        return None

    async def _execute(self, write: OpcWrite, runtime: ConnectionRuntime, tag: TagConfig) -> None:
        """Escreve no node e audita o resultado (RF-205: toda escrita gera evento)."""
        # Reconferência COMPLETA do gate, não só da sessão: `watchdog_alive` e `state` são
        # zerados juntos por `fail()` hoje, mas depender disso seria invariante implícita
        # entre dois módulos. Aqui é o último ponto antes de o valor chegar ao PLC.
        blocked = self._gate_reason(runtime)
        if blocked is not None:
            await self._block(write, runtime, blocked)
            return
        client = runtime.client
        if client is None:  # estreitado por `_gate_reason`; o type checker não sabe disso
            await self._block(write, runtime, "session_down")
            return
        variant_type = runtime.variant_type_for(tag.id)
        valor = coerce_value(write.value, variant_type)
        try:
            node = client.get_node(tag.node_id)
            await node.write_value(ua.DataValue(ua.Variant(valor, variant_type)))
        except Exception as exc:
            detail = describe_exception(exc)
            runtime.snapshot.write_errors += 1
            logger.warning(
                "Falha ao escrever na tag %s da conexão %s: %s", tag.id, write.conn_id, detail
            )
            await publish_event(
                self._redis,
                severity="warning",
                origin=write.source,
                message=(
                    f"Falha ao escrever na tag '{tag.name}' da conexão "
                    f"'{runtime.config.name}': {detail}"
                ),
                kind=KIND_OPC_WRITE,
                payload={
                    "conn_id": write.conn_id,
                    "tag_id": write.tag_id,
                    "value": write.value,
                    "status": "error",
                    "detail": detail,
                },
            )
            return
        await publish_event(
            self._redis,
            severity="info",
            origin=write.source,
            message=(
                f"Escrita na tag '{tag.name}' da conexão '{runtime.config.name}': {write.value}"
            ),
            kind=KIND_OPC_WRITE,
            payload={
                "conn_id": write.conn_id,
                "tag_id": write.tag_id,
                "value": write.value,
                "status": "ok",
            },
        )

    async def _reject(
        self, write: OpcWrite, runtime: ConnectionRuntime | None, reason: RejectReason
    ) -> None:
        """Descarta com aviso deduplicado por `(conn_id, tag_id, reason)` (spec §4.2)."""
        fingerprint = None if runtime is None else (id(runtime), runtime.config.tags_key)
        memory = self._rejected.get(write.conn_id)
        if memory is None or memory.fingerprint != fingerprint:
            memory = _RejectMemory(fingerprint)
            self._rejected[write.conn_id] = memory
        key = (write.tag_id, reason)
        if key in memory.seen:
            return
        memory.seen.add(key)
        detail = _REJECT_TEXT[reason]
        logger.warning(
            "Escrita recusada na conexão %s, tag %s: %s", write.conn_id, write.tag_id, detail
        )
        await publish_event(
            self._redis,
            severity="warning",
            origin=f"conn:{write.conn_id}",
            message=f"Escrita recusada na conexão {write.conn_id}: {detail}",
            kind=KIND_WRITE_REJECTED,
            payload={
                "conn_id": write.conn_id,
                "tag_id": write.tag_id,
                "reason": reason,
                "detail": detail,
            },
        )

    async def _block(
        self, write: OpcWrite, runtime: ConnectionRuntime, reason: BlockReason
    ) -> None:
        """Descarta pelo gate; um evento por conexão por período de falha (spec §4.2-c).

        O período é identificado pela `gate_generation` do runtime, que avança na aresta
        real de recuperação. Assim, dois episódios de falha separados por uma janela de
        gate aberto rendem dois eventos mesmo que nenhuma escrita tenha chegado no meio —
        senão o alarme ficaria silenciado indefinidamente, refém do acaso de uma escrita
        cair na janela certa.
        """
        generation = runtime.gate_generation
        period = self._blocked.get(write.conn_id)
        if period is not None and period.generation != generation:
            await self._close_period(write.conn_id)
            period = None
        if period is None:
            period = _BlockedPeriod(
                first=write,
                reason=reason,
                conn_name=runtime.config.name,
                generation=generation,
            )
            self._blocked[write.conn_id] = period
            period.task = asyncio.create_task(
                self._emit_blocked_later(write.conn_id), name=f"opc-write-blocked-{write.conn_id}"
            )
        period.dropped += 1
        logger.warning(
            "Escrita bloqueada na conexão %s, tag %s: %s",
            write.conn_id,
            write.tag_id,
            _BLOCK_TEXT[reason],
        )

    async def _emit_blocked_later(self, conn_id: int) -> None:
        await asyncio.sleep(self._blocked_window_s)
        period = self._blocked.get(conn_id)
        if period is not None:
            await self._emit_blocked(period)

    async def _close_period(self, conn_id: int) -> None:
        """Encerra o período: publica o que ainda não foi avisado e esquece a conexão."""
        period = self._blocked.pop(conn_id, None)
        if period is None:
            return
        await _cancel(period.task)
        await self._emit_blocked(period)

    async def _emit_blocked(self, period: _BlockedPeriod) -> None:
        if period.emitted:
            return
        period.emitted = True
        write = period.first
        await publish_event(
            self._redis,
            severity="warning",
            origin=f"conn:{write.conn_id}",
            message=(
                f"Escrita bloqueada na conexão '{period.conn_name}': {_BLOCK_TEXT[period.reason]}"
            ),
            kind=KIND_WRITE_BLOCKED,
            payload={
                "conn_id": write.conn_id,
                "tag_id": write.tag_id,
                "value": write.value,
                "reason": period.reason,
                # Descartes além do que abriu o período: preserva a ordem de grandeza sem
                # inundar o canal na cadência do MPC.
                "suppressed": period.dropped - 1,
            },
        )

    async def _consume(self) -> None:
        """Laço do canal; reassina depois de qualquer queda do Redis."""
        while True:
            try:
                pubsub = self._pubsub
                if pubsub is None:
                    pubsub = await self._subscribe()
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        await self._dispatch(message["data"])
                logger.warning(
                    "Escuta do canal %s terminou sem erro; reassinando em %.1fs",
                    CHANNEL_OPC_WRITES,
                    RESUBSCRIBE_RETRY_S,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Assinante do canal %s caiu; reassinando em %.1fs",
                    CHANNEL_OPC_WRITES,
                    RESUBSCRIBE_RETRY_S,
                    exc_info=True,
                )
            await self._drop_pubsub()
            await asyncio.sleep(RESUBSCRIBE_RETRY_S)

    async def _dispatch(self, data: str | bytes) -> None:
        """Valida o payload e roda o pipeline; nada daqui escapa para o laço."""
        try:
            write = OpcWrite.model_validate_json(data)
        except Exception:
            # Sem conexão conhecida não há a quem atribuir o evento (spec §4.2).
            logger.warning("Payload inválido descartado no canal %s", CHANNEL_OPC_WRITES)
            return
        try:
            await self.handle(write)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erro inesperado no pipeline de escrita da conexão %s", write.conn_id)

    async def _subscribe(self) -> PubSub:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(CHANNEL_OPC_WRITES)
        self._pubsub = pubsub
        return pubsub

    async def _drop_pubsub(self) -> None:
        """Fecha o assinante atual sem nunca levantar: é caminho de desmonte."""
        pubsub, self._pubsub = self._pubsub, None
        if pubsub is None:
            return
        try:
            await pubsub.aclose()
        except Exception:
            logger.warning(
                "Falha ao fechar o assinante do canal %s", CHANNEL_OPC_WRITES, exc_info=True
            )


async def _cancel(task: asyncio.Task[None] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
