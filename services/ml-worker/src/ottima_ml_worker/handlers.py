"""Handlers dos jobs, executados DENTRO do processo filho (ADR-046 D1). A SV-3 acrescenta
`tune`."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.models import (
    LabSample,
    LabVariable,
    MlJob,
    SoftSensorDataset,
    SoftSensorModel,
    Tag,
)
from ottima_core.softsensor import build_dataset, load_compatible_datasets, parse_hyperparams


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


async def train_job(ctx: JobContext) -> dict:
    """Treina um método sobre um ou mais conjuntos `ready` e grava o modelo (RF-587, spec §8.1).

    O modelo é o ÚLTIMO passo, numa sessão própria: a sessão de leitura fecha antes do treino (que
    pode levar minutos) e a janela entre o commit do modelo e o `done` do job fica mínima.
    O treino roda no laço do filho: este processo só treina, não há nada mais a servir."""
    # Import tardio: o pai importa este módulo só pelo `HANDLERS` e não pode carregar o scikit-learn
    # (~100 MB) que só o filho de `train` usa.
    from ottima_ml_worker.training import InputSeed, TrainingError, load_train_data, train

    params = ctx.params
    method, name = params["method"], params["name"]
    hp = parse_hyperparams(method, params.get("hyperparams"))
    ctx.report({"stage": "loading"})
    async with ctx.session_factory() as session:
        job = await session.get(MlJob, ctx.job_id)
        datasets = await load_compatible_datasets(session, job.project_id, params["dataset_ids"])
        first = datasets[0]  # os conjuntos compartilham variável, entradas e período
        lab_variable = await session.get(LabVariable, first.lab_variable_id)
        # Nome e EU das entradas: os congelados no conjunto mais recente (spec §7.3), não os das
        # tags vivas. Tag apagada ou renomeada depois do congelamento não muda o que se treinou.
        latest = max(datasets, key=lambda ds: ds.end_ts)
        try:
            inputs = [InputSeed(m["name"], m["eu"]) for m in latest.inputs_meta]
        except (KeyError, TypeError):
            inputs = []
        if len(inputs) != len(latest.input_tag_ids) or not all(
            isinstance(i.name, str) and isinstance(i.eu, str) for i in inputs
        ):
            raise TrainingError(
                f"Os metadados de entrada do conjunto '{latest.name}' estão incompletos "
                "ou não correspondem às suas entradas"
            )
        for ds in datasets:
            await session.refresh(ds, ["data"])
        data = load_train_data([ds.data for ds in datasets])
        project_id, created_by = job.project_id, job.created_by
        input_tag_ids, period_s = list(first.input_tag_ids), first.period_s
        dataset_ids = [ds.id for ds in datasets]
        output_name, output_eu = lab_variable.name, lab_variable.eu
    ctx.report({"stage": "training"})
    meta, weights, info = train(
        method,
        data,
        hp,
        inputs=inputs,
        output_name=output_name,
        output_eu=output_eu,
        period_s=period_s,
        dataset_ids=dataset_ids,
        epoch_cb=lambda epoch, _loss: ctx.report(
            {"stage": "training", "epoch": epoch, "epochs": hp.epochs}
        ),
    )
    ctx.report({"stage": "saving"})
    async with ctx.session_factory() as session:
        model = SoftSensorModel(
            project_id=project_id,
            name=name,
            method=method,
            period_s=period_s,
            n_inputs=len(meta.inputs),
            input_tag_ids=input_tag_ids,
            meta=meta.model_dump(mode="json"),
            weights=weights,
            created_by=created_by,
        )
        session.add(model)
        try:
            await session.commit()
        except IntegrityError as exc:
            if "uq_soft_sensor_models_project_name" not in str(exc):
                raise
            raise TrainingError(f"Já existe um modelo com o nome '{name}'") from exc
        return {"model_id": model.id, "metrics": meta.metrics, **info}


HANDLERS: dict[str, Callable[[JobContext], Awaitable[dict]]] = {
    "dataset_build": dataset_build,
    "train": train_job,
}
