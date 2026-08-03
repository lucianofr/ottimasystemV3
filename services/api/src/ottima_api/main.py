"""Alvo do uvicorn em produção: ottima_api.main:app."""

from ottima_api.app import create_app

app = create_app()
