"""App factory da API: rotas sob /api, logging JSON e ciclo de vida do engine."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ottima_api import API_VERSION
from ottima_api.routers.health import heartbeat_loop
from ottima_api.validacao import traduzir_erro_de_validacao
from ottima_api.ws import FlowStatusHub
from ottima_api.ws import router as ws_router
from ottima_core.config import Settings, get_settings, validate_secrets
from ottima_core.db import create_engine, create_session_factory
from ottima_core.logging import setup_logging, watch_log_level


async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handler global de `RequestValidationError` (spec F5 §4.3-1): `detail` sempre string
    única, primeiro erro da lista — mesmo contrato dos 422 de domínio (`api.ts` descarta
    `detail` que não seja string)."""
    return JSONResponse(
        status_code=422,
        content={"detail": traduzir_erro_de_validacao(exc.errors()[0])},
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cria engine, session factory, Redis, o hub do /ws e o heartbeat de health na subida;
    descarta na descida. O heartbeat grava app.state.redis_ok/db_ok (spec F6 §3.3, RNF-07);
    o handler de /health só lê esse estado, nunca faz I/O."""
    settings: Settings = app.state.settings
    engine = create_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    # decode_responses=True é contrato do barramento na F2: consumidor recebe str
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    # Uma assinatura de flow.status.* para todos os sockets do /ws (spec F3 §5.3)
    app.state.flow_status_hub = FlowStatusHub(app.state.redis)
    await app.state.flow_status_hub.start()
    heartbeat_task = asyncio.create_task(
        heartbeat_loop(app.state.redis, app.state.session_factory, app)
    )
    log_level_task = asyncio.create_task(watch_log_level(app.state.session_factory))
    yield
    log_level_task.cancel()
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    try:
        await log_level_task
    except asyncio.CancelledError:
        pass
    await app.state.flow_status_hub.stop()  # antes do aclose: o hub usa este cliente
    await app.state.redis.aclose()
    await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level, "api")
    validate_secrets(settings)  # falha o boot se a chave de assinatura JWT não for própria
    app = FastAPI(
        title="OttimaSystem API",
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings  # lido pelo lifespan; precisa existir antes da subida
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)

    from ottima_api.routers import (
        auth,
        calculated_tags,
        certificates,
        connections,
        events,
        flows,
        health,
        history,
        history_retention,
        operate,
        projects,
        system_settings,
        tags,
        users,
    )

    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(users.router, prefix="/api/users", tags=["users"])
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(connections.router, prefix="/api/connections", tags=["connections"])
    app.include_router(tags.router, prefix="/api/tags", tags=["tags"])
    app.include_router(
        calculated_tags.router, prefix="/api/calculated-tags", tags=["calculated-tags"]
    )
    app.include_router(flows.router, prefix="/api/flows", tags=["flows"])
    app.include_router(operate.router, prefix="/api/operate", tags=["operate"])
    app.include_router(events.router, prefix="/api/events", tags=["events"])
    app.include_router(history.router, prefix="/api/history", tags=["history"])
    app.include_router(history_retention.router, prefix="/api", tags=["history-retention"])
    app.include_router(system_settings.router, prefix="/api", tags=["system-settings"])
    app.include_router(certificates.router, prefix="/api/certificates", tags=["certificates"])
    app.include_router(ws_router, tags=["ws"])  # /ws sem prefixo /api (plano e spec §5.3)
    return app
