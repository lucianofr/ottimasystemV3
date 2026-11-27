"""Runner do ml-worker (ADR-046 D1): job em processo filho `spawn`, resultado pelo `Pipe`.

`ck_ml_jobs_kind` só aceita os tipos reais, então a linha é `train` e o `ClaimedJob` entregue ao
runner carrega o nome do handler de teste — o filho resolve o `kind`, não o banco."""

import asyncio
import time
from pathlib import Path

import pytest

from ottima_core.config import Settings
from ottima_core.models import MlJob, SoftSensorDataset
from ottima_ml_worker import runner
from ottima_ml_worker.jobs import ClaimedJob, claim_next
from ottima_ml_worker.runner import run_job


@pytest.fixture(autouse=True)
def handlers_de_teste(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    monkeypatch.setenv("OTTIMA_ML_EXTRA_HANDLERS", "handlers_de_teste")
    # `run_job` escreve estas variáveis no os.environ do pai; o monkeypatch as restaura no fim
    # de cada teste (o valor sentinela também prova a sobrescrita no teste de threads).
    for name in runner.BLAS_THREADS_ENV:
        monkeypatch.setenv(name, "99")


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


async def test_excecao_inesperada_no_handler_vira_failed_com_mensagem_generica(
    session_factory, make_job, migrated_database_url
):
    """Texto cru de driver ou de biblioteca nunca chega à página: só o log do filho o guarda."""
    job_id = await make_job(status="running")

    job = await _run(session_factory, migrated_database_url, job_id, "teste_explode")

    assert (job.status, job.error) == (
        "failed",
        "Falha inesperada no job (ver o log do ml-worker).",
    )


async def test_dataset_error_no_handler_passa_a_mensagem_em_ptbr(
    session_factory, make_job, migrated_database_url
):
    job_id = await make_job(status="running")

    job = await _run(session_factory, migrated_database_url, job_id, "teste_explode_dataset")

    assert (job.status, job.error) == (
        "failed",
        "O conjunto teria 9 análises com 2 entradas, acima do máximo de 4",
    )


async def test_value_error_de_biblioteca_no_ajuste_chega_ao_job_em_ptbr(
    session_factory, make_job, migrated_database_url
):
    """O runner repassa todo `ValueError` (inclusive os de sklearn, scipy e numpy): o texto em
    inglês da biblioteca não pode chegar à página."""
    job_id = await make_job(status="running")

    job = await _run(session_factory, migrated_database_url, job_id, "teste_ajuste_quebra")

    assert (job.status, job.error) == (
        "failed",
        "O ajuste do PLS falhou com estes dados (ver o log do ml-worker)",
    )


async def test_kind_desconhecido_vira_failed(session_factory, make_job, migrated_database_url):
    job_id = await make_job(status="running")

    job = await _run(session_factory, migrated_database_url, job_id, "nao_existe")

    assert job.status == "failed"
    assert "nao_existe" in job.error


async def test_cancelamento_mata_o_filho_e_grava_cancelled(
    session_factory, make_job, make_dataset, make_tag, migrated_database_url
):
    # Linha `dataset_build` (efeito no conjunto) executando o handler que dorme.
    dataset_id = await make_dataset([await make_tag("t0")])
    job_id = await make_job("dataset_build", status="running", params={"dataset_id": dataset_id})
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
        assert (await session.get(SoftSensorDataset, dataset_id)).status == "failed"


async def test_dataset_build_de_ponta_a_ponta_no_filho(
    session_factory, make_job, make_dataset, make_tag, migrated_database_url
):
    """Handler real no filho: prova o engine próprio criado a partir de `database_url`."""
    dataset_id = await make_dataset([await make_tag("t0")])
    job_id = await make_job("dataset_build", params={"dataset_id": dataset_id})

    job = await claim_next(session_factory)
    await run_job(session_factory, job, database_url=migrated_database_url)

    async with session_factory() as session:
        row = await session.get(MlJob, job_id)
        assert (row.status, row.error) == ("done", None)
        assert row.result["analyses"] == 0
        assert (await session.get(SoftSensorDataset, dataset_id)).status == "ready"


async def test_filho_nasce_com_as_threads_de_blas_limitadas_por_ml_threads(
    session_factory, make_job, migrated_database_url, monkeypatch
):
    monkeypatch.setattr(runner, "get_settings", lambda: Settings(ml_threads=3))
    job_id = await make_job(status="running")

    job = await _run(session_factory, migrated_database_url, job_id, "teste_threads")

    assert job.result == {
        "OMP_NUM_THREADS": "3",
        "OPENBLAS_NUM_THREADS": "3",
        "MKL_NUM_THREADS": "3",
    }


async def test_filho_que_morre_sem_resultado_vira_failed(
    session_factory, make_job, migrated_database_url
):
    job_id = await make_job(status="running")

    job = await _run(session_factory, migrated_database_url, job_id, "teste_morre")

    assert (job.status, job.error) == ("failed", "processo terminou sem resultado (código 3)")


async def test_falha_transitoria_de_progresso_e_cancelamento_nao_aborta_o_job(
    session_factory, make_job, migrated_database_url, monkeypatch
):
    """Banco piscando no meio do job: progresso e consulta de cancelamento são best-effort."""

    def falha_uma_vez(real):
        chamadas = []

        async def wrapper(*args, **kwargs):
            chamadas.append(args)
            if len(chamadas) == 1:
                raise ConnectionError("banco piscou")
            return await real(*args, **kwargs)

        return wrapper, chamadas

    progress, progress_calls = falha_uma_vez(runner.write_progress)
    cancel, cancel_calls = falha_uma_vez(runner.cancel_requested)
    monkeypatch.setattr(runner, "write_progress", progress)
    monkeypatch.setattr(runner, "cancel_requested", cancel)
    job_id = await make_job(status="running")

    job = await _run(session_factory, migrated_database_url, job_id, "teste_progresso")

    assert job.status == "done"
    assert job.progress == {"done": 2, "total": 2}
    assert progress_calls and cancel_calls, "as duas falhas precisam ter acontecido"
