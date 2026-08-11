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

- [ ] **TD-009**: `uv run pytest` do workspace sem veredito — 13 failed + 24 errors na última execução, atribuídos a contenção de recurso e não confirmados
  - **Impact:** High - o gate de qualidade do backend está sem resultado válido; qualquer merge seguinte herda a dúvida
  - **Detalhe:** os 24 errors são `redis.exceptions.ConnectionError: Connection closed by server` no *setup* das fixtures (`test_script.py`, `test_snapshot.py`, `test_supervisor.py`); as 13 falhas são `await_until` estourando 10 s em `test_mpc_host.py` (5), `test_mpc_worker.py` (3), `test_supervisor_mpc.py` (2), `test_mpc_retomada.py`, `test_mpc_transplante.py` e `recorder/test_backpressure.py`. Durante a execução havia outra suíte concorrente rodando no worktree `otimizador-linear` (180% de CPU), 54 containers no ar e 24 de 31 GB de RAM ocupados. Nenhum dos testes que falharam toca o diff dos blocos de filtro, e o que ele toca passou (core flowgraph, blocos de runtime, `definition`, contratos, TFS e `mpc_discretize`)
  - **Ação:** rodar `uv run pytest` numa máquina ociosa, sem suíte concorrente e sem containers órfãos de testcontainers. Se algum dos 13 falhar sozinho, é regressão real e não contenção
  - **Source:** sessão ADR-026 (blocos de filtro) — execução pós-merge do commit `197dfa1`
  - **Effort:** 1 h (execução) + investigação se reproduzir
  - **Owner:** @unassigned
  - **Created:** 2026-08-10

- [ ] **TD-014**: SSTO otimiza alvos para MVs que o ADR-028 congela — alvo de regime inalcançável no ciclo degradado
  - **Impact:** High - o SP entregue ao MPC dinâmico pressupõe movimento de uma MV que não vai se mover; as MVs saudáveis são empurradas para compensar um alvo impossível
  - **Detalhe:** as duas camadas nasceram em branches paralelas e se encontraram no merge do ADR-028 (`a696616`). O ADR-028 classifica cada MV por ciclo e **congela** (`dumax = 0` no horizonte) a que estiver `local_override`/`bad_quality`/`out_of_service`, além de suprimir a escrita no PID dela. O SSTO (ADR-027, `target_calculation/`) roda antes do `make_step` e resolve o LP com **todas** as MVs como variáveis de decisão: `SstoInput` (`u`, `d`, `d_prev`, `bias`, `delta_mv_prev`) não tem noção de disponibilidade. Resultado: `delta_mv` pode conter movimento para uma MV congelada, e o `cv_target` derivado dele vira um SP que o controlador dinâmico não alcança. Não é inseguro — o limite de MV é duro em todo caminho de código e a congelada de fato não se move — mas é subótimo e pode oscilar (o LP recalcula o mesmo alvo impossível a cada ciclo, e o detuning anti-flipping do ADR-027 §8 compara contra um `delta_mv_prev` que nunca se realizou)
  - **Ação:** passar o conjunto congelado ao `SstoInput` e fixar `ΔMV = 0` para essas MVs no LP (é "excluir MV elegível", não mudar a formulação). Decidir também se o `ssto_delta_prev` do detuning deve ignorar as congeladas. Provável emenda ao ADR-027 ou ao ADR-028 registrando a precedência entre as camadas
  - **Source:** sessão ADR-028 (disponibilidade de MV por ciclo) — achado durante a resolução do merge de `mpc/worker.py`; deliberadamente NÃO corrigido ali por estar fora do escopo aprovado
  - **Effort:** 4 h (implementação + testes) + revisão do ADR
  - **Owner:** @unassigned
  - **Created:** 2026-08-11

## Medium (Slows Development)

_Debt that makes development harder but doesn't block._

<!-- Example:
- [ ] **TD-003**: Test fixtures are brittle
  - **Impact:** Low - flaky CI
  - **Effort:** 1 week
  - **Owner:** @unassigned
  - **Created:** 2025-01-01
-->

- [ ] **TD-010**: Checks unitários do frontend (`*.check.ts`) ficam fora do typecheck do build e acumularam 5 erros de TS reais
  - **Impact:** Medium - `tsconfig.build.json` exclui `src/**/*.check.ts`, então `npm run build` fica verde com os checks quebrados no tipo; o Playwright transpila sem checar e também não acusa
  - **Detalhe:** `npx tsc --noEmit -p tsconfig.json` acusa 5 erros de `horizons` ausente em `HomePage.check.ts` (3), `eventos.check.ts` (1) e `faceplateVariavel.check.ts` (1) — as fixtures de MPC desses arquivos não acompanharam o campo novo do tipo gerado do OpenAPI. Pré-existente à F6; confirmado por `git stash` contra a árvore limpa
  - **Ação:** corrigir as fixtures e decidir se o typecheck dos `*.check.ts` entra no comando de build ou em passo próprio
  - **Source:** sessão ADR-026 (blocos de filtro) — verificação de build
  - **Effort:** 2 h
  - **Owner:** @unassigned
  - **Created:** 2026-08-10

## Low (Track for Later)

_Known issues not currently prioritized._

<!-- Example:
- [ ] **TD-004**: Could use newer React patterns
  - **Impact:** None - works fine
  - **Effort:** 2 weeks
  - **Owner:** @unassigned
  - **Created:** 2025-01-01
-->

- [ ] **TD-011**: Nó do Filtro 1ª ordem no canvas só rotula "passagem direta" com `tau = 0`, mas o runtime degrada em `tau < Ts/10`
  - **Impact:** Low - só rótulo; o filtro se comporta corretamente. Com `Ts = 1 s` e `tau = 0,05`, o bloco roda como passagem direta e o nó exibe "0,05 s" sem dizer que o filtro está desligado. O texto de apoio do modal já avisa do limiar
  - **Ação:** injetar o `Ts` do flow no contexto dos nós (`nodes/contexto.ts`, como já se faz com as tags) e comparar contra `Ts/DIRECT_PASS_RATIO` em `NoFiltroPrimeiraOrdem`
  - **Source:** sessão ADR-026 — `code-reviewer`, achado LOW
  - **Effort:** 2 h
  - **Owner:** @unassigned
  - **Created:** 2026-08-10

- [ ] **TD-012**: Blocos de filtro sem cenário no gate E2E (camadas L2 e L3)
  - **Impact:** Low - cobertos por unidade e integração (39 casos de contrato/validação, 28 de runtime, 6 de instanciação/hot-swap, 17 checks de frontend); falta a prova ponta a ponta contra o stack
  - **Detalhe:** escopo declarado como fora no plano da feature — os 41 cenários da L2 não conhecem os blocos novos, e o roteiro de browser da L3 também não
  - **Ação:** um cenário de L2 com flow `opc_read → kalman → opc_write` deployado, e um passo de L3 configurando os dois filtros pelo modal
  - **Source:** sessão ADR-026 — escopo declarado no plano
  - **Effort:** 4 h
  - **Owner:** @unassigned
  - **Created:** 2026-08-10

- [ ] **TD-013**: §5.13 do PRD (blocos de filtro) fica fora do agrupamento temático dos blocos
  - **Impact:** Low - cosmético. As seções §5.6 a §5.10 descrevem blocos; a §5.13 caiu depois de "Histórico e eventos" porque mover exigiria renumerar §5.9–§5.12, que as specs de fase podem citar. A numeração dos requisitos (RF-53x) já posiciona os filtros entre TFS (RF-52x) e MPC (RF-60x)
  - **Ação:** ao renumerar, varrer `docs/specs/` e `docs/plans/` atrás de citações de "§5.9".."§5.12" antes de mexer
  - **Source:** sessão ADR-026 — decisão consciente de evitar renumeração
  - **Effort:** 1 h
  - **Owner:** @unassigned
  - **Created:** 2026-08-10

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

---

## Metrics

| Category | Count | Oldest |
|----------|-------|--------|
| Critical | 0 | - |
| High | 2 | 2026-08-10 |
| Medium | 1 | 2026-08-10 |
| Low | 3 | 2026-08-10 |
| **Total Open** | **6** | 2026-08-10 |

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
