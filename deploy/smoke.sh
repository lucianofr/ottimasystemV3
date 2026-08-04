#!/usr/bin/env bash
# L1 do gate E2E da F1: stack completo healthy + login do seed + retenção ativa.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo "ERRO: deploy/.env ausente (copie de .env.example e preencha)"; exit 1; }
set -a; source .env; set +a
PORT="${OTTIMA_HTTP_PORT:-80}"
BASE="http://localhost:${PORT}"

docker compose up -d --build

echo "aguardando os 7 serviços ficarem healthy..."
for i in $(seq 1 90); do
  # contagem exata: 'grep -v healthy' contaria "unhealthy" como saudável
  saudaveis=$(docker compose ps --format '{{.Service}} {{.Health}}' | grep -c ' healthy$' || true)
  [ "${saudaveis}" -eq 7 ] && break
  sleep 2
  if [ "$i" -eq 90 ]; then echo "ERRO: serviços não ficaram healthy:"; docker compose ps; exit 1; fi
done
docker compose ps

echo "E2E-01a: /api/health via nginx (same-origin)..."
curl -fsS "${BASE}/api/health" | grep -q '"status"'

echo "E2E-01b: healths internos dos workers..."
for svc in "opc-worker:8001" "flow-runtime:8002" "recorder:8003"; do
  nome="${svc%%:*}"; porta="${svc##*:}"
  docker compose exec -T "${nome}" python -c "import urllib.request; assert urllib.request.urlopen('http://localhost:${porta}/health', timeout=3).status == 200"
done

echo "E2E-02: login com o admin do seed..."
TOKEN=$(curl -fsS -X POST "${BASE}/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"${OTTIMA_ADMIN_USERNAME}\",\"password\":\"${OTTIMA_ADMIN_PASSWORD}\"}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
curl -fsS -H "Authorization: Bearer ${TOKEN}" "${BASE}/api/auth/me" | grep -q '"role"'

echo "E2E-03: retention policies de 1 mês (aceite: retenção ativa)..."
docker compose exec -T timescaledb psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc \
  "SELECT count(*) FROM timescaledb_information.jobs WHERE proc_name = 'policy_retention' AND (config->>'drop_after')::interval = INTERVAL '1 month'" \
  | grep -qx 3

echo "SMOKE OK"
