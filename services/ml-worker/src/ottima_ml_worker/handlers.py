"""Handlers dos jobs, executados DENTRO do processo filho (ADR-046 D1)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from pydantic import BaseModel
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

if TYPE_CHECKING:
    from ottima_ml_worker.training import InputSeed, TrainData

PROGRESS_TRIALS = 500  # tentativas que o progresso do `tune` carrega (as mais recentes)


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


@dataclass(frozen=True)
class _TrainingSet:
    """O que `train` e `tune` leem do banco antes de abrir mão da sessão."""

    data: "TrainData"
    inputs: "list[InputSeed]"
    project_id: int
    created_by: str
    input_tag_ids: list[int]
    period_s: float
    dataset_ids: list[int]
    output_name: str
    output_eu: str


async def _load_training_set(ctx: JobContext) -> _TrainingSet:
    # Import tardio: o pai importa este módulo só pelo `HANDLERS` e não pode carregar o scikit-learn
    # (~100 MB) que só o filho de `train`/`tune` usa.
    from ottima_ml_worker.training import InputSeed, TrainingError, load_train_data

    ctx.report({"stage": "loading"})
    async with ctx.session_factory() as session:
        job = await session.get(MlJob, ctx.job_id)
        datasets = await load_compatible_datasets(
            session, job.project_id, ctx.params["dataset_ids"]
        )
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
        return _TrainingSet(
            data=load_train_data([ds.data for ds in datasets]),
            inputs=inputs,
            project_id=job.project_id,
            created_by=job.created_by,
            input_tag_ids=list(first.input_tag_ids),
            period_s=first.period_s,
            dataset_ids=[ds.id for ds in datasets],
            output_name=lab_variable.name,
            output_eu=lab_variable.eu,
        )


async def _train_and_save(
    ctx: JobContext, ts: _TrainingSet, method: str, name: str, hp: BaseModel
) -> dict:
    """Treina `method` com `hp` (80/20 e reajuste em 100%) e grava o modelo, ÚLTIMO passo, numa
    sessão própria: a de leitura já fechou antes do treino (que pode levar minutos) e a janela
    entre o commit do modelo e o `done` do job fica mínima. O treino roda no laço do filho: este
    processo só treina, não há nada mais a servir."""
    from ottima_ml_worker.training import TrainingError, train

    ctx.report({"stage": "training"})
    meta, weights, info = train(
        method,
        ts.data,
        hp,
        inputs=ts.inputs,
        output_name=ts.output_name,
        output_eu=ts.output_eu,
        period_s=ts.period_s,
        dataset_ids=ts.dataset_ids,
        epoch_cb=lambda epoch, _loss: ctx.report(
            {"stage": "training", "epoch": epoch, "epochs": hp.epochs}
        ),
    )
    ctx.report({"stage": "saving"})
    async with ctx.session_factory() as session:
        model = SoftSensorModel(
            project_id=ts.project_id,
            name=name,
            method=method,
            period_s=ts.period_s,
            n_inputs=len(meta.inputs),
            input_tag_ids=ts.input_tag_ids,
            meta=meta.model_dump(mode="json"),
            weights=weights,
            created_by=ts.created_by,
        )
        session.add(model)
        try:
            await session.commit()
        except IntegrityError as exc:
            if "uq_soft_sensor_models_project_name" not in str(exc):
                raise
            raise TrainingError(f"Já existe um modelo com o nome '{name}'") from exc
        return {"model_id": model.id, "metrics": meta.metrics, **info}


async def train_job(ctx: JobContext) -> dict:
    """Treina um método sobre um ou mais conjuntos `ready` e grava o modelo (RF-587, spec §8.1)."""
    params = ctx.params
    method = params["method"]
    hp = parse_hyperparams(method, params.get("hyperparams"))
    ts = await _load_training_set(ctx)
    return await _train_and_save(ctx, ts, method, params["name"], hp)


async def tune_job(ctx: JobContext) -> dict:
    """Busca hiperparâmetros com Optuna e grava o modelo treinado com os melhores (RF-588,
    spec §8.2). O progresso é o do estudo; nas fases de treino e gravação ele segue junto, para
    a tabela de tentativas não sumir da tela."""
    from ottima_ml_worker.training import TrainingError
    from ottima_ml_worker.training.tune import INVALID, MAX_TRIALS, MIN_TRIALS, tune

    params = ctx.params
    method, n_trials, min_r2 = params["method"], params.get("n_trials"), params.get("min_r2")
    base = parse_hyperparams(method, None)  # também recusa método desconhecido
    if (
        not isinstance(n_trials, int)
        or isinstance(n_trials, bool)
        or not MIN_TRIALS <= n_trials <= MAX_TRIALS
    ):
        raise TrainingError(
            f"O número de tentativas deve ser um inteiro entre {MIN_TRIALS} e {MAX_TRIALS}"
        )
    if isinstance(min_r2, bool) or not isinstance(min_r2, int | float) or not 0 <= min_r2 <= 1:
        raise TrainingError("O R² mínimo deve estar entre 0 e 1")
    ts = await _load_training_set(ctx)

    trials: list[dict] = []

    def progress() -> dict:
        scores = [t["r2"] for t in trials if t["state"] == "COMPLETE" and t["r2"] > INVALID]
        return {
            "trial": len(trials),
            "n_trials": n_trials,
            "best_r2": max(scores, default=None),
            "trials": trials[-PROGRESS_TRIALS:],
        }

    def on_trial(trial: dict) -> None:
        trials.append(trial)
        ctx.report(progress())

    ctx.report(progress())
    best = tune(
        method, ts.data, n_trials=n_trials, min_r2=float(min_r2), base=base, on_trial=on_trial
    )
    study = progress()
    with_study = replace(ctx, report=lambda stage: ctx.report({**study, **stage}))
    result = await _train_and_save(with_study, ts, method, params["name"], best)
    return {
        **result,
        "best_params": best.model_dump(),
        "best_cv_r2": study["best_r2"],
        "trials_run": study["trial"],
    }


HANDLERS: dict[str, Callable[[JobContext], Awaitable[dict]]] = {
    "dataset_build": dataset_build,
    "train": train_job,
    "tune": tune_job,
}
