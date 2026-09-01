"""Ferramentas de leitura do servidor MCP (Fase 2): cada uma chama a rota REST certa e
devolve a forma esperada. `@mcp.tool()` devolve a função original — chamável direto com um
`Context` falso, sem precisar do protocolo MCP inteiro."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from ottima_mcp import server


def _ctx(cliente: Any) -> Any:
    """Duck-type do `Context[ContextoOttima]`: `server._cliente(ctx)` só acessa
    `ctx.request_context.lifespan_context.cliente` — nada mais do SDK é necessário aqui."""
    return SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context=SimpleNamespace(cliente=cliente))
    )


@pytest.mark.asyncio
async def test_mpc_list_devolve_lista_crua(cliente_falso) -> None:
    cliente, _hub = await cliente_falso(
        lambda r: httpx.Response(200, json=[{"block_id": "mpc1", "flow_id": 1}])
    )
    resultado = await server.mpc_list(_ctx(cliente))
    assert resultado == [{"block_id": "mpc1", "flow_id": 1}]


@pytest.mark.asyncio
async def test_fuzzy_detail_monta_path_com_flow_e_block(cliente_falso) -> None:
    capturado = {}

    def _rota(request: httpx.Request) -> httpx.Response:
        capturado["path"] = request.url.path
        return httpx.Response(200, json={"block_id": "fz1"})

    cliente, _hub = await cliente_falso(_rota)
    resultado = await server.fuzzy_detail(3, "fz1", _ctx(cliente))
    assert capturado["path"] == "/api/operate/fuzzy/3/fz1"
    assert resultado == {"block_id": "fz1"}


@pytest.mark.asyncio
async def test_ssto_last_none_vira_texto_explicativo_nao_erro(cliente_falso) -> None:
    cliente, _hub = await cliente_falso(lambda r: httpx.Response(200, content=b"null"))
    resultado = await server.ssto_last(1, "mpc1", _ctx(cliente))
    assert isinstance(resultado, str)
    assert "ainda não executou" in resultado


@pytest.mark.asyncio
async def test_ssto_last_com_run_repassa_o_corpo(cliente_falso) -> None:
    corpo = {"ts": "2026-08-17T00:00:00Z", "run": {"run_id": "abc", "status": "optimal"}}
    cliente, _hub = await cliente_falso(lambda r: httpx.Response(200, json=corpo))
    resultado = await server.ssto_last(1, "mpc1", _ctx(cliente))
    assert resultado == corpo


@pytest.mark.asyncio
async def test_trend_junta_tag_ids_em_csv_na_query(cliente_falso) -> None:
    capturado = {}

    def _rota(request: httpx.Request) -> httpx.Response:
        capturado["query"] = dict(request.url.params)
        return httpx.Response(200, json={"mode": "raw", "series": []})

    cliente, _hub = await cliente_falso(_rota)
    await server.trend([1, 2, 3], _ctx(cliente))
    assert capturado["query"]["tag_ids"] == "1,2,3"


@pytest.mark.asyncio
async def test_mpc_history_junta_var_ids_e_usa_block_id_string(cliente_falso) -> None:
    capturado = {}

    def _rota(request: httpx.Request) -> httpx.Response:
        capturado["query"] = dict(request.url.params)
        return httpx.Response(200, json={"mode": "raw", "series": []})

    cliente, _hub = await cliente_falso(_rota)
    await server.mpc_history(1, "mpc1", ["mv_a", "cv_a"], _ctx(cliente))
    assert capturado["query"] == {
        "flow_id": "1",
        "block_id": "mpc1",
        "var_ids": "mv_a,cv_a",
    }


def _evento(ts: str) -> dict[str, Any]:
    return {"ts": ts, "severity": "info", "origin": "x", "message": "m", "payload": {}}


@pytest.mark.asyncio
async def test_events_query_cursor_e_o_ts_do_evento_mais_antigo_da_pagina(cliente_falso) -> None:
    eventos = [_evento("2026-08-17T12:00:00Z"), _evento("2026-08-17T11:00:00Z")]
    cliente, _hub = await cliente_falso(lambda r: httpx.Response(200, json=eventos))
    resultado = await server.events_query(_ctx(cliente))
    assert resultado["eventos"] == eventos
    # o mais ANTIGO da página, não o mais recente
    assert resultado["cursor"] == "2026-08-17T11:00:00Z"


@pytest.mark.asyncio
async def test_events_query_pagina_avanca_para_eventos_mais_antigos(cliente_falso) -> None:
    """Backend real: `ORDER BY ts DESC` + `ts <= end` inclusivo (events.py:40,48). Prova que
    passar o `cursor` da página 1 como `end` da página 2 avança de verdade no tempo — não
    reproduz a mesma janela para sempre (o hub simula o filtro `end` de verdade, não devolve
    a resposta que o predicado já espera)."""
    todos = [
        _evento("2026-08-17T12:00:00Z"),
        _evento("2026-08-17T11:00:00Z"),
        _evento("2026-08-17T10:00:00Z"),
    ]

    def _rota(request: httpx.Request) -> httpx.Response:
        end = request.url.params.get("end")
        pagina = [e for e in todos if end is None or e["ts"] <= end][:2]
        return httpx.Response(200, json=pagina)

    cliente, _hub = await cliente_falso(_rota)
    pagina1 = await server.events_query(_ctx(cliente))
    assert [e["ts"] for e in pagina1["eventos"]] == ["2026-08-17T12:00:00Z", "2026-08-17T11:00:00Z"]
    assert pagina1["cursor"] == "2026-08-17T11:00:00Z"

    pagina2 = await server.events_query(_ctx(cliente), end=pagina1["cursor"])
    # limite inclusivo: o evento mais antigo da página 1 reaparece como o mais recente da
    # página 2 (1 duplicata documentada, não um bug) — mas a página INTEIRA nunca é igual à
    # anterior, prova de que houve progresso real para trás no tempo.
    assert [e["ts"] for e in pagina2["eventos"]] == ["2026-08-17T11:00:00Z", "2026-08-17T10:00:00Z"]
    assert pagina2["eventos"] != pagina1["eventos"]
    assert pagina2["cursor"] == "2026-08-17T10:00:00Z"
    assert pagina2["cursor"] < pagina1["cursor"]


@pytest.mark.asyncio
async def test_events_query_lista_vazia_cursor_none(cliente_falso) -> None:
    cliente, _hub = await cliente_falso(lambda r: httpx.Response(200, json=[]))
    resultado = await server.events_query(_ctx(cliente))
    assert resultado == {"eventos": [], "cursor": None}


@pytest.mark.asyncio
async def test_system_health_agrega_api_e_workers(cliente_falso) -> None:
    def _rota(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"opc_worker": {"up": True}})

    cliente, _hub = await cliente_falso(_rota)
    resultado = await server.system_health(_ctx(cliente))
    assert resultado == {"api": {"status": "ok"}, "workers": {"opc_worker": {"up": True}}}


@pytest.mark.asyncio
async def test_flow_list_e_flow_get(cliente_falso) -> None:
    def _rota(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/flows/1":
            return httpx.Response(200, json={"id": 1, "graph_json": {"nodes": [], "edges": []}})
        return httpx.Response(200, json=[{"id": 1, "name": "flow1"}])

    cliente, _hub = await cliente_falso(_rota)
    assert await server.flow_list(_ctx(cliente)) == [{"id": 1, "name": "flow1"}]
    detalhe = await server.flow_get(1, _ctx(cliente))
    assert detalhe["graph_json"] == {"nodes": [], "edges": []}


def test_block_catalog_expoe_node_types_e_contratos() -> None:
    catalogo = server.block_catalog()
    assert catalogo["node_types"] == [
        "opc_read",
        "opc_write",
        "script",
        "fuzzy",
        "tfs",
        "mpc",
        "first_order",
        "kalman",
        "pid",
    ]
    assert "port_contracts" in catalogo
    assert "node_configs" in catalogo
