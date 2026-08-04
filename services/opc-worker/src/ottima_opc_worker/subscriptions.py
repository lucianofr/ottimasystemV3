"""Subscriptions OPC-UA do worker: monitored items → `opc.values.<conn_id>` (spec F2 §2.2-4/5/7).

Uma subscription por conexão, um monitored item por tag de leitura. O canal só recebe o
payload §7.1 (`OpcValue`) e a publicação tem um ponto único, porque as tarefas seguintes
(heartbeat de valor e rajada de quality=bad) publicam com a sessão caída, sem subscription.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from asyncua import Client, ua
from asyncua.common.node import Node
from asyncua.common.subscription import DataChangeNotif, Subscription
from redis.asyncio import Redis

from ottima_core.bus import (
    KIND_TAG_SUBSCRIBE_ERROR,
    OpcValue,
    channel_opc_values,
    publish_event,
)

from .state import ConnectionConfig, ConnectionSnapshot, TagConfig, TagSnapshot

logger = logging.getLogger(__name__)

# Dado cíclico: 250 ms é metade do menor Ts da F3 e o mais recente vence (spec §2.2-5).
PUBLISHING_INTERVAL_MS = 250
SAMPLING_INTERVAL_MS = 250
QUEUE_SIZE = 1

QUALITY_GOOD = 0
QUALITY_UNCERTAIN = 1
QUALITY_BAD = 2

# A severidade da StatusCode vive nos 2 bits mais altos (OPC-UA Part 4 §7.34).
_SEVERITY_SHIFT = 30
_SEVERITY_TO_QUALITY = {0: QUALITY_GOOD, 1: QUALITY_UNCERTAIN}


def status_to_quality(status_code: ua.StatusCode | None) -> int:
    """StatusCode OPC-UA → quality 0/1/2 (spec F1 §3.4-4).

    A severidade está nos 2 bits mais altos do código: 0=Good, 1=Uncertain, 2=Bad,
    3=reservado (tratado como Bad). Ausência de status também é Bad: sem qualidade
    declarada o valor não pode ser dado bom.
    """
    if status_code is None:
        return QUALITY_BAD
    severity = (int(status_code.value) >> _SEVERITY_SHIFT) & 0b11
    return _SEVERITY_TO_QUALITY.get(severity, QUALITY_BAD)


def coerce_value(raw: Any) -> float:
    """Valor OPC → float (bool→0.0/1.0, int→float; None ⇒ 0.0 sob quality bad).

    `samples.value` é DOUBLE PRECISION (spec F1 §3.2): o barramento já trafega float.
    """
    if raw is None:
        return 0.0
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    return float(raw)


async def publish_value(
    redis_client: Redis,
    conn_id: int,
    snapshot: ConnectionSnapshot,
    *,
    tag_id: int,
    value: float,
    quality: int,
    ts: datetime | None = None,
) -> None:
    """Ponto único de publicação em `opc.values.<conn_id>` (payload §7.1 verbatim).

    É função de módulo, não método, porque o heartbeat de valor (tarefa 1.3) e a rajada de
    quality=bad (tarefa 2.2) publicam com a sessão CAÍDA, quando não existe subscription.
    `published_at` é o relógio de parede da publicação, distinto de `ts` (timestamp da
    fonte): o heartbeat decide por ele para que servidor com relógio adiantado não o cale.
    """
    ts = _as_utc(ts) if ts is not None else datetime.now(UTC)
    published_at = datetime.now(UTC)
    payload = OpcValue(tag_id=tag_id, ts=ts, value=value, quality=quality)
    await redis_client.publish(channel_opc_values(conn_id), payload.model_dump_json())
    snapshot.last_values[tag_id] = TagSnapshot(
        ts=ts, value=value, quality=quality, published_at=published_at
    )
    snapshot.last_publish_ts = published_at


def _as_utc(moment: datetime) -> datetime:
    """Timestamp do servidor em UTC aware; naive é tratado como UTC (spec §2.2-7)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


class ValueSubscription:
    """Uma subscription por conexão, com um monitored item por tag `direction='r'`."""

    def __init__(
        self,
        config: ConnectionConfig,
        client: Client,
        redis_client: Redis,
        snapshot: ConnectionSnapshot,
    ) -> None:
        self._config = config
        self._client = client
        self._redis = redis_client
        self._snapshot = snapshot
        self._subscription: Subscription | None = None
        self._tags_by_handle: dict[int, TagConfig] = {}
        # Notificação pode chegar antes do handle voltar do servidor (asyncua registra o
        # monitored item antes da resposta): o node_id é o mapa de resgate nessa janela.
        self._tags_by_node: dict[str, TagConfig] = {}
        # Dedupe do evento por tag: uma tag mal configurada não vira rajada de warning.
        # Uma nova subscription (nova sessão ou troca de tags) rearma o dedupe.
        self._reported_errors: set[int] = set()

    @property
    def asyncua_subscription(self) -> Subscription | None:
        """Subscription do asyncua criada por `start()`; None antes de subir ou após parar."""
        return self._subscription

    async def start(self) -> None:
        """Cria a subscription e um monitored item por tag de leitura.

        Falha ao criar a subscription propaga (é falha de sessão); falha de uma tag
        isolada não derruba as outras (spec §2.2-4).
        """
        subscription = await self._client.create_subscription(PUBLISHING_INTERVAL_MS, self)
        self._subscription = subscription
        subscribed = 0
        for tag in self._config.tags:
            if tag.direction != "r":
                # Monitored item é leitura; o readback de uma tag W é tag R própria (RF-604).
                continue
            if await self._subscribe_tag(subscription, tag):
                subscribed += 1
        self._snapshot.tags_subscribed = subscribed

    async def _subscribe_tag(self, subscription: Subscription, tag: TagConfig) -> bool:
        try:
            node = self._client.get_node(tag.node_id)
            self._tags_by_node[str(node.nodeid)] = tag
            handle = await subscription.subscribe_data_change(
                node, queuesize=QUEUE_SIZE, sampling_interval=SAMPLING_INTERVAL_MS
            )
        except Exception as exc:
            await self._report_tag_error(
                tag, "node inválido ou inexistente", f"{type(exc).__name__}: {exc}".strip()
            )
            return False
        if isinstance(handle, int):
            self._tags_by_handle[handle] = tag
        return True

    async def _report_tag_error(self, tag: TagConfig, reason: str, detail: str) -> None:
        """Erro de cadastro da tag: ela vira bad e avisa uma vez, sem derrubar a conexão.

        Tag muda por erro de configuração é proibido (spec §2.2-4): quem consome
        `opc.values` precisa distinguir "sem dado" de "dado ruim".
        """
        self._snapshot.monitored_errors += 1
        await publish_value(
            self._redis,
            self._config.id,
            self._snapshot,
            tag_id=tag.id,
            value=0.0,
            quality=QUALITY_BAD,
        )
        logger.warning(
            "Tag %s (%s) da conexão %s em falha: %s — %s",
            tag.id,
            tag.node_id,
            self._config.id,
            reason,
            detail,
        )
        if tag.id in self._reported_errors:
            return
        self._reported_errors.add(tag.id)
        await publish_event(
            self._redis,
            severity="warning",
            origin=f"conn:{self._config.id}",
            message=(f"Falha na tag '{tag.name}' da conexão '{self._config.name}': {reason}"),
            kind=KIND_TAG_SUBSCRIBE_ERROR,
            payload={
                "conn_id": self._config.id,
                "tag_id": tag.id,
                "node_id": tag.node_id,
                "detail": detail,
            },
        )

    async def stop(self) -> None:
        """Deleta a subscription no servidor. Idempotente."""
        subscription, self._subscription = self._subscription, None
        self._tags_by_handle.clear()
        self._tags_by_node.clear()
        self._snapshot.tags_subscribed = 0
        if subscription is None:
            return
        try:
            await subscription.delete()
        except Exception:
            # Sessão já caída é o caminho normal aqui: não há nada a apagar no servidor.
            logger.debug("Erro ignorado ao deletar subscription", exc_info=True)

    async def datachange_notification(self, node: Node, val: Any, data: DataChangeNotif) -> None:
        """Callback do asyncua (assinatura fixada pela lib) para cada datachange.

        Nenhuma exceção escapa: esta corrotina roda na task de dispatch do asyncua e um
        erro em UMA tag mataria a entrega de TODAS as outras da subscription. Este é o
        único ponto do worker onde engolir exceção é o comportamento correto.
        """
        try:
            tag = self._resolve_tag(node, data)
            if tag is None:
                logger.warning(
                    "Datachange sem tag correspondente na conexão %s: %s", self._config.id, node
                )
                return
            data_value = data.monitored_item.Value
            try:
                value = coerce_value(val)
            except (TypeError, ValueError) as exc:
                # Node de tipo incompatível com a tag é erro de cadastro: publica bad e
                # avisa, em vez de deixar a tag muda no canal.
                await self._report_tag_error(
                    tag, "valor do node não é numérico", f"{type(exc).__name__}: {exc}".strip()
                )
                return
            await publish_value(
                self._redis,
                self._config.id,
                self._snapshot,
                tag_id=tag.id,
                value=value,
                quality=status_to_quality(data_value.StatusCode if data_value else None),
                ts=_notification_ts(data_value),
            )
        except Exception:
            logger.exception(
                "Erro ao processar datachange da conexão %s (node %s)", self._config.id, node
            )

    def _resolve_tag(self, node: Node, data: DataChangeNotif) -> TagConfig | None:
        handle = data.subscription_data.server_handle
        if handle is not None:
            tag = self._tags_by_handle.get(handle)
            if tag is not None:
                return tag
        return self._tags_by_node.get(str(node.nodeid))


def _notification_ts(data_value: ua.DataValue | None) -> datetime | None:
    """SourceTimestamp → ServerTimestamp → None (o publisher usa `now()`), spec §2.2-7."""
    if data_value is None:
        return None
    return data_value.SourceTimestamp or data_value.ServerTimestamp
