"""App factory da API: rotas sob /api, logging JSON e ciclo de vida do engine."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ottima_api import API_VERSION
from ottima_api.ws import FlowStatusHub
from ottima_api.ws import router as ws_router
from ottima_core.config import Settings, get_settings, validate_secrets
from ottima_core.db import create_engine, create_session_factory
from ottima_core.logging import setup_logging

# Motivo pt-BR por `type` de erro do Pydantic v2 (spec F5 §4.3-1, decisão A-9, dívida F4).
# Cobre os tipos que aparecem nos schemas do serviço (Literal, Field(min_length=...),
# Field(ge=/le=...), campo obrigatório, `model_validator` com `ValueError` pt-BR já pronto)
# e `json_invalid`, do corpo malformado antes mesmo de chegar ao schema.
_MOTIVO_POR_TIPO = {
    "missing": lambda erro: "campo obrigatório",
    "string_too_short": lambda erro: f"mínimo de {erro['ctx']['min_length']} caractere(s)",
    "string_too_long": lambda erro: f"máximo de {erro['ctx']['max_length']} caractere(s)",
    "greater_than_equal": lambda erro: f"deve ser maior ou igual a {erro['ctx']['ge']}",
    "less_than_equal": lambda erro: f"deve ser menor ou igual a {erro['ctx']['le']}",
    "greater_than": lambda erro: f"deve ser maior que {erro['ctx']['gt']}",
    "less_than": lambda erro: f"deve ser menor que {erro['ctx']['lt']}",
    "int_parsing": lambda erro: "deve ser um número inteiro",
    "int_type": lambda erro: "deve ser um número inteiro",
    "float_parsing": lambda erro: "deve ser um número",
    "float_type": lambda erro: "deve ser um número",
    "bool_parsing": lambda erro: "deve ser verdadeiro ou falso",
    "bool_type": lambda erro: "deve ser verdadeiro ou falso",
    "string_type": lambda erro: "deve ser um texto",
    "json_invalid": lambda erro: "corpo JSON inválido",
}


def _traduzir_erro_de_validacao(erro: dict[str, Any]) -> str:
    """`{loc, msg, type, ctx}` do Pydantic vira `"<campo>: <motivo pt-BR>"` (formato exato
    da spec F5 §4.3-1). `value_error` (de `model_validator`) já é pt-BR: só remove o prefixo
    "Value error, " que o Pydantic adiciona. `literal_error` (Literal/enum) traduz a lista de
    opções. Tipo desconhecido cai na mensagem original do Pydantic (defensivo; nenhum schema
    do serviço produz outro tipo hoje)."""
    campo = ".".join(str(parte) for parte in erro["loc"])
    if erro["type"] == "value_error":
        motivo = str(erro["ctx"]["error"])
    elif erro["type"] == "literal_error":
        opcoes = erro["ctx"]["expected"].replace("'", "").replace(" or ", ", ")
        motivo = f"valor inválido; esperado um de: {opcoes}"
    else:
        motivo = _MOTIVO_POR_TIPO.get(erro["type"], lambda e: e["msg"])(erro)
    return f"{campo}: {motivo}"


async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handler global de `RequestValidationError` (spec F5 §4.3-1): `detail` sempre string
    única, primeiro erro da lista — mesmo contrato dos 422 de domínio (`api.ts` descarta
    `detail` que não seja string)."""
    return JSONResponse(
        status_code=422,
        content={"detail": _traduzir_erro_de_validacao(exc.errors()[0])},
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cria engine, session factory, Redis e o hub do /ws na subida; descarta na descida."""
    settings: Settings = app.state.settings
    engine = create_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    # decode_responses=True é contrato do barramento na F2: consumidor recebe str
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    # Uma assinatura de flow.status.* para todos os sockets do /ws (spec F3 §5.3)
    app.state.flow_status_hub = FlowStatusHub(app.state.redis)
    await app.state.flow_status_hub.start()
    yield
    await app.state.flow_status_hub.stop()  # antes do aclose: o hub usa este cliente
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
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)

    from ottima_api.routers import (
        auth,
        certificates,
        connections,
        events,
        flows,
        health,
        history,
        operate,
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
    app.include_router(operate.router, prefix="/api/operate", tags=["operate"])
    app.include_router(events.router, prefix="/api/events", tags=["events"])
    app.include_router(history.router, prefix="/api/history", tags=["history"])
    app.include_router(certificates.router, prefix="/api/certificates", tags=["certificates"])
    app.include_router(ws_router, tags=["ws"])  # /ws sem prefixo /api (plano e spec §5.3)
    return app
