"""Health check público (sem autenticação) e agregador de workers (spec F5 §4.2, decisão A-8)."""

import asyncio
import json
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends

from ottima_api import API_VERSION
from ottima_api.deps import get_app_settings, require_operator
from ottima_core.config import Settings

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api", "version": API_VERSION}


def _fetch_worker_health(url: str) -> dict:
    """Busca o /health de um worker; falha de rede, timeout ou corpo inválido nunca propaga
    (spec F5 §4.2, decisão A-8): o agregador sempre responde 200 e a degradação do worker
    fica em `up`."""
    try:
        with urllib.request.urlopen(url, timeout=1) as resp:  # noqa: S310 - URL vem de Settings
            corpo = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return {"up": False}
    return {"up": True, **corpo}


@router.get("/health/workers", dependencies=[Depends(require_operator)])
async def health_workers(settings: Settings = Depends(get_app_settings)) -> dict:
    """Agrega os 3 workers em paralelo, 1 thread cada (F5R-09: urllib stdlib, sem httpx em
    produção)."""
    opc_worker, flow_runtime, recorder = await asyncio.gather(
        asyncio.to_thread(_fetch_worker_health, settings.health_url_opc_worker),
        asyncio.to_thread(_fetch_worker_health, settings.health_url_flow_runtime),
        asyncio.to_thread(_fetch_worker_health, settings.health_url_recorder),
    )
    return {"opc_worker": opc_worker, "flow_runtime": flow_runtime, "recorder": recorder}
