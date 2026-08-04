"""App factory da API: rotas sob /api, logging JSON e ciclo de vida do engine."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI

from ottima_api import API_VERSION
from ottima_core.config import Settings, get_settings, validate_secrets
from ottima_core.db import create_engine, create_session_factory
from ottima_core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cria engine, session factory e cliente Redis na subida; descarta tudo na descida."""
    settings: Settings = app.state.settings
    engine = create_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    # decode_responses=True é contrato do barramento na F2: consumidor recebe str
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    yield
    await app.state.redis.aclose()
    await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)
    validate_secrets(settings)  # falha o boot se a chave de assinatura JWT não for própria
    app = FastAPI(
        title="OttimaSystem API",
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings  # lido pelo lifespan; precisa existir antes da subida

    from ottima_api.routers import (
        auth,
        certificates,
        connections,
        events,
        flows,
        health,
        history,
        projects,
        tags,
        users,
    )

    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(users.router, prefix="/api/users", tags=["users"])
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(connections.router, prefix="/api/connections", tags=["connections"])
    app.include_router(tags.router, prefix="/api/tags", tags=["tags"])
    app.include_router(flows.router, prefix="/api/flows", tags=["flows"])
    app.include_router(events.router, prefix="/api/events", tags=["events"])
    app.include_router(history.router, prefix="/api/history", tags=["history"])
    app.include_router(certificates.router, prefix="/api/certificates", tags=["certificates"])
    return app
