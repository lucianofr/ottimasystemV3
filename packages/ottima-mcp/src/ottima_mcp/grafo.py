"""Mutações de `graph_json` via read-modify-write (Fase 4, ADR-036). `PUT /api/flows/{id}`
recebe o objeto `{nodes, edges}` INTEIRO — nunca patch parcial (`services/api/src/ottima_api/
routers/flows.py:209-296`, `packages/ottima-core/src/ottima_core/schemas/flows.py:59-77`).
Campos de config ficam FLATTENED em `node["data"]` junto de `exec_order`/`label` — nunca
aninhados sob uma chave `"config"` (`flowgraph/parse.py:_parse_node`); chave desconhecida em
`data` é 422 do backend.

`exec_order`: inteiro >=1, único, contíguo 1..N (ADR-024, `flowgraph/validate.py:
_check_exec_order`) — toda mutação que muda a contagem de nós renumera o resto.
"""

from __future__ import annotations

import secrets
from typing import Any

from ottima_mcp.cliente import ClienteOttima


def _gerar_id(prefixo: str, existentes: set[str]) -> str:
    while True:
        candidato = f"{prefixo}_{secrets.token_hex(4)}"
        if candidato not in existentes:
            return candidato


async def _ler_grafo(cliente: ClienteOttima, flow_id: int) -> dict[str, Any]:
    detalhe = await cliente.get(f"/api/flows/{flow_id}")
    return detalhe["graph_json"]


async def _salvar_grafo(
    cliente: ClienteOttima, flow_id: int, graph_json: dict[str, Any]
) -> dict[str, Any]:
    """PUT com `graph_json` inteiro; todos os outros campos de `FlowUpdate` ficam `None`
    (preservam o valor salvo — nome, Ts, watchdog intocados)."""
    return await cliente.put(f"/api/flows/{flow_id}", json={"graph_json": graph_json})


def _renumerar_por_exec_order_atual(nodes: list[dict[str, Any]]) -> None:
    """Ordena por `exec_order` corrente e reatribui 1..N contíguo — para remoção: a lista
    filtrada preserva a ordem do array `nodes` do JSON (não necessariamente a ordem de
    exec_order), então é preciso ordenar pelos valores ANTIGOS antes de fechar os buracos."""
    nodes.sort(key=lambda n: n["data"].get("exec_order", 0))
    _atribuir_exec_order_sequencial(nodes)


def _atribuir_exec_order_sequencial(nodes: list[dict[str, Any]]) -> None:
    """Atribui 1..N pela ordem ATUAL da lista, sem reordenar — para reposicionamento
    explícito (`flow_update_block`): a lista já foi montada na ordem final desejada; ordenar
    de novo pelo `exec_order` antigo desfaria o reposicionamento (bug pego em teste)."""
    for indice, node in enumerate(nodes, start=1):
        node["data"]["exec_order"] = indice


async def flow_create(
    cliente: ClienteOttima, project_id: int, name: str, ts_seconds: float
) -> dict[str, Any]:
    return await cliente.post(
        "/api/flows", json={"project_id": project_id, "name": name, "ts_seconds": ts_seconds}
    )


async def flow_add_block(
    cliente: ClienteOttima,
    flow_id: int,
    tipo: str,
    config: dict[str, Any],
    position: dict[str, float] | None,
    label: str | None,
) -> dict[str, Any]:
    grafo = await _ler_grafo(cliente, flow_id)
    ids_existentes = {n["id"] for n in grafo["nodes"]}
    novo_id = _gerar_id(tipo, ids_existentes)
    data: dict[str, Any] = {"exec_order": len(grafo["nodes"]) + 1, **config}
    if label is not None:
        data["label"] = label
    grafo["nodes"].append(
        {
            "id": novo_id,
            "type": tipo,
            "position": position or {"x": 0.0, "y": 0.0},
            "data": data,
        }
    )
    resultado = await _salvar_grafo(cliente, flow_id, grafo)
    resultado["node_id"] = novo_id
    return resultado


async def flow_remove_block(cliente: ClienteOttima, flow_id: int, block_id: str) -> dict[str, Any]:
    grafo = await _ler_grafo(cliente, flow_id)
    grafo["nodes"] = [n for n in grafo["nodes"] if n["id"] != block_id]
    grafo["edges"] = [
        e for e in grafo["edges"] if e["source"] != block_id and e["target"] != block_id
    ]
    _renumerar_por_exec_order_atual(grafo["nodes"])
    return await _salvar_grafo(cliente, flow_id, grafo)


async def flow_update_block(
    cliente: ClienteOttima,
    flow_id: int,
    block_id: str,
    config_patch: dict[str, Any] | None,
    position: dict[str, float] | None,
    exec_order: int | None,
    label: str | None,
) -> dict[str, Any]:
    grafo = await _ler_grafo(cliente, flow_id)
    alvo = next((n for n in grafo["nodes"] if n["id"] == block_id), None)
    if alvo is None:
        raise ValueError(f"Bloco '{block_id}' não encontrado no flow {flow_id}.")
    if config_patch:
        alvo["data"].update(config_patch)
    if label is not None:
        alvo["data"]["label"] = label
    if position is not None:
        alvo["position"] = position
    if exec_order is not None:
        outros = [n for n in grafo["nodes"] if n["id"] != block_id]
        outros.sort(key=lambda n: n["data"].get("exec_order", 0))
        posicao = max(1, min(exec_order, len(outros) + 1))
        outros.insert(posicao - 1, alvo)
        grafo["nodes"] = outros
        _atribuir_exec_order_sequencial(grafo["nodes"])
    return await _salvar_grafo(cliente, flow_id, grafo)


async def flow_connect(
    cliente: ClienteOttima,
    flow_id: int,
    source: str,
    source_handle: str,
    target: str,
    target_handle: str,
) -> dict[str, Any]:
    grafo = await _ler_grafo(cliente, flow_id)
    ids_existentes = {e["id"] for e in grafo["edges"]}
    nova_id = _gerar_id("e", ids_existentes)
    grafo["edges"].append(
        {
            "id": nova_id,
            "source": source,
            "target": target,
            "sourceHandle": source_handle,
            "targetHandle": target_handle,
        }
    )
    resultado = await _salvar_grafo(cliente, flow_id, grafo)
    resultado["edge_id"] = nova_id
    return resultado


async def flow_disconnect(cliente: ClienteOttima, flow_id: int, edge_id: str) -> dict[str, Any]:
    grafo = await _ler_grafo(cliente, flow_id)
    grafo["edges"] = [e for e in grafo["edges"] if e["id"] != edge_id]
    return await _salvar_grafo(cliente, flow_id, grafo)
