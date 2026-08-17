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
async def test_flow_stop_idempotente_ja_parado_trata_como_sucesso(cliente_com_ws) -> None:
    """Flow já parado: `stop()` idempotente não publica nada (flow parado não varre, não
    republica sozinho) — só o último estado observado prova que já está no alvo."""
    cliente, _hub_rest, hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))

    async def _fluxo():
        return await server.flow_stop(1, _ctx(cliente), timeout=0.2)

    tarefa = asyncio.ensure_future(_fluxo())
    await asyncio.sleep(0.02)
    await hub_ws.publicar("flow.status.1", {"state": "stopped", "scan_ms": 0.0, "overruns": 0})
    resultado = await tarefa
    assert resultado["state"] == "stopped"


@pytest.mark.asyncio
async def test_flow_stop_timeout_genuino_sem_estado_alvo_levanta_erro(cliente_com_ws) -> None:
    cliente, _hub_rest, _hub_ws = await cliente_com_ws(lambda r: httpx.Response(202))

    async def _fluxo():
        return await server.flow_stop(1, _ctx(cliente), timeout=0.2)

    with pytest.raises(RuntimeError):
        await _fluxo()


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
