#!/usr/bin/env bash
# L1 do gate E2E da F1: stack completo healthy + login do seed + retenção ativa.
# 8 serviços, uma porta publicada (ADR-023). O simulador OPC-UA saiu da stack
# (dev-only): quando a suíte e2e precisa de um servidor OPC, ela o sobe standalone
# no host (tests/e2e/conftest.py).
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo "ERRO: deploy/.env ausente (copie de .env.example e preencha)"; exit 1; }
set -a; source .env; set +a
PORT="${OTTIMA_HTTP_PORT:-80}"
BASE="http://localhost:${PORT}"

# 8 serviços, uma porta publicada (ADR-023). O calc-worker (ADR-033) soma 1 na contagem.
COMPOSE=(docker compose)
ESPERADOS=8

# --remove-orphans: sem ele, um serviço deixado por um override anterior sobrevive ao
# `down` do modo produção, entra na contagem do `ps` e quebra o aceite de 8 serviços.
"${COMPOSE[@]}" up -d --build --remove-orphans

echo "aguardando os ${ESPERADOS} serviços ficarem healthy..."
for i in $(seq 1 90); do
  # contagem exata: 'grep -v healthy' contaria "unhealthy" como saudável
  saudaveis=$("${COMPOSE[@]}" ps --format '{{.Service}} {{.Health}}' | grep -c ' healthy$' || true)
  [ "${saudaveis}" -eq "${ESPERADOS}" ] && break
  sleep 2
  if [ "$i" -eq 90 ]; then echo "ERRO: serviços não ficaram healthy:"; "${COMPOSE[@]}" ps; exit 1; fi
done
"${COMPOSE[@]}" ps

echo "E2E-01a: /api/health via nginx (same-origin)..."
# status precisa valer "ok" (não só existir) e redis_ok/db_ok precisam estar presentes:
# um stack degradado (Redis ou Postgres fora do alcance) tem de reprovar aqui.
curl -fsS "${BASE}/api/health" | python3 -c '
import json, sys
corpo = json.load(sys.stdin)
assert corpo["status"] == "ok", corpo
assert "redis_ok" in corpo, corpo
assert "db_ok" in corpo, corpo
'

echo "E2E-01b: healths internos dos workers..."
for svc in "opc-worker:8001" "flow-runtime:8002" "recorder:8003" "calc-worker:8004"; do
  nome="${svc%%:*}"; porta="${svc##*:}"
  "${COMPOSE[@]}" exec -T "${nome}" python -c "import urllib.request; assert urllib.request.urlopen('http://localhost:${porta}/health', timeout=3).status == 200"
done

echo "E2E-02: login com o admin do seed..."
TOKEN=$(curl -fsS -X POST "${BASE}/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"${OTTIMA_ADMIN_USERNAME}\",\"password\":\"${OTTIMA_ADMIN_PASSWORD}\"}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
curl -fsS -H "Authorization: Bearer ${TOKEN}" "${BASE}/api/auth/me" | grep -q '"role"'

echo "E2E-03: GET /api/health/workers com os 4 workers up:true (F5R-09, ADR-033)..."
curl -fsS -H "Authorization: Bearer ${TOKEN}" "${BASE}/api/health/workers" | python3 -c '
import json, sys
corpo = json.load(sys.stdin)
for nome in ("opc_worker", "flow_runtime", "recorder", "calc_worker"):
    assert corpo[nome]["up"] is True, corpo
'

echo "E2E-04: retenção de 1 mês ativa (samples/events/samples_1m/mpc_samples/mpc_samples_1m — F5R-07)..."
# a CAgg aparece em timescaledb_information.jobs pelo nome interno do hypertable
# materializado (_materialized_hypertable_N), não pelo view_name -- por isso o LEFT JOIN
# resolve o nome público antes de filtrar (mesmo padrão de packages/ottima-core/tests/test_timescale.py).
"${COMPOSE[@]}" exec -T timescaledb psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc \
  "SELECT count(*) FROM timescaledb_information.jobs j
   LEFT JOIN timescaledb_information.continuous_aggregates ca
     ON ca.materialization_hypertable_name = j.hypertable_name
   WHERE j.proc_name = 'policy_retention'
     AND (j.config->>'drop_after')::interval = INTERVAL '1 month'
     AND COALESCE(ca.view_name, j.hypertable_name) IN ('samples','events','samples_1m','mpc_samples','mpc_samples_1m')" \
  | grep -qx 5

echo "SMOKE OK"
