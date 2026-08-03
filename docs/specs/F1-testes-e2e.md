# F1 — Testes E2E (gate de conclusão da fase)

**Status:** normativo para o encerramento da F1 · 2026-08-03
**Governança:** aceite PRD §8-F1 · spec `docs/specs/F1-fundacao.md` (§9 e emenda ao §8.5, aprovada em 2026-08-03) · skill e2e-testing (padrões Playwright)
**Regra do gate:** a F1 só é considerada **concluída com sucesso** quando **todos** os cenários abaixo passarem contra o stack `docker compose` completo, num ambiente zerado (`down -v` antes da rodada final).

---

## 1. Ambiente de execução

```bash
cp deploy/.env.example deploy/.env        # preencher OTTIMA_SECRET_KEY e OTTIMA_FERNET_KEY
sed -i 's/^OTTIMA_HTTP_PORT=.*/OTTIMA_HTTP_PORT=8080/' deploy/.env   # porta não-privilegiada p/ teste
docker compose -f deploy/docker-compose.yml down -v                  # rodada de gate parte do zero
set -a; source deploy/.env; set +a
export E2E_BASE_URL="http://localhost:${OTTIMA_HTTP_PORT}"
export E2E_ADMIN_USERNAME="${OTTIMA_ADMIN_USERNAME}"
export E2E_ADMIN_PASSWORD="${OTTIMA_ADMIN_PASSWORD}"
```

## 2. Camadas e comandos

| Camada | O quê | Comando | Cenários |
|---|---|---|---|
| **L1 — Stack** | 7 serviços healthy, login do seed, retenção ativa | `bash deploy/smoke.sh` | E2E-01, E2E-02, E2E-03 |
| **L1s — Scripts dirigidos** | CAgg, restart idempotente, persistência de volumes | comandos da seção 4 | E2E-04, E2E-18, E2E-19 |
| **L2 — API** | RBAC, guardas, regras de CRUD contra o compose real | `uv run pytest -m e2e tests/e2e -v` | E2E-11…E2E-15 |
| **L3 — UI (Playwright)** | Login, sessão, shell, projeto ativo | `cd frontend && npm run e2e` | E2E-05…E2E-10, E2E-16, E2E-17 |

Artefatos L3 (skill e2e-testing): relatório HTML em `frontend/playwright-report/`; screenshot/vídeo/trace retidos em falha (`test-results/`).

## 3. Tabela de cenários

| ID | Camada | Cenário | Cobre |
|---|---|---|---|
| E2E-01 | L1 | `docker compose up` sobe os 7 serviços healthy; `/api/health` via nginx; `/health` dos 3 workers | Aceite "compose up sobe tudo" · ADR-023 · RNF-06/07 |
| E2E-02 | L1 | Login do admin do seed via API + `/auth/me` | Aceite "login admin" · RF-001 · spec §5.3 |
| E2E-03 | L1 | 3 retention policies de 1 mês registradas (`samples`, `events`, `samples_1m`) | Aceite "retenção ativa" · ADR-003/020 · RF-801 |
| E2E-04 | L1s | CAgg `samples_1m` agrega avg/min/max/count/worst_quality no banco do compose | RF-801/802 · spec §3.3 |
| E2E-05 | L3 | Admin entra pela UI e vê o shell | Aceite "login admin" · RF-001 · spec §8.3 |
| E2E-06 | L3 | Credencial errada: erro pt-BR com ícone+texto, sem navegação | RF-001 · DESIGN.md (Canal Redundante) · RNF-08 |
| E2E-07 | L3 | Rota protegida sem sessão redireciona a `/login` | RF-003 · spec §8.4 |
| E2E-08 | L3 | Sessão sobrevive a reload (token + `/auth/me`) | spec §5.1/§8.5 |
| E2E-09 | L3 | "Sair" encerra a sessão e bloqueia `/` | spec §8.5 |
| E2E-10 | L3 | Operador criado via API entra pela UI | Aceite "login operador" · RF-002 · ADR-015 |
| E2E-11 | L2 | RBAC: operador lê tudo, não escreve engenharia, não vê `/users`; sem token ⇒ 401 | RF-003 · ADR-015 · PRD §2 |
| E2E-12 | L2 | Guardas de usuário: não excluir a si próprio; não rebaixar/remover o último admin ativo | RF-002 · spec §5.5 |
| E2E-13 | L2 | Ativação de projeto é única e atômica; excluir ativo ⇒ 409 | RF-101 · ADR-017 |
| E2E-14 | L2 | Conexão: senha nunca em response (`has_password`), cifrada no banco; 6ª conexão ⇒ 409 | RF-201 · ADR-021 · spec §5.4 |
| E2E-15 | L2 | Tags: CRUD + filtros por conexão/direção | RF-203 |
| E2E-16 | L3 | Projeto ativado via API aparece como "Projeto ativo" no shell | spec §8.4 · ADR-017 |
| E2E-17 | L3 | Faixa anunciadora presente e colapsada ("Sem alarmes ativos") | DESIGN.md §Layout · ADR-020 |
| E2E-18 | L1s | `docker compose restart api`: migrations/seed idempotentes, volta healthy, login segue | RF-104 (espírito: boot seguro) · spec §4/§5.3 |
| E2E-19 | L1s | `down` (sem `-v`) + `up`: dados persistem (projeto criado continua lá) | RNF-06 (volumes persistentes) |

## 4. Cenários dirigidos por script (L1s)

### E2E-04 — CAgg operacional no compose
```bash
docker compose -f deploy/docker-compose.yml exec -T timescaledb \
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 <<'SQL'
INSERT INTO samples (ts, tag_id, value, quality) VALUES
  ('2026-01-15T10:00:05Z', 999001, 1.0, 0),
  ('2026-01-15T10:00:25Z', 999001, 2.0, 0),
  ('2026-01-15T10:00:45Z', 999001, 3.0, 2);
CALL refresh_continuous_aggregate('samples_1m', NULL, NULL);
SQL
docker compose -f deploy/docker-compose.yml exec -T timescaledb \
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc \
  "SELECT avg_value, min_value, max_value, n_samples, worst_quality FROM samples_1m WHERE tag_id = 999001"
# Esperado: 2 | 1 | 3 | 3 | 2
docker compose -f deploy/docker-compose.yml exec -T timescaledb \
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "DELETE FROM samples WHERE tag_id = 999001"
```

### E2E-18 — restart idempotente da api
```bash
ANTES=$(curl -fsS -X POST "${E2E_BASE_URL}/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"${E2E_ADMIN_USERNAME}\",\"password\":\"${E2E_ADMIN_PASSWORD}\"}" | head -c1)
docker compose -f deploy/docker-compose.yml restart api
sleep 5
for i in $(seq 1 30); do
  curl -fsS "${E2E_BASE_URL}/api/health" >/dev/null 2>&1 && break; sleep 2
done
# Esperado: health volta 200; login funciona; seed NÃO duplicou o admin:
docker compose -f deploy/docker-compose.yml exec -T timescaledb \
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc \
  "SELECT count(*) FROM users WHERE username = '${E2E_ADMIN_USERNAME}'"
# Esperado: 1
```

### E2E-19 — persistência de volumes
```bash
TOKEN=$(curl -fsS -X POST "${E2E_BASE_URL}/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"${E2E_ADMIN_USERNAME}\",\"password\":\"${E2E_ADMIN_PASSWORD}\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -fsS -X POST "${E2E_BASE_URL}/api/projects" -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' -d '{"name":"persistencia-e2e19"}' >/dev/null
docker compose -f deploy/docker-compose.yml down          # SEM -v
docker compose -f deploy/docker-compose.yml up -d
bash deploy/smoke.sh
curl -fsS -H "Authorization: Bearer ${TOKEN}" "${E2E_BASE_URL}/api/projects" | grep -q 'persistencia-e2e19'
# Limpeza:
# curl -X DELETE .../api/projects/<id> com o token
```
Nota: o token emitido antes do `down` continua válido (JWT sem estado, spec §5.1) — o teste também evidencia isso.

## 5. Critério do gate e relatório

- **Passa:** 19/19 cenários verdes na mesma rodada, partindo de `down -v`.
- **Falha:** qualquer cenário vermelho ⇒ F1 não concluída; corrigir e repetir a rodada completa (L1 → L1s → L2 → L3).
- Flaky (skill e2e-testing): re-rodar o spec isolado com `--repeat-each=5`; se instável, corrigir a causa (espera por condição, nunca `waitForTimeout` arbitrário) antes de aceitar.

Registrar o resultado no PR de encerramento da fase com o template:

```markdown
# Relatório E2E — F1
**Data:** YYYY-MM-DD HH:MM · **Duração:** Xm · **Status:** PASSING / FAILING
| Camada | Total | Verde | Vermelho |
|---|---|---|---|
| L1 + L1s | 6 | | |
| L2 | 5 | | |
| L3 | 8 | | |
Artefatos: frontend/playwright-report/ · test-results/ (screenshots/vídeos/traces em falha)
Falhas: <cenário → erro → correção>
```

## 6. Rastreabilidade ao aceite PRD §8-F1

| Critério de aceite | Cenários |
|---|---|
| Login admin/operador | E2E-02, E2E-05, E2E-10 |
| Retenção ativa | E2E-03, E2E-04 |
| `docker compose up` sobe tudo | E2E-01, E2E-18, E2E-19 |
| Entrega CRUD projetos/conexões/tags (backend) | E2E-11, E2E-13, E2E-14, E2E-15 |
| Entrega auth/RBAC | E2E-06…E2E-12 |
