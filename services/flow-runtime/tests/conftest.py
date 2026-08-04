"""Helpers compartilhados dos testes do flow-runtime.

Uma versão única da espera por condição para os arquivos de teste deste serviço: sem isto,
cada tarefa da fase acrescentaria a própria cópia no mesmo diretório. O que é específico de
um arquivo de teste continua nele.

Também mora aqui o arreio do supervisor (banco commitado, construtores de grafo, pool-duplo
e a fábrica de supervisores), porque `test_supervisor.py` e `test_hotswap.py` compartilham o
mesmo cenário: fixture não atravessa módulo de teste, e importar um módulo de teste do outro
colidiria com o `test_supervisor.py` homônimo do opc-worker no `sys.path`.

As fixtures de infraestrutura (`redis_client`, `db_session`) continuam vindo do `conftest.py`
da raiz do repositório.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ottima_core.bus import (
    CHANNEL_FLOW_COMMANDS,
    EventMessage,
    FlowCommand,
    FlowStatus,
    OpcValue,
    channel_opc_values,
)
from ottima_core.models import Flow, OpcConnection, Project, Tag
from ottima_flow_runtime.events import ChannelListener, build_event_listener
from ottima_flow_runtime.script_pool import ScriptResult
from ottima_flow_runtime.snapshot import ValueSnapshot
from ottima_flow_runtime.state import RuntimeState
from ottima_flow_runtime.supervisor import Supervisor

# A suíte roda com --import-mode=importlib, que não põe o diretório dos testes no
# sys.path: sem isto os arquivos de teste não conseguem `from conftest import ...`.
_TESTS_DIR = str(Path(__file__).parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

# Teto das esperas do flow-runtime: o Redis dos testes é local e o laço de reassinatura tem
# freio de 1 s, então não satisfazer a condição em 5 s é falha real, não lentidão.
AWAIT_TIMEOUT_S = 5.0


async def await_until(
    condition: Callable[[], bool], timeout_s: float = AWAIT_TIMEOUT_S, interval: float = 0.02
) -> None:
    """Aguarda a condição virar verdadeira, com polling — evita sleep cego nos testes."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if condition():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"condição não satisfeita em {timeout_s}s")


# --------------------------------------------------------------------------------------
# Arreio do supervisor: constantes
# --------------------------------------------------------------------------------------

TS_SECONDS = 0.5  # menor valor aceito pelo CHECK de `flows.ts_seconds` (ADR-007)
USER = "user:7"
# Poll longo o bastante para provar que o efeito observado NÃO veio do watermark.
SLOW_POLL_S = 60.0
# Poll curto para os testes de watermark: várias passadas dentro de uma espera normal.
FAST_POLL_S = 0.05
# Janela para provar que algo NÃO acontece (cobre várias passadas do poll curto e 1 Ts).
QUIET_WINDOW_S = 0.8


# --------------------------------------------------------------------------------------
# Banco: o supervisor tem session_factory próprio, então o cenário é commitado de verdade
# --------------------------------------------------------------------------------------


@pytest.fixture
async def session_factory(
    migrated_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Factory commitada de verdade: o supervisor não vê transação aberta de teste."""
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _truncate(factory)
    try:
        yield factory
    finally:
        await _truncate(factory)
        await engine.dispose()


async def _truncate(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        await session.execute(text("TRUNCATE flows, tags, opc_connections, projects CASCADE"))
        await session.commit()


async def create_project(
    factory: async_sessionmaker[AsyncSession], *, name: str = "Projeto", is_active: bool = True
) -> int:
    async with factory() as session:
        project = Project(name=name, description="", is_active=is_active)
        session.add(project)
        await session.commit()
        return project.id


async def create_connection(
    factory: async_sessionmaker[AsyncSession], project_id: int, *, name: str = "Forno 1"
) -> int:
    async with factory() as session:
        connection = OpcConnection(
            project_id=project_id,
            name=name,
            endpoint="opc.tcp://inexistente:4840",
            security_policy="none",
            security_mode="none",
            auth_mode="anonymous",
            watchdog_period_ms=1000,
        )
        session.add(connection)
        await session.commit()
        return connection.id


async def create_tag(
    factory: async_sessionmaker[AsyncSession],
    connection_id: int,
    *,
    name: str = "Nível",
    direction: str = "r",
    data_type: str = "float",
) -> int:
    async with factory() as session:
        tag = Tag(
            connection_id=connection_id,
            name=name,
            node_id="ns=2;s=Tag",
            direction=direction,
            data_type=data_type,
        )
        session.add(tag)
        await session.commit()
        return tag.id


async def create_flow(
    factory: async_sessionmaker[AsyncSession],
    project_id: int,
    *,
    graph: dict,
    name: str = "Flow",
    ts_seconds: float = TS_SECONDS,
    desired_state: str = "stopped",
) -> int:
    async with factory() as session:
        flow = Flow(
            project_id=project_id,
            name=name,
            ts_seconds=ts_seconds,
            desired_state=desired_state,
            graph_json=graph,
        )
        session.add(flow)
        await session.commit()
        return flow.id


async def save_graph(
    factory: async_sessionmaker[AsyncSession],
    flow_id: int,
    graph: dict,
    *,
    ts_seconds: float | None = None,
) -> None:
    """Grava o grafo direto no banco, sem passar pela API: é o que o hot-swap relê."""
    async with factory() as session:
        flow = await session.get(Flow, flow_id)
        assert flow is not None
        flow.graph_json = graph
        if ts_seconds is not None:
            flow.ts_seconds = ts_seconds
        await session.commit()


async def delete_flow(factory: async_sessionmaker[AsyncSession], flow_id: int) -> None:
    async with factory() as session:
        flow = await session.get(Flow, flow_id)
        assert flow is not None
        await session.delete(flow)
        await session.commit()


async def set_project_active(
    factory: async_sessionmaker[AsyncSession], project_id: int, *, is_active: bool
) -> None:
    async with factory() as session:
        project = await session.get(Project, project_id)
        assert project is not None
        project.is_active = is_active
        await session.commit()


# --------------------------------------------------------------------------------------
# Construtores de grafo (forma do React Flow, como a API grava)
# --------------------------------------------------------------------------------------


def node(
    node_id: str,
    node_type: str,
    exec_order: int,
    config: dict,
    *,
    label: str = "",
    position: tuple[float, float] = (0.0, 0.0),
) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": position[0], "y": position[1]},
        "data": {"exec_order": exec_order, "label": label, **config},
    }


def read_node(node_id: str, exec_order: int, tag_id: int, **kwargs: Any) -> dict:
    return node(node_id, "opc_read", exec_order, {"tag_id": tag_id}, **kwargs)


def write_node(node_id: str, exec_order: int, tag_id: int, **kwargs: Any) -> dict:
    return node(node_id, "opc_write", exec_order, {"tag_id": tag_id}, **kwargs)


def script_node(
    node_id: str,
    exec_order: int,
    *,
    code: str = "OUT1 = 1.0",
    n_inputs: int = 0,
    n_outputs: int = 1,
    **kwargs: Any,
) -> dict:
    config = {"code": code, "n_inputs": n_inputs, "n_outputs": n_outputs}
    return node(node_id, "script", exec_order, config, **kwargs)


def sopdt(K: float = 1.0, tau: float = 0.5, theta: float = 0.0) -> dict:
    return {
        "enabled": True,
        "kind": "sopdt",
        "params": {"K": K, "tau1": tau, "tau2": tau, "theta": theta},
    }


def disabled_element() -> dict:
    return {"enabled": False, "kind": "iopdt", "params": {"Ki": 0.0, "theta": 0.0}}


def tfs_node(node_id: str, exec_order: int, *, y1_u1: dict | None = None, **kwargs: Any) -> dict:
    """TFS 2x2 com um único elemento possivelmente habilitado em y1/u1."""
    element = disabled_element() if y1_u1 is None else y1_u1
    matrix = [[element, disabled_element()], [disabled_element(), disabled_element()]]
    return node(node_id, "tfs", exec_order, {"matrix": matrix}, **kwargs)


def edge(source: str, source_handle: str, target: str, target_handle: str) -> dict:
    return {
        "id": f"{source}:{source_handle}->{target}:{target_handle}",
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
    }


def graph(nodes: list[dict], edges: list[dict] | None = None) -> dict:
    return {"nodes": nodes, "edges": edges or []}


def read_only_graph(tag_id: int) -> dict:
    """Um bloco OPC-Read: o grafo válido mais simples que amarra o flow a uma conexão."""
    return graph([read_node("r1", 1, tag_id)])


def counter_graph(node_id: str = "s1") -> dict:
    """Script sem entradas: com o pool-duplo, OUT1 é o contador de varreduras do bloco."""
    return graph([script_node(node_id, 1)])


# --------------------------------------------------------------------------------------
# Duplos e coletores
# --------------------------------------------------------------------------------------


class StubPool:
    """Pool-duplo: `OUT1..OUTn` viram o contador de varreduras guardado no `state`.

    Fiel ao pool real em dois pontos que os testes usam: `run` depois do `stop` levanta (é
    como o `script_error` espúrio do desligamento apareceria) e a ordem das chamadas fica
    registrada. O pool real é da tarefa 1.3 e subir processos aqui só encareceria a bateria.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.started = False
        # Sonda de ordem de desmonte: quantos flows ainda estavam rodando no instante do
        # `stop()`. O sintoma real (`script_error` espúrio) depende de uma varredura estar em
        # voo, o que é uma corrida; a contagem no instante do `stop()` é o mesmo contrato sem
        # corrida nenhuma. Quem a liga é o teste da ordem.
        self.probe: Callable[[], int] | None = None
        self.running_flows_at_stop: int | None = None

    async def start(self) -> None:
        self.started = True
        self.calls.append("start")

    async def stop(self) -> None:
        if self.probe is not None:
            self.running_flows_at_stop = self.probe()
        self.started = False
        self.calls.append("stop")

    async def run(
        self, *, code: str, inputs: dict[str, float], state: Any, n_outputs: int, timeout_s: float
    ) -> ScriptResult:
        if not self.started:
            raise RuntimeError("ScriptPool não está em execução")
        self.calls.append("run")
        count = (state or {}).get("n", 0) + 1
        outputs = {f"OUT{i}": float(count) for i in range(1, n_outputs + 1)}
        return ScriptResult(status="ok", outputs=outputs, state={"n": count}, detail=None)

    @property
    def runs_after_stop(self) -> int:
        if "stop" not in self.calls:
            return 0
        return self.calls[self.calls.index("stop") :].count("run")


@dataclass(slots=True)
class Collector:
    """Assinante de um canal: guarda os payloads crus na ordem em que chegaram."""

    received: list[str] = field(default_factory=list)

    def events(self, kind: str | None = None) -> list[EventMessage]:
        events = [EventMessage.model_validate_json(raw) for raw in list(self.received)]
        if kind is None:
            return events
        return [event for event in events if event.payload.get("kind") == kind]

    def status(self) -> list[FlowStatus]:
        return [FlowStatus.model_validate_json(raw) for raw in list(self.received)]

    def scans(self) -> list[FlowStatus]:
        """Só as publicações de varredura: transição de estado não leva `ports` (§2.2-5)."""
        return [status for status in self.status() if status.ports]


@pytest.fixture
async def collect(redis_client: Redis) -> AsyncIterator[Callable[[str], Awaitable[Collector]]]:
    """Fábrica de assinantes; a inscrição está confirmada quando a fábrica retorna."""
    pumps: list[asyncio.Task[None]] = []
    pubsubs: list[Any] = []

    async def factory(channel: str) -> Collector:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        collector = Collector()
        ready = asyncio.Event()

        async def pump() -> None:
            async for message in pubsub.listen():
                if message["type"] == "subscribe":
                    ready.set()
                elif message["type"] == "message":
                    collector.received.append(message["data"])

        pumps.append(asyncio.create_task(pump()))
        pubsubs.append(pubsub)
        await asyncio.wait_for(ready.wait(), AWAIT_TIMEOUT_S)
        return collector

    yield factory

    for pump_task in pumps:
        pump_task.cancel()
    for pump_task in pumps:
        with suppress(asyncio.CancelledError):
            await pump_task
    for pubsub in pubsubs:
        await pubsub.aclose()


@dataclass(slots=True)
class Harness:
    """Supervisor vivo com os colaboradores que os testes precisam observar."""

    supervisor: Supervisor
    state: RuntimeState
    pool: StubPool
    snapshot: ValueSnapshot
    redis: Redis
    events: ChannelListener

    async def command(self, cmd: str, flow_id: int, *, user: str = USER) -> None:
        """Publica em `flow.commands` como a API faz (spec §5.1)."""
        command = FlowCommand(flow_id=flow_id, cmd=cmd, args={}, user=user, ts=datetime.now(UTC))
        await self.redis.publish(CHANNEL_FLOW_COMMANDS, command.model_dump_json())

    def flow_state(self, flow_id: int) -> str | None:
        task = self.supervisor.flows.get(flow_id)
        return None if task is None else task.state

    async def await_state(self, flow_id: int, expected: str) -> None:
        await await_until(lambda: self.flow_state(flow_id) == expected)


@pytest.fixture
async def harness_factory(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Redis
) -> AsyncIterator[Callable[..., Awaitable[Harness]]]:
    built: list[Harness] = []

    async def factory(*, poll_interval_s: float = SLOW_POLL_S) -> Harness:
        state = RuntimeState()
        pool = StubPool()
        snapshot = ValueSnapshot(redis_client)
        supervisor = Supervisor(
            session_factory,
            redis_client,
            state,
            snapshot=snapshot,
            pool=pool,
            poll_interval_s=poll_interval_s,
        )
        # Mesma composição do lifespan de `main.py`: o assinante de `events` é quem liga o
        # contrato F2 §3.7 ao supervisor, então o arreio tem de montá-lo igual.
        events = build_event_listener(
            redis_client,
            on_comm_failure=supervisor.on_comm_failure,
            on_project_activated=supervisor.on_project_activated,
        )
        harness = Harness(supervisor, state, pool, snapshot, redis_client, events)
        built.append(harness)
        await snapshot.start()
        await supervisor.start()
        await events.start()
        return harness

    yield factory

    for harness in built:
        await harness.events.stop()
        await harness.supervisor.stop()
        await harness.snapshot.stop()


async def publish_tag_value(
    redis_client: Redis, conn_id: int, tag_id: int, value: float, *, quality: int = 0
) -> None:
    payload = OpcValue(tag_id=tag_id, ts=datetime.now(UTC), value=value, quality=quality)
    await redis_client.publish(channel_opc_values(conn_id), payload.model_dump_json())


def port_value(status: FlowStatus, block_id: str, port: str) -> float | bool | None:
    return status.ports[block_id][port].v


def counters(collector: Collector, block_id: str = "s1") -> list[float | bool | None]:
    """Sequência de OUT1 do bloco Script nas varreduras: o contador do `state` do script."""
    return [port_value(status, block_id, "OUT1") for status in collector.scans()]
