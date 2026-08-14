"""WebSocket `/ws`: fanout de `flow.status.<id>`, `mpc.state.<flow_id>.<block_id>` e do canal
`events` para o cliente ao vivo (RF-305, spec F3 §5.3; fanout de `mpc.state` — spec F4 §6.2,
decisão A-6; canal `events` — spec F5 §5, decisão A-5).

Três assinaturas Redis por processo, uma por barramento/canal (`flow.status.*`, `mpc.state.*`
e `events`): duas dúzias de editores abertos não podem virar duas dúzias de conexões Redis
por canal.

O laço que lê cada barramento nunca aguarda um socket — ele só enfileira, e cada socket tem a
sua task de envio com fila limitada. Um TCP travado de um operador não pode congelar os
valores ao vivo dos demais (RNF-05).

Sem replay: assinar não entrega o último valor conhecido, o cliente espera a próxima
varredura/execução/evento. É isso que mantém a API sem estado de flow.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

import jwt
from fastapi import APIRouter, WebSocket
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.bus import CHANNEL_EVENTS
from ottima_core.config import Settings
from ottima_core.models import User
from ottima_core.pubsub import ChannelListener, PatternListener
from ottima_core.security import decode_access_token

logger = logging.getLogger(__name__)

STATUS_PATTERN = "flow.status.*"
"""Um só assinante para todos os flows: o padrão cobre `flow.status.<flow_id>` inteiro."""

STATUS_PREFIX = "flow.status."

MPC_STATE_PATTERN = "mpc.state.*"
"""Segunda assinatura do hub: um só padrão cobre `mpc.state.<flow_id>.<block_id>` (spec F4 §6.2)."""

MPC_STATE_PREFIX = "mpc.state."

OPC_VALUES_PATTERN = "opc.values.*"
"""Terceira assinatura do hub: valores crus do opc-worker (RF-204) filtrados por tag
(decisão F6 A-1 revertida — a operação precisa da taxa OPC, não da taxa do MPC)."""

OPC_VALUES_PREFIX = "opc.values."

QUEUE_MAX = 8
"""Mensagens em espera por socket. O Ts mínimo é 0,5 s (ADR-007), então 8 mensagens são ~4 s
de folga por flow inscrito — cobre soluço de rede sem deixar um cliente travado acumular
memória. Cheia, descarta-se a **mais antiga**: o canvas mostra estado publicado, não
histórico (RNF-05, fire-and-forget)."""


class Subscriber:
    """Um socket inscrito: os flows/blocos que ele quer, se está no canal `events`, a fila
    que o protege e a task de envio."""

    def __init__(self, socket: WebSocket) -> None:
        self._socket = socket
        self.flow_ids: set[int] = set()
        self.mpc_ids: set[tuple[int, str]] = set()
        self.tags: set[int] = set()
        self.events: bool = False
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
    """Assinatura única de `flow.status.*`, `mpc.state.*` e do canal `events` roteando aos
    sockets inscritos (§5.3; fanout de `mpc.state` — spec F4 §6.2, decisão A-6; canal
    `events` — spec F5 §5, decisão A-5).

    Três escutas resilientes (dois `PatternListener` e um `ChannelListener`), uma por
    barramento/canal, sobre o mesmo cliente Redis: o invariante de UMA assinatura por
    processo (§5.3/§6.2) vale por barramento/canal, nunca uma segunda conexão para o mesmo
    padrão ou canal.
    """

    def __init__(self, redis_client: Redis) -> None:
        self._subs: set[Subscriber] = set()
        self._listener = PatternListener(
            redis_client, STATUS_PATTERN, self._dispatch_status, name="api-flow-status-hub"
        )
        self._mpc_listener = PatternListener(
            redis_client, MPC_STATE_PATTERN, self._dispatch_mpc_state, name="api-mpc-state-hub"
        )
        self._opc_listener = PatternListener(
            redis_client, OPC_VALUES_PATTERN, self._dispatch_opc_values, name="api-opc-values-hub"
        )
        self._events_listener = ChannelListener(
            redis_client, CHANNEL_EVENTS, self._dispatch_events, name="api-events-hub"
        )

    async def start(self) -> None:
        """Assina os dois padrões e o canal `events`, e sobe as tasks de leitura; retorna já.
        Idempotente.

        O P/SUBSCRIBE e o SUBSCRIBE acontecem aqui, e não dentro das tasks: quem chamou
        `start()` precisa poder contar com as inscrições ativas em seguida.
        """
        await self._listener.start()
        await self._mpc_listener.start()
        await self._opc_listener.start()
        await self._events_listener.start()

    async def stop(self) -> None:
        """Para os laços, encerra as inscrições e fecha os sockets restantes. Nunca levanta."""
        await self._listener.stop()
        await self._mpc_listener.stop()
        await self._opc_listener.stop()
        await self._events_listener.stop()
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

    async def _dispatch_status(self, channel: str, raw: str) -> None:
        flow_id = _flow_id_of(channel)
        if flow_id is not None:
            await self._fanout(channel, raw, "flow_ids", flow_id)

    async def _dispatch_mpc_state(self, channel: str, raw: str) -> None:
        mpc_id = _mpc_id_of(channel)
        if mpc_id is not None:
            await self._fanout(channel, raw, "mpc_ids", mpc_id)

    async def _dispatch_opc_values(self, channel: str, raw: str) -> None:
        """Fanout de `opc.values.<conn_id>`: o filtro é o `tag_id` DENTRO do payload (o canal
        é por conexão, RF-204), então o `_fanout` por id de canal não serve aqui."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Payload inválido descartado no fanout de %s: %.200s", channel, raw)
            return
        tag_id = data.get("tag_id") if isinstance(data, dict) else None
        if not isinstance(tag_id, int) or isinstance(tag_id, bool):
            logger.info("opc.values sem tag_id inteiro, ignorado: %.200s", raw)
            return
        # `data` vai como veio do barramento: remontar arriscaria divergir do RF-204.
        text = json.dumps({"channel": channel, "data": data})
        for sub in self._subs:
            if tag_id in sub.tags:
                sub.offer(text)

    async def _dispatch_events(self, raw: str) -> None:
        """Fanout do canal `events`: sem id, entrega a quem ligou `sub.events` (§5, F5R-15)."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Payload inválido descartado no fanout de events: %.200s", raw)
            return
        text = json.dumps({"channel": CHANNEL_EVENTS, "data": data})
        for sub in self._subs:
            if sub.events:
                sub.offer(text)

    async def _fanout(self, channel: str, raw: str, attr_name: str, wanted: object) -> None:
        """Roteia uma publicação para quem pediu aquele flow/bloco.

        Não aguarda nenhum socket (`offer()` é síncrono): um cliente lento não pode congelar
        os demais.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Payload inválido descartado no fanout de %s: %.200s", channel, raw)
            return
        # `data` vai como veio do barramento: remontar arriscaria divergir do §4.2/§5.1.
        text = json.dumps({"channel": channel, "data": data})
        # Varredura linear: são poucas dezenas de sockets, e um índice por flow/bloco custaria
        # sincronizar dois estados a cada subscribe/unsubscribe.
        for sub in self._subs:
            if wanted in getattr(sub, attr_name):
                sub.offer(text)


def _flow_id_of(channel: str) -> int | None:
    suffix = channel.removeprefix(STATUS_PREFIX)
    return int(suffix) if suffix.isdigit() else None


def _mpc_id_of(channel: str) -> tuple[int, str] | None:
    suffix = channel.removeprefix(MPC_STATE_PREFIX)
    flow_id_str, sep, block_id = suffix.partition(".")
    if sep and flow_id_str.isdigit() and block_id:
        return int(flow_id_str), block_id
    return None


def _flow_ids(ids: Any) -> set[int]:
    """Só inteiros: item de forma inesperada é ignorado, não derruba a conexão."""
    if not isinstance(ids, list):
        logger.info("Lista de flows inesperada no /ws, ignorada: %.200s", ids)
        return set()
    return {i for i in ids if isinstance(i, int) and not isinstance(i, bool)}


def _tag_ids(ids: Any) -> set[int]:
    """Mesmo formato de `_flow_ids`, para a assinatura `opc_values` (lista de tag_id)."""
    if not isinstance(ids, list):
        logger.info("Lista de opc_values inesperada no /ws, ignorada: %.200s", ids)
        return set()
    return {i for i in ids if isinstance(i, int) and not isinstance(i, bool)}


def _mpc_ids(ids: Any) -> set[tuple[int, str]]:
    """Só pares `flow_id/block_id` bem formados (§6.2); item malformado é ignorado."""
    if not isinstance(ids, list):
        logger.info("Lista de mpc_state inesperada no /ws, ignorada: %.200s", ids)
        return set()
    parsed: set[tuple[int, str]] = set()
    for item in ids:
        if not isinstance(item, str):
            continue
        flow_id_str, sep, block_id = item.partition("/")
        if sep and flow_id_str.isdigit() and block_id:
            parsed.add((int(flow_id_str), block_id))
    return parsed


def _apply_events(sub: Subscriber, action: str, value: Any) -> None:
    """Ramo booleano do canal `events` (§5, F5R-15): só o literal `True` liga/desliga —
    qualquer outro valor é logado e ignorado, sem inverter a ação."""
    if value is not True:
        logger.info("Valor inesperado em events no /ws, ignorado: %.200s", value)
        return
    sub.events = action == "subscribe"


def _apply_client_message(sub: Subscriber, raw: str) -> None:
    """Aplica `subscribe`/`unsubscribe` de `flow_status`/`mpc_state`/`events`; o resto é
    logado e ignorado. Mensagem malformada nunca derruba o socket (§5.3/§6.2; `events` — §5).
    """
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        logger.info("Mensagem não-JSON ignorada no /ws: %.200s", raw)
        return
    if not isinstance(message, dict):
        logger.info("Mensagem de forma inesperada ignorada no /ws: %.200s", raw)
        return
    for action in ("subscribe", "unsubscribe"):
        body = message.get(action)
        if body is None:
            continue
        if not isinstance(body, dict):
            logger.info("Corpo inesperado em %s no /ws, ignorado: %.200s", action, body)
            continue
        for key, ids in body.items():
            if key == "flow_status":
                attr_name, parse = "flow_ids", _flow_ids
            elif key == "mpc_state":
                attr_name, parse = "mpc_ids", _mpc_ids
            elif key == "opc_values":
                attr_name, parse = "tags", _tag_ids
            elif key == "events":
                _apply_events(sub, action, ids)
                continue
            else:
                logger.info("Canal %s fora do escopo do /ws, ignorado", key)
                continue
            attr: set[Any] = getattr(sub, attr_name)
            (attr.update if action == "subscribe" else attr.difference_update)(parse(ids))


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
async def flow_status_ws(websocket: WebSocket, token: str | None = None) -> None:
    """Canal ao vivo do canvas: `?token=` de operador e `subscribe`/`unsubscribe` de flows,
    blocos MPC e do canal `events` (`flow_status`/`mpc_state`/`events`)."""
    # Aceitar antes de recusar é deliberado: fechar sem aceitar vira um 403 HTTP que o
    # cliente WS não distingue de falha de rede, e o canvas precisa saber que foi auth.
    await websocket.accept()
    # A sessão morre com a autenticação, não com o socket: o laço de receive não toca no
    # banco, e uma conexão retida por socket esgotaria o pool com uma dúzia de editores.
    async with websocket.app.state.session_factory() as session:
        user = await _authenticate(token, session, websocket.app.state.settings)
    if user is None:
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
