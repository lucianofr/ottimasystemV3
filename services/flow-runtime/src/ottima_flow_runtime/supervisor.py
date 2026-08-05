"""Supervisor do flow-runtime: dono do ciclo de vida das `FlowTask` (spec F3 §2.2, §4.1).

Fonte da verdade é o banco. O supervisor consome `flow.commands` (`deploy`/`stop`/`reload`,
mais `mpc_mode`/`mpc_sp`/`mpc_mv`, plano F4b §4.8), monta a `FlowDefinition` da tarefa 1.4 a
partir do `graph_json` validado e mantém uma `FlowTask` por flow rodando. O canal `events`
entra por `events.py` e traz as duas reações do contrato F2 §3.7. Um poll de 10 s é o
backstop de dica perdida (§2.2-9).

Quatro invariantes carregam a fase:

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
4. **`MpcHost` é do supervisor (plano F4b, tarefa 2.2).** Todo `MpcHost` que `definition.py`
   monta é `start()`ado aqui e `stop()`ado aqui — nunca pelo bloco, nunca pelo `FlowTask`.
   Confirmação de armar e shed (spec §4.4/§4.5) moram em `mpc_arming.py`, uma task de fundo
   por bloco armado que este módulo cria/cancela; stop gracioso em REMOTO devolve o PID
   (`mode_cmd=auto`) antes de encerrar a task de varredura, e hot-swap sheda o bloco
   substituído antes de derrubar o host antigo.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from multiprocessing.connection import Connection
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import (
    CHANNEL_FLOW_COMMANDS,
    KIND_DEPLOY_REJECTED,
    KIND_MPC_ARM_FAILED,
    KIND_MPC_SHED,
    KIND_RELOAD_REJECTED,
    FlowCommand,
    publish_event,
)
from ottima_core.flowgraph import GraphParseError, parse_graph, validate_graph
from ottima_core.models import Flow, Project
from ottima_core.tags import project_tags

from .blocks.base import Block
from .blocks.mpc import MpcBlock
from .definition import StagedDefinition, build_definition
from .events import (
    ChannelListener,
    mpc_block_origin,
    publish_flow_deployed,
    publish_flow_stopped,
    publish_mpc_hot_swap,
    publish_rejected,
)
from .mpc.host import MpcHost
from .mpc.worker import worker_main
from .mpc_arming import watch_arm, write_mode_cmd
from .scheduler import FlowTask
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

# Mensagem humana por `reason` de `_Rejected`, compartilhada entre deploy e hot-swap: as
# duas recusas têm o mesmo texto de causa, só o prefixo de ação (§4.3) muda por chamador.
_REJECTION_REASON_MESSAGES: dict[str, str] = {
    REASON_INVALID_GRAPH: "o grafo salvo é inválido",
}

# Ator do log de desmonte do serviço. NUNCA entra em payload de auditoria: parada sem comando
# de usuário atrás omite a chave `user` (ver `events.publish_flow_stopped`).
SYSTEM_ACTOR = "runtime"


class _Rejected(Exception):
    """Grafo do banco recusado na montagem da definição. `messages` traz todas as reprovações."""

    def __init__(self, messages: list[str], *, reason: str = REASON_INVALID_GRAPH) -> None:
        self.messages = list(messages)
        self.reason = reason
        super().__init__(" | ".join(self.messages))


@dataclass(slots=True)
class _FlowRuntime:
    """O que o supervisor lembra de um flow que ele já materializou."""

    task: FlowTask
    ts_seconds: float
    updated_at: datetime | None
    conn_ids: frozenset[int]
    blocks: dict[str, tuple[dict[str, Any], Block]]
    hosts: dict[str, MpcHost] = field(default_factory=dict)
    """`block_id -> MpcHost`, só dos blocos `mpc` (plano F4b, tarefa 2.2) — o supervisor é
    dono do ciclo de vida deles."""
    mpc_write_opc: Any = None
    """`write_opc` com `conn_id` já resolvido (`definition._make_write_opc`) — reusado para
    escrever `mode_cmd` fora do `step()` do bloco (transições §4.4/§4.5)."""
    mpc_watchdogs: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    """`block_id -> task` de `mpc_arming.watch_arm`, uma por bloco armado agora mesmo."""


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
        mpc_worker_target: Callable[[Connection, str, float], None] = worker_main,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._state = state
        self._snapshot = snapshot
        self._pool = pool
        self._poll_interval_s = poll_interval_s
        self._mpc_worker_target = mpc_worker_target
        self._runtimes: dict[int, _FlowRuntime] = {}
        # Nunca dois comandos (ou comando e watermark) mexendo no mesmo mapa em paralelo.
        self._lock = asyncio.Lock()
        self._commands = ChannelListener(
            redis_client,
            CHANNEL_FLOW_COMMANDS,
            self._on_command_payload,
            name=f"listener-{CHANNEL_FLOW_COMMANDS}",
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
    # Comandos (`flow.commands`, spec §2.2-7, §4.8)
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
        handlers = {
            "deploy": self._deploy,
            "stop": self._stop,
            "reload": self._reload,
            "mpc_mode": self._mpc_command,
            "mpc_sp": self._mpc_command,
            "mpc_mv": self._mpc_command,
        }
        handler = handlers.get(command.cmd)
        if handler is None:
            logger.info(
                "Comando '%s' não é do vocabulário da F3/F4b; ignorado (flow %s)",
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
        old_runtime = self._runtimes.get(flow_id)
        if old_runtime is not None and old_runtime.task.state == "running":
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
                    reason=rejected.reason,
                    message=(
                        f"Deploy do flow {flow_id} recusado: "
                        f"{_REJECTION_REASON_MESSAGES[rejected.reason]}"
                    ),
                    detail=str(rejected),
                )
                return

        for host in staged.hosts.values():
            await host.start()

        task = FlowTask(staged.definition, redis_client=self._redis)
        self._runtimes[flow_id] = _FlowRuntime(
            task=task,
            ts_seconds=staged.ts_seconds,
            updated_at=flow.updated_at,
            conn_ids=staged.conn_ids,
            blocks=staged.blocks,
            hosts=staged.hosts,
            mpc_write_opc=staged.mpc_write_opc,
        )
        self._state.track(flow_id, task)
        await task.start(user=command.user)
        await publish_flow_deployed(self._redis, flow_id=flow_id, user=command.user)

        if old_runtime is not None:
            # Redeploy sobre um runtime anterior (parado ou em falha, nunca "running" — o
            # early-return acima cobre isso): a `StagedDefinition` nova é zerada (`reuse={}`),
            # então qualquer `MpcHost`/watchdog do runtime velho ficaria órfão sem isto —
            # falha (`comm_failure`) não desarma nem para host nenhum (ADR-009), então é
            # aqui, não lá, que o processo do worker antigo finalmente morre.
            for block_id in list(old_runtime.mpc_watchdogs):
                await self._cancel_watchdog(old_runtime, block_id)
            for host in old_runtime.hosts.values():
                await host.stop()

    async def _stop(self, command: FlowCommand) -> None:
        flow_id = command.flow_id
        runtime = self._runtimes.get(flow_id)
        if runtime is None or runtime.task.state != "running":
            # Parado, em falha ou desconhecido: nada a materializar, nenhum evento.
            return
        await self._shutdown_mpc(runtime, flow_id=flow_id)
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
    # Comandos do bloco MPC (spec F4 §4.4/§4.8, plano F4b tarefa 2.2)
    # ----------------------------------------------------------------------------------

    async def _mpc_command(self, command: FlowCommand) -> None:
        flow_id = command.flow_id
        runtime = self._runtimes.get(flow_id)
        if runtime is None or runtime.task.state != "running":
            logger.info(
                "Comando '%s' do flow %s: flow não está rodando; ignorado", command.cmd, flow_id
            )
            return
        block_id = command.args.get("block_id")
        entry = runtime.blocks.get(block_id) if isinstance(block_id, str) else None
        if entry is None or not isinstance(entry[1], MpcBlock):
            logger.info(
                "Comando '%s' do flow %s: bloco '%s' não existe; ignorado",
                command.cmd,
                flow_id,
                block_id,
            )
            return
        block = entry[1]
        axis = command.args.get("axis")
        value = command.args.get("value")

        if (
            command.cmd == "mpc_mode"
            and axis == "man_auto"
            and value == "auto"
            and block.local_remote == "remote"
        ):
            # Gate de MAN->AUTO (spec §4.4): host pronto + entradas quentes+válidas. Só
            # existe em REMOTO (ADR-010) — em LOCAL o comando é ignorado de verdade
            # (`MpcBlock._command_mode` já faz isso), nunca um `mpc_arm_failed`. O bloco
            # só EXPÕE o motivo (predicado puro, tarefa 2.1/2.2); quem decide não
            # materializar o comando é o supervisor, ANTES de rotear para `command()`.
            reason = block.auto_arm_blocked_reason()
            if reason is not None:
                await publish_event(
                    self._redis,
                    severity="warning",
                    origin=mpc_block_origin(flow_id, block_id),
                    message=f"MPC '{block_id}': armar 'man_auto' falhou ({reason})",
                    kind=KIND_MPC_ARM_FAILED,
                    payload={"axis": "man_auto", "reason": reason},
                )
                return

        if command.cmd == "mpc_mode" and axis == "local_remote" and value in ("local", "remote"):
            await self._transition_local_remote(
                runtime, flow_id, block_id, block, value, command.user
            )
            return

        await block.command(command.cmd, command.args, command.user)

    async def _transition_local_remote(
        self,
        runtime: _FlowRuntime,
        flow_id: int,
        block_id: str,
        block: MpcBlock,
        value: str,
        user: str | None,
    ) -> None:
        """LOCAL<->REMOTO (spec §4.4): materializa no bloco primeiro (idempotência, MAN e
        MV manual := vigente já são regra do bloco), e só se algo REALMENTE mudou escreve
        `mode_cmd`/arma o watchdog de confirmação — comando repetido não reescreve o PID
        nem reinicia a janela de confirmação."""
        await self._cancel_watchdog(runtime, block_id)
        was_remote = block.local_remote == "remote"
        await block.command("mpc_mode", {"axis": "local_remote", "value": value}, user)
        now_remote = block.local_remote == "remote"
        if now_remote == was_remote:
            return
        await write_mode_cmd(
            runtime.mpc_write_opc,
            block.pid_bindings,
            "target" if now_remote else "auto",
            source=mpc_block_origin(flow_id, block_id),
        )
        if now_remote:
            self._start_watchdog(runtime, flow_id, block_id, block)

    def _start_watchdog(
        self, runtime: _FlowRuntime, flow_id: int, block_id: str, block: MpcBlock
    ) -> None:
        async def on_no_confirm() -> None:
            await self._auto_revert(
                runtime,
                flow_id,
                block_id,
                block,
                kind=KIND_MPC_ARM_FAILED,
                payload={"axis": "local_remote", "reason": "no_confirm"},
                severity="warning",
                message=f"MPC '{block_id}': armar 'local_remote' falhou (no_confirm)",
            )

        async def on_shed() -> None:
            await self._auto_revert(
                runtime,
                flow_id,
                block_id,
                block,
                kind=KIND_MPC_SHED,
                payload={},
                severity="alarm",
                message=f"MPC '{block_id}': shed para LOCAL — mode_read divergente do PID",
            )

        task = asyncio.create_task(
            watch_arm(
                block=block, snapshot=self._snapshot, on_no_confirm=on_no_confirm, on_shed=on_shed
            ),
            name=f"mpc-watchdog-{flow_id}-{block_id}",
        )
        runtime.mpc_watchdogs[block_id] = task

    async def _cancel_watchdog(self, runtime: _FlowRuntime, block_id: str) -> None:
        task = runtime.mpc_watchdogs.pop(block_id, None)
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _auto_revert(
        self,
        runtime: _FlowRuntime,
        flow_id: int,
        block_id: str,
        block: MpcBlock,
        *,
        kind: str,
        payload: dict[str, Any],
        severity: str,
        message: str,
    ) -> None:
        """Reversão automática (`no_confirm`/`mpc_shed`) disparada pelo próprio watchdog —
        `asyncio.current_task()` confere que ninguém já cancelou/substituiu esta task
        (comando concorrente do usuário sempre cancela ANTES de mexer no bloco de novo, spec
        `_transition_local_remote`), então não precisa do lock do supervisor: por construção,
        chegar aqui significa que esta é ainda a task ativa para este bloco."""
        current = asyncio.current_task()
        if runtime.mpc_watchdogs.get(block_id) is not current:
            return
        runtime.mpc_watchdogs.pop(block_id, None)
        if block.local_remote != "remote":
            return
        await block.command("mpc_mode", {"axis": "local_remote", "value": "local"}, None)
        await write_mode_cmd(
            runtime.mpc_write_opc,
            block.pid_bindings,
            "auto",
            source=mpc_block_origin(flow_id, block_id),
        )
        await publish_event(
            self._redis,
            severity=severity,
            origin=mpc_block_origin(flow_id, block_id),
            message=message,
            kind=kind,
            payload=payload,
        )

    async def _shutdown_mpc(self, runtime: _FlowRuntime, *, flow_id: int) -> None:
        """Devolve o PID (`mode_cmd=auto`) de todo bloco MPC armado e mata os workers da
        tarefa — chamado ANTES de `task.stop()` em todo caminho de parada exceto
        `on_comm_failure` (ADR-009: a conexão pode estar caída lá, sem como escrever; o
        watchdog do lado do PLC devolve, documentado no relatório da tarefa 2.2)."""
        for block_id, (_, block) in list(runtime.blocks.items()):
            if not isinstance(block, MpcBlock):
                continue
            await self._cancel_watchdog(runtime, block_id)
            if block.local_remote == "remote":
                await block.command(
                    "mpc_mode", {"axis": "local_remote", "value": "local"}, SYSTEM_ACTOR
                )
                await write_mode_cmd(
                    runtime.mpc_write_opc,
                    block.pid_bindings,
                    "auto",
                    source=mpc_block_origin(flow_id, block_id),
                )
        for host in runtime.hosts.values():
            await host.stop()

    # ----------------------------------------------------------------------------------
    # Hot-swap (spec §4.1, §4.7)
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
                reason=rejected.reason,
                message=(
                    f"Hot-swap do flow {flow.id} recusado: "
                    f"{_REJECTION_REASON_MESSAGES[rejected.reason]};"
                    " a definição em execução foi mantida"
                ),
                detail=str(rejected),
            )
            # Avança o watermark mesmo recusando: sem isso o poll repetiria o mesmo aviso a
            # cada 10 s enquanto o grafo continuasse inválido, virando alarme de fundo.
            runtime.updated_at = flow.updated_at
            return

        swapped_block_ids = await self._reconcile_mpc_hosts(runtime, staged, flow_id=flow.id)
        runtime.task.stage(staged.definition)
        runtime.ts_seconds = staged.ts_seconds
        runtime.conn_ids = staged.conn_ids
        runtime.blocks = staged.blocks
        runtime.hosts = staged.hosts
        runtime.mpc_write_opc = staged.mpc_write_opc
        runtime.updated_at = flow.updated_at
        # O evento sai só DEPOIS do runtime já refletir a troca (blocks/hosts atualizados):
        # publicar antes (dentro de `_reconcile_mpc_hosts`) deixava uma janela em que quem
        # reagisse ao `mpc_mode_changed{reason: hot_swap}` ainda veria o host/bloco velhos
        # em `self._runtimes` — achado desta tarefa, mesma classe de bug que `_publish_status`
        # já evita na F3 (acertar o estado ANTES de publicar).
        for block_id in swapped_block_ids:
            await publish_mpc_hot_swap(self._redis, flow_id=flow.id, block_id=block_id)

    async def _reconcile_mpc_hosts(
        self, runtime: _FlowRuntime, staged: StagedDefinition, *, flow_id: int
    ) -> list[str]:
        """Hot-swap de host por `MpcHost` (spec §4.7): bloco cujo config não mudou preserva
        o MESMO host (identidade de objeto, §4.1-3) — só quem mudou (ou saiu do grafo) ganha
        host novo e sheda o antigo a LOCAL antes de matar o processo velho. Devolve os
        `block_id` substituídos (config mudou, ainda presentes no grafo novo) — `_stage`
        publica `mpc_mode_changed{reason: hot_swap}` para eles só DEPOIS de já ter
        atualizado `runtime.blocks`/`runtime.hosts`, nunca aqui dentro."""
        old_hosts = runtime.hosts
        new_hosts = staged.hosts
        for block_id, host in new_hosts.items():
            if old_hosts.get(block_id) is not host:
                await host.start()
        swapped: list[str] = []
        for block_id, old_host in old_hosts.items():
            if new_hosts.get(block_id) is old_host:
                continue  # bloco não mudou: host e estado preservados (§4.1-3)
            await self._cancel_watchdog(runtime, block_id)
            old_entry = runtime.blocks.get(block_id)
            if old_entry is not None and isinstance(old_entry[1], MpcBlock):
                old_block = old_entry[1]
                if old_block.local_remote == "remote":
                    await write_mode_cmd(
                        runtime.mpc_write_opc,
                        old_block.pid_bindings,
                        "auto",
                        source=mpc_block_origin(flow_id, block_id),
                    )
                if block_id in new_hosts:  # substituído (config mudou), não removido do grafo
                    swapped.append(block_id)
            await old_host.stop()
        return swapped

    async def _build(
        self,
        session: AsyncSession,
        flow: Flow,
        *,
        reuse: Mapping[str, tuple[dict[str, Any], Block]],
    ) -> StagedDefinition:
        """`graph_json` + tags do projeto -> definição da 1.4. Levanta `_Rejected` se recusado."""
        try:
            graph = parse_graph(flow.graph_json)
        except GraphParseError as erro:
            raise _Rejected(erro.errors) from None
        tags = await project_tags(session, flow.project_id)
        # `Flow.ts_seconds` é Numeric(4,1) e chega como Decimal: `Decimal * float` levanta
        # TypeError na aritmética de fronteira (armadilha herdada da F1).
        ts_seconds = float(flow.ts_seconds)
        result = validate_graph(graph, tags, ts_seconds)
        if result.errors:
            raise _Rejected(result.errors)
        for aviso in result.warnings:
            logger.info("Flow %s: %s", flow.id, aviso)

        return build_definition(
            graph,
            tags,
            flow_id=flow.id,
            ts_seconds=ts_seconds,
            reuse=reuse,
            redis_client=self._redis,
            pool=self._pool,
            snapshot=self._snapshot,
            mpc_worker_target=self._mpc_worker_target,
        )

    # ----------------------------------------------------------------------------------
    # Contrato F2 §3.7 (spec §2.2-8)
    # ----------------------------------------------------------------------------------

    async def on_comm_failure(self, conn_id: int) -> None:
        """Derruba os flows cujo grafo referencia tag da conexão caída (RF-207).

        Os demais seguem intactos, e descongelar não retoma nada: retomada é só por deploy
        manual (ADR-017). Quem emite `flow_failed` é a própria `FlowTask` (tarefa 1.4).

        MPC (ADR-009): watchdog de armar/shed cancelado — sem conexão não há como confirmar
        nem shedar de verdade, e não há como escrever `mode_cmd=auto` (a conexão está
        caída); o watchdog do lado do PLC devolve o controle sozinho. O `MpcHost` (processo)
        fica vivo até o próximo `deploy`/`stop`/desligamento — matar processo não é reação a
        `comm_failure`.
        """
        async with self._lock:
            for flow_id, runtime in list(self._runtimes.items()):
                if runtime.task.state != "running" or conn_id not in runtime.conn_ids:
                    continue
                for block_id in list(runtime.mpc_watchdogs):
                    await self._cancel_watchdog(runtime, block_id)
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
            await self._shutdown_mpc(runtime, flow_id=flow_id)
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
        mostraria "Rodando" enquanto o `/health` mostra `flows={}`. Um flow já parado/em
        falha pode ainda ter `MpcHost` vivo (`comm_failure` não para host nenhum, ADR-009) —
        mata aqui, sem tentar devolver o PID (o flow não está mais rodando).
        """
        runtime = self._runtimes.get(flow_id)
        try:
            if runtime is not None:
                was_running = runtime.task.state == "running"
                if was_running:
                    await self._shutdown_mpc(runtime, flow_id=flow_id)
                else:
                    for host in runtime.hosts.values():
                        await host.stop()
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
