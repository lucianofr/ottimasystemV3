# Plano F3 — Motor + canvas

**Fase:** F3 (PRD §8) · **Status:** aprovado em blocos (1/3, 2/3, 3/3) em sessão de planejamento · 2026-08-04
**Executa:** `docs/specs/F3-motor-canvas.md` (aprovado integralmente na mesma sessão)
**Fontes normativas:** `docs/PRD.md` v1.2 · `docs/adr/ADR-001…024` (prevalecem) · `docs/GLOSSARY.md` · `PRODUCT.md`/`DESIGN.md` (frontend) · `docs/specs/F1-fundacao.md` e `docs/specs/F2-aquisicao.md` (vinculantes)

> Este plano não foi executado nesta sessão: nenhuma linha de código de aplicação foi escrita. Execução em worktree dedicado, fase única, conforme CLAUDE.md §Workflow.

---

## Regras globais (valem para todas as tarefas)

1. **Governança:** em conflito plano×spec×PRD×ADR: **ADR > PRD > spec > plano**. Um git worktree para a fase (`ottimaSystemV3-f3`), branch `f3-motor-canvas`, Conventional Commits pt-BR (CLAUDE.md).
2. **Ciclo de conclusão de etapa:** cada etapa termina com a bateria de testes da etapa **toda verde** — pytest e, onde houver superfície de UI/fim-a-fim, **testes E2E com a tool nativa `browser` do harness** (evidência = screenshot por passo). Qualquer teste vermelho ⇒ **corrigir ⇒ re-executar a bateria ⇒ repetir até verde**. Nenhuma etapa é dada como concluída com teste falhando.
3. **TDD estrito em lógica pura** (CLAUDE.md §Testes): `flowgraph`, scheduler/`exec_order`, discretização TFS, hot-swap. Runtime testado com Redis/Timescale de fixtures (F1/F2); OPC exclusivamente via opcsim (in-process ou container e2e) — **sem PLC real**.
4. **Dependências novas:** somente `numpy` (flow-runtime, produção) e `@xyflow/react` (frontend) — spec F3 §1.1, ambas da stack declarada (ADR-018/005, PRD §10). Qualquer outra exige aprovação do usuário.
5. **DoD da fase = aceite PRD §8-F3** (checklist ao final deste plano).

## Contratos do barramento — PRD §7.1 v1.2 (verbatim; tipados em `ottima_core.bus`)

| Canal | Produtor | Consumidores | Payload (JSON) |
|---|---|---|---|
| `opc.values.<conn_id>` | opc-worker | flow-runtime, recorder, api(WS) | {tag_id, ts, value, quality} |
| `opc.writes` | flow-runtime, api | opc-worker | {conn_id, tag_id, value, source, ts} |
| `flow.status.<flow_id>` | flow-runtime | api(WS) | {state, scan_ms, overruns, ts, ports{block_id→{porta:{v, ok}}}} |
| `flow.commands` | api | flow-runtime | {flow_id, cmd, args, user, ts} |
| `mpc.state.<flow_id>.<block_id>` | flow-runtime | api(WS) | {modes, status, vars, cost, prediction{t[], cv[][], mv[][]}} |
| `events` | todos | api(WS→banner), gravação | {ts, severity, origin, message, payload} |

Canais são **fixos** (ADR-002/CLAUDE.md); a F3 usa `opc.values.<conn_id>`, `opc.writes`, `flow.status.<flow_id>`, `flow.commands` e `events`. Nenhum canal novo (decisão A-3 do spec).

---

## Etapa 0 — Fundações (core)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 0.1 | Deps: `numpy` no flow-runtime (produção — escopo do script e TFS) | `services/flow-runtime/pyproject.toml` | `uv sync --all-packages` verde; `uv run python -c "import numpy"` | ADR-018 · spec §1.1 |
| 0.2 | **`flowgraph.py`** no core (TDD): modelo tipado do `graph_json` (nós {opc_read, opc_write, script, tfs} com config por tipo; `mpc` rejeitado na F3 — decisão A-1) + validações — tipos de porta (Script bivalente, resto estrito — decisão A-5), ciclos, entradas obrigatórias (`in` do Write, INs do Script, `uK` do TFS spec §3.4), `exec_order` 1..N único/contíguo, integridade de tag (existe, direção, projeto do flow), tetos (script 0..8 portas, TFS `d≤7200`, params) — e **warnings** de inversão de aresta. Interface: `parse_graph(json) -> FlowGraph` · `validate_graph(graph, tags) -> {errors[], warnings[]}` | `packages/ottima-core/src/ottima_core/flowgraph.py` · `packages/ottima-core/tests/test_flowgraph.py` | pytest: mesa completa de casos válidos/inválidos + warnings de inversão | RF-302/307 · ADR-024 · spec §5.2 |
| 0.3 | `bus.py`: `FlowStatus` ganha `ports: dict[str, dict[str, PortValue]]` (`PortValue{v: float\|bool\|None, ok: bool}`); constantes novas `KIND_FLOW_DEPLOYED/STOPPED/FAILED/OVERRUN`, `KIND_SCRIPT_TIMEOUT/ERROR`, `KIND_WRITE_SUPPRESSED`, `KIND_RELOAD_REJECTED`, `KIND_FLOW_CREATED/UPDATED/DELETED` | `packages/ottima-core/src/ottima_core/bus.py` · `packages/ottima-core/tests/test_bus_events.py` | pytest: serialização §7.1 v1.2 verbatim | spec §4.2/4.3 · decisão A-3 |

**Conclusão:** `uv run pytest packages` verde (ciclo corrigir→re-testar até verde).

---

## Etapa 1 — flow-runtime: núcleo de execução

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 1.1 | `snapshot.py`: `psubscribe opc.values.*` → `{tag_id: (value, quality, ts)}`; sem valor = ausente (cold start spec §3.0) | `services/flow-runtime/src/ottima_flow_runtime/snapshot.py` · `services/flow-runtime/tests/test_snapshot.py` | publica `OpcValue` na fixture Redis ⇒ snapshot reflete | RF-401 · spec §2.1 |
| 1.2 | `blocks/` base + OPC-Read + OPC-Write + **TFS** (TDD): protocolo `Block.step(inputs) -> outputs` com `{v, ok}`; Read (invalidez ⇔ `quality≠0`/sem valor); Write (publica `OpcWrite` com `source="flow:<fid>/block:<bid>"`; suprime entrada inválida/null + `write_suppressed` dedupe — decisão A-6); TFS (2 estágios de 1ª ordem exatos `a=e^(−Ts/τ)` em série + K, `τ<Ts/10` ⇒ passagem direta, IOPDT `acc+=Ki·Ts·u`, fila de atraso `d=round(θ/Ts)`, elemento desabilitado = ganho zero, linha vazia ⇒ `yJ=0.0`) | `services/flow-runtime/src/ottima_flow_runtime/blocks/{base,opc_read,opc_write,tfs}.py` · `tests/test_blocks.py` · `tests/test_tfs.py` | TFS vs solução analítica (degrau SOPDT/IOPDT, tempo morto, τ≈0); supressão de escrita; cold start não executa | RF-501/502/521/522 · ADR-022 · spec §3 |
| 1.3 | `script_pool.py` + `blocks/script.py`: ProcessPool dedicado (tamanho = constante de código — decisão A-4), escopo fechado (`IN1..INn`, `state`, `math`, `numpy`+alias `np`, builtins da lista exaustiva: `abs`, `min`, `max`, `round`, `len`, `range`, `float`, `int`, `bool`; `__import__` bloqueado), timeout `0.7×Ts` ⇒ kill+respawn do worker, state round-trip picklado (cópia-mestre no runtime, atualizada só em retorno OK), OUTx não atribuído/state não-picklável ⇒ `script_error`, exceção ⇒ traceback no payload, eventos deduplicados por bloco por período de falha | `services/flow-runtime/src/ottima_flow_runtime/script_pool.py` · `blocks/script.py` · `tests/test_script.py` | pool real: timeout mata e re-sobe; busy-loop não trava o loop; state sobrevive entre steps e NÃO muda em falha; saídas mantidas em timeout/exceção | RF-511..514 · ADR-018 · spec §3.3 |
| 1.4 | `scheduler.py` (TDD): FlowTask com deadline absoluto (`t0+n×Ts`, sem deriva), varredura que estoura ⇒ **pula fronteiras perdidas** + `overruns` + `flow_overrun` dedupe, execução por `exec_order` crescente com tabela de portas persistente entre varreduras (aresta invertida = valor da varredura anterior — RF-401), publica `flow.status` com `ports` a cada varredura (**`ts` = instante de disparo**) + em transição, estados `stopped→running→stopped\|failed`, exceção não tratada ⇒ `flow_failed` + task encerra (isolamento RF-402) | `services/flow-runtime/src/ottima_flow_runtime/scheduler.py` · `tests/test_scheduler.py` | clock controlado: fronteiras exatas, skip de overrun, semântica invertida = valor N-1, payload verbatim | RF-401/402/404 · ADR-007/024 · spec §2.2 |
| 1.5 | `supervisor.py` + `events.py` + `main.py` + `state.py`: comandos idempotentes (`deploy`/`stop`/`reload`; `flow_id` desconhecido = log e ignora), deploy carrega banco→valida→instancia (projeto inativo ⇒ warning; boot **parado** — nunca auto-aplica `desired_state`), hot-swap (stage validado, troca atômica na fronteira, preservação por `block_id`+config funcional — Script `code+n_inputs+n_outputs`, TFS matriz, Read/Write `tag_id`; `exec_order`/posição/rótulo não resetam; Ts muda ⇒ tudo re-instancia + re-âncora; staged inválido ⇒ `reload_rejected` mantém vigente), `comm_failure` ⇒ `failed(reason=comm_failure)` dos flows cujo grafo usa tags da conexão, `project_activated` ⇒ para todos, watermark 10 s backstop (dica perdida/deletado/projeto desativado), eventos `flow_deployed/stopped/failed` com `origin` do `user` do comando, `/health` `{status, service, version, flows:{id:{state, scan_ms, overruns, last_scan_ts}}}` (`status` = só dependências) | `services/flow-runtime/src/ottima_flow_runtime/{supervisor,events,main,state}.py` · `tests/test_supervisor.py` · `tests/test_hotswap.py` | deploy⇒running; reload preserva estado de bloco idêntico e zera alterado; comm_failure para o flow certo e poupa os demais; boot ⇒ tudo parado; watermark pega dica perdida | RF-101/104/207/304/402/405 · ADR-011/017 · spec §2.2/§4.1 |

**Conclusão:** `uv run pytest services/flow-runtime` verde (loop até verde).

---

## Etapa 2 — API: flows, deploy/stop e WS

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 2.1 | Router `/api/flows` + schemas: GET lista leve (id, nome, ts, `desired_state`, `updated_at` — sem `graph_json`) / GET `{id}` completo / POST (nome único por projeto) / PUT (valida via `flowgraph`, 422 pt-BR, responde `{flow, warnings[]}`) / DELETE (**409 se `desired_state='running'`** — interpretação determinística do "rodando" do spec §5.1: parar = `/stop`, que zera o desejado); GET `require_operator`, mutações `require_admin` | `services/api/src/ottima_api/routers/flows.py` · `packages/ottima-core/src/ottima_core/schemas/flows.py` · `services/api/tests/test_flows.py` | CRUD completo; 422 de ciclo/exec_order/tag; warnings de inversão no response; 409 do DELETE | RF-302/306/307 · spec §5.1/5.2 |
| 2.2 | Deploy/stop + auditoria: `POST /{id}/deploy` · `/stop` (admin — PRD §2) ⇒ seta `desired_state` + publica `FlowCommand{cmd, user}` ⇒ **202** (comando é intenção; UI confirma pelo estado publicado); PUT em flow com `desired_state='running'` publica `cmd=reload` após commit (decisão A-7); eventos `flow_created/updated/deleted` (`origin="user:<id>"`) — simultaneamente a dica de reconcile do runtime (padrão F2 §7.2) | `services/api/src/ottima_api/routers/flows.py` · `services/api/tests/test_flow_commands.py` | 202 + comando no canal (assinante de teste); reload publicado só quando rodando; eventos com kind correto | RF-306/405 · ADR-015/020 · spec §5.1/§4.3 |
| 2.3 | **WS `/ws`**: upgrade autenticado por `?token=` (`require_operator`), protocolo `{"subscribe": {"flow_status": [ids]}}`/`unsubscribe`, **uma** assinatura Redis compartilhada (psubscribe `flow.status.*`) roteando para os sockets, mensagens `{"channel": "flow.status.<id>", "data": {…}}`; sem replay (RNF-05) | `services/api/src/ottima_api/ws.py` · `services/api/tests/test_ws.py` | cliente WS de teste: subscribe ⇒ recebe payload com `ports`; token inválido ⇒ fechado; unsubscribe para o fanout | RF-305 · spec §5.3 |

**Conclusão:** `uv run pytest` (workspace inteiro) verde. Superfícies prontas para os tipos TS do frontend.

---

## Etapa 3 — Integração composta (compose, smoke, L2)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 3.1 | Compose: `OTTIMA_DATABASE_URL` no flow-runtime (novo consumidor de banco — `depends_on` healthy `timescaledb`); `smoke.sh` estendido: `/health` do flow-runtime ok com `flows` vazio no boot (**F3-L1a**: boot parado observável) | `deploy/docker-compose.yml` · `deploy/smoke.sh` | rodada compose (com override e2e) + smoke verde | RF-104 · RNF-06/07 · ADR-017/023 |
| 3.2 | Suíte **L2** (`pytest -m e2e`): cenários **E2E-F3-01..10** do spec §7.2 — setup via API (projeto/conexão→opcsim/tags/flows); jitter medido em ≥120 s de `flow.status` (p95 do desvio de fronteira < 50 ms, zero overruns); hot-swap ≤2×Ts sem stop/deploy no meio + continuidade de estado do TFS; atraso de 1 varredura do `exec_order` invertido + `warnings[]`; script busy-loop ⇒ `script_timeout` (flow segue) e exceção ⇒ `script_error`; watchdog congelado ⇒ `failed(comm_failure)` só nos flows da conexão, descongelar não retoma, deploy manual retoma; `project_activated` para tudo; restart do runtime ⇒ boot parado apesar de `desired_state='running'`; WS com `ports` e token inválido rejeitado; script em erro desde a 1ª varredura ⇒ `write_suppressed` e espelho não muda | `tests/e2e/test_f3_engine.py` · `tests/e2e/test_f3_jitter.py` · `tests/e2e/test_f3_hotswap.py` · `tests/e2e/test_f3_failure.py` · `tests/e2e/test_f3_ws.py` · `tests/e2e/conftest.py` (reusa F2) | 10 cenários verdes contra o compose real | Aceite PRD §8-F3 · RF-207/304/305/401 · spec §7.2 |

**Conclusão:** L1 + L2 verdes (loop até verde).

---

## Etapa 4 — Frontend

> Cada tarefa termina com **E2E via tool `browser`** contra o stack composto (com override e2e), evidência = screenshot por passo. Vermelho ⇒ corrigir ⇒ re-testar ⇒ repetir até verde. Rebuild por validação: `docker compose … up -d --build frontend`.

| # | Tarefa | Arquivos | Validação browser-tool | RF/ADR |
|---|---|---|---|---|
| 4.1 | Tipos OpenAPI regenerados (`generate:api`) + nav "Flows" (plaqueta; ordem Conexões · Tags · Flows · Trend) + **`/engenharia/flows`**: tabela (nome, Ts, desejado, "Último estado" via `/api/events` polling 5 s — padrão F2), criar (Ts da lista fixa ADR-007)/excluir (409), **Deploy/Parar** com estado *comandado* pendente até o *publicado* confirmar (Regra do Estado Publicado), escopo pelo projeto ativo no cliente (decisão F2 2026-08-04), RBAC `useCanMutate` | `frontend/src/lib/` · `frontend/src/app/{AppShell,router}.tsx` · `frontend/src/features/flows/{FlowsPage,useFlows}.tsx` | **B-F3-01** (login → nav Flows) · **B-F3-02** (criar flow Ts 0,5 → na lista) | RF-303/306 · spec §6.1 |
| 4.2 | **Editor** `/engenharia/flows/:id`: React Flow **re-vestido** (nó = chapa + plaqueta de título + portas rotuladas, bisel 2-4 px; default proibido; dep `@xyflow/react`), paleta 5 blocos (MPC presente, desabilitado, badge "F4" — decisão A-1), auto-numeração `exec_order` (próximo livre) + badge no nó + edição manual no modal + compactação ao excluir, validação de conexão no arraste (tipos decisão A-5, ciclo, 1 aresta por porta de entrada), modais de config por duplo-clique (Read/Write: seletor de tag por direção/projeto ativo reusando `useTags`; Script: 0..8 portas + código em `<textarea>` mono com Tab; TFS: matriz 2×2 com habilitação + params), save PUT + exibição de `warnings[]` (inversão, não-bloqueante) | `frontend/src/features/flows/{FlowEditorPage,nodes/*,ConfigModals,graphClient}.tsx` · `frontend/package.json` | **B-F3-03** (4 blocos arrastados; MPC inerte com badge; conexão incompatível recusada; badges exec_order) · **B-F3-04** (modais, save, warning de inversão) | RF-301/302/307 · ADR-005/024 · spec §6.2 |
| 4.3 | **Canvas ao vivo** (RF-305): hook `useFlowStatus` (WS `?token=`, subscribe do flow aberto, reconexão), valores nas portas (mono tabular — Regra do Número Tabular; inválido dessaturado + rótulo — Regra do Canal Redundante), lâmpada de estado do flow, `scan_ms`/`overruns` no cabeçalho da chapa; operador = somente-leitura (sem paleta/arraste/save/deploy — PRD §2) | `frontend/src/features/flows/useFlowStatus.ts` · `FlowEditorPage.tsx` · `nodes/*` | **B-F3-05** (deploy → pendente → rodando; valores vivos mudando, screenshots espaçados) · **B-F3-06** (editar script rodando → salvar → efeito sem parada) · **B-F3-08** (operador read-only) | RF-305 · ADR-015 · spec §6.2/§5.3 |

**Conclusão:** B-F3-01..06 + B-F3-08 verdes com evidências (loop até verde).

---

## Etapa 5 — Gate final da fase

| # | Tarefa | Verificar | Governança |
|---|---|---|---|
| 5.1 | **Rodada de gate completa** partindo de `down -v` + `--build`: regressão `uv run pytest` (workspace) + ruff → **L1** (smoke estendido) → **L2** completo (5 F1 + 9 F2 + 10 F3 = 24 cenários) → regressão Playwright F1 + `npm run test:unit` → **L3 roteiro browser-tool B-F3-01..08 completo**, incluindo **B-F3-07** (congelar watchdog ⇒ flow em falha na lista/canvas; restaurar ⇒ segue parado; re-deploy manual retoma) — evidências (screenshots) anexadas. Qualquer vermelho ⇒ corrigir ⇒ **repetir a rodada completa** | L1+L2 verdes na mesma rodada + L3 completo + regressões F1/F2 verdes | spec §7.2 · aceite PRD §8-F3 |
| 5.2 | Encerramento: CLAUDE.md §Comandos conferido/atualizado (L2 = 24 cenários; comandos F2 já cobrem o resto); relatório de gate (template F2) em `.superpowers/sdd/F3-motor-canvas/RELATORIO-GATE-F3.md` | seção reflete comandos reais; relatório completo | CLAUDE.md §Comandos |

---

## Aderência ao aceite F3 (PRD §8) — Definition of Done

| Critério | Tarefas que o provam |
|---|---|
| **Flow Script+TFS a 0,5 s sem jitter >10%** | 1.4 (unit, clock controlado) + 3.2 (E2E-F3-03, p95 real ≥120 s) |
| **Edição aplica na varredura seguinte sem parar** | 1.5 (unit hot-swap) + 3.2 (E2E-F3-04) + 4.3 (B-F3-06) |
| Entrega: editor React Flow (5 blocos) | 4.2 (B-F3-03/04) |
| Entrega: scan cycle | 1.4 + 3.2 (E2E-F3-02/05) |
| Entrega: hot-swap | 1.5 + 3.2 (E2E-F3-04) |
| Entrega: blocos Read/Write/Script/TFS | 1.2/1.3 + 3.2 (E2E-F3-02/06/10) |

**A fase só encerra com a rodada de gate da Etapa 5 inteira verde** (regra global 2: corrigir ⇒ re-testar ⇒ repetir até todos os testes — pytest e browser-tool — passarem).

## RF por tarefa (rastreabilidade)

| RF | Tarefas |
|---|---|
| RF-101/104 (ganchos de projeto/boot) | 1.5, 3.1, 3.2 (E2E-F3-08) |
| RF-207 (contrato F2 §3.7) | 1.5, 3.2 (E2E-F3-07) |
| RF-301 | 4.2 |
| RF-302 | 0.2, 2.1, 4.2 |
| RF-303 | 2.1, 4.1 |
| RF-304 | 1.5, 3.2 (E2E-F3-04) |
| RF-305 | 2.3, 4.3 |
| RF-306 | 2.1, 2.2, 4.1 |
| RF-307 | 0.2, 4.2 |
| RF-401 | 1.1, 1.4, 3.2 (E2E-F3-02/05) |
| RF-402/403 | 1.3, 1.4, 1.5 |
| RF-404/405 | 1.4, 1.5, 2.2 |
| RF-501/502 | 1.2 |
| RF-511..514 | 1.3, 3.2 (E2E-F3-06/10) |
| RF-521/522 | 1.2, 3.2 (E2E-F3-03/04) |
| RNF-02 | 1.4, 3.2 (E2E-F3-03) |
| RNF-06/07 | 3.1 |

ADRs 004/005/007/011/017/018/022/024 citados por tarefa nas tabelas acima.
