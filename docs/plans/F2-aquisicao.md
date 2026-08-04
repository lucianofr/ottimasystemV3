# Plano F2 — Aquisição

**Fase:** F2 (PRD §8) · **Status:** aprovado em blocos (1/3, 2/3, 3/3) em sessão de planejamento · 2026-08-03
**Executa:** `docs/specs/F2-aquisicao.md` (aprovado integralmente na mesma sessão)
**Fontes normativas:** `docs/PRD.md` · `docs/adr/ADR-001…023` (prevalecem) · `docs/GLOSSARY.md` · `PRODUCT.md`/`DESIGN.md` (frontend) · `docs/specs/F1-fundacao.md` (vinculante)

> Este plano não foi executado nesta sessão: nenhuma linha de código de aplicação foi escrita. Execução em worktree dedicado, fase única, conforme CLAUDE.md §Workflow.

---

## Regras globais (valem para todas as tarefas)

1. **Governança:** em conflito plano×spec×PRD×ADR: **ADR > PRD > spec > plano**. Um git worktree para a fase, branch `f2-aquisicao`, Conventional Commits pt-BR (CLAUDE.md).
2. **Ciclo de conclusão de etapa (exigência do usuário, 2026-08-03):** cada etapa termina com a bateria de testes da etapa **toda verde** — pytest e, onde houver superfície de UI/fim-a-fim, **testes E2E com a tool nativa `browser` do harness** (evidência = screenshot por passo). Qualquer teste vermelho ⇒ **corrigir ⇒ re-executar a bateria ⇒ repetir até verde**. Nenhuma etapa é dada como concluída com teste falhando. Na F2 a tool `browser` substitui o Playwright para as superfícies novas (spec §1.1); a suíte Playwright da F1 permanece como regressão (Etapa 7).
3. **TDD onde é lógica pura** (CLAUDE.md §Testes); opc-worker sempre testado contra **servidor asyncua in-process** (opcsim) — subscriptions, escrita, watchdog, reconexão, **sem PLC real**.
4. **Dependências novas:** somente `asyncua` (produção, worker) e `uplot` (frontend) — ambas da stack declarada (PRD §3/§10). Qualquer outra exige aprovação do usuário.
5. **DoD da fase = aceite PRD §8-F2** (checklist ao final deste plano).

## Contratos do barramento — PRD §7.1 (verbatim; tipados em `ottima_core.bus` desde a F1)

| Canal | Produtor | Consumidores | Payload (JSON) |
|---|---|---|---|
| `opc.values.<conn_id>` | opc-worker | flow-runtime, recorder, api(WS) | {tag_id, ts, value, quality} |
| `opc.writes` | flow-runtime, api | opc-worker | {conn_id, tag_id, value, source, ts} |
| `flow.status.<flow_id>` | flow-runtime | api(WS) | {state, scan_ms, overruns, ts} |
| `flow.commands` | api | flow-runtime | {flow_id, cmd, args, user, ts} |
| `mpc.state.<flow_id>.<block_id>` | flow-runtime | api(WS) | {modes, status, vars, cost, prediction{t[], cv[][], mv[][]}} |
| `events` | todos | api(WS→banner), gravação | {ts, severity, origin, message, payload} |

Canais são **fixos** (ADR-002/CLAUDE.md); a F2 usa `opc.values.<conn_id>`, `opc.writes` e `events`.

---

## Etapa 0 — Fundações (core, opcsim, certificados)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 0.1 | Deps + workspace: `asyncua` no worker; `tests/opcsim` como member do workspace; opcsim como dev-dep do worker | `services/opc-worker/pyproject.toml` · `pyproject.toml` (raiz: `members += "tests/opcsim"`) · `tests/opcsim/pyproject.toml` (novo) | `uv sync --all-packages` verde; `uv run python -c "import asyncua"` | RF-204 · PRD §10 · spec §10.2/10.3 |
| 0.2 | **opcsim**: servidor asyncua com namespace fixo (floats senoide, int contador, bool onda, tags W + espelhos R, **rung do watchdog** NOT-cruzado, nodes `sim/control/*` p/ congelar rung/parar updates), modos None/Basic256Sha256 (cert próprio no boot), CLI `__main__` (`--port`, `--security`), Dockerfile | `tests/opcsim/src/opcsim/{__init__,server,__main__}.py` · `tests/opcsim/Dockerfile` · `tests/opcsim/tests/test_server.py` | pytest: sobe in-process, vars variam, rung alterna quando cliente escreve, freeze congela | ADR-009 · spec §10.3 · CLAUDE.md §Testes |
| 0.3 | **`publish_event()`** canônico + constantes `KIND_*` no core; fixture `redis_container` no conftest raiz (testcontainers, imagem pinada `redis:7.4-alpine` — paridade produção/teste, padrão F1 §9) | `packages/ottima-core/src/ottima_core/bus.py` · `packages/ottima-core/tests/test_bus_events.py` · `conftest.py` (raiz) | pytest core: `EventMessage` §7.1 verbatim serializado; fixture sobe/derruba | ADR-020 · spec §7.1/7.3 |
| 0.4 | **Módulo de certificados** no core: `generate_app_certificate(force)` (RSA 2048 · SHA-256 · 10 anos · `CN=OttimaSystem opc-worker` · SAN URI `urn:ottima:opc-worker` · keyUsage/extKeyUsage §5.3), metadados/fingerprint, layout `/certs/app/ottima.{pem,key,der}` + `trusted/conn-<id>.der`; `Settings.certs_dir = "/certs"` | `packages/ottima-core/src/ottima_core/certs.py` · `config.py` · `packages/ottima-core/tests/test_certs.py` | pytest: extensões (SAN URI, keyUsage), `force`, DER export | RF-202 · ADR-021 · spec §5.3/5.4 |

**Conclusão:** `uv run pytest packages tests/opcsim` verde (ciclo corrigir→re-testar até verde).

---

## Etapa 1 — opc-worker: núcleo de leitura

| # | Tarefa | Arquivos | Verificar (pytest vs opcsim in-process) | RF/ADR |
|---|---|---|---|---|
| 1.1 | `ConnectionRuntime`: máquina `connecting→up→failed`, backoff 1→2→4→…→30 s + full jitter, Fernet só em memória, eventos `comm_failure(connect_failed\|session_lost)`/`comm_restored` edge-triggered (1ª subida não emite; retries em backoff não re-emitem) | `services/opc-worker/src/ottima_opc_worker/{state,connection}.py` · `services/opc-worker/tests/test_connection.py` | conecta ⇒ `up`; porta errada ⇒ `failed` + 1 evento; derrubar servidor ⇒ `session_lost`; religar ⇒ `restored` | RF-201/204/207 · spec §2.2-2/3, §3.6 |
| 1.2 | Subscriptions: 1/conexão, `publishing_interval = sampling = 250 ms`, `queue_size=1`, monitored items só `direction='r'`, StatusCode→quality 0/1/2, publica `OpcValue` verbatim em `opc.values.<conn_id>`, `tag_subscribe_error` p/ node ruim sem derrubar a conexão | `subscriptions.py` · `tests/test_subscriptions.py` | mudança no opcsim ⇒ mensagem no canal com payload exato; node inválido ⇒ bad + warning; datachange inicial entrega valores atuais | RF-204 · spec §2.2-4/5 |
| 1.3 | Heartbeat de valor: republica tags sem publicação há ≥10 s (intervalo injetável nos testes); na falha ⇒ rajada quality=bad + heartbeat bad contínuo (valor = último conhecido; sem último ⇒ 0.0) | `heartbeat.py` · `tests/test_heartbeat.py` | tag estática republica; falha ⇒ todas quality=2 | spec §2.2-6 (Q3/Q4) |
| 1.4 | Supervisor: watermark 10 s (`max(updated_at)`+`count` de projects/opc_connections/tags do **projeto ativo**), diff ⇒ spawn/teardown; conexão ⇒ recria sessão, tags ⇒ recria só subscription; hint por assinatura de `events` (kinds §7.2/7.3); sem projeto ativo ⇒ zero sessões | `supervisor.py` · `tests/test_supervisor.py` (fixtures Timescale F1) | cria conexão ⇒ runtime nasce; muda tag ⇒ só subscription recria; desativa projeto ⇒ teardown; hint dispara reconcile imediato | RF-201/204 · ADR-017 · spec §2.2-1 |
| 1.5 | `main.py` (lifespan: supervisor + Redis + DB) + `/health` por conexão — `status` reflete **só** dependências do serviço (Redis/banco) | `main.py` · `tests/test_health.py` | shape do `/health`; conexão OPC caída **não** degrada `status` | RNF-07 · spec §2.2-8 |

**Conclusão:** `uv run pytest services/opc-worker` verde (loop até verde).

---

## Etapa 2 — opc-worker: watchdog, gate, escritas, segurança

| # | Tarefa | Arquivos | Verificar (pytest vs opcsim in-process) | RF/ADR |
|---|---|---|---|---|
| 2.1 | Task de watchdog: `read` explícito → escreve `NOT`, cadência `watchdog_period_ms` (500–5000, default 1500), congelamento >10 s (**threshold injetável nos testes; default de produção fixo 10.0** — não é knob de usuário), `watchdog_alive` armado na 1ª alternância pós-(re)conexão, escritas do watchdog **bypassam o gate** | `watchdog.py` · `tests/test_watchdog.py` | rung do opcsim alterna ⇒ `alive=true`; `sim/control/freeze_watchdog` ⇒ `watchdog_timeout` no limiar; exceção de read ⇒ falha dura imediata | RF-206 · ADR-009 · spec §3.1–3.3 |
| 2.2 | Integração de falha: `comm_failure(watchdog_timeout)` + rajada bad (1.3) na mesma transição; `comm_restored` só com sessão `up` **e** nova alternância (sem watchdog: sessão basta); **Δt detecção→evento medido** (proporcional ao threshold de teste) | `connection.py` · `watchdog.py` · `tests/test_failure.py` | freeze ⇒ 1 evento alarm + todas as tags quality=2; unfreeze ⇒ `restored`; sem re-emissão durante backoff | RF-207 · spec §3.6/3.8 |
| 2.3 | Consumidor `opc.writes`: pipeline §4.2 (a. conexão ativa; b. tag existe/`direction='w'`; c. gate sessão∧watchdog; d. executa), coerção pelo `DataType` real do servidor (cache 1×; fallback float→Double, int→Int32, bool→Boolean; bool = `value != 0.0`), auditoria `opc_write` ok/erro (origin = `source`), `write_blocked`/`write_rejected` com dedupe, `write_errors` no `/health`; conexão sem watchdog ⇒ drop + warning (dedupe, re-armado em reconfiguração) | `writes.py` · `tests/test_writes.py` | write ok ⇒ espelho R muda + evento info; em falha ⇒ `write_blocked` e valor **não** muda; tag R ⇒ `write_rejected`; gate reabre pós 1ª alternância (stateless) | RF-205/207 · spec §3.4/3.5/§4 |
| 2.4 | Segurança do worker: montagem dos 3 modos (§5.1) + identidade de usuário (anonymous/user_password/certificate **reusando o app cert**); pinning: `cert_missing` (policy≠none sem `server_cert_file`) e `cert_mismatch` (handshake divergente do pinado) | `security.py` · `tests/test_security.py` (certs de fixture via core 0.4; opcsim b256) | None/Sign/SignAndEncrypt conectam; sem server cert ⇒ `failed(cert_missing)`; cert errado ⇒ `cert_mismatch` | RF-201 · ADR-021 · spec §5.1/5.2/5.6 |

**Conclusão:** `uv run pytest services/opc-worker` verde (loop até verde).

---

## Etapa 3 — recorder

| # | Tarefa | Arquivos | Verificar (Timescale + redis testcontainers) | RF/ADR |
|---|---|---|---|---|
| 3.1 | Pipeline: `psubscribe opc.values.*` + `subscribe events`; buffers separados; flush **1 s ou 1000 linhas** (o que vier antes); eventos **antes** de samples; `insert().values(batch)` executemany; dumb pipe (tag órfã grava — F1 §3.4-2) | `services/recorder/src/ottima_recorder/{main,pipeline}.py` · `services/recorder/tests/test_pipeline.py` | N `OpcValue` publicados ⇒ N linhas em `samples`; `EventMessage` ⇒ linha em `events`; flush por tamanho E por tempo | RF-801 · spec §6.1–6.3 |
| 3.2 | Backpressure/resiliência: fila 100k **drop-oldest** + contador; buffer de eventos 10k prioritário; retry de flush 1→30 s; `recorder_backpressure` (warning, total) **na recuperação**; payload malformado ⇒ log+descarte; `/health` com `buffered_samples/buffered_events/dropped_total/last_flush_ts/db_ok` | `pipeline.py` · `main.py` · `tests/test_backpressure.py` | DB pausado ⇒ buffer segura; overflow ⇒ drop-oldest + contador; recuperação ⇒ 1 evento warning com total | RF-801 · spec §6.4–6.6 |

**Conclusão:** `uv run pytest services/recorder` verde (loop até verde).

---

## Etapa 4 — API: eventos, auditoria, histórico, certificados

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 4.1 | `GET /api/events`: filtros `severity/origin/start/end/limit` (default 100, máx 1000), ts desc, `require_operator` | `services/api/src/ottima_api/routers/events.py` · `packages/ottima-core/src/ottima_core/schemas/events.py` · `services/api/tests/test_events.py` | filtros; operador lê (ADR-015); 401 sem token | RF-803 (API) · spec §7.4 |
| 4.2 | Auditoria da API: `publish_event` em `POST /projects/{id}/activate` + CRUD de conexão/tag — payloads §7.2 (`project_activated{project_id,name}` · `connection_*{conn_id,project_id,name}` · `tag_*{tag_id,conn_id,name}`); users/projects sem efeito operacional ⇒ sem evento | `routers/{projects,connections,tags}.py` · `tests/test_audit_events.py` | mutação ⇒ evento com `kind` correto no canal (assinante de teste) | ADR-020 · spec F1 §6.3 · spec §7.2 |
| 4.3 | `GET /api/history`: raw ≤2 h / `samples_1m` >2 h; resposta colunar `{t[],v[],q[]}` (+`v_min[],v_max[]` no 1m); validações (≤6 tags, ≤31 d, `start<end`, defaults now−1h/now, 422 pt-BR); `require_operator` | `routers/history.py` · `schemas/history.py` · `tests/test_history.py` (seed + `refresh_continuous_aggregate`) | switch raw/1m; shape colunar; limites | RF-802 · spec §8 |
| 4.4 | API de certificados: `POST /api/certificates/app/generate` (409/`force` + aviso de re-trust), `GET /api/certificates/app` (metadados), `GET /api/certificates/app/export` (DER), `POST|DELETE /api/connections/{id}/server-certificate` (PEM→DER, `trusted/conn-<id>.der`, seta/limpa `server_cert_file`); RBAC admin | `routers/certificates.py` · `schemas/certificates.py` · `tests/test_certificates.py` (`certs_dir` temporário) | arquivos no layout §5.4; upload inválido ⇒ 422 | RF-202 · ADR-021 · spec §5.5/5.7 |

**Conclusão:** `uv run pytest` (workspace inteiro) verde (loop até verde). Superfícies prontas para os tipos TS do frontend.

---

## Etapa 5 — Integração composta (compose, smoke, L2)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 5.1 | Compose: `OTTIMA_DATABASE_URL` no opc-worker; **`deploy/docker-compose.e2e.yml`** (serviço `opcsim` build `tests/opcsim`; **portas de teste em 127.0.0.1**: opcsim 4840 e redis 6379 — só no override; produção segue 7 serviços/1 porta); `smoke.sh` estendido (com override: opcsim healthy, worker `/health` com conexão `up` e **`watchdog_alive=true`**) | `deploy/docker-compose.yml` · `deploy/docker-compose.e2e.yml` · `deploy/smoke.sh` | `docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build` + smoke verde (**L1**) | RNF-06/07 · ADR-023 · spec §10.1/10.4 · §11.2-L1 |
| 5.2 | Suite **L2** (`pytest -m e2e`): cenários E2E-F2-01…09 do spec §11.2 (setup via API: projeto + conexão→opcsim + tags; `opc.writes` publicado no redis exposto; freeze via nodes `sim/control/*`; **Δt do alarme medido em tempo real <12 s**; `docker stop opcsim` p/ falha dura) | `tests/e2e/test_f2_acquisition.py` · `tests/e2e/test_f2_failure.py` · `tests/e2e/test_f2_security.py` · `tests/e2e/conftest.py` | 9 cenários verdes contra o compose real | RF-204/205/206/207/801/802/803 · spec §11.2-L2 |

**Conclusão:** L1 + L2 verdes (loop até verde).

---

## Etapa 6 — Frontend

> Cada tarefa termina com **E2E via tool `browser`** contra o stack composto (com override e2e), evidência = screenshot por passo. Vermelho ⇒ corrigir ⇒ re-testar ⇒ repetir até verde. Rebuild por validação: `docker compose … up -d --build frontend`.

| # | Tarefa | Arquivos | Validação browser-tool | RF/ADR |
|---|---|---|---|---|
| 6.1 | Tokens `--pen-1..6` (spec §9.3) + nav "Conexões · Tags · Trend" (plaqueta) no shell + tipos OpenAPI regenerados (`generate:api`) | `frontend/src/styles/tokens.css` · `frontend/src/app/AppShell.tsx` · `frontend/src/app/router.tsx` · `frontend/src/lib/` | **B-01**: login admin → nav Engenharia visível | spec §9.1/9.3 · DESIGN §Colors |
| 6.2 | Tela `/engenharia/conexoes`: tabela + form (validações dos schemas F1: policy×mode, auth condicional, watchdog par-ou-vazio, período 500–5000), senha write-only, aviso "sem watchdog ⇒ conexão somente leitura", coluna "Último estado" via `/api/events` (polling 5 s) | `frontend/src/features/connections/*` | **B-02**: criar conexão real → opcsim; validações do form; linha na tabela | RF-201 · spec §9.1 |
| 6.3 | Tela `/engenharia/tags`: tabela filtrável (conexão/direção) + form com node_id **manual** | `frontend/src/features/tags/*` | **B-03**: criar tags R/W; filtros funcionam | RF-203 · spec §9.1 |
| 6.4 | Trend `/engenharia/trend`: uPlot **re-vestido** (fundo Poço, grade Linha, penas §9.3, mono tabular + EU), seletor ≤6 tags, janelas 30 min–7 d, polling 5 s, BAD = gap + rótulo (Canal Redundante); dep `uplot` | `frontend/src/features/trend/*` · `frontend/package.json` | **B-04**: ≥2 penas desenhando dados vivos do opcsim (screenshot com valores) | RF-802 · spec §9.2/9.3 |
| 6.5 | RBAC na UI: mutações ocultas para operador nas 3 telas (operador enxerga tudo — ADR-015) | `frontend/src/features/*` | **B-07**: login operador → vê telas, sem botões de mutação | ADR-015 · PRD §2 · spec §9.1 |

**Conclusão:** B-01…B-04 + B-07 verdes com evidências (loop até verde).

---

## Etapa 7 — Gate final da fase

| # | Tarefa | Verificar | Governança |
|---|---|---|---|
| 7.1 | **Rodada de gate completa** partindo de `down -v`: **L1** (smoke) → **L2** (9 cenários) → **L3 roteiro browser-tool B-01…B-07 completo**, incluindo **B-05** (congelar watchdog ⇒ "Último estado" em falha + BAD/gap no trend) e **B-06** (restaurar ⇒ estado volta) — evidências (screenshots) anexadas ao PR; **regressão Playwright F1** (`cd frontend && npm run e2e`; ajustes mínimos nos specs existentes permitidos — o shell ganhou nav —, specs novas não). Qualquer vermelho ⇒ corrigir ⇒ **repetir a rodada completa**. | L1+L2 verdes na mesma rodada + L3 completo + regressão F1 verde | spec §11.2 · aceite PRD §8-F2 |
| 7.2 | Encerramento: atualizar CLAUDE.md §Comandos (compose com override e2e, `pytest -m e2e` da F2); relatório de gate no PR (template do `docs/specs/F1-testes-e2e.md` §5, adaptado: L1 · L2 · L3-browser) | seção Comandos reflete os comandos reais; relatório no PR | CLAUDE.md (pede manutenção da seção) |

---

## Aderência ao aceite F2 (PRD §8) — Definition of Done

| Critério | Tarefas que o provam |
|---|---|
| **Leituras de servidor real chegam ao trend** | 5.2 (E2E-F2-01/02) + 6.4 (B-04) |
| **Bit de watchdog alternando** | 2.1/2.2 (unit) + 5.1 (smoke: `watchdog_alive=true`) |
| **Queda ⇒ alarme em <12 s** | 2.2 (unit, proporcional) + 5.2 (E2E-F2-04/06, Δt real) |
| **Queda ⇒ bloqueio de escrita** | 2.3 (unit) + 5.2 (E2E-F2-04) |
| Entrega: opc-worker com 3 modos de segurança | 2.4 + 5.2 (E2E-F2-07) |
| Entrega: barramento | Etapas 1–4 usam exclusivamente os canais §7.1 verbatim |
| Entrega: recorder | 3.1/3.2 + 5.2 (E2E-F2-01/08) |
| Entrega: watchdog | 2.1/2.2 + 5.1/5.2 |

**A fase só encerra com a rodada de gate da Etapa 7 inteira verde** (regra global 2: corrigir ⇒ re-testar ⇒ repetir até todos os testes — pytest e browser-tool — passarem).

## RF por tarefa (rastreabilidade)

| RF | Tarefas |
|---|---|
| RF-201 | 1.1, 1.4, 2.4, 6.2 |
| RF-202 | 0.4, 4.4 |
| RF-203 | 6.3 (tela; CRUD backend é F1; browse adiado — spec §1.2) |
| RF-204 | 0.1, 1.1, 1.2, 1.3, 1.4, 1.5 |
| RF-205 | 2.3 |
| RF-206 | 2.1, 2.2 |
| RF-207 | 2.2, 2.3 (contrato F3 registrado no spec §3.7) |
| RF-801 | 3.1, 3.2 |
| RF-802 | 4.3, 6.4 |
| RF-803 (metade API) | 4.1 |
| RNF-06/07 | 1.5, 3.2, 5.1 |

ADRs 002/003/006/009/017/020/021/023 citados por tarefa nas tabelas acima.
