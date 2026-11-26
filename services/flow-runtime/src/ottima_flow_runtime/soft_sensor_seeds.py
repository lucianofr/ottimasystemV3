"""Sensor virtual no deploy: carga do modelo vinculado e pré-aquecimento pelo histórico.

Spec SENSOR_VIRTUAL §5.6-5 (o deploy carrega `desired_model_id` e iguala `active_model_id`) e
§5.7 (buffer de 256 passos lido de `samples`). Modelo ruim nunca derruba o deploy: o bloco
sobe sem modelo e ele mesmo avisa (`soft_sensor_model_missing`) com o `missing_reason`.

Sessões: nada aqui usa a sessão de `Supervisor._build`, que só lê e nunca dá commit. A
gravação do vínculo tem sessão e commit próprios; cada pré-aquecimento roda numa sessão
própria, porque o `wait_for` cancela a consulta no meio e a sessão cancelada não serve mais.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Container, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import undefer

from ottima_core.bus import (
    KIND_SOFT_SENSOR_MODEL_REJECTED,
    KIND_SOFT_SENSOR_PREWARM_SKIPPED,
    FlowCommand,
    publish_event,
)
from ottima_core.flowgraph import SOFT_SENSOR_METHOD, FlowGraph
from ottima_core.models import SoftSensorBinding, SoftSensorModel, Tag
from ottima_core.softsensor import (
    BUFFER_STEPS,
    PERIOD_TOLERANCE,
    LoadedModel,
    SampleBuffer,
    load_grid,
    load_model,
    model_steps,
)

from .blocks.base import Block
from .blocks.soft_sensor import BindingUpdate, SoftSensorBlock

logger = logging.getLogger(__name__)

PREWARM_TIMEOUT_S: Final[float] = 5.0
"""Prazo de TODO o pré-aquecimento de um deploy (spec §5.7), não de cada bloco: `load_seeds`
roda sob o `Supervisor._lock`, e N blocos lentos não podem somar N x 5 s."""

PERSIST_TIMEOUT_S: Final[float] = 2.0
"""Teto da gravação do vínculo, mesmo valor de `PERSIST_SP_TIMEOUT_S` do MPC. O bloco espera
`persist` sem limite (protegido do cancelamento); um banco parado não pode prender a
varredura, e a gravação de um bloco parado não pode atropelar por muito tempo a do redeploy."""

_ORIGIN = "flow-runtime"

EmitEvent = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class SoftSensorSeed:
    model: LoadedModel | None
    prewarm: SampleBuffer | None
    missing_reason: str | None


def model_mismatch(
    model_method: str,
    model_n_inputs: int,
    model_period_s: float,
    *,
    block_type: str,
    n_inputs: int,
    ts_seconds: float,
) -> str | None:
    """Motivo pelo qual o modelo não serve ao bloco, ou `None`. O bloco confia nisto: ele não
    trata `n_inputs` divergente nem período que não seja múltiplo inteiro >= 1 do Ts."""
    if SOFT_SENSOR_METHOD.get(block_type) != model_method:
        return "method"
    if model_n_inputs != n_inputs:
        return "n_inputs"
    if model_steps(model_period_s, ts_seconds) is None:
        return "period"
    return None


def make_emit_event(redis_client: Redis, flow_id: int) -> EmitEvent:
    """Evento do sensor virtual com `flow_id` no payload; o chamador dá o resto."""

    async def emit_event(*, payload: dict[str, Any] | None = None, **kwargs: Any) -> None:
        await publish_event(
            redis_client,
            ts=datetime.now(UTC),
            payload={"flow_id": flow_id, **(payload or {})},
            **kwargs,
        )

    return emit_event


def make_persist(
    session_factory: async_sessionmaker[AsyncSession] | None, flow_id: int, block_id: str
) -> Callable[[BindingUpdate], Awaitable[None]]:
    """Grava `active`/`candidate` (e, ao rejeitar, `desired = active`) no vínculo do bloco."""

    async def persist(change: BindingUpdate) -> None:
        if session_factory is None:
            return
        values: dict[str, int | None] = {
            "active_model_id": change.active_model_id,
            "candidate_model_id": change.candidate_model_id,
        }
        if change.reset_desired_to_active:
            values["desired_model_id"] = change.active_model_id
        await write_binding(session_factory, flow_id, block_id, **values)

    return persist


async def write_binding(
    session_factory: async_sessionmaker[AsyncSession],
    flow_id: int,
    block_id: str,
    **values: int | None,
) -> None:
    """Grava só as colunas dadas do vínculo; falha vira log, nunca exceção."""
    stmt = (
        update(SoftSensorBinding)
        .where(SoftSensorBinding.flow_id == flow_id, SoftSensorBinding.block_id == block_id)
        .values(**values)
    )

    async def write() -> None:
        async with session_factory() as session:
            await session.execute(stmt)
            await session.commit()

    try:
        await asyncio.wait_for(write(), timeout=PERSIST_TIMEOUT_S)
    except Exception:
        logger.exception("Sensor virtual '%s': falha ao gravar o vínculo", block_id)


async def load_seeds(
    session_factory: async_sessionmaker[AsyncSession],
    flow_id: int,
    graph: FlowGraph,
    *,
    ts_seconds: float,
    skip: Container[str],
    emit_event: EmitEvent,
) -> dict[str, SoftSensorSeed]:
    """Uma semente por nó de sensor virtual fora de `skip` (os blocos que o hot-swap reaproveita
    mantêm modelo e buffer vivos)."""
    nodes = [n for n in graph.nodes if n.type in SOFT_SENSOR_METHOD and n.id not in skip]
    if not nodes:
        return {}
    seeds: dict[str, SoftSensorSeed] = {}
    loaded: list[tuple[str, LoadedModel, list[int]]] = []
    async with session_factory() as session:
        bindings = await session.scalars(
            select(SoftSensorBinding).where(
                SoftSensorBinding.flow_id == flow_id,
                SoftSensorBinding.block_id.in_([n.id for n in nodes]),
            )
        )
        desired = {b.block_id: b.desired_model_id for b in bindings}
        rows = {
            m.id: m
            for m in await session.scalars(
                select(SoftSensorModel)
                .options(undefer(SoftSensorModel.weights))
                .where(SoftSensorModel.id.in_([i for i in desired.values() if i is not None]))
            )
        }
        for node in nodes:
            model_id = desired.get(node.id)
            row = rows.get(model_id) if model_id is not None else None
            if row is None:
                seeds[node.id] = SoftSensorSeed(None, None, "no_model")
                continue
            try:
                model = await asyncio.to_thread(load_model, row.id, row.meta, row.weights)
            except Exception as exc:  # ArtifactError e também `meta` JSONB que nem é objeto
                logger.warning("Sensor virtual '%s': modelo %s ilegível: %s", node.id, row.id, exc)
                seeds[node.id] = SoftSensorSeed(None, None, "corrupt")
                continue
            # O bloco usa os metadados do artefato, não as colunas: é contra eles que se confere.
            reason = model_mismatch(
                model.meta.method,
                model.n_inputs,
                model.meta.period_s,
                block_type=node.type,
                n_inputs=node.config.n_inputs,
                ts_seconds=ts_seconds,
            )
            if reason is not None:
                seeds[node.id] = SoftSensorSeed(None, None, reason)
                continue
            loaded.append((node.id, model, list(row.input_tag_ids)))
        input_ids = {t for _, _, tag_ids in loaded for t in tag_ids}
        existing = set(await session.scalars(select(Tag.id).where(Tag.id.in_(input_ids))))

    # Regra do Estado Publicado (ADR-002): o vínculo diz o que o bloco RODA — o modelo
    # carregado ou nenhum. `desired_model_id` é o pedido do usuário e fica como está.
    in_use = {block_id: model.model_id for block_id, model, _ in loaded}
    for block_id in desired:
        await make_persist(session_factory, flow_id, block_id)(
            BindingUpdate(active_model_id=in_use.get(block_id), candidate_model_id=None)
        )

    loop = asyncio.get_running_loop()
    deadline = loop.time() + PREWARM_TIMEOUT_S
    for block_id, model, tag_ids in loaded:
        buffer = await _warm(
            session_factory,
            block_id,
            model,
            tag_ids,
            existing,
            remaining=deadline - loop.time(),
            emit_event=emit_event,
        )
        seeds[block_id] = SoftSensorSeed(model, buffer, None)
    return seeds


async def _warm(
    session_factory: async_sessionmaker[AsyncSession],
    block_id: str,
    model: LoadedModel,
    tag_ids: list[int],
    existing: Container[int],
    *,
    remaining: float,
    emit_event: EmitEvent,
) -> SampleBuffer | None:
    """Pré-aquecimento de um bloco, com o aviso `prewarm_skipped` quando não dá."""
    if len(tag_ids) != model.n_inputs or not all(t in existing for t in tag_ids):
        buffer, skipped = None, "tags"
    else:
        buffer, skipped = await _prewarm(session_factory, model, tag_ids, remaining=remaining)
    if skipped is not None:
        try:
            await emit_event(
                severity="info",
                origin=_ORIGIN,
                message=f"Sensor virtual '{block_id}': sem pré-aquecimento ({skipped})",
                kind=KIND_SOFT_SENSOR_PREWARM_SKIPPED,
                payload={"block_id": block_id, "model_id": model.model_id, "reason": skipped},
            )
        except Exception:  # aviso perdido nunca impede o bloco de subir ou o candidato de entrar
            logger.exception("Sensor virtual '%s': falha ao emitir prewarm_skipped", block_id)
    return buffer


async def _prewarm(
    session_factory: async_sessionmaker[AsyncSession],
    model: LoadedModel,
    tag_ids: list[int],
    *,
    remaining: float,
) -> tuple[SampleBuffer | None, str | None]:
    """Buffer cheio pelo histórico, ou `None` e o motivo (`timeout`/`error`)."""
    if remaining <= 0:
        return None, "timeout"

    async def query() -> SampleBuffer:
        async with session_factory() as session:
            values, qualities = await load_grid(
                session,
                tag_ids,
                # A amostra da varredura 0 do bloco é o ponto k=0: a grade para um período antes.
                end=datetime.now(UTC) - timedelta(seconds=model.meta.period_s),
                period_s=model.meta.period_s,
                steps=BUFFER_STEPS,
            )
        buffer = SampleBuffer(model.n_inputs)
        buffer.preload(values, qualities)
        return buffer

    try:
        return await asyncio.wait_for(query(), timeout=remaining), None
    except TimeoutError:
        return None, "timeout"
    except Exception:
        logger.exception("Sensor virtual: pré-aquecimento do modelo %s falhou", model.model_id)
        return None, "error"


class _Runtime(Protocol):
    """O que o comando lê do `_FlowRuntime` do supervisor (import circular evitado)."""

    ts_seconds: float
    blocks: Mapping[str, tuple[Mapping[str, Any], Block]]


async def soft_sensor_command(
    session_factory: async_sessionmaker[AsyncSession],
    runtime: _Runtime,
    command: FlowCommand,
    *,
    emit_event: EmitEvent,
) -> None:
    """`soft_sensor_model` num flow rodando (spec §5.6-2): monta o candidato e o entrega ao
    bloco. Recusa vira evento `soft_sensor_model_rejected`; nada levanta para o chamador."""
    flow_id = command.flow_id
    block_id, model_id = command.args.get("block_id"), command.args.get("model_id")
    entry = runtime.blocks.get(block_id) if isinstance(block_id, str) else None
    block = entry[1] if entry is not None else None
    if (
        entry is None
        or not isinstance(block, SoftSensorBlock)
        or not isinstance(model_id, int)
        or isinstance(model_id, bool)
    ):
        logger.info("soft_sensor_model ignorado: flow %s, args %s", flow_id, command.args)
        return

    async def read() -> tuple[SoftSensorModel | None, list[int], set[int]]:
        async with session_factory() as session:
            row = await session.scalar(
                select(SoftSensorModel)
                .options(undefer(SoftSensorModel.weights))
                .where(SoftSensorModel.id == model_id)
            )
            tag_ids = list(row.input_tag_ids) if row is not None else []
            existing = set(await session.scalars(select(Tag.id).where(Tag.id.in_(tag_ids))))
        return row, tag_ids, existing

    try:
        # Com prazo: o handler segura o `_lock` do supervisor, de que `on_comm_failure`
        # precisa para parar o flow (ADR-009).
        row, tag_ids, existing = await asyncio.wait_for(read(), timeout=PERSIST_TIMEOUT_S)
    except Exception:  # banco fora ou lento: não é motivo para desfazer o pedido do usuário
        logger.exception("Sensor virtual '%s': falha ao ler o modelo %s", block_id, model_id)
        return
    if row is None:
        logger.info("Sensor virtual '%s': modelo %s não existe; ignorado", block_id, model_id)
        return

    async def reject(reason: str, **values: int | None) -> None:
        await write_binding(
            session_factory, flow_id, block_id, desired_model_id=block.intended_model_id, **values
        )
        try:
            await emit_event(
                severity="warning",
                origin=_ORIGIN,
                message=f"Sensor virtual '{block_id}': modelo {model_id} descartado ({reason})",
                kind=KIND_SOFT_SENSOR_MODEL_REJECTED,
                payload={"block_id": block_id, "model_id": model_id, "reason": reason},
            )
        except Exception:
            logger.exception("Sensor virtual '%s': falha ao emitir a rejeição", block_id)

    try:
        model = await asyncio.to_thread(load_model, row.id, row.meta, row.weights)
    except Exception as exc:  # ArtifactError e também `meta` JSONB que nem é objeto
        logger.warning("Sensor virtual '%s': modelo %s ilegível: %s", block_id, model_id, exc)
        await reject("corrupt")
        return
    config = entry[0]
    reason = model_mismatch(
        model.meta.method,
        model.n_inputs,
        model.meta.period_s,
        block_type=config["type"],
        n_inputs=config["n_inputs"],
        ts_seconds=runtime.ts_seconds,
    )
    if reason is not None:
        await reject(reason)
        return

    def same_period() -> bool:
        active = block.active_period_s
        return active is not None and abs(active - model.meta.period_s) <= PERIOD_TOLERANCE

    prewarm = None
    if not same_period():
        prewarm = await _warm(
            session_factory,
            block_id,
            model,
            tag_ids,
            existing,
            remaining=PREWARM_TIMEOUT_S,
            emit_event=emit_event,
        )
    # Antes do `set_candidate`: sem modelo em uso a varredura seguinte promove e grava
    # `(X, None)`, que tem de chegar depois desta gravação. O desejado vai junto: um candidato
    # anterior vencido durante os `await` acima devolveu o desejado ao ativo.
    await write_binding(
        session_factory, flow_id, block_id, candidate_model_id=model_id, desired_model_id=model_id
    )
    # Sem `await` daqui ao `set_candidate`: a cópia leva as amostras empurradas durante as
    # gravações, e uma promoção no meio pode ter mudado o período do modelo em uso.
    buffer = block.active_buffer_copy() if same_period() else prewarm
    try:
        block.set_candidate(model, buffer)
    except ValueError:
        in_flight = block.intended_model_id
        await reject(
            "period", candidate_model_id=None if in_flight == block.active_model_id else in_flight
        )
