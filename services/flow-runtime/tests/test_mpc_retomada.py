"""Retomada automática pós `comm_restored` — restauração de modos/SP do bloco `mpc`
(TD-005, ADR-025).

Os cenários genéricos (flow retoma sozinho, `desired_state` parado não retoma, deploy
manual limpa a pendência) moram em `test_supervisor.py` — este arquivo isola o único
cenário que precisa de um bloco `mpc` de verdade: o snapshot pré-queda (TD-006,
`EstadoMpcTransplante`) tem de valer no bloco novo depois do redeploy automático.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from runtime_test_helpers import (
    Collector,
    Harness,
    await_until,
    create_connection,
    create_flow,
    create_project,
    create_tag,
    mpc_graph_valido,
    mpc_host_echo_plan_worker,
    publish_tag_value,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_COMM_RESTORED,
    KIND_FLOW_RESUMED,
    KIND_MPC_MODE_CHANGED,
    MpcState,
    channel_mpc_state,
    publish_event,
)

Factory = Callable[..., Awaitable[Harness]]
Collect = Callable[[str], Awaitable[Collector]]
Sessions = async_sessionmaker[AsyncSession]


async def _comm_failure(redis_client: Redis, conn_id: int) -> None:
    """Evento tal como o opc-worker o emite (spec F2 §3.7)."""
    await publish_event(
        redis_client,
        severity="alarm",
        origin=f"conn:{conn_id}",
        message=f"Conexão {conn_id} em falha",
        kind="comm_failure",
        payload={"conn_id": conn_id, "reason": "timeout"},
    )


def _last_mpc_state(collector: Collector) -> MpcState:
    return MpcState.model_validate_json(collector.received[-1])


async def test_comm_restored_restaura_modos_e_sp_do_bloco_mpc(
    harness_factory: Factory,
    collect: Collect,
    session_factory: Sessions,
    redis_client: Redis,
) -> None:
    """TD-005: o snapshot pré-queda (TD-006, `EstadoMpcTransplante`) volta a valer no
    bloco `mpc` novo — REMOTO/AUTO e o SP escrito antes da queda, não o config zerado."""
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id)
    tag_id = await create_tag(session_factory, conn_id, direction="r")
    flow_id = await create_flow(
        session_factory,
        project_id,
        graph=mpc_graph_valido(tag_id),
        desired_state="running",
        watchdog_enabled=True,
    )
    events = await collect(CHANNEL_EVENTS)
    mpc_states = await collect(channel_mpc_state(flow_id, "m1"))
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_plan_worker)

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running", timeout_s=15.0)
    runtime = harness.supervisor._runtimes[flow_id]  # noqa: SLF001
    await await_until(lambda: runtime.blocks["m1"][1].host.ready, timeout_s=15.0)
    await publish_tag_value(harness.redis, conn_id, tag_id, 90.0)
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
    await harness.command(
        "mpc_sp", flow_id, args={"block_id": "m1", "var_id": "cv_a", "value": 95.0}
    )
    await await_until(lambda: _last_mpc_state(mpc_states).vars["cv_a"].sp == 95.0)

    await _comm_failure(redis_client, conn_id)
    await harness.await_state(flow_id, "failed")

    await publish_event(
        redis_client,
        severity="info",
        origin=f"conn:{conn_id}",
        message="Conexão restaurada",
        kind=KIND_COMM_RESTORED,
        payload={"conn_id": conn_id},
    )
    await harness.await_state(flow_id, "running", timeout_s=15.0)
    await publish_tag_value(harness.redis, conn_id, tag_id, 90.0)  # entradas frias no bloco novo

    await await_until(
        lambda: bool(mpc_states.received) and _last_mpc_state(mpc_states).modes.man_auto == "auto",
        timeout_s=15.0,
    )
    final = _last_mpc_state(mpc_states)
    assert final.modes.local_remote == "remote"
    assert final.modes.man_auto == "auto"
    assert final.vars["cv_a"].sp == 95.0

    resumido = events.events(KIND_FLOW_RESUMED)
    assert len(resumido) == 1

    def _tem_auto_resume() -> bool:
        return any(
            e.payload.get("reason") == "auto_resume" for e in events.events(KIND_MPC_MODE_CHANGED)
        )

    await await_until(_tem_auto_resume, timeout_s=15.0)
    auto_resume = [
        e for e in events.events(KIND_MPC_MODE_CHANGED) if e.payload.get("reason") == "auto_resume"
    ]
    assert len(auto_resume) == 1
    assert auto_resume[0].origin == f"flow:{flow_id}/block:m1"
