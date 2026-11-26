"""Runner do ml-worker (ADR-046 D1): job em processo filho `spawn`, resultado pelo `Pipe`.

`ck_ml_jobs_kind` só aceita os tipos reais, então a linha é `train` e o `ClaimedJob` entregue ao
runner carrega o nome do handler de teste — o filho resolve o `kind`, não o banco."""

import asyncio
import time
from pathlib import Path

import pytest

from ottima_core.models import MlJob
from ottima_ml_worker.jobs import ClaimedJob
from ottima_ml_worker.runner import run_job


@pytest.fixture(autouse=True)
def handlers_de_teste(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    monkeypatch.setenv("OTTIMA_ML_EXTRA_HANDLERS", "handlers_de_teste")


async def _run(factory, url: str, job_id: int, kind: str, params: dict | None = None) -> MlJob:
    await run_job(factory, ClaimedJob(id=job_id, kind=kind, params=params or {}), database_url=url)
    async with factory() as session:
        return await session.get(MlJob, job_id)


async def test_job_que_termina_grava_done_e_result(
    session_factory, make_job, migrated_database_url
):
    job_id = await make_job(status="running")

    job = await _run(session_factory, migrated_database_url, job_id, "teste_ok", {"x": 1})

    assert job.status == "done"
    assert job.result == {"echo": {"x": 1}, "job_id": job_id}
    assert job.finished_at is not None


async def test_progresso_chega_ao_banco(session_factory, make_job, migrated_database_url):
    job_id = await make_job(status="running")

    job = await _run(session_factory, migrated_database_url, job_id, "teste_progresso")

    assert job.status == "done"
    assert job.progress == {"done": 2, "total": 2}, "o último progresso não pode se perder"


async def test_excecao_no_handler_vira_failed_com_a_mensagem(
    session_factory, make_job, migrated_database_url
):
    job_id = await make_job(status="running")

    job = await _run(session_factory, migrated_database_url, job_id, "teste_explode")

    assert (job.status, job.error) == ("failed", "falhou de propósito")


async def test_kind_desconhecido_vira_failed(session_factory, make_job, migrated_database_url):
    job_id = await make_job(status="running")

    job = await _run(session_factory, migrated_database_url, job_id, "nao_existe")

    assert job.status == "failed"
    assert "nao_existe" in job.error


async def test_cancelamento_mata_o_filho_e_grava_cancelled(
    session_factory, make_job, migrated_database_url
):
    job_id = await make_job(status="running")
    task = asyncio.create_task(
        run_job(
            session_factory,
            ClaimedJob(id=job_id, kind="teste_dorme", params={}),
            database_url=migrated_database_url,
        )
    )
    await asyncio.sleep(1.0)
    async with session_factory() as session:
        (await session.get(MlJob, job_id)).cancel_requested = True
        await session.commit()
    pedido = time.monotonic()

    await asyncio.wait_for(task, timeout=3.0)

    assert time.monotonic() - pedido < 3.0
    async with session_factory() as session:
        assert (await session.get(MlJob, job_id)).status == "cancelled"


async def test_filho_que_morre_sem_resultado_vira_failed(
    session_factory, make_job, migrated_database_url
):
    job_id = await make_job(status="running")

    job = await _run(session_factory, migrated_database_url, job_id, "teste_morre")

    assert (job.status, job.error) == ("failed", "processo terminou sem resultado (código 3)")
