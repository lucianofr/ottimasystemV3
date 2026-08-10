"""Retomada automática pós `comm_restored` (TD-005, ADR-025).

Extraído do `Supervisor` pelo mesmo motivo da extração do `MpcOrchestrator`
(`supervisor_mpc.py`, débito #6 do plano F4b): teto de linhas por arquivo. `on_comm_failure`
continua em `supervisor.py` — o snapshot pré-queda depende do `_FlowRuntime` de antes de
`task.fail()`, mesmo lugar onde o resto do desmonte por `comm_failure` já mora; este módulo
só CONSOME o que `on_comm_failure` guarda em `self.pendentes`.

Desenho em duas fases, para nunca prender `Supervisor._lock` atrás de um `sleep` (mesma
disciplina de `MpcOrchestrator.start_host_background`/`stop_host_background`):
1. `on_comm_restored` (sob o lock): redeploy + aplica o snapshot nos blocos MPC novos —
   síncrono, rápido, mesmo caminho de `Supervisor._deploy_flow`.
2. O rearme em si (`_rearmar_um`, fora do lock, task destacada): espera as entradas
   esquentarem (pode levar vários `Ts_mpc`) e só então rearma pela MESMA máquina de
   comandos que um operador usaria (`MpcOrchestrator.mpc_command`) — sem atalho.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import KIND_FLOW_RESUMED, KIND_MPC_MODE_CHANGED, FlowCommand, publish_event
from ottima_core.models import Flow

from .blocks.mpc import EstadoMpcTransplante, MpcBlock
from .events import flow_origin, mpc_block_origin
from .supervisor_mpc import MpcOrchestrator

if TYPE_CHECKING:
    from .supervisor import _FlowRuntime

logger = logging.getLogger(__name__)

SYSTEM_RESUME_ACTOR = "sistema:retomada"
"""Ator de auditoria do redeploy e do rearme automáticos pós `comm_restored` (ADR-025)."""

_REARME_TENTATIVAS_MAX = 30
"""Teto de esperas de `Ts_mpc` até as entradas voltarem a quentes/válidas (`auto_arm_
blocked_reason`, spec §4.4) antes de desistir do rearme automático — o flow já redeployou;
a partir daí um operador arma na mão. Não é retry storm (guarda §2.2-8): 1 tentativa de
retomada por evento `comm_restored`, este laço é só a espera DENTRO dela."""


@dataclass(slots=True)
class RetomadaPendente:
    """Retomada automática pendente após `comm_failure` numa conexão (TD-005, ADR-025).

    `estados` só tem entradas para os blocos `mpc` do flow — vazio quando ele não tem
    nenhum (o redeploy roda igual, só não há modo/SP nenhum para restaurar depois)."""

    conn_id: int
    estados: dict[str, EstadoMpcTransplante]


class ResumeOrchestrator:
    """Escuta `comm_restored` e retoma os flows pendentes (spec §2.2-8, ADR-025).

    `Supervisor` guarda a instância e delega `on_comm_restored`; `on_comm_failure` popula
    `self.pendentes` diretamente (mesmo padrão de `self._runtimes` do `MpcOrchestrator`)."""

    def __init__(
        self,
        runtimes: dict[int, _FlowRuntime],
        redis_client: Redis,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lock: asyncio.Lock,
        mpc: MpcOrchestrator,
        deploy_flow: Callable[[int, str], Awaitable[_FlowRuntime | None]],
        load_flow: Callable[[AsyncSession, int], Awaitable[tuple[Flow, bool] | None]],
    ) -> None:
        self._runtimes = runtimes
        self._redis = redis_client
        self._session_factory = session_factory
        self._lock = lock
        self._mpc = mpc
        self._deploy_flow = deploy_flow
        self._load_flow = load_flow
        self.pendentes: dict[int, RetomadaPendente] = {}

    def descartar(self, flow_id: int) -> None:
        """Comando manual (`deploy`/`stop`) sempre vence sobre a retomada automática
        (§2.2-8, RNF-05): limpa a entrada pendente do flow, se houver."""
        self.pendentes.pop(flow_id, None)

    async def on_comm_restored(self, conn_id: int) -> None:
        """Redeploy + snapshot aplicado sob `self._lock` (rápido); o rearme em si roda
        destacado (`_rearmar_todos`) — nunca prende o lock atrás de um `sleep`."""
        async with self._lock:
            casam = [
                (flow_id, pendente)
                for flow_id, pendente in self.pendentes.items()
                if pendente.conn_id == conn_id
            ]
            for flow_id, pendente in casam:
                await self._iniciar(flow_id, pendente)

    async def _iniciar(self, flow_id: int, pendente: RetomadaPendente) -> None:
        async with self._session_factory() as session:
            row = await self._load_flow(session, flow_id)
        if row is None or row[0].desired_state != "running":
            # Flow deletado ou o operador parou durante a queda: comando manual vence.
            self.pendentes.pop(flow_id, None)
            return
        runtime = await self._deploy_flow(flow_id, SYSTEM_RESUME_ACTOR)
        if runtime is None:
            return  # redeploy recusado (grafo inválido etc.): a entrada FICA p/ o próximo edge
        self.pendentes.pop(flow_id, None)

        blocos: list[tuple[str, MpcBlock, EstadoMpcTransplante]] = []
        for block_id, estado in pendente.estados.items():
            entry = runtime.blocks.get(block_id)
            if entry is None or not isinstance(entry[1], MpcBlock):
                continue  # bloco saiu do grafo entre a queda e a retomada
            entry[1].aplicar_estado(estado)
            blocos.append((block_id, entry[1], estado))

        task = asyncio.get_running_loop().create_task(
            self._rearmar_todos(flow_id, blocos), name=f"mpc-retomada-{flow_id}"
        )
        runtime.mpc_boot_tasks.add(task)
        task.add_done_callback(runtime.mpc_boot_tasks.discard)

        await publish_event(
            self._redis,
            severity="info",
            origin=flow_origin(flow_id),
            message=f"Flow {flow_id} retomado automaticamente após restauração da conexão",
            kind=KIND_FLOW_RESUMED,
            payload={"flow_id": flow_id, "conn_id": pendente.conn_id},
        )

    async def _rearmar_todos(
        self, flow_id: int, blocos: list[tuple[str, MpcBlock, EstadoMpcTransplante]]
    ) -> None:
        for block_id, block, estado in blocos:
            if estado.local_remote != "remote":
                continue  # LOCAL/MAN já voltou por `aplicar_estado`; nada a rearmar no PID
            await self._rearmar_um(flow_id, block_id, block, estado)

    async def _rearmar_um(
        self, flow_id: int, block_id: str, block: MpcBlock, estado: EstadoMpcTransplante
    ) -> None:
        """Espera as entradas esquentarem/validarem (mesmo predicado do arme manual,
        `auto_arm_blocked_reason`), depois rearma pela MESMA máquina de comandos que um
        operador usaria (`MpcOrchestrator.mpc_command`) — sem atalho: `local_remote`
        confirma via watchdog como sempre (`mpc_arming.watch_arm`), `man_auto` some por
        cima quando já REMOTO, e o SP só materializa de verdade se `_in_auto` (o próprio
        `_command_sp` do bloco no-opera fora de AUTO, spec §4.8) — não precisamos verificar
        o resultado à mão."""
        for _ in range(_REARME_TENTATIVAS_MAX):
            if block.auto_arm_blocked_reason() is None:
                break
            await asyncio.sleep(block.ts_mpc)
        else:
            return  # nunca esquentou/validou — desiste; operador arma na mão

        runtime = self._runtimes.get(flow_id)
        if runtime is None or runtime.task.state != "running":
            return  # o flow saiu do ar (stop/comm_failure de novo) enquanto esperava
        entry = runtime.blocks.get(block_id)
        if entry is None or entry[1] is not block:
            return  # redeployado de novo nesse meio-tempo: este bloco já é obsoleto

        async with self._lock:
            await self._mpc.mpc_command(
                _comando(flow_id, "mpc_mode", _eixo("local_remote", "remote", block_id))
            )
            if block.local_remote != "remote":
                return
            await self._mpc.mpc_command(
                _comando(flow_id, "mpc_mode", _eixo("man_auto", "auto", block_id))
            )
            for var_id, valor in estado.sp.items():
                await self._mpc.mpc_command(
                    _comando(
                        flow_id, "mpc_sp", {"block_id": block_id, "var_id": var_id, "value": valor}
                    )
                )

        await publish_event(
            self._redis,
            severity="info",
            origin=mpc_block_origin(flow_id, block_id),
            message=f"MPC '{block_id}': modo restaurado após retomada automática",
            kind=KIND_MPC_MODE_CHANGED,
            payload={"reason": "auto_resume"},
        )


def _eixo(axis: str, value: str, block_id: str) -> dict[str, str]:
    return {"block_id": block_id, "axis": axis, "value": value}


def _comando(flow_id: int, cmd: str, args: dict[str, object]) -> FlowCommand:
    return FlowCommand(
        flow_id=flow_id, cmd=cmd, args=args, user=SYSTEM_RESUME_ACTOR, ts=datetime.now(UTC)
    )
