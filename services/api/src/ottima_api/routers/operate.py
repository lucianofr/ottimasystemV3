"""Rotas `/api/operate`: modo, SP e MV do bloco MPC (spec F4 §4.8/§6.1, decisão A-2; emenda §1.3-3).

Regra do Estado Publicado (DESIGN.md): a API não conhece o modo vigente do bloco — só valida
forma e faixa contra o `graph_json` já persistido (sempre válido: `PUT /api/flows/{id}` só
grava grafo que passou por `validate_graph`, spec F3 §5.2). Flow inexistente é 404, mesma
constante de `flows.py` (emenda §1.3-3, decisão A-9): identifica o recurso comandado, igual
ao CRUD. Bloco inexistente/errado, enum incompatível, var fora de categoria e valor fora de
faixa seguem no canal 422 pt-BR string única (spec §6.1).

Sucesso publica `FlowCommand{cmd: mpc_mode|mpc_sp|mpc_mv}` em `flow.commands` e responde 202
— nenhum evento sai daqui; quem materializa e audita (`mpc_mode_changed`/`mpc_sp_written`/
`mpc_mv_written`) é o runtime, ao processar o comando (spec §4.8).
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, get_redis, require_operator
from ottima_api.messages import MSG_FLOW_NAO_ENCONTRADO
from ottima_core.bus import CHANNEL_FLOW_COMMANDS, FlowCommand
from ottima_core.flowgraph import (
    ConstraintObjective,
    CvObjective,
    CvVar,
    FlowGraph,
    FlowNode,
    GraphParseError,
    Horizons,
    Limits,
    MpcConfig,
    MvObjective,
    MvVar,
    Range,
    TagConfig,
    derive_horizons,
    parse_graph,
)
from ottima_core.flowgraph.introspect import FuzzyIntrospection, introspect_fll
from ottima_core.models import Flow, Project, User
from ottima_core.schemas.flows import MAX_BIGINT

logger = logging.getLogger(__name__)

router = APIRouter()

FlowId = Annotated[int, Path(ge=1, le=MAX_BIGINT)]
BlockId = Annotated[str, Path(min_length=1)]

Axis = Literal["local_remote", "man_auto"]
AxisValue = Literal["local", "remote", "man", "auto"]

_VALORES_DO_EIXO: dict[Axis, frozenset[AxisValue]] = {
    "local_remote": frozenset({"local", "remote"}),
    "man_auto": frozenset({"man", "auto"}),
}


class ModeCommand(BaseModel):
    axis: Axis
    value: AxisValue


class SpCommand(BaseModel):
    var_id: str
    value: float


class MvCommand(BaseModel):
    var_id: str
    value: float


class MvOut(BaseModel):
    """Projeção de uma MV do bloco (spec §4.1-1) — sem `pid`/`initial_value`/`psv` (§4.1-3).

    `tag_id`: tag da posição real (readback do `pid` ou da MV direta) — a operação assina
    `opc.values` dela para o PV na taxa OPC (decisão F6 A-1 revertida). `zero`/`span`: faixa
    de instrumento — a escala do faceplate (RF-609)."""

    id: str
    name: str
    eu: str
    description: str = ""
    zero: float = 0.0
    span: float = 100.0
    limits: Limits
    max_rate: float
    objective: MvObjective
    tag_id: int | None = None


class CvOut(BaseModel):
    """Projeção de uma CV do bloco (spec §4.1-1) — sem `weight`/`tss`/`kind` (§4.1-3).

    `tag_id`: tag OPC que alimenta a CV (aresta direta de um `opc_read`); `None` quando a
    origem é filtro/script — o faceplate cai para a taxa do `mpc.state`. `remote_sp`: SP
    vem de tag OPC (RF-614) — a escrita manual é recusada (422) e a UI desabilita o campo.
    `priority`: rank do SSTO (ADR-027 §5) — maior = mais importante; o faceplate da operação
    usa para o marcador numérico de prioridade.
    """

    id: str
    name: str
    eu: str
    description: str = ""
    zero: float = 0.0
    span: float = 100.0
    sp_limits: Limits
    priority: int
    objective: CvObjective
    tag_id: int | None = None
    remote_sp: bool = False


class ConstraintOut(BaseModel):
    """Projeção de uma Restrição do bloco (spec §4.1-1) — sem `tss`/`kind` (§4.1-3).

    `priority`: rank do SSTO (ADR-019/ADR-027 §5) — maior = mais importante; o faceplate da
    operação usa para o marcador numérico de prioridade.
    """

    id: str
    name: str
    eu: str
    description: str = ""
    zero: float = 0.0
    span: float = 100.0
    range: Range
    priority: int
    objective: ConstraintObjective
    tag_id: int | None = None


class DvOut(BaseModel):
    """Projeção de uma DV do bloco (spec §4.1-1) — `range` opcional (§4.2, RF-702)."""

    id: str
    name: str
    eu: str
    zero: float = 0.0
    span: float = 100.0
    range: Range | None = None
    tag_id: int | None = None


class MpcVariablesOut(BaseModel):
    mvs: list[MvOut]
    cvs: list[CvOut]
    constraints: list[ConstraintOut]
    dvs: list[DvOut]


class MpcNodeOut(BaseModel):
    """Um bloco `mpc` projetado (spec §4.1-1) — sem `models`/pesos/TSS (§4.1-3); estado
    rodando/parado do flow não entra (§4.1-4).

    `horizons` é derivado no servidor porque a projeção não expõe `tss` (§4.1-3): sem ele o
    cliente teria de duplicar a regra de `derive_horizons` com metade da entrada.
    """

    flow_id: int
    flow_name: str
    flow_ts_seconds: float
    block_id: str
    name: str
    multiplier: int
    variables: MpcVariablesOut
    horizons: Horizons


class FuzzyPortOut(BaseModel):
    port: str
    name: str


class FuzzyOutputPortOut(BaseModel):
    port: str
    name: str
    eu: str | None = None


class FuzzyNodeOut(BaseModel):
    """Um bloco `fuzzy` projetado (ADR-030, ADR-029) — nomes de porta vêm de `introspect_fll`
    (o frontend nunca parseia FLL). Curvas de pertinência descartadas na listagem: só a
    página de detalhe (`GET .../{block_id}`) paga o custo completo da introspecção.
    """

    flow_id: int
    flow_name: str
    block_id: str
    block_name: str  # `label` do nó; cai para o `block_id` quando o canvas não nomeou o bloco
    inputs: list[FuzzyPortOut]
    outputs: list[FuzzyOutputPortOut]


class FuzzyDetailOut(BaseModel):
    """Detalhe completo de um bloco `fuzzy` (ADR-030): introspecção com curvas de
    pertinência, normas e texto das regras, para a página FUZZY OPERATE."""

    flow_id: int
    flow_name: str
    block_id: str
    block_name: str
    output_eu: dict[str, str]
    introspection: FuzzyIntrospection


def _reprovado(mensagem: str) -> HTTPException:
    """422 de domínio com `detail` string única, como no resto da API (padrão `flows.py`)."""
    return HTTPException(status_code=422, detail=mensagem)


async def _mpc_config(db: AsyncSession, flow_id: int, block_id: str) -> MpcConfig:
    """Bloco `mpc` tipado, ou 404 (flow inexistente) / 422 (bloco, spec §6.1)."""
    flow = await db.get(Flow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=MSG_FLOW_NAO_ENCONTRADO)
    graph = parse_graph(flow.graph_json)
    try:
        node = graph.node(block_id)
    except KeyError:
        raise _reprovado(f"Bloco '{block_id}' não encontrado no flow") from None
    if node.type != "mpc":
        raise _reprovado(f"Bloco '{block_id}' não é um bloco MPC")
    return MpcConfig.model_validate(node.config.model_dump())


def _cv_do_bloco(config: MpcConfig, var_id: str) -> CvVar:
    for cv in config.variables.cvs:
        if cv.id == var_id:
            return cv
    raise _reprovado(f"'{var_id}' não é uma CV do bloco")


def _mv_do_bloco(config: MpcConfig, var_id: str) -> MvVar:
    for mv in config.variables.mvs:
        if mv.id == var_id:
            return mv
    raise _reprovado(f"'{var_id}' não é uma MV do bloco")


async def _publicar_comando(
    redis_client: Redis, user: User, flow_id: int, cmd: str, args: dict
) -> None:
    """Publica em `flow.commands` (mesmo padrão de `flows.py::_publicar_comando`, generalizado
    com `args`): falha de publicação não derruba a rota — comando é intenção, o runtime
    materializa e audita (spec §4.8); comando perdido = nada aconteceu.
    """
    comando = FlowCommand(
        flow_id=flow_id, cmd=cmd, args=args, user=f"user:{user.id}", ts=datetime.now(UTC)
    )
    try:
        await redis_client.publish(CHANNEL_FLOW_COMMANDS, comando.model_dump_json())
    except Exception:
        logger.exception("Falha ao publicar comando '%s' do flow %s", cmd, flow_id)


@router.post("/{flow_id}/{block_id}/mode", status_code=202)
async def set_mode(
    flow_id: FlowId,
    block_id: BlockId,
    body: ModeCommand,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    redis_client: Redis = Depends(get_redis),
) -> Response:
    await _mpc_config(db, flow_id, block_id)
    if body.value not in _VALORES_DO_EIXO[body.axis]:
        raise _reprovado(f"Valor '{body.value}' não é válido para o eixo '{body.axis}'")
    await _publicar_comando(
        redis_client,
        user,
        flow_id,
        "mpc_mode",
        {"block_id": block_id, "axis": body.axis, "value": body.value},
    )
    return Response(status_code=202)


@router.post("/{flow_id}/{block_id}/sp", status_code=202)
async def set_sp(
    flow_id: FlowId,
    block_id: BlockId,
    body: SpCommand,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    redis_client: Redis = Depends(get_redis),
) -> Response:
    config = await _mpc_config(db, flow_id, block_id)
    cv = _cv_do_bloco(config, body.var_id)
    if cv.remote_sp_tag_id is not None:
        raise _reprovado("SP desta CV é remoto (tag OPC)")
    if not (cv.sp_limits.min <= body.value <= cv.sp_limits.max):
        raise _reprovado(
            f"Valor {body.value} fora da faixa de SP de '{body.var_id}' "
            f"({cv.sp_limits.min}..{cv.sp_limits.max})"
        )
    await _publicar_comando(
        redis_client,
        user,
        flow_id,
        "mpc_sp",
        {"block_id": block_id, "var_id": body.var_id, "value": body.value},
    )
    return Response(status_code=202)


@router.post("/{flow_id}/{block_id}/mv", status_code=202)
async def set_mv(
    flow_id: FlowId,
    block_id: BlockId,
    body: MvCommand,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    redis_client: Redis = Depends(get_redis),
) -> Response:
    config = await _mpc_config(db, flow_id, block_id)
    mv = _mv_do_bloco(config, body.var_id)
    if not (mv.limits.min <= body.value <= mv.limits.max):
        raise _reprovado(
            f"Valor {body.value} fora da faixa de MV '{body.var_id}' "
            f"({mv.limits.min}..{mv.limits.max})"
        )
    await _publicar_comando(
        redis_client,
        user,
        flow_id,
        "mpc_mv",
        {"block_id": block_id, "var_id": body.var_id, "value": body.value},
    )
    return Response(status_code=202)


def _horizontes(config: MpcConfig, ts_flow: float) -> Horizons:
    """Ts do MPC, Np e Nc do bloco (spec §2.2-5) — a mesma função pura que o runtime usa."""
    return derive_horizons(
        config.multiplier,
        ts_flow,
        [linha.tss for linha in (*config.variables.cvs, *config.variables.constraints)],
    )


def _tags_de_entrada(graph: FlowGraph, node_id: str) -> dict[str, int]:
    """Mapa `var_id -> tag_id` das entradas de um bloco `mpc` alimentadas DIRETO por um
    `opc_read` (aresta com `target == node_id` e `target_handle == var_id`). Origem que não
    é `opc_read` (filtro/script) não tem tag crua — a variável segue na taxa do `mpc.state`
    (fallback explícito da operação, sem erro)."""
    nos_por_id = {no.id: no for no in graph.nodes}
    tags: dict[str, int] = {}
    for edge in graph.edges:
        if edge.target != node_id:
            continue
        origem = nos_por_id.get(edge.source)
        if origem is None or origem.type != "opc_read":
            continue
        config = origem.config
        if isinstance(config, TagConfig):
            tags[edge.target_handle] = config.tag_id
    return tags


def _mpc_nodes(flow: Flow) -> list[MpcNodeOut]:
    """Projeta os blocos `mpc` de um flow (spec §4.1-1). `graph_json` que não parseia, ou
    cujo bloco `mpc` não tipa como `MpcConfig` (grafo estruturalmente válido mas conteúdo do
    bloco incompleto/inválido — `parse_graph` não valida o conteúdo do `mpc`, só a forma
    alheia a ele), é pulado com log, nunca 5xx: a listagem é melhor-esforço, não um recurso
    identificado por id que mereça 404/422 (mesma postura de defesa em profundidade do resto
    do domínio — ver Regra do Estado Publicado no topo do módulo).
    """
    saida: list[MpcNodeOut] = []
    try:
        graph = parse_graph(flow.graph_json)
        for node in graph.nodes:
            if node.type != "mpc":
                continue
            config = MpcConfig.model_validate(node.config.model_dump())
            tags_entrada = _tags_de_entrada(graph, node.id)
            saida.append(
                MpcNodeOut(
                    flow_id=flow.id,
                    flow_name=flow.name,
                    flow_ts_seconds=float(flow.ts_seconds),
                    block_id=node.id,
                    name=config.name,
                    multiplier=config.multiplier,
                    variables=MpcVariablesOut(
                        mvs=[
                            MvOut(
                                id=mv.id,
                                name=mv.name,
                                eu=mv.eu,
                                description=mv.description,
                                zero=mv.zero,
                                span=mv.span,
                                limits=mv.limits,
                                max_rate=mv.max_rate,
                                objective=mv.objective,
                                tag_id=(mv.pid.readback_tag_id if mv.pid else mv.readback_tag_id),
                            )
                            for mv in config.variables.mvs
                        ],
                        cvs=[
                            CvOut(
                                id=cv.id,
                                name=cv.name,
                                eu=cv.eu,
                                description=cv.description,
                                zero=cv.zero,
                                span=cv.span,
                                sp_limits=cv.sp_limits,
                                priority=cv.priority,
                                objective=cv.objective,
                                tag_id=tags_entrada.get(cv.id),
                                remote_sp=cv.remote_sp_tag_id is not None,
                            )
                            for cv in config.variables.cvs
                        ],
                        constraints=[
                            ConstraintOut(
                                id=co.id,
                                name=co.name,
                                eu=co.eu,
                                description=co.description,
                                zero=co.zero,
                                span=co.span,
                                range=co.range,
                                priority=co.priority,
                                objective=co.objective,
                                tag_id=tags_entrada.get(co.id),
                            )
                            for co in config.variables.constraints
                        ],
                        dvs=[
                            DvOut(
                                id=dv.id,
                                name=dv.name,
                                eu=dv.eu,
                                zero=dv.zero,
                                span=dv.span,
                                range=dv.range,
                                tag_id=tags_entrada.get(dv.id),
                            )
                            for dv in config.variables.dvs
                        ],
                    ),
                    horizons=_horizontes(config, float(flow.ts_seconds)),
                )
            )
    except (GraphParseError, ValueError):
        logger.warning(
            "Flow %s ('%s') com graph_json inválido; ignorado na projeção de MPCs",
            flow.id,
            flow.name,
        )
        return []
    return saida


@router.get("/mpcs", response_model=list[MpcNodeOut], dependencies=[Depends(require_operator)])
async def list_mpcs(db: AsyncSession = Depends(get_db)) -> list[MpcNodeOut]:
    """Projeta os blocos MPC de todos os flows do projeto ativo (spec §4.1; decisão A-7).

    Sem projeto ativo, lista vazia (§4.1-4) — não há 404, o recurso é a projeção do projeto
    vigente, não um flow identificado. Estado rodando/parado do flow não entra na projeção.
    """
    project_id = await db.scalar(select(Project.id).where(Project.is_active))
    if project_id is None:
        return []
    flows = list(
        await db.scalars(select(Flow).where(Flow.project_id == project_id).order_by(Flow.name))
    )
    saida: list[MpcNodeOut] = []
    for flow in flows:
        saida.extend(_mpc_nodes(flow))
    return saida


def _fuzzy_flow_and_node(flow: Flow, block_id: str) -> FlowNode:
    """Bloco `fuzzy` tipado do flow já carregado (mesmo padrão de `_mpc_config`, sem tocar o
    banco de novo) — 422 se o bloco não existir ou não for `fuzzy`."""
    graph = parse_graph(flow.graph_json)
    try:
        node = graph.node(block_id)
    except KeyError:
        raise _reprovado(f"Bloco '{block_id}' não encontrado no flow") from None
    if node.type != "fuzzy":
        raise _reprovado(f"Bloco '{block_id}' não é um bloco Fuzzy")
    return node


def _fuzzy_nodes(flow: Flow) -> list[FuzzyNodeOut]:
    """Projeta os blocos `fuzzy` de um flow (ADR-030): nomes de porta vêm de `introspect_fll`,
    curvas descartadas. `graph_json`/FLL que não parseia é pulado com log, nunca 5xx — mesma
    postura melhor-esforço de `_mpc_nodes`."""
    saida: list[FuzzyNodeOut] = []
    try:
        graph = parse_graph(flow.graph_json)
        for node in graph.nodes:
            if node.type != "fuzzy":
                continue
            config = node.config
            intro = introspect_fll(config.fll)
            saida.append(
                FuzzyNodeOut(
                    flow_id=flow.id,
                    flow_name=flow.name,
                    block_id=node.id,
                    block_name=node.label or node.id,
                    inputs=[FuzzyPortOut(port=v.port, name=v.name) for v in intro.inputs],
                    outputs=[
                        FuzzyOutputPortOut(
                            port=v.port, name=v.name, eu=config.output_eu.get(v.port)
                        )
                        for v in intro.outputs
                    ],
                )
            )
    except (GraphParseError, ValueError):
        logger.warning(
            "Flow %s ('%s') com graph_json/FLL inválido; ignorado na projeção de Fuzzy",
            flow.id,
            flow.name,
        )
        return []
    return saida


@router.get("/fuzzy", response_model=list[FuzzyNodeOut], dependencies=[Depends(require_operator)])
async def list_fuzzy(db: AsyncSession = Depends(get_db)) -> list[FuzzyNodeOut]:
    """Projeta os blocos Fuzzy de todos os flows do projeto ativo (ADR-030), mesmo escopo e
    consulta de `GET /mpcs` (decisão A-7): sem projeto ativo, lista vazia — não há 404.
    """
    project_id = await db.scalar(select(Project.id).where(Project.is_active))
    if project_id is None:
        return []
    flows = list(
        await db.scalars(select(Flow).where(Flow.project_id == project_id).order_by(Flow.name))
    )
    # `_fuzzy_nodes` reparseia FLL (CPU-bound, O(pontos × termos) por bloco): fora do event
    # loop, como o `get_fuzzy_detail` e como o save faz com `validate_graph` (ADR-029). Um
    # único hop para todos os flows — `Flow.graph_json`/`name`/`id` já vieram carregados.
    return await asyncio.to_thread(lambda: [no for flow in flows for no in _fuzzy_nodes(flow)])


@router.get(
    "/fuzzy/{flow_id}/{block_id}",
    response_model=FuzzyDetailOut,
    dependencies=[Depends(require_operator)],
)
async def get_fuzzy_detail(
    flow_id: FlowId, block_id: BlockId, db: AsyncSession = Depends(get_db)
) -> FuzzyDetailOut:
    """Introspecção completa do bloco Fuzzy (ADR-030): curvas de pertinência, normas e regras
    para a página de detalhe — o frontend nunca parseia FLL (ADR-029). FLL que não parseia
    (não deveria acontecer pós-save, defesa em profundidade) vira 422 com a mensagem do
    `ValueError` de `introspect_fll`.
    """
    flow = await db.get(Flow, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=MSG_FLOW_NAO_ENCONTRADO)
    node = _fuzzy_flow_and_node(flow, block_id)
    try:
        intro = await asyncio.to_thread(introspect_fll, node.config.fll)
    except ValueError as erro:
        raise _reprovado(str(erro)) from erro
    return FuzzyDetailOut(
        flow_id=flow.id,
        flow_name=flow.name,
        block_id=node.id,
        block_name=node.label or node.id,
        output_eu=node.config.output_eu,
        introspection=intro,
    )
