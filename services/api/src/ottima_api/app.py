"""App factory da API: rotas sob /api, logging JSON e ciclo de vida do engine."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ottima_api import API_VERSION
from ottima_core.config import Settings, get_settings
from ottima_core.db import create_engine, create_session_factory
from ottima_core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cria engine e session factory na subida e descarta o pool na descida."""
    settings: Settings = app.state.settings
    engine = create_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    yield
    await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(
        title="OttimaSystem API",
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings  # lido pelo lifespan; precisa existir antes da subida

    from ottima_api.routers import auth, health, users

    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(users.router, prefix="/api/users", tags=["users"])
    return app
