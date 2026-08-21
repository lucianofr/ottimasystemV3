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
    KIND_RELOAD_REJECTED,
    FlowCommand,
)
from ottima_core.flowgraph import FlowGraph, GraphParseError, TagRef, parse_graph, validate_graph
from ottima_core.models import Flow, Project
from ottima_core.script_pool import ScriptPool
from ottima_core.snapshot import ValueSnapshot
from ottima_core.tags import project_tags

from .blocks.base import Block
from .blocks.mpc import MpcBlock
from .definition import StagedDefinition, build_definition, carregar_sp_seeds
from .events import (
    ChannelListener,
    publish_flow_deployed,
    publish_flow_stopped,
    publish_mpc_hot_swap,
    publish_rejected,
)
from .mpc.host import MpcHost
from .mpc.worker import worker_main
from .partition import UNPARTITIONED, Partition
from .scheduler import FlowTask
from .state import RuntimeState
from .supervisor_mpc import MpcOrchestrator
from .supervisor_resume import ResumeOrchestrator, RetomadaPendente

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


def _parse_e_validar(
    graph_json: dict, tags: Mapping[int, TagRef], ts_seconds: float
) -> tuple[FlowGraph, list[str]]:
    """Parse + validação num passo só, para rodar inteiro fora do event loop dentro de um
    único `asyncio.to_thread` — mesmo padrão de `ottima_api.routers.flows._validar_grafo`
    (TD-002). Levanta `_Rejected` com todas as reprovações; puro e thread-safe, opera só
    sobre o `graph_json` e as tags já carregadas do banco.
    """
    try:
        graph = parse_graph(graph_json)
    except GraphParseError as erro:
        raise _Rejected(erro.errors) from None
    result = validate_graph(graph, tags, ts_seconds)
    if result.errors:
        raise _Rejected(result.errors)
    return graph, result.warnings


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
    mpc_boot_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    """Tasks de `MpcOrchestrator.start_host_background` (spec F5 §6.1, tarefa 4.1 F5a —
    F-1): `host.start()` roda em segundo plano, fora do lock; a referência mora aqui
    (mesmo idioma de `mpc_watchdogs` abaixo) para o event loop nunca segurar só a
    referência fraca de `asyncio.create_task` — `MpcHost.stop()` já espera o boot em voo
    por conta própria (`mpc/host.py`), então nada aqui precisa cancelar/aguardar por fora;
    é só o que evita a task desaparecer no meio."""
    mpc_stop_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    """Tasks de `MpcOrchestrator.stop_host_background` (spec F5 §6.3/§6.5, tarefa 4.2 F5a
    — F-1): `host.stop()` roda em segundo plano, fora do lock e fora do caminho síncrono
    de `flow.commands` — mesmo idioma/motivo de `mpc_boot_tasks` acima, mas para o
    desmonte (`Supervisor._stop`, `reconcile_mpc_hosts` do hot-swap) em vez do boot.
    `_teardown` aguarda o que sobrar aqui antes de considerar o flow desmontado, para o
    desligamento do serviço nunca abandonar um kill/join ainda em voo."""
    mpc_write_opc: Any = None
    """`write_opc` com `conn_id` já resolvido (`definition._make_write_opc`) — reusado para
    escrever `mode_cmd` fora do `step()` do bloco (transições §4.4/§4.5)."""
    mpc_watchdogs: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    """`block_id -> task` de `mpc_arming.watch_arm`, uma por bloco armado agora mesmo."""
    mpc_fail_watchdogs: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    """`block_id -> task` de `mpc_arming.watch_fail_actions` (RF-613) — mesmo ciclo de vida
    de `mpc_watchdogs`: toda saída de REMOTO cancela as duas (`cancel_watchdog`)."""


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
        partition: Partition = UNPARTITIONED,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._state = state
        self._snapshot = snapshot
        self._pool = pool
        self._poll_interval_s = poll_interval_s
        self._mpc_worker_target = mpc_worker_target
        self._partition = partition
        self._runtimes: dict[int, _FlowRuntime] = {}
        # Cola de orquestração MPC extraída do Supervisor (plano F4b tarefa 5.0, spec F4 §8
        # débito #6): mesmo `self._runtimes`, delegação interna — API pública inalterada.
        self._mpc = MpcOrchestrator(
            self._runtimes,
            redis_client,
            snapshot=snapshot,
            pool=pool,
            system_actor=SYSTEM_ACTOR,
        )
        # Nunca dois comandos (ou comando e watermark) mexendo no mesmo mapa em paralelo.
        self._lock = asyncio.Lock()
        # TD-005/ADR-025: retomada automática pós `comm_restored`. Mesmo `self._runtimes`
        # do `MpcOrchestrator` acima — delegação interna, API pública ganha só
        # `on_comm_restored`. Precisa do lock JÁ criado (linha acima) para o rearme nunca
        # prender um comando concorrente atrás de um `sleep` (ver `supervisor_resume.py`).
        self._resume = ResumeOrchestrator(
            self._runtimes,
            redis_client,
            session_factory,
            lock=self._lock,
            mpc=self._mpc,
            deploy_flow=self._deploy_flow,
            load_flow=self._load,
        )
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

    def mpc_health(self, flow_id: int) -> dict[str, dict]:
        """Delega a `MpcOrchestrator.mpc_health` (spec F4 §4.10, plano F4b tarefa 2.3/5.0)."""
        return self._mpc.mpc_health(flow_id)

    def script_pool_stats(self) -> dict:
        """Delega a `MpcOrchestrator.script_pool_stats` (débito 5, spec F4 §4.10/§8)."""
        return self._mpc.script_pool_stats()

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
        """Despacha um comando. Idempotente e nunca levanta (RNF-05).

        `flow.commands` é um canal só, então TODA partição recebe TODO comando: quem não é dono
        do flow sai aqui, sem log por comando (com N partições, N-1 delas descartariam cada
        comando e o log viraria ruído). É o único ponto de posse do runtime particionado —
        ADR-017 garante que nenhum outro caminho sobe flow, e o índice do processo é atribuído
        pelo pai (ver `partition.py`), então cada comando cai em exatamente um processo.
        """
        if not self._partition.owns(command.flow_id):
            return
        handlers = {
            "deploy": self._deploy,
            "stop": self._stop,
            "reload": self._reload,
            "mpc_mode": self._mpc.mpc_command,
            "mpc_sp": self._mpc.mpc_command,
            "mpc_mv": self._mpc.mpc_command,
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
        self._resume.descartar(flow_id)  # comando manual sempre vence (§2.2-8, RNF-05)
        runtime = self._runtimes.get(flow_id)
        if runtime is not None and runtime.task.state == "running":
            return  # no-op sem evento duplicado (RNF-05)
        await self._deploy_flow(flow_id, command.user)

    async def _deploy_flow(self, flow_id: int, user: str) -> _FlowRuntime | None:
        """Miolo do deploy — comum ao comando manual (`_deploy`) e à retomada automática
        pós `comm_restored` (TD-005/ADR-025, `ResumeOrchestrator._iniciar`). Devolve o
        `_FlowRuntime` novo, ou `None` se o deploy foi recusado (flow desconhecido, projeto
        inativo ou grafo inválido) — os dois chamadores decidem o que fazer com a recusa:
        `_deploy` só sai (o `deploy_rejected` já saiu daqui); a retomada mantém a entrada
        pendente para o próximo `comm_restored`.

        Rede de segurança de posse: este é o ÚNICO lugar que instancia `FlowTask`, e dois
        processos executando o mesmo flow significaria escrita duplicada na mesma tag OPC. Hoje
        os dois chamadores já são seguros (`_deploy` passa pelo filtro de `handle_command`, e a
        retomada só age sobre flows que ESTE processo derrubou), então o guard abaixo nunca
        dispara — é o que impede um terceiro chamador futuro de furar a posse em silêncio.
        """
        if not self._partition.owns(flow_id):
            logger.error(
                "Deploy do flow %s recusado: não pertence à partição %s. Caminho que ignora o "
                "filtro de posse — corrigir o chamador, não este guard.",
                flow_id,
                self._partition.label or "única",
            )
            return None
        old_runtime = self._runtimes.get(flow_id)
        async with self._session_factory() as session:
            row = await self._load(session, flow_id)
            if row is None:
                logger.info("Deploy de flow %s desconhecido; ignorado", flow_id)
                return None
            flow, project_active = row
            if not project_active:
                await self._reject(
                    KIND_DEPLOY_REJECTED,
                    flow_id=flow_id,
                    user=user,
                    reason=REASON_PROJECT_INACTIVE,
                    message=(f"Deploy do flow {flow_id} recusado: o projeto do flow não é o ativo"),
                    detail="ative o projeto do flow antes de executá-lo",
                )
                return None
            try:
                # Deploy nasce zerado: `state` de bloco zera ao parar (RF-512), então não há
                # o que preservar de uma execução anterior — exceção única: o SP do operador
                # volta como semente de `mpc_setpoints` (`carregar_sp_seeds` em `_build`).
                staged = await self._build(session, flow, reuse={})
            except _Rejected as rejected:
                await self._reject(
                    KIND_DEPLOY_REJECTED,
                    flow_id=flow_id,
                    user=user,
                    reason=rejected.reason,
                    message=(
                        f"Deploy do flow {flow_id} recusado: "
                        f"{_REJECTION_REASON_MESSAGES[rejected.reason]}"
                    ),
                    detail=str(rejected),
                )
                return None

        task = FlowTask(staged.definition, redis_client=self._redis)
        runtime = _FlowRuntime(
            task=task,
            ts_seconds=staged.ts_seconds,
            updated_at=flow.updated_at,
            conn_ids=staged.conn_ids,
            blocks=staged.blocks,
            hosts=staged.hosts,
            mpc_write_opc=staged.mpc_write_opc,
        )
        self._runtimes[flow_id] = runtime
        # F-1 (spec F5 §6.1, tarefa 4.1 F5a): `host.start()` sai do caminho síncrono do
        # lock global — estagia e retorna; o build (spawn + montagem do-mpc) roda em
        # segundo plano e o flow varre desde a 1a fronteira, publicando `building` (§6.2)
        # até o host ficar pronto.
        for block_id, host in staged.hosts.items():
            self._mpc.start_host_background(runtime, host, flow_id=flow_id, block_id=block_id)
        self._state.track(flow_id, task)
        await task.start(user=user)
        await publish_flow_deployed(self._redis, flow_id=flow_id, user=user)

        if old_runtime is not None:
            # Redeploy sobre um runtime anterior (parado ou em falha, nunca "running" — o
            # early-return de `_deploy` cobre isso; a retomada nunca vê "running" por
            # construção, `on_comm_failure` só cria pendência de flow que estava rodando e
            # acabou de cair): a `StagedDefinition` nova é zerada (`reuse={}`), então
            # qualquer `MpcHost`/watchdog do runtime velho ficaria órfão sem isto.
            # `revert_armed_mpc` (idempotente) devolve `mode_cmd=auto` se o bloco velho ainda
            # estiver armado REMOTO — achado 1 da revisão F4: sem isto, um redeploy logo após
            # uma falha interna (watermark ainda não passou) matava o worker antigo mas nunca
            # escrevia a devolução, travando o PID em `target` pra sempre (comm_failure não
            # conta: `fail()` já reseta o bloco pra LOCAL antes de chegar aqui, então o guard
            # por `local_remote` é no-op nesse caso).
            #
            # F6R-06 (spec F6 §5.2, débito F5 §8, tarefa 5.2): o `shutdown_mpc` síncrono
            # antigo mantinha `Supervisor._lock` preso pelo boot/kill/join real do worker
            # velho — mesma sequência de três passos que `_stop` já usa. A task destacada de
            # `stop_host_background` é registrada no `_FlowRuntime` NOVO (já publicado no
            # mapa algumas linhas acima), não no `old_runtime`: ele sai do mapa aqui mesmo, e
            # uma task pendurada nele ficaria órfã — `_teardown` (que aguarda `runtime.
            # mpc_stop_tasks` de propósito) voltaria a poder abandonar um kill em voo,
            # reabrindo o defeito que a spec F5 §6.5 fechou.
            await self._mpc.revert_armed_mpc(old_runtime, flow_id=flow_id)
            for block_id, host in self._mpc.detach_hosts(old_runtime).items():
                self._mpc.stop_host_background(runtime, host, flow_id=flow_id, block_id=block_id)
        return runtime

    async def _stop(self, command: FlowCommand) -> None:
        flow_id = command.flow_id
        self._resume.descartar(flow_id)  # comando manual sempre vence (§2.2-8, RNF-05)
        runtime = self._runtimes.get(flow_id)
        if runtime is None or runtime.task.state != "running":
            # Parado, em falha ou desconhecido: nada a materializar, nenhum evento.
            return
        await self._mpc.revert_armed_mpc(runtime, flow_id=flow_id)
        # F-1 (spec F5 §6.3/§6.5, tarefa 4.2 F5a): o host sai do mapa e o desmonte — que
        # pode esperar um build em voo até `_BOOT_TIMEOUT_S = 30s`, `mpc/host.py::stop` —
        # roda destacado. Sem isso o bloqueio que a tarefa 4.1 tirou do deploy só
        # migraria para o stop, no MESMO canal sequencial de `flow.commands` (docstring de
        # `MpcOrchestrator.stop_host_background`).
        for block_id, host in self._mpc.detach_hosts(runtime).items():
            self._mpc.stop_host_background(runtime, host, flow_id=flow_id, block_id=block_id)
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

        swapped_block_ids, swapped_bumpless_ids = await self._mpc.reconcile_mpc_hosts(
            runtime, staged, flow_id=flow.id
        )
        runtime.task.stage(staged.definition)
        runtime.ts_seconds = staged.ts_seconds
        runtime.conn_ids = staged.conn_ids
        runtime.blocks = staged.blocks
        runtime.hosts = staged.hosts
        runtime.mpc_write_opc = staged.mpc_write_opc
        runtime.updated_at = flow.updated_at
        # O evento sai só DEPOIS do runtime já refletir a troca (blocks/hosts atualizados):
        # publicar antes (dentro de `reconcile_mpc_hosts`) deixava uma janela em que quem
        # reagisse ao `mpc_mode_changed` ainda veria o host/bloco velhos em `self._runtimes`
        # — achado desta tarefa, mesma classe de bug que `_publish_status` já evita na F3
        # (acertar o estado ANTES de publicar). `swapped_bumpless_ids` (TD-006): o bloco já
        # nasceu transplantado — reason `hot_swap_bumpless`, nenhum PID foi tocado.
        for block_id in swapped_block_ids:
            await publish_mpc_hot_swap(self._redis, flow_id=flow.id, block_id=block_id)
        for block_id in swapped_bumpless_ids:
            await publish_mpc_hot_swap(
                self._redis, flow_id=flow.id, block_id=block_id, bumpless=True
            )

    async def _build(
        self,
        session: AsyncSession,
        flow: Flow,
        *,
        reuse: Mapping[str, tuple[dict[str, Any], Block]],
    ) -> StagedDefinition:
        """`graph_json` + tags do projeto -> definição da 1.4. Levanta `_Rejected` se recusado."""
        tags = await project_tags(session, flow.project_id)
        # `Flow.ts_seconds` é Numeric(4,1) e chega como Decimal: `Decimal * float` levanta
        # TypeError na aritmética de fronteira (armadilha herdada da F1).
        ts_seconds = float(flow.ts_seconds)
        # `parse_graph`/`validate_graph` são CPU-bound sobre dados já materializados (funções
        # puras, thread-safe); `await asyncio.to_thread(...)` devolve o event loop enquanto um
        # grafo grande valida — o `Supervisor._lock` de quem chama (`_pass`) continua
        # serializando comandos por design; o objetivo aqui é só `flow.status` das demais
        # tasks continuar publicando durante o deploy/hot-swap (TD-002).
        graph, warnings = await asyncio.to_thread(
            _parse_e_validar, flow.graph_json, tags, ts_seconds
        )
        for aviso in warnings:
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
            watchdog_enabled=flow.watchdog_enabled,
            mpc_worker_target=self._mpc_worker_target,
            sp_seeds=await carregar_sp_seeds(session, flow.id),
            session_factory=self._session_factory,
        )

    # ----------------------------------------------------------------------------------
    # Contrato F2 §3.7 (spec §2.2-8)
    # ----------------------------------------------------------------------------------

    async def on_comm_failure(self, conn_id: int, flow_id: int | None = None) -> None:
        """Derruba o(s) flow(s) afetados pela falha (RF-207 revisado, ADR-009).

        Dois caminhos, conforme `flow_id`:
        - `None` (falha de SESSÃO — `session_lost`/`connect_failed`/`cert_*`): derruba
          TODOS os flows cujo grafo referencia tag da conexão caída (comportamento
          herdado, `_conn_ids`).
        - Dado (falha do WATCHDOG de UM flow — `watchdog_timeout`, ADR-009 revisado):
          derruba SÓ esse flow. Os demais flows da mesma conexão, com watchdog próprio
          ainda vivo, seguem intactos — é exatamente o isolamento que motivou mover o
          watchdog da conexão para o flow (uma conexão pode ser um gateway com vários
          PLCs atrás dela).

        Descongelar não retoma nada: retomada é só por deploy manual (ADR-017) ou pelo
        `ResumeOrchestrator` (TD-005/ADR-025). Quem emite `flow_failed` é a própria
        `FlowTask` (tarefa 1.4).

        MPC (ADR-009): watchdog de armar/shed cancelado — sem conexão/flow não há como
        confirmar nem shedar de verdade, e não há como escrever `mode_cmd=auto`; o
        watchdog do lado do PLC devolve o controle sozinho. O `MpcHost` (processo) fica
        vivo até o próximo `deploy`/`stop`/desligamento — matar processo não é reação a
        `comm_failure`.
        """
        async with self._lock:
            if flow_id is not None:
                runtime = self._runtimes.get(flow_id)
                if runtime is not None and runtime.task.state == "running":
                    await self._fail_flow(flow_id, runtime, conn_id)
                return
            for fid, runtime in list(self._runtimes.items()):
                if runtime.task.state != "running" or conn_id not in runtime.conn_ids:
                    continue
                await self._fail_flow(fid, runtime, conn_id)

    async def _fail_flow(self, flow_id: int, runtime: _FlowRuntime, conn_id: int) -> None:
        """Corpo isolado de `on_comm_failure` para um flow — reusado pelos dois caminhos
        (sessão inteira ou watchdog de um flow só)."""
        for block_id in list(runtime.mpc_watchdogs):
            await self._mpc.cancel_watchdog(runtime, block_id)
        # Snapshot ANTES de `fail()` (TD-005/ADR-025): a retomada automática pós
        # `comm_restored` precisa dos modos/últimos valores/SPs de cada bloco MPC de
        # antes da queda — depois de `fail()` eles já foram zerados por
        # `_reset_blocks()` (`FlowTask.fail`). Vazio quando o flow não tem bloco `mpc`
        # nenhum: o redeploy automático roda igual, só não há modo/SP nenhum para
        # restaurar depois.
        estados = {
            block_id: block.snapshot_estado()
            for block_id, (_, block) in runtime.blocks.items()
            if isinstance(block, MpcBlock)
        }
        self._resume.pendentes[flow_id] = RetomadaPendente(conn_id=conn_id, estados=estados)
        try:
            await runtime.task.fail(reason=REASON_COMM_FAILURE)
        except Exception:
            # Isolado por flow: um que falhe ao cair não pode poupar os seguintes.
            logger.exception(
                "Falha ao derrubar o flow %s por queda da conexão %s", flow_id, conn_id
            )

    async def on_comm_restored(self, conn_id: int, flow_id: int | None = None) -> None:
        """Retomada automática completa pós `comm_restored` (TD-005, ADR-025) — delega a
        `ResumeOrchestrator`, que guarda o próprio estado de pendências (`self._resume.
        pendentes`, populado por `on_comm_failure` acima). `flow_id` (ADR-009 revisado)
        restringe a retomada a ESSE flow; ausente, retoma todos pendentes na conexão."""
        await self._resume.on_comm_restored(conn_id, flow_id)

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
        """Uma passada sobre os flows **rodando** + a devolução de PID órfã (achado 1 da
        revisão F4, `_handback_failed_mpc`). Absorve toda exceção.

        O domínio do reconcile de banco é só o conjunto de flows rodando, e é por
        construção que ela nunca inicia flow nenhum (contrato 1 / ADR-017): não existe
        caminho daqui para `start()`. A devolução de PID roda pra QUALQUER flow no mapa,
        rodando ou não — só ela cobre o flow que caiu em `failed` sem passar pelo
        supervisor.
        """
        async with self._lock:
            await self._handback_failed_mpc()
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

    async def _handback_failed_mpc(self) -> None:
        """Achado 1 da revisão F4: `FlowTask` pode ir a `failed` por exceção não tratada em
        QUALQUER bloco (scheduler.py `_handle_loop_failure`) sem passar pelo supervisor
        nenhuma vez — nem watchdog cancelado, nem `mode_cmd` devolvido; um MPC armado
        REMOTO fica esquecido, travando o PID no PLC em `target` pra sempre.

        Só entra quem tem watchdog ainda vivo no `_FlowRuntime`: toda saída controlada de
        REMOTO (comando explícito, `_stop`/`_force_stop`/`_teardown`, hot-swap,
        `on_comm_failure`) já cancela o watchdog ANTES de deixar de rodar — sobreviver até
        aqui com watchdog em pé só acontece nesta falha interna, não anunciada.
        `revert_armed_mpc`/`MpcHost.stop()` são idempotentes: repetir a cada passada até o
        flow sumir do mapa (redeploy) nunca escreve `mode_cmd` de novo nem tenta reparar um
        host que já saiu de `runtime.hosts`.

        F6R-06 (spec F6 §5.2, débito F5 §8, tarefa 5.2): mesma sequência de três passos que
        `_stop` já usa no lugar do `shutdown_mpc` síncrono — esperar o boot/kill/join real
        do worker aqui prendia `self._lock` (a mesma tomada de `_pass`) pelo mesmo tempo
        que um comando concorrente de QUALQUER outro flow levaria para ser processado."""
        for flow_id, runtime in list(self._runtimes.items()):
            if runtime.task.state == "failed" and runtime.mpc_watchdogs:
                await self._mpc.revert_armed_mpc(runtime, flow_id=flow_id)
                for block_id, host in self._mpc.detach_hosts(runtime).items():
                    self._mpc.stop_host_background(
                        runtime, host, flow_id=flow_id, block_id=block_id
                    )

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
        """Parada sem comando de usuário atrás: o `reason` carrega a causa, o `user` não
        existe. F6R-06 (spec F6 §5.2, débito F5 §8, tarefa 5.2): mesma sequência de três
        passos que `_stop` já usa no lugar do `shutdown_mpc` síncrono —
        `on_project_activated`/`_reconcile_flow` chamam este método SOB `self._lock`;
        esperar o kill/join real do worker ali prendia o lock pelo mesmo tempo do
        boot/kill (até `_BOOT_TIMEOUT_S`, `mpc/host.py::stop`)."""
        runtime = self._runtimes.get(flow_id)
        if runtime is None or runtime.task.state != "running":
            return
        try:
            await self._mpc.revert_armed_mpc(runtime, flow_id=flow_id)
            for block_id, host in self._mpc.detach_hosts(runtime).items():
                self._mpc.stop_host_background(runtime, host, flow_id=flow_id, block_id=block_id)
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
        mostraria "Rodando" enquanto o `/health` mostra `flows={}`. `shutdown_mpc` roda pra
        QUALQUER runtime, rodando ou não (achado 1 da revisão F4): um flow já parado/em
        falha pode ainda ter `MpcHost` vivo (`comm_failure` não para host nenhum, ADR-009)
        e/ou watchdog esquecido de uma falha interna que o watermark ainda não alcançou —
        mata o host e devolve o PID aqui, idempotente (no-op se já tratado antes)."""
        runtime = self._runtimes.get(flow_id)
        try:
            if runtime is not None:
                was_running = runtime.task.state == "running"
                await self._mpc.shutdown_mpc(runtime, flow_id=flow_id)
                if runtime.mpc_stop_tasks:
                    # Desligamento do serviço: espera até o fim qualquer desmonte de host
                    # que um `_stop` anterior tenha destacado (`stop_host_background`) e
                    # ainda estivesse em voo — sem isso o processo do worker poderia
                    # sobreviver ao `Supervisor.stop()` (spec F5 §6.5, tarefa 4.2 F5a).
                    await asyncio.gather(*runtime.mpc_stop_tasks, return_exceptions=True)
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
