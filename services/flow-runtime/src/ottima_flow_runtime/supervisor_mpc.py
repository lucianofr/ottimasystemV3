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

from ottima_core.bus import (
    KIND_MPC_ARM_FAILED,
    KIND_MPC_FAIL_ACTION_TRIGGERED,
    KIND_MPC_SHED,
    FlowCommand,
    publish_event,
)

from .blocks.mpc import MpcBlock
from .definition import StagedDefinition
from .events import mpc_block_origin
from .mpc.host import MpcHost
from .mpc_arming import watch_arm, watch_fail_actions, write_mode_cmd
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

    async def mpc_command(self, command: FlowCommand) -> None:
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
        nem reinicia a janela de confirmação.

        Achado 2 da revisão F4: armar REMOTO só passava pelo predicado que já gateava
        MAN->AUTO (`auto_arm_blocked_reason()`: host pronto + entradas quentes e válidas +
        readback de todo `pid`) NA transição de sub-modo — a de eixo `local_remote` não
        checava nada. Armar com entrada fria escrevia `mode_cmd=target` na hora, mas
        `MpcBlock.step()` sai cedo no `has_cold_input` ANTES de atualizar `_mv_last`; o MAN
        manual congelava em `initial_value` até a entrada esquentar — e aí saltava pro
        valor real (PRD §8-F4). Gate aqui, ANTES de materializar: sem isso, `mpc_arm_failed`
        sai e a transição nem acontece — o bloco fica LOCAL."""
        if value == "remote" and block.local_remote != "remote":
            reason = block.auto_arm_blocked_reason()
            if reason is not None:
                await publish_event(
                    self._redis,
                    severity="warning",
                    origin=mpc_block_origin(flow_id, block_id),
                    message=f"MPC '{block_id}': armar 'local_remote' falhou ({reason})",
                    kind=KIND_MPC_ARM_FAILED,
                    payload={"axis": "local_remote", "reason": reason},
                )
                return
        await self.cancel_watchdog(runtime, block_id)
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
            local_shed_modes=block.local_shed_modes,
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
                # ADR-028: o shed deixou de ser "algum mode_read divergiu" e passou a ser
                # "nenhuma MV disponível" (divergência parcial vira modo degradado) — a
                # mensagem acompanha o que de fato aconteceu.
                message=(
                    f"MPC '{block_id}': shed para LOCAL — nenhuma MV disponível "
                    "(fora de RCAS ou sem leitura confiável)"
                ),
            )

        async def on_fail_action(var_id: str, acao: str, motivo: str) -> None:
            # O evento sai ANTES da ação (RF-613): se a ação falhar, o rastro do disparo
            # já existe no log de eventos.
            await publish_event(
                self._redis,
                severity="warning",
                origin=mpc_block_origin(flow_id, block_id),
                message=(
                    f"MPC '{block_id}': fail action de '{var_id}' disparada ({acao}; {motivo})"
                ),
                kind=KIND_MPC_FAIL_ACTION_TRIGGERED,
                payload={"var_id": var_id, "action": acao, "reason": motivo},
            )
            if acao == "manual":
                # Mesmo eixo do comando do operador (§4.8) — idempotente se já em MAN.
                await block.command("mpc_mode", {"axis": "man_auto", "value": "man"}, None)
            elif acao == "shed_local":
                # MESMA rotina do shed global (REMOTO→LOCAL + devolução do PID +
                # KIND_MPC_SHED), com a razão distinta no payload.
                await self._auto_revert(
                    runtime,
                    flow_id,
                    block_id,
                    block,
                    kind=KIND_MPC_SHED,
                    payload={"reason": "fail_action", "var_id": var_id},
                    severity="alarm",
                    message=(
                        f"MPC '{block_id}': shed para LOCAL por fail action de "
                        f"'{var_id}' ({motivo})"
                    ),
                )

        task = asyncio.create_task(
            watch_arm(
                block=block, snapshot=self._snapshot, on_no_confirm=on_no_confirm, on_shed=on_shed
            ),
            name=f"mpc-watchdog-{flow_id}-{block_id}",
        )
        runtime.mpc_watchdogs[block_id] = task
        fail_task = asyncio.create_task(
            watch_fail_actions(block=block, on_fail_action=on_fail_action),
            name=f"mpc-fail-actions-{flow_id}-{block_id}",
        )
        runtime.mpc_fail_watchdogs[block_id] = fail_task

    async def cancel_watchdog(self, runtime: _FlowRuntime, block_id: str) -> None:
        for mapping in (runtime.mpc_watchdogs, runtime.mpc_fail_watchdogs):
            task = mapping.pop(block_id, None)
            if task is None:
                continue
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
        if (
            runtime.mpc_watchdogs.get(block_id) is not current
            and runtime.mpc_fail_watchdogs.get(block_id) is not current
        ):
            return
        # A task que disparou sai do registro e a IRMÃ (arm-watchdog ou fail-watchdog) é
        # cancelada: uma reversão só, sem o outro vigia disparar em cima de bloco já LOCAL.
        for mapping in (runtime.mpc_watchdogs, runtime.mpc_fail_watchdogs):
            sibling = mapping.pop(block_id, None)
            if sibling is not None and sibling is not current:
                sibling.cancel()
                with suppress(asyncio.CancelledError):
                    await sibling
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
                local_shed_modes=block.local_shed_modes,
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

    # ----------------------------------------------------------------------------------
    # Ciclo de vida do host MPC (spec F5 §6.1, tarefa 4.1 F5a — F-1: boot assíncrono)
    # ----------------------------------------------------------------------------------

    def start_host_background(
        self, runtime: _FlowRuntime, host: MpcHost, *, flow_id: int, block_id: str
    ) -> None:
        """Sobe `host.start()` como task de fundo, FORA do caminho síncrono do lock global
        do supervisor: quem chama (`Supervisor._deploy`/`reconcile_mpc_hosts`, os DOIS
        caminhos que montam `MpcHost`, spec F5 §6.1) estagia e retorna sem pagar o build
        (spawn + montagem do-mpc) — o flow varre desde a 1a fronteira, publicando
        `building` (spec F5 §6.2, `blocks/mpc.py::_build_state`) até o host ficar pronto.

        A task entra em `runtime.mpc_boot_tasks` (mesmo idioma de `mpc_watchdogs` logo
        abaixo, e do `self._background` interno do próprio `MpcHost`): sem guardar a
        referência o event loop só segura a fraca de `asyncio.create_task`, que pode sumir
        no meio (docs do stdlib). `MpcHost.stop()` já espera sozinho o boot em voo antes de
        desligar o processo (`mpc/host.py::stop`), então nada aqui precisa cancelar ou
        aguardar essa task por fora.

        `host.start()` não levanta pelo caminho normal (handshake ausente/atrasado vira log
        + `ready` permanece `False`, `mpc/host.py::_spawn_and_wait_ready`) — mas
        `_spawn_worker` (`mpc/host.py::_spawn_worker`, `Pipe`/`Process.start()`) não tem
        `try/except`: uma falha rara aí (recursos do SO esgotados etc.) propaga até esta
        task. Como ninguém a `await`, ela nunca seria observada — "Task exception was never
        retrieved" sem `flow_id`/`block_id` nenhum (achado do fix round 1). O callback
        abaixo observa `task.exception()` e loga com contexto; o bloco segue em `building`
        para sempre nesse caso (mesmo destino documentado de um handshake falho — sem laço
        de respawn automático, `mpc/host.py::_spawn_and_wait_ready`), só que agora com
        sinal operacional em vez de silêncio."""

        def _log_se_falhou(task: asyncio.Task[None]) -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.error(
                    "Boot do worker MPC do flow %s / bloco '%s' falhou com exceção não "
                    "tratada — host segue indisponível (building nunca alcança idle/ok "
                    "até uma intervenção externa)",
                    flow_id,
                    block_id,
                    exc_info=exc,
                )

        task = asyncio.get_running_loop().create_task(host.start())
        runtime.mpc_boot_tasks.add(task)
        task.add_done_callback(runtime.mpc_boot_tasks.discard)
        task.add_done_callback(_log_se_falhou)

    def detach_hosts(self, runtime: _FlowRuntime) -> dict[str, MpcHost]:
        """Esvazia `runtime.hosts` e devolve o que havia — spec F5 §6.3 (tarefa 4.2 F5a —
        F-1): "desmonte destacado com o `MpcHost` já removido do mapa". Chamado ANTES de
        `stop_host_background`: com o host já fora do mapa, nenhum comando novo para o
        MESMO flow (nem um `_teardown`/redeploy subsequente, que passa por `shutdown_mpc`
        de sempre) o encontra e tenta redesmontá-lo — `MpcHost.stop()` já é idempotente
        (`mpc/host.py`), mas o mapa vazio deixa `runtime.hosts` refletir a verdade: nenhum
        host desta chamada de `stop` segue "gerenciado" pelo supervisor."""
        hosts = dict(runtime.hosts)
        runtime.hosts.clear()
        return hosts

    def stop_host_background(
        self, runtime: _FlowRuntime, host: MpcHost, *, flow_id: int, block_id: str
    ) -> None:
        """Desmonta `host` como task de fundo, FORA do caminho síncrono de quem chama —
        spec F5 §6.3/§6.5 (tarefa 4.2 F5a — F-1). `MpcHost.stop()` espera o boot em voo
        até `_BOOT_TIMEOUT_S = 30s` antes de matar/juntar o processo (`mpc/host.py::stop`,
        comportamento pré-existente, intocado por esta tarefa): sem destacar essa espera,
        o bloqueio que a tarefa 4.1 tirou do deploy só MIGRARIA para quem chama esta
        função (`Supervisor._stop`, `reconcile_mpc_hosts` do hot-swap) — o canal
        `flow.commands` tem um único consumidor sequencial (mesma nota de
        `start_host_background` acima): um `stop`/`reload` que esperasse aqui de forma
        síncrona atrasaria o PRÓXIMO comando de QUALQUER flow, não só deste.

        `host` já saiu do mapa (`detach_hosts`, responsabilidade de quem chama esta
        função, ANTES desta task nascer): nada mais disputa por ele enquanto desmonta. A
        task entra em `runtime.mpc_stop_tasks` (mesmo idioma/motivo de `mpc_boot_tasks`:
        sem guardar a referência o event loop só segura a fraca de `asyncio.create_task`,
        que pode sumir no meio)."""

        def _log_se_falhou(task: asyncio.Task[None]) -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.error(
                    "Desmonte do worker MPC do flow %s / bloco '%s' falhou com exceção não tratada",
                    flow_id,
                    block_id,
                    exc_info=exc,
                )

        task = asyncio.get_running_loop().create_task(host.stop())
        runtime.mpc_stop_tasks.add(task)
        task.add_done_callback(runtime.mpc_stop_tasks.discard)
        task.add_done_callback(_log_se_falhou)

    async def revert_armed_mpc(self, runtime: _FlowRuntime, *, flow_id: int) -> None:
        """Devolve o PID (`mode_cmd=auto`) de todo bloco MPC armado do runtime — metade do
        antigo `shutdown_mpc` que NÃO espera processo nenhum (spec F5 §6.3, tarefa 4.2
        F5a — F-1): extraída para `Supervisor._stop` poder terminar de devolver o PID e só
        DEPOIS desmontar o(s) host(s) em segundo plano (`stop_host_background`), sem
        segurar quem chama pelo build/kill/join do processo. Idempotente (guarda por
        `block.local_remote`, mesma garantia do `shutdown_mpc` original)."""
        for block_id, (_, block) in list(runtime.blocks.items()):
            if not isinstance(block, MpcBlock):
                continue
            await self.cancel_watchdog(runtime, block_id)
            if block.local_remote == "remote":
                await block.command(
                    "mpc_mode", {"axis": "local_remote", "value": "local"}, self._system_actor
                )
                await write_mode_cmd(
                    runtime.mpc_write_opc,
                    block.pid_bindings,
                    "auto",
                    source=mpc_block_origin(flow_id, block_id),
                    local_shed_modes=block.local_shed_modes,
                )

    async def shutdown_mpc(self, runtime: _FlowRuntime, *, flow_id: int) -> None:
        """Devolve o PID de todo bloco MPC armado (`revert_armed_mpc`) e mata os workers
        da tarefa, de forma SÍNCRONA — usado SÓ por `Supervisor._teardown` (spec F5 §6.5),
        que precisa do processo realmente morto antes de considerar o flow desmontado e
        não roda sob `Supervisor._lock` (chamado por `Supervisor.stop()`, fora do canal
        sequencial de `flow.commands`), então esperar aqui não bloqueia comando nenhum.

        F6R-06 (spec F6 §5.2, débito F5 §8, tarefa 5.2): `_deploy` (redeploy sobre o
        `old_runtime`), `_handback_failed_mpc` e `_force_stop` usavam esta função SOB o
        lock — os três passaram para a variante destacada (`revert_armed_mpc` +
        `detach_hosts` + `stop_host_background`, mesma sequência de `Supervisor._stop`);
        `shutdown_mpc` sobrevive só para `_teardown`.

        Idempotente: repetir numa `_FlowRuntime` já tratada não escreve `mode_cmd` de novo
        nem falha ao re-parar host (`MpcHost.stop()` já é idempotente) — é o que deixa o
        supervisor chamar de novo sem se importar se já rodou antes (achado 1 da revisão
        F4: falha interna do flow sem handback anunciado, `_handback_failed_mpc`)."""
        await self.revert_armed_mpc(runtime, flow_id=flow_id)
        for host in runtime.hosts.values():
            await host.stop()

    # ----------------------------------------------------------------------------------
    # Hot-swap (spec §4.1, §4.7)
    # ----------------------------------------------------------------------------------

    async def reconcile_mpc_hosts(
        self, runtime: _FlowRuntime, staged: StagedDefinition, *, flow_id: int
    ) -> tuple[list[str], list[str]]:
        """Hot-swap de host por `MpcHost` (spec §4.7): bloco cujo config não mudou preserva
        o MESMO host (identidade de objeto, §4.1-3) — só quem mudou (ou saiu do grafo) ganha
        host novo. Devolve `(swapped, swapped_bumpless)` — dois conjuntos de `block_id`
        substituídos (config mudou, ainda presentes no grafo novo), por MOTIVO do evento
        que `_stage` publica para eles só DEPOIS de já ter atualizado
        `runtime.blocks`/`runtime.hosts`, nunca aqui dentro:
        - `swapped`: sheda a LOCAL (`mpc_mode_changed{reason: hot_swap}`) — comportamento
          herdado (ADR-011), config mudou E o conjunto de MVs mudou (ou não havia bloco
          MPC velho para transplantar).
        - `swapped_bumpless`: o bloco novo já nasceu transplantado (TD-006,
          `definition.py::build_definition` chamou `aplicar_estado` — `block.transplantado`
          é `True`) — os modos NÃO mudaram, então o `mode_cmd=auto` do shed de sempre é
          PULADO (devolvê-lo aqui destruiria o REMOTO que acabou de ser preservado);
          `mpc_mode_changed{reason: hot_swap_bumpless}` é só auditoria.

        Achado 4 da revisão F4 (race contra `_auto_revert` do watchdog, que roda FORA de
        `self._lock`): `cancel_watchdog` pode achar o dict já vazio — o watchdog se
        auto-removeu ao disparar `_auto_revert` — e virar no-op sem esperar essa task. Mas
        `_auto_revert` remove a entrada do dict E muda `block.local_remote` no MESMO trecho
        síncrono (sem nenhum `await` entre as duas linhas — só depois vem o primeiro I/O,
        `_audit_mode_changed`). Logo quem acha o dict vazio SEMPRE acha `local_remote` já
        "local" também: nunca os dois escrevem `mode_cmd=auto` pro mesmo bloco. Provado no
        relatório desta tarefa (fix-final-supervisor.md); nenhum guard extra entrou aqui."""
        old_hosts = runtime.hosts
        new_hosts = staged.hosts
        for block_id, host in new_hosts.items():
            if old_hosts.get(block_id) is not host:
                self.start_host_background(runtime, host, flow_id=flow_id, block_id=block_id)
        swapped: list[str] = []
        swapped_bumpless: list[str] = []
        for block_id, old_host in old_hosts.items():
            if new_hosts.get(block_id) is old_host:
                continue  # bloco não mudou: host e estado preservados (§4.1-3)
            await self.cancel_watchdog(runtime, block_id)
            old_entry = runtime.blocks.get(block_id)
            new_entry = staged.blocks.get(block_id)
            transplantado = (
                new_entry is not None
                and isinstance(new_entry[1], MpcBlock)
                and new_entry[1].transplantado
            )
            if old_entry is not None and isinstance(old_entry[1], MpcBlock):
                old_block = old_entry[1]
                if old_block.local_remote == "remote" and not transplantado:
                    await write_mode_cmd(
                        runtime.mpc_write_opc,
                        old_block.pid_bindings,
                        "auto",
                        source=mpc_block_origin(flow_id, block_id),
                        local_shed_modes=old_block.local_shed_modes,
                    )
                if block_id in new_hosts:  # substituído (config mudou), não removido do grafo
                    (swapped_bumpless if transplantado else swapped).append(block_id)
            self.stop_host_background(runtime, old_host, flow_id=flow_id, block_id=block_id)
        return swapped, swapped_bumpless
