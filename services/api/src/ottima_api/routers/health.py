"""Health check público (sem autenticação) e agregador de workers (spec F5 §4.2, decisão A-8).

`/health` reflete Redis/Postgres por heartbeat de fundo (spec F6 §3.3, RNF-07): o `lifespan`
de `app.py` inicia `heartbeat_loop`, que grava `app.state.redis_ok`/`db_ok` a cada
HEARTBEAT_INTERVAL_S segundos — mesmo padrão dos 3 workers (`opc-worker/main.py:52-57`). O
handler não faz I/O nenhum, só lê o estado já gravado; sem lifespan (app cru dos testes de
unidade) os dois campos caem no default `False`. A rota segue pública mesmo revelando esses
dois booleanos: é o healthcheck do compose e não expõe nada que a disponibilidade da própria
rota já não revele na rede interna (spec §3.3-4, exceção a RF-003).
"""

import asyncio
import json
import urllib.error
import urllib.request
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel
from sqlalchemy import text

from ottima_api import API_VERSION
from ottima_api.deps import get_app_settings, require_operator
from ottima_core.config import Settings

router = APIRouter()

HEARTBEAT_INTERVAL_S = 5.0


async def check_redis(client, app: FastAPI) -> None:
    """Faz ping no Redis e registra o resultado em app.state.redis_ok."""
    try:
        await client.ping()
        app.state.redis_ok = True
    except Exception:
        # Captura ampla proposital: nenhuma falha do heartbeat pode derrubar a api.
        app.state.redis_ok = False


async def check_database(session_factory, app: FastAPI) -> None:
    """Faz um SELECT 1 no banco e registra o resultado em app.state.db_ok."""
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        app.state.db_ok = True
    except Exception:
        # Captura ampla proposital: nenhuma falha do heartbeat pode derrubar a api.
        app.state.db_ok = False


async def heartbeat_loop(client, session_factory, app: FastAPI) -> None:
    """Repete as checagens de dependência a cada HEARTBEAT_INTERVAL_S segundos."""
    while True:
        await check_redis(client, app)
        await check_database(session_factory, app)
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)


class HealthOut(BaseModel):
    """Forma de `/health` (spec §3.3): as 5 chaves sempre presentes, tipadas para o OpenAPI
    carregar `redis_ok`/`db_ok` — antes a rota devolvia `dict` cru e o gerador de contratos
    (`frontend/openapi.json`/`api-types.ts`, tarefa 6.1) não tinha como nomear os campos."""

    status: Literal["ok", "degraded"]
    service: str
    version: str
    redis_ok: bool
    db_ok: bool


@router.get("/health", response_model=HealthOut)
async def health(request: Request) -> HealthOut:
    """Sempre 200: a degradação vai no corpo (spec §3.3-3)."""
    redis_ok = getattr(request.app.state, "redis_ok", False)
    db_ok = getattr(request.app.state, "db_ok", False)
    return HealthOut(
        status="ok" if redis_ok and db_ok else "degraded",
        service="api",
        version=API_VERSION,
        redis_ok=redis_ok,
        db_ok=db_ok,
    )


def _fetch_worker_health(url: str) -> dict:
    """Busca o /health de um worker; falha de rede, timeout, corpo não-JSON ou JSON que não é
    objeto (lista/escalar/bool/null) nunca propaga (spec F5 §4.2, decisão A-8): o agregador
    sempre responde 200 e a degradação do worker fica em `up`."""
    try:
        with urllib.request.urlopen(url, timeout=1) as resp:  # noqa: S310 - URL vem de Settings
            corpo = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return {"up": False}
    if not isinstance(corpo, dict):
        return {"up": False}
    return {"up": True, **corpo}


@router.get("/health/workers", dependencies=[Depends(require_operator)])
async def health_workers(settings: Settings = Depends(get_app_settings)) -> dict:
    """Agrega os 4 workers em paralelo, 1 thread cada (F5R-09: urllib stdlib, sem httpx em
    produção)."""
    opc_worker, flow_runtime, recorder, calc_worker = await asyncio.gather(
        asyncio.to_thread(_fetch_worker_health, settings.health_url_opc_worker),
        asyncio.to_thread(_fetch_worker_health, settings.health_url_flow_runtime),
        asyncio.to_thread(_fetch_worker_health, settings.health_url_recorder),
        asyncio.to_thread(_fetch_worker_health, settings.health_url_calc_worker),
    )
    return {
        "opc_worker": opc_worker,
        "flow_runtime": flow_runtime,
        "recorder": recorder,
        "calc_worker": calc_worker,
    }
