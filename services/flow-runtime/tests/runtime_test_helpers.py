"""Helpers de teste do flow-runtime, importados por nome qualificado pelos arquivos de teste.

Nome próprio (não `conftest`) para não colidir com o slot de módulo `conftest` que o
`opc-worker/tests/conftest.py` também expõe via `sys.path`: um pytest que rode as duas
suítes juntas resolveria `import conftest` (nome nu) para qualquer uma das duas, a depender
da ordem de coleta — débito 8 do plano F4a.

Concentra os construtores de grafo e o arreio do supervisor (banco commitado, pool-duplo e
os duplos `Collector`/`Harness`) porque `test_supervisor.py` e `test_hotswap.py` compartilham
o mesmo cenário: fixture não atravessa módulo de teste. As fixtures (`session_factory`,
`collect`, `harness_factory`) continuam no `conftest.py`, que importa deste módulo o que
precisa para montá-las.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import (
    CHANNEL_FLOW_COMMANDS,
    EventMessage,
    FlowCommand,
    FlowStatus,
    OpcValue,
    channel_opc_values,
)
from ottima_core.models import Flow, OpcConnection, Project, Tag
from ottima_flow_runtime.events import ChannelListener
from ottima_flow_runtime.mpc.worker import SolveResult
from ottima_flow_runtime.script_pool import ScriptResult
from ottima_flow_runtime.snapshot import ValueSnapshot
from ottima_flow_runtime.state import RuntimeState
from ottima_flow_runtime.supervisor import Supervisor
from testkit.await_until import await_until

# Teto das esperas do flow-runtime: o Redis dos testes é local e o laço de reassinatura tem
# freio de 1 s, então não satisfazer a condição em 5 s é falha real, não lentidão.
AWAIT_TIMEOUT_S = 5.0
# `deploy` aqui paga `MpcHost.start()` — um `spawn` real reimportando `casadi`/`do-mpc`
# do zero no processo filho (custo de import a frio, não do solve): sob carga da máquina,
# esse boot pode passar de 5s mesmo com o worker falso.
DEPLOY_TIMEOUT_S = 30.0  # Permite boot lento do worker + solve lento inicial


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
# Atraso real e finito do boot de `mpc_host_slow_build_worker` (tarefa 4.1, F5a — F-1):
# bem além de `AWAIT_TIMEOUT_S` (a janela em que os testes provam "ainda building"/"não
# bloqueou outro flow" precisa fechar ANTES do host ficar pronto), mas dentro do
# `_BOOT_TIMEOUT_S` real de 30 s (o handshake tem de chegar, não estourar o deadline).
MPC_SLOW_BUILD_DELAY_S = 7.0
# Atraso real do solve para injetar overrun determinístico (TD-008): bem além do orçamento
# de 0.5 s (Ts padrão dos testes), forçando timeout no dispatch. Análogo a
# `mpc_host_sleeper_worker`, mas mantém worker vivo entre solves.
MPC_SLOW_SOLVE_DELAY_S = 0.6


# --------------------------------------------------------------------------------------
# Banco: helpers do cenário do supervisor (a fixture `session_factory` mora no conftest.py)
# --------------------------------------------------------------------------------------


async def create_project(
    factory: async_sessionmaker[AsyncSession], *, name: str = "Projeto", is_active: bool = True
) -> int:
    async with factory() as session:
        project = Project(name=name, description="", is_active=is_active)
        session.add(project)
        await session.commit()
        return project.id


async def create_connection(
    factory: async_sessionmaker[AsyncSession],
    project_id: int,
    *,
    name: str = "Forno 1",
    watchdog_read_node_id: str | None = "ns=2;s=WD_R",
    watchdog_write_node_id: str | None = "ns=2;s=WD_W",
) -> int:
    """Watchdog configurado por padrão (TD-004): cenários de MPC com `pid` escrevem por
    tags desta conexão de verdade, e o gate de arme (`auto_arm_blocked_reason`) bloqueia
    REMOTO sem watchdog — passe `watchdog_read_node_id=None` para simular a conexão sem
    watchdog nos testes que exercitam esse gate."""
    async with factory() as session:
        connection = OpcConnection(
            project_id=project_id,
            name=name,
            endpoint="opc.tcp://inexistente:4840",
            security_policy="none",
            security_mode="none",
            auth_mode="anonymous",
            watchdog_read_node_id=watchdog_read_node_id,
            watchdog_write_node_id=watchdog_write_node_id,
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


def mpc_graph_valido(
    tag_id: int, *, node_id: str = "m1", du_max: float = 5.0, weight: float = 1.0
) -> dict:
    """Esqueleto mínimo válido do §2.1 (spec F4): 1 MV direta + 1 CV, matriz cheia.

    Compartilhado entre `test_supervisor.py` (deploy), `test_hotswap.py` (reload) e
    `test_mpc_boot_async.py` (tarefa 4.2 F5a — F-1, reload com host novo: `du_max`
    muda config funcional sem afetar horizontes/validação, §4.1-3, mesmo truque de
    `test_supervisor_mpc.py::mpc_graph_com_pid`). A CV entra pela porta obrigatória
    (decisão A-10): precisa de 1 leitor OPC dedicado.
    """
    mpc = node(
        node_id,
        "mpc",
        2,
        {
            "name": "MPC teste",
            "multiplier": 1,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_a",
                        "name": "MV a",
                        "eu": "m3/h",
                        "limits": {"min": 0.0, "max": 100.0},
                        "du_max": du_max,
                        "initial_value": 0.0,
                    }
                ],
                "cvs": [
                    {
                        "id": "cv_a",
                        "name": "CV a",
                        "eu": "C",
                        "kind": "selfreg",
                        "tss": 30.0,
                        "weight": weight,
                        "sp_limits": {"min": 80.0, "max": 120.0},
                    }
                ],
                "constraints": [],
                "dvs": [],
            },
            "models": {
                "cv_a": {
                    "mv_a": {
                        "enabled": True,
                        "params": {"K": 1.2, "tau1": 10.0, "tau2": 2.0, "theta": 15.0},
                    }
                }
            },
        },
    )
    return graph([read_node("r1", 1, tag_id), mpc], [edge("r1", "out", node_id, "cv_a")])


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

    def stats(self) -> dict:
        """Espelha o contrato de `ScriptPool.stats()` (F4a 0.6, spec F4 §4.10) — sem
        processos reais, só as chaves que `Supervisor.script_pool_stats()` repassa."""
        return {"size": 0, "busy": 0, "respawns": 0}

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


@dataclass(slots=True)
class Harness:
    """Supervisor vivo com os colaboradores que os testes precisam observar."""

    supervisor: Supervisor
    state: RuntimeState
    pool: StubPool
    snapshot: ValueSnapshot
    redis: Redis
    events: ChannelListener

    async def command(
        self, cmd: str, flow_id: int, *, user: str = USER, args: dict[str, Any] | None = None
    ) -> None:
        """Publica em `flow.commands` como a API faz (spec §5.1)."""
        command = FlowCommand(
            flow_id=flow_id, cmd=cmd, args=args or {}, user=user, ts=datetime.now(UTC)
        )
        await self.redis.publish(CHANNEL_FLOW_COMMANDS, command.model_dump_json())

    def flow_state(self, flow_id: int) -> str | None:
        task = self.supervisor.flows.get(flow_id)
        return None if task is None else task.state

    async def await_state(self, flow_id: int, expected: str, *, timeout_s: float = 5.0) -> None:
        await await_until(lambda: self.flow_state(flow_id) == expected, timeout_s=timeout_s)


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


# --------------------------------------------------------------------------------------
# Workers falsos de `mpc.host` (test_mpc_host.py) — nível de MÓDULO PROPRIAMENTE
# IMPORTÁVEL: `spawn` precisa reimportá-los por nome qualificado num interpretador novo, e
# só um módulo real neste diretório inserido em `sys.path` (ver `conftest.py`) sobrevive a
# isso — um módulo de teste sob `--import-mode=importlib` não tem um nome pontilhado
# resolvível de fora do pytest (mesma razão de `worker_main` viver em `ottima_flow_runtime`
# e não dentro de `test_mpc_worker.py`).
# --------------------------------------------------------------------------------------


def mpc_host_ok_result(*, detail: str = "") -> SolveResult:
    return SolveResult(
        u_plan={},
        prediction_t=[],
        prediction_cv=[],
        prediction_mv=[],
        cost=0.0,
        status="ok",
        wall_ms=1.0,
        detail=detail,
    )


def mpc_host_echo_worker(conn: Connection, config_json: str, ts_flow: float) -> None:
    """Fica pronto na hora e responde `status=ok` a todo pedido — usado nos testes que só
    observam o ciclo de vida do processo, não o conteúdo do resultado."""
    conn.send(("ready", 1))
    try:
        while True:
            request = conn.recv()
            if request is None:
                return
            conn.send(mpc_host_ok_result())
    except (EOFError, OSError):
        return


def mpc_host_reinit_capturing_worker(conn: Connection, config_json: str, ts_flow: float) -> None:
    """Ecoa `request.reinit` no campo `detail` da resposta — prova o que o host realmente
    mandou pelo pipe, sem expor estado interno do host ao teste."""
    conn.send(("ready", 1))
    try:
        while True:
            request = conn.recv()
            if request is None:
                return
            conn.send(mpc_host_ok_result(detail=str(request.reinit)))
    except (EOFError, OSError):
        return


def mpc_host_sleeper_worker(conn: Connection, config_json: str, ts_flow: float) -> None:
    """Fica pronto na hora, mas nunca responde a um pedido — prova o kill no deadline de
    forma determinística (sem depender de timing do solver real)."""
    import time

    conn.send(("ready", 1))
    try:
        while True:
            request = conn.recv()
            if request is None:
                return
            time.sleep(10.0)  # bem além de qualquer deadline usado na suíte de MpcHost
    except (EOFError, OSError):
        return


def mpc_host_dying_on_request_worker(conn: Connection, config_json: str, ts_flow: float) -> None:
    """Fica pronto na hora, mas morre (`os._exit`, sem responder) assim que recebe o
    PRIMEIRO pedido — prova o caminho de crash-EM-VOO (spec §4.9: `_receive` vê EOF/erro de
    SO no meio da espera de um dispatch, não um `dispatch()` idle notando `is_alive()`
    depois). `os._exit` (não `sys.exit`/exceção) porque precisa fechar o processo sem passar
    pelo `finally: conn.close()` do laço normal — mais perto de um crash real."""
    import os

    conn.send(("ready", 1))
    conn.recv()
    os._exit(1)


def mpc_host_echo_plan_worker(conn: Connection, config_json: str, ts_flow: float) -> None:
    """Fica pronto na hora e responde `status=ok` com `u_plan = u_applied` do próprio
    pedido (mantém a MV vigente) — `mpc_host_echo_worker` devolve `u_plan={}`, que faz
    `MpcBlock._compute_outputs` estourar `KeyError` assim que um teste de integração
    (supervisor, plano F4b tarefa 2.2) deixa o bloco entrar em AUTO de verdade; este worker
    existe só para isso, sem pagar o custo de um solve real."""
    conn.send(("ready", 1))
    try:
        while True:
            request = conn.recv()
            if request is None:
                return
            conn.send(
                SolveResult(
                    u_plan=dict(request.u_applied),
                    prediction_t=[],
                    prediction_cv=[],
                    prediction_mv=[],
                    cost=0.0,
                    status="ok",
                    wall_ms=1.0,
                    detail="",
                )
            )
    except (EOFError, OSError):
        return


def mpc_host_never_ready_worker(conn: Connection, config_json: str, ts_flow: float) -> None:
    """Nunca manda o handshake `("ready", n_x)` — o host fica com `ready=False` para
    sempre (usado para exercitar o gate `worker_not_ready` de MAN->AUTO, spec F4 §4.4,
    plano F4b tarefa 2.2, sem esperar o `_BOOT_TIMEOUT_S` de 30 s do host de verdade)."""
    import time

    while True:
        time.sleep(3600)


def mpc_host_slow_build_worker(conn: Connection, config_json: str, ts_flow: float) -> None:
    """Atraso real e finito (`MPC_SLOW_BUILD_DELAY_S`) antes do handshake `("ready", n_x)`
    — prova o boot assíncrono do host MPC (spec F5 §6.1/§6.2, tarefa 4.1 F5a — F-1): fica
    "building" por um tempo bem além de `AWAIT_TIMEOUT_S`, mas termina o boot de verdade
    (ao contrário de `mpc_host_never_ready_worker`) e passa a ecoar `status=ok` com
    `u_plan = u_applied` do próprio pedido — mesmo corpo de `mpc_host_echo_plan_worker`,
    só com o atraso na frente."""
    import time

    time.sleep(MPC_SLOW_BUILD_DELAY_S)
    conn.send(("ready", 1))
    try:
        while True:
            request = conn.recv()
            if request is None:
                return
            conn.send(
                SolveResult(
                    u_plan=dict(request.u_applied),
                    prediction_t=[],
                    prediction_cv=[],
                    prediction_mv=[],
                    cost=0.0,
                    status="ok",
                    wall_ms=1.0,
                    detail="",
                )
            )
    except (EOFError, OSError):
        return


def mpc_host_slow_solve_worker(conn: Connection, config_json: str, ts_flow: float) -> None:
    """TD-008: Atraso real no SOLVE (não no boot) para forçar overrun determinístico.
    Fica pronto na hora, mas cada solve leva `MPC_SLOW_SOLVE_DELAY_S` (~0.6s) — bem além
    do orçamento de `Ts = 0.5s` dos testes, causando timeout e overrun. Análogo a
    `mpc_host_sleeper_worker`, mas responde depois do atraso (worker vivo, não pendurado)."""
    import time

    conn.send(("ready", 1))
    try:
        while True:
            request = conn.recv()
            if request is None:
                return
            time.sleep(MPC_SLOW_SOLVE_DELAY_S)
            conn.send(
                SolveResult(
                    u_plan=dict(request.u_applied),
                    prediction_t=[],
                    prediction_cv=[],
                    prediction_mv=[],
                    cost=0.0,
                    status="ok",
                    wall_ms=float(MPC_SLOW_SOLVE_DELAY_S * 1000),
                    detail="",
                )
            )
    except (EOFError, OSError):
        return
