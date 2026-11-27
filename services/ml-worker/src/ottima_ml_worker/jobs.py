"""Fila `ml_jobs` (ADR-046 D1; spec §7.5): única fila do sistema, consumida só pelo ml-worker em
duas raias (emenda 2026-11-27): otimização (`tune`) e geral (todo outro kind). `tune=None` é a
fila inteira; `True`/`False`, a raia.

`dataset_build` que não termina `done` (falha, cancelamento, órfão) leva o conjunto de `building`
para `failed`: senão ele ficaria travado em construção para sempre."""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, func, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.models import MlJob, SoftSensorDataset

ORPHAN_ERROR = "interrompido pelo reinício do serviço"

Sessions = async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    kind: str
    params: dict


def _lane(tune: bool | None) -> ColumnElement[bool]:
    """Geral por exclusão: um kind novo cai nela sem tocar aqui."""
    if tune is None:
        return true()
    return MlJob.kind == "tune" if tune else MlJob.kind != "tune"


async def claim_next(session_factory: Sessions, *, tune: bool | None = None) -> ClaimedJob | None:
    async with session_factory() as session:
        job = await session.scalar(
            select(MlJob)
            .where(MlJob.status == "queued", _lane(tune))
            .order_by(MlJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        claimed = ClaimedJob(id=job.id, kind=job.kind, params=dict(job.params))
        job.status = "running"
        job.started_at = func.now()
        await session.commit()
        return claimed


async def write_progress(session_factory: Sessions, job_id: int, progress: dict) -> None:
    async with session_factory() as session:
        await session.execute(update(MlJob).where(MlJob.id == job_id).values(progress=progress))
        await session.commit()


async def _fail_datasets(session: AsyncSession, rows) -> None:
    ids = [params.get("dataset_id") for kind, params in rows if kind == "dataset_build"]
    if ids:
        await session.execute(
            update(SoftSensorDataset)
            .where(SoftSensorDataset.id.in_(ids), SoftSensorDataset.status == "building")
            .values(status="failed")
        )


async def finish(
    session_factory: Sessions,
    job_id: int,
    *,
    status: Literal["done", "failed", "cancelled"],
    result: dict | None = None,
    error: str | None = None,
) -> None:
    async with session_factory() as session:
        rows = await session.execute(
            update(MlJob)
            # `running`: um `finish(failed)` repetido não desfaz `done`/`cancelled` já gravado
            .where(MlJob.id == job_id, MlJob.status == "running")
            .values(status=status, result=result, error=error, finished_at=func.now())
            .returning(MlJob.kind, MlJob.params)
        )
        if status != "done":
            await _fail_datasets(session, rows.all())
        await session.commit()


async def fail_orphans(session_factory: Sessions, *, tune: bool | None = None) -> int:
    async with session_factory() as session:
        rows = (
            await session.execute(
                update(MlJob)
                .where(MlJob.status == "running", _lane(tune))
                .values(status="failed", error=ORPHAN_ERROR, finished_at=func.now())
                .returning(MlJob.kind, MlJob.params)
            )
        ).all()
        await _fail_datasets(session, rows)
        await session.commit()
        return len(rows)


async def cancel_requested(session_factory: Sessions, job_id: int) -> bool:
    async with session_factory() as session:
        return bool(await session.scalar(select(MlJob.cancel_requested).where(MlJob.id == job_id)))
