"""Cola de orquestração dos blocos `mpc` de um flow (spec F4 §4.4/§4.5/§4.7/§4.8/§4.10).

Extraído do `Supervisor` na tarefa 5.0 do plano F4b (débito #6, spec F4 §8): comandos
`mpc_mode`/`mpc_sp`/`mpc_mv`, o watchdog de confirmação/shed e sua reversão automática — tudo
nascido nas tarefas 2.2/2.3 — e o hot-swap de `MpcHost` por bloco `mpc`. `Supervisor` guarda a
instância (mesmo `_runtimes`) e delega; a API pública dele não muda.

`mpc_arming.watch_arm` continua módulo à parte (tarefa 2.1) — este módulo só o consome.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from redis.asyncio import Redis

from ottima_core.bus import KIND_MPC_ARM_FAILED, KIND_MPC_SHED, FlowCommand, publish_event

from .blocks.mpc import MpcBlock
from .definition import StagedDefinition
from .events import mpc_block_origin
from .mpc_arming import watch_arm, write_mode_cmd
from .script_pool import ScriptPool
from .snapshot import ValueSnapshot

if TYPE_CHECKING:
    from .supervisor import _FlowRuntime

logger = logging.getLogger(__name__)


class MpcOrchestrator:
    """Comandos, watchdog e hot-swap dos blocos `mpc` de um `_FlowRuntime` — ver `Supervisor`."""

    def __init__(
        self,
        runtimes: dict[int, _FlowRuntime],
        redis_client: Redis,
        *,
        snapshot: ValueSnapshot,
        pool: ScriptPool,
        system_actor: str,
    ) -> None:
        self._runtimes = runtimes
        self._redis = redis_client
        self._snapshot = snapshot
        self._pool = pool
        self._system_actor = system_actor

    def mpc_health(self, flow_id: int) -> dict[str, dict]:
        """`block_id -> MpcBlock.health()` do flow (spec F4 §4.10, plano F4b tarefa 2.3).

        Vazio se o flow não existe ou não tem bloco `mpc` — o `/health` não distingue as
        duas causas, igual à propriedade `flows` do `Supervisor`.
        """
        runtime = self._runtimes.get(flow_id)
        if runtime is None:
            return {}
        return {
            block_id: block.health()
            for block_id, (_, block) in runtime.blocks.items()
            if isinstance(block, MpcBlock)
        }

    def script_pool_stats(self) -> dict:
        """`ScriptPool.stats()` (F4a tarefa 0.6) para o `/health` (débito 5, spec F4 §4.10/§8)."""
        return self._pool.stats()

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
        chegar aqui significa que esta é ainda a task ativa para este bloco.

        Achado da revisão 1: esse guard só cobre REENTRÂNCIA da mesma task, não a JANELA
        entre `block.command(...)` (que já solta o watchdog do dict, síncrono) e o resto
        deste corpo — um `mpc_mode` novo pode chegar, ver o bloco em LOCAL, e rearmar
        (`mode_cmd=target`) enquanto este `await` de I/O ainda está em voo. Sem a
        reconferência abaixo, a escrita de `mode_cmd=auto` que vem a seguir sobrescreveria
        esse rearme fresco com um comando obsoleto — daí o segundo `if`."""
        current = asyncio.current_task()
        if runtime.mpc_watchdogs.get(block_id) is not current:
            return
        runtime.mpc_watchdogs.pop(block_id, None)
        if block.local_remote != "remote":
            return
        await block.command("mpc_mode", {"axis": "local_remote", "value": "local"}, None)
        if block.local_remote != "local":
            # Rearmado por um comando concorrente enquanto o `await` acima estava em voo:
            # esse comando novo já escreveu seu próprio `mode_cmd`/iniciou seu próprio
            # watchdog — nada a fazer aqui, e sobretudo nada a SOBRESCREVER.
            return
        try:
            await write_mode_cmd(
                runtime.mpc_write_opc,
                block.pid_bindings,
                "auto",
                source=mpc_block_origin(flow_id, block_id),
            )
        except Exception:
            # O bloco já está LOCAL (o `command()` acima teve sucesso), mas o PID real pode
            # continuar armado em `target` no PLC — isso é dessincronismo silencioso se
            # ninguém souber. Reporta explicitamente em vez de deixar o `mpc_arm_failed`/
            # `mpc_shed` normal sair como se a devolução tivesse funcionado.
            logger.exception(
                "MPC '%s': falha ao escrever mode_cmd=auto na reversão automática (%s) — "
                "bloco já está LOCAL mas o PID pode continuar armado em target no PLC",
                block_id,
                kind,
            )
            await publish_event(
                self._redis,
                severity="alarm",
                origin=mpc_block_origin(flow_id, block_id),
                message=(
                    f"MPC '{block_id}': dessincronismo — bloco voltou a LOCAL mas a escrita "
                    "de mode_cmd=auto falhou; confira o PID manualmente"
                ),
                kind=kind,
                payload={**payload, "write_failed": True},
            )
            return
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
                    "mpc_mode", {"axis": "local_remote", "value": "local"}, self._system_actor
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
