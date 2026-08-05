# CLAUDE.md — OttimaSystem

Plataforma on-premise de APC industrial: estratégias de controle montadas em canvas de blocos (OPC-Read/Write, MPC via do-mpc, Python-Script, TFS), executadas ciclicamente no servidor, operadas por faceplates com tendência + predição. O controle regulatório fica nos PIDs do PLC; o sistema assume/devolve malhas de forma bumpless e falha sempre para o lado seguro (PLC no comando).

## 🔒 Fonte da verdade (leia antes de qualquer coisa)

1. **`docs/adr/ADR-001…023` são NORMATIVOS.** Nenhuma decisão registrada em ADR pode ser relitigada, "melhorada" ou contornada em código. Em conflito entre código, plano, PRD e ADR — **o ADR vence**.
2. **`docs/PRD.md`** é a fonte de requisitos (RF-xxx / RNF-xx) e dos contratos (§7: canais do barramento, JSON de projeto, grupos de API) e fases (§8).
3. **`docs/GLOSSARY.md`** fixa o vocabulário. Use os termos de lá; não invente sinônimos.
4. Encontrou contradição ou lacuna real? **PARE.** Não resolva silenciosamente no código: proponha a atualização do ADR/PRD ao usuário e aguarde a decisão.
5. O design do produto está **fechado**. Brainstorm/planejamento é apenas sobre *implementação* (layout, DDL, nomes de módulos) — nunca sobre stack, arquitetura ou escopo.

## Arquitetura (resumo — detalhe no PRD §3 e ADR-001…006)

```
frontend (React+Vite) ⇄ api (FastAPI: REST + WS)
                              │
                        Redis pub/sub (barramento)
                        ↑      ↑      ↕
                 opc-worker  recorder  flow-runtime (do-mpc, scripts, TFS)
                        │                    │
                 Servidores OPC-UA     Postgres + TimescaleDB
```

Stack: React + Vite + shadcn/ui + React Flow + uPlot · FastAPI + SQLAlchemy 2.0 async · Postgres/TimescaleDB único · Redis pub/sub · workers asyncio · `uv` · Docker Compose.

## Layout do monorepo

```
docs/                 # PRD.md, GLOSSARY.md, adr/  (normativos — não editar sem processo do item 4)
frontend/             # React + Vite (TS strict). NUNCA Next.js.
packages/
  ottima-core/        # compartilhado: modelos SQLAlchemy, schemas Pydantic, contratos do barramento
services/
  api/                # FastAPI (REST + WebSocket)
  opc-worker/         # asyncua, watchdog, escritas
  flow-runtime/       # motor de scan, MPC, scripts, TFS
  recorder/           # barramento → hypertable
deploy/               # docker-compose.yml, Dockerfiles, .env.example
tests/                # integração cross-service (malha fechada MPC↔TFS — RNF-09)
```

Python organizado como **uv workspace** (um `pyproject.toml` por package/service + workspace na raiz).

## Invariantes de engenharia (violar = bug de arquitetura)

- **Nunca bloquear o event loop.** `mpc.make_step()` (IPOPT) e `exec()` de scripts sempre via `run_in_executor`. (ADR-004)
- **Sem Celery, sem filas de job.** MPC/OPC são loops vivos em asyncio. (ADR-004)
- **`opc-worker` é o ÚNICO processo que fala OPC-UA.** Todo o resto usa o barramento. (ADR-006)
- **Barramento: apenas os canais do PRD §7.1.** Criar/alterar canal exige ADR. Pub/sub é fire-and-forget: comandos vão por `flow.commands` e a UI reflete **estado publicado**, nunca eco de comando. (ADR-002)
- **Segurança de processo:** nenhuma escrita OPC sem flow em deploy + watchdog vivo + modo REMOTO; falha de comunicação ⇒ cessa escrita e para o flow; boot sobe tudo **parado**. Em LOCAL o sistema não escreve MV (a MV do MPC faz *tracking* do readback do PID). (ADR-009, 010, 017)
- **Banco único** Postgres/TimescaleDB. Sem SQLite, sem segundo banco. Retenção (1 mês) e downsampling via policies/continuous aggregates do Timescale — **nunca** código manual de limpeza. (ADR-003)
- **Script block:** escopo restrito a `math` + `numpy`; timeout ≈70% do Ts; `state` dict persistente. (ADR-018)
- **Frontend nunca executa lógica de flow** — o canvas só edita o grafo; execução é 100% no flow-runtime. (ADR-005)
- **Hot-swap:** troca de definição de flow é atômica entre varreduras, preservando estado dos blocos não alterados. (ADR-011)
- **Ordem de execução:** blocos executam estritamente em ordem crescente de `exec_order` (1..N, único por flow) — nunca por ordenação topológica; aresta com ordem invertida ⇒ valor da varredura anterior. (ADR-024)
- Predições do MPC **não são persistidas** — só publicadas no barramento. (ADR-016)

## Convenções de código

- **Python ≥ 3.12**, type hints obrigatórios, Pydantic v2, SQLAlchemy 2.0 async style, `ruff` (lint + format), `pytest` + `pytest-asyncio`.
- **TypeScript strict**; componentes shadcn/ui; estado de servidor via WebSocket/REST tipados.
- **Identificadores de código em inglês; strings de UI e docs em pt-BR.** O GLOSSARY é o cânone de tradução (ex.: Restrição → `constraint_var`, faceplate → `faceplate`).
- Commits no padrão **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `test:`, `docs:` …), mensagens em pt-BR.
- Novas dependências fora da stack declarada exigem justificativa explícita ao usuário (e ADR se forem estruturais).

## Testes

- **TDD estrito (RED→GREEN→REFACTOR)** em lógica pura: motor de scan (execução por `exec_order`, hot-swap), discretização SOPDT/IOPDT, montagem do do-mpc, precedência Restrição>CV, bumpless, TFS.
- **opc-worker:** testar contra **servidor OPC-UA de teste in-process do asyncua** (sem PLC real) — subscriptions, escrita, watchdog, reconexão.
- **Malha fechada MPC↔TFS** é a suíte de aceitação do sistema (RNF-09): assume/devolve sem salto de MV, restrição vence CV, overrun mantém MV + alarme.
- Infra (compose, schema): testes de integração; não faça teatro de TDD unitário aqui.

## Workflow de desenvolvimento (Superpowers)

- **Um plano por fase (F1→F6 do PRD §8)** — nunca um plano do sistema inteiro. F4 (MPC) pode ser dividida em dois planos (config/montagem × runtime/modos).
- Cada tarefa do plano cita os **RF-xxx** que implementa; o *definition of done* da fase são os critérios de aceite do PRD §8.
- Um **git worktree por fase**; branch limpa; revisão em duas etapas antes de merge.
- Contratos do PRD §7 entram **verbatim** nos planos (payloads dos canais, JSON de projeto).

## Comandos (materializam na F1, estendidos na F2 e na F3 — manter esta seção atualizada)

```bash
uv sync --all-packages                              # ambiente do workspace
uv run pytest                                       # testes do workspace (sobe Timescale efêmero)
uv run ruff check . && uv run ruff format --check . # lint + formato
cd frontend && npm run build                        # tsc --noEmit strict + bundle
cd frontend && npm run dev                          # frontend (Vite, 127.0.0.1:5173, proxy /api e /ws -> 8080)
cd frontend && npm run test:unit                    # checks puros do frontend (sem browser, sem backend)
cd frontend && npm run generate:api                 # tipos do OpenAPI + contratos gerados; exige frontend/openapi.json (gitignored)
cd frontend && npm run generate:contracts           # só os contratos (portas por bloco + payloads do WS) de ottima_core.contracts_export
uv run pytest -m slow services/flow-runtime/tests   # carga do MPC (RNF-02); o run default exclui `slow` além de `e2e`

# Stack. A F2 acrescentou o opcsim e as portas de host do gate: use SEMPRE os dois arquivos.
cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d   # 8 serviços
# Sem o override e2e sobem 7 (sem opcsim) e o opcsim/redis não ficam acessíveis do host.
# deploy/.env é obrigatório e gitignored. Se a 6379 já estiver ocupada por outro projeto da
# máquina, defina OTTIMA_E2E_REDIS_PORT (ex.: 6399) — senão a L2 fala com o Redis do vizinho.
# Rebuild de um serviço só: use --no-deps, senão `--build frontend` arrasta o `api` junto.

# Gate E2E — 3 camadas (docs/specs/F1-testes-e2e.md; F2 §11.2; F3 §7.2):
OTTIMA_E2E=1 bash deploy/smoke.sh                   # L1 — stack, retenção, login, conexão up, boot parado
# O check de boot parado exige flow-runtime recem-subido: ele assere flows={}, e um deploy/stop
# deixa o flow no mapa como stopped. Re-rodar o L1 depois da L2 da vermelho falso; nesse caso
# `docker compose ... restart flow-runtime` antes.
uv run pytest -m e2e tests/e2e -v                   # L2 — 24 cenários (5 F1 + 9 F2 + 10 F3)
cd frontend && npm run e2e                          # regressão Playwright da F1 (specs novas não)
# A L2 e o Playwright NÃO podem rodar juntos: o E2E-16 publica project_activated duas vezes e
# derruba os cenários E2E-F3-03/04/08. Serialize.
# Playwright e a L2 da F1 exigem E2E_ADMIN_USERNAME/E2E_ADMIN_PASSWORD exportados; passe-os
# inline (`env VAR=... comando`) para não vazar OTTIMA_DATABASE_URL no shell e quebrar os
# testcontainers da regressão unitária.
# L3 das superfícies novas da F3 = roteiro browser-tool B-F3-01..08 (spec §7.2), executado pelo
# agente com a tool `browser`, screenshot por passo. Exige o bundle novo dentro do container:
cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --no-deps frontend
```

## Proibições rápidas para agentes

Não editar `docs/` sem o processo do item 4 · Não usar Django, Next.js, Celery, SQLite, InfluxDB · Não criar canal de barramento novo · Não escrever em tag OPC fora do fluxo `opc.writes` · Não persistir predições · Não colocar lógica de backend no frontend · Não "simplificar" removendo watchdog/modos/bumpless em ambiente de teste — use o bloco TFS para simular.
