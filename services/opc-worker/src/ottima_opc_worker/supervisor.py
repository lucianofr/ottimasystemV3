"""Supervisor do worker: reconciliação banco -> sessões OPC-UA (spec F2 §2.2-1).

Fonte da verdade é o banco, lido via `ottima-core`. O supervisor compara um watermark
barato (contagens + `max(updated_at)` do projeto ativo) com o último visto e, quando muda,
carrega a configuração completa e ajusta os runtimes: cria, derruba ou reconfigura.
O canal `events` só serve de dica para antecipar a passada; perda de mensagem é inofensiva
porque o poll corrige (RF-201/204, ADR-017).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_CONNECTION_CREATED,
    KIND_CONNECTION_DELETED,
    KIND_CONNECTION_UPDATED,
    KIND_PROJECT_ACTIVATED,
    KIND_TAG_CREATED,
    KIND_TAG_DELETED,
    KIND_TAG_UPDATED,
    EventMessage,
)
from ottima_core.models import OpcConnection, Project, Tag

from .connection import ConnectionRuntime
from .state import ConnectionConfig, ConnectionSnapshot, TagConfig, WorkerState

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 10.0  # spec §2.2-1; constante de código, não knob de env
MAX_CONNECTIONS = 5  # RF-201: no máximo 5 sessões simultâneas
# Espera antes de reassinar o canal de eventos depois de uma queda do Redis.
HINT_RETRY_S = 1.0

# Kinds de auditoria da API (spec §7.2/§7.3) que antecipam a reconciliação.
HINT_KINDS: frozenset[str] = frozenset(
    {
        KIND_PROJECT_ACTIVATED,
        KIND_CONNECTION_CREATED,
        KIND_CONNECTION_UPDATED,
        KIND_CONNECTION_DELETED,
        KIND_TAG_CREATED,
        KIND_TAG_UPDATED,
        KIND_TAG_DELETED,
    }
)


@dataclass(frozen=True, slots=True)
class Watermark:
    """Assinatura barata do estado da configuração do projeto ativo."""

    project_id: int | None
    projects_max_updated_at: datetime | None
    connections_count: int
    connections_max_updated_at: datetime | None
    tags_count: int
    tags_max_updated_at: datetime | None


_NO_PROJECT = Watermark(
    project_id=None,
    projects_max_updated_at=None,
    connections_count=0,
    connections_max_updated_at=None,
    tags_count=0,
    tags_max_updated_at=None,
)


async def read_watermark(session: AsyncSession) -> Watermark:
    """Assinatura do projeto ativo por agregados: nunca carrega linhas de configuração."""
    project_id = await session.scalar(select(Project.id).where(Project.is_active))
    if project_id is None:
        # ADR-017: sem projeto ativo não há nada a supervisionar.
        return _NO_PROJECT

    projects_max = await session.scalar(
        select(func.max(Project.updated_at)).where(Project.is_active)
    )
    connections_count, connections_max = (
        await session.execute(
            select(func.count(), func.max(OpcConnection.updated_at)).where(
                OpcConnection.project_id == project_id
            )
        )
    ).one()
    tags_count, tags_max = (
        await session.execute(
            select(func.count(), func.max(Tag.updated_at))
            .select_from(Tag)
            .join(OpcConnection, Tag.connection_id == OpcConnection.id)
            .where(OpcConnection.project_id == project_id)
        )
    ).one()
    return Watermark(
        project_id=project_id,
        projects_max_updated_at=projects_max,
        connections_count=connections_count,
        connections_max_updated_at=connections_max,
        tags_count=tags_count,
        tags_max_updated_at=tags_max,
    )


async def load_active_configuration(session: AsyncSession) -> tuple[ConnectionConfig, ...]:
    """Configuração completa do projeto ativo, em uma única transação de leitura.

    Conexões vêm ordenadas por `id` (o teto de conexões corta as últimas) e as tags de
    cada conexão também: sem ordem estável o `tags_key` mudaria sozinho e o diff
    recriaria subscription a cada passada.
    """
    project_id = await session.scalar(select(Project.id).where(Project.is_active))
    if project_id is None:
        return ()
    connections = (
        await session.scalars(
            select(OpcConnection)
            .where(OpcConnection.project_id == project_id)
            .order_by(OpcConnection.id)
        )
    ).all()
    if not connections:
        return ()

    tags: dict[int, list[TagConfig]] = {connection.id: [] for connection in connections}
    rows = await session.scalars(
        select(Tag).where(Tag.connection_id.in_(list(tags))).order_by(Tag.id)
    )
    for tag in rows:
        tags[tag.connection_id].append(
            TagConfig(
                id=tag.id,
                name=tag.name,
                node_id=tag.node_id,
                direction=tag.direction,
                data_type=tag.data_type,
            )
        )
    return tuple(_to_config(connection, tuple(tags[connection.id])) for connection in connections)


def _to_config(connection: OpcConnection, tags: tuple[TagConfig, ...]) -> ConnectionConfig:
    return ConnectionConfig(
        id=connection.id,
        project_id=connection.project_id,
        name=connection.name,
        endpoint=connection.endpoint,
        security_policy=connection.security_policy,
        security_mode=connection.security_mode,
        auth_mode=connection.auth_mode,
        auth_username=connection.auth_username,
        auth_password_enc=connection.auth_password_enc,
        server_cert_file=connection.server_cert_file,
        watchdog_read_node_id=connection.watchdog_read_node_id,
        watchdog_write_node_id=connection.watchdog_write_node_id,
        watchdog_period_ms=connection.watchdog_period_ms,
        tags=tags,
    )


class Supervisor:
    """Mantém os runtimes de conexão alinhados com o projeto ativo no banco."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        state: WorkerState,
        *,
        certs_dir: Path = Path("/certs"),
        fernet_key: str = "",
        poll_interval_s: float = POLL_INTERVAL_S,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._state = state
        self._certs_dir = certs_dir
        self._fernet_key = fernet_key
        self._poll_interval_s = poll_interval_s
        self._runtimes: dict[int, ConnectionRuntime] = {}
        # None antes da primeira passada: nenhum Watermark é igual a None, então o
        # primeiro ciclo sempre reconcilia.
        self._watermark: Watermark | None = None
        self._hint = asyncio.Event()
        # Nunca dois reconciles em voo: dica e poll competem pelo mesmo estado.
        self._lock = asyncio.Lock()
        self._poll_task: asyncio.Task[None] | None = None
        self._hint_task: asyncio.Task[None] | None = None
        self._pubsub: PubSub | None = None

    @property
    def runtimes(self) -> Mapping[int, ConnectionRuntime]:
        """Runtimes vivos por `conn_id`; a escrita (tarefa 2.3) resolve a sessão por aqui."""
        return self._runtimes

    async def start(self) -> None:
        """Sobe o assinante de `events` e o loop de poll. Idempotente."""
        if self._poll_task is not None:
            return
        # SUBSCRIBE antes de retornar: uma dica publicada logo após o start() não se perde.
        await self._subscribe_events()
        self._hint_task = asyncio.create_task(self._listen_hints(), name="supervisor-hints")
        self._poll_task = asyncio.create_task(self._poll_loop(), name="supervisor-poll")

    async def stop(self) -> None:
        """Derruba assinante, loop e todos os runtimes. Idempotente.

        Cada desmonte é isolado: falha em um não pode abortar os outros. Runtime que
        sobrevivesse a um `stop()` viraria sessão OPC órfã, falando com o PLC sem
        supervisor nenhum.
        """
        await _cancel(self._poll_task, "loop de poll do supervisor")
        await _cancel(self._hint_task, "assinante do canal de eventos")
        self._poll_task = None
        self._hint_task = None
        await self._drop_pubsub()
        conn_ids = list(self._runtimes)
        resultados = await asyncio.gather(
            *(self._teardown(conn_id) for conn_id in conn_ids),
            return_exceptions=True,
        )
        _log_teardown_results(conn_ids, resultados)
        self._watermark = None

    async def reconcile(self) -> None:
        """Uma passada de reconciliação, independente do watermark. Nunca levanta."""
        await self._pass(force=True)

    async def _poll_loop(self) -> None:
        while True:
            await self._pass(force=False)
            # A dica encurta a espera; o timeout é o poll da spec.
            with suppress(TimeoutError):
                await asyncio.wait_for(self._hint.wait(), timeout=self._poll_interval_s)
            self._hint.clear()

    async def _pass(self, *, force: bool) -> None:
        """Lê watermark, carrega config se mudou e aplica o diff. Absorve toda exceção."""
        async with self._lock:
            try:
                async with self._session_factory() as session:
                    watermark = await read_watermark(session)
                    if not force and watermark == self._watermark:
                        return
                    configs = await load_active_configuration(session)
                await self._apply(configs)
            except Exception:
                # Watermark não avança: a próxima passada tenta de novo.
                logger.exception("Falha na reconciliação do supervisor; watermark preservado")
                return
            self._watermark = watermark

    async def _apply(self, configs: tuple[ConnectionConfig, ...]) -> None:
        wanted = {config.id: config for config in self._within_limit(configs)}
        for conn_id in [conn_id for conn_id in self._runtimes if conn_id not in wanted]:
            await self._teardown(conn_id)
        for conn_id, config in wanted.items():
            runtime = self._runtimes.get(conn_id)
            if runtime is None:
                await self._spawn(config)
            elif runtime.config.session_key != config.session_key:
                # Campo da conexão mudou: a sessão asyncua não é reconfigurável. A falha
                # pendente atravessa a troca — quem resolve a causa editando a conexão
                # (confiar no certificado, reinformar a senha) precisa ver o `comm_restored`
                # quando a sessão nova sobe, senão a tela fica presa no alarme antigo.
                pendente = runtime.failure_pending
                await self._teardown(conn_id)
                await self._spawn(config, failure_pending=pendente)
            elif runtime.config.tags_key != config.tags_key:
                # Só o conjunto de tags mudou: troca a subscription sem derrubar a sessão.
                await runtime.apply_tags(config.tags)

    def _within_limit(self, configs: tuple[ConnectionConfig, ...]) -> tuple[ConnectionConfig, ...]:
        """Corta o excedente do teto de conexões (RF-201) com um log por passada."""
        if len(configs) <= MAX_CONNECTIONS:
            return configs
        logger.error(
            "Projeto ativo tem %d conexões e o teto é %d (RF-201); ignorando as conexões %s",
            len(configs),
            MAX_CONNECTIONS,
            [config.id for config in configs[MAX_CONNECTIONS:]],
        )
        return configs[:MAX_CONNECTIONS]

    async def _spawn(self, config: ConnectionConfig, *, failure_pending: bool = False) -> None:
        snapshot = ConnectionSnapshot(name=config.name)
        runtime = ConnectionRuntime(
            config,
            self._redis,
            snapshot,
            certs_dir=self._certs_dir,
            fernet_key=self._fernet_key,
            failure_pending=failure_pending,
        )
        self._runtimes[config.id] = runtime
        self._state.connections[config.id] = snapshot
        await runtime.start()
        logger.info("Conexão %s (%s) supervisionada", config.id, config.name)

    async def _teardown(self, conn_id: int) -> None:
        """Para o runtime e tira a conexão do mapa e do `/health`.

        A entrada sai do mapa mesmo quando o `stop()` falha, e só depois da tentativa:
        manter uma conexão quebrada no mapa travaria a reconciliação para sempre, porque
        toda passada seguinte tropeçaria no mesmo runtime e jamais subiria a configuração
        nova. Remover antes de tentar seria pior ainda — o runtime seguiria vivo e
        inalcançável.
        """
        runtime = self._runtimes.get(conn_id)
        try:
            if runtime is not None:
                await runtime.stop()
                logger.info("Conexão %s (%s) desmontada", conn_id, runtime.config.name)
        except Exception:
            logger.exception(
                "Falha ao parar a conexão %s; a entrada é removida assim mesmo", conn_id
            )
        finally:
            self._runtimes.pop(conn_id, None)
            self._state.connections.pop(conn_id, None)

    async def _listen_hints(self) -> None:
        """Traduz evento de auditoria em sinal; o reconcile é sempre do loop de poll.

        Perder uma dica é inofensivo por contrato (o poll corrige), mas a morte silenciosa
        desta task não é: o sistema degradaria para o poll de 10 s sem ninguém saber. Por
        isso o laço reassina o canal depois de qualquer queda do Redis.
        """
        while True:
            try:
                pubsub = self._pubsub
                if pubsub is None:
                    pubsub = await self._subscribe_events()
                async for message in pubsub.listen():
                    if message["type"] == "message" and _is_hint(message["data"]):
                        self._hint.set()
                # Escuta que termina limpa também é canal perdido: o Redis pode fechar a
                # conexão sem levantar nada.
                logger.warning(
                    "Escuta do canal %s terminou sem erro; reassinando em %.1fs",
                    CHANNEL_EVENTS,
                    HINT_RETRY_S,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Assinante do canal %s caiu; reassinando em %.1fs",
                    CHANNEL_EVENTS,
                    HINT_RETRY_S,
                    exc_info=True,
                )
            # O freio vale para TODO recomeço, não só para o caminho de exceção: sem ele
            # um listen() que retorna na hora vira rajada de reassinatura queimando CPU.
            await self._drop_pubsub()
            await asyncio.sleep(HINT_RETRY_S)

    async def _subscribe_events(self) -> PubSub:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(CHANNEL_EVENTS)
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
            logger.warning("Falha ao fechar o assinante do canal %s", CHANNEL_EVENTS, exc_info=True)


def _is_hint(data: str) -> bool:
    try:
        kind = EventMessage.model_validate_json(data).payload["kind"]
    except Exception:
        logger.debug("Mensagem descartada no canal %s", CHANNEL_EVENTS, exc_info=True)
        return False
    return kind in HINT_KINDS


def _log_teardown_results(conn_ids: list[int], resultados: list[object]) -> None:
    """Registra o que o gather engoliu: desmonte silencioso esconde sessão OPC órfã."""
    for conn_id, resultado in zip(conn_ids, resultados, strict=True):
        if not isinstance(resultado, BaseException):
            continue
        if isinstance(resultado, asyncio.CancelledError):
            # Anormal, mas não é erro de programação: o cancelamento veio de fora, já que
            # o `stop()` inteiro sendo cancelado repropagaria em vez de cair aqui.
            logger.warning("Desmonte da conexão %s foi cancelado por fora", conn_id)
        else:
            logger.exception(
                "Falha inesperada ao desmontar a conexão %s", conn_id, exc_info=resultado
            )


async def _cancel(task: asyncio.Task[None] | None, what: str) -> None:
    """Cancela e aguarda a task; erro dela não pode impedir o resto do desmonte."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Falha ao encerrar %s", what)
