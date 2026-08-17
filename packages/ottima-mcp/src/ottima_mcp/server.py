"""Servidor MCP: ferramentas de leitura sobre a API REST do OttimaSystem (ADR-036, Fase 2).

Superfície curada — só operação, monitoramento e engenharia de flows; nenhuma ferramenta de
users/certificates/connections-write/tags-write/projects-write/system-settings (ADR-036).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import Field

from ottima_core.contracts_export import build_contracts
from ottima_core.flowgraph.parse import NODE_TYPES
from ottima_mcp.cliente import ClienteOttima
from ottima_mcp.config import Config


@dataclass
class ContextoOttima:
    cliente: ClienteOttima


@asynccontextmanager
async def _lifespan(_server: MCPServer[ContextoOttima]) -> AsyncIterator[ContextoOttima]:
    cliente = await ClienteOttima.conectar(Config.do_ambiente())
    try:
        yield ContextoOttima(cliente=cliente)
    finally:
        await cliente.fechar()


mcp = MCPServer("ottima", lifespan=_lifespan)


def _cliente(ctx: Context[ContextoOttima]) -> ClienteOttima:
    return ctx.request_context.lifespan_context.cliente


# --------------------------------------------------------------------------------------
# Operação — leitura (escrita fica na Fase 3)
# --------------------------------------------------------------------------------------


@mcp.tool()
async def mpc_list(ctx: Context[ContextoOttima]) -> list[dict[str, Any]]:
    """Lista os blocos MPC do projeto ativo: config (MVs/CVs/Restrições/DVs, horizontes) —
    não o estado ao vivo (modos/valores correntes vêm de `mpc_state`, Fase 3)."""
    return await _cliente(ctx).get("/api/operate/mpcs")


@mcp.tool()
async def fuzzy_list(ctx: Context[ContextoOttima]) -> list[dict[str, Any]]:
    """Lista os blocos Fuzzy do projeto ativo (entradas/saídas por porta)."""
    return await _cliente(ctx).get("/api/operate/fuzzy")


@mcp.tool()
async def fuzzy_detail(
    flow_id: Annotated[int, Field(description="Id do flow que contém o bloco")],
    block_id: Annotated[str, Field(description="Id do bloco Fuzzy dentro do flow")],
    ctx: Context[ContextoOttima],
) -> dict[str, Any]:
    """Detalhe de um bloco Fuzzy: variáveis linguísticas, termos e regras (introspecção da
    FLL) — o frontend nunca parseia FLL (ADR-029); esta é a via de leitura completa."""
    return await _cliente(ctx).get(f"/api/operate/fuzzy/{flow_id}/{block_id}")


@mcp.tool()
async def ssto_last(
    flow_id: Annotated[int, Field(description="Id do flow que contém o bloco MPC")],
    block_id: Annotated[str, Field(description="Id do bloco MPC dentro do flow")],
    ctx: Context[ContextoOttima],
) -> dict[str, Any] | str:
    """Última execução do otimizador de regime permanente (SSTO) do bloco MPC. Devolve texto
    explicativo (não erro) se o bloco nunca rodou SSTO ainda."""
    resultado = await _cliente(ctx).get(
        "/api/history/ssto/last", flow_id=flow_id, block_id=block_id
    )
    if resultado is None:
        return f"Bloco '{block_id}' do flow {flow_id} ainda não executou nenhum ciclo de SSTO."
    return resultado


# --------------------------------------------------------------------------------------
# Monitoramento
# --------------------------------------------------------------------------------------


@mcp.tool()
async def trend(
    tag_ids: Annotated[
        list[int], Field(description="Ids de tag OPC a consultar (máx. 6 por chamada)")
    ],
    ctx: Context[ContextoOttima],
    start: Annotated[
        str | None, Field(description="Início ISO-8601 (default: 1h atrás)")
    ] = None,
    end: Annotated[str | None, Field(description="Fim ISO-8601 (default: agora)")] = None,
) -> dict[str, Any]:
    """Série histórica de tags OPC. Downsample automático: dado bruto até 2h de janela,
    médias de 1 minuto acima disso (v_min/v_max aparecem só no modo agregado)."""
    ids = ",".join(str(i) for i in tag_ids)
    return await _cliente(ctx).get("/api/history", tag_ids=ids, start=start, end=end)


@mcp.tool()
async def mpc_history(
    flow_id: Annotated[int, Field(description="Id do flow")],
    block_id: Annotated[str, Field(description="Id do bloco MPC")],
    var_ids: Annotated[
        list[str], Field(description="Ids de variáveis do MPC a consultar (máx. 14)")
    ],
    ctx: Context[ContextoOttima],
    start: Annotated[str | None, Field(description="Início ISO-8601")] = None,
    end: Annotated[str | None, Field(description="Fim ISO-8601")] = None,
) -> dict[str, Any]:
    """Série histórica de variáveis de um MPC: valor, SP (só CV) e modo AUTO/MAN por
    amostra — histórico de comando, não de confirmação em tempo real (ver `mpc_state`)."""
    ids = ",".join(var_ids)
    return await _cliente(ctx).get(
        "/api/history/mpc", flow_id=flow_id, block_id=block_id, var_ids=ids, start=start, end=end
    )


@mcp.tool()
async def events_query(
    ctx: Context[ContextoOttima],
    severity: Annotated[
        str | None, Field(description="Filtro: 'info', 'warning' ou 'alarm'")
    ] = None,
    origin: Annotated[str | None, Field(description="Filtro por origem exata")] = None,
    start: Annotated[str | None, Field(description="Início ISO-8601")] = None,
    end: Annotated[str | None, Field(description="Fim ISO-8601")] = None,
    limit: Annotated[int, Field(description="Máximo de eventos (1-1000)", ge=1, le=1000)] = 100,
) -> dict[str, Any]:
    """Log de eventos de auditoria/alarme, mais recente primeiro. `cursor` no retorno é o
    timestamp do evento MAIS ANTIGO desta página — passe como `end` da próxima chamada
    para avançar para eventos mais antigos ainda (paginação para trás no tempo).

    # ponytail: cursor codifica ts, não id (a tabela `events` não tem coluna id hoje) —
    # `ts <= end` é inclusivo no backend (events.py:48), então o evento mais antigo da
    # página N reaparece como o mais recente da página N+1 (1 duplicata por página, nunca
    # perda nem loop). v2 migra para coluna id e passa a codificar id sem quebrar este
    # contrato (mesma chave `cursor`), eliminando a duplicata.
    """
    eventos = await _cliente(ctx).get(
        "/api/events", severity=severity, origin=origin, start=start, end=end, limit=limit
    )
    cursor = eventos[-1]["ts"] if eventos else None
    return {"eventos": eventos, "cursor": cursor}


@mcp.tool()
async def system_health(ctx: Context[ContextoOttima]) -> dict[str, Any]:
    """Saúde do sistema: API (redis/db) + os 4 workers (opc-worker, flow-runtime, recorder,
    calc-worker)."""
    cliente = _cliente(ctx)
    api = await cliente.get("/api/health")
    workers = await cliente.get("/api/health/workers")
    return {"api": api, "workers": workers}


# --------------------------------------------------------------------------------------
# Engenharia de flows — leitura (mutação fica na Fase 4)
# --------------------------------------------------------------------------------------


@mcp.tool()
async def flow_list(
    ctx: Context[ContextoOttima],
    project_id: Annotated[int | None, Field(description="Filtra por projeto")] = None,
) -> list[dict[str, Any]]:
    """Lista flows (sem o grafo — use `flow_get` para o desenho completo)."""
    return await _cliente(ctx).get("/api/flows", project_id=project_id)


@mcp.tool()
async def flow_get(
    flow_id: Annotated[int, Field(description="Id do flow")], ctx: Context[ContextoOttima]
) -> dict[str, Any]:
    """Detalhe completo de um flow, incluindo `graph_json` (nós e arestas)."""
    return await _cliente(ctx).get(f"/api/flows/{flow_id}")


@mcp.tool()
def block_catalog() -> dict[str, Any]:
    """Catálogo de tipos de bloco válidos, contratos de porta e forma de config por bloco —
    consultar antes de montar `config` em `flow_add_block` (Fase 4). Fonte única, gerada do
    backend (`ottima_core.contracts_export`), nunca reimplementada aqui."""
    return {"node_types": list(NODE_TYPES), **build_contracts()}
