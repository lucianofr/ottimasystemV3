"""Lock reescopado + stop sem órfão (spec F5 §6.3/§6.5; F5R-06; tarefa 4.2, plano F5a —
continuação do F-1 da tarefa 4.1: boot assíncrono do worker MPC).

A tarefa 4.1 tirou `host.start()` do caminho síncrono do lock global no deploy. Sem
reescopar o resto, o MESMO bloqueio de até `_BOOT_TIMEOUT_S = 30 s` (`MpcHost.stop()`
esperando um boot em voo, `mpc/host.py::stop`) só MIGRA para o `stop`/`reload` — os dois
CONTINUAM chamando `MpcHost.stop()` de forma síncrona, no MESMO canal sequencial de
`flow.commands` (`ottima_core.pubsub._ResilientSubscriber._listen`: `async for message in
pubsub.listen(): await self._safe_dispatch(message)` — a PRÓXIMA mensagem só é lida depois
que o handler da atual retorna). Esta suíte prova as 3 latências que a spec pede (a/b/c) e
que o desmonte destacado (`MpcOrchestrator.detach_hosts` + `stop_host_background`) não
abandona o processo do worker (`stats()["alive"]` falso e PID reaped do SO).

Usa `mpc_graph_valido`/`mpc_host_slow_build_worker` (`runtime_test_helpers.py`, herdados
da tarefa 4.1): os testes desta tarefa não armam REMOTO/AUTO — só o ciclo de vida do host
(deploy/stop/reload) importa aqui, então `mpc_graph_valido` (sem `pid`) basta; a tabela de
transições §4.4 com `pid` completo já está coberta por `test_supervisor_mpc.py`.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from runtime_test_helpers import (
    AWAIT_TIMEOUT_S,
    MPC_SLOW_BUILD_DELAY_S,
    TS_SECONDS,
    Harness,
    await_until,
    create_connection,
    create_flow,
    create_project,
    create_tag,
    mpc_graph_valido,
    mpc_host_slow_build_worker,
    read_only_graph,
    save_graph,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Factory = Callable[..., Awaitable[Harness]]
Sessions = async_sessionmaker[AsyncSession]

DEPLOY_TIMEOUT_S = 15.0
"""Mesmo piso de `test_supervisor_mpc.py`: sob carga da máquina, o spawn real do processo
filho pode passar de `AWAIT_TIMEOUT_S` mesmo sem pagar `MPC_SLOW_BUILD_DELAY_S` (o deploy
em si, pós tarefa 4.1, não espera o boot — só o spawn do supervisor até `task.start()`)."""


async def _mpc_scenario(session_factory: Sessions) -> dict:
    """Projeto + conexão + tag CV + flow com `mpc_graph_valido` (sem `pid`: esta tarefa
    prova o ciclo de vida do host — deploy/stop/reload —, não a tabela de transições de
    armar, que já é de `test_supervisor_mpc.py`)."""
    project_id = await create_project(session_factory)
    connection_id = await create_connection(session_factory, project_id)
    cv_tag_id = await create_tag(session_factory, connection_id, name="cv", direction="r")
    flow_id = await create_flow(
        session_factory, project_id, graph=mpc_graph_valido(cv_tag_id), ts_seconds=TS_SECONDS
    )
    return {
        "project_id": project_id,
        "connection_id": connection_id,
        "cv_tag_id": cv_tag_id,
        "flow_id": flow_id,
    }


async def _outro_flow(session_factory: Sessions, scenario: dict) -> int:
    """Flow B: sem bloco `mpc`, na MESMA conexão — sonda de latência que não paga
    nenhum custo de build, só o vaivém normal do supervisor."""
    other_tag_id = await create_tag(
        session_factory, scenario["connection_id"], name="outro", direction="r"
    )
    return await create_flow(
        session_factory,
        scenario["project_id"],
        graph=read_only_graph(other_tag_id),
        name="Flow B",
        ts_seconds=TS_SECONDS,
    )


# --------------------------------------------------------------------------------------
# (a) deploy de flow MPC pesado não bloqueia stop/deploy de outro flow — regressão da
#     tarefa 4.1 (spec F5 §6.1), reafirmada aqui porque a 4.2 mexe no MESMO canal
#     sequencial de `flow.commands` que a 4.1 já provou não travar mais no deploy.
# --------------------------------------------------------------------------------------


async def test_a_deploy_de_flow_mpc_pesado_nao_bloqueia_stop_e_deploy_de_outro_flow(
    harness_factory: Factory, session_factory: Sessions
) -> None:
    scenario = await _mpc_scenario(session_factory)
    flow_b_id = await _outro_flow(session_factory, scenario)
    harness = await harness_factory(mpc_worker_target=mpc_host_slow_build_worker)

    await harness.command("deploy", flow_b_id)
    await harness.await_state(flow_b_id, "running", timeout_s=DEPLOY_TIMEOUT_S)

    await harness.command("deploy", scenario["flow_id"])  # host leva MPC_SLOW_BUILD_DELAY_S
    await harness.command("stop", flow_b_id)  # mesma fila, logo depois

    await harness.await_state(flow_b_id, "stopped", timeout_s=AWAIT_TIMEOUT_S)


# --------------------------------------------------------------------------------------
# (b) reload de flow MPC pesado não bloqueia comando de outro flow — spec F5 §6.3:
#     `reconcile_mpc_hosts` (hot-swap) esperava `await old_host.stop()` de forma síncrona;
#     o host VELHO ainda está no meio do próprio build (`MPC_SLOW_BUILD_DELAY_S`) quando o
#     reload troca a config e manda desmontá-lo.
# --------------------------------------------------------------------------------------


async def test_b_reload_de_flow_mpc_pesado_nao_bloqueia_comando_de_outro_flow(
    harness_factory: Factory, session_factory: Sessions
) -> None:
    scenario = await _mpc_scenario(session_factory)
    flow_b_id = await _outro_flow(session_factory, scenario)
    harness = await harness_factory(mpc_worker_target=mpc_host_slow_build_worker)

    await harness.command("deploy", flow_b_id)
    await harness.await_state(flow_b_id, "running", timeout_s=DEPLOY_TIMEOUT_S)

    await harness.command("deploy", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)
    # host "m1" ainda está subindo (MPC_SLOW_BUILD_DELAY_S=7s) quando o reload chega.

    changed_graph = mpc_graph_valido(scenario["cv_tag_id"], max_rate=12.0)  # host novo (§4.1-3)
    await save_graph(session_factory, scenario["flow_id"], changed_graph)
    await harness.command("reload", scenario["flow_id"])  # host velho, em build, precisa parar
    await harness.command("stop", flow_b_id)  # mesma fila, logo depois

    await harness.await_state(flow_b_id, "stopped", timeout_s=AWAIT_TIMEOUT_S)


# --------------------------------------------------------------------------------------
# (c) stop de flow em build não bloqueia deploy de outro flow — a inversão que o E2E não
#     cobre (§9.1): `Supervisor._stop` chamava `shutdown_mpc` (que espera
#     `MpcHost.stop()`) de forma síncrona. Órfão (spec F5 §6.5): `host.py` (comportamento
#     pré-existente, intocado por esta tarefa) já marca `_stopped` primeiro, espera a
#     thread de spawn concluir e só então mata+junta o processo — esta suíte prova que o
#     desmonte DESTACADO (fora do lock/canal síncrono) preserva essa garantia.
# --------------------------------------------------------------------------------------


async def test_c_stop_de_flow_em_build_nao_bloqueia_deploy_de_outro_flow_e_nao_deixa_orfao(
    harness_factory: Factory, session_factory: Sessions
) -> None:
    scenario = await _mpc_scenario(session_factory)
    flow_b_id = await _outro_flow(session_factory, scenario)
    harness = await harness_factory(mpc_worker_target=mpc_host_slow_build_worker)

    await harness.command("deploy", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)
    runtime = harness.supervisor._runtimes[scenario["flow_id"]]  # noqa: SLF001
    host = runtime.blocks["m1"][1].host
    await await_until(lambda: host._proc is not None, timeout_s=AWAIT_TIMEOUT_S)  # noqa: SLF001
    proc_pid = host._proc.pid  # noqa: SLF001

    await harness.command("stop", scenario["flow_id"])  # host ainda em build (7s)
    await harness.command("deploy", flow_b_id)  # mesma fila, logo depois

    await harness.await_state(flow_b_id, "running", timeout_s=AWAIT_TIMEOUT_S)

    # Órfão: dentro da janela do build + margem, o host morre (stats()["alive"] falso) e o
    # PID some do processo do SO (morto E juntado — não só desconectado do MpcHost).
    await await_until(
        lambda: host.stats()["alive"] is False,
        timeout_s=MPC_SLOW_BUILD_DELAY_S + AWAIT_TIMEOUT_S,
    )

    def _processo_reaped() -> bool:
        try:
            os.kill(proc_pid, 0)
        except ProcessLookupError:
            return True
        return False

    await await_until(_processo_reaped, timeout_s=AWAIT_TIMEOUT_S)


# --------------------------------------------------------------------------------------
# Prova direta (não só inferida da latência de outro comando): o lock do supervisor está
# LIVRE assim que `stop` termina de processar, mesmo com o desmonte do host ainda em voo
# em segundo plano — "o lock passa a proteger só o mapa `_runtimes`... `stop` não segura
# o lock durante `MpcHost.stop()`" (spec F5 §6.3).
# --------------------------------------------------------------------------------------


async def test_stop_durante_build_nao_segura_lock_do_supervisor_em_mpchost_stop(
    harness_factory: Factory, session_factory: Sessions
) -> None:
    scenario = await _mpc_scenario(session_factory)
    harness = await harness_factory(mpc_worker_target=mpc_host_slow_build_worker)

    await harness.command("deploy", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)
    runtime = harness.supervisor._runtimes[scenario["flow_id"]]  # noqa: SLF001
    host = runtime.blocks["m1"][1].host

    await harness.command("stop", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "stopped", timeout_s=AWAIT_TIMEOUT_S)

    # `stop` já terminou (flow "stopped"), mas o host ainda está vivo — em desmonte, em
    # segundo plano: a janela de MPC_SLOW_BUILD_DELAY_S (7s) ainda não fechou. Mesmo assim
    # o lock já está livre.
    assert host.stats()["alive"] is True
    assert harness.supervisor._lock.locked() is False  # noqa: SLF001
