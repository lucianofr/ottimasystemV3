"""Execução de um job em processo filho `spawn` (ADR-046 D1).

O filho manda `("progress", dict)`, `("done", dict)` ou `("error", str)` pelo `Pipe`. O pai nunca
bloqueia o event loop: a espera no `Pipe` e o `join` vão para thread. Cancelar é matar o filho."""

import asyncio
import importlib
import multiprocessing
import os
import time
from multiprocessing.connection import Connection

from ottima_core.db import create_engine, create_session_factory
from ottima_ml_worker.handlers import HANDLERS, JobContext
from ottima_ml_worker.jobs import ClaimedJob, Sessions, cancel_requested, finish, write_progress

PROGRESS_INTERVAL_S = 1.0
# Módulo extra de handlers importado no filho; só os testes o definem.
EXTRA_HANDLERS_ENV = "OTTIMA_ML_EXTRA_HANDLERS"
_EOF = ("eof", None)


async def _run_handler(kind: str, job_id: int, params: dict, database_url: str, conn) -> dict:
    handler = HANDLERS.get(kind)
    if handler is None:
        raise ValueError(f"tipo de job desconhecido: {kind}")
    engine = create_engine(database_url)
    try:
        ctx = JobContext(
            job_id=job_id,
            params=params,
            session_factory=create_session_factory(engine),
            report=lambda progress: conn.send(("progress", progress)),
        )
        return await handler(ctx)
    finally:
        await engine.dispose()


def child_main(kind: str, job_id: int, params: dict, database_url: str, conn: Connection) -> None:
    try:
        if extra := os.environ.get(EXTRA_HANDLERS_ENV):
            importlib.import_module(extra)
        result = asyncio.run(_run_handler(kind, job_id, params, database_url, conn))
    except Exception as exc:
        conn.send(("error", str(exc) or type(exc).__name__))
    else:
        conn.send(("done", result))
    finally:
        conn.close()


def _recv(conn: Connection, timeout: float) -> tuple | None:
    if not conn.poll(timeout):
        return None
    try:
        return conn.recv()
    except EOFError:
        return _EOF


async def run_job(
    session_factory: Sessions, job: ClaimedJob, *, database_url: str, poll_s: float = 0.5
) -> None:
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=child_main,
        args=(job.kind, job.id, job.params, database_url, sender),
        name=f"ml-job-{job.id}",
    )
    proc.start()
    sender.close()  # sem isto o pai segura o lado de escrita e nunca vê EOF
    pending: dict | None = None
    last_write = next_cancel_check = -float("inf")
    try:
        while True:
            message = await asyncio.to_thread(_recv, receiver, poll_s)
            if message is None and not proc.is_alive() and not receiver.poll():
                message = _EOF  # filho morto com o fd herdado por um neto: não espera o EOF
            if message is not None:
                kind, payload = message
                if kind == "progress":
                    pending = payload
                else:
                    if pending is not None:
                        await write_progress(session_factory, job.id, pending)
                    if kind == "done":
                        await finish(session_factory, job.id, status="done", result=payload)
                    elif kind == "error":
                        await finish(session_factory, job.id, status="failed", error=payload)
                    else:
                        await asyncio.to_thread(proc.join)
                        error = f"processo terminou sem resultado (código {proc.exitcode})"
                        await finish(session_factory, job.id, status="failed", error=error)
                    return
            now = time.monotonic()
            if pending is not None and now - last_write >= PROGRESS_INTERVAL_S:
                await write_progress(session_factory, job.id, pending)
                pending, last_write = None, now
            if now >= next_cancel_check:
                next_cancel_check = now + poll_s
                if await cancel_requested(session_factory, job.id):
                    proc.kill()
                    await asyncio.to_thread(proc.join)
                    await finish(session_factory, job.id, status="cancelled")
                    return
    finally:
        # Também no cancelamento da task (desligamento do serviço): nada de filho órfão ou
        # zumbi. A linha fica `running` e o `fail_orphans` da próxima partida a encerra.
        if proc.is_alive():
            proc.kill()
        await asyncio.to_thread(proc.join)
        receiver.close()
