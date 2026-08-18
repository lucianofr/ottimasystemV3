"""Servidor MCP sobre a API REST/WS do OttimaSystem (ADR-036). Ferramentas de leitura
(Fase 2) e de escrita de operação com confirmação publicada (Fase 3, RNF-05).

Superfície curada — só operação, monitoramento e engenharia de flows; nenhuma ferramenta de
users/certificates/connections-write/tags-write/projects-write/system-settings (ADR-036).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import Field

from ottima_core.bus import CHANNEL_EVENTS, channel_flow_status, channel_mpc_state
from ottima_core.contracts_export import build_contracts
from ottima_core.flowgraph.parse import NODE_TYPES
from ottima_mcp.cliente import ClienteOttima
from ottima_mcp.config import Config
from ottima_mcp.confirmacao import ErroConfirmacao, esperar_confirmacao
from ottima_mcp.grafo import flow_add_block as _grafo_add_block
from ottima_mcp.grafo import flow_connect as _grafo_connect
from ottima_mcp.grafo import flow_create as _grafo_create
from ottima_mcp.grafo import flow_disconnect as _grafo_disconnect
from ottima_mcp.grafo import flow_remove_block as _grafo_remove_block
from ottima_mcp.grafo import flow_update_block as _grafo_update_block


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
# Operação — escrita (Fase 3). Toda escrita espera a confirmação PUBLICADA pelo runtime
# (RNF-05: comandado ≠ confirmado) — nunca reporta sucesso só pelo 202 HTTP.
# --------------------------------------------------------------------------------------


async def _timeout_padrao(cliente: ClienteOttima, flow_id: int, block_id: str) -> float:
    """`limite = max(2×ts_mpc, 10s)`; o fator 2× sobrevive a UMA publicação de fronteira
    perdida na fila de profundidade 8 do `/ws` (`ws.py:QUEUE_MAX`)."""
    blocos = await cliente.get("/api/operate/mpcs")
    for bloco in blocos:
        if bloco["flow_id"] == flow_id and bloco["block_id"] == block_id:
            ts_mpc = bloco["flow_ts_seconds"] * bloco["multiplier"]
            return max(2 * ts_mpc, 10.0)
    return 10.0  # bloco não encontrado aqui — a rota REST relevante devolve 404/422 de verdade


def _origem_mpc(flow_id: int, block_id: str) -> str:
    """Mesmo formato usado pelo runtime para `origin` de eventos de bloco MPC
    (`mpc.py:169` `self._source`; `events.py:85` `mpc_block_origin`). O canal `events` é
    GLOBAL — sem filtrar por `origin`, o evento de OUTRO bloco com o mesmo `kind`/`var_id`
    confirmaria falsamente um comando que nunca foi aplicado ao bloco pedido."""
    return f"flow:{flow_id}/block:{block_id}"


def _erro_com_estado(erro: ErroConfirmacao) -> RuntimeError:
    if erro.ultimo_estado is None:
        return RuntimeError(erro.mensagem)
    detalhe = f"Último estado observado: {json.dumps(erro.ultimo_estado)}"
    return RuntimeError(f"{erro.mensagem} {detalhe}")


@mcp.tool()
async def mpc_set_mode(
    flow_id: Annotated[int, Field(description="Id do flow")],
    block_id: Annotated[str, Field(description="Id do bloco MPC")],
    axis: Annotated[
        Literal["local_remote", "man_auto"], Field(description="Eixo de modo a comandar")
    ],
    value: Annotated[
        Literal["local", "remote", "man", "auto"], Field(description="Valor alvo do eixo")
    ],
    ctx: Context[ContextoOttima],
    timeout: Annotated[  # noqa: ASYNC109 - parâmetro público da ferramenta, não reimplementação de wait_for
        float | None,
        Field(description="Segundos a esperar a confirmação; default: derivado do Ts do MPC"),
    ] = None,
) -> dict[str, Any]:
    """Troca o modo LOCAL/REMOTO ou MAN/AUTO de um MPC (ADR-010) e espera a confirmação
    publicada pelo runtime antes de devolver — nunca reporta sucesso só pelo 202 HTTP
    (RNF-05). `man_auto` só tem efeito com o bloco em REMOTO; comandado em LOCAL é
    silenciosamente ignorado pelo runtime (nenhum evento, nenhum erro) — o tempo esgotado
    nesse caso já vem com o diagnóstico certo, não é lentidão."""
    cliente = _cliente(ctx)
    canal = channel_mpc_state(flow_id, block_id)
    origem = _origem_mpc(flow_id, block_id)

    async def _publicar() -> None:
        await cliente.post(
            f"/api/operate/{flow_id}/{block_id}/mode", json={"axis": axis, "value": value}
        )

    def _sucesso(canal_msg: str, dado: dict[str, Any]) -> bool:
        if canal_msg == canal:
            return dado.get("modes", {}).get(axis) == value
        payload = dado.get("payload", {})
        return (
            dado.get("origin") == origem
            and payload.get("kind") == "mpc_mode_changed"
            and payload.get("axis") == axis
            and payload.get("to") == value
        )

    def _falha(canal_msg: str, dado: dict[str, Any]) -> bool:
        if canal_msg != CHANNEL_EVENTS or dado.get("origin") != origem:
            return False
        payload = dado.get("payload", {})
        return payload.get("kind") == "mpc_arm_failed" and payload.get("axis") == axis

    prazo = timeout if timeout is not None else await _timeout_padrao(cliente, flow_id, block_id)
    try:
        estado, evento_falha = await esperar_confirmacao(
            cliente,
            interesses={"mpc_state": [f"{flow_id}/{block_id}"], "events": True},
            publicar_comando=_publicar,
            predicado_sucesso=_sucesso,
            predicado_falha=_falha,
            canais_relevantes=(canal, CHANNEL_EVENTS),
            limite_segundos=prazo,
        )
    except ErroConfirmacao as erro:
        modos = (erro.ultimo_estado or {}).get("modes", {})
        if axis == "man_auto" and modos.get("local_remote") == "local":
            raise RuntimeError(
                "Tempo esgotado, mas o bloco está em LOCAL: MAN/AUTO só tem efeito em "
                "REMOTO (ADR-010) — o comando foi silenciosamente ignorado pelo runtime, "
                f"não é lentidão. Estado observado: {json.dumps(erro.ultimo_estado)}"
            ) from erro
        raise _erro_com_estado(erro) from erro
    if evento_falha is not None:
        razao = evento_falha.get("payload", {}).get("reason", evento_falha)
        raise RuntimeError(f"Comando recusado pelo runtime (mpc_arm_failed): {razao}")
    return estado or {}


@mcp.tool()
async def mpc_write_sp(
    flow_id: Annotated[int, Field(description="Id do flow")],
    block_id: Annotated[str, Field(description="Id do bloco MPC")],
    var_id: Annotated[str, Field(description="Id da CV (prefixo cv_)")],
    value: Annotated[float, Field(description="Novo SP, dentro de sp_limits")],
    ctx: Context[ContextoOttima],
    timeout: Annotated[  # noqa: ASYNC109 - parâmetro público da ferramenta, não reimplementação de wait_for
        float | None,
        Field(description="Segundos a esperar a confirmação; default: derivado do Ts do MPC"),
    ] = None,
) -> dict[str, Any]:
    """Escreve o SP de uma CV — só tem efeito com o bloco em REMOTO+AUTO (spec §4.8); fora
    disso o PV-tracking manda e o backend ignora silenciosamente (sem 422). Confirma por
    evento `mpc_sp_written` OU pelo campo `sp` publicado (é o comando aplicado, republicado
    a cada fronteira — cobre o evento perdido na fila do `/ws` e o retry idempotente do
    mesmo valor, `mpc.py:1043-1044`). Valor fora de `sp_limits` é 422 do backend, propagado
    como erro antes mesmo de esperar confirmação."""
    cliente = _cliente(ctx)
    canal = channel_mpc_state(flow_id, block_id)
    origem = _origem_mpc(flow_id, block_id)

    async def _publicar() -> None:
        await cliente.post(
            f"/api/operate/{flow_id}/{block_id}/sp", json={"var_id": var_id, "value": value}
        )

    def _sucesso(canal_msg: str, dado: dict[str, Any]) -> bool:
        if canal_msg == canal:
            sp_publicado = dado.get("vars", {}).get(var_id, {}).get("sp")
            return sp_publicado is not None and abs(sp_publicado - value) < 1e-9
        payload = dado.get("payload", {})
        return (
            dado.get("origin") == origem
            and payload.get("kind") == "mpc_sp_written"
            and payload.get("var_id") == var_id
        )

    prazo = timeout if timeout is not None else await _timeout_padrao(cliente, flow_id, block_id)
    try:
        estado, _evento_falha = await esperar_confirmacao(
            cliente,
            interesses={"mpc_state": [f"{flow_id}/{block_id}"], "events": True},
            publicar_comando=_publicar,
            predicado_sucesso=_sucesso,
            canais_relevantes=(canal, CHANNEL_EVENTS),
            limite_segundos=prazo,
        )
    except ErroConfirmacao as erro:
        modos = (erro.ultimo_estado or {}).get("modes", {})
        if modos.get("local_remote") != "remote" or modos.get("man_auto") != "auto":
            raise RuntimeError(
                "Tempo esgotado, mas o bloco não está em REMOTO+AUTO: SP só é aplicado "
                "nesse modo (spec §4.8) — o comando foi provavelmente ignorado "
                f"silenciosamente pelo runtime, não é lentidão. Modo observado: {modos}"
            ) from erro
        raise _erro_com_estado(erro) from erro
    return estado or {}


@mcp.tool()
async def mpc_write_mv(
    flow_id: Annotated[int, Field(description="Id do flow")],
    block_id: Annotated[str, Field(description="Id do bloco MPC")],
    var_id: Annotated[str, Field(description="Id da MV (prefixo mv_)")],
    value: Annotated[float, Field(description="Nova MV, dentro de limits")],
    ctx: Context[ContextoOttima],
    timeout: Annotated[  # noqa: ASYNC109 - parâmetro público da ferramenta, não reimplementação de wait_for
        float | None,
        Field(description="Segundos a esperar a confirmação; default: derivado do Ts do MPC"),
    ] = None,
) -> dict[str, Any]:
    """Escreve uma MV manualmente — só tem efeito com o bloco em REMOTO+MAN (spec §4.8,
    ADR-010: em LOCAL o sistema nunca escreve MV). Confirma **só** por evento
    `mpc_mv_written` — NUNCA pelo campo `v` publicado: `v` é a posição fisicamente aplicada
    (`mpc.py:1098`), rampeada por `max_rate` ao longo de vários ciclos (ADR-028); pode
    divergir do valor comandado por vários ciclos mesmo com o comando já aceito, e usar `v`
    como sucesso mentiria sobre isso. Valor fora de `limits` é 422 do backend, propagado
    como erro antes mesmo de esperar confirmação."""
    cliente = _cliente(ctx)
    canal = channel_mpc_state(flow_id, block_id)
    origem = _origem_mpc(flow_id, block_id)

    async def _publicar() -> None:
        await cliente.post(
            f"/api/operate/{flow_id}/{block_id}/mv", json={"var_id": var_id, "value": value}
        )

    def _sucesso(canal_msg: str, dado: dict[str, Any]) -> bool:
        if canal_msg != CHANNEL_EVENTS or dado.get("origin") != origem:
            return False
        payload = dado.get("payload", {})
        return payload.get("kind") == "mpc_mv_written" and payload.get("var_id") == var_id

    prazo = timeout if timeout is not None else await _timeout_padrao(cliente, flow_id, block_id)
    try:
        estado, _evento_falha = await esperar_confirmacao(
            cliente,
            interesses={"mpc_state": [f"{flow_id}/{block_id}"], "events": True},
            publicar_comando=_publicar,
            predicado_sucesso=_sucesso,
            canais_relevantes=(canal, CHANNEL_EVENTS),
            limite_segundos=prazo,
        )
    except ErroConfirmacao as erro:
        modos = (erro.ultimo_estado or {}).get("modes", {})
        if modos.get("local_remote") != "remote" or modos.get("man_auto") != "man":
            raise RuntimeError(
                "Tempo esgotado, mas o bloco não está em REMOTO+MAN: MV manual só é "
                "aplicada nesse modo (spec §4.8, ADR-010) — o comando foi provavelmente "
                f"ignorado silenciosamente pelo runtime, não é lentidão. Modo observado: {modos}"
            ) from erro
        raise RuntimeError(
            f"{erro.mensagem} O bloco MPC é idempotente para MV manual (mpc.py:1063-1064): "
            "se o valor pedido já é o vigente, nenhum novo evento é emitido. Confira "
            "`mpc_state` antes de reenviar o MESMO valor — reenviar não vai gerar novo "
            f"evento. Último estado observado: {json.dumps(erro.ultimo_estado)}"
            if erro.ultimo_estado is not None
            else erro.mensagem
        ) from erro
    return estado or {}


@mcp.tool()
async def mpc_state(
    flow_id: Annotated[int, Field(description="Id do flow")],
    block_id: Annotated[str, Field(description="Id do bloco MPC")],
    ctx: Context[ContextoOttima],
    timeout: Annotated[  # noqa: ASYNC109 - parâmetro público da ferramenta, não reimplementação de wait_for
        float | None,
        Field(description="Segundos a esperar a 1a publicação; default: derivado do Ts do MPC"),
    ] = None,
) -> dict[str, Any]:
    """Estado ao vivo de um MPC: modos, valores/SP correntes, custo, predição — a mesma
    fonte que o faceplate usa. Leitura one-shot: espera a primeira publicação em
    `mpc.state.<flow_id>.<block_id>` (não existe endpoint REST de estado vivo, só `/ws`)."""
    cliente = _cliente(ctx)
    canal = channel_mpc_state(flow_id, block_id)

    async def _nao_publica_nada() -> None:
        return None

    prazo = timeout if timeout is not None else await _timeout_padrao(cliente, flow_id, block_id)
    try:
        estado, _evento_falha = await esperar_confirmacao(
            cliente,
            interesses={"mpc_state": [f"{flow_id}/{block_id}"]},
            publicar_comando=_nao_publica_nada,
            predicado_sucesso=lambda canal_msg, _dado: canal_msg == canal,
            canais_relevantes=(canal,),
            limite_segundos=prazo,
        )
    except ErroConfirmacao as erro:
        raise RuntimeError(
            "Nenhuma publicação de mpc_state chegou dentro do tempo — o flow está rodando "
            f"e o bloco existe? {erro.mensagem}"
        ) from erro
    return estado or {}


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


# --------------------------------------------------------------------------------------
# Engenharia de flows — escrita (Fase 4). Read-modify-write do graph_json (grafo.py);
# deploy/stop seguem a mesma regra de confirmação publicada da Fase 3 (RNF-05).
# --------------------------------------------------------------------------------------


@mcp.tool()
async def flow_create(
    project_id: Annotated[int, Field(description="Id do projeto (deve ser o ativo)")],
    name: Annotated[str, Field(description="Nome do flow, único no projeto")],
    ts_seconds: Annotated[
        Literal[0.5, 1, 2, 5, 10, 30, 60], Field(description="Período de scan, em segundos")
    ],
    ctx: Context[ContextoOttima],
) -> dict[str, Any]:
    """Cria um flow novo, parado (ADR-017), com grafo vazio. Use `flow_add_block`/
    `flow_connect` para montar o desenho e `flow_deploy` para colocar em execução."""
    return await _grafo_create(_cliente(ctx), project_id, name, ts_seconds)


@mcp.tool()
async def flow_add_block(
    flow_id: Annotated[int, Field(description="Id do flow")],
    type: Annotated[
        Literal[
            "opc_read",
            "opc_write",
            "script",
            "fuzzy",
            "tfs",
            "mpc",
            "first_order",
            "kalman",
            "pid",
        ],
        Field(description="Tipo do bloco — ver block_catalog para os campos de config"),
    ],
    config: Annotated[
        dict[str, Any], Field(description="Campos de config do bloco (forma em block_catalog)")
    ],
    ctx: Context[ContextoOttima],
    position: Annotated[
        dict[str, float] | None, Field(description="{x, y} no canvas; default (0, 0)")
    ] = None,
    label: Annotated[str | None, Field(description="Rótulo opcional exibido no editor")] = None,
) -> dict[str, Any]:
    """Adiciona um bloco ao flow (read-modify-write do `graph_json` inteiro). `exec_order`
    é atribuído automaticamente (vai por último); use `flow_update_block` para reordenar.
    Devolve `node_id` gerado junto com o flow salvo e `warnings` (avisos não-bloqueantes de
    inversão de exec_order, RF-307). 422 do backend (campo de config inválido/desconhecido)
    propagado verbatim."""
    return await _grafo_add_block(_cliente(ctx), flow_id, type, config, position, label)


@mcp.tool()
async def flow_remove_block(
    flow_id: Annotated[int, Field(description="Id do flow")],
    block_id: Annotated[str, Field(description="Id do bloco a remover")],
    ctx: Context[ContextoOttima],
) -> dict[str, Any]:
    """Remove um bloco e toda aresta conectada a ele; renumera `exec_order` 1..N do
    restante."""
    return await _grafo_remove_block(_cliente(ctx), flow_id, block_id)


@mcp.tool()
async def flow_update_block(
    flow_id: Annotated[int, Field(description="Id do flow")],
    block_id: Annotated[str, Field(description="Id do bloco a editar")],
    ctx: Context[ContextoOttima],
    config_patch: Annotated[
        dict[str, Any] | None, Field(description="Campos de config a sobrescrever (merge raso)")
    ] = None,
    position: Annotated[dict[str, float] | None, Field(description="Novo {x, y}")] = None,
    exec_order: Annotated[
        int | None,
        Field(description="Nova posição de execução (1..N); o resto é renumerado ao redor"),
    ] = None,
    label: Annotated[str | None, Field(description="Novo rótulo")] = None,
) -> dict[str, Any]:
    """Edita um bloco existente. `config_patch` faz merge RASO — chaves ausentes no patch
    preservam o valor salvo; chave que o tipo do bloco não reconhece é 422."""
    return await _grafo_update_block(
        _cliente(ctx), flow_id, block_id, config_patch, position, exec_order, label
    )


@mcp.tool()
async def flow_connect(
    flow_id: Annotated[int, Field(description="Id do flow")],
    source: Annotated[str, Field(description="Id do bloco de origem")],
    source_handle: Annotated[str, Field(description="Porta de saída do bloco de origem")],
    target: Annotated[str, Field(description="Id do bloco de destino")],
    target_handle: Annotated[str, Field(description="Porta de entrada do bloco de destino")],
    ctx: Context[ContextoOttima],
) -> dict[str, Any]:
    """Conecta a saída de um bloco à entrada de outro. Portas: ver `block_catalog` para
    contratos fixos/dinâmicos; blocos MPC usam os ids das variáveis como porta (entrada:
    cvs/constraints/dvs; saída: mvs + `local`/`auto` fixas). 422 se a porta não existir, o
    tipo não bater, ou a conexão fechar um ciclo."""
    return await _grafo_connect(
        _cliente(ctx), flow_id, source, source_handle, target, target_handle
    )


@mcp.tool()
async def flow_disconnect(
    flow_id: Annotated[int, Field(description="Id do flow")],
    edge_id: Annotated[str, Field(description="Id da aresta a remover")],
    ctx: Context[ContextoOttima],
) -> dict[str, Any]:
    """Remove uma conexão entre blocos."""
    return await _grafo_disconnect(_cliente(ctx), flow_id, edge_id)


def _origem_flow(flow_id: int) -> str:
    """Mesmo formato usado pelo runtime para `origin` de eventos de flow
    (`services/flow-runtime/.../events.py:80-82` `flow_origin`) — mesmo motivo de
    `_origem_mpc`: `events` é canal global, sem escopo por flow no protocolo."""
    return f"flow:{flow_id}"

async def _estado_real_do_flow(cliente: ClienteOttima, flow_id: int) -> str | None:
    """`GET /api/health/workers` -> `flow_runtime.flows[id].state` é a mesma leitura de
    `FlowTask._state` que o evento `flow.status` carregaria (`state.py::to_health`,
    `Literal["running","stopped","failed"]`) — mas legível via REST mesmo quando o comando
    idempotente não publica nada (`_stop`/`_deploy` no-op: `supervisor.py:315-321,427-431`,
    "nenhum evento"). Ao contrário de `desired_state` (intenção gravada, pode divergir se
    um comando anterior se perdeu — RNF-05), isto é o estado REAL do supervisor. `None` se
    o worker está degradado ou o flow nunca foi materializado (nunca deployado) — o
    chamador trata como "não sei", nunca como sucesso."""
    try:
        resultado = await cliente.get("/api/health/workers")
    except Exception:  # noqa: BLE001 - best-effort: falha aqui nunca mascara o erro original
        return None
    flows = resultado.get("flow_runtime", {}).get("flows", {})
    return flows.get(str(flow_id), {}).get("state")


async def _aguardar_flow(
    cliente: ClienteOttima,
    flow_id: int,
    *,
    publicar_comando: Any,
    estado_alvo: str,
    limite_segundos: float | None,
) -> dict[str, Any]:
    """`flow.status` é republicado a cada varredura enquanto o flow roda (`scheduler.py:
    _publish_status`) — cobre o comando idempotente na origem (deploy num flow já rodando).
    Um flow PARADO não varre e não republica sozinho: se o comando for idempotente
    (`stop()` já parado) e nenhuma transição sair, nada chega nem no `/ws` nem no
    `ultimo_estado` desta mesma espera — o fallback abaixo consulta `/health/workers`
    (achado de revisão) só para o alvo `"stopped"`; para `"running"` (deploy) não serve:
    `_deploy` num flow já rodando é no-op que NUNCA lê o grafo (`_reload`, não `_deploy`, é
    quem hot-swapa — `supervisor.py:315-321`), então "running" no health não prova que a
    edição do agente entrou em vigor, só que ALGUMA definição está de pé."""
    canal = channel_flow_status(flow_id)
    origem = _origem_flow(flow_id)

    def _sucesso(canal_msg: str, dado: dict[str, Any]) -> bool:
        return canal_msg == canal and dado.get("state") == estado_alvo

    def _falha(canal_msg: str, dado: dict[str, Any]) -> bool:
        if canal_msg == canal:
            return dado.get("state") == "failed"
        payload = dado.get("payload", {})
        return (
            canal_msg == CHANNEL_EVENTS
            and dado.get("origin") == origem
            and payload.get("kind") in ("deploy_rejected", "reload_rejected")
        )

    prazo = limite_segundos if limite_segundos is not None else 15.0
    try:
        estado, evento_falha = await esperar_confirmacao(
            cliente,
            interesses={"flow_status": [flow_id], "events": True},
            publicar_comando=publicar_comando,
            predicado_sucesso=_sucesso,
            predicado_falha=_falha,
            canais_relevantes=(canal, CHANNEL_EVENTS),
            limite_segundos=prazo,
        )
    except ErroConfirmacao as erro:
        if erro.ultimo_estado is not None and erro.ultimo_estado.get("state") == estado_alvo:
            return erro.ultimo_estado  # comando idempotente: já estava no alvo (visto no /ws)
        if estado_alvo == "stopped":
            estado_real = await _estado_real_do_flow(cliente, flow_id)
            if estado_real == "stopped":
                return {"state": "stopped"}  # idempotente: confirmado via /health, sem evento
        raise _erro_com_estado(erro) from erro
    if evento_falha is not None:
        if evento_falha.get("state") == "failed":
            raise RuntimeError(f"Flow entrou em falha. Estado: {json.dumps(evento_falha)}")
        payload = evento_falha.get("payload", {})
        razao = payload.get("reason", evento_falha)
        raise RuntimeError(f"Comando recusado pelo runtime ({payload.get('kind')}): {razao}")
    return estado or {}


@mcp.tool()
async def flow_deploy(
    flow_id: Annotated[int, Field(description="Id do flow")],
    ctx: Context[ContextoOttima],
    timeout: Annotated[  # noqa: ASYNC109 - parâmetro público da ferramenta, não reimplementação de wait_for
        float | None, Field(description="Segundos a esperar a confirmação; default 15s")
    ] = None,
) -> dict[str, Any]:
    """Coloca o flow em execução e espera a confirmação publicada (`flow.status.state ==
    'running'`) antes de devolver — nunca reporta sucesso só pelo 202 HTTP (RNF-05). **Se o
    flow já está rodando, este comando é um no-op** (`_deploy` em `supervisor.py:315-321`:
    `return` sem ler o grafo) — a confirmação vem só da varredura que já estava publicando
    sozinha, não prova que uma edição recente entrou em vigor. Editar um flow rodando
    (`flow_add_block`/`flow_update_block`/etc.) já aplica a mudança sozinho via hot-swap
    (`_reload`, publicado automaticamente pelo `PUT` quando o flow está rodando —
    `flows.py:302-303`); `flow_deploy` não precisa ser chamado de novo depois de editar.
    Falha rápida em `deploy_rejected`/`reload_rejected` (projeto inativo, grafo inválido)
    ou `state == 'failed'`."""
    cliente = _cliente(ctx)

    async def _publicar() -> None:
        await cliente.post(f"/api/flows/{flow_id}/deploy")

    return await _aguardar_flow(
        cliente, flow_id, publicar_comando=_publicar, estado_alvo="running", limite_segundos=timeout
    )


@mcp.tool()
async def flow_stop(
    flow_id: Annotated[int, Field(description="Id do flow")],
    ctx: Context[ContextoOttima],
    timeout: Annotated[  # noqa: ASYNC109 - parâmetro público da ferramenta, não reimplementação de wait_for
        float | None, Field(description="Segundos a esperar a confirmação; default 15s")
    ] = None,
) -> dict[str, Any]:
    """Para o flow e espera a confirmação publicada (`flow.status.state == 'stopped'`)."""
    cliente = _cliente(ctx)

    async def _publicar() -> None:
        await cliente.post(f"/api/flows/{flow_id}/stop")

    return await _aguardar_flow(
        cliente, flow_id, publicar_comando=_publicar, estado_alvo="stopped", limite_segundos=timeout
    )
