"""Health check público (sem autenticação)."""

from fastapi import APIRouter

from ottima_api import API_VERSION

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api", "version": API_VERSION}
