"""Serviço ml-worker (ADR-046 D2): laço da fila `ml_jobs` e `/health` na porta 8005. Sem Redis.

Duas raias (emenda 2026-11-27): otimização (`tune`) e geral (os demais kinds), cada uma com um
job por vez num processo filho próprio — uma otimização de horas não retém conjunto nem treino.
Sobe sem executar nada além de encerrar os órfãos da execução anterior; banco fora na subida não
impede o `/health` degradado."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import func, select

from ottima_core.config import get_settings
from ottima_core.db import create_engine, create_session_factory
from ottima_core.logging import setup_logging, watch_log_level
from ottima_core.models import MlJob
from ottima_ml_worker.jobs import ClaimedJob, Sessions, claim_next, fail_orphans, finish
from ottima_ml_worker.runner import run_job

logger = logging.getLogger(__name__)

SERVICE_NAME = "ml-worker"
VERSION = "0.1.0"
HEARTBEAT_INTERVAL_S = 5.0
JOB_POLL_INTERVAL_S = 2.0


async def check_database(session_factory: Sessions, app: FastAPI) -> None:
    """Conta a fila: a mesma consulta serve de ping do banco e de `job.queued` do `/health`."""
    try:
        async with session_factory() as session:
            app.state.queued = await session.scalar(
                select(func.count()).select_from(MlJob).where(MlJob.status == "queued")
            )
        app.state.db_ok = True
    except Exception:
        # Captura ampla proposital: nenhuma falha do heartbeat pode derrubar o worker.
        app.state.db_ok = False


async def _heartbeat_loop(session_factory: Sessions, app: FastAPI) -> None:
    while True:
        await check_database(session_factory, app)
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)


async def run_claimed(session_factory: Sessions, job: ClaimedJob, *, database_url: str) -> bool:
    """`run_job` que explode (banco fora no `finish`, por exemplo) encerra a linha como `failed`.
    Devolve False se nem isso deu: a linha pode ter ficado `running` e a raia re-arma o
    `fail_orphans` dela (raia serial: `running` do seu kind com o job já devolvido é órfão)."""
    try:
        await run_job(session_factory, job, database_url=database_url)
    except Exception as exc:
        logger.exception("falha ao executar o job %d", job.id)
        try:
            await finish(
                session_factory,
                job.id,
                status="failed",
                error=f"falha no ml-worker: {str(exc) or type(exc).__name__}",
            )
        except Exception:
            logger.exception("falha ao encerrar o job %d como failed", job.id)
            return False
    return True


async def _job_loop(
    session_factory: Sessions, app: FastAPI, database_url: str, *, tune: bool
) -> None:
    """Uma raia. Toda varredura de órfãos (subida e re-arme) fica nos kinds DESTA raia: a outra
    pode estar com um job vivo, e só aqui um `running` do kind dela seria órfão. A união das duas
    varreduras da subida cobre a fila inteira."""
    state_key = "tune_running_id" if tune else "running_id"
    orphans_done = False
    while True:
        try:
            if not orphans_done:
                if n := await fail_orphans(session_factory, tune=tune):
                    logger.warning("%d job(s) interrompido(s) pelo reinício marcado(s) failed", n)
                orphans_done = True
            job = await claim_next(session_factory, tune=tune)
            if job is not None:
                setattr(app.state, state_key, job.id)
                try:
                    if not await run_claimed(session_factory, job, database_url=database_url):
                        orphans_done = False
                finally:
                    setattr(app.state, state_key, None)
                continue
        except Exception:
            # Banco fora no claim ou nos órfãos: o laço segue e tenta de novo. Um `claim_next` que
            # comitou o `running` e perdeu a conexão na volta deixa um job que ninguém executa;
            # sem job em andamento aqui, o `running` que sobra é órfão: re-arma a varredura.
            logger.exception("falha no laço de jobs do ml-worker")
            orphans_done = False
        await asyncio.sleep(JOB_POLL_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, SERVICE_NAME)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    tasks = [
        asyncio.create_task(_heartbeat_loop(session_factory, app)),
        asyncio.create_task(_job_loop(session_factory, app, settings.database_url, tune=True)),
        asyncio.create_task(_job_loop(session_factory, app, settings.database_url, tune=False)),
        asyncio.create_task(watch_log_level(session_factory)),
    ]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await engine.dispose()


app = FastAPI(title=f"OttimaSystem {SERVICE_NAME}", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Sempre 200: a degradação vai no corpo. Job em falha não degrada o serviço."""
    return {
        "status": "ok" if getattr(app.state, "db_ok", False) else "degraded",
        "service": SERVICE_NAME,
        "version": VERSION,
        "job": {
            "running_id": getattr(app.state, "running_id", None),  # raia geral
            "tune_running_id": getattr(app.state, "tune_running_id", None),
            "queued": getattr(app.state, "queued", 0),
        },
    }
