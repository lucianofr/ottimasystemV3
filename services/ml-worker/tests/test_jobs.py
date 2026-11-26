"""Fila `ml_jobs` (ADR-046 D1): claim com SKIP LOCKED, órfãos na partida e efeito no conjunto."""

import asyncio

import pytest
from fastapi import FastAPI

from ottima_core.models import MlJob, SoftSensorDataset
from ottima_ml_worker import main
from ottima_ml_worker.jobs import (
    ClaimedJob,
    cancel_requested,
    claim_next,
    fail_orphans,
    finish,
    write_progress,
)


async def _job(factory, job_id: int) -> MlJob:
    async with factory() as session:
        return await session.get(MlJob, job_id)


async def _dataset_status(factory, dataset_id: int) -> str:
    async with factory() as session:
        return (await session.get(SoftSensorDataset, dataset_id)).status


async def test_claim_pega_o_mais_antigo_e_marca_running(session_factory, make_job):
    primeiro = await make_job(params={"a": 1})
    await make_job()

    claimed = await claim_next(session_factory)

    assert claimed == ClaimedJob(id=primeiro, kind="train", params={"a": 1})
    job = await _job(session_factory, primeiro)
    assert job.status == "running"
    assert job.started_at is not None


async def test_claim_sem_fila_devolve_none(session_factory, make_job):
    await make_job(status="done")

    assert await claim_next(session_factory) is None


async def test_dois_claims_concorrentes_nao_pegam_o_mesmo_job(session_factory, make_job):
    ids = {await make_job(), await make_job()}

    a, b = await asyncio.gather(claim_next(session_factory), claim_next(session_factory))

    assert {a.id, b.id} == ids


async def test_job_orfao_vira_failed_na_partida(session_factory, make_job, make_dataset, make_tag):
    dataset_id = await make_dataset([await make_tag("t0")])
    orfao = await make_job("dataset_build", status="running", params={"dataset_id": dataset_id})
    na_fila = await make_job()

    assert await fail_orphans(session_factory) == 1

    job = await _job(session_factory, orfao)
    assert (job.status, job.error) == ("failed", "interrompido pelo reinício do serviço")
    assert job.finished_at is not None
    assert await _dataset_status(session_factory, dataset_id) == "failed"
    assert (await _job(session_factory, na_fila)).status == "queued"


async def test_finish_de_dataset_build_que_falha_marca_o_conjunto(
    session_factory, make_job, make_dataset, make_tag
):
    dataset_id = await make_dataset([await make_tag("t0")])
    job_id = await make_job("dataset_build", status="running", params={"dataset_id": dataset_id})

    await finish(session_factory, job_id, status="failed", error="deu ruim")

    job = await _job(session_factory, job_id)
    assert (job.status, job.error, job.result) == ("failed", "deu ruim", None)
    assert job.finished_at is not None
    assert await _dataset_status(session_factory, dataset_id) == "failed"


async def test_finish_done_nao_mexe_no_conjunto(session_factory, make_job, make_dataset, make_tag):
    dataset_id = await make_dataset([await make_tag("t0")])
    job_id = await make_job("dataset_build", status="running", params={"dataset_id": dataset_id})

    await finish(session_factory, job_id, status="done", result={"paired": 3})

    assert (await _job(session_factory, job_id)).result == {"paired": 3}
    assert await _dataset_status(session_factory, dataset_id) == "building"


async def test_progresso_e_cancelamento(session_factory, make_job):
    job_id = await make_job(status="running")
    assert await cancel_requested(session_factory, job_id) is False

    await write_progress(session_factory, job_id, {"done": 1, "total": 4})
    async with session_factory() as session:
        job = await session.get(MlJob, job_id)
        job.cancel_requested = True
        await session.commit()

    assert (await _job(session_factory, job_id)).progress == {"done": 1, "total": 4}
    assert await cancel_requested(session_factory, job_id) is True


async def test_run_job_que_explode_e_encerrado_como_failed(session_factory, make_job, monkeypatch):
    """Falha do próprio runner (banco fora no `finish`, por exemplo): o laço encerra a linha."""

    async def explode(*args, **kwargs):
        raise RuntimeError("runner caiu")

    monkeypatch.setattr(main, "run_job", explode)
    job_id = await make_job(status="running")

    await main.run_claimed(
        session_factory, ClaimedJob(id=job_id, kind="train", params={}), database_url="x"
    )

    job = await _job(session_factory, job_id)
    assert job.status == "failed"
    assert "runner caiu" in job.error


@pytest.mark.parametrize("encerrado", ["done", "cancelled"])
async def test_finish_nao_sobrescreve_job_ja_encerrado(
    session_factory, make_job, make_dataset, make_tag, encerrado
):
    """`finish(failed)` repetido depois de um commit cujo ack se perdeu não desfaz o resultado."""
    dataset_id = await make_dataset([await make_tag("t0")])
    job_id = await make_job("dataset_build", status=encerrado, params={"dataset_id": dataset_id})

    await finish(session_factory, job_id, status="failed", error="tarde demais")

    job = await _job(session_factory, job_id)
    assert (job.status, job.error) == (encerrado, None)
    assert await _dataset_status(session_factory, dataset_id) == "building"


async def test_laco_encerra_o_job_mesmo_quando_o_finish_de_fallback_tambem_falha(
    session_factory, make_job, make_dataset, make_tag, monkeypatch
):
    """Postgres reinicia no meio do job: `run_job` e o `finish` de fallback explodem. Sem a
    varredura de órfãos re-armada, a linha ficaria `running` e o conjunto `building` para sempre."""
    dataset_id = await make_dataset([await make_tag("t0")])
    job_id = await make_job("dataset_build", params={"dataset_id": dataset_id})

    async def banco_fora(*args, **kwargs):
        raise ConnectionError("banco fora")

    monkeypatch.setattr(main, "run_job", banco_fora)
    monkeypatch.setattr(main, "finish", banco_fora)
    monkeypatch.setattr(main, "JOB_POLL_INTERVAL_S", 0.05)
    task = asyncio.create_task(main._job_loop(session_factory, FastAPI(), "x"))
    try:
        for _ in range(100):  # até 5 s: o laço fecha a linha no segundo ciclo
            if (await _job(session_factory, job_id)).status == "failed":
                break
            await asyncio.sleep(0.05)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    job = await _job(session_factory, job_id)
    assert (job.status, job.finished_at is not None) == ("failed", True)
    assert await _dataset_status(session_factory, dataset_id) == "failed"


async def test_claim_que_comita_mas_perde_a_conexao_na_volta_re_arma_a_varredura_de_orfaos(
    session_factory, make_job, monkeypatch
):
    """O `claim_next` grava `running` e a conexão cai antes de devolver o job: ninguém o executa e
    ele ficaria `running` para sempre. O laço tem de re-armar o `fail_orphans`."""
    job_id = await make_job()
    chamadas = 0

    async def claim_que_perde_a_volta(factory):
        nonlocal chamadas
        chamadas += 1
        if chamadas == 1:
            await claim_next(factory)  # comita o `running`
            raise ConnectionError("conexão perdida na volta")
        return None

    monkeypatch.setattr(main, "claim_next", claim_que_perde_a_volta)
    monkeypatch.setattr(main, "JOB_POLL_INTERVAL_S", 0.05)
    task = asyncio.create_task(main._job_loop(session_factory, FastAPI(), "x"))
    try:
        for _ in range(100):
            if (await _job(session_factory, job_id)).status == "failed":
                break
            await asyncio.sleep(0.05)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    job = await _job(session_factory, job_id)
    assert (job.status, job.error) == ("failed", "interrompido pelo reinício do serviço")
