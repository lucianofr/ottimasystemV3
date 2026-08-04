"""WebSocket `/ws`: fanout de `flow.status.<id>` para o canvas ao vivo (RF-305, spec F3 §5.3).

Uma **única** assinatura Redis por processo (`psubscribe flow.status.*`) alimenta todos os
sockets: duas dúzias de editores abertos não podem virar duas dúzias de conexões Redis.

O laço que lê o barramento nunca aguarda um socket — ele só enfileira, e cada socket tem a
sua task de envio com fila limitada. Um TCP travado de um operador não pode congelar os
valores ao vivo dos demais (RNF-05).

Sem replay: assinar não entrega o último valor conhecido, o cliente espera a próxima
varredura. É isso que mantém a API sem estado de flow.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from typing import Any

import jwt
from fastapi import APIRouter, Depends, WebSocket
from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.config import Settings
from ottima_core.models import User
from ottima_core.security import decode_access_token

logger = logging.getLogger(__name__)

STATUS_PATTERN = "flow.status.*"
"""Um só assinante para todos os flows: o padrão cobre `flow.status.<flow_id>` inteiro."""

STATUS_PREFIX = "flow.status."

QUEUE_MAX = 8
"""Mensagens em espera por socket. O Ts mínimo é 0,5 s (ADR-007), então 8 mensagens são ~4 s
de folga por flow inscrito — cobre soluço de rede sem deixar um cliente travado acumular
memória. Cheia, descarta-se a **mais antiga**: o canvas mostra estado publicado, não
histórico (RNF-05, fire-and-forget)."""

RESUBSCRIBE_RETRY_S = 1.0
"""Freio entre reassinaturas: queda do Redis não pode virar rajada de PSUBSCRIBE."""

SUBSCRIBE_TIMEOUT_S = 5.0
"""Teto do PSUBSCRIBE: o Redis é local ao stack, não confirmar em 5 s é falha real."""


class Subscriber:
    """Um socket inscrito: os flows que ele quer, a fila que o protege e a task de envio."""

    def __init__(self, socket: WebSocket) -> None:
        self._socket = socket
        self.flow_ids: set[int] = set()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_MAX)
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._send_loop(), name="ws-flow-status-send")

    def offer(self, text: str) -> None:
        """Enfileira sem nunca aguardar; fila cheia descarta a mensagem mais antiga.

        Síncrono de propósito: é chamado de dentro do laço do hub, que atende todos os
        sockets. Um `await` aqui seria o cliente lento congelando os demais.
        """
        if self._queue.full():
            self._queue.get_nowait()
        self._queue.put_nowait(text)

    async def stop(self) -> None:
        """Cancela a task de envio. Idempotente e nunca levanta: é desmonte."""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def close(self) -> None:
        """Encerra o envio e fecha o socket; um socket já morto é caminho normal."""
        await self.stop()
        try:
            await self._socket.close(code=1001, reason="Servidor encerrando")
        except Exception:
            logger.debug("Socket já encerrado no desmonte do hub", exc_info=True)

    async def _send_loop(self) -> None:
        while True:
            text = await self._queue.get()
            try:
                await self._socket.send_text(text)
            except Exception:
                # Socket que cai no meio do envio é caminho normal: o endpoint desregistra.
                logger.debug("Envio interrompido; encerrando o fanout deste cliente")
                return


class FlowStatusHub:
    """Assinatura única de `flow.status.*` roteando para os sockets inscritos (§5.3)."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client
        self._subs: set[Subscriber] = set()
        self._pubsub: PubSub | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Assina o padrão e sobe a task de leitura; retorna já. Idempotente.

        O PSUBSCRIBE acontece aqui, e não dentro da task: quem chamou `start()` precisa poder
        contar com a inscrição ativa em seguida.
        """
        if self._task is not None and not self._task.done():
            return
        self._pubsub = await self._subscribe()
        self._task = asyncio.create_task(self._read_loop(), name="api-flow-status-hub")

    async def stop(self) -> None:
        """Para o laço, encerra a inscrição e fecha os sockets restantes. Nunca levanta."""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self._close_pubsub()
        subs, self._subs = self._subs, set()
        for sub in subs:
            await sub.close()

    async def register(self, socket: WebSocket) -> Subscriber:
        sub = Subscriber(socket)
        sub.start()
        self._subs.add(sub)
        return sub

    async def unregister(self, sub: Subscriber) -> None:
        self._subs.discard(sub)
        await sub.stop()

    async def _read_loop(self) -> None:
        """Laço do padrão; reassina depois de qualquer queda do Redis.

        O que foi publicado durante a queda se perde — é o mesmo contrato de sempre: sem
        replay, a varredura seguinte repõe o estado.
        """
        while True:
            try:
                if self._pubsub is None:
                    self._pubsub = await self._subscribe()
                async for message in self._pubsub.listen():
                    self._dispatch(message)
                logger.warning(
                    "Escuta de %s terminou sem erro; reassinando em %.1fs",
                    STATUS_PATTERN,
                    RESUBSCRIBE_RETRY_S,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Assinante de %s caiu; reassinando em %.1fs",
                    STATUS_PATTERN,
                    RESUBSCRIBE_RETRY_S,
                    exc_info=True,
                )
            await self._close_pubsub()
            await asyncio.sleep(RESUBSCRIBE_RETRY_S)

    def _dispatch(self, message: Mapping[str, Any]) -> None:
        """Roteia uma publicação para quem pediu aquele flow. Sem `await`, por contrato."""
        if message["type"] != "pmessage":
            return
        channel = message["channel"]
        flow_id = _flow_id_of(channel)
        if flow_id is None:
            return
        raw = message["data"]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Payload inválido descartado no fanout de %s: %.200s", channel, raw)
            return
        # `data` vai como veio do barramento: remontar arriscaria divergir do §4.2.
        text = json.dumps({"channel": channel, "data": data})
        # Varredura linear: são poucas dezenas de sockets, e um índice por flow custaria
        # sincronizar dois estados a cada subscribe/unsubscribe.
        for sub in self._subs:
            if flow_id in sub.flow_ids:
                sub.offer(text)

    async def _subscribe(self) -> PubSub:
        pubsub = self._redis.pubsub()
        try:
            await pubsub.psubscribe(STATUS_PATTERN)
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
        """Só volta com o PSUBSCRIBE confirmado: a publicação seguinte não se perde."""
        async with asyncio.timeout(SUBSCRIBE_TIMEOUT_S):
            while True:
                message = await pubsub.get_message(timeout=SUBSCRIBE_TIMEOUT_S)
                if message is None:
                    continue
                if message["type"] == "psubscribe":
                    return
                self._dispatch(message)


async def _close(pubsub: PubSub) -> None:
    """Fecha o assinante sem nunca levantar: é caminho de desmonte."""
    try:
        await pubsub.aclose()  # aclose desfaz a inscrição e devolve a conexão
    except Exception:
        logger.warning("Falha ao fechar o assinante de %s", STATUS_PATTERN, exc_info=True)


def _flow_id_of(channel: str) -> int | None:
    suffix = channel.removeprefix(STATUS_PREFIX)
    return int(suffix) if suffix.isdigit() else None


def _flow_ids(ids: Any) -> set[int]:
    """Só inteiros: item de forma inesperada é ignorado, não derruba a conexão."""
    if not isinstance(ids, list):
        logger.info("Lista de flows inesperada no /ws, ignorada: %.200s", ids)
        return set()
    return {i for i in ids if isinstance(i, int) and not isinstance(i, bool)}


def _apply_client_message(sub: Subscriber, raw: str) -> None:
    """Aplica `subscribe`/`unsubscribe` de `flow_status`; o resto é logado e ignorado.

    Escopo F3: só `flow_status`. Mensagem malformada nunca derruba o socket (§5.3).
    """
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        logger.info("Mensagem não-JSON ignorada no /ws: %.200s", raw)
        return
    if not isinstance(message, dict):
        logger.info("Mensagem de forma inesperada ignorada no /ws: %.200s", raw)
        return
    for action, apply in (
        ("subscribe", sub.flow_ids.update),
        ("unsubscribe", sub.flow_ids.difference_update),
    ):
        body = message.get(action)
        if body is None:
            continue
        if not isinstance(body, dict):
            logger.info("Corpo inesperado em %s no /ws, ignorado: %.200s", action, body)
            continue
        for key, ids in body.items():
            if key != "flow_status":
                logger.info("Canal %s fora do escopo da F3, ignorado no /ws", key)
                continue
            apply(_flow_ids(ids))


async def get_ws_db(websocket: WebSocket) -> AsyncIterator[AsyncSession]:
    """Sessão por conexão WebSocket.

    `deps.get_db` não serve aqui: ele declara `Request`, que o FastAPI não injeta em rota
    WebSocket (a chamada estoura com argumento faltando).
    """
    async with websocket.app.state.session_factory() as session:
        yield session


async def _authenticate(token: str | None, db: AsyncSession, settings: Settings) -> User | None:
    """Token vem na query string (§5.3, risco aceito no ADR-023), não no header.

    Papel operator é o piso: admin também passa (ADR-015), como em `require_operator`.
    """
    if not token:
        return None
    try:
        payload = decode_access_token(token, secret=settings.secret_key)
    except jwt.PyJWTError:
        return None
    user = await db.get(User, int(payload["sub"]))  # sub é string por contrato do JWT
    if user is None or not user.is_active:
        return None
    return user


router = APIRouter()


@router.websocket("/ws")
async def flow_status_ws(
    websocket: WebSocket,
    token: str | None = None,
    db: AsyncSession = Depends(get_ws_db),
) -> None:
    """Canal ao vivo do canvas: `?token=` de operador e `subscribe`/`unsubscribe` de flows."""
    # Aceitar antes de recusar é deliberado: fechar sem aceitar vira um 403 HTTP que o
    # cliente WS não distingue de falha de rede, e o canvas precisa saber que foi auth.
    await websocket.accept()
    if await _authenticate(token, db, websocket.app.state.settings) is None:
        await websocket.close(code=1008, reason="Sessão inválida ou expirada")
        return

    hub: FlowStatusHub = websocket.app.state.flow_status_hub
    sub = await hub.register(websocket)
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            raw = message.get("text")
            if raw is None:
                logger.info("Quadro binário ignorado no /ws")
                continue
            _apply_client_message(sub, raw)
    finally:
        await hub.unregister(sub)
