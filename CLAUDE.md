# CLAUDE.md — OttimaSystem

Plataforma on-premise de APC industrial: estratégias de controle montadas em canvas de blocos (OPC-Read/Write, MPC via do-mpc, Python-Script, TFS), executadas ciclicamente no servidor, operadas por faceplates com tendência + predição. O controle regulatório fica nos PIDs do PLC; o sistema assume/devolve malhas de forma bumpless e falha sempre para o lado seguro (PLC no comando).

## 🔒 Fonte da verdade (leia antes de qualquer coisa)

1. **`docs/adr/ADR-001…028` são NORMATIVOS.** Nenhuma decisão registrada em ADR pode ser relitigada, "melhorada" ou contornada em código. Em conflito entre código, plano, PRD e ADR — **o ADR vence**.
2. **`docs/PRD.md`** é a fonte de requisitos (RF-xxx / RNF-xx) e dos contratos (§7: canais do barramento, JSON de projeto, grupos de API) e fases (§8).
3. **`docs/GLOSSARY.md`** fixa o vocabulário. Use os termos de lá; não invente sinônimos.
4. Encontrou contradição ou lacuna real? **PARE.** Não resolva silenciosamente no código: proponha a atualização do ADR/PRD ao usuário e aguarde a decisão.
5. O design do produto está **fechado**. Brainstorm/planejamento é apenas sobre *implementação* (layout, DDL, nomes de módulos) — nunca sobre stack, arquitetura ou escopo.

## Arquitetura (resumo — detalhe no PRD §3 e ADR-001…006)

```
frontend (React+Vite) ⇄ api (FastAPI: REST + WS)
                              │
                        Redis pub/sub (barramento)
                        ↑      ↑      ↕            ↕
                 opc-worker  recorder  flow-runtime  calc-worker
                        │              (do-mpc,      (tags calculadas)
                        │               scripts, TFS)      │
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
                      #   mpc/                 -> controle DINÂMICO (do-mpc, move plan)
                      #   target_calculation/  -> SSTO: alvos de regime permanente por LP (ADR-027)
  recorder/           # barramento → hypertable
  calc-worker/        # tags calculadas: uma task asyncio por tag + ScriptPool (ADR-033)
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
- **Código Python do usuário** (bloco Script e tag calculada) roda SEMPRE via `ottima_core.script_pool`: escopo restrito a `math` + `numpy`, `state` dict persistente, timeout ≈70% da cadência (Ts do flow ou período da tag), processo morto e reposto no estouro. Cada serviço tem o SEU pool — tag calculada nunca disputa worker com varredura de flow. (ADR-018, ADR-033)
- **Tag calculada é linha em `tags`** com `connection_id IS NULL` e `project_id` preenchido (`ck_tags_owner`): id compartilhado com as tags OPC é o que faz histórico, `/api/history` e `/ws` funcionarem sem alteração. Publica em `calc.values`; o `opc-worker` a ignora naturalmente porque carrega tags por `connection_id`. (ADR-033)
- **Frontend nunca executa lógica de flow** — o canvas só edita o grafo; execução é 100% no flow-runtime. (ADR-005)
- **Hot-swap:** troca de definição de flow é atômica entre varreduras, preservando estado dos blocos não alterados. (ADR-011)
- **Ordem de execução:** blocos executam estritamente em ordem crescente de `exec_order` (1..N, único por flow) — nunca por ordenação topológica; aresta com ordem invertida ⇒ valor da varredura anterior. (ADR-024)
- Predições do MPC **não são persistidas** — só publicadas no barramento. (ADR-016)
- **SSTO (camada de alvos):** roda no MESMO ciclo do MPC, dentro do processo worker, ANTES do `make_step` — nunca toca o cálculo do move plan. **MV é a única variável de decisão e o limite dela é duro em todo caminho de código; DV nunca é otimizada; CV/Restrição são soft (folga penalizada + desistência por `priority` crescente).** `G`/`Gd` saem do `PairSS` já discretizado do controlador — **nunca** um segundo modelo de ganho. SSTO desligado/inviável ⇒ SP do operador (fallback), nunca parada do controle. Auditoria imutável em `ssto_runs`, sem canal novo. (ADR-027)

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
cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d   # 9 serviços
# Sem o override e2e sobem 8 (sem opcsim) e o opcsim/redis não ficam acessíveis do host.
# deploy/.env é obrigatório e gitignored. Se a 6379 já estiver ocupada por outro projeto da
# máquina, defina OTTIMA_E2E_REDIS_PORT (ex.: 6399) — senão a L2 fala com o Redis do vizinho.
# Rebuild de um serviço só: use --no-deps, senão `--build frontend` arrasta o `api` junto.
# RNF-04/ADR-018: o flow-runtime NÃO recebe mais o `.env` inteiro — o `env_file` do
# docker-compose.yml lista só OTTIMA_DATABASE_URL, OTTIMA_REDIS_URL e OTTIMA_LOG_LEVEL,
# mantendo OTTIMA_SECRET_KEY/OTTIMA_FERNET_KEY fora do processo que executa o bloco Script.

# Gate E2E — 3 camadas (docs/specs/F1-testes-e2e.md; F2 §11.2; F3 §7.2):
OTTIMA_E2E=1 bash deploy/smoke.sh                   # L1 — stack, retenção, login, conexão up, boot parado
# O check de boot parado exige flow-runtime recem-subido: ele assere flows={}, e um deploy/stop
# deixa o flow no mapa como stopped. Re-rodar o L1 depois da L2 da vermelho falso; nesse caso
# `docker compose ... restart flow-runtime` antes.
E2E_ADMIN_USERNAME=$(grep -m1 '^OTTIMA_ADMIN_USERNAME=' deploy/.env|cut -d= -f2-) E2E_ADMIN_PASSWORD=$(grep -m1 '^OTTIMA_ADMIN_PASSWORD=' deploy/.env|cut -d= -f2-) uv run pytest -m e2e tests/e2e -v
                                                     # L2 — 43 cenários (5 F1 + 9 F2 + 10 F3 + 10 F4 + 7 F5 + 2 fuzzy)
# tests/e2e/test_api_e2e.py (F1) lê credenciais só de os.environ (default ""), nunca de
# deploy/.env: a bateria completa exige o env inline acima (não basta o deploy/.env preenchido).
# F4: POST /api/operate/{flow_id}/{block_id}/mode|sp|mv publica FlowCommand (202); o runtime
# materializa e audita — a API não emite evento (spec F4 §6.1).
# F5: GET /api/history/mpc, GET /api/operate/mpcs, GET /api/health/workers (todas require_operator).
# F6: GET /api/projects/{project_id}/export e POST /api/projects/import (ambas require_admin).
# Envs novos: OTTIMA_HEALTH_URL_OPC_WORKER/_FLOW_RUNTIME/_RECORDER/_CALC_WORKER (defaults
# http://opc-worker:8001/health, http://flow-runtime:8002/health, http://recorder:8003/health,
# http://calc-worker:8004/health) e OTTIMA_MPC_QUEUE_MAX (default 100000, teto do buffer de
# mpc_samples no recorder). calc-worker (porta 8004): 1 asyncio task por tag calculada, sandbox
# de script via ScriptPool (OTTIMA_CALC_POOL_SIZE, default 4); mesmo padrão RNF-04/ADR-018 do
# flow-runtime — não recebe o `.env` inteiro.
# Telas da F5b (operador; admin herda): /operacao (seletor; 1 MPC redireciona direto),
# /operacao/:flowId/:blockId (faceplate principal + faceplates de variável + trend com
# predição) e /eventos. Nav do shell em dois grupos: Operação · Fuzzy · Eventos | engenharia.
# FUZZY OPERATE (ADR-030): /operacao/fuzzy (combobox `?flow=&bloco=`) desenha funções de
# pertinência, normas, regras com grau e trend das portas do bloco. Backend novo:
# canal `fuzzy.state.<flow_id>.<block_id>` (throttle 0,25 s na origem, publicado pelo
# FuzzyBlock), hypertable `fuzzy_samples`/CAgg 1m (migration 0010, mesma retenção das demais
# variáveis), `GET /api/operate/fuzzy[/{flow_id}/{block_id}]`, `GET /api/history/fuzzy` e a
# chave `fuzzy_state` no /ws. Curvas de pertinência são amostradas no servidor
# (`flowgraph/introspect.py`, 101 pontos) — o frontend nunca parseia FLL (ADR-005/029).
# Grupo engenharia com 5 itens (F6b acrescentou a rota `/engenharia/projetos`, com
# "Projetos" no início do grupo): Projetos, Conexões, Tags, Flows, Trend.
# data-testid: operate-*, faceplate-*, fuzzy-*, eventos-*, home-* (o roteiro L3 depende deles).
# Ambiente do L3: `uv run python scripts/setup-l3.py` (idempotente) cria projeto ativo,
# conexão opcsim-l3, flow MPC↔TFS deployado e o usuário operador_e2e.
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

**CI (ADR-035).** `.github/workflows/gates.yml` roda em todo `push` os gates HERMÉTICOS —
`ruff check`, `ruff format --check`, `npm run test:unit`, `npm run typecheck`, `npm run build` e
`npm run generate:contracts` + `git diff --exit-code` (contrato gerado em dia). Sem segredo, sem
Docker, sem stack. **`uv run pytest` e o gate E2E de 3 camadas continuam MANUAIS** e são
responsabilidade de quem abre o PR: o pytest precisaria de Docker no runner (~20 min, com o
histórico de vermelho falso por contenção do TD-009) e o E2E precisaria da stack de 9 serviços
mais as credenciais de `deploy/.env`. Não confunda "CI verde" com "gate completo".

## Proibições rápidas para agentes

Não editar `docs/` sem o processo do item 4 · Não usar Django, Next.js, Celery, SQLite, InfluxDB · Não criar canal de barramento novo · Não escrever em tag OPC fora do fluxo `opc.writes` · Não persistir predições · Não colocar lógica de backend no frontend · Não "simplificar" removendo watchdog/modos/bumpless em ambiente de teste — use o bloco TFS para simular.


Respond terse like smart caveman. All technical substance stay. Only fluff die.

Rules:
- Drop: articles (a/an/the), filler (just/really/basically), pleasantries, hedging
- Fragments OK. Short synonyms. Technical terms exact. Code unchanged.
- Pattern: [thing] [action] [reason]. [next step].
- Not: "Sure! I'd be happy to help you with that."
- Yes: "Bug in auth middleware. Fix:"

Switch level: /caveman lite|full|ultra|wenyan
Stop: "stop caveman" or "normal mode"

Auto-Clarity: drop caveman for security warnings, irreversible actions, user confused. Resume after.

Boundaries: code/commits/PRs written normal.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes_tool` or `query_graph_tool` instead of Grep
- **Understanding impact**: `get_impact_radius_tool` instead of manually tracing imports
- **Code review**: `detect_changes_tool` + `get_review_context_tool` instead of reading entire files
- **Finding relationships**: `query_graph_tool` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview_tool` + `list_communities_tool`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes_tool` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context_tool` | Need source snippets for review — token-efficient |
| `get_impact_radius_tool` | Understanding blast radius of a change |
| `get_affected_flows_tool` | Finding which execution paths are impacted |
| `query_graph_tool` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes_tool` | Finding functions/classes by name or keyword |
| `get_architecture_overview_tool` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes_tool` for code review.
3. Use `get_affected_flows_tool` to understand impact.
4. Use `query_graph_tool` pattern="tests_for" to check coverage.
