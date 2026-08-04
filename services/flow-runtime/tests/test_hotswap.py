"""Hot-swap: preservação de estado por `block_id` e troca na fronteira (RF-304, ADR-011/024).

Critério de "bloco não alterado" é igualdade de `FlowNode.functional_config()` (spec §4.1-3):
`exec_order`, rótulo e posição mudam sem resetar estado. As provas são comportamentais, não
por identidade de objeto — o contrato que o operador enxerga é o estado interno continuar (a
resposta ao degrau do TFS não reinicia; o contador de varreduras do Script não volta a 1).

O `state` do Script vem do pool-duplo do `conftest.py`, que devolve em `OUT1` o número de
varreduras que aquele bloco já fez: se a instância foi trocada, `OUT1` volta a 1.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from conftest import (
    QUIET_WINDOW_S,
    Collector,
    Harness,
    await_until,
    create_connection,
    create_flow,
    create_project,
    create_tag,
    edge,
    graph,
    port_value,
    publish_tag_value,
    read_node,
    save_graph,
    script_node,
    sopdt,
    tfs_node,
)
from ottima_core.bus import CHANNEL_EVENTS, KIND_RELOAD_REJECTED, channel_flow_status

Factory = Callable[..., Awaitable[Harness]]
Collect = Callable[[str], Awaitable[Collector]]
Sessions = async_sessionmaker[AsyncSession]

TWO_COUNTERS = graph([script_node("s1", 1), script_node("s2", 2)])


def series(collector: Collector, block_id: str, port: str = "OUT1") -> list[float | bool | None]:
    """Valores de uma porta, só nas varreduras em que o bloco existia."""
    return [
        port_value(scan, block_id, port)
        for scan in collector.scans()
        if block_id in scan.ports and port in scan.ports[block_id]
    ]


def tfs_graph(tag_id: int, *, label: str = "", position: tuple[float, float] = (0.0, 0.0)) -> dict:
    """OPC-Read alimentando `u1` de um TFS SOPDT: um degrau na entrada de uma malha."""
    return graph(
        [
            read_node("r1", 1, tag_id),
            tfs_node("t1", 2, y1_u1=sopdt(), label=label, position=position),
        ],
        [edge("r1", "out", "t1", "u1")],
    )


# --------------------------------------------------------------------------------------
# 16: config funcional idêntica ⇒ estado interno contínuo (§4.1-3)
# --------------------------------------------------------------------------------------


async def test_bloco_identico_mantem_o_estado_interno_do_tfs(
    harness_factory: Factory,
    collect: Collect,
    session_factory: Sessions,
    redis_client: Redis,
) -> None:
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id)
    tag_id = await create_tag(session_factory, conn_id)
    flow_id = await create_flow(session_factory, project_id, graph=tfs_graph(tag_id))
    status = await collect(channel_flow_status(flow_id))
    harness = await harness_factory()

    await publish_tag_value(redis_client, conn_id, tag_id, 1.0)
    await await_until(lambda: harness.snapshot.get(tag_id) is not None)
    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")

    # Três varreduras de degrau: a resposta já subiu bem acima do primeiro passo.
    await await_until(lambda: len([v for v in series(status, "t1", "y1") if v]) >= 3)
    antes = [v for v in series(status, "t1", "y1") if v is not None]
    ultimo_antes = antes[-1]

    await save_graph(session_factory, flow_id, tfs_graph(tag_id))  # grafo idêntico
    await harness.command("reload", flow_id)

    await await_until(lambda: len(series(status, "t1", "y1")) > len(antes) + 1)
    depois = [v for v in series(status, "t1", "y1")][len(antes) :]

    assert all(v is not None for v in depois)
    # Instância preservada: a resposta continua subindo em vez de voltar ao primeiro passo.
    assert depois[0] > ultimo_antes
    assert harness.flow_state(flow_id) == "running"


# --------------------------------------------------------------------------------------
# 17: config funcional alterada ⇒ instância nova, estado zerado
# --------------------------------------------------------------------------------------


async def test_code_alterado_reinstancia_o_script_com_state_zerado(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=TWO_COUNTERS)
    status = await collect(channel_flow_status(flow_id))
    harness = await harness_factory()

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await await_until(lambda: any((v or 0) >= 2 for v in series(status, "s1")))
    antes_s1 = len(series(status, "s1"))
    antes_s2 = max(v or 0 for v in series(status, "s2"))

    alterado = graph([script_node("s1", 1, code="OUT1 = 2.0"), script_node("s2", 2)])
    await save_graph(session_factory, flow_id, alterado)
    await harness.command("reload", flow_id)

    # s1 recomeça do 1 (state zerado, RF-512); s2 não foi tocado e segue contando.
    await await_until(lambda: 1.0 in series(status, "s1")[antes_s1:])
    await await_until(lambda: any((v or 0) > antes_s2 for v in series(status, "s2")))
    assert harness.flow_state(flow_id) == "running"


# --------------------------------------------------------------------------------------
# 18: exec_order/label/position fora da identidade (ADR-024, coração do §4.1-3)
# --------------------------------------------------------------------------------------


async def test_exec_order_label_e_posicao_nao_resetam_estado(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=TWO_COUNTERS)
    status = await collect(channel_flow_status(flow_id))
    harness = await harness_factory()

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await await_until(lambda: any((v or 0) >= 2 for v in series(status, "s1")))
    corte = len(series(status, "s1"))
    maximo_antes = max(v or 0 for v in series(status, "s1"))

    # Ordem trocada, rótulos novos, posições novas — nenhuma mudança funcional.
    remexido = graph(
        [
            script_node("s1", 2, label="Primeiro", position=(120.0, 40.0)),
            script_node("s2", 1, label="Segundo", position=(320.0, 240.0)),
        ]
    )
    await save_graph(session_factory, flow_id, remexido)
    await harness.command("reload", flow_id)

    await await_until(lambda: len(series(status, "s1")) > corte + 1)
    depois = series(status, "s1")[corte:]

    assert 1.0 not in depois  # nenhum reset
    assert all((v or 0) > maximo_antes - 1 for v in depois)
    assert depois[-1] > maximo_antes


# --------------------------------------------------------------------------------------
# 19: bloco removido é descartado, bloco novo nasce null (§3.0/§4.1-3)
# --------------------------------------------------------------------------------------


async def test_bloco_removido_desaparece_e_bloco_novo_nasce_null(
    harness_factory: Factory,
    collect: Collect,
    session_factory: Sessions,
    redis_client: Redis,
) -> None:
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id)
    tag_id = await create_tag(session_factory, conn_id)
    flow_id = await create_flow(session_factory, project_id, graph=tfs_graph(tag_id))
    status = await collect(channel_flow_status(flow_id))
    harness = await harness_factory()

    await publish_tag_value(redis_client, conn_id, tag_id, 1.0)
    await await_until(lambda: harness.snapshot.get(tag_id) is not None)
    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await await_until(lambda: len(series(status, "t1", "y1")) >= 2)

    # `t1` sai; `t2` e `r2` entram. `t2` executa ANTES de `r2` (aresta invertida), então na
    # varredura da adoção a entrada dele ainda é a porta recém-nascida de `r2`: null (§3.0).
    novo = graph(
        [
            read_node("r1", 1, tag_id),
            tfs_node("t2", 2, y1_u1=sopdt()),
            read_node("r2", 3, tag_id),
        ],
        [edge("r2", "out", "t2", "u1")],
    )
    await save_graph(session_factory, flow_id, novo)
    await harness.command("reload", flow_id)

    await await_until(lambda: any("t2" in scan.ports for scan in status.scans()))
    adocao = next(scan for scan in status.scans() if "t2" in scan.ports)

    assert "t1" not in adocao.ports  # removido ⇒ descartado
    assert adocao.ports["t2"]["u1"].v is None  # novo ⇒ nasce null
    assert adocao.ports["t2"]["y1"].v is None
    assert adocao.ports["t2"]["y1"].ok is False


# --------------------------------------------------------------------------------------
# 20: Ts mudou ⇒ tudo re-instancia (§4.1-4)
# --------------------------------------------------------------------------------------


async def test_mudanca_de_ts_reinstancia_todos_os_blocos(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=TWO_COUNTERS)
    status = await collect(channel_flow_status(flow_id))
    harness = await harness_factory()

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await await_until(lambda: any((v or 0) >= 2 for v in series(status, "s1")))
    corte_s1 = len(series(status, "s1"))
    corte_s2 = len(series(status, "s2"))

    # Grafo idêntico, só o Ts muda: a timebase inteira muda, então nada é preservado.
    await save_graph(session_factory, flow_id, TWO_COUNTERS, ts_seconds=1.0)
    await harness.command("reload", flow_id)

    await await_until(lambda: 1.0 in series(status, "s1")[corte_s1:])
    await await_until(lambda: 1.0 in series(status, "s2")[corte_s2:])
    assert harness.flow_state(flow_id) == "running"


# --------------------------------------------------------------------------------------
# 21: staged inválido ⇒ reload_rejected e o flow vigente continua (§4.1-5)
# --------------------------------------------------------------------------------------


async def test_staged_invalido_mantem_a_definicao_vigente_rodando(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=TWO_COUNTERS)
    events = await collect(CHANNEL_EVENTS)
    status = await collect(channel_flow_status(flow_id))
    harness = await harness_factory()

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await await_until(lambda: any((v or 0) >= 2 for v in series(status, "s1")))
    corte = len(series(status, "s1"))
    maximo_antes = max(v or 0 for v in series(status, "s1"))

    # exec_order duplicado: a API valida no save, então só corrida ou bug chega aqui.
    await save_graph(session_factory, flow_id, graph([script_node("s1", 1), script_node("s2", 1)]))
    await harness.command("reload", flow_id)

    await await_until(lambda: len(events.events(KIND_RELOAD_REJECTED)) == 1)
    rejeitado = events.events(KIND_RELOAD_REJECTED)[0]
    assert rejeitado.severity == "warning"
    assert rejeitado.origin == f"flow:{flow_id}"

    # Hot-swap nunca derruba flow: a definição vigente segue varrendo, sem reset.
    await await_until(lambda: len(series(status, "s1")) > corte + 1)
    depois = series(status, "s1")[corte:]
    assert harness.flow_state(flow_id) == "running"
    assert 1.0 not in depois
    assert depois[-1] > maximo_antes


# --------------------------------------------------------------------------------------
# 22: troca na fronteira, ponta a ponta (E2E-F3-04 em unidade)
# --------------------------------------------------------------------------------------


async def test_troca_aplica_na_varredura_seguinte_sem_parar_o_flow(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    project_id = await create_project(session_factory)
    flow_id = await create_flow(session_factory, project_id, graph=graph([script_node("s1", 1)]))
    events = await collect(CHANNEL_EVENTS)
    status = await collect(channel_flow_status(flow_id))
    harness = await harness_factory()

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running")
    await await_until(lambda: len(status.scans()) >= 2)

    varreduras_no_stage = len(status.scans())
    await save_graph(session_factory, flow_id, TWO_COUNTERS)
    await harness.command("reload", flow_id)

    await await_until(lambda: any("s2" in scan.ports for scan in status.scans()))
    scans = status.scans()
    primeira_com_s2 = next(i for i, scan in enumerate(scans) if "s2" in scan.ports)

    # Aplicou na fronteira seguinte (a dica pode chegar logo após uma fronteira: <= 2xTs).
    assert varreduras_no_stage <= primeira_com_s2 <= varreduras_no_stage + 1
    # Sem parada no meio: nenhuma publicação saiu de `running` e nenhum evento de ciclo.
    assert {scan.state for scan in scans} == {"running"}
    assert [event.payload.get("kind") for event in events.events()] == ["flow_deployed"]

    await asyncio.sleep(QUIET_WINDOW_S)
    assert harness.flow_state(flow_id) == "running"
