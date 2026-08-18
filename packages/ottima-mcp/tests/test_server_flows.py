"""Ferramentas MCP de engenharia de flows (Fase 4): `flow_deploy`/`flow_stop` (confirmação
via `flow.status`, canal `/ws` real local) e sanidade dos wrappers finos sobre `grafo.py`
(a lógica de mutação já está coberta em `test_grafo.py`)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from ottima_mcp import server


def _ctx(cliente: Any) -> Any:
    return SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context=SimpleNamespace(cliente=cliente))
    )


# ----------------------------------------------------------------------------------
# flow_deploy / flow_stop — confirmação publicada
# ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_deploy_confirma_por_state_running(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))

    async def _fluxo():
        return await server.flow_deploy(1, _ctx(cliente))

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.05)
    await hub_ws.publicar("flow.status.1", {"state": "running", "scan_ms": 1.0, "overruns": 0})
    resultado = await tarefa
    assert resultado["state"] == "running"


@pytest.mark.asyncio
async def test_flow_deploy_falha_rapida_em_deploy_rejected(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))
    evento = {
        "severity": "warning",
        "origin": "flow:1",
        "message": "recusado",
        "payload": {"kind": "deploy_rejected", "reason": "project_inactive"},
    }

    async def _fluxo():
        return await server.flow_deploy(1, _ctx(cliente))

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.05)
    await hub_ws.publicar("events", evento)
    with pytest.raises(RuntimeError, match="project_inactive"):
        await tarefa


@pytest.mark.asyncio
async def test_flow_deploy_ignora_deploy_rejected_de_outro_flow(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))
    evento_de_outro_flow = {
        "severity": "warning",
        "origin": "flow:9",  # flow DIFERENTE
        "message": "recusado",
        "payload": {"kind": "deploy_rejected", "reason": "project_inactive"},
    }

    async def _fluxo():
        return await server.flow_deploy(1, _ctx(cliente), timeout=0.2)

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.02)
    await hub_ws.publicar("events", evento_de_outro_flow)
    with pytest.raises(RuntimeError):  # tempo esgota — origem não bate, não confirma nem falha
        await tarefa


@pytest.mark.asyncio
async def test_flow_deploy_idempotente_ja_rodando_trata_como_sucesso(cliente_com_ws) -> None:
    """Flow já rodando: `start()` idempotente não publica transição nova, mas
    `_publish_status` republica a cada varredura — o último estado observado já mostra
    'running' mesmo sem confirmação fresca. Timeout não deveria ser erro aqui."""
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))

    async def _fluxo():
        return await server.flow_deploy(1, _ctx(cliente), timeout=0.2)

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.02)
    # publica 'running' UMA vez só — nenhuma transição nova, mas já é o estado alvo.
    await hub_ws.publicar("flow.status.1", {"state": "running", "scan_ms": 1.0, "overruns": 0})
    resultado = await tarefa
    assert resultado["state"] == "running"


@pytest.mark.asyncio
async def test_flow_deploy_state_failed_levanta_erro(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))

    async def _fluxo():
        return await server.flow_deploy(1, _ctx(cliente))

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.05)
    await hub_ws.publicar("flow.status.1", {"state": "failed", "scan_ms": 0.0, "overruns": 0})
    with pytest.raises(RuntimeError, match="falha"):
        await tarefa


@pytest.mark.asyncio
async def test_flow_stop_confirma_por_state_stopped(cliente_com_ws) -> None:
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))

    async def _fluxo():
        return await server.flow_stop(1, _ctx(cliente))

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.05)
    await hub_ws.publicar("flow.status.1", {"state": "stopped", "scan_ms": 0.0, "overruns": 0})
    resultado = await tarefa
    assert resultado["state"] == "stopped"


@pytest.mark.asyncio
async def test_flow_stop_timeout_genuino_sem_estado_alvo_levanta_erro(cliente_com_ws) -> None:
    """Nada no `/ws`, `/health/workers` com o worker degradado (`up: False`, sem `flows`) —
    genuinamente nada a informar, continua erro."""

    def _rota(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health/workers":
            return httpx.Response(
                200,
                json={
                    "opc_worker": {"up": True},
                    "flow_runtime": {"up": False},
                    "recorder": {"up": True},
                    "calc_worker": {"up": True},
                },
            )
        return httpx.Response(202)

    cliente, _hub_rest, _hub_ws = await cliente_com_ws(_rota)

    async def _fluxo():
        return await server.flow_stop(1, _ctx(cliente), timeout=0.2)

    with pytest.raises(RuntimeError):
        await _fluxo()


@pytest.mark.asyncio
async def test_flow_stop_health_mostra_ainda_rodando_nao_da_falso_sucesso(cliente_com_ws) -> None:
    """Sanidade do fallback: `/health/workers` responde, mas mostra `state` DIFERENTE do
    alvo — não pode virar sucesso só por a chamada ter funcionado."""

    def _rota(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health/workers":
            return httpx.Response(
                200,
                json={
                    "opc_worker": {"up": True},
                    "flow_runtime": {"up": True, "flows": {"1": {"state": "running"}}},
                    "recorder": {"up": True},
                    "calc_worker": {"up": True},
                },
            )
        return httpx.Response(202)

    cliente, _hub_rest, _hub_ws = await cliente_com_ws(_rota)

    with pytest.raises(RuntimeError):
        await server.flow_stop(1, _ctx(cliente), timeout=0.2)


@pytest.mark.asyncio
async def test_flow_stop_ja_parado_sem_nenhum_evento_publicado_trata_como_sucesso(
    cliente_com_ws,
) -> None:
    """Cenário REAL de `stop()` idempotente (`supervisor.py:427-431`: `runtime is None or
    state != "running"` -> `return` SEM publicar nada, nem `/ws` nem republicação
    periódica — ao contrário de um flow rodando). `/health/workers` prova o estado real
    quando nenhum evento sai (mesmo `FlowTask._state` que o evento carregaria,
    `state.py::to_health`); `desired_state` não serve pra isso (intenção, pode divergir —
    RNF-05)."""

    def _rota(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health/workers":
            return httpx.Response(
                200,
                json={
                    "opc_worker": {"up": True},
                    "flow_runtime": {"up": True, "flows": {"1": {"state": "stopped"}}},
                    "recorder": {"up": True},
                    "calc_worker": {"up": True},
                },
            )
        return httpx.Response(202)

    cliente, _hub_rest, _hub_ws = await cliente_com_ws(_rota)

    resultado = await server.flow_stop(1, _ctx(cliente), timeout=0.2)
    assert resultado["state"] == "stopped"


# ----------------------------------------------------------------------------------
# Wrappers finos sobre grafo.py — sanidade (mutação já coberta em test_grafo.py)
# ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_create_delega_para_grafo(cliente_falso) -> None:
    def _rota(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/flows":
            return httpx.Response(201, json={"id": 5, "graph_json": {"nodes": [], "edges": []}})
        return httpx.Response(404)

    cliente, _hub = await cliente_falso(_rota)
    resultado = await server.flow_create(3, "Flow X", 2.0, _ctx(cliente))
    assert resultado["id"] == 5


@pytest.mark.asyncio
async def test_flow_add_block_via_ferramenta_devolve_node_id(cliente_falso) -> None:
    def _rota(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/flows/1":
            return httpx.Response(200, json={"id": 1, "graph_json": {"nodes": [], "edges": []}})
        if request.method == "PUT" and request.url.path == "/api/flows/1":
            enviado = json.loads(request.content)
            return httpx.Response(
                200, json={"flow": {"id": 1, "graph_json": enviado["graph_json"]}, "warnings": []}
            )
        return httpx.Response(404)

    cliente, _hub = await cliente_falso(_rota)
    resultado = await server.flow_add_block(1, "opc_read", {"tag_id": 1}, _ctx(cliente))
    assert "node_id" in resultado
    assert resultado["node_id"].startswith("opc_read_")
