# Tech Debt Registry

Track technical debt explicitly like bugs. Review weekly.

---

## Critical (Blocks Feature Work)

_Debt that prevents or significantly slows new development._

<!-- Example:
- [ ] **TD-001**: Legacy auth system needs migration
  - **Impact:** High - blocks SSO integration
  - **Effort:** 2 weeks
  - **Owner:** @unassigned
  - **Created:** 2025-01-01
-->

## High (Causes Frequent Issues)

_Debt that causes recurring problems or bugs._

<!-- Example:
- [ ] **TD-002**: N+1 queries in user dashboard
  - **Impact:** Medium - page load > 5s
  - **Effort:** 3 days
  - **Owner:** @unassigned
  - **Created:** 2025-01-01
-->

## Medium (Slows Development)

_Debt that makes development harder but doesn't block._

<!-- Example:
- [ ] **TD-003**: Test fixtures are brittle
  - **Impact:** Low - flaky CI
  - **Effort:** 1 week
  - **Owner:** @unassigned
  - **Created:** 2025-01-01
-->

## Low (Track for Later)

_Known issues not currently prioritized._

<!-- Example:
- [ ] **TD-004**: Could use newer React patterns
  - **Impact:** None - works fine
  - **Effort:** 2 weeks
  - **Owner:** @unassigned
  - **Created:** 2025-01-01
-->

---

## Resolved

_Completed tech debt items. Keep for 90 days then archive._

<!-- Example:
- [x] **TD-000**: Migrated from callbacks to async/await
  - **Resolved:** 2025-01-15
  - **Resolution:** Refactored auth module
-->
- [x] **TD-003**: Modelo integrador do MPC operava em coordenada ABSOLUTA (`y' = Ki·u`), sem ponto de balanço
  - **Resolved:** 2026-08-10
  - **Resolution:** `operating_point` por MV/DV (`MvVar`/`DvVar` em `flowgraph/mpc_config.py`), consumido em `builder.build_mpc` (`pair_input = coluna − operating_point`) e em `bumpless._pair_input_value` (`x_ss` e registrador de atraso resolvidos na coordenada do modelo). A porta do bloco passou a ser ABSOLUTA: `limits`, `du_max` e `initial_value` são o curso físico do atuador. Junto veio `MvVar.readback_tag_id` (tag `r` com a posição real da MV direta): em LOCAL a saída acompanha a variável OPC-UA ligada à MV, o que torna LOCAL→REMOTO e MAN→AUTO bumpless sem nenhum bloco externo; com tag configurada e ainda sem valor a porta sai FRIA (o `opc_write` a jusante suprime) em vez de escrever `initial_value` na planta. Validação em `validate._check_mpc_tags`; UI em `TabVariables.tsx`.
  - **Prova:** com a config real da debutanizadora e a MV parada no ponto nominal, a predição de LT-101 fica em 50,21 → 49,87 % em 60 min; a MESMA config com `operating_point = 0` prevê −109,59 % (deriva de −2,66 %/min). Na planta viva: saída de MV seguindo o readback (inclusive um degrau externo para 0 %), LOCAL→REMOTO e MAN→AUTO sem salto, e os dois blocos Script (`dv_desvio`, `mv_absoluto`) removidos do flow — 11 nós, 10 arestas, nenhum Script.
  - **Dois defeitos adjacentes achados na validação contra planta e corrigidos junto:** (1) MAN→AUTO reaplicava o `_plan` GUARDADO — calculado antes de o operador assumir, contra outro `u_prev` — em vez de segurar o último valor do MAN até o primeiro solve novo; na planta isso jogou XV-101 de 52 % para 7 % no instante da devolução do controle, sem passar pelo Δu. Agora `_command_mode` zera `_plan` ao entrar em AUTO. (2) `_readback_value` aceitava amostra com `quality != 0` como posição; num restart da planta as tags voltaram `0,0` com `quality=2`, e adotar isso semeia `_mv_manual` com zero — o clamp em `limits` manda o atuador para o batente. Agora vale a mesma régua do `opc_read` (`quality != 0` invalida) e o gate de arme usa o mesmo predicado.
- [x] **TD-001**: `flow-runtime` recebia o `.env` inteiro via `env_file`, expondo segredo ao processo que executa código do bloco Script
  - **Resolved:** 2026-08-10
  - **Resolution:** O `env_file` já estava restrito desde a F6a — `deploy/docker-compose.yml` passa ao flow-runtime só `OTTIMA_DATABASE_URL`/`OTTIMA_REDIS_URL`/`OTTIMA_LOG_LEVEL`, nunca `OTTIMA_SECRET_KEY`/`OTTIMA_FERNET_KEY`. O que faltava era o resíduo: (a) o worker do `script_pool` herdava aquelas duas URLs (que carregam credencial do banco) — `_worker_main` agora chama `os.environ.clear()` como PRIMEIRA instrução, antes do `_READY`, então uma fuga de sandbox não encontra segredo nenhum no ambiente; (b) barreira AST em `flowgraph/validate.py::_check_script_code`, que reprova com 422 pt-BR qualquer `ast.Name`/`ast.Attribute` dunder no código do Script — cobre `().__class__.__mro__[...].__subclasses__()`, a fuga clássica de sandbox restrito, que não depende de `__import__` (já removido de `ALLOWED_BUILTINS`).
  - **Prova:** teste do pool que roda um job lendo `os.environ` e prova dict vazio (RED: o worker via 119 variáveis herdadas, incluindo a `OTTIMA_DATABASE_URL` injetada pelo teste); dois testes de validação recusando dunder por `Name` e por `Attribute`, com o caso aritmético normal como baseline verde. Grep de dunder nas fixtures de `code` de bloco Script em `tests/e2e`, `services/*/tests` e `packages/ottima-core/tests`: nenhuma usa — nenhuma fixture precisou de ajuste.
  - **Resíduo documentado (não é débito aberto):** isolamento de processo/seccomp do worker de Script continua fora do escopo e fica como limitação conhecida do ADR-018. A barreira AST é defesa em profundidade, não um sandbox.
- [x] **TD-002**: Validação CPU-bound bloqueava o único worker uvicorn, que também serve `/ws`
  - **Resolved:** 2026-08-10
  - **Resolution:** `parse_graph` + `validate_graph` (funções puras sobre dados já materializados) passaram a rodar em `asyncio.to_thread` nos três callsites síncronos: `routers/flows.py::update_flow` (helper `_validar_grafo`), `routers/projects.py::import_project` (um `to_thread` por flow, dentro do laço, devolvendo o loop entre flows) e `flow_runtime/supervisor.py::_build` (sob `self._lock`, que continua serializando comandos por design — o objetivo é o `flow.status` das demais tasks continuar publicando durante deploy/hot-swap).
  - **Prova:** sem teste novo, deliberadamente — assert de responsividade de event loop é flaky por natureza. A prova é a suíte do workspace verde (1034 passed) com os três caminhos exercitados pelos testes existentes de `update_flow`, `import_project` e deploy.
- [x] **TD-004**: Conexão sem watchdog era read-only de fato, sem superfície que avisasse, e a recusa de escrita não realimentava o bloco MPC
  - **Resolved:** 2026-08-10
  - **Resolution:** A causa é 100% ESTÁTICA (configuração da conexão), então é barrada onde dá para barrar, sem inventar um canal de retorno bus→bloco. (a) Análise no deploy: `definition.py` computa `escreve_sem_watchdog` por bloco MPC seguindo as tags do `pid` ou, na MV direta, as arestas da saída da MV até blocos `opc_write`; (b) gate de arme: `blocks/mpc.py::auto_arm_blocked_reason` ganhou `"write_target_sem_watchdog"` como PRIMEIRO check, precedendo `worker_not_ready`/`cold_input` — erro de configuração ganha de transiente, e o `mpc_arm_failed` existente já leva o motivo à faixa anunciadora; (c) aviso no salvar: `update_flow` acrescenta a `FlowSaved.warnings` uma linha por bloco que escreve em conexão sem watchdog; (d) badge `"Somente leitura (sem watchdog)"` (`data-testid="conn-somente-leitura"`) na listagem de Conexões. A consulta "conexões sem watchdog" virou helper único (`ottima_core.connections.conexoes_sem_watchdog`) usado pelos dois serviços — uma regra só.
  - **Prova:** unit do gate (com o flag ⇒ motivo novo; sem o flag ⇒ inalterado, inclusive a precedência sobre `cold_input`); unit da função pura de avisos; teste de `update_flow` provando a linha em `FlowSaved.warnings` (RED genuíno: o teste `test_put_grafo_valido_grava_e_nao_avisa` existente ficou vermelho com o aviso real antes de as conexões de teste ganharem watchdog); teste de deploy provando `mpc_arm_failed {reason: write_target_sem_watchdog}`. E2E-TD-06 (`tests/e2e/test_td_watchdog.py`) cobre as duas pontas contra o stack.
- [x] **TD-005**: `comm_failure` derrubava o flow em definitivo, sem retomada automática nem botão de retomar
  - **Resolved:** 2026-08-10
  - **Resolution:** Retomada automática COMPLETA (ADR-025, novo). `on_comm_failure` tira um snapshot (`EstadoMpcTransplante`: eixos de modo, `mv_manual`, `mv_last`, SP por CV) de cada bloco MPC ANTES de `task.fail()`; `events.py` roteia `comm_restored` para o `on_comm_restored` novo, que — só se `flow.desired_state == "running"` continuar valendo no banco — redeploya pelo miolo extraído `_deploy_flow(user="sistema:retomada")`, aplica o snapshot nos blocos novos e rearma REMOTO/AUTO pela MESMA máquina de comandos que um operador usaria, com os SPs restaurados via `mpc_sp`. Publica `flow_resumed` e `mpc_mode_changed {reason: auto_resume}`. Uma tentativa por evento `comm_restored` (edge-triggered, sem retry storm); `deploy`/`stop` manuais limpam a pendência. A orquestração vive em `supervisor_resume.py` (módulo novo, mesmo padrão do `MpcOrchestrator`). **O ADR-017 permanece intacto para boot** — o escopo é queda de comunicação, não partida.
  - **Prova:** `test_comm_restored_nao_retoma_o_flow` (que fixava o comportamento antigo) foi REMOVIDO e substituído por quatro cenários: flow retoma sozinho; `desired_state == "stopped"` não retoma; snapshot restaura modos e SPs; deploy manual limpa a pendência. RED: `AssertionError` esperando `flow_state == "running"` pós `comm_restored`, com `on_comm_restored` ainda inexistente. E2E-TD-04/05 (`tests/e2e/test_td_retomada.py`) provam ponta a ponta com `docker compose stop/start opcsim`.
- [x] **TD-006**: Salvar o flow no editor derrubava um MPC em AUTO para LOCAL, sem confirmação e sem preservar o ponto de operação
  - **Resolved:** 2026-08-10
  - **Resolution:** Duas metades. **Runtime:** `MpcBlock.snapshot_estado()`/`aplicar_estado()` sobre a dataclass `EstadoMpcTransplante`; `build_definition` transplanta o estado quando a `functional_config` mudou MAS o conjunto de ids de MV é idêntico (resintonia pura), marcando `transplantado = True`; `reconcile_mpc_hosts` pula a devolução de `mode_cmd=auto` ao PLC nesse caso e emite `mpc_mode_changed {reason: hot_swap_bumpless}` para auditoria. O primeiro solve do worker novo já nasce bumpless de graça: `MpcHost._needs_reinit` força `reinit=True` no primeiro dispatch e `u_applied` lê o `_mv_last` restaurado. Mudança do conjunto de MVs ou do Ts do flow continua sendo reset para LOCAL — a dimensão do estado mudou, transplantar `u_prev` seria semear o modelo com um valor sem dono. **Editor:** função pura `impactoSave.ts::impactoDoSave` (espelho de `functional_config()`, ignora `label`/`exec_order`) classifica cada bloco MPC em `preservado`/`rearme_bumpless`/`reset_local`, e o diálogo `flow-impacto-dialog` mostra o efeito antes de Salvar ou de dar Deploy com o flow rodando.
  - **Prova:** RED comparando o payload do evento (`hot_swap` obtido, `hot_swap_bumpless` esperado). Cenários: reload com peso de CV mudado mantém `man_auto == "auto"` e a MV segura `mv_last` durante o build; MV adicionada reseta para LOCAL; config idêntico reusa a mesma instância. E2E-TD-01/02/03 (`tests/e2e/test_td_hotswap.py`) provam contra o stack, inclusive "MV sem salto além de `du_max` durante o swap". 10 checks unitários cobrem `impactoDoSave`, incluindo as bordas "só label", "só posição" e "MV reordenada mantendo o conjunto".
- [x] **TD-007**: Sem mínimo de movimento de MV e sem peso de supressão de movimento configurável
  - **Resolved:** 2026-08-10
  - **Resolution:** `MvVar` ganhou `du_min` (banda morta, `ge=0`) e `move_weight` (`gt=0`), com `model_validator` exigindo `du_min <= du_max`; os defaults (`0.0`/`1.0`) preservam bit a bit todo config já salvo. `builder.py` pondera o termo de movimento por `R_DELTA_U * mv.move_weight` (a constante segue como base). A banda morta é aplicada no WORKER, não no bloco — uma fonte só, para o modelo interno nunca divergir do que foi escrito: depois do solve, `|Δu| < du_min` ⇒ `u0 := u_prev`, e o registrador interno avança com o valor QUANTIZADO, nunca com o fantasma. Frontend: campos "Δu mínimo" e "Peso de movimento" na aba MV (`mpc-mv-du-min`, `mpc-mv-move-weight`), validação no Resumo e leitura com default para `graph_json` antigo.
  - **Prova:** RED nos dois: `move_weight` sem efeito (`assert 21.078... < 21.078...`) e `du_min` devolvendo o Δu fantasma cru (`assert 30.43 == 30.0`). Guard de não-regressão com `du_min=0`/`move_weight=1` reproduzindo o resultado atual. Golden Python→TS regenerado pelo gerador (`ottima_core.mpc_golden_export`), nunca à mão.
- [x] **TD-008**: `test_e2e_f6_05_overrun_pela_malha_tfs` decidia o gate por relógio de parede
  - **Resolved:** 2026-08-10
  - **Resolution:** Gate por CAUSA, não por efeito. O E2E foi reescrito: acompanha `mpc.state.status.overruns` durante a rodada, dá `pytest.skip` explícito se `overruns == 0` ("o solve coube no orçamento nesta máquina") e, quando houve estouro, assevera o CONTRATO (evento `mpc_overrun` presente; `mv_pid` sem avanço nos quadros de estouro) — nunca mais "MV congelada a rodada inteira". Junto entrou um teste determinístico no workspace (`services/flow-runtime/tests/test_td_overrun_gate.py`) que FORÇA o overrun com o worker `mpc_host_slow_solve_worker` (solve de 0,6 s contra orçamento de 0,5 s).
  - **Prova:** o teste determinístico assevera quatro coisas sobre valores observados: o contador incrementa e nunca regride; o evento `mpc_overrun` sai; a MV publica um único valor em toda a janela em AUTO (sem `SolveResult` "ok", `_plan` nunca é aplicado e a saída segura `_mv_last`); e o número de EVENTOS é menor que o número de estouros — que é exatamente o rearme de `_overrun_reported`, que só volta a armar quando um resultado não-overrun chega.
- [x] **TD-009**: `uv run pytest` do workspace sem veredito — 13 failed + 24 errors atribuídos a contenção de recurso, não confirmados
  - **Resolved:** 2026-08-11
  - **Resolution:** Confirmado: era contenção, não regressão real. `uv run pytest` do workspace inteiro, isolado (sem suíte concorrente rodando em paralelo), terminou limpo.
  - **Prova:** `1269 passed, 0 failed, 0 errors, 67 deselected in 1200.48s (0:20:00)` — nenhum dos 13 testes antes falhos, nem os 24 com erro de fixture do Redis, falhou sozinho numa máquina sem contenção.
- [x] **TD-010**: Checks unitários do frontend (`*.check.ts`) ficam fora do typecheck do build e acumularam erros de TS reais
  - **Resolved:** 2026-08-11
  - **Resolution:** Drift real: entre o registro do débito e agora, `MpcVarState` ganhou `status` (ADR-028), abrindo mais 3 erros (8 no total, não os 5 originais) em `pendencia.check.ts` (2) e `trendOperacao.check.ts` (1), além dos 5 já conhecidos em `HomePage.check.ts` (3), `eventos.check.ts` (1) e `faceplateVariavel.check.ts` (1) — todos por `horizons`/`status` ausente nas fixtures. Corrigidas as 6 fixtures. Decisão do "corrigir e decidir": `*.check.ts` ganha comando PRÓPRIO — `npm run typecheck` (`tsc --noEmit -p tsconfig.json`, cobre todo `src/`) — em vez de entrar no `build`, que continua excluindo `*.check.ts` de propósito (algumas fixtures usam `node:fs`; a imagem de produção roda sem `@types/node`).
  - **Prova:** `npx tsc --noEmit -p tsconfig.json` limpo (0 erros); `npm run build` verde; suíte de unidade completa (`npm run test:unit`): 458 passed.
- [x] **TD-011**: Nó do Filtro 1ª ordem no canvas só rotulava "passagem direta" com `tau = 0`, mas o runtime degrada em `tau < Ts/10`
  - **Resolved:** 2026-08-11
  - **Resolution:** `Ts` do flow entra em contexto (`ContextoTsFlow`/`useTsFlowDoEditor` em `nodes/contexto.ts`, mesmo padrão de `ContextoTags`), provido por `FlowEditorPage.tsx::ContextosDoEditor` a partir de `flow.data.ts_seconds`. Função pura `passagemDireta(tau, tsFlowSegundos)` em `graph.ts` (mesmo limiar `DIRECT_PASS_RATIO = 10` do runtime, `services/flow-runtime/.../blocks/lag.py`), consumida por `NoFiltroPrimeiraOrdem`: `tau === 0` continua "passagem direta" puro; `0 < tau < Ts/10` agora mostra `"<tau> s (passagem direta)"` em vez de esconder o desligamento atrás só do número.
  - **Prova:** 4 testes novos de `passagemDireta` em `filtros.check.ts` (tau=0; abaixo do limiar; exatamente no limiar — continua dinâmico, mesma fronteira do runtime; bem acima). `tsc --noEmit` limpo; suíte de unidade completa: 458 passed.
- [x] **TD-013**: §5.13 do PRD (blocos de filtro) ficava fora do agrupamento temático dos blocos
  - **Resolved:** 2026-08-11
  - **Resolution:** Varredura de `docs/specs/`/`docs/plans/` por citações de §5.9-§5.12: uma só, em `docs/plans/tests-e2e-f5.md`, version-pinned a "PRD.md v1.3" (já defasada da v1.7 então corrente) — deixada intocada por descrever o PRD NAQUELA versão, não um ponteiro vivo. Reordenado: §5.13 (Blocos de filtro) vira **§5.11**, logo após os demais blocos de canvas (§5.6-§5.10); Tela de operação avança para §5.12, Histórico e eventos para §5.13; §5.14 (SSTO) inalterado. Nenhum RF renumerado (RF-53x já ficava certo entre TFS/RF-52x e MPC/RF-60x). PRD avança para v1.8 com Changelog 1.8 documentando a reorganização.
  - **Prova:** `grep '^### 5\.' docs/PRD.md` confirma numeração sequencial 5.1-5.14 sem furo nem duplicata.
- [x] **TD-014**: SSTO otimizava alvos para MVs que o ADR-028 congela — alvo de regime inalcançável no ciclo degradado
  - **Resolved:** 2026-08-11
  - **Resolution:** `SstoInput` ganhou `frozen_mvs: frozenset[str] = frozenset()` (default vazio preserva bit a bit quem monta sem o campo). `SteadyStateOptimizer.solve()` clampa os limites de ΔMV da MV congelada em `(0.0, 0.0)` — mesmo mecanismo do `dumax = 0` do MPC dinâmico (`worker.py::_apply_tvp`), sem excluir a coluna nem mudar a montagem estrutural do LP. `worker.py::_run_ssto` (o hop que faltava — `SolveRequest.frozen_mvs` já vinha certo de `blocks/mpc.py::frozen_mv_ids`, só não chegava ao `SstoInput`) agora encaminha `frozen_mvs=request.frozen_mvs`. Detuning anti-flipping (`ρ‖ΔMV−ΔMV_anterior‖²`) não precisou de tratamento à parte: o limite duro já força `ΔMV≡0` da MV congelada independente do que o termo quadrático pediria.
  - **Prova:** RED genuíno confirmado por `git stash` do fix mantendo os testes: `TypeError` (campo inexistente) + `mv_target["mv_1"] == 100.0` quando deveria ficar em `10.0` (a MV "congelada" se movia até o limite). GREEN após o fix: teste de LP com 2 MVs (a congelada fica em `delta_mv=0`, a saudável compensa sozinha até o próprio limite) + não-regressão (sem congelamento, as duas se movem) + teste de integração no worker provando o hop `SolveRequest.frozen_mvs → SstoInput.frozen_mvs`. Suíte alvo: 52 passed (`test_ssto.py`, `test_ssto_integration.py`, `test_ssto_detuning.py`, `test_mpc_frozen_mv.py`); suíte completa de `services/flow-runtime/tests/`: 438 passed.

- [x] **TD-012**: Blocos de filtro sem cenário no gate E2E (camadas L2 e L3)
  - **Resolved:** 2026-08-11
  - **Resolution:** Um cenário L2 (`tests/e2e/test_td_filtros.py::test_e2e_td_10_kalman_deployado_filtra_e_escreve_na_planta`, E2E-TD-10) deploya `opc_read -> kalman -> opc_write` contra o stack real e prova, por 8 amostras consecutivas pós-partida, que a saída do Kalman diverge da leitura bruta na MESMA varredura (filtra de verdade, não repassa) e que o valor filtrado chega à planta simulada via o mirror do opcsim, com variação ao longo do tempo (entrega viva, não escrita parada). `first_order` não ganha cenário próprio — mesmo contrato de porta única/config escalar (RF-531) e mesmo caminho de execução do motor; o Kalman é o mais rico dos dois para provar filtragem de verdade. L3 (`frontend/e2e/filtros.spec.ts`, PW-FT-01, arquivo próprio pelo mesmo critério de `filtros.check.ts`) configura os dois blocos pelo modal (`tau`/`measurement_noise`/`process_noise`) e prova round-trip via reload + `GET /api/flows/{id}.graph_json` como fonte de verdade; `tau` novo fica bem acima de `Ts/DIRECT_PASS_RATIO` (TD-011) para o cenário ficar sobre o round-trip, não sobre o rótulo de borda.
  - **Prova:** L2: `uv run pytest -q -m e2e tests/e2e/test_td_filtros.py` → 1 passed; confirmado excluído do run default (`uv run pytest -q tests/e2e/test_td_filtros.py` → 1 deselected). L3: `npx playwright test filtros.spec.ts` → 1 passed; confirmado fora de `playwright.unit.config.ts` (`--list` não lista o arquivo).

---

## Metrics

| Category | Count | Oldest |
|----------|-------|--------|
| Critical | 0 | - |
| High | 0 | - |
| Medium | 0 | - |
| Low | 0 | - |
| **Total Open** | **0** | - |

_Last updated: 2026-08-11_

---

## Guidelines

### When to Add Debt

Add to registry when you:
- Skip tests to meet deadline
- Use workaround instead of proper fix
- Copy-paste instead of abstract
- Ignore deprecation warnings
- Hard-code instead of configure
- Disable linter rules

### Debt Item Format

```markdown
- [ ] **TD-NNN**: Brief description
  - **Impact:** Critical | High | Medium | Low
  - **Source:** [report-name.md] or [postmortem-name.md] (what identified this debt)
  - **Effort:** Time estimate
  - **Owner:** @username or @unassigned
  - **Created:** YYYY-MM-DD
```

### Priority Guidelines

| Priority | Criteria | Action |
|----------|----------|--------|
| Critical | Blocks features, security risk | Address immediately |
| High | Causes incidents, slows team | Next sprint |
| Medium | Annoying but manageable | Quarterly review |
| Low | Nice to fix someday | Opportunistic |

### Review Cadence

- **Weekly:** Review Critical/High items
- **Sprint planning:** Consider Medium items
- **Quarterly:** Audit full registry, archive resolved

### Commands

```bash
# View debt summary
/debt

# Add new debt item
/debt add "Description" --priority high

# Mark resolved
/debt resolve TD-001
```
