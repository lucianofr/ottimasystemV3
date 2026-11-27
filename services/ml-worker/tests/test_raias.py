"""Duas raias no ml-worker (ADR-046, emenda 2026-11-27): otimização (`tune`) e geral (o resto).

Cada raia executa um job por vez; uma otimização de horas não retém montagem de conjunto e treino.
A varredura de órfãos de uma raia nunca alcança o job que a outra está executando."""

import asyncio
import dataclasses
from pathlib import Path

import pytest
from fastapi import FastAPI

from ottima_core.models import MlJob
from ottima_ml_worker import main, runner
from ottima_ml_worker.jobs import ORPHAN_ERROR, claim_next, finish


async def _status(factory, job_id: int) -> str:
    async with factory() as session:
        return (await session.get(MlJob, job_id)).status


async def _espera(factory, job_id: int, status: str) -> None:
    for _ in range(300):  # até 15 s: folga para a suíte sob carga
        if await _status(factory, job_id) == status:
            return
        await asyncio.sleep(0.05)
    assert await _status(factory, job_id) == status


class Raias:
    """As duas raias do `lifespan`, numa `FastAPI` própria, encerradas ao sair."""

    def __init__(self, factory, url: str = "x"):
        self.factory, self.url, self.app, self.tasks = factory, url, FastAPI(), []

    def sobe(self, *, tune: bool) -> None:
        self.tasks.append(
            asyncio.create_task(main._job_loop(self.factory, self.app, self.url, tune=tune))
        )

    async def __aenter__(self) -> "Raias":
        return self

    async def __aexit__(self, *exc_info) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


@pytest.fixture
def run_job_falso(monkeypatch):
    """`run_job` do pai sem filho: o `tune` espera o evento, os demais terminam na hora."""
    monkeypatch.setattr(main, "JOB_POLL_INTERVAL_S", 0.05)
    libera = asyncio.Event()
    estado = {"tunes": 0, "max_tunes": 0}

    async def falso(factory, job, *, database_url):
        if job.kind == "tune":
            estado["tunes"] += 1
            estado["max_tunes"] = max(estado["max_tunes"], estado["tunes"])
            try:
                await libera.wait()
            finally:
                estado["tunes"] -= 1
        await finish(factory, job.id, status="done")

    monkeypatch.setattr(main, "run_job", falso)
    return libera, estado


async def test_claim_filtra_por_raia(session_factory, make_job):
    tune_id = await make_job("tune")
    train_id = await make_job("train")
    build_id = await make_job("dataset_build")

    assert (await claim_next(session_factory, tune=False)).id == train_id
    assert (await claim_next(session_factory, tune=False)).id == build_id
    assert await claim_next(session_factory, tune=False) is None
    assert (await claim_next(session_factory, tune=True)).id == tune_id
    assert await claim_next(session_factory, tune=True) is None


async def test_treino_anda_enquanto_a_otimizacao_roda(session_factory, make_job, run_job_falso):
    libera, _ = run_job_falso
    async with Raias(session_factory) as raias:
        raias.sobe(tune=True)
        raias.sobe(tune=False)
        tune_id = await make_job("tune")
        await _espera(session_factory, tune_id, "running")
        build_id = await make_job("dataset_build")
        train_id = await make_job("train")

        await _espera(session_factory, build_id, "done")
        await _espera(session_factory, train_id, "done")
        assert await _status(session_factory, tune_id) == "running"
        assert raias.app.state.tune_running_id == tune_id

        libera.set()
        await _espera(session_factory, tune_id, "done")


async def test_dois_tunes_rodam_um_apos_o_outro(session_factory, make_job, run_job_falso):
    libera, estado = run_job_falso
    async with Raias(session_factory) as raias:
        raias.sobe(tune=True)
        raias.sobe(tune=False)
        primeiro, segundo = await make_job("tune"), await make_job("tune")
        await _espera(session_factory, primeiro, "running")
        await asyncio.sleep(0.3)  # vários ciclos de poll: a raia geral não pega o segundo tune
        assert await _status(session_factory, segundo) == "queued"

        libera.set()
        await _espera(session_factory, segundo, "done")
    assert await _status(session_factory, primeiro) == "done"
    assert estado["max_tunes"] == 1


async def test_orfaos_da_subida_somem_nas_duas_raias(session_factory, make_job, run_job_falso):
    tune_id = await make_job("tune", status="running")
    train_id = await make_job("train", status="running")
    async with Raias(session_factory) as raias:
        raias.sobe(tune=True)
        raias.sobe(tune=False)
        await _espera(session_factory, tune_id, "failed")
        await _espera(session_factory, train_id, "failed")


async def test_subida_de_uma_raia_nao_mata_o_job_da_outra(session_factory, make_job, run_job_falso):
    """A raia que sobe depois varre os órfãos: só os do SEU conjunto de kinds."""
    libera, _ = run_job_falso
    async with Raias(session_factory) as raias:
        raias.sobe(tune=True)
        tune_id = await make_job("tune")
        await _espera(session_factory, tune_id, "running")
        raias.sobe(tune=False)
        train_id = await make_job("train")
        await _espera(session_factory, train_id, "done")
        assert await _status(session_factory, tune_id) == "running"
        libera.set()
        await _espera(session_factory, tune_id, "done")


async def test_re_varredura_por_erro_nao_mata_o_job_da_outra_raia(
    session_factory, make_job, monkeypatch
):
    """Banco cai no meio do `train`: `run_job` e o `finish` de fallback explodem e a raia geral
    re-arma a varredura. O `tune` em execução na outra raia segue `running`."""
    monkeypatch.setattr(main, "JOB_POLL_INTERVAL_S", 0.05)
    libera = asyncio.Event()

    async def run_job(factory, job, *, database_url):
        if job.kind != "tune":
            raise ConnectionError("banco fora")
        await libera.wait()
        await finish(factory, job.id, status="done")

    async def banco_fora(*args, **kwargs):
        raise ConnectionError("banco fora")

    monkeypatch.setattr(main, "run_job", run_job)
    monkeypatch.setattr(main, "finish", banco_fora)
    async with Raias(session_factory) as raias:
        raias.sobe(tune=True)
        raias.sobe(tune=False)
        tune_id = await make_job("tune")
        await _espera(session_factory, tune_id, "running")
        train_id = await make_job("train")

        await _espera(session_factory, train_id, "failed")
        async with session_factory() as session:
            assert (await session.get(MlJob, train_id)).error == ORPHAN_ERROR
        await asyncio.sleep(0.3)  # mais ciclos da raia geral com a varredura já feita
        assert await _status(session_factory, tune_id) == "running"

        libera.set()
        await _espera(session_factory, tune_id, "done")


async def test_cancelar_um_job_em_cada_raia(
    session_factory, make_job, migrated_database_url, monkeypatch
):
    """Dois filhos `spawn` de verdade ao mesmo tempo, cada um cancelado pela própria raia."""
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    monkeypatch.setenv(runner.EXTRA_HANDLERS_ENV, "handlers_de_teste")
    for name in runner.BLAS_THREADS_ENV:
        monkeypatch.setenv(name, "1")
    monkeypatch.setattr(main, "JOB_POLL_INTERVAL_S", 0.05)

    async def dorme_no_filho(factory, job, *, database_url):
        # `ck_ml_jobs_kind` só aceita os kinds reais: o filho executa o handler que dorme.
        await runner.run_job(
            factory, dataclasses.replace(job, kind="teste_dorme"), database_url=database_url
        )

    monkeypatch.setattr(main, "run_job", dorme_no_filho)
    async with Raias(session_factory, migrated_database_url) as raias:
        raias.sobe(tune=True)
        raias.sobe(tune=False)
        tune_id, train_id = await make_job("tune"), await make_job("train")
        await _espera(session_factory, tune_id, "running")
        await _espera(session_factory, train_id, "running")
        estado = raias.app.state
        for _ in range(100):  # o id entra no estado logo depois do commit do claim
            if (getattr(estado, "tune_running_id", None), getattr(estado, "running_id", None)) == (
                tune_id,
                train_id,
            ):
                break
            await asyncio.sleep(0.05)
        assert (raias.app.state.tune_running_id, raias.app.state.running_id) == (
            tune_id,
            train_id,
        )

        async with session_factory() as session:
            for job_id in (tune_id, train_id):
                (await session.get(MlJob, job_id)).cancel_requested = True
            await session.commit()

        await _espera(session_factory, tune_id, "cancelled")
        await _espera(session_factory, train_id, "cancelled")
