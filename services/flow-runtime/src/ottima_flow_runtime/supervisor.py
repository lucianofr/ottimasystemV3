"""Supervisor do flow-runtime: dono do ciclo de vida das `FlowTask` (spec F3 §2.2, §4.1).

Fonte da verdade é o banco. O supervisor consome `flow.commands` (`deploy`/`stop`/`reload`),
monta a `FlowDefinition` da tarefa 1.4 a partir do `graph_json` validado e mantém uma
`FlowTask` por flow rodando. O canal `events` entra por `events.py` e traz as duas reações do
contrato F2 §3.7. Um poll de 10 s é o backstop de dica perdida (§2.2-9).

Três invariantes carregam a fase:

1. **Boot parado é lei (ADR-017).** Nenhum caminho aqui sobe flow por `desired_state`: só o
   comando `deploy` instancia `FlowTask`. A passada de watermark itera **apenas o conjunto de
   flows rodando**, então subir um flow não é uma decisão que ela toma — é uma operação que
   ela não tem como expressar.
2. **Hot-swap nunca derruba flow (§4.1-5).** Staged inválido vira `reload_rejected` e a
   definição vigente continua varrendo.
3. **Desmonte isolado por flow.** Exceção parando um flow não pode deixar os seguintes vivos
   depois de `stop()` retornar (isto derrubou a tarefa 1.4 da F2 com um Critical). E as
   varreduras encerram **antes** do `ScriptPool`: pool parado com varredura em voo devolve
   `timeout`/`error` naquela varredura, o que viraria `script_error` espúrio no desligamento
   (achado da tarefa 1.3).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import (
    CHANNEL_FLOW_COMMANDS,
    KIND_DEPLOY_REJECTED,
    KIND_RELOAD_REJECTED,
    FlowCommand,
)
from ottima_core.flowgraph import (
    FlowGraph,
    FlowNode,
    GraphParseError,
    TagRef,
    parse_graph,
    validate_graph,
)
from ottima_core.models import Flow, OpcConnection, Project, Tag

from .blocks.base import Block
from .blocks.opc_read import OpcReadBlock
from .blocks.opc_write import OpcWriteBlock
from .blocks.script import ScriptBlock
from .blocks.tfs import TfsBlock
from .events import (
    ChannelListener,
    publish_flow_deployed,
    publish_flow_stopped,
    publish_rejected,
)
from .scheduler import FlowDefinition, FlowTask
from .script_pool import ScriptPool
from .snapshot import ValueSnapshot
from .state import RuntimeState

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 10.0  # spec §2.2-9; constante de código, não knob de env

# Motivos de `flow_stopped`/`deploy_rejected`/`reload_rejected` — identificadores em inglês,
# mensagens em pt-BR. `project_activated` é reusado pelo backstop de watermark de propósito:
# projeto que deixou de ser o ativo é a mesma causa da dica que se perdeu (§2.2-9).
REASON_USER = "user"
REASON_PROJECT_ACTIVATED = "project_activated"
REASON_COMM_FAILURE = "comm_failure"
REASON_FLOW_DELETED = "flow_deleted"
REASON_PROJECT_INACTIVE = "project_inactive"
REASON_INVALID_GRAPH = "invalid_graph"
# Desligamento do runtime: contrato com o mapa de tradução de `reason` do frontend (§6.1).
REASON_SHUTDOWN = "shutdown"

# Ator do log de desmonte do serviço. NUNCA entra em payload de auditoria: parada sem comando
# de usuário atrás omite a chave `user` (ver `events.publish_flow_stopped`).
SYSTEM_ACTOR = "runtime"

_TAG_TYPES = frozenset({"opc_read", "opc_write"})


class _Rejected(Exception):
    """Grafo do banco recusado na montagem da definição. `messages` traz todas as reprovações."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = list(messages)
        super().__init__(" | ".join(self.messages))


@dataclass(frozen=True, slots=True)
class _Staged:
    """Definição pronta para subir ou entrar em hot-swap, com o que o supervisor guarda dela."""

    definition: FlowDefinition
    ts_seconds: float
    conn_ids: frozenset[int]
    blocks: dict[str, tuple[dict[str, Any], Block]]
    """`block_id -> (config funcional, instância)`: a chave da preservação de estado (§4.1-3)."""


@dataclass(slots=True)
class _FlowRuntime:
    """O que o supervisor lembra de um flow que ele já materializou."""

    task: FlowTask
    ts_seconds: float
    updated_at: datetime | None
    conn_ids: frozenset[int]
    blocks: dict[str, tuple[dict[str, Any], Block]]


class Supervisor:
    """Mantém as `FlowTask` alinhadas com os comandos e com o banco."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        state: RuntimeState,
        *,
        snapshot: ValueSnapshot,
        pool: ScriptPool,
        poll_interval_s: float = POLL_INTERVAL_S,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._state = state
        self._snapshot = snapshot
        self._pool = pool
        self._poll_interval_s = poll_interval_s
        self._runtimes: dict[int, _FlowRuntime] = {}
        # Nunca dois comandos (ou comando e watermark) mexendo no mesmo mapa em paralelo.
        self._lock = asyncio.Lock()
        self._commands = ChannelListener(
            redis_client, CHANNEL_FLOW_COMMANDS, self._on_command_payload
        )
        self._poll_task: asyncio.Task[None] | None = None

    @property
    def flows(self) -> Mapping[int, FlowTask]:
        """Tasks vivas por `flow_id` — inclui as paradas e as em falha, como o `/health`."""
        return {flow_id: runtime.task for flow_id, runtime in self._runtimes.items()}

    async def start(self) -> None:
        """Sobe o pool, o consumidor de comandos e o poll. Idempotente.

        Nenhum flow sobe aqui (ADR-017): `desired_state` é exibição e só `deploy` executa.
        O pool primeiro, para a primeira varredura não pagar o boot dentro do próprio
        orçamento de 0,7xTs; o SUBSCRIBE antes de retornar, para um comando publicado logo
        depois do `start()` não se perder.
        """
        if self._poll_task is not None:
            return
        await self._pool.start()
        await self._commands.start()
        self._poll_task = asyncio.create_task(self._poll_loop(), name="supervisor-poll")

    async def stop(self) -> None:
        """Derruba poll, consumidor, todas as tasks e o pool — nesta ordem. Idempotente.

        Cada desmonte de flow é isolado: falha em um não pode abortar os outros, senão um
        flow sobreviveria ao `stop()` varrendo sem supervisor nenhum. O pool vem por último
        porque parar o pool com varredura em voo devolve erro naquela varredura.
        """
        await _cancel(self._poll_task, "loop de watermark do supervisor")
        self._poll_task = None
        await self._commands.stop()
        flow_ids = list(self._runtimes)
        results = await asyncio.gather(
            *(self._teardown(flow_id) for flow_id in flow_ids), return_exceptions=True
        )
        _log_teardown_results(flow_ids, results)
        await self._pool.stop()

    async def reconcile(self) -> None:
        """Uma passada de watermark, fora do relógio do poll. Nunca levanta."""
        await self._pass()

    # ----------------------------------------------------------------------------------
    # Comandos (`flow.commands`, spec §2.2-7)
    # ----------------------------------------------------------------------------------

    async def _on_command_payload(self, data: str) -> None:
        try:
            command = FlowCommand.model_validate_json(data)
        except Exception:
            logger.warning("Mensagem inválida no canal %s", CHANNEL_FLOW_COMMANDS, exc_info=True)
            return
        await self.handle_command(command)

    async def handle_command(self, command: FlowCommand) -> None:
        """Despacha um comando. Idempotente e nunca levanta (RNF-05)."""
        handlers = {"deploy": self._deploy, "stop": self._stop, "reload": self._reload}
        handler = handlers.get(command.cmd)
        if handler is None:
            logger.info(
                "Comando '%s' não é do vocabulário da F3; ignorado (flow %s)",
                command.cmd,
                command.flow_id,
            )
            return
        async with self._lock:
            try:
                await handler(command)
            except Exception:
                logger.exception(
                    "Falha ao processar o comando '%s' do flow %s", command.cmd, command.flow_id
                )

    async def _deploy(self, command: FlowCommand) -> None:
        flow_id = command.flow_id
        runtime = self._runtimes.get(flow_id)
        if runtime is not None and runtime.task.state == "running":
            return  # no-op sem evento duplicado (RNF-05)

        async with self._session_factory() as session:
            row = await self._load(session, flow_id)
            if row is None:
                logger.info("Comando deploy de flow %s desconhecido; ignorado", flow_id)
                return
            flow, project_active = row
            if not project_active:
                await self._reject(
                    KIND_DEPLOY_REJECTED,
                    flow_id=flow_id,
                    user=command.user,
                    reason=REASON_PROJECT_INACTIVE,
                    message=(f"Deploy do flow {flow_id} recusado: o projeto do flow não é o ativo"),
                    detail="ative o projeto do flow antes de executá-lo",
                )
                return
            try:
                # Deploy nasce zerado: `state` de bloco zera ao parar (RF-512), então não há
                # o que preservar de uma execução anterior.
                staged = await self._build(session, flow, reuse={})
            except _Rejected as rejected:
                await self._reject(
                    KIND_DEPLOY_REJECTED,
                    flow_id=flow_id,
                    user=command.user,
                    reason=REASON_INVALID_GRAPH,
                    message=f"Deploy do flow {flow_id} recusado: o grafo salvo é inválido",
                    detail=str(rejected),
                )
                return

        task = FlowTask(staged.definition, redis_client=self._redis)
        self._runtimes[flow_id] = _FlowRuntime(
            task=task,
            ts_seconds=staged.ts_seconds,
            updated_at=flow.updated_at,
            conn_ids=staged.conn_ids,
            blocks=staged.blocks,
        )
        self._state.track(flow_id, task)
        await task.start(user=command.user)
        await publish_flow_deployed(self._redis, flow_id=flow_id, user=command.user)

    async def _stop(self, command: FlowCommand) -> None:
        flow_id = command.flow_id
        runtime = self._runtimes.get(flow_id)
        if runtime is None or runtime.task.state != "running":
            # Parado, em falha ou desconhecido: nada a materializar, nenhum evento.
            return
        await runtime.task.stop(user=command.user, reason=REASON_USER)
        await publish_flow_stopped(
            self._redis, flow_id=flow_id, reason=REASON_USER, user=command.user
        )

    async def _reload(self, command: FlowCommand) -> None:
        flow_id = command.flow_id
        runtime = self._runtimes.get(flow_id)
        if runtime is None or runtime.task.state != "running":
            # Flow parado: o save é só persistência e o deploy futuro lê o vigente (§4.1-2).
            logger.info("Comando reload do flow %s, que não está rodando; ignorado", flow_id)
            return
        async with self._session_factory() as session:
            row = await self._load(session, flow_id)
            if row is None:
                logger.info("Comando reload de flow %s desconhecido; ignorado", flow_id)
                return
            flow, _ = row
            await self._stage(session, runtime, flow, user=command.user)

    # ----------------------------------------------------------------------------------
    # Hot-swap (spec §4.1)
    # ----------------------------------------------------------------------------------

    async def _stage(
        self,
        session: AsyncSession,
        runtime: _FlowRuntime,
        flow: Flow,
        *,
        user: str | None,
    ) -> None:
        """Monta a definição nova e a entrega ao laço, que a adota na fronteira seguinte."""
        # Ts novo muda a timebase inteira — discretização do TFS, timeout do Script e as
        # fronteiras: nada é preservado (§4.1-4).
        reuse = {} if float(flow.ts_seconds) != runtime.ts_seconds else runtime.blocks
        try:
            staged = await self._build(session, flow, reuse=reuse)
        except _Rejected as rejected:
            # A definição vigente continua rodando: hot-swap nunca derruba flow (§4.1-5).
            await self._reject(
                KIND_RELOAD_REJECTED,
                flow_id=flow.id,
                user=user,
                reason=REASON_INVALID_GRAPH,
                message=(
                    f"Hot-swap do flow {flow.id} recusado: o grafo salvo é inválido;"
                    " a definição em execução foi mantida"
                ),
                detail=str(rejected),
            )
            # Avança o watermark mesmo recusando: sem isso o poll repetiria o mesmo aviso a
            # cada 10 s enquanto o grafo continuasse inválido, virando alarme de fundo.
            runtime.updated_at = flow.updated_at
            return

        runtime.task.stage(staged.definition)
        runtime.ts_seconds = staged.ts_seconds
        runtime.conn_ids = staged.conn_ids
        runtime.blocks = staged.blocks
        runtime.updated_at = flow.updated_at

    async def _build(
        self,
        session: AsyncSession,
        flow: Flow,
        *,
        reuse: Mapping[str, tuple[dict[str, Any], Block]],
    ) -> _Staged:
        """`graph_json` + tags do projeto -> definição da 1.4. Levanta `_Rejected` se recusado."""
        try:
            graph = parse_graph(flow.graph_json)
        except GraphParseError as erro:
            raise _Rejected(erro.errors) from None
        tags = await _project_tags(session, flow.project_id)
        # `Flow.ts_seconds` é Numeric(4,1) e chega como Decimal: `Decimal * float` levanta
        # TypeError na aritmética de fronteira (armadilha herdada da F1).
        ts_seconds = float(flow.ts_seconds)
        result = validate_graph(graph, tags, ts_seconds)
        if result.errors:
            raise _Rejected(result.errors)
        for aviso in result.warnings:
            logger.info("Flow %s: %s", flow.id, aviso)

        blocks: dict[str, tuple[dict[str, Any], Block]] = {}
        instances: list[Block] = []
        for node in sorted(graph.nodes, key=lambda item: item.exec_order):
            functional = node.functional_config()
            kept = reuse.get(node.id)
            # Config funcional igual ⇒ a instância viva continua, e o estado interno vem
            # junto de graça (ADR-011). O método É o comparador: `exec_order`, rótulo e
            # posição ficam fora dele de propósito (ADR-024).
            block = (
                kept[1]
                if kept is not None and kept[0] == functional
                else self._instantiate(node, flow_id=flow.id, ts_seconds=ts_seconds, tags=tags)
            )
            blocks[node.id] = (functional, block)
            instances.append(block)

        return _Staged(
            definition=FlowDefinition(
                flow_id=flow.id,
                ts_seconds=ts_seconds,
                blocks=tuple(instances),
                wiring=_wiring(graph),
            ),
            ts_seconds=ts_seconds,
            conn_ids=_conn_ids(graph, tags),
            blocks=blocks,
        )

    def _instantiate(
        self, node: FlowNode, *, flow_id: int, ts_seconds: float, tags: Mapping[int, TagRef]
    ) -> Block:
        """Instancia o bloco com os serviços do runtime. Bloco novo nasce zerado (§4.1-3)."""
        config: Any = node.config
        if node.type == "opc_read":
            tag = tags[config.tag_id]
            return OpcReadBlock(
                node.id, tag_id=tag.id, data_type=tag.data_type, snapshot=self._snapshot
            )
        if node.type == "opc_write":
            tag = tags[config.tag_id]
            return OpcWriteBlock(
                node.id,
                tag_id=tag.id,
                conn_id=tag.conn_id,
                flow_id=flow_id,
                redis_client=self._redis,
            )
        if node.type == "script":
            return ScriptBlock(
                node.id,
                code=config.code,
                n_inputs=config.n_inputs,
                n_outputs=config.n_outputs,
                flow_id=flow_id,
                ts_seconds=ts_seconds,
                pool=self._pool,
                redis_client=self._redis,
            )
        return TfsBlock(node.id, matrix=config.matrix, ts_seconds=ts_seconds)

    # ----------------------------------------------------------------------------------
    # Contrato F2 §3.7 (spec §2.2-8)
    # ----------------------------------------------------------------------------------

    async def on_comm_failure(self, conn_id: int) -> None:
        """Derruba os flows cujo grafo referencia tag da conexão caída (RF-207).

        Os demais seguem intactos, e descongelar não retoma nada: retomada é só por deploy
        manual (ADR-017). Quem emite `flow_failed` é a própria `FlowTask` (tarefa 1.4).
        """
        async with self._lock:
            for flow_id, runtime in list(self._runtimes.items()):
                if runtime.task.state != "running" or conn_id not in runtime.conn_ids:
                    continue
                try:
                    await runtime.task.fail(reason=REASON_COMM_FAILURE)
                except Exception:
                    # Isolado por flow: um que falhe ao cair não pode poupar os seguintes.
                    logger.exception(
                        "Falha ao derrubar o flow %s por queda da conexão %s", flow_id, conn_id
                    )

    async def on_project_activated(self, project_id: int) -> None:
        """Para **todos** os flows rodando: pertencem ao projeto anterior (§4.3, gancho RF-101)."""
        logger.info("Projeto %s ativado: parando todos os flows em execução", project_id)
        async with self._lock:
            for flow_id in list(self._runtimes):
                await self._force_stop(flow_id, reason=REASON_PROJECT_ACTIVATED)

    # ----------------------------------------------------------------------------------
    # Watermark backstop (spec §2.2-9)
    # ----------------------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval_s)
            await self._pass()

    async def _pass(self) -> None:
        """Uma passada sobre os flows **rodando**. Absorve toda exceção.

        O domínio da passada é o conjunto de flows rodando, e é por construção que ela nunca
        inicia flow nenhum (contrato 1 / ADR-017): não existe caminho daqui para `start()`.
        """
        async with self._lock:
            running = [
                flow_id
                for flow_id, runtime in self._runtimes.items()
                if runtime.task.state == "running"
            ]
            if not running:
                return
            try:
                async with self._session_factory() as session:
                    for flow_id in running:
                        await self._reconcile_flow(session, flow_id)
            except Exception:
                logger.exception("Falha na passada de watermark do supervisor")

    async def _reconcile_flow(self, session: AsyncSession, flow_id: int) -> None:
        runtime = self._runtimes.get(flow_id)
        if runtime is None:
            return
        try:
            row = await self._load(session, flow_id)
            if row is None:
                logger.info("Flow %s não existe mais no banco; parando", flow_id)
                await self._force_stop(flow_id, reason=REASON_FLOW_DELETED)
                return
            flow, project_active = row
            if not project_active:
                logger.info("Projeto do flow %s deixou de ser o ativo; parando", flow_id)
                await self._force_stop(flow_id, reason=REASON_PROJECT_ACTIVATED)
                return
            if flow.updated_at == runtime.updated_at:
                return
            # Dica de `reload` perdida: o banco é a fonte da verdade (§4.1-1).
            logger.info("Flow %s mudou no banco sem dica; aplicando hot-swap", flow_id)
            await self._stage(session, runtime, flow, user=None)
        except Exception:
            # Isolado por flow: erro em um não pode abortar a passada dos outros.
            logger.exception("Falha ao reconciliar o flow %s", flow_id)

    # ----------------------------------------------------------------------------------
    # Auxiliares
    # ----------------------------------------------------------------------------------

    async def _load(self, session: AsyncSession, flow_id: int) -> tuple[Flow, bool] | None:
        """Flow e se o projeto dele é o ativo, numa consulta (§2.2-1 pergunta as duas coisas)."""
        row = (
            await session.execute(
                select(Flow, Project.is_active)
                .join(Project, Project.id == Flow.project_id)
                .where(Flow.id == flow_id)
            )
        ).first()
        if row is None:
            return None
        return row[0], bool(row[1])

    async def _force_stop(self, flow_id: int, *, reason: str) -> None:
        """Parada sem comando de usuário atrás: o `reason` carrega a causa, o `user` não existe."""
        runtime = self._runtimes.get(flow_id)
        if runtime is None or runtime.task.state != "running":
            return
        try:
            await runtime.task.stop(user=SYSTEM_ACTOR, reason=reason)
        except Exception:
            logger.exception("Falha ao parar o flow %s (motivo=%s)", flow_id, reason)
            return
        await publish_flow_stopped(self._redis, flow_id=flow_id, reason=reason)

    async def _reject(
        self,
        kind: str,
        *,
        flow_id: int,
        user: str | None,
        reason: str,
        message: str,
        detail: str,
    ) -> None:
        logger.warning("%s (motivo=%s): %s", message, reason, detail)
        await publish_rejected(
            self._redis,
            kind=kind,
            flow_id=flow_id,
            reason=reason,
            message=message,
            detail=detail,
            user=user,
        )

    async def _teardown(self, flow_id: int) -> None:
        """Para a task e tira o flow do mapa e do `/health`.

        A entrada sai do mapa mesmo quando o `stop()` falha, e só depois da tentativa: manter
        um flow quebrado no mapa travaria todo comando seguinte, e removê-lo antes de tentar
        deixaria a task viva e inalcançável.

        O flow que estava rodando ganha `flow_stopped` com `reason="shutdown"`: sem ele o
        último evento de estado continuaria `flow_deployed`, e depois de um restart a lista
        mostraria "Rodando" enquanto o `/health` mostra `flows={}`.
        """
        runtime = self._runtimes.get(flow_id)
        try:
            if runtime is not None:
                was_running = runtime.task.state == "running"
                await runtime.task.stop(user=SYSTEM_ACTOR, reason=REASON_SHUTDOWN)
                if was_running:
                    # Sem usuário comandando um desligamento: a chave `user` é omitida, como
                    # nos demais caminhos de parada sem comando (ruling do controlador).
                    await publish_flow_stopped(self._redis, flow_id=flow_id, reason=REASON_SHUTDOWN)
        except Exception:
            logger.exception("Falha ao parar o flow %s; a entrada é removida assim mesmo", flow_id)
        finally:
            self._runtimes.pop(flow_id, None)
            self._state.forget(flow_id)


async def _project_tags(session: AsyncSession, project_id: int) -> dict[int, TagRef]:
    """Tags visíveis ao flow: as do projeto dele, via conexão (o `graph_json` não tem FK).

    Uma consulta para o grafo inteiro — o número de nós não pode virar número de queries.
    """
    stmt = (
        select(Tag.id, Tag.connection_id, Tag.direction, Tag.data_type)
        .join(OpcConnection, OpcConnection.id == Tag.connection_id)
        .where(OpcConnection.project_id == project_id)
    )
    return {
        row.id: TagRef(
            id=row.id,
            conn_id=row.connection_id,
            direction=row.direction,
            data_type=row.data_type,
        )
        for row in await session.execute(stmt)
    }


def _wiring(graph: FlowGraph) -> dict[str, dict[str, tuple[str, str]]]:
    """`wiring[block_id][handle_de_entrada] = (bloco_origem, handle_de_origem)`."""
    wiring: dict[str, dict[str, tuple[str, str]]] = {}
    for edge in graph.edges:
        wiring.setdefault(edge.target, {})[edge.target_handle] = (edge.source, edge.source_handle)
    return wiring


def _conn_ids(graph: FlowGraph, tags: Mapping[int, TagRef]) -> frozenset[int]:
    """Conexões que o grafo referencia — o conjunto que o `comm_failure` consulta (§2.2-8).

    Mora aqui, e não na `FlowDefinition`, porque o laço de varredura não tem nada a fazer
    com `conn_id`: quem reage à queda de conexão é o supervisor.
    """
    return frozenset(
        tags[node.config.tag_id].conn_id
        for node in graph.nodes
        if node.type in _TAG_TYPES and node.config.tag_id in tags
    )


def _log_teardown_results(flow_ids: list[int], results: list[Any]) -> None:
    """Registra o que o gather engoliu: desmonte silencioso esconde flow órfão varrendo."""
    for flow_id, result in zip(flow_ids, results, strict=True):
        if not isinstance(result, BaseException):
            continue
        if isinstance(result, asyncio.CancelledError):
            logger.warning("Desmonte do flow %s foi cancelado por fora", flow_id)
        else:
            logger.error("Falha inesperada ao desmontar o flow %s", flow_id, exc_info=result)


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
