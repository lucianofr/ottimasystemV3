"""Esqueleto F1 do recorder: gravação de samples chega na F2 (RF-801).

Na F1 o serviço existe apenas para expor /health e o heartbeat de Redis (RNF-07).
"""

import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI

from ottima_core.config import get_settings
from ottima_core.logging import setup_logging

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
    """Sobe logging, cliente Redis e a task de heartbeat; encerra tudo na saída."""
    settings = get_settings()
    setup_logging(settings.log_level)
    client = redis.from_url(settings.redis_url)
    task = asyncio.create_task(_heartbeat_loop(client, app))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
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
