"""TD-008 — gate de overrun por CAUSA, determinístico, sem relógio de parede.

O gate antigo (`tests/e2e/test_f6_rnf09.py`) inferia overrun pelo EFEITO ("a MV não andou")
e só passava quando o solve real NÃO cabia no orçamento — numa máquina rápida ele ficava
vermelho sem regressão nenhuma. Aqui o overrun é FORÇADO por um worker de solve lento
(`mpc_host_slow_solve_worker`, 0,6 s contra o orçamento de `Ts = 0,5 s`), e o que se assevera
é o contrato:

1. `status.overruns` incrementa de fato (contador monotônico, `blocks/mpc.py::_apply_result`);
2. o evento `mpc_overrun` sai;
3. a saída é SEGURA durante o estouro — sem `SolveResult` "ok", `_plan` nunca é aplicado e a
   MV segura `_mv_last`;
4. o evento é uma vez por EPISÓDIO, não por quadro: `_overrun_reported` só rearma quando um
   resultado não-overrun chega (`_apply_result`, o `if result.status != "overrun"`). Com o
   worker permanentemente lento nenhum resultado bom chega, então muitos overruns produzem
   UM evento — é exatamente essa razão entre os dois números que prova o rearme.

Imports ABSOLUTOS: o `spawn` reimporta a função-alvo do worker por `__module__` num
interpretador novo, e só o nome sem pacote é resolvível pelo `sys.path` do filho
(`runtime_test_helpers.py`, bloco de comentário dos workers falsos).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from runtime_test_helpers import (
    AWAIT_TIMEOUT_S,
    DEPLOY_TIMEOUT_S,
    TS_SECONDS,
    Collector,
    Harness,
    await_until,
    create_connection,
    create_flow,
    create_project,
    create_tag,
    mpc_graph_valido,
    mpc_host_slow_solve_worker,
    publish_tag_value,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import CHANNEL_EVENTS, KIND_MPC_OVERRUN, MpcState, channel_mpc_state

Factory = Callable[..., Awaitable[Harness]]
Sessions = async_sessionmaker[AsyncSession]
Collect = Callable[[str], Awaitable[Collector]]

BLOCO = "m1"
MV = "mv_a"
"""Ids do `mpc_graph_valido`: uma MV direta (`mv_a`) e uma CV (`cv_a`)."""

OVERRUNS_ALVO = 3
"""Estouros observados antes de fechar a janela. Três bastam para provar incremento repetido
e para a razão evento/overrun ser conclusiva, sem alongar a suíte."""


def _estados(coletor: Collector) -> list[MpcState]:
    return [MpcState.model_validate_json(raw) for raw in list(coletor.received)]


def _ultimo(coletor: Collector) -> MpcState:
    return MpcState.model_validate_json(coletor.received[-1])


def _overruns(coletor: Collector) -> int:
    return _ultimo(coletor).status.overruns if coletor.received else 0


async def _cenario(session_factory: Sessions) -> dict[str, Any]:
    """Projeto + conexão + tag da CV + flow com `mpc_graph_valido` (MV direta, sem `pid`)."""
    project_id = await create_project(session_factory)
    connection_id = await create_connection(session_factory, project_id)
    cv_tag_id = await create_tag(session_factory, connection_id, name="cv", direction="r")
    flow_id = await create_flow(
        session_factory,
        project_id,
        graph=mpc_graph_valido(cv_tag_id),
        ts_seconds=TS_SECONDS,
        watchdog_enabled=True,
    )
    return {"connection_id": connection_id, "cv_tag_id": cv_tag_id, "flow_id": flow_id}


async def test_td_008_solve_lento_gera_overrun_com_saida_segura_e_um_evento_por_episodio(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    cenario = await _cenario(session_factory)
    flow_id = cenario["flow_id"]

    eventos = await collect(CHANNEL_EVENTS)
    estados = await collect(channel_mpc_state(flow_id, BLOCO))
    harness = await harness_factory(mpc_worker_target=mpc_host_slow_solve_worker)

    await harness.command("deploy", flow_id)
    await harness.await_state(flow_id, "running", timeout_s=DEPLOY_TIMEOUT_S)
    runtime = harness.supervisor._runtimes[flow_id]  # noqa: SLF001
    await await_until(lambda: runtime.blocks[BLOCO][1].host.ready, timeout_s=DEPLOY_TIMEOUT_S)

    # Entrada quente: sem ela o gate de arme recusa com `cold_input` antes de qualquer solve.
    await publish_tag_value(harness.redis, cenario["connection_id"], cenario["cv_tag_id"], 90.0)
    await await_until(
        lambda: bool(estados.received) and _ultimo(estados).status.input_valid,
        timeout_s=AWAIT_TIMEOUT_S,
    )

    await harness.command(
        "mpc_mode", flow_id, args={"block_id": BLOCO, "axis": "local_remote", "value": "remote"}
    )
    await await_until(
        lambda: _ultimo(estados).modes.local_remote == "remote", timeout_s=AWAIT_TIMEOUT_S
    )

    overruns_ao_entrar_em_auto = _overruns(estados)
    await harness.command(
        "mpc_mode", flow_id, args={"block_id": BLOCO, "axis": "man_auto", "value": "auto"}
    )
    await await_until(lambda: _ultimo(estados).modes.man_auto == "auto", timeout_s=AWAIT_TIMEOUT_S)
    quadros_em_auto = len(estados.received)

    # Espera pela CAUSA, não pelo relógio: a janela fecha quando os estouros aparecem.
    await await_until(
        lambda: _overruns(estados) >= overruns_ao_entrar_em_auto + OVERRUNS_ALVO,
        timeout_s=AWAIT_TIMEOUT_S * 3,
    )

    serie = _estados(estados)
    contadores = [estado.status.overruns for estado in serie]

    # (1) O contador andou, e nunca regride — é monotônico por construção.
    assert contadores[-1] > overruns_ao_entrar_em_auto, (
        f"o solve lento não gerou overrun: série de overruns {contadores}"
    )
    assert all(
        depois >= antes for antes, depois in zip(contadores, contadores[1:], strict=False)
    ), f"o contador de overruns regrediu: {contadores}"

    # (2) O evento saiu.
    disparos = eventos.events(KIND_MPC_OVERRUN)
    assert disparos, f"nenhum `mpc_overrun` publicado apesar de {contadores[-1]} estouros contados"
    assert disparos[0].payload["overruns"] >= 1

    # (3) Saída segura: sem resultado "ok", `_plan` nunca é aplicado e a MV segura o último
    #     valor. Um único valor distinto em toda a janela em AUTO é a prova.
    em_auto = serie[quadros_em_auto - 1 :]
    valores_mv = {estado.vars[MV].v for estado in em_auto}
    assert len(valores_mv) == 1, (
        f"a MV se moveu durante os estouros — saída não foi segura: {sorted(valores_mv)}"
    )

    # (4) Rearme: o evento é uma vez por EPISÓDIO. Com o worker sempre lento nenhum resultado
    #     bom chega para rearmar `_overrun_reported`, então N estouros dão MENOS de N eventos.
    estouros_em_auto = contadores[-1] - overruns_ao_entrar_em_auto
    assert estouros_em_auto >= OVERRUNS_ALVO
    assert len(disparos) < estouros_em_auto, (
        f"{len(disparos)} eventos para {estouros_em_auto} estouros consecutivos: o gate "
        "`_overrun_reported` rearmou sem nenhum resultado bom no meio"
    )
