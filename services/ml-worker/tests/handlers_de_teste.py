"""Handlers de teste do runner, registrados no FILHO via `OTTIMA_ML_EXTRA_HANDLERS`.

O `spawn` reimporta tudo no filho: monkeypatch do pai não chega lá, por isso o registro é por
import deste módulo (que precisa estar no `sys.path` do pai antes do `spawn`)."""

import asyncio
import importlib
import os

import numpy as np

from ottima_core.softsensor import PlsHyperparams
from ottima_core.softsensor.dataset import DatasetError
from ottima_ml_worker.handlers import HANDLERS, JobContext
from ottima_ml_worker.training import InputSeed, TrainData, train


async def ok(ctx: JobContext) -> dict:
    return {"echo": ctx.params, "job_id": ctx.job_id}


async def progresso(ctx: JobContext) -> dict:
    ctx.report({"done": 1, "total": 2})
    ctx.report({"done": 2, "total": 2})
    return {}


async def explode(ctx: JobContext) -> dict:
    raise RuntimeError("(psycopg) falhou de propósito")


async def explode_dataset(ctx: JobContext) -> dict:
    raise DatasetError("O conjunto teria 9 análises com 2 entradas, acima do máximo de 4")


async def ajuste_quebra(ctx: JobContext) -> dict:
    """O `train` de verdade, com um ajuste que levanta o `ValueError` cru de uma biblioteca."""

    def quebra(*_args, **_kw):
        raise ValueError("slice 0 has a NaN entry")

    # `training.train` é função e submódulo: o módulo vem por importlib. Só este filho é afetado.
    importlib.import_module("ottima_ml_worker.training.train").fit = quebra
    x = np.random.default_rng(0).normal(size=(30, 4, 1)).astype(np.float32)
    data = TrainData(x=x, y=x[:, -1, 0], ts=np.arange(30, dtype=float))
    train(
        "pls",
        data,
        PlsHyperparams(),
        inputs=[InputSeed("T1", "")],
        output_name="y",
        output_eu="",
        period_s=1.0,
        dataset_ids=[],
    )
    return {}


async def dorme(ctx: JobContext) -> dict:
    await asyncio.sleep(60)
    return {}


async def threads(ctx: JobContext) -> dict:
    return {
        name: os.environ.get(name)
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
    }


async def morre(ctx: JobContext) -> dict:
    os._exit(3)


HANDLERS.update(
    {
        "teste_ok": ok,
        "teste_progresso": progresso,
        "teste_explode": explode,
        "teste_explode_dataset": explode_dataset,
        "teste_ajuste_quebra": ajuste_quebra,
        "teste_dorme": dorme,
        "teste_morre": morre,
        "teste_threads": threads,
    }
)
