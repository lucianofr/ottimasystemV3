"""Barramento de eventos do runtime: o que ele escuta e o que ele emite (spec F3 §2.2-8/§4.3).

Escuta o canal `events` para honrar o contrato F2 §3.7 — `comm_failure` derruba os flows da
conexão caída (RF-207) e `project_activated` encerra a execução do projeto anterior (gancho
RF-101 registrado na F1). Todo o resto do canal é ignorado sem custo.

Emite os dois eventos que o supervisor **materializa** (`flow_deployed`/`flow_stopped`) e as
duas recusas (`deploy_rejected`/`reload_rejected`). `flow_overrun` e `flow_failed` são da
`FlowTask` (tarefa 1.4) e não se duplicam aqui.

Convenção de `origin` da fase: evento de flow usa `flow:<id>` exato, porque a lista do
frontend filtra por igualdade nesse campo (§6.1); o `user` do comando viaja no payload.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_COMM_FAILURE,
    KIND_DEPLOY_REJECTED,
    KIND_FLOW_DEPLOYED,
    KIND_FLOW_STOPPED,
    KIND_PROJECT_ACTIVATED,
    KIND_RELOAD_REJECTED,
    EventMessage,
    publish_event,
)

logger = logging.getLogger(__name__)

# Espera antes de reassinar um canal depois de uma queda do Redis (padrão do opc-worker).
RESUBSCRIBE_RETRY_S = 1.0


class ChannelListener:
    """Assinante resiliente de um canal do barramento.

    Mesma forma e mesmas garantias do `_listen_hints` do opc-worker: o SUBSCRIBE acontece no
    `start()` (mensagem publicada logo depois não se perde), a escuta reassina depois de
    qualquer queda — inclusive de um `listen()` que termina sem erro, porque o Redis pode
    fechar a conexão calado —, `CancelledError` é re-levantado e `stop()` nunca levanta,
    porque é caminho de desmonte.

    O freio vale para todo recomeço, não só para o caminho de exceção: sem ele um `listen()`
    que retorna na hora vira rajada de reassinatura queimando CPU.
    """

    def __init__(
        self,
        redis_client: Redis,
        channel: str,
        handler: Callable[[str], Awaitable[None]],
        *,
        retry_s: float = RESUBSCRIBE_RETRY_S,
    ) -> None:
        self._redis = redis_client
        self._channel = channel
        self._handler = handler
        self._retry_s = retry_s
        self._pubsub: PubSub | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Assina o canal e sobe a escuta. Idempotente."""
        if self._task is not None and not self._task.done():
            return
        await self._subscribe()
        self._task = asyncio.create_task(self._listen(), name=f"listener-{self._channel}")

    async def stop(self) -> None:
        """Cancela a escuta e fecha a inscrição. Idempotente e nunca levanta."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Falha ao encerrar a escuta do canal %s", self._channel)
        await self._drop_pubsub()

    async def _listen(self) -> None:
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
                    self._channel,
                    self._retry_s,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Assinante do canal %s caiu; reassinando em %.1fs",
                    self._channel,
                    self._retry_s,
                    exc_info=True,
                )
            await self._drop_pubsub()
            await asyncio.sleep(self._retry_s)

    async def _dispatch(self, data: str) -> None:
        """Falha de um payload não pode derrubar a escuta do canal inteiro."""
        try:
            await self._handler(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha ao tratar mensagem do canal %s", self._channel)

    async def _subscribe(self) -> PubSub:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel)
        self._pubsub = pubsub
        return pubsub

    async def _drop_pubsub(self) -> None:
        pubsub, self._pubsub = self._pubsub, None
        if pubsub is None:
            return
        try:
            await pubsub.aclose()
        except Exception:
            logger.warning("Falha ao fechar o assinante do canal %s", self._channel, exc_info=True)


def build_event_listener(
    redis_client: Redis,
    *,
    on_comm_failure: Callable[[int], Awaitable[None]],
    on_project_activated: Callable[[int], Awaitable[None]],
) -> ChannelListener:
    """Assinante do canal `events` com os dois `kind` que o runtime consome (§2.2-8).

    Payloads verificados no código da F2: `comm_failure` traz `conn_id`/`reason`/`detail` e
    `project_activated` traz `project_id`/`name`.
    """

    async def handle(data: str) -> None:
        try:
            event = EventMessage.model_validate_json(data)
        except Exception:
            logger.debug("Mensagem descartada no canal %s", CHANNEL_EVENTS, exc_info=True)
            return
        kind = event.payload.get("kind")
        if kind == KIND_COMM_FAILURE:
            conn_id = event.payload.get("conn_id")
            if isinstance(conn_id, int):
                await on_comm_failure(conn_id)
        elif kind == KIND_PROJECT_ACTIVATED:
            project_id = event.payload.get("project_id")
            if isinstance(project_id, int):
                await on_project_activated(project_id)

    return ChannelListener(redis_client, CHANNEL_EVENTS, handle)


def flow_origin(flow_id: int) -> str:
    """`origin` de evento de flow; §6.1 filtra por igualdade nele."""
    return f"flow:{flow_id}"


async def publish_flow_deployed(redis_client: Redis, *, flow_id: int, user: str) -> None:
    await publish_event(
        redis_client,
        severity="info",
        origin=flow_origin(flow_id),
        message=f"Flow {flow_id} em execução",
        kind=KIND_FLOW_DEPLOYED,
        payload={"flow_id": flow_id, "user": user},
    )


async def publish_flow_stopped(
    redis_client: Redis, *, flow_id: int, reason: str, user: str | None = None
) -> None:
    """`user` ausente quando não há comando de usuário atrás da parada (ruling do controlador):
    inventar um ator na trilha de auditoria seria pior do que a chave faltar.
    """
    payload: dict[str, object] = {"flow_id": flow_id, "reason": reason}
    if user is not None:
        payload["user"] = user
    await publish_event(
        redis_client,
        severity="info",
        origin=flow_origin(flow_id),
        message=f"Flow {flow_id} parado (motivo: {reason})",
        kind=KIND_FLOW_STOPPED,
        payload=payload,
    )


async def publish_rejected(
    redis_client: Redis,
    *,
    kind: str,
    flow_id: int,
    reason: str,
    message: str,
    detail: str,
    user: str | None = None,
) -> None:
    """Recusa de comando: `deploy_rejected` (§2.2-1) ou `reload_rejected` (§4.1-5).

    O `kind` entra por parâmetro porque as duas recusas têm severidade, `origin` e forma de
    payload idênticos e só diferem no vocabulário — duplicar a função separaria o que é a
    mesma regra.
    """
    payload: dict[str, object] = {"flow_id": flow_id, "reason": reason, "detail": detail}
    if user is not None:
        payload["user"] = user
    await publish_event(
        redis_client,
        severity="warning",
        origin=flow_origin(flow_id),
        message=message,
        kind=kind,
        payload=payload,
    )


__all__ = [
    "KIND_DEPLOY_REJECTED",
    "KIND_RELOAD_REJECTED",
    "RESUBSCRIBE_RETRY_S",
    "ChannelListener",
    "build_event_listener",
    "flow_origin",
    "publish_flow_deployed",
    "publish_flow_stopped",
    "publish_rejected",
]
