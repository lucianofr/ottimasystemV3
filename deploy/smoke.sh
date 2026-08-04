#!/usr/bin/env bash
# L1 do gate E2E da F1: stack completo healthy + login do seed + retenção ativa.
# Com OTTIMA_E2E=1 acrescenta o override de teste (simulador OPC-UA) e a camada L1 da F2:
# opcsim healthy, conexão up e watchdog vivo (spec F2 §11.2-L1).
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo "ERRO: deploy/.env ausente (copie de .env.example e preencha)"; exit 1; }
set -a; source .env; set +a
PORT="${OTTIMA_HTTP_PORT:-80}"
BASE="http://localhost:${PORT}"

# Sem OTTIMA_E2E o comportamento é o da F1: 7 serviços, uma porta publicada (ADR-023).
E2E="${OTTIMA_E2E:-0}"
COMPOSE=(docker compose)
ESPERADOS=7
if [ "${E2E}" = "1" ]; then
  COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.e2e.yml)
  ESPERADOS=8
  # O diretório do bind-mount precisa existir ANTES do up: criado pelo daemon ele viria
  # como root e o opcsim, que roda sem privilégio, não gravaria o certificado do boot.
  mkdir -p e2e-certs
fi

# --remove-orphans: sem ele, um opcsim deixado por uma rodada e2e anterior sobrevive ao
# `down` do modo produção, entra na contagem do `ps` e quebra o aceite de 7 serviços.
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
curl -fsS "${BASE}/api/health" | grep -q '"status"'

echo "E2E-01b: healths internos dos workers..."
for svc in "opc-worker:8001" "flow-runtime:8002" "recorder:8003"; do
  nome="${svc%%:*}"; porta="${svc##*:}"
  "${COMPOSE[@]}" exec -T "${nome}" python -c "import urllib.request; assert urllib.request.urlopen('http://localhost:${porta}/health', timeout=3).status == 200"
done

echo "E2E-02: login com o admin do seed..."
TOKEN=$(curl -fsS -X POST "${BASE}/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"${OTTIMA_ADMIN_USERNAME}\",\"password\":\"${OTTIMA_ADMIN_PASSWORD}\"}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
curl -fsS -H "Authorization: Bearer ${TOKEN}" "${BASE}/api/auth/me" | grep -q '"role"'

echo "E2E-03: retention policies de 1 mês (aceite: retenção ativa)..."
"${COMPOSE[@]}" exec -T timescaledb psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc \
  "SELECT count(*) FROM timescaledb_information.jobs WHERE proc_name = 'policy_retention' AND (config->>'drop_after')::interval = INTERVAL '1 month'" \
  | grep -qx 3

if [ "${E2E}" = "1" ]; then
  echo "E2E-F2-L1a: opcsim healthy..."
  "${COMPOSE[@]}" ps --format '{{.Service}} {{.Health}}' | grep -qx 'opcsim healthy'

  echo "E2E-F2-L1b: aquisição contra o opcsim (conexão up + watchdog vivo)..."
  # Sufixo único: o script é reexecutável sem colidir com o projeto da rodada anterior.
  RUN_ID="$(date +%s)"
  AUTH=(-H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json')

  PROJ_ID=$(curl -fsS -X POST "${BASE}/api/projects" "${AUTH[@]}" \
    -d "{\"name\":\"smoke-l1-${RUN_ID}\",\"description\":\"smoke L1 da F2\"}" \
    | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')
  curl -fsS -X POST "${BASE}/api/projects/${PROJ_ID}/activate" "${AUTH[@]}" >/dev/null

  CONN_ID=$(curl -fsS -X POST "${BASE}/api/connections" "${AUTH[@]}" -d "{
      \"project_id\": ${PROJ_ID},
      \"name\": \"opcsim-${RUN_ID}\",
      \"endpoint\": \"opc.tcp://opcsim:4840\",
      \"security_policy\": \"none\",
      \"security_mode\": \"none\",
      \"auth_mode\": \"anonymous\",
      \"watchdog_read_node_id\": \"ns=2;s=sim.watchdog.to_system\",
      \"watchdog_write_node_id\": \"ns=2;s=sim.watchdog.from_system\"
    }" | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')

  curl -fsS -X POST "${BASE}/api/tags" "${AUTH[@]}" -d "{
      \"connection_id\": ${CONN_ID},
      \"name\": \"sine\",
      \"node_id\": \"ns=2;s=sim.float.sine\",
      \"direction\": \"r\",
      \"data_type\": \"float\"
    }" >/dev/null

  echo "  projeto ${PROJ_ID}, conexão ${CONN_ID}: aguardando o worker reconciliar (até 40 s)..."
  for i in $(seq 1 20); do
    HEALTH=$("${COMPOSE[@]}" exec -T opc-worker python -c \
      "import urllib.request; print(urllib.request.urlopen('http://localhost:8001/health', timeout=3).read().decode())") \
      || HEALTH='{"connections": {}}'
    if printf '%s' "${HEALTH}" | CONN_ID="${CONN_ID}" python3 -c '
import json, os, sys
conn = json.load(sys.stdin)["connections"].get(os.environ["CONN_ID"])
sys.exit(0 if conn and conn["state"] == "up" and conn["watchdog_alive"] else 1)
'; then
      echo "  conexão ${CONN_ID}: state=up, watchdog_alive=true"
      break
    fi
    sleep 2
    if [ "$i" -eq 20 ]; then
      echo "ERRO: conexão ${CONN_ID} não chegou a up com watchdog vivo. /health do worker:"
      printf '%s\n' "${HEALTH}"
      "${COMPOSE[@]}" logs --tail=50 opc-worker
      exit 1
    fi
  done

  echo "E2E-F3-L1a: boot parado do flow-runtime (ADR-017, spec F3 §7.2-L1)..."
  # Não é health genérico: `flows` vazio logo depois do up é a evidência de que o motor não
  # auto-aplica `desired_state` — só o comando `deploy` sobe flow. E `status` precisa ser
  # "ok" (não "degraded"): é ele que denuncia o banco fora do alcance do runtime, a
  # dependência que este serviço passou a ter (spec F3 §2.2-10).
  "${COMPOSE[@]}" exec -T flow-runtime python -c '
import json, urllib.request
corpo = json.load(urllib.request.urlopen("http://localhost:8002/health", timeout=3))
assert corpo["status"] == "ok", corpo
assert corpo["flows"] == {}, corpo
print("  /health: status=ok, flows={} (nenhum flow subiu no boot)")
'
fi

echo "SMOKE OK"
