"""Laço resiliente de assinatura ao barramento pub/sub do Redis (canal fixo ou padrão glob).

Três consumidores da F3 reimplementavam quase à letra a mesma reação a queda do Redis, cada
um com uma pequena divergência entre si — a mais grave foi o hub de `/ws`, que não fechava o
pubsub quando o `start()` falhava no meio, vazando conexão e inscrição no servidor a cada
reconexão (defeito real na F3). Este módulo unifica o laço: `ChannelListener` assina um canal
fixo (`SUBSCRIBE`), `PatternListener` assina um padrão glob (`PSUBSCRIBE`).

Garantias comuns aos dois, o mais defensivo das três cópias:
- `start()` só retorna com a inscrição confirmada — a publicação seguinte não se perde;
- queda do Redis reassina com freio entre tentativas, sem nunca levantar para fora do laço;
- exceção do `handler` é logada e engolida (RNF-05): o laço nunca morre por handler ruim;
- `stop()` é idempotente e nunca levanta, mesmo sob `BaseException` no meio do `start()`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

logger = logging.getLogger(__name__)

RESUBSCRIBE_RETRY_S = 1.0
"""Freio entre reassinaturas: queda do Redis não pode virar rajada de SUBSCRIBE/PSUBSCRIBE."""

SUBSCRIBE_TIMEOUT_S = 5.0
"""Teto da confirmação: o Redis é local ao stack, não confirmar em 5 s é falha real."""


class _ResilientSubscriber:
    """Esqueleto do laço resiliente.

    `ChannelListener` e `PatternListener` só variam o verbo Redis (SUBSCRIBE/PSUBSCRIBE), o
    tipo da mensagem de confirmação e a forma da mensagem despachada ao `handler`.
    """

    _confirmation_type: str
    _message_type: str

    def __init__(self, redis: Redis, target: str, *, name: str) -> None:
        self._redis = redis
        self._target = target
        self._name = name
        self._pubsub: PubSub | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Assina o alvo e sobe a escuta; só retorna com a inscrição confirmada. Idempotente."""
        if self._task is not None and not self._task.done():
            return
        await self._subscribe()
        self._task = asyncio.create_task(self._listen(), name=self._name)

    async def stop(self) -> None:
        """Cancela a escuta e fecha a inscrição. Idempotente e nunca levanta: é desmonte."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Falha ao encerrar a escuta de %s", self._target)
        await self._drop_pubsub()

    async def _listen(self) -> None:
        while True:
            try:
                pubsub = self._pubsub
                if pubsub is None:
                    pubsub = await self._subscribe()
                async for message in pubsub.listen():
                    if message["type"] == self._message_type:
                        await self._safe_dispatch(message)
                logger.warning(
                    "Escuta de %s terminou sem erro; reassinando em %.1fs",
                    self._target,
                    RESUBSCRIBE_RETRY_S,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Assinante de %s caiu; reassinando em %.1fs",
                    self._target,
                    RESUBSCRIBE_RETRY_S,
                    exc_info=True,
                )
            await self._drop_pubsub()
            await asyncio.sleep(RESUBSCRIBE_RETRY_S)

    async def _safe_dispatch(self, message: Mapping[str, Any]) -> None:
        """Falha do `handler` não pode derrubar a escuta inteira (RNF-05)."""
        try:
            await self._dispatch(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha ao tratar mensagem de %s", self._target)

    async def _subscribe(self) -> PubSub:
        pubsub = self._redis.pubsub()
        try:
            await self._do_subscribe(pubsub)
            await self._await_confirmation(pubsub)
        except BaseException:
            # Falhou antes de virar `self._pubsub`, onde nem `stop()` o alcançaria: sem este
            # fechamento, cada start() que falha vaza conexão e inscrição no servidor.
            await _close(pubsub, self._target)
            raise
        self._pubsub = pubsub
        return pubsub

    async def _await_confirmation(self, pubsub: PubSub) -> None:
        """Só volta com a inscrição confirmada: a publicação seguinte não se perde.

        Mensagem que chega na janela da confirmação é despachada como qualquer outra, em
        vez de virar evento perdido no start.
        """
        async with asyncio.timeout(SUBSCRIBE_TIMEOUT_S):
            while True:
                message = await pubsub.get_message(timeout=SUBSCRIBE_TIMEOUT_S)
                if message is None:
                    continue
                if message["type"] == self._confirmation_type:
                    return
                if message["type"] == self._message_type:
                    await self._safe_dispatch(message)

    async def _drop_pubsub(self) -> None:
        pubsub, self._pubsub = self._pubsub, None
        if pubsub is not None:
            await _close(pubsub, self._target)

    async def _do_subscribe(self, pubsub: PubSub) -> None:
        raise NotImplementedError

    async def _dispatch(self, message: Mapping[str, Any]) -> None:
        raise NotImplementedError


class ChannelListener(_ResilientSubscriber):
    """Assinante resiliente de um canal fixo (`SUBSCRIBE`); `handler` recebe só o `data`."""

    _confirmation_type = "subscribe"
    _message_type = "message"

    def __init__(
        self,
        redis: Redis,
        channel: str,
        handler: Callable[[str], Awaitable[None]],
        *,
        name: str,
    ) -> None:
        super().__init__(redis, channel, name=name)
        self._handler = handler

    async def _do_subscribe(self, pubsub: PubSub) -> None:
        await pubsub.subscribe(self._target)

    async def _dispatch(self, message: Mapping[str, Any]) -> None:
        await self._handler(message["data"])


class PatternListener(_ResilientSubscriber):
    """Assinante resiliente de um padrão glob (`PSUBSCRIBE`); `handler` recebe `(channel, data)`."""

    _confirmation_type = "psubscribe"
    _message_type = "pmessage"

    def __init__(
        self,
        redis: Redis,
        pattern: str,
        handler: Callable[[str, str], Awaitable[None]],
        *,
        name: str,
    ) -> None:
        super().__init__(redis, pattern, name=name)
        self._handler = handler

    async def _do_subscribe(self, pubsub: PubSub) -> None:
        await pubsub.psubscribe(self._target)

    async def _dispatch(self, message: Mapping[str, Any]) -> None:
        await self._handler(message["channel"], message["data"])


async def _close(pubsub: PubSub, target: str) -> None:
    """Fecha o assinante sem nunca levantar: é caminho de desmonte."""
    try:
        await pubsub.aclose()  # aclose desfaz a inscrição e devolve a conexão
    except Exception:
        logger.warning("Falha ao fechar o assinante de %s", target, exc_info=True)


__all__ = ["RESUBSCRIBE_RETRY_S", "SUBSCRIBE_TIMEOUT_S", "ChannelListener", "PatternListener"]
