"""Stage do deploy: instanciação de blocos, fiação e conjunto de conexões (spec F3 tarefa 1.4).

Extraído do supervisor (débito 6 do plano F4a — teto de linhas por arquivo): monta o que o
supervisor precisa para subir ou trocar a definição de um flow a partir do grafo já validado
e das tags do projeto. O supervisor mantém a leitura do banco, a validação e a orquestração
de comandos/ciclo de vida (`supervisor.py`); aqui mora só a montagem em si.

Bloco `mpc` (plano F4b, tarefa 2.2): instanciado como qualquer outro — `MpcHost` nasce aqui
(spawn ainda NÃO acontece; `MpcHost.__init__` só monta o processo em `start()`, que o
supervisor chama depois de montar a `StagedDefinition` inteira, dono do ciclo de vida do
host por flow). `write_opc`/`publish`/`emit_event` são fechos sobre `redis_client` — o MESMO
`write_opc` (`_make_write_opc`) resolve `conn_id` a partir de `tags` tanto para as escritas
de MV do próprio bloco quanto para as escritas de `mode_cmd` que o supervisor faz por fora
(`mpc_arming.write_mode_cmd`, via `StagedDefinition.mpc_write_opc`) — um fechamento só,
dois chamadores, sem duplicar a resolução tag→conexão (débito #3 da spec F4 §8, fechado
aqui). A PONTE de deploy da tarefa 3.1 do F4a (`MpcNotReadyError`, que recusava um grafo
com `mpc` no stage) morreu nesta tarefa: o grafo agora instancia normalmente.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from typing import Any, Final, NamedTuple

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import (
    CHANNEL_OPC_WRITES,
    FuzzyState,
    LoopState,
    MpcState,
    OpcWrite,
    channel_fuzzy_state,
    channel_loop_state,
    channel_mpc_state,
    publish_event,
)
from ottima_core.flowgraph import (
    FlowGraph,
    FlowNode,
    FuzzyLoopConfig,
    LoopBaseConfig,
    MpcConfig,
    PidLoopConfig,
    TagRef,
    loop_structural,
)
from ottima_core.models import LoopSetpoint, MpcSetpoint
from ottima_core.script_pool import ScriptPool
from ottima_core.snapshot import ValueSnapshot

from .blocks.base import Block
from .blocks.first_order import FirstOrderBlock
from .blocks.fuzzy import FuzzyBlock
from .blocks.kalman import KalmanBlock
from .blocks.kernels.fuzzy import FuzzyKernelCfg, build_fuzzy_kernel
from .blocks.kernels.pid import PidKernel, PidKernelCfg
from .blocks.mpc import MpcBlock
from .blocks.opc_read import OpcReadBlock
from .blocks.opc_write import OpcWriteBlock
from .blocks.pid import PidBlock
from .blocks.script import ScriptBlock
from .blocks.shell.block import BlockShell
from .blocks.shell.config import ShellCfg
from .blocks.shell.kernel import ControlKernel
from .blocks.shell.mode import Mode, mode_from_name
from .blocks.tfs import TfsBlock
from .mpc.host import MpcHost
from .mpc.worker import worker_main
from .scheduler import FlowDefinition

LOOP_TYPES: frozenset[str] = frozenset({"pid_loop", "fuzzy_loop"})


class LoopSeed(NamedTuple):
    sp: float | None
    man_out: float | None


_TAG_TYPES = frozenset({"opc_read", "opc_write"})


PERSIST_SP_TIMEOUT_S: Final[float] = 2.0
"""Teto do upsert de `mpc_setpoints` (achado HIGH da revisão): `persist_sp` roda sob o
`Supervisor._lock` (que serializa deploy/stop/reload/watermark da partição inteira) e o
engine não tem statement timeout — um Postgres parado congelaria a fila de comandos de
TODOS os flows. O `wait_for` degrada a parada para no máximo este teto; o `MpcBlock`
captura o `TimeoutError` como qualquer falha de persistência (fire-and-forget, RNF-05).
Upsert de uma linha é sub-10 ms em regime — 2 s é margem de commit lento, não de espera."""


@dataclass(frozen=True, slots=True)
class StagedDefinition:
    """Definição pronta para subir ou entrar em hot-swap, com o que o supervisor guarda dela."""

    definition: FlowDefinition
    ts_seconds: float
    conn_ids: frozenset[int]
    blocks: dict[str, tuple[dict[str, Any], Block]]
    """`block_id -> (config funcional, instância)`: a chave da preservação de estado (§4.1-3)."""
    hosts: dict[str, MpcHost] = field(default_factory=dict)
    """`block_id -> MpcHost` só dos blocos `mpc` — o supervisor decide start/stop por
    identidade de objeto (mesmo host reaproveitado = bloco não mudou, §4.1-3)."""
    mpc_write_opc: Callable[[OpcWrite], Awaitable[None]] | None = None
    """`write_opc` com `conn_id` já resolvido — o supervisor reusa para escrever `mode_cmd`
    fora do `step()` do bloco (transições §4.4/§4.5, `mpc_arming.py`)."""


def build_definition(
    graph: FlowGraph,
    tags: Mapping[int, TagRef],
    *,
    flow_id: int,
    ts_seconds: float,
    reuse: Mapping[str, tuple[dict[str, Any], Block]],
    redis_client: Redis,
    pool: ScriptPool,
    snapshot: ValueSnapshot,
    watchdog_enabled: bool = False,
    mpc_worker_target: Callable[[Connection, str, float], None] = worker_main,
    sp_seeds: Mapping[str, Mapping[str, float]] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    loop_seeds: Mapping[str, LoopSeed] | None = None,
) -> StagedDefinition:
    """Instancia os blocos do grafo (reaproveitando os que não mudaram) e monta a fiação.

    `reuse` é o `blocks` da definição vigente: config funcional igual ⇒ a instância viva
    continua, e o estado interno vem junto de graça (ADR-011). O método É o comparador:
    `exec_order`, rótulo e posição ficam fora dele de propósito (ADR-024).
    """
    blocks: dict[str, tuple[dict[str, Any], Block]] = {}
    hosts: dict[str, MpcHost] = {}
    instances: list[Block] = []
    write_opc = _make_write_opc(redis_client, tags, flow_id=flow_id)
    for node in sorted(graph.nodes, key=lambda item: item.exec_order):
        functional = node.functional_config()
        kept = reuse.get(node.id)
        if kept is not None and kept[0] == functional:
            block = kept[1]
        elif (
            kept is not None
            and node.type in LOOP_TYPES
            and isinstance(kept[1], BlockShell)
            and loop_structural(kept[0]) == loop_structural(functional)
        ):
            # Classe de sintonia (ADR-039 D11): in-place, estado preservado.
            block = kept[1]
            kernel_cfg = _loop_kernel_cfg(node)
            block.apply_tuning(shell_cfg_from(node.config, ts_seconds), kernel_cfg)
        else:
            # TD-006 MPC abaixo. Estrutural de malha (D11): o predecessor carrega
            # u/sp/man e aterrissa em MAN se a instancia velha calculava.
            predecessor: BlockShell | None = None
            if kept is not None and isinstance(kept[1], BlockShell):
                predecessor = kept[1]
            block = _instantiate(
                node,
                flow_id=flow_id,
                ts_seconds=ts_seconds,
                tags=tags,
                redis_client=redis_client,
                pool=pool,
                snapshot=snapshot,
                write_opc=write_opc,
                mpc_worker_target=mpc_worker_target,
                watchdog_enabled=watchdog_enabled,
                sp_seed=(sp_seeds or {}).get(node.id),
                session_factory=session_factory,
                loop_seed=(loop_seeds or {}).get(node.id),
                predecessor=predecessor,
            )
            # TD-006: config mudou (ou o bloco é novo) — quando o bloco velho é um
            # `MpcBlock` e o conjunto de MVs é IDÊNTICO, o novo transplanta o estado do
            # velho (`EstadoMpcTransplante`) em vez de nascer zerado em LOCAL (ADR-011 já
            # cobre "config não mudou": esse caso nem entra aqui, reuse acima resolve
            # sozinho). Conjunto de MVs mudou, ou o Ts do flow mudou (`reuse={}` inteiro
            # antes deste laço, então `kept is None`) -> comportamento herdado, nasce
            # zerado.
            if kept is not None and isinstance(kept[1], MpcBlock) and isinstance(block, MpcBlock):
                mvs_velhas = _mv_ids_de_functional(kept[0])
                mvs_novas = _mv_ids_de_functional(functional)
                if mvs_velhas is not None and mvs_velhas == mvs_novas:
                    block.aplicar_estado(kept[1].snapshot_estado())
                    block.transplantado = True
        blocks[node.id] = (functional, block)
        instances.append(block)
        if isinstance(block, MpcBlock):
            hosts[node.id] = block.host

    return StagedDefinition(
        definition=FlowDefinition(
            flow_id=flow_id,
            ts_seconds=ts_seconds,
            blocks=tuple(instances),
            wiring=_wiring(graph),
        ),
        ts_seconds=ts_seconds,
        conn_ids=_conn_ids(graph, tags),
        blocks=blocks,
        hosts=hosts,
        mpc_write_opc=write_opc,
    )


def _mv_ids_de_functional(functional: dict[str, Any]) -> frozenset[str] | None:
    """IDs das MVs de um `functional_config()` de bloco `mpc` (TD-006): compara o
    conjunto de MVs entre a config velha e a nova direto nos dicts crus, sem reinstanciar
    `MpcConfig` nem tocar o estado privado do `MpcBlock` velho. `None` fora do tipo `mpc`
    ou de uma forma inesperada — o chamador só invoca isto já sob `isinstance(..., MpcBlock)`
    dos dois lados, então a forma normal é sempre a esperada."""
    if functional.get("type") != "mpc":
        return None
    variables = functional.get("variables")
    if not isinstance(variables, dict):
        return None
    mvs = variables.get("mvs")
    if not isinstance(mvs, list):
        return None
    return frozenset(mv["id"] for mv in mvs if isinstance(mv, dict) and "id" in mv)


def _make_write_opc(
    redis_client: Redis, tags: Mapping[int, TagRef], *, flow_id: int
) -> Callable[[OpcWrite], Awaitable[None]]:
    """`OpcWrite` chega com `conn_id=0` (o `pid` não carrega conexão, só `tag_id`) — este
    fecho é quem resolve o `conn_id` de verdade a partir de `tags` antes de publicar
    (débito #3 da spec F4 §8). Também resolve `flow_id` (ADR-009 revisado: watchdog é por
    flow — o gate de escrita do opc-worker precisa saber de qual flow a escrita veio).
    Único fechamento — usado tanto pelas escritas de MV do próprio `MpcBlock`
    (`_write_pid`) quanto pelas de `mode_cmd` que o supervisor faz por fora dele
    (`mpc_arming.write_mode_cmd`)."""

    async def write_opc(write: OpcWrite) -> None:
        resolved = write.model_copy(
            update={"conn_id": tags[write.tag_id].conn_id, "flow_id": flow_id}
        )
        await redis_client.publish(CHANNEL_OPC_WRITES, resolved.model_dump_json())

    return write_opc


def _instantiate(
    node: FlowNode,
    *,
    flow_id: int,
    ts_seconds: float,
    tags: Mapping[int, TagRef],
    redis_client: Redis,
    pool: ScriptPool,
    snapshot: ValueSnapshot,
    write_opc: Callable[[OpcWrite], Awaitable[None]],
    mpc_worker_target: Callable[[Connection, str, float], None],
    watchdog_enabled: bool,
    sp_seed: Mapping[str, float] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    loop_seed: LoopSeed | None = None,
    predecessor: BlockShell | None = None,
) -> Block:
    """Instancia o bloco com os serviços do runtime. Bloco novo nasce zerado (§4.1-3)."""
    config: Any = node.config
    if node.type == "opc_read":
        tag = tags[config.tag_id]
        return OpcReadBlock(node.id, tag_id=tag.id, data_type=tag.data_type, snapshot=snapshot)
    if node.type == "opc_write":
        tag = tags[config.tag_id]
        return OpcWriteBlock(
            node.id,
            tag_id=tag.id,
            conn_id=tag.conn_id,
            flow_id=flow_id,
            redis_client=redis_client,
        )
    if node.type == "script":
        return ScriptBlock(
            node.id,
            code=config.code,
            n_inputs=config.n_inputs,
            n_outputs=config.n_outputs,
            flow_id=flow_id,
            ts_seconds=ts_seconds,
            pool=pool,
            redis_client=redis_client,
        )
    if node.type == "mpc":
        return _instantiate_mpc(
            node,
            flow_id=flow_id,
            ts_seconds=ts_seconds,
            snapshot=snapshot,
            redis_client=redis_client,
            write_opc=write_opc,
            worker_target=mpc_worker_target,
            escreve_sem_watchdog=not watchdog_enabled,
            sp_seed=sp_seed,
            session_factory=session_factory,
        )
    if node.type == "first_order":
        return FirstOrderBlock(node.id, tau=config.tau, ts_seconds=ts_seconds)
    if node.type == "kalman":
        return KalmanBlock(
            node.id,
            measurement_noise=config.measurement_noise,
            process_noise=config.process_noise,
        )
    if node.type == "fuzzy":
        return _instantiate_fuzzy(node, flow_id=flow_id, redis_client=redis_client)
    if node.type == "pid_loop":
        return _instantiate_loop(
            node,
            flow_id=flow_id,
            ts_seconds=ts_seconds,
            redis_client=redis_client,
            session_factory=session_factory,
            seed=loop_seed,
            predecessor=predecessor,
        )
    if node.type == "pid":
        return PidBlock(
            node.id,
            kc=config.kc,
            ti_seconds=config.ti_seconds,
            td_seconds=config.td_seconds,
            setpoint=config.setpoint,
            output_min=config.output_min,
            output_max=config.output_max,
            auto_mode=config.auto_mode,
            proportional_on_measurement=config.proportional_on_measurement,
            differential_on_measurement=config.differential_on_measurement,
            starting_output=config.starting_output,
            ts_seconds=ts_seconds,
        )
    return TfsBlock(node.id, matrix=config.matrix, ts_seconds=ts_seconds)


def _instantiate_mpc(
    node: FlowNode,
    *,
    flow_id: int,
    ts_seconds: float,
    snapshot: ValueSnapshot,
    redis_client: Redis,
    write_opc: Callable[[OpcWrite], Awaitable[None]],
    worker_target: Callable[[Connection, str, float], None],
    escreve_sem_watchdog: bool = False,
    sp_seed: Mapping[str, float] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> MpcBlock:
    config = MpcConfig.model_validate(node.config.model_dump())
    host = MpcHost(node.id, config, ts_seconds, worker_target=worker_target)
    channel = channel_mpc_state(flow_id, node.id)

    async def publish(state: MpcState) -> None:
        await redis_client.publish(channel, state.model_dump_json())

    async def emit_event(**kwargs: Any) -> None:
        await publish_event(redis_client, ts=datetime.now(UTC), **kwargs)

    async def persist_sp(var_id: str, value: float) -> None:
        """Upsert do SP materializado em `mpc_setpoints` — sessão própria, commit próprio,
        com teto de `PERSIST_SP_TIMEOUT_S` (fire-and-forget visto do bloco: o `MpcBlock`
        captura exceção E timeout e só loga; o comando nunca fica refém do banco)."""
        if session_factory is None:
            return
        stmt = pg_insert(MpcSetpoint).values(
            flow_id=flow_id, block_id=node.id, var_id=var_id, value=value
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["flow_id", "block_id", "var_id"],
            set_={"value": stmt.excluded.value, "updated_at": func.now()},
        )

        async def _grava() -> None:
            async with session_factory() as session:
                await session.execute(stmt)
                await session.commit()

        await asyncio.wait_for(_grava(), timeout=PERSIST_SP_TIMEOUT_S)

    return MpcBlock(
        node.id,
        config=config,
        ts_flow=ts_seconds,
        snapshot=snapshot,
        host=host,
        flow_id=flow_id,
        publish=publish,
        write_opc=write_opc,
        emit_event=emit_event,
        escreve_sem_watchdog=escreve_sem_watchdog,
        sp_seed=sp_seed,
        persist_sp=persist_sp,
    )


def _instantiate_fuzzy(node: FlowNode, *, flow_id: int, redis_client: Redis) -> FuzzyBlock:
    config: Any = node.config
    channel = channel_fuzzy_state(flow_id, node.id)

    async def publish(state: FuzzyState) -> None:
        await redis_client.publish(channel, state.model_dump_json())

    return FuzzyBlock(
        node.id,
        fll=config.fll,
        n_inputs=config.n_inputs,
        n_outputs=config.n_outputs,
        publish=publish,
    )


def _wiring(graph: FlowGraph) -> dict[str, dict[str, tuple[str, str]]]:
    """`wiring[block_id][handle_de_entrada] = (bloco_origem, handle_de_origem)`."""
    wiring: dict[str, dict[str, tuple[str, str]]] = {}
    for edge in graph.edges:
        wiring.setdefault(edge.target, {})[edge.target_handle] = (edge.source, edge.source_handle)
    return wiring


def _conn_ids(graph: FlowGraph, tags: Mapping[int, TagRef]) -> frozenset[int]:
    """Conexões que o grafo referencia — o conjunto que o `comm_failure` consulta (§2.2-8).

    Mora aqui, e não na `FlowDefinition`, porque o laço de varredura não tem nada a fazer
    com `conn_id`: quem reage à queda de conexão é o supervisor. Inclui as tags do `pid` de
    cada MV de cada bloco `mpc` (spec F4 §2.2-8): um `comm_failure` na conexão derruba o
    flow do MPC como derruba o de um OPC-Read. O grafo aqui já passou por `validate_graph`
    (precondição do módulo) — `MpcConfig.model_validate` não deve falhar.
    """
    tag_conn_ids = (
        tags[node.config.tag_id].conn_id
        for node in graph.nodes
        if node.type in _TAG_TYPES and node.config.tag_id in tags
    )
    pid_conn_ids = (
        tags[tag_id].conn_id
        for node in graph.nodes
        if node.type == "mpc"
        for tag_id in _mpc_pid_tag_ids(node)
        if tag_id in tags
    )
    return frozenset((*tag_conn_ids, *pid_conn_ids))


def _mpc_pid_tag_ids(node: FlowNode) -> Iterator[int]:
    """Tags do `pid` de cada MV do bloco `mpc` — MV "direta" (sem `pid`, decisão A-8) não
    contribui nenhuma."""
    config = MpcConfig.model_validate(node.config.model_dump())
    for mv in config.variables.mvs:
        if mv.pid is None:
            continue
        yield mv.pid.write_tag_id
        yield mv.pid.mode_cmd_tag_id
        yield mv.pid.readback_tag_id
        if mv.pid.mode_read_tag_id is not None:
            yield mv.pid.mode_read_tag_id


async def carregar_sp_seeds(session: AsyncSession, flow_id: int) -> dict[str, dict[str, float]]:
    """`{block_id: {var_id: valor}}` persistido em `mpc_setpoints` para o flow — semente
    de `reset()` dos blocos `mpc` no deploy/redeploy (persistência do SP do operador;
    os modos seguem voláteis, RNF-03)."""
    resultado = await session.execute(
        select(MpcSetpoint.block_id, MpcSetpoint.var_id, MpcSetpoint.value).where(
            MpcSetpoint.flow_id == flow_id
        )
    )
    seeds: dict[str, dict[str, float]] = {}
    for block_id, var_id, value in resultado.all():
        seeds.setdefault(block_id, {})[var_id] = float(value)
    return seeds


def shell_cfg_from(config: LoopBaseConfig, ts_seconds: float) -> ShellCfg:
    permitted = Mode(0)
    for nome in config.permitted:
        permitted |= mode_from_name(nome)
    return ShellCfg(
        sp_hi_lim=config.sp_hi_lim,
        sp_lo_lim=config.sp_lo_lim,
        max_dt=10.0 * ts_seconds,
        permitted=permitted,
        normal=mode_from_name(config.normal),
        shed_opt=config.shed_opt,
        shed_no_return=config.shed_no_return,
        direct_acting=config.direct_acting,
        sp_pv_track_in_man=config.sp_pv_track_in_man,
        use_pv_for_bkcal=config.use_pv_for_bkcal,
        track_enable=config.track_enable,
        track_in_manual=config.track_in_manual,
        sp_rate_up=config.sp_rate_up,
        sp_rate_dn=config.sp_rate_dn,
        out_hi_lim=config.out_hi_lim,
        out_lo_lim=config.out_lo_lim,
        out_rate_up=config.out_rate_up,
        out_rate_dn=config.out_rate_dn,
        out_scale_lo=config.out_scale_lo,
        out_scale_hi=config.out_scale_hi,
        out_startup=config.out_startup,
        pv_ftime=config.pv_ftime,
        trk_val=config.trk_val,
        lo_val=config.lo_val,
        ff_scale_lo=config.ff_scale_lo,
        ff_scale_hi=config.ff_scale_hi,
        ff_gain=config.ff_gain,
        ff_enable=config.ff_enable,
    )


def pid_kernel_cfg_from(config: PidLoopConfig) -> PidKernelCfg:
    return PidKernelCfg(
        kc=config.kc,
        ti=config.ti_seconds,
        td=config.td_seconds,
        n=config.n,
        beta=config.beta,
        gamma=config.gamma,
        gap_band=config.gap_band,
        gap_gain=config.gap_gain,
        direct_acting=config.direct_acting,
    )


def fuzzy_kernel_cfg_from(config: FuzzyLoopConfig) -> FuzzyKernelCfg:
    return FuzzyKernelCfg(
        ke=config.ke,
        kde=config.kde,
        ku=config.ku,
        tf_de=config.tf_de,
        direct_acting=config.direct_acting,
    )


def _loop_kernel_cfg(node: FlowNode) -> PidKernelCfg | FuzzyKernelCfg | None:
    """Config de sintonia do kernel para o hot-swap in-place (ADR-039 D11).

    `None` para tipo que nao e malha: `apply_tuning` entao so troca o `ShellCfg`.
    """
    if node.type == "pid_loop":
        return pid_kernel_cfg_from(node.config)
    if node.type == "fuzzy_loop":
        return fuzzy_kernel_cfg_from(node.config)
    return None


def _build_loop_kernel(node_type: str, config: Any) -> ControlKernel:
    """Kernel de uma instancia nova de malha.

    O `fuzzy_loop` pode devolver `BrokenKernel` (FLL degradado entre save e deploy): o
    bloco nasce, o shell le `validate()` e o prende em OOS+CONFIG_ERROR em vez de derrubar
    o flow na construcao (SPEC_FUZZY secao 4.1-5).
    """
    if node_type == "fuzzy_loop":
        return build_fuzzy_kernel(config.fll, fuzzy_kernel_cfg_from(config))
    return PidKernel(pid_kernel_cfg_from(config))


async def carregar_loop_seeds(session: AsyncSession, flow_id: int) -> dict[str, LoopSeed]:
    """`{block_id: LoopSeed(sp, man_out)}` persistido em `loop_setpoints` para o flow —
    semente de SP e MAN_OUT no deploy (ADR-039 §4.10); TARGET persiste so para auditoria."""
    resultado = await session.execute(
        select(LoopSetpoint.sp, LoopSetpoint.man_out, LoopSetpoint.block_id).where(
            LoopSetpoint.flow_id == flow_id
        )
    )
    return {block_id: LoopSeed(sp=sp, man_out=man_out) for sp, man_out, block_id in resultado.all()}


def _instantiate_loop(
    node: FlowNode,
    *,
    flow_id: int,
    ts_seconds: float,
    redis_client: Redis,
    session_factory: async_sessionmaker[AsyncSession] | None,
    seed: LoopSeed | None,
    predecessor: BlockShell | None,
) -> BlockShell:
    config: Any = node.config
    channel = channel_loop_state(flow_id, node.id)

    async def publish(state: LoopState) -> None:
        await redis_client.publish(channel, state.model_dump_json())

    async def emit_event(**kwargs: Any) -> None:
        await publish_event(redis_client, ts=datetime.now(UTC), **kwargs)

    async def persist_op(field: str, value: float | str) -> None:
        """Upsert do valor de operacao em `loop_setpoints` — mesmo teto e postura
        fire-and-forget do `persist_sp` do MPC (RNF-05)."""
        if session_factory is None:
            return
        stmt = pg_insert(LoopSetpoint).values(flow_id=flow_id, block_id=node.id, **{field: value})
        stmt = stmt.on_conflict_do_update(
            index_elements=["flow_id", "block_id"],
            set_={field: value, "updated_at": func.now()},
        )

        async def _grava() -> None:
            async with session_factory() as session:
                await session.execute(stmt)
                await session.commit()

        await asyncio.wait_for(_grava(), timeout=PERSIST_SP_TIMEOUT_S)

    kernel = _build_loop_kernel(node.type, config)
    return BlockShell(
        node.id,
        kernel=kernel,
        cfg=shell_cfg_from(config, ts_seconds),
        emit_event=emit_event,
        publish_state=publish,
        persist_op=persist_op,
        sp_seed=seed.sp if seed else None,
        man_out_seed=seed.man_out if seed else None,
        carry=predecessor.carry_state() if predecessor is not None else None,
    )
