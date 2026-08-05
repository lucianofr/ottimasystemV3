"""Rotas `/api/operate`: modo, SP e MV do bloco MPC (spec F4 §4.8/§6.1, decisão A-2).

Regra do Estado Publicado (DESIGN.md): a API não conhece o modo vigente do bloco — só valida
forma e faixa contra o `graph_json` já persistido (sempre válido: `PUT /api/flows/{id}` só
grava grafo que passou por `validate_graph`, spec F3 §5.2). Toda reprovação daqui — flow
inexistente, bloco inexistente/errado, enum incompatível, var fora de categoria, valor fora
de faixa — sai pelo mesmo canal 422 pt-BR string única (spec §6.1): estas rotas comandam,
não identificam um recurso CRUD, então "flow existe" não é 404 aqui como em `flows.py`.

Sucesso publica `FlowCommand{cmd: mpc_mode|mpc_sp|mpc_mv}` em `flow.commands` e responde 202
— nenhum evento sai daqui; quem materializa e audita (`mpc_mode_changed`/`mpc_sp_written`/
`mpc_mv_written`) é o runtime, ao processar o comando (spec §4.8).
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, get_redis, require_operator
from ottima_core.bus import CHANNEL_FLOW_COMMANDS, FlowCommand
from ottima_core.flowgraph import CvVar, MpcConfig, MvVar, parse_graph
from ottima_core.models import Flow, User
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

MSG_FLOW_NAO_ENCONTRADO = "Flow não encontrado"


class ModeCommand(BaseModel):
    axis: Axis
    value: AxisValue


class SpCommand(BaseModel):
    var_id: str
    value: float


class MvCommand(BaseModel):
    var_id: str
    value: float


def _reprovado(mensagem: str) -> HTTPException:
    """422 de domínio com `detail` string única, como no resto da API (padrão `flows.py`)."""
    return HTTPException(status_code=422, detail=mensagem)


async def _mpc_config(db: AsyncSession, flow_id: int, block_id: str) -> MpcConfig:
    """Bloco `mpc` tipado, ou 422 (spec §6.1)."""
    flow = await db.get(Flow, flow_id)
    if flow is None:
        raise _reprovado(MSG_FLOW_NAO_ENCONTRADO)
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
