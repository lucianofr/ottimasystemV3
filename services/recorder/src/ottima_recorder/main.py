"""Serviço recorder: /health + heartbeat de Redis (F1) e o pipeline de gravação (RF-801).

O pipeline é o único escritor de `samples`/`events` (spec F2 §6); o /health estendido com
as métricas do buffer chega na tarefa 3.2.
"""

import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI

from ottima_core.config import get_settings
from ottima_core.db import create_engine, create_session_factory
from ottima_core.logging import setup_logging
from ottima_recorder.pipeline import RecorderPipeline

SERVICE_NAME = "recorder"
VERSION = "0.1.0"
HEARTBEAT_INTERVAL_S = 5.0


async def check_redis(client, app: FastAPI) -> None:
    """Faz ping no Redis e registra o resultado em app.state.redis_ok."""
    try:
        await client.ping()
        app.state.redis_ok = True
    except Exception:
        # Captura ampla proposital: nenhuma falha do heartbeat pode derrubar o worker.
        app.state.redis_ok = False


async def _heartbeat_loop(client, app: FastAPI) -> None:
    """Repete o ping no Redis a cada HEARTBEAT_INTERVAL_S segundos."""
    while True:
        await check_redis(client, app)
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Sobe Redis, banco, pipeline e heartbeat; encerra na ordem inversa."""
    settings = get_settings()
    setup_logging(settings.log_level)
    # decode_responses=True é contrato do barramento na F2: consumidor recebe str
    client = redis.from_url(settings.redis_url, decode_responses=True)
    engine = create_engine(settings.database_url)
    pipeline = RecorderPipeline(client, create_session_factory(engine))
    app.state.pipeline = pipeline
    await pipeline.start()
    task = asyncio.create_task(_heartbeat_loop(client, app))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await pipeline.stop()
    await engine.dispose()
    await client.aclose()


app = FastAPI(title=f"OttimaSystem {SERVICE_NAME}", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Sempre responde 200: 'degraded' quando o Redis não respondeu ao último ping."""
    redis_ok = getattr(app.state, "redis_ok", False)
    return {
        "status": "ok" if redis_ok else "degraded",
        "service": SERVICE_NAME,
        "version": VERSION,
    }
