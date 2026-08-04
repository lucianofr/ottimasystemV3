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

import logging
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

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
from ottima_core.pubsub import ChannelListener

logger = logging.getLogger(__name__)


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

    return ChannelListener(
        redis_client, CHANNEL_EVENTS, handle, name=f"listener-{CHANNEL_EVENTS}"
    )


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
    "ChannelListener",
    "build_event_listener",
    "flow_origin",
    "publish_flow_deployed",
    "publish_flow_stopped",
    "publish_rejected",
]
