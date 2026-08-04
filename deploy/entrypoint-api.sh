#!/usr/bin/env bash
# Entrypoint da api: migrations -> seed do admin -> uvicorn (spec F1 §7.1).
set -euo pipefail
cd /app
alembic -c packages/ottima-core/alembic.ini upgrade head
python -m ottima_api.seed
exec uvicorn ottima_api.main:app --host 0.0.0.0 --port 8000
