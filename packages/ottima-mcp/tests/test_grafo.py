"""Mutações de `graph_json` (Fase 4): read-modify-write sobre o subconjunto r1->s1->w1 da
fixture real `packages/ottima-core/tests/test_flowgraph.py::base_graph` (nós/arestas
copiados verbatim; TFS/r2 omitidos — não exercitados por estas mutações estruturais). Sem
validação semântica local (`validate_graph` roda só no backend) — aqui só a mecânica de
adicionar/remover/conectar/renumerar preservando a forma do dict."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from ottima_mcp import grafo

# Verbatim de test_flowgraph.py:33-100 (subconjunto r1->s1->w1; r2/t1 omitidos).
_GRAFO_BASE: dict[str, Any] = {
    "nodes": [
        {
            "id": "r1",
            "type": "opc_read",
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": 1, "label": "Leitura PV", "tag_id": 1},
        },
        {
            "id": "s1",
            "type": "script",
            "position": {"x": 200.0, "y": 0.0},
            "data": {
                "exec_order": 2,
                "n_inputs": 1,
                "n_outputs": 1,
                "code": "OUT1 = IN1 * 2",
            },
        },
        {
            "id": "w1",
            "type": "opc_write",
            "position": {"x": 400.0, "y": 0.0},
            "data": {"exec_order": 3, "tag_id": 2},
        },
    ],
    "edges": [
        {"id": "e1", "source": "r1", "target": "s1", "sourceHandle": "out", "targetHandle": "IN1"},
        {"id": "e2", "source": "s1", "target": "w1", "sourceHandle": "OUT1", "targetHandle": "in"},
    ],
}


def _rota_grafo(capturado: dict[str, Any]):
    """Backend falso mínimo: GET devolve o grafo base; PUT captura o `graph_json` enviado
    (prova de que é o objeto INTEIRO, nunca patch) e devolve FlowSaved-like."""

    def _rota(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/flows/1":
            return httpx.Response(
                200, json={"id": 1, "graph_json": capturado.get("grafo_atual", _GRAFO_BASE)}
            )
        if request.method == "PUT" and request.url.path == "/api/flows/1":
            enviado = json.loads(request.content)
            capturado["put_body"] = enviado
            capturado["grafo_atual"] = enviado["graph_json"]
            return httpx.Response(
                200,
                json={
                    "flow": {"id": 1, "graph_json": enviado["graph_json"]},
                    "warnings": [],
                },
            )
        return httpx.Response(404, json={"detail": "não mapeado no teste"})

    return _rota


@pytest.mark.asyncio
async def test_flow_add_block_anexa_no_com_exec_order_seguinte(cliente_falso) -> None:
    capturado: dict[str, Any] = {}
    cliente, _hub = await cliente_falso(_rota_grafo(capturado))

    resultado = await grafo.flow_add_block(
        cliente, 1, "opc_read", {"tag_id": 99}, {"x": 500.0, "y": 0.0}, "Leitura nova"
    )
    put_grafo = capturado["put_body"]["graph_json"]
    assert len(put_grafo["nodes"]) == 4
    novo = next(n for n in put_grafo["nodes"] if n["id"] == resultado["node_id"])
    assert novo["type"] == "opc_read"
    assert novo["data"] == {"exec_order": 4, "label": "Leitura nova", "tag_id": 99}
    assert novo["position"] == {"x": 500.0, "y": 0.0}
    # nós existentes intocados (id, exec_order, config preservados).
    assert put_grafo["nodes"][0] == _GRAFO_BASE["nodes"][0]


@pytest.mark.asyncio
async def test_flow_add_block_id_gerado_e_unico_mesmo_tipo_repetido(cliente_falso) -> None:
    capturado: dict[str, Any] = {}
    cliente, _hub = await cliente_falso(_rota_grafo(capturado))

    r1 = await grafo.flow_add_block(cliente, 1, "opc_read", {"tag_id": 10}, None, None)
    r2 = await grafo.flow_add_block(cliente, 1, "opc_read", {"tag_id": 11}, None, None)
    assert r1["node_id"] != r2["node_id"]


@pytest.mark.asyncio
async def test_flow_remove_block_remove_no_e_arestas_incidentes(cliente_falso) -> None:
    capturado: dict[str, Any] = {}
    cliente, _hub = await cliente_falso(_rota_grafo(capturado))

    await grafo.flow_remove_block(cliente, 1, "s1")
    put_grafo = capturado["put_body"]["graph_json"]
    assert {n["id"] for n in put_grafo["nodes"]} == {"r1", "w1"}
    # e1 (r1->s1) e e2 (s1->w1) incidem em s1 — as duas somem.
    assert put_grafo["edges"] == []


@pytest.mark.asyncio
async def test_flow_remove_block_renumera_exec_order_contiguo(cliente_falso) -> None:
    capturado: dict[str, Any] = {}
    cliente, _hub = await cliente_falso(_rota_grafo(capturado))

    await grafo.flow_remove_block(cliente, 1, "s1")  # tinha exec_order=2; r1=1, w1=3 antes
    put_grafo = capturado["put_body"]["graph_json"]
    ordens = {n["id"]: n["data"]["exec_order"] for n in put_grafo["nodes"]}
    assert ordens == {"r1": 1, "w1": 2}  # contíguo 1..2, ordem relativa preservada


@pytest.mark.asyncio
async def test_flow_update_block_config_patch_e_merge_raso(cliente_falso) -> None:
    capturado: dict[str, Any] = {}
    cliente, _hub = await cliente_falso(_rota_grafo(capturado))

    await grafo.flow_update_block(cliente, 1, "s1", {"code": "OUT1 = IN1 * 3"}, None, None, None)
    put_grafo = capturado["put_body"]["graph_json"]
    s1 = next(n for n in put_grafo["nodes"] if n["id"] == "s1")
    assert s1["data"]["code"] == "OUT1 = IN1 * 3"
    assert s1["data"]["n_inputs"] == 1  # chave fora do patch preservada
    assert s1["data"]["n_outputs"] == 1


@pytest.mark.asyncio
async def test_flow_update_block_reordena_exec_order_mantendo_contiguidade(cliente_falso) -> None:
    capturado: dict[str, Any] = {}
    cliente, _hub = await cliente_falso(_rota_grafo(capturado))

    # w1 (exec_order=3) vai para a posição 1 (primeiro a executar).
    await grafo.flow_update_block(cliente, 1, "w1", None, None, 1, None)
    put_grafo = capturado["put_body"]["graph_json"]
    ordens = {n["id"]: n["data"]["exec_order"] for n in put_grafo["nodes"]}
    assert ordens == {"w1": 1, "r1": 2, "s1": 3}
    assert sorted(ordens.values()) == [1, 2, 3]  # contíguo, sem buraco nem duplicata


@pytest.mark.asyncio
async def test_flow_update_block_bloco_inexistente_levanta_value_error(cliente_falso) -> None:
    capturado: dict[str, Any] = {}
    cliente, _hub = await cliente_falso(_rota_grafo(capturado))

    with pytest.raises(ValueError, match="não encontrado"):
        await grafo.flow_update_block(cliente, 1, "inexistente", {"x": 1}, None, None, None)


@pytest.mark.asyncio
async def test_flow_update_block_sem_exec_order_nao_toca_ordem_dos_outros(cliente_falso) -> None:
    """Regressão: `nodes` do JSON NÃO segue necessariamente a ordem de `exec_order` (React
    Flow reordena o array por seleção/z-index; ADR-024 existe justamente porque a ordem de
    execução é um campo explícito, não posição no array). Editar só `label`/`config` de UM
    bloco não pode reordenar `exec_order` de NINGUÉM — bug pego em revisão: a renumeração
    rodava incondicionalmente, fora do `if exec_order is not None`."""
    capturado: dict[str, Any] = {}
    grafo_embaralhado = {
        # array na ordem w1, r1, s1 — exec_order de cada um continua 3, 1, 2 (NÃO bate
        # com a posição no array).
        "nodes": [
            _GRAFO_BASE["nodes"][2],  # w1, data.exec_order == 3
            _GRAFO_BASE["nodes"][0],  # r1, data.exec_order == 1
            _GRAFO_BASE["nodes"][1],  # s1, data.exec_order == 2
        ],
        "edges": _GRAFO_BASE["edges"],
    }
    capturado["grafo_atual"] = grafo_embaralhado
    cliente, _hub = await cliente_falso(_rota_grafo(capturado))

    await grafo.flow_update_block(cliente, 1, "s1", None, None, None, "Novo rótulo")
    put_grafo = capturado["put_body"]["graph_json"]
    ordens = {n["id"]: n["data"]["exec_order"] for n in put_grafo["nodes"]}
    assert ordens == {"w1": 3, "r1": 1, "s1": 2}  # intocado — só o label de s1 mudou
    s1 = next(n for n in put_grafo["nodes"] if n["id"] == "s1")
    assert s1["data"]["label"] == "Novo rótulo"


@pytest.mark.asyncio
async def test_flow_connect_adiciona_aresta_com_id_unico(cliente_falso) -> None:
    capturado: dict[str, Any] = {}
    cliente, _hub = await cliente_falso(_rota_grafo(capturado))

    resultado = await grafo.flow_connect(cliente, 1, "r1", "out", "w1", "in")
    put_grafo = capturado["put_body"]["graph_json"]
    assert len(put_grafo["edges"]) == 3
    nova = next(e for e in put_grafo["edges"] if e["id"] == resultado["edge_id"])
    assert nova == {
        "id": resultado["edge_id"],
        "source": "r1",
        "target": "w1",
        "sourceHandle": "out",
        "targetHandle": "in",
    }


@pytest.mark.asyncio
async def test_flow_disconnect_remove_apenas_a_aresta_pedida(cliente_falso) -> None:
    capturado: dict[str, Any] = {}
    cliente, _hub = await cliente_falso(_rota_grafo(capturado))

    await grafo.flow_disconnect(cliente, 1, "e1")
    put_grafo = capturado["put_body"]["graph_json"]
    assert {e["id"] for e in put_grafo["edges"]} == {"e2"}


@pytest.mark.asyncio
async def test_flow_remove_block_id_inexistente_levanta_erro(cliente_falso) -> None:
    """Regressão: filtrar por id sem checar existência é no-op silencioso que ainda salva —
    falso-sucesso na superfície do agente (achado de revisão)."""
    capturado: dict[str, Any] = {}
    cliente, _hub = await cliente_falso(_rota_grafo(capturado))

    with pytest.raises(ValueError, match="não encontrado"):
        await grafo.flow_remove_block(cliente, 1, "inexistente")
    assert "put_body" not in capturado  # nunca salvou


@pytest.mark.asyncio
async def test_flow_disconnect_edge_id_inexistente_levanta_erro(cliente_falso) -> None:
    """Mesma regressão de `flow_remove_block`, para arestas."""
    capturado: dict[str, Any] = {}
    cliente, _hub = await cliente_falso(_rota_grafo(capturado))

    with pytest.raises(ValueError, match="não encontrada"):
        await grafo.flow_disconnect(cliente, 1, "inexistente")
    assert "put_body" not in capturado  # nunca salvou


@pytest.mark.asyncio
async def test_flow_create_body_exato(cliente_falso) -> None:
    capturado: dict[str, Any] = {}

    def _rota(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/flows":
            capturado["body"] = json.loads(request.content)
            return httpx.Response(201, json={"id": 42, "graph_json": {"nodes": [], "edges": []}})
        return httpx.Response(404)

    cliente, _hub = await cliente_falso(_rota)
    resultado = await grafo.flow_create(cliente, 7, "Flow novo", 1.0)
    assert capturado["body"] == {"project_id": 7, "name": "Flow novo", "ts_seconds": 1.0}
    assert resultado["id"] == 42
