"""Ciclo de vida dos flows (RF-101/104/207/402/405, ADR-017, spec F3 §2.2, §4.3).

Comando entra sempre pelo barramento (`flow.commands`), nunca por chamada direta: o que está
sob teste é o caminho que a API usa. O cenário (banco commitado, grafos, pool-duplo, fábrica
de supervisores) vem do `runtime_test_helpers.py` do serviço, compartilhado com
`test_hotswap.py`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from runtime_test_helpers import (
    FAST_POLL_S,
    QUIET_WINDOW_S,
    USER,
    Collector,
    Harness,
    await_until,
    counter_graph,
    create_connection,
    create_flow,
    create_project,
    create_tag,
    delete_flow,
    graph,
    mpc_graph_valido,
    mpc_host_echo_worker,
    node,
    read_only_graph,
    save_graph,
    script_node,
    set_project_active,
    tfs_node,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_COMM_FAILURE,
    KIND_COMM_RESTORED,
    KIND_DEPLOY_REJECTED,
    KIND_FLOW_DEPLOYED,
    KIND_FLOW_FAILED,
    KIND_FLOW_RESUMED,
    KIND_FLOW_STOPPED,
    KIND_PROJECT_ACTIVATED,
    KIND_SCRIPT_ERROR,
    KIND_SCRIPT_TIMEOUT,
    channel_flow_status,
    publish_event,
)
from ottima_flow_runtime.supervisor import (
    REASON_INVALID_GRAPH,
    REASON_PROJECT_INACTIVE,
)

Factory = Callable[..., Awaitable[Harness]]
Collect = Callable[[str], Awaitable[Collector]]
Sessions = async_sessionmaker[AsyncSession]


async def comm_failure(redis_client: Redis, conn_id: int) -> None:
    """Evento tal como o opc-worker o emite (spec F2 §3.7)."""
    await publish_event(
        redis_client,
        severity="alarm",
        origin=f"conn:{conn_id}",
        message=f"Conexão {conn_id} em falha",
        kind=KIND_COMM_FAILURE,
        payload={"conn_id": conn_id, "reason": "session_lost", "detail": "sessão perdida"},
    )


# --------------------------------------------------------------------------------------
# 1-4: comandos idempotentes (RNF-05, spec §2.2-7)
# --------------------------------------------------------------------------------------


async def test_deploy_sobe_flow_e_emite_flow_deployed_uma_vez(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=counter_graph())
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory()

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await await_until(lambda: len(events.events(KIND_FLOW_DEPLOYED)) == 1)

    deployed = events.events(KIND_FLOW_DEPLOYED)[0]
    assert deployed.origin == f"flow:{flow_id}"  # §6.1 filtra por igualdade neste origin
    assert deployed.payload["user"] == USER
    assert deployed.payload["flow_id"] == flow_id
    assert deployed.severity == "info"


async def test_deploy_em_flow_rodando_e_no_op_sem_segundo_evento(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=counter_graph())
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory()

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await await_until(lambda: len(events.events(KIND_FLOW_DEPLOYED)) == 1)

    await harness.command("deploy", flow_id)
    await asyncio.sleep(QUIET_WINDOW_S)

    assert len(events.events(KIND_FLOW_DEPLOYED)) == 1
    assert harness.flow_state(flow_id) == "running"


async def test_stop_para_o_flow_com_motivo_user_e_e_idempotente(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=counter_graph())
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory()

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await harness.command("stop", flow_id)
    await harness.await_state(flow_id, "stopped")
    await await_until(lambda: len(events.events(KIND_FLOW_STOPPED)) == 1)

    stopped = events.events(KIND_FLOW_STOPPED)[0]
    assert stopped.origin == f"flow:{flow_id}"
    assert stopped.payload["reason"] == "user"
    assert stopped.payload["user"] == USER

    await harness.command("stop", flow_id)
    await asyncio.sleep(QUIET_WINDOW_S)
    assert len(events.events(KIND_FLOW_STOPPED)) == 1


@pytest.mark.parametrize("cmd", ["deploy", "stop", "reload"])
async def test_flow_id_desconhecido_e_ignorado_sem_excecao(
    cmd: str, harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    vivo = await create_flow(session_factory, project_id, graph=counter_graph())
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory()

    await harness.command(cmd, 987_654)
    await asyncio.sleep(QUIET_WINDOW_S)

    assert events.events() == []
    assert dict(harness.supervisor.flows) == {}
    # O consumidor de comandos continua vivo depois do comando órfão.
    await harness.command("deploy", vivo)
    await harness.await_state(vivo, "running")


# --------------------------------------------------------------------------------------
# 5-6: deploy rejeitado (spec §2.2-1)
# --------------------------------------------------------------------------------------


async def test_deploy_de_flow_de_projeto_inativo_e_rejeitado(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory, is_active=False)
    flow_id = await create_flow(session_factory, project_id, graph=counter_graph())
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory()

    await harness.command("deploy", flow_id)
    await await_until(lambda: len(events.events(KIND_DEPLOY_REJECTED)) == 1)

    rejeitado = events.events(KIND_DEPLOY_REJECTED)[0]
    assert rejeitado.severity == "warning"
    assert rejeitado.origin == f"flow:{flow_id}"
    assert rejeitado.payload["reason"] == REASON_PROJECT_INACTIVE
    assert dict(harness.supervisor.flows) == {}
    assert events.events(KIND_FLOW_DEPLOYED) == []


@pytest.mark.parametrize(
    "invalido",
    [
        pytest.param(graph([script_node("a", 1), script_node("b", 1)]), id="exec_order-duplicado"),
        pytest.param(graph([node("m1", "mpc", 1, {})]), id="bloco-mpc-nao-parseia"),
    ],
)
async def test_deploy_de_grafo_invalido_e_rejeitado_sem_task_orfa(
    invalido: dict, harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=invalido)
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory()

    await harness.command("deploy", flow_id)
    await await_until(lambda: len(events.events(KIND_DEPLOY_REJECTED)) == 1)

    rejeitado = events.events(KIND_DEPLOY_REJECTED)[0]
    assert rejeitado.severity == "warning"
    assert rejeitado.origin == f"flow:{flow_id}"
    assert rejeitado.payload["reason"] == REASON_INVALID_GRAPH
    assert dict(harness.supervisor.flows) == {}
    assert harness.state.flows == {}


async def test_deploy_de_flow_com_mpc_succeede_ponte_f4a_removida(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """PONTE DE DEPLOY [tarefa 3.1 do F4a; REMOVIDA na tarefa 2.2 do F4b]: o grafo com `mpc`
    valida e salva (spec F4 §2.2, tarefa 1.2) e agora TAMBÉM sobe — `MpcBlock`/`MpcHost`
    (plano F4b, tarefas 2.1/2.2) já executam de verdade; nenhum `deploy_rejected` sai mais
    por causa de um nó `mpc`.

    Também cobre `Supervisor.mpc_health()`/`script_pool_stats()` (plano F4b, tarefa 2.3;
    spec F4 §4.10) contra um flow MPC de verdade — `test_health_mpc.py` só prova o wiring
    do `main.py` com um supervisor dublê; aqui a travessia real de `_runtimes`/`blocks`/
    `_pool` está sob teste.
    """
    project_id = await create_project(session_factory)
    connection_id = await create_connection(session_factory, project_id)
    tag_id = await create_tag(session_factory, connection_id, direction="r")
    flow_id = await create_flow(session_factory, project_id, graph=mpc_graph_valido(tag_id))
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running", timeout_s=15.0)

    assert events.events(KIND_DEPLOY_REJECTED) == []
    assert len(events.events(KIND_FLOW_DEPLOYED)) == 1
    assert harness.flow_state(flow_id) == "running"

    mpc_health = harness.supervisor.mpc_health(flow_id)
    assert set(mpc_health) == {"m1"}
    assert set(mpc_health["m1"]) == {"mode", "overruns", "last_solve_ms", "worker"}
    assert set(mpc_health["m1"]["worker"]) == {"alive", "respawns", "last_solve_ms"}
    # Flow inexistente: mesmo contrato de dict vazio de `mpc_graph_valido` sem bloco mpc.
    assert harness.supervisor.mpc_health(flow_id + 1) == {}
    assert set(harness.supervisor.script_pool_stats()) == {"size", "busy", "respawns"}


# --------------------------------------------------------------------------------------
# 7: boot parado (RF-104, ADR-017) — E2E-F3-08 em unidade
# --------------------------------------------------------------------------------------


async def test_boot_nao_aplica_desired_state_running(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """`desired_state` é exibição: só comando `deploy` sobe flow (ADR-017, contrato 1)."""
    project_id = await create_project(session_factory)
    primeiro = await create_flow(
        session_factory, project_id, graph=counter_graph(), name="A", desired_state="running"
    )
    segundo = await create_flow(
        session_factory, project_id, graph=counter_graph("s2"), name="B", desired_state="running"
    )
    events = await collect(CHANNEL_EVENTS)
    status = await collect(channel_flow_status(primeiro))
    harness = await harness_factory(poll_interval_s=FAST_POLL_S)

    # Além das passadas que o poll curto rodou na janela, uma explícita.
    await asyncio.sleep(QUIET_WINDOW_S)
    await harness.supervisor.reconcile()

    assert dict(harness.supervisor.flows) == {}
    assert harness.state.flows == {}
    assert events.events(KIND_FLOW_DEPLOYED) == []
    assert status.received == []
    # E o flow continua deployável por comando, que é o único caminho de subida.
    await harness.command("deploy", segundo)
    await harness.await_state(segundo, "running")


# --------------------------------------------------------------------------------------
# 8-9: comm_failure seletivo (RF-207, spec §2.2-8)
# --------------------------------------------------------------------------------------


async def test_comm_failure_derruba_so_os_flows_da_conexao(
    harness_factory: Factory,
    collect: Collect,
    session_factory: Sessions,
    redis_client: Redis,
) -> None:
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id)
    outra_conn = await create_connection(session_factory, project_id, name="Forno 2")
    tag_id = await create_tag(session_factory, conn_id)
    da_conexao = await create_flow(
        session_factory, project_id, graph=read_only_graph(tag_id), name="Com tag"
    )
    puro = await create_flow(
        session_factory,
        project_id,
        graph=graph([script_node("s1", 1), tfs_node("t1", 2)]),
        name="Script e TFS",
    )
    events = await collect(CHANNEL_EVENTS)
    status_puro = await collect(channel_flow_status(puro))
    harness = await harness_factory()

    await harness.command("deploy", da_conexao)
    await harness.command("deploy", puro)
    await harness.await_state(da_conexao, "running")
    await harness.await_state(puro, "running")
    antes = len(status_puro.scans())

    await comm_failure(redis_client, conn_id)
    await harness.await_state(da_conexao, "failed")

    await await_until(lambda: len(events.events(KIND_FLOW_FAILED)) == 1)
    falhou = events.events(KIND_FLOW_FAILED)[0]
    assert falhou.payload["flow_id"] == da_conexao
    assert falhou.payload["reason"] == "comm_failure"
    assert falhou.severity == "alarm"

    # O flow sem tag nenhuma segue varrendo e publicando (RF-402).
    await await_until(lambda: len(status_puro.scans()) > antes)
    assert harness.flow_state(puro) == "running"

    # Falha na conexão que o flow NÃO usa não derruba ninguém.
    await comm_failure(redis_client, outra_conn)
    await asyncio.sleep(QUIET_WINDOW_S)
    assert harness.flow_state(puro) == "running"
    assert len(events.events(KIND_FLOW_FAILED)) == 1


async def test_comm_restored_retoma_o_flow_automaticamente(
    harness_factory: Factory,
    collect: Collect,
    session_factory: Sessions,
    redis_client: Redis,
) -> None:
    """TD-005/ADR-025: `desired_state == "running"` sobrevive à queda -> `comm_restored`
    redeploya o flow sozinho, sem comando manual nenhum."""
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id)
    tag_id = await create_tag(session_factory, conn_id)
    flow_id = await create_flow(
        session_factory,
        project_id,
        graph=read_only_graph(tag_id),
        desired_state="running",
    )
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(poll_interval_s=FAST_POLL_S)

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await comm_failure(redis_client, conn_id)
    await harness.await_state(flow_id, "failed")

    await publish_event(
        redis_client,
        severity="info",
        origin=f"conn:{conn_id}",
        message="Conexão restaurada",
        kind=KIND_COMM_RESTORED,
        payload={"conn_id": conn_id},
    )
    await harness.await_state(flow_id, "running")

    await await_until(lambda: len(events.events(KIND_FLOW_RESUMED)) == 1)
    resumido = events.events(KIND_FLOW_RESUMED)[0]
    assert resumido.payload["flow_id"] == flow_id
    assert resumido.payload["conn_id"] == conn_id
    assert len(events.events(KIND_FLOW_DEPLOYED)) == 2  # deploy original + retomada


async def test_comm_restored_nao_retoma_flow_com_desired_state_parado(
    harness_factory: Factory,
    collect: Collect,
    session_factory: Sessions,
    redis_client: Redis,
) -> None:
    """O operador pode ter parado o flow durante a queda: a retomada automática respeita
    `desired_state` do banco, não o estado em memória de quando ele caiu (RNF-05, comando
    manual sempre vence)."""
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id)
    tag_id = await create_tag(session_factory, conn_id)
    flow_id = await create_flow(session_factory, project_id, graph=read_only_graph(tag_id))
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(poll_interval_s=FAST_POLL_S)

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await comm_failure(redis_client, conn_id)
    await harness.await_state(flow_id, "failed")

    await publish_event(
        redis_client,
        severity="info",
        origin=f"conn:{conn_id}",
        message="Conexão restaurada",
        kind=KIND_COMM_RESTORED,
        payload={"conn_id": conn_id},
    )
    await asyncio.sleep(QUIET_WINDOW_S)

    assert harness.flow_state(flow_id) == "failed"
    assert events.events(KIND_FLOW_RESUMED) == []

    await harness.command("deploy", flow_id)  # deploy manual continua retomando
    await harness.await_state(flow_id, "running")


async def test_deploy_manual_apos_queda_limpa_a_retomada_pendente(
    harness_factory: Factory,
    collect: Collect,
    session_factory: Sessions,
    redis_client: Redis,
) -> None:
    """Guarda (§2.2-8): `deploy`/`stop` manuais limpam a entrada pendente — um
    `comm_restored` chegando DEPOIS não redeploya de novo por cima."""
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id)
    tag_id = await create_tag(session_factory, conn_id)
    flow_id = await create_flow(
        session_factory,
        project_id,
        graph=read_only_graph(tag_id),
        desired_state="running",
    )
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(poll_interval_s=FAST_POLL_S)

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await comm_failure(redis_client, conn_id)
    await harness.await_state(flow_id, "failed")

    await harness.command("deploy", flow_id)  # operador redeploya na mão antes da conexão voltar
    await harness.await_state(flow_id, "running")

    await publish_event(
        redis_client,
        severity="info",
        origin=f"conn:{conn_id}",
        message="Conexão restaurada",
        kind=KIND_COMM_RESTORED,
        payload={"conn_id": conn_id},
    )
    await asyncio.sleep(QUIET_WINDOW_S)

    assert events.events(KIND_FLOW_RESUMED) == []
    assert len(events.events(KIND_FLOW_DEPLOYED)) == 2  # inicial + manual, sem retomada somando


# --------------------------------------------------------------------------------------
# 10: project_activated (RF-101, spec §4.3)
# --------------------------------------------------------------------------------------


async def test_project_activated_para_todos_os_flows_rodando(
    harness_factory: Factory,
    collect: Collect,
    session_factory: Sessions,
    redis_client: Redis,
) -> None:
    project_id = await create_project(session_factory)
    primeiro = await create_flow(session_factory, project_id, graph=counter_graph(), name="A")
    segundo = await create_flow(session_factory, project_id, graph=counter_graph("s2"), name="B")
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory()

    await harness.command("deploy", primeiro)
    await harness.command("deploy", segundo)
    await harness.await_state(primeiro, "running")
    await harness.await_state(segundo, "running")

    await publish_event(
        redis_client,
        severity="info",
        origin="user:1",
        message="Projeto ativado",
        kind=KIND_PROJECT_ACTIVATED,
        payload={"project_id": 42, "name": "Outro"},
    )

    await harness.await_state(primeiro, "stopped")
    await harness.await_state(segundo, "stopped")
    await await_until(lambda: len(events.events(KIND_FLOW_STOPPED)) == 2)
    for event in events.events(KIND_FLOW_STOPPED):
        assert event.payload["reason"] == "project_activated"
        # Sem comando de usuário atrás: a chave `user` não existe (ruling do controlador).
        assert "user" not in event.payload


# --------------------------------------------------------------------------------------
# 11-13: watermark backstop de 10 s (spec §2.2-9)
# --------------------------------------------------------------------------------------


async def test_watermark_pega_dica_de_reload_perdida(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=counter_graph())
    status = await collect(channel_flow_status(flow_id))
    harness = await harness_factory(poll_interval_s=FAST_POLL_S)

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")

    # Grafo novo no banco SEM publicar `reload`: quem tem de perceber é o watermark.
    await save_graph(session_factory, flow_id, graph([script_node("s1", 1), tfs_node("t2", 2)]))

    await await_until(lambda: any("t2" in scan.ports for scan in status.scans()))
    assert harness.flow_state(flow_id) == "running"


async def test_watermark_para_flow_deletado_do_banco(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """Só um projeto ativo por vez (DDL da F1), então cada backstop tem o seu cenário."""
    project_id = await create_project(session_factory)
    deletado = await create_flow(session_factory, project_id, graph=counter_graph(), name="A")
    sobrevivente = await create_flow(
        session_factory, project_id, graph=counter_graph("s2"), name="B"
    )
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(poll_interval_s=FAST_POLL_S)

    await harness.command("deploy", deletado)
    await harness.command("deploy", sobrevivente)
    await harness.await_state(deletado, "running")
    await harness.await_state(sobrevivente, "running")

    await delete_flow(session_factory, deletado)

    await await_until(lambda: harness.flow_state(deletado) in {None, "stopped"})
    await await_until(lambda: len(events.events(KIND_FLOW_STOPPED)) == 1)
    parado = events.events(KIND_FLOW_STOPPED)[0]
    assert parado.payload["flow_id"] == deletado
    # String literal de propósito: `flow_deleted` é contrato com o mapa de tradução de
    # `reason` do frontend (tarefa 4.3), e a §4.3 lista só `user|project_activated`. Comparar
    # com a constante do módulo passaria mesmo se o valor mudasse, que é o risco real aqui.
    assert parado.payload["reason"] == "flow_deleted"
    # O flow que ninguém tocou segue rodando: a passada é isolada por flow.
    assert harness.flow_state(sobrevivente) == "running"


async def test_watermark_para_flow_de_projeto_desativado(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=counter_graph())
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(poll_interval_s=FAST_POLL_S)

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")

    await set_project_active(session_factory, project_id, is_active=False)

    await harness.await_state(flow_id, "stopped")
    await await_until(lambda: len(events.events(KIND_FLOW_STOPPED)) == 1)
    assert events.events(KIND_FLOW_STOPPED)[0].payload["reason"] == "project_activated"


async def test_watermark_nunca_inicia_flow(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """Contrato 1: nenhuma passada de reconciliação sobe flow, nem com desired_state=running."""
    project_id = await create_project(session_factory)
    flow_id = await create_flow(
        session_factory, project_id, graph=counter_graph(), desired_state="running"
    )
    events = await collect(CHANNEL_EVENTS)
    status = await collect(channel_flow_status(flow_id))
    harness = await harness_factory(poll_interval_s=FAST_POLL_S)

    # Mexer no flow durante as passadas: nem edição nem desired_state podem virar subida.
    await save_graph(session_factory, flow_id, graph([script_node("s1", 1), tfs_node("t2", 2)]))
    await asyncio.sleep(QUIET_WINDOW_S)
    await harness.supervisor.reconcile()

    assert dict(harness.supervisor.flows) == {}
    assert events.events(KIND_FLOW_DEPLOYED) == []
    assert status.received == []


# --------------------------------------------------------------------------------------
# 14: desmonte isolado e ordem do desligamento (Critical da F2 + achado da tarefa 1.3)
# --------------------------------------------------------------------------------------


async def test_stop_do_supervisor_desmonta_todos_mesmo_com_um_levantando(
    harness_factory: Factory, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    ruim = await create_flow(session_factory, project_id, graph=counter_graph(), name="Ruim")
    bom = await create_flow(session_factory, project_id, graph=counter_graph("s2"), name="Bom")
    harness = await harness_factory()

    await harness.command("deploy", ruim)
    await harness.command("deploy", bom)
    await harness.await_state(ruim, "running")
    await harness.await_state(bom, "running")
    task_bom = harness.supervisor.flows[bom]

    async def explode(**kwargs: Any) -> None:
        raise RuntimeError("stop do flow explodiu de proposito")

    harness.supervisor.flows[ruim].stop = explode  # type: ignore[method-assign]

    await harness.supervisor.stop()

    assert dict(harness.supervisor.flows) == {}
    assert harness.state.flows == {}
    assert task_bom.state == "stopped"


async def test_stop_encerra_varreduras_antes_de_parar_o_pool(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """Pool parado antes das varreduras devolve `timeout`/`error` na varredura em voo.

    Achado roteado da tarefa 1.3: a ordem invertida vira `script_error` espúrio no
    desligamento, que é alarme falso no log de eventos do operador.
    """
    project_id = await create_project(session_factory)
    primeiro = await create_flow(session_factory, project_id, graph=counter_graph(), name="A")
    segundo = await create_flow(session_factory, project_id, graph=counter_graph("s2"), name="B")
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory()

    await harness.command("deploy", primeiro)
    await harness.command("deploy", segundo)
    await harness.await_state(primeiro, "running")
    await harness.await_state(segundo, "running")
    await await_until(lambda: "run" in harness.pool.calls)

    harness.pool.probe = lambda: sum(
        1 for task in harness.supervisor.flows.values() if task.state == "running"
    )
    await harness.supervisor.stop()

    # A prova da ordem: quando o pool foi parado, não havia mais varredura possível.
    assert harness.pool.running_flows_at_stop == 0
    assert harness.pool.calls[-1] == "stop"
    assert harness.pool.runs_after_stop == 0
    assert events.events(KIND_SCRIPT_ERROR) == []
    assert events.events(KIND_SCRIPT_TIMEOUT) == []


async def test_desmonte_do_supervisor_publica_flow_stopped_de_shutdown(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """Restart do runtime: o flow que estava rodando ganha `flow_stopped` com `shutdown`.

    Sem o evento, o último estado conhecido segue `flow_deployed` e a lista do frontend
    mostra "Rodando" enquanto o `/health` mostra `flows={}` (achado I3).
    """
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=counter_graph())
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory()

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await await_until(lambda: len(events.events(KIND_FLOW_DEPLOYED)) == 1)

    await harness.supervisor.stop()

    await await_until(lambda: len(events.events(KIND_FLOW_STOPPED)) == 1)
    parado = events.events(KIND_FLOW_STOPPED)[0]
    assert parado.origin == f"flow:{flow_id}"
    assert parado.payload["flow_id"] == flow_id
    # String literal de propósito: `shutdown` é contrato com o mapa de tradução de `reason`
    # do frontend, como o `flow_deleted` do teste do watermark.
    assert parado.payload["reason"] == "shutdown"
    # Desligamento sem comando de usuário atrás: a chave `user` não existe.
    assert "user" not in parado.payload


# --------------------------------------------------------------------------------------
# 15: /health (spec §2.2-10)
# --------------------------------------------------------------------------------------


async def test_health_reporta_dependencias_e_flows(
    harness_factory: Factory, session_factory: Sessions
) -> None:
    from ottima_flow_runtime.main import app

    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=counter_graph())
    harness = await harness_factory()
    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await await_until(lambda: harness.supervisor.flows[flow_id].last_scan_ts is not None)

    app.state.runtime_state = harness.state
    app.state.redis_ok = True
    app.state.db_ok = False
    app.state.runtime_up = True
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        degradado = await client.get("/health")
        app.state.db_ok = True
        saudavel = await client.get("/health")

    assert degradado.status_code == 200  # dependência fora nunca é 5xx
    assert degradado.json()["status"] == "degraded"

    corpo = saudavel.json()
    assert corpo["status"] == "ok"
    assert corpo["service"] == "flow-runtime"
    # Chave string: JSON não tem chave inteira (como `connections` do opc-worker).
    task = harness.supervisor.flows[flow_id]
    flow = corpo["flows"][str(flow_id)]
    assert flow["state"] == "running"
    assert flow["overruns"] == task.overruns
    assert flow["scan_ms"] == pytest.approx(task.scan_ms)
    assert flow["last_scan_ts"] is not None


async def test_health_sem_lifespan_nao_inventa_flows() -> None:
    """App cru (sem lifespan) cai nos defaults: flow em falha não é unhealth do serviço."""
    from ottima_flow_runtime.main import app

    app.state.runtime_state = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["flows"] == {}
