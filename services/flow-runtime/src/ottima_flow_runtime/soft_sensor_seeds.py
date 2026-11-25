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
from collections.abc import Awaitable, Callable, Container
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import undefer

from ottima_core.bus import KIND_SOFT_SENSOR_PREWARM_SKIPPED, publish_event
from ottima_core.flowgraph import SOFT_SENSOR_METHOD, FlowGraph
from ottima_core.models import SoftSensorBinding, SoftSensorModel, Tag
from ottima_core.softsensor import (
    BUFFER_STEPS,
    ArtifactError,
    LoadedModel,
    SampleBuffer,
    load_grid,
    load_model,
)

from .blocks.soft_sensor import BindingUpdate

logger = logging.getLogger(__name__)

PREWARM_TIMEOUT_S: Final[float] = 5.0
"""Prazo de TODO o pré-aquecimento de um deploy (spec §5.7), não de cada bloco: `load_seeds`
roda sob o `Supervisor._lock`, e N blocos lentos não podem somar N x 5 s."""

PERSIST_TIMEOUT_S: Final[float] = 2.0
"""Teto da gravação do vínculo, mesmo valor de `PERSIST_SP_TIMEOUT_S` do MPC. O bloco espera
`persist` sem limite (protegido do cancelamento); um banco parado não pode prender a
varredura, e a gravação de um bloco parado não pode atropelar por muito tempo a do redeploy."""

_ORIGIN = "flow-runtime"
_PERIOD_TOLERANCE = 1e-9

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
    ratio = model_period_s / ts_seconds
    if round(ratio) < 1 or abs(ratio - round(ratio)) > _PERIOD_TOLERANCE:
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

    return persist


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
            except ArtifactError as exc:
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
            await session.execute(
                update(SoftSensorBinding)
                .where(SoftSensorBinding.flow_id == flow_id, SoftSensorBinding.block_id == node.id)
                .values(active_model_id=row.id, candidate_model_id=None)
            )
            loaded.append((node.id, model, list(row.input_tag_ids)))
        input_ids = {t for _, _, tag_ids in loaded for t in tag_ids}
        existing = set(await session.scalars(select(Tag.id).where(Tag.id.in_(input_ids))))
        await session.commit()

    loop = asyncio.get_running_loop()
    deadline = loop.time() + PREWARM_TIMEOUT_S
    for block_id, model, tag_ids in loaded:
        if len(tag_ids) != model.n_inputs or not existing.issuperset(tag_ids):
            buffer, skipped = None, "tags"
        else:
            buffer, skipped = await _prewarm(
                session_factory, model, tag_ids, remaining=deadline - loop.time()
            )
        if skipped is not None:
            await emit_event(
                severity="info",
                origin=_ORIGIN,
                message=f"Sensor virtual '{block_id}': sem pré-aquecimento ({skipped})",
                kind=KIND_SOFT_SENSOR_PREWARM_SKIPPED,
                payload={"block_id": block_id, "model_id": model.model_id, "reason": skipped},
            )
        seeds[block_id] = SoftSensorSeed(model, buffer, None)
    return seeds


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
                end=datetime.now(UTC),
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
