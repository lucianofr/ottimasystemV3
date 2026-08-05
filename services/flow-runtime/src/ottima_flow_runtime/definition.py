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

from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from typing import Any

from redis.asyncio import Redis

from ottima_core.bus import CHANNEL_OPC_WRITES, MpcState, OpcWrite, channel_mpc_state, publish_event
from ottima_core.flowgraph import FlowGraph, FlowNode, MpcConfig, TagRef

from .blocks.base import Block
from .blocks.mpc import MpcBlock
from .blocks.opc_read import OpcReadBlock
from .blocks.opc_write import OpcWriteBlock
from .blocks.script import ScriptBlock
from .blocks.tfs import TfsBlock
from .mpc.host import MpcHost
from .mpc.worker import worker_main
from .scheduler import FlowDefinition
from .script_pool import ScriptPool
from .snapshot import ValueSnapshot

_TAG_TYPES = frozenset({"opc_read", "opc_write"})


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
    mpc_worker_target: Callable[[Connection, str, float], None] = worker_main,
) -> StagedDefinition:
    """Instancia os blocos do grafo (reaproveitando os que não mudaram) e monta a fiação.

    `reuse` é o `blocks` da definição vigente: config funcional igual ⇒ a instância viva
    continua, e o estado interno vem junto de graça (ADR-011). O método É o comparador:
    `exec_order`, rótulo e posição ficam fora dele de propósito (ADR-024).
    """
    blocks: dict[str, tuple[dict[str, Any], Block]] = {}
    hosts: dict[str, MpcHost] = {}
    instances: list[Block] = []
    write_opc = _make_write_opc(redis_client, tags)
    for node in sorted(graph.nodes, key=lambda item: item.exec_order):
        functional = node.functional_config()
        kept = reuse.get(node.id)
        block = (
            kept[1]
            if kept is not None and kept[0] == functional
            else _instantiate(
                node,
                flow_id=flow_id,
                ts_seconds=ts_seconds,
                tags=tags,
                redis_client=redis_client,
                pool=pool,
                snapshot=snapshot,
                write_opc=write_opc,
                mpc_worker_target=mpc_worker_target,
            )
        )
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


def _make_write_opc(
    redis_client: Redis, tags: Mapping[int, TagRef]
) -> Callable[[OpcWrite], Awaitable[None]]:
    """`OpcWrite` chega com `conn_id=0` (o `pid` não carrega conexão, só `tag_id`) — este
    fecho é quem resolve o `conn_id` de verdade a partir de `tags` antes de publicar
    (débito #3 da spec F4 §8). Único fechamento — usado tanto pelas escritas de MV do
    próprio `MpcBlock` (`_write_pid`) quanto pelas de `mode_cmd` que o supervisor faz por
    fora dele (`mpc_arming.write_mode_cmd`)."""

    async def write_opc(write: OpcWrite) -> None:
        resolved = write.model_copy(update={"conn_id": tags[write.tag_id].conn_id})
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
) -> MpcBlock:
    config = MpcConfig.model_validate(node.config.model_dump())
    host = MpcHost(node.id, config, ts_seconds, worker_target=worker_target)
    channel = channel_mpc_state(flow_id, node.id)

    async def publish(state: MpcState) -> None:
        await redis_client.publish(channel, state.model_dump_json())

    async def emit_event(**kwargs: Any) -> None:
        await publish_event(redis_client, ts=datetime.now(UTC), **kwargs)

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
