"""Hot-swap com transplante de estado do bloco `mpc` (TD-006, ADR-011).

Sintonia muda (peso de CV, `max_rate` etc.) com o MESMO conjunto de MVs: o bloco novo nasce
com os modos/últimos valores/SPs do bloco velho em vez de zerado em LOCAL — o operador não
vê o controle cair só porque um parâmetro de ajuste mudou. Conjunto de MVs mudado (ou Ts do
flow) continua reiniciando para LOCAL, comportamento herdado do ADR-011.

Usa `mpc_graph_valido` (MV direta, sem `pid`) — mais simples que `mpc_graph_com_pid`
(`test_supervisor_mpc.py`): não há confirmação/shed de PID no caminho testado aqui, só o
transplante de estado do próprio bloco. `mpc_host_echo_plan_worker` ecoa `u_applied` como
`u_plan` — a MV não desliza sozinha entre solves, então "sem salto" é observável comparando
o valor publicado antes e depois do hot-swap.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from runtime_test_helpers import (
    DEPLOY_TIMEOUT_S,
    Collector,
    Harness,
    await_until,
    create_connection,
    create_flow,
    create_project,
    create_tag,
    edge,
    graph,
    mpc_graph_valido,
    mpc_host_echo_plan_worker,
    node,
    publish_tag_value,
    read_node,
    save_graph,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import CHANNEL_EVENTS, KIND_MPC_MODE_CHANGED, MpcState, channel_mpc_state

Factory = Callable[..., Awaitable[Harness]]
Collect = Callable[[str], Awaitable[Collector]]
Sessions = async_sessionmaker[AsyncSession]


def _mpc_graph_2_mvs(tag_id: int, *, node_id: str = "m1") -> dict:
    """Mesmo esqueleto de `mpc_graph_valido`, com uma 2a MV: o CONJUNTO de MVs muda, então
    o hot-swap correspondente NÃO transplanta — reinicia para LOCAL como sempre (ADR-011)."""
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
                        "max_rate": 5.0,
                        "initial_value": 0.0,
                    },
                    {
                        "id": "mv_b",
                        "name": "MV b",
                        "eu": "m3/h",
                        "limits": {"min": 0.0, "max": 100.0},
                        "max_rate": 5.0,
                        "initial_value": 0.0,
                    },
                ],
                "cvs": [
                    {
                        "id": "cv_a",
                        "name": "CV a",
                        "eu": "C",
                        "kind": "selfreg",
                        "tss": 30.0,
                        "weight": 1.0,
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
                    },
                    "mv_b": {
                        "enabled": True,
                        "params": {"K": 0.5, "tau1": 8.0, "tau2": 1.0, "theta": 5.0},
                    },
                }
            },
        },
    )
    return graph([read_node("r1", 1, tag_id), mpc], [edge("r1", "out", node_id, "cv_a")])


def _last_mpc_state(collector: Collector) -> MpcState:
    return MpcState.model_validate_json(collector.received[-1])


async def _deploy_arma_auto(
    harness: Harness, mpc_states: Collector, *, connection_id: int, tag_id: int, flow_id: int
) -> None:
    """Sobe o flow, aquece a entrada e arma REMOTO+AUTO — mesmo caminho dos 3 testes deste
    arquivo, então mora num helper só."""
    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running", timeout_s=DEPLOY_TIMEOUT_S)
    runtime = harness.supervisor._runtimes[flow_id]  # noqa: SLF001
    await await_until(lambda: runtime.blocks["m1"][1].host.ready, timeout_s=DEPLOY_TIMEOUT_S)
    await publish_tag_value(harness.redis, connection_id, tag_id, 90.0)
    await await_until(
        lambda: bool(mpc_states.received) and _last_mpc_state(mpc_states).status.input_valid
    )
    await harness.command(
        "mpc_mode", flow_id, args={"block_id": "m1", "axis": "local_remote", "value": "remote"}
    )
    await harness.command(
        "mpc_mode", flow_id, args={"block_id": "m1", "axis": "man_auto", "value": "auto"}
    )
    await await_until(lambda: _last_mpc_state(mpc_states).modes.man_auto == "auto")


async def test_reload_com_peso_de_cv_mudado_preserva_remoto_auto_sem_salto_na_mv(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """TD-006: sintonia mudou (peso da CV), MVs iguais -> `man_auto` continua "auto" e a
    MV não pula — o solve seguinte parte do mesmo `mv_last`, não do `initial_value`."""
    project_id = await create_project(session_factory)
    connection_id = await create_connection(session_factory, project_id)
    tag_id = await create_tag(session_factory, connection_id, direction="r")
    flow_id = await create_flow(
        session_factory, project_id, graph=mpc_graph_valido(tag_id), watchdog_enabled=True
    )
    events = await collect(CHANNEL_EVENTS)
    mpc_states = await collect(channel_mpc_state(flow_id, "m1"))
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_plan_worker)

    await _deploy_arma_auto(
        harness, mpc_states, connection_id=connection_id, tag_id=tag_id, flow_id=flow_id
    )
    bloco_antes = harness.supervisor._runtimes[flow_id].blocks["m1"][1]  # noqa: SLF001
    mv_antes = _last_mpc_state(mpc_states).vars["mv_a"].v

    baseline = len(events.events(KIND_MPC_MODE_CHANGED))
    changed_graph = mpc_graph_valido(tag_id, weight=3.0)
    await save_graph(session_factory, flow_id, changed_graph)
    await harness.command("reload", flow_id)

    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) > baseline)
    bumpless = events.events(KIND_MPC_MODE_CHANGED)[-1]
    assert bumpless.payload == {"kind": KIND_MPC_MODE_CHANGED, "reason": "hot_swap_bumpless"}

    novo_bloco = harness.supervisor._runtimes[flow_id].blocks["m1"][1]  # noqa: SLF001
    assert novo_bloco is not bloco_antes, "hot-swap tem de trocar a instância"
    assert novo_bloco.local_remote == "remote"

    await await_until(
        lambda: (
            len(mpc_states.received) > 0 and _last_mpc_state(mpc_states).modes.man_auto == "auto"
        )
    )
    depois = _last_mpc_state(mpc_states)
    assert depois.modes.local_remote == "remote"
    assert depois.modes.man_auto == "auto"
    assert depois.vars["mv_a"].v == mv_antes, "MV não pode saltar no hot-swap bumpless"


async def test_reload_com_mv_adicionada_reseta_para_local(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """TD-006: conjunto de MVs mudou -> comportamento ATUAL preservado (reset para LOCAL,
    ADR-011); só a config mudar SEM mudar as MVs é que transplanta."""
    project_id = await create_project(session_factory)
    connection_id = await create_connection(session_factory, project_id)
    tag_id = await create_tag(session_factory, connection_id, direction="r")
    flow_id = await create_flow(
        session_factory, project_id, graph=mpc_graph_valido(tag_id), watchdog_enabled=True
    )
    events = await collect(CHANNEL_EVENTS)
    mpc_states = await collect(channel_mpc_state(flow_id, "m1"))
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_plan_worker)

    await _deploy_arma_auto(
        harness, mpc_states, connection_id=connection_id, tag_id=tag_id, flow_id=flow_id
    )

    baseline = len(events.events(KIND_MPC_MODE_CHANGED))
    await save_graph(session_factory, flow_id, _mpc_graph_2_mvs(tag_id))
    await harness.command("reload", flow_id)

    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) > baseline)
    hot_swap = events.events(KIND_MPC_MODE_CHANGED)[-1]
    assert hot_swap.payload == {"kind": KIND_MPC_MODE_CHANGED, "reason": "hot_swap"}

    novo_bloco = harness.supervisor._runtimes[flow_id].blocks["m1"][1]  # noqa: SLF001
    assert novo_bloco.local_remote == "local", "MV nova: reset para LOCAL, não transplante"


async def test_reload_com_config_identico_preserva_a_mesma_instancia(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """Regressão do reuse existente (ADR-011): grafo idêntico não instancia bloco novo
    nenhum — nem transplante, nem reset, a MESMA instância segue no ar."""
    project_id = await create_project(session_factory)
    connection_id = await create_connection(session_factory, project_id)
    tag_id = await create_tag(session_factory, connection_id, direction="r")
    original_graph = mpc_graph_valido(tag_id)
    flow_id = await create_flow(session_factory, project_id, graph=original_graph)
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_plan_worker)

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running", timeout_s=DEPLOY_TIMEOUT_S)
    runtime = harness.supervisor._runtimes[flow_id]  # noqa: SLF001
    bloco_antes = runtime.blocks["m1"][1]

    await save_graph(session_factory, flow_id, original_graph)
    await harness.command("reload", flow_id)
    await await_until(lambda: runtime.updated_at is not None)

    assert events.events(KIND_MPC_MODE_CHANGED) == [], "config igual não é hot-swap nenhum"
    assert harness.supervisor._runtimes[flow_id].blocks["m1"][1] is bloco_antes  # noqa: SLF001
