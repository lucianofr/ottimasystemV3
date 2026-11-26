"""Handlers dos jobs, executados DENTRO do processo filho (ADR-046 D1). A SV-3 acrescenta
`train` e `tune`."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.models import LabSample, SoftSensorDataset, Tag
from ottima_core.softsensor import build_dataset


@dataclass
class JobContext:
    job_id: int
    params: dict
    session_factory: async_sessionmaker[AsyncSession]
    report: Callable[[dict], None]


async def dataset_build(ctx: JobContext) -> dict:
    """Congela o conjunto `building` (spec §7.3): análises em `[start_ts, end_ts]`, janela de
    processo lida sem esse corte (pode começar antes de `start_ts`)."""
    dataset_id = ctx.params["dataset_id"]
    async with ctx.session_factory() as session:
        ds = await session.get(SoftSensorDataset, dataset_id)
        if ds is None or ds.status != "building" or ds.end_ts is None:
            raise ValueError(f"Conjunto {dataset_id} não está em building")
        tags = {
            t.id: t for t in await session.scalars(select(Tag).where(Tag.id.in_(ds.input_tag_ids)))
        }
        for tag_id in ds.input_tag_ids:
            if tag_id not in tags:
                raise ValueError(f"Tag de entrada {tag_id} não existe mais no projeto")
        analyses = await session.execute(
            select(LabSample.sampled_at, LabSample.value).where(
                LabSample.lab_variable_id == ds.lab_variable_id,
                LabSample.sampled_at >= ds.start_ts,
                LabSample.sampled_at <= ds.end_ts,
            )
        )
        blob, stats = await build_dataset(
            session,
            tag_ids=ds.input_tag_ids,
            period_s=ds.period_s,
            analyses=[(at, value) for at, value in analyses],
            report=lambda done, total: ctx.report({"done": done, "total": total}),
        )
        ds.data = blob
        ds.stats = stats
        ds.inputs_meta = [
            {"tag_id": i, "name": tags[i].name, "eu": tags[i].eu} for i in ds.input_tag_ids
        ]
        ds.status = "ready"
        await session.commit()
    return stats


HANDLERS: dict[str, Callable[[JobContext], Awaitable[dict]]] = {"dataset_build": dataset_build}
