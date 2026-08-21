"""Persistência do SP do operador do bloco MPC (orch-change-feature 2026-08-20).

O defeito fechado aqui: `MpcBlock.reset()` semeava `_sp` em 0.0 em TODO deploy/stop/
restart, então o SP que o operador escreveu em AUTO morria no primeiro redeploy ou
reinício do serviço. A decisão A-4 da spec F4 ("nada de modos/SP/MV manual persiste no
banco") foi emendada: o NÚMERO do SP persiste em `mpc_setpoints` (Postgres), os MODOS
seguem voláteis (boot sempre LOCAL+MAN, RNF-03 intacto).

Cobertura deste arquivo (nível supervisor, Redis + Postgres reais, worker eco):

1. `mpc_sp` materializado grava a linha em `mpc_setpoints` com o valor JÁ clampado;
2. stop + redeploy restaura o SP persistido (CV `track_sp=False` — sem tracking para
   colar o SP no PV de novo, o valor visto É a semente);
3. redeploy SEM SP persistido nasce zerado (a semente não vaza entre blocos);
4. redeploy com `track_sp=True` segue rastreando o PV fora de AUTO (RF-612 intacto —
   a semente não congela o tracking);
5. delete do flow cascateia as linhas (FK `flows` ON DELETE CASCADE).

O caso comm_restored (transplante de estado, TD-006) já é coberto por
`test_mpc_retomada.py` — aqui só os caminhos que RECONSTROEM o bloco do zero.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from runtime_test_helpers import (
    AWAIT_TIMEOUT_S,
    USER,
    Collector,
    Harness,
    await_until,
    create_connection,
    create_flow,
    create_project,
    create_tag,
    delete_flow,
    mpc_host_echo_plan_worker,
    publish_tag_value,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_supervisor_mpc import (
    DEPLOY_TIMEOUT_S,
    TS_SECONDS,
    _arm_args,
    _deploy_and_warm,
    _last_mpc_state,
    mpc_graph_com_pid,
)

from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_MPC_MODE_CHANGED,
    KIND_MPC_SP_WRITTEN,
    channel_mpc_state,
)

Factory = Callable[..., Awaitable[Harness]]
Collect = Callable[[str], Awaitable[Collector]]
Sessions = async_sessionmaker[AsyncSession]

SP_OPERADOR = 95.0
PV_QUENTE = 90.0


async def _scenario(session_factory: Sessions, *, track_sp: bool = True) -> dict:
    """Mesmo cenário do `test_supervisor_mpc._scenario`; `track_sp=False` desliga o
    PV-tracking da CV — necessário para enxergar a semente persistida sem o tracking
    colando o SP no PV na primeira varredura quente."""
    project_id = await create_project(session_factory)
    connection_id = await create_connection(session_factory, project_id)
    cv_tag_id = await create_tag(session_factory, connection_id, name="cv", direction="r")
    write_tag_id = await create_tag(session_factory, connection_id, name="write", direction="w")
    mode_cmd_tag_id = await create_tag(
        session_factory, connection_id, name="mode_cmd", direction="w"
    )
    readback_tag_id = await create_tag(
        session_factory, connection_id, name="readback", direction="r"
    )
    mode_read_tag_id = await create_tag(
        session_factory, connection_id, name="mode_read", direction="r"
    )
    grafo = mpc_graph_com_pid(
        cv_tag_id=cv_tag_id,
        write_tag_id=write_tag_id,
        mode_cmd_tag_id=mode_cmd_tag_id,
        readback_tag_id=readback_tag_id,
        mode_read_tag_id=mode_read_tag_id,
    )
    if not track_sp:
        for no in grafo["nodes"]:
            if no["type"] == "mpc":
                no["data"]["variables"]["cvs"][0]["track_sp"] = False
    flow_id = await create_flow(
        session_factory,
        project_id,
        graph=grafo,
        ts_seconds=TS_SECONDS,
        watchdog_enabled=True,
    )
    return {
        "project_id": project_id,
        "connection_id": connection_id,
        "cv_tag_id": cv_tag_id,
        "readback_tag_id": readback_tag_id,
        "flow_id": flow_id,
    }


async def _escreve_sp_em_auto(harness: Harness, collect: Collect, scenario: dict) -> Collector:
    """Arma REMOTO+AUTO e escreve o SP do operador — devolve o coletor de `mpc.state`."""
    events = await collect(CHANNEL_EVENTS)
    mpc_states = await _deploy_and_warm(harness, collect, scenario)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)
    await harness.command(
        "mpc_mode",
        scenario["flow_id"],
        args={"block_id": "m1", "axis": "man_auto", "value": "auto"},
    )
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 2)

    await harness.command(
        "mpc_sp",
        scenario["flow_id"],
        args={"block_id": "m1", "var_id": "cv_a", "value": SP_OPERADOR},
    )
    await await_until(lambda: len(events.events(KIND_MPC_SP_WRITTEN)) == 1)
    await await_until(lambda: _last_mpc_state(mpc_states).vars["cv_a"].sp == SP_OPERADOR)
    return mpc_states


async def _linhas_sp(session_factory: Sessions, flow_id: int) -> list[tuple[str, float]]:
    async with session_factory() as session:
        resultado = await session.execute(
            text("SELECT var_id, value FROM mpc_setpoints WHERE flow_id = :flow_id"),
            {"flow_id": flow_id},
        )
        return [(var_id, float(value)) for var_id, value in resultado.all()]


async def _tem_linhas_sp(session_factory: Sessions, flow_id: int) -> bool:
    """Condição assíncrona para `await_until` (que aceita `Awaitable[bool]`): a linha
    persistida chega fire-and-forget DEPOIS do evento de SP — a espera cobre o atraso."""
    return await _linhas_sp(session_factory, flow_id) != []


async def test_comando_mpc_sp_grava_linha_clampada_em_mpc_setpoints(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """O banco guarda exatamente o valor materializado: comando acima de `sp_limits.max`
    grava o valor clampado (200.0), não o pedido bruto."""
    scenario = await _scenario(session_factory)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_plan_worker)
    await _escreve_sp_em_auto(harness, collect, scenario)

    await harness.command(
        "mpc_sp",
        scenario["flow_id"],
        args={"block_id": "m1", "var_id": "cv_a", "value": 9999.0},
    )

    async def _sp_clampado() -> bool:
        return await _linhas_sp(session_factory, scenario["flow_id"]) == [("cv_a", 200.0)]

    await await_until(_sp_clampado)

    assert await _linhas_sp(session_factory, scenario["flow_id"]) == [("cv_a", 200.0)]


async def test_stop_e_redeploy_restauram_sp_sem_tracking(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """Coração da mudança: stop + redeploy com `track_sp=False` — a primeira varredura
    quente publica o SP persistido (95.0), não 0.0 nem o PV. Modo segue volátil: o bloco
    volta LOCAL, RNF-03 intacto."""
    scenario = await _scenario(session_factory, track_sp=False)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_plan_worker)
    await _escreve_sp_em_auto(harness, collect, scenario)

    await harness.command("stop", scenario["flow_id"], user=USER)
    await harness.await_state(scenario["flow_id"], "stopped")

    mpc_states = await collect(channel_mpc_state(scenario["flow_id"], "m1"))
    await harness.command("deploy", scenario["flow_id"], user=USER)
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)
    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["cv_tag_id"], PV_QUENTE
    )
    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["readback_tag_id"], 10.0
    )

    await await_until(
        lambda: bool(mpc_states.received) and _last_mpc_state(mpc_states).status.input_valid,
        timeout_s=AWAIT_TIMEOUT_S,
    )
    final = _last_mpc_state(mpc_states)
    assert final.modes.local_remote == "local", "modo permanece volátil (boot LOCAL)"
    assert final.vars["cv_a"].sp == SP_OPERADOR, "SP do operador volta da persistência"


async def test_redeploy_sem_sp_persistido_nasce_zero(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """Sem escrita do operador, `mpc_setpoints` não tem linha e o bloco nasce zerado —
    a semente não vaza de outro flow/bloco."""
    scenario = await _scenario(session_factory, track_sp=False)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_plan_worker)
    mpc_states = await collect(channel_mpc_state(scenario["flow_id"], "m1"))

    await harness.command("deploy", scenario["flow_id"], user=USER)
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)
    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["cv_tag_id"], PV_QUENTE
    )

    await await_until(
        lambda: bool(mpc_states.received) and _last_mpc_state(mpc_states).status.input_valid,
        timeout_s=AWAIT_TIMEOUT_S,
    )
    assert _last_mpc_state(mpc_states).vars["cv_a"].sp == 0.0


async def test_redeploy_com_track_sp_segue_rastreando_pv(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """Com `track_sp=True` (default), o SP persistido NÃO congela o tracking: após o
    redeploy, a primeira varredura quente cola o SP no PV (RF-612 intacto)."""
    scenario = await _scenario(session_factory)  # track_sp=True
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_plan_worker)
    await _escreve_sp_em_auto(harness, collect, scenario)

    await harness.command("stop", scenario["flow_id"], user=USER)
    await harness.await_state(scenario["flow_id"], "stopped")

    mpc_states = await collect(channel_mpc_state(scenario["flow_id"], "m1"))
    await harness.command("deploy", scenario["flow_id"], user=USER)
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)
    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["cv_tag_id"], PV_QUENTE
    )
    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["readback_tag_id"], 10.0
    )

    await await_until(
        lambda: bool(mpc_states.received) and _last_mpc_state(mpc_states).status.input_valid,
        timeout_s=AWAIT_TIMEOUT_S,
    )
    assert _last_mpc_state(mpc_states).vars["cv_a"].sp == PV_QUENTE


async def test_delete_flow_cascata_limpa_mpc_setpoints(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """FK `flows` ON DELETE CASCADE: apagar o flow leva as linhas de SP junto — nada de
    semente órfã ressuscitando num flow recriado com o mesmo id de sequência."""
    scenario = await _scenario(session_factory)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_plan_worker)
    await _escreve_sp_em_auto(harness, collect, scenario)
    await await_until(lambda: _tem_linhas_sp(session_factory, scenario["flow_id"]))

    await delete_flow(session_factory, scenario["flow_id"])

    assert await _linhas_sp(session_factory, scenario["flow_id"]) == []
