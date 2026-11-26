"""Handlers de teste do runner, registrados no FILHO via `OTTIMA_ML_EXTRA_HANDLERS`.

O `spawn` reimporta tudo no filho: monkeypatch do pai não chega lá, por isso o registro é por
import deste módulo (que precisa estar no `sys.path` do pai antes do `spawn`)."""

import asyncio
import os

from ottima_core.softsensor.dataset import DatasetError
from ottima_ml_worker.handlers import HANDLERS, JobContext


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
        "teste_dorme": dorme,
        "teste_morre": morre,
        "teste_threads": threads,
    }
)
