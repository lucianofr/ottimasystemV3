# Graph Report - ottimaSystemV3  (2026-08-11)

## Corpus Check
- 522 files · ~503,582 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 6570 nodes · 15212 edges · 358 communities (250 shown, 108 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 868 edges (avg confidence: 0.68)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d34a5758`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- api.ts
- opc-worker/tests/test_supervisor.py
- mpcLogic.ts
- test_flowgraph_mpc.py
- test_flowgraph.py
- OpcSim
- ConnectionRuntime
- graph.ts
- WSClient
- PatternListener
- test_flow_commands.py
- FlakyRedis
- ValueSnapshot
- FakeClock
- Ambiente
- Supervisor
- validate.py
- MpcHost
- useFlowStatus.ts
- FlowTask
- PortSample
- test_mpc_block.py
- test_f3_engine.py
- test_operate.py
- test_watchdog.py
- WriteConsumer
- ScriptPool
- TagRef
- OpcWriteBlock
- opc-worker/tests/test_security.py
- routers/connections.py
- 4. Cenários
- test_ssto.py
- FakeSnapshot
- test_tfs.py
- Spec F6 — Portabilidade & hardening (export/import, certificados, suíte RNF-09)
- ottima_opc_worker/main.py
- test_f3_lifecycle.py
- channel_flow_status
- MpcConfig
- test_failure.py
- harness_factory
- test_backpressure.py
- Plano F6a — Portabilidade & dados
- test_flows.py
- test_flows_mpc.py
- FlowsPage.tsx
- test_certificates.py
- OpcSimServer
- test_mpc_discretize.py
- routers/flows.py
- MpcBlock
- test_connection.py
- test_subscriptions.py
- RecorderPipeline
- TrendOperacao.tsx
- generate_app_certificate
- mpc_config.py
- test_heartbeat.py
- test_ssto_model.py
- ModalConfigBloco.tsx
- test_pipeline.py
- ottima_opc_worker/security.py
- Plano F6b — Superfícies (Projetos, certificados, pendências, EU, DV)
- Spec F5 — Tela de operação (faceplates, trend com predição, eventos e banner)
- set_server_certificate
- ottima_core/security.py
- flowgraph/__init__.py
- solver.py
- e2e/conftest.py
- test_mpc_bumpless.py
- make_user
- ConnectionConfig
- publish_event
- create_flow
- test_server.py
- 4. Cenários
- _get
- test_mpc_builder.py
- mpc_golden_export.py
- FlowCommand
- models/__init__.py
- Validacao do bloco MPC (422 pt-BR string unica)
- certs.py
- test_td_hotswap.py
- impactoSave.ts
- routers/projects.py
- Plano F5b — Operação: tela de operação
- ValueHeartbeat
- ADR-011 — Hot-swap de flows sem interrupção; sem versionamento
- User
- Plano F4a — MPC: config & montagem
- bus.py
- test_mpc_worker.py
- test_f4_failure.py
- flow-runtime
- compilerOptions
- _solve
- MpcWorker — processo dedicado por bloco MPC
- ADR-013 — Modelo do MPC: matriz SOPDT + processo integrador; horizontes derivados do TSS
- build_mpc(config, ts_flow) -> BuiltMpc
- devDependencies
- ottima_flow_runtime/state.py
- dependencies
- Log de eventos persistido
- Plano F6c — Suíte RNF-09, cenários de portabilidade e guia de implantação
- Derivacao de horizontes Ts_mpc/Np/Nc (funcao pura)
- test_script.py
- set_mv
- MpcBlock (blocks/mpc.py)
- ADR-012 — Projeto como unidade de agrupamento e portabilidade (JSON)
- Semantica de invalidez: executa com o valor e propaga flag
- index.tsx
- api/tests/test_events.py
- MCP Tools: code-review-graph
- ADR-001…024 (decisões de arquitetura normativas)
- Supervisor (ciclo de vida dos FlowTasks)
- test_writes.py
- test_api_e2e.py
- test_mpc_load.py
- ADR-010 — Modos LOCAL/REMOTO e MAN/AUTO com transferência bumpless
- ADR-014 — Orçamento de tempo do MPC e multiplicador de execução
- ottima_core.flowgraph (validacao de grafo compartilhada)
- fixtures.ts
- ResumeOrchestrator
- Semantica de exec_order e tabela de portas persistente
- conftest.py
- Contrato de canais do barramento (PRD §7.1)
- definition.py
- Serviço api (FastAPI, porta interna 8000)
- generate-contracts.mjs
- ValueError
- routers/history.py
- Hot-swap (banco + dica, aplicacao atomica na fronteira)
- RF-206/207 watchdog por conexão e política de falha
- PRD OttimaSystem v1.2 (requisitos, contratos, fases)
- PRD §4 domain model: User, Project, OpcConnection, Tag, Flow, Block/Edge in graph_json, Event and Sample hypertables
- CLAUDE.md (archived) — OttimaSystem agent operating rules
- RBAC com papéis admin e operador
- Canal mpc.state.<flow_id>.<block_id>
- build_contracts
- Decision: two mode axes — LOCAL/REMOTO (PID vs MPC, bumpless both ways via PID mode writes AUTO<->RCAS/CAS/ROUT) and MAN/AUTO sub-mode of REMOTO; MV tracking in LOCAL
- Decision: Redis pub/sub internal bus (opc.values.<conn_id> out, opc.writes in)
- Decision: per-pair model matrix (MV->CV, DV->CV); response type per CV — self-regulating SOPDT(K,t1,t2,th) or integrating (Ki,th); Np/Nc derived from TSS, not user-edited; hard MV limits and rate limit
- PRD.md (archived) — OttimaSystem product requirements v1.0
- tfs.py
- _DropOldestBuffer
- ottima_flow_runtime/main.py
- scripts
- test_ssto_solver.py
- errors_of
- schemas/flows.py
- Decision: solver timeout ~70% of effective Ts_mpc — on overrun keep last MV, raise alarm, skip to next scan; per-block multiplier N (Ts_mpc = N x Ts_flow)
- Decision: per-connection watchdog with two OPC bits (read+write), crossed NOT, frozen >10s declares comm failure; failure stops writes and flows
- Decision: fifth palette block TFS — transfer-function matrix up to 2x2, each element SOPDT or IOPDT, discrete-time at flow Ts, persistent internal state
- Matriz de modelos SOPDT/integrador com horizontes derivados do TSS
- env.py
- cert_servidor
- pipeline.py
- await_until
- Plano F5a — Operação: dados & serviços
- api/tests/test_tags.py
- test_ssto_detuning.py
- WSClient
- Continuous aggregate samples_1m (avg/min/max/count/worst_quality)
- Decision: live flow edits take effect on the next scan without interruption; no flow versioning
- RF-401 scan cycle por exec_order com atraso determinístico de 1 scan
- script_pool: guarda do teto C2 + stats
- RNF-09 suíte de malha fechada MPC↔TFS
- package.json
- ottima-core
- test_auto_laco_e_ciclo
- sim
- Minor
- Retenção 1 mês + continuous aggregate (RF-801, ADR-003)
- ottima_core.contracts_export
- MpcState
- Campo grafite (paleta neutra escura dessaturada)
- Bumpless (transferência sem salto na MV)
- Scan cycle (avaliação a cada Ts em ordem de exec_order)
- TFS (bloco de simulação, matriz até 2×2 SOPDT/IOPDT)
- ADR-005 — Canvas com React Flow; execução 100% no backend
- ADR-023 — Escopo de plataforma da v1: pt-BR, auth local, HTTP interno, Compose on-prem
- Camadas L1/L1s/L2/L3 e 19 cenários do gate da F1
- Collector
- api/tests/test_health.py
- ottima_opc_worker/connection.py
- entrypoint-api.sh
- smoke.sh
- Faceplates com barras verticais PV/SP/OUT (convenção intocável)
- Filosofia ISA-101 (cor reservada a estado)
- Monorepo layout: docs/, frontend/, packages/ottima-core, services/{api,opc-worker,flow-runtime,recorder}, deploy/, tests/ as uv workspace
- ProcessPool dedicado do bloco Script
- tests/testkit/await_until.py (util unico)
- ottima_core.tags.project_tags
- ConnectionRuntime (máquina connecting→up→failed, backoff + jitter)
- _avisos_watchdog
- test_mpc_economics.py
- conexoes_sem_watchdog
- test_parse_exige_matriz_2x2_no_tfs
- test_get_app_com_pem_corrompido_devolve_500_em_pt_br
- blocks/__init__.py
- ottima_flow_runtime/__init__.py
- test_grafo_vazio_e_valido
- ottima_opc_worker/__init__.py
- ws.py
- Events
- ottima_recorder/__init__.py
- testkit/__init__.py
- Arquitetura on-premise APC (React/FastAPI/Redis/workers/TimescaleDB)
- Hierarquia normativa ADR > PRD > GLOSSARY
- Invariante: banco unico Postgres/TimescaleDB
- Invariante: frontend nunca executa logica de flow
- Invariante: opc-worker e o unico processo que fala OPC-UA
- Regra do Azul Único (uma cor de interação, nunca codifica dado)
- Regra do Número Tabular (mono tabular + EU em todo valor)
- Hot-swap (edição aplicada atomicamente na próxima varredura)
- Hypertable (tabela particionada por tempo, retenção 1 mês)
- Loop vivo (task asyncio contínua, nunca job de fila)
- Projeto (N armazenados, 1 ativo por vez)
- Restrição (variável em faixa com precedência sobre CVs)
- Editor canvas React Flow re-vestido (paleta 5 blocos)
- WS /ws (fanout de flow.status para o canvas ao vivo)
- Etapa 1 do F4a: core — config, validacao e derivacao (TDD)
- Etapa 5 do F4a: regressao completa e encerramento parcial
- Etapa 1 do F4b: MpcWorker — processo dedicado (A-3)
- Etapa 2 do F4b: bloco MPC, supervisor e saude
- Etapa 3 do F4b: API /api/operate e fanout WS
- Grupos de API (PRD §7.3)
- Fases de implementação F1–F6 (PRD §8)
- JSON de projeto export/import (PRD §7.2)
- Infra de testes (testcontainers + rollback por SAVEPOINT)
- Gate E2E da F2 em 3 camadas (E2E-F2-01…09 + roteiro B-01…07)
- Heartbeat de valor (republicação a cada 10 s)
- Decisao F3 #8: baseline da branch F3 (merge f2-aquisicao antes)
- Evento reload_rejected
- FlowId
- Any
- BaseModel
- opcsim
- ottima-workspace
- Princípio: falhar para o lado seguro é inegociável
- Princípio: operação e engenharia são mundos distintos
- v1: reescrita completa do sistema legado Django, sem compatibilidade
- test_stop_loga_desmonte_cancelado_por_fora
- PubSub
- PubSub
- Any
- PubSub
- Exception
- Any
- Redis
- TagConfig
- TagConfig
- TagConfig
- PubSub
- Supervisor
- FlowStatus
- Settings
- Decisão
- runtime_test_helpers.py
- SolveRequest
- test_td_flow_props.py
- OpcWrite
- test_pipeline_ssto.py
- OpcWrite
- setup_planta.py
- parametrize
- schemas/projects.py
- schemas/events.py
- ADR-025 — Retomada automática completa após `comm_restored`
- planta_virtual/supervisor_mpc.py
- build_mpc
- MpcConfig
- test_f4_ws.py
- FakeClock
- plant_ops.py
- All Reports by Category
- test_bus_ssto.py
- schemas/auth.py
- _propaga
- SolveResult
- FlowCreate
- FlowGraph
- probe_sessao.py
- SolveResult
- FlowNode
- FlowSaved
- FlowStatus
- FlowUpdate
- .advance
- test_timescale_ssto.py
- MvVar
- PidBinding
- patch
- MpcConfig
- Bloco 2 — Critical resolvíveis por reescrita da spec
- OpcWrite
- SolveResult
- FastAPI
- Task
- SpawnProcess
- MonkeyPatch
- MpcState
- parametrize
- Achados
- test_e2e_td_08_predicao_tem_np_mais_um_ponto_e_parte_do_u_prev
- test_e2e_td_06_salvar_avisa_e_armar_e_recusado
- Connection
- test_e2e_f6_05_overrun_pela_malha_tfs
- StatusStream
- ottima_core/tags.py
- Achados
- trendOperacao.check.ts
- test_kind_fora_de_hint_kinds_nao_dispara_reconcile
- schemas/tags.py
- Achados
- SteadyStateOptimizer
- field_validator
- Block
- MpcHost
- ValueSnapshot
- Connection
- DM
- async_sessionmaker
- AsyncSession
- T
- Table
- Achados
- Achados
- Tech Debt Registry
- WatchdogTask
- Achados
- Archive Directory
- Achados
- StubPool
- .stop
- Report Registry
- blocks/base.py
- BuiltMpc
- SstoRun
- ndarray
- test_reassinatura_limpa_respeita_o_freio
- .functional_config
- react
- react-dom
- tailwind-merge

## God Nodes (most connected - your core abstractions)
1. `await_until()` - 136 edges
2. `MpcConfig` - 76 edges
3. `MpcBlock` - 70 edges
4. `harness_factory()` - 68 edges
5. `mpc_node()` - 64 edges
6. `collect()` - 62 edges
7. `mpc_graph()` - 62 edges
8. `mpc_tags()` - 62 edges
9. `publish_event()` - 57 edges
10. `has()` - 57 edges

## Surprising Connections (you probably didn't know these)
- `Rodada de gate da F2 (L1 + L2 + L3 browser-tool)` --semantically_similar_to--> `Gate E2E de 3 camadas (L1 smoke, L2 pytest e2e, L3 browser)`  [INFERRED] [semantically similar]
  docs/plans/F2-aquisicao.md → CLAUDE.md
- `Rodada de gate da F3 (L2 = 24 cenários)` --semantically_similar_to--> `Gate E2E de 3 camadas (L1 smoke, L2 pytest e2e, L3 browser)`  [INFERRED] [semantically similar]
  docs/plans/F3-motor-canvas.md → CLAUDE.md
- `Princípio: estado publicado é a única verdade` --semantically_similar_to--> `Regra do Estado Publicado (comandado × confirmado)`  [INFERRED] [semantically similar]
  PRODUCT.md → DESIGN.md
- `Dependências RBAC (get_current_user, require_operator, require_admin)` --semantically_similar_to--> `Papéis admin/operador (ADR-015)`  [INFERRED] [semantically similar]
  docs/specs/F1-fundacao.md → PRODUCT.md
- `Serviço redis (barramento pub/sub, redis:7.4-alpine)` --semantically_similar_to--> `Barramento (Redis pub/sub: opc.values.*, opc.writes)`  [INFERRED] [semantically similar]
  deploy/docker-compose.yml → docs/GLOSSARY.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Malha fechada MPC<->TFS (aceite da fase F4)** — docs_specs_f4_mpc_mpcworker, docs_specs_f3_motor_canvas_tfs_block, docs_specs_f4_mpc_e2e_f4_03, docs_specs_f4_mpc_e2e_f4_05, docs_specs_f4_mpc_e2e_f4_06 [EXTRACTED 1.00]
- **Ciclo de vida de modos: armar bumpless, shed e hot-swap** — docs_specs_f4_mpc_init_bumpless, docs_specs_f4_mpc_modos_local_remoto_man_auto, docs_specs_f4_mpc_shed, docs_specs_f4_mpc_hot_swap_shed, docs_specs_f4_mpc_mpc_arm_failed [EXTRACTED 1.00]
- **Fonte unica de contratos Pydantic -> TS (debitos 2 e 4)** — docs_plans_f4a_mpc_config_montagem_contracts_export, docs_plans_f4a_mpc_config_montagem_generate_contracts_ts, docs_plans_f4a_mpc_config_montagem_mpc_state_model, docs_specs_f4_mpc_debito_2_contrato_porta_ts, docs_specs_f4_mpc_debito_4_portvalue_ws [EXTRACTED 1.00]
- **Barramento Redis pub/sub (produtores e consumidores no compose)** — deploy_docker_compose_redis, deploy_docker_compose_api, deploy_docker_compose_opc_worker, deploy_docker_compose_flow_runtime, deploy_docker_compose_recorder [EXTRACTED 1.00]
- **Aceitação de malha fechada MPC↔TFS (RNF-09)** — docs_prd_rnf09, docs_prd_mpc_bloco, docs_prd_tfs_bloco, docs_archive_claude_tdd_malha_fechada, tests_readme_mpc_tfs_destino [EXTRACTED 1.00]
- **Pipeline de dados: opc-worker publica no barramento Redis; flow-runtime, recorder e FastAPI consomem** — docs_adr_adr_006_separacao_opc_worker_flow_runtime_opc_worker, docs_adr_adr_002_barramento_redis_pubsub_redis_pubsub_bus, docs_adr_adr_006_separacao_opc_worker_flow_runtime_flow_runtime, docs_adr_adr_006_separacao_opc_worker_flow_runtime_recorder [EXTRACTED 1.00]
- **Subsistema MPC: formulário de configuração, modelo SOPDT/integrador, orçamento de solver, categorias de variáveis e simulação TFS** — docs_adr_adr_008_mpc_config_formulario_abas_formulario_mpc_abas, docs_adr_adr_013_modelo_sopdt_tss_integrador_matriz_sopdt, docs_adr_adr_014_orcamento_solver_multiplicador_timeout_solver_70pct, docs_adr_adr_014_orcamento_solver_multiplicador_multiplicador_execucao_mpc, docs_adr_adr_019_cv_sp_restricoes_por_faixa_precedencia_categorias_variaveis_mpc, docs_adr_adr_022_bloco_tfs_simulacao_bloco_tfs [INFERRED 0.85]
- **Padrão failsafe: watchdog de comunicação, boot parado, overrun visível e trilha de eventos protegem a planta** — docs_adr_adr_009_watchdog_bit_alternante_watchdog_bit_alternante, docs_adr_adr_009_watchdog_bit_alternante_failsafe_para_escrita, docs_adr_adr_017_projeto_ativo_unico_boot_parado_boot_parado_deploy, docs_adr_adr_014_orcamento_solver_multiplicador_politica_overrun, docs_adr_adr_020_log_eventos_sem_ack_log_eventos_persistido [INFERRED 0.75]
- **Process-safety write gate: watchdog alive + REMOTO mode + explicit deploy after boot** — docs_archive_adr_adr_009_watchdog_bit_alternante_decisao, docs_archive_adr_adr_010_modos_local_remoto_man_auto_bumpless_decisao, docs_archive_adr_adr_017_projeto_ativo_unico_boot_parado_decisao, docs_archive_prd_seguranca_processo [EXTRACTED 1.00]
- **Closed-loop MPC<->TFS acceptance suite: bumpless, constraint precedence, overrun, hot-swap without hardware** — docs_archive_adr_adr_022_bloco_tfs_simulacao_decisao, docs_archive_adr_adr_010_modos_local_remoto_man_auto_bumpless_decisao, docs_archive_adr_adr_014_orcamento_solver_multiplicador_decisao, docs_archive_adr_adr_019_cv_sp_restricoes_por_faixa_precedencia_decisao, docs_archive_adr_adr_011_hot_swap_sem_versionamento_decisao, docs_archive_prd_malha_fechada_aceitacao [EXTRACTED 1.00]
- **Redis pub/sub bus ecosystem: decoupled producers/consumers, state-published UI, prediction and event fanout channels** — docs_archive_adr_adr_002_barramento_redis_pubsub_decisao, docs_archive_adr_adr_006_separacao_opc_worker_flow_runtime_decisao, docs_archive_adr_adr_016_tela_operacao_faceplate_tendencia_predicao_decisao, docs_archive_adr_adr_020_log_eventos_sem_ack_decisao, docs_archive_prd_contratos_barramento [EXTRACTED 1.00]
- **Redis pub/sub bus: producer and consumer processes** — docs_ottimasystem_docsv1_1_adr_adr_002_barramento_redis_pubsub_redis_pubsub, docs_ottimasystem_docsv1_1_adr_adr_006_separacao_opc_worker_flow_runtime_recorder [EXTRACTED 1.00]
- **Flow execution semantics (scan cycle, exec_order, hot-swap, solver budget)** — docs_ottimasystem_docsv1_1_adr_adr_007_scan_cycle_ts_por_flow_scan_cycle, docs_ottimasystem_docsv1_1_adr_adr_024_ordem_execucao_explicita_exec_order, docs_ottimasystem_docsv1_1_adr_adr_011_hot_swap_sem_versionamento_hot_swap, docs_ottimasystem_docsv1_1_adr_adr_014_orcamento_solver_multiplicador_solver_budget [EXTRACTED 1.00]
- **Docker Compose on-prem v1 service topology** — docs_ottimasystem_docsv1_1_adr_adr_023_escopo_plataforma_v1_docker_compose, docs_ottimasystem_docsv1_1_adr_adr_001_fastapi_all_in_fastapi, docs_ottimasystem_docsv1_1_adr_adr_002_barramento_redis_pubsub_redis_pubsub, docs_ottimasystem_docsv1_1_adr_adr_006_separacao_opc_worker_flow_runtime_recorder [EXTRACTED 1.00]

## Communities (358 total, 108 thin omitted)

### Community 0 - "api.ts"
Cohesion: 0.04
Nodes (70): ADR-0015, ADR-0020, AnnunciatorBar(), AppShell(), NAV_ENGENHARIA, AuthGuard(), HomePage(), App() (+62 more)

### Community 1 - "opc-worker/tests/test_supervisor.py"
Cohesion: 0.19
Nodes (44): create_connection(), create_project(), create_tag(), make_supervisor(), async_sessionmaker, AsyncSession, fixture, OpcSimServer (+36 more)

### Community 2 - "mpcLogic.ts"
Cohesion: 0.05
Nodes (89): Button, ButtonProps, buttonVariants, Card(), Input, Label(), Select, AuthMode (+81 more)

### Community 3 - "test_flowgraph_mpc.py"
Cohesion: 0.11
Nodes (97): _auto_models(), co(), cv(), dv(), errors_of(), has(), integrating_params(), mpc_graph() (+89 more)

### Community 4 - "test_flowgraph.py"
Cohesion: 0.12
Nodes (55): base_graph(), edge_of(), has(), node_of(), parse_errors(), Mesa de casos de `ottima_core.flowgraph` (RF-302/307, ADR-024, spec F3 §5.2).…, Alguma mensagem contém todos os fragmentos., ADR-024/spec §4.1-3: mexer em ordem, rótulo ou posição não reinicia o estado. (+47 more)

### Community 5 - "OpcSim"
Cohesion: 0.10
Nodes (48): AmbienteMpc, assinar_mpc_state(), _config_mpc_malha(), criar_flow_mpc(), deploy_flow(), grafo_mpc_tfs(), OpcSim, operar_modo() (+40 more)

### Community 6 - "ConnectionRuntime"
Cohesion: 0.05
Nodes (35): backoff_delay(), build_client(), ConnectionRuntime, _disconnect_quiet(), Client, FailureReason, TagConfig, VariantType (+27 more)

### Community 7 - "graph.ts"
Cohesion: 0.03
Nodes (106): ADR-0011, ADR-0023, filtro(), POS, TAGS, ADR-0026, AGUARDO, COR_LAMPADA (+98 more)

### Community 8 - "WSClient"
Cohesion: 0.08
Nodes (32): channel_mpc_state(), connect(), hub(), make_token(), mpc_state_json(), operator_token(), _payload_of(), Any (+24 more)

### Community 9 - "PatternListener"
Cohesion: 0.05
Nodes (40): ChannelListener, _close(), PatternListener, Any, PubSub, Redis, Laço resiliente de assinatura ao barramento pub/sub do Redis (canal fixo ou…, Só volta com a inscrição confirmada: a publicação seguinte não se perde.… (+32 more)

### Community 10 - "test_flow_commands.py"
Cohesion: 0.08
Nodes (56): eventos(), Assinante do canal `events` num segundo cliente, como faz o worker (ADR-020).…, _admin_id(), _conexao(), _projeto(), Auditoria da API no canal `events` (ADR-020, spec F2 §7.2): o que emite e o que…, CRUD de users, CRUD de projects sem ativação e qualquer GET: canal silencioso…, Trocar `dependencies=[require_admin]` pelo parâmetro nomeado não pode afrouxar… (+48 more)

### Community 11 - "FlakyRedis"
Cohesion: 0.15
Nodes (7): _BrokenPubSub, _EmptyPubSub, FlakyRedis, PubSub, Assinante que morre na primeira escuta, como numa queda de conexão do Redis., Cliente cujo primeiro `pubsub()` devolve um assinante que cai ao escutar., Assinante cuja escuta termina limpa na hora, sem levantar nada.

### Community 12 - "ValueSnapshot"
Cohesion: 0.07
Nodes (28): mode_read_matches(), pid_targets(), Só as MVs cujo `pid` tem `mode_read_tag_id` — sem ele não há como confirmar nem…, `True` só se TODAS as MVs monitoradas confirmam `target` no `mode_read` agora., Task de fundo por bloco armado: confirma em até `CONFIRM_MISSES_LIMIT` ticks de…, watch_arm(), Último valor conhecido de uma tag, como veio do barramento. `value` continua…, Espelho do barramento: padrão `opc.values.*` → último valor por `tag_id`. (+20 more)

### Community 13 - "FakeClock"
Cohesion: 0.09
Nodes (47): events_of(), FakeClock, flow(), datetime, fixture, Redis, Contratos do laço de varredura (RF-401/402/404, ADR-004/007/024, spec F3 §2.2,…, Fábrica de assinantes: devolve a lista que recebe os payloads crus de um canal. (+39 more)

### Community 14 - "Ambiente"
Cohesion: 0.08
Nodes (51): Ambiente, congelar_watchdog(), esperar_ate(), esperar_conexao(), evento_de(), EventStream, publicar_escrita(), PubSub (+43 more)

### Community 15 - "Supervisor"
Cohesion: 0.07
Nodes (24): FlowTask, AsyncSession, Block, Flow, Mantém as `FlowTask` alinhadas com os comandos e com o banco., Tasks vivas por `flow_id` — inclui as paradas e as em falha, como o `/health`., Delega a `MpcOrchestrator.mpc_health` (spec F4 §4.10, plano F4b tarefa 2.3/5.0)., Delega a `MpcOrchestrator.script_pool_stats` (débito 5, spec F4 §4.10/§8). (+16 more)

### Community 16 - "validate.py"
Cohesion: 0.07
Nodes (56): FlowEdge, MvVar, Variável manipulada. Sem `pid` ⇒ MV "direta" (spec §2.1-3). Coordenada da…, _check_cycles(), _check_edge_endpoints(), _check_exec_order(), _check_fan_in(), _check_handles() (+48 more)

### Community 17 - "MpcHost"
Cohesion: 0.07
Nodes (37): _empty_result(), MpcHost, Any, Connection, SpawnProcess, Mata + junta + fecha o pipe. Roda numa thread (ADR-004); nunca levanta — mesmo…, Resultado sintético (nunca veio do filho) — mesmo formato vazio de…, Dono do processo do worker MPC de UM bloco (spec F4 §3.6/§4.2/§4.9). Ver… (+29 more)

### Community 18 - "useFlowStatus.ts"
Cohesion: 0.03
Nodes (65): ADR-0010, ADR-0027, AGORA, SEM_FLOW_STATUS, SEM_MPC_STATES, rotuloVariavel(), Props, TabLimits() (+57 more)

### Community 19 - "FlowTask"
Cohesion: 0.07
Nodes (20): PortValue, FlowTask, datetime, Redis, Ancora a grade e sobe a task. Idempotente: deploy em rodando é no-op (RNF-05)., Encerra a task. Idempotente e nunca levanta: é caminho de desmonte (RNF-05).…, Falha imposta de fora: `comm_failure` derruba os flows da conexão caída…, Uma varredura: blocos na ordem da tupla, lendo e escrevendo a tabela de portas. (+12 more)

### Community 20 - "PortSample"
Cohesion: 0.09
Nodes (46): has_cold_input(), PortSample, Valor de uma porta numa varredura. `v is None` é cold start (nunca houve valor…, Portão de cold start (§3.0): alguma entrada conectada ainda não tem valor., OpcReadBlock, Sem entradas; saída `out`. Invalidez (§3.1) é conservadora: `quality != 0`…, bus(), drain() (+38 more)

### Community 21 - "test_mpc_block.py"
Cohesion: 0.08
Nodes (67): _block(), _config(), _entra_remoto_auto(), entradas(), PortSample, Contratos do bloco MPC — cadência, modos, aplicar-na-fronteira e write-back…, Tag de readback configurada e ainda sem nenhum valor publicado: a saída sai…, Sem tag de readback configurada não há o que esperar — vale o hold de sempre. É… (+59 more)

### Community 22 - "test_f3_engine.py"
Cohesion: 0.08
Nodes (66): aguardar_parado(), aresta(), assinantes_de_status(), ativar_projeto(), bloco(), de_varredura(), deploy(), elemento_iopdt() (+58 more)

### Community 23 - "test_operate.py"
Cohesion: 0.07
Nodes (64): _aresta(), _cenario(), comandos(), _conexao(), _cv(), _flow(), _grafo_mpc(), _id_do_usuario() (+56 more)

### Community 24 - "test_watchdog.py"
Cohesion: 0.09
Nodes (44): assert_bit_stable(), await_bit(), await_flips(), connected(), make_config(), make_watchdog(), Client, ConnectionConfig (+36 more)

### Community 25 - "WriteConsumer"
Cohesion: 0.07
Nodes (29): BlockReason, RejectReason, describe_exception(), Detalhe curto e sem segredo para o payload do evento., _BlockedPeriod, _cancel(), coerce_value(), PubSub (+21 more)

### Community 26 - "ScriptPool"
Cohesion: 0.09
Nodes (25): _PoolState, Any, Connection, ProcessPool dedicado ao bloco Script (RF-511..514, ADR-018/004, spec F3 §3.3,…, Alvo do `spawn`: laço de jobs. Nível de módulo porque `spawn` precisa importá-…, Sobe um worker. Roda **numa thread** — nunca no event loop (ADR-004)., Espera um resultado no pipe. Roda **numa thread** — nunca no event loop…, Encerra o processo e fecha o pipe. Roda numa thread; nunca levanta. (+17 more)

### Community 27 - "TagRef"
Cohesion: 0.14
Nodes (38): BaseModel, O que a validação precisa saber de uma tag; o chamador projeta a linha do banco., TagRef, _conn_ids(), _mpc_escreve_sem_watchdog(), Conexões que o grafo referencia — o conjunto que o `comm_failure` consulta…, TD-004: alguma MV deste bloco escreve numa conexão sem watchdog completo — o…, edge() (+30 more)

### Community 28 - "OpcWriteBlock"
Cohesion: 0.13
Nodes (8): OpcWriteBlock, Redis, Bloco OPC-Write: publica `OpcWrite` no barramento (RF-502, spec F3 §3.2,…, Entrada `in`, nenhuma saída. Supressão (§3.2): entrada nula ou inválida não é…, Motivo da supressão, ou `None` quando a escrita pode sair. Entrada ausente do…, _suppression_reason(), _AccumulatorBlock, Bloco mínimo com estado, para exercitar as regras de base sem a matemática do…

### Community 29 - "opc-worker/tests/test_security.py"
Cohesion: 0.10
Nodes (46): certs_dir(), certs_dir_vazio(), endpoint_mudo(), failures(), falha_unica(), make_config(), pin_server_certificate(), ConnectionConfig (+38 more)

### Community 30 - "routers/connections.py"
Cohesion: 0.08
Nodes (34): EventOut, HTTPAuthorizationCredentials, create_app(), lifespan(), FastAPI, Settings, App factory da API: rotas sob /api, logging JSON e ciclo de vida do engine., Cria engine, session factory, Redis e o hub do /ws na subida; descarta na… (+26 more)

### Community 31 - "4. Cenários"
Cohesion: 0.09
Nodes (21): 1. Precondições de ambiente, 2. Regras de execução com a tool `browser`, 3. Evidências, 4. Cenários, 5. O que este roteiro NÃO cobre, 6. Ordem de gate, B-F6-01 — `/engenharia/projetos`: CRUD, exclusão do ativo recusada, B-F6-02 — Ativar: confirmação nomeia o projeto e o nº de flows a parar; invalidação de cache sem reload (+13 more)

### Community 32 - "test_ssto.py"
Cohesion: 0.13
Nodes (49): _co(), _config(), _config_conflitante(), _config_limite(), _cv(), _dv(), _entrada(), _iopdt() (+41 more)

### Community 33 - "FakeSnapshot"
Cohesion: 0.40
Nodes (3): FakeSnapshot, Duplo de `ValueSnapshot` — só o `.get()` síncrono que o bloco usa., TagValue

### Community 34 - "test_tfs.py"
Cohesion: 0.12
Nodes (44): double_pole(), first_order(), iopdt(), off(), parametrize, Contratos do bloco TFS contra a solução analítica (RF-521/522, ADR-022, spec F3…, Cascata de dois ZOH exatos != ZOH exato do produto. O 2o estágio consome…, Sem excitação não há resposta: entrada 0.0 é valor legítimo, não invalidez. (+36 more)

### Community 35 - "Spec F6 — Portabilidade & hardening (export/import, certificados, suíte RNF-09)"
Cohesion: 0.05
Nodes (39): 10. Débitos herdados — veredito, 11. Aderência ao aceite F6 (PRD §8), 12. Mapa de seções por plano (RFC-09), 1.1 Dentro da F6, 1.2 Fora da F6 — com destino registrado, 1.3 Emendas a documentos anteriores (consolidação), 1. Escopo da F6, 2.1 Schemas de bundle próprios (decisão A-2; emenda PRD §7.2 → v1.4; F6R-05) (+31 more)

### Community 36 - "ottima_opc_worker/main.py"
Cohesion: 0.06
Nodes (42): app(), App real com get_db na sessão em SAVEPOINT e get_redis no Redis efêmero dos…, Runtime que não subiu o supervisor está surdo a todo `deploy`: nunca…, StubRedis, test_check_redis_marca_estado(), test_health_responde_200_com_nome_do_servico(), test_health_sem_supervisor_nao_responde_ok(), check_database() (+34 more)

### Community 37 - "test_f3_lifecycle.py"
Cohesion: 0.12
Nodes (32): Ambiente, abrir_ws(), assinar_status(), criar_flow(), Any, Client, EventStream, fixture (+24 more)

### Community 38 - "channel_flow_status"
Cohesion: 0.15
Nodes (36): channel_flow_status(), connect(), hub(), make_token(), operator_token(), fixture, parametrize, WebSocket `/ws`: auth, protocolo, fanout e isolamento entre clientes (RF-305,… (+28 more)

### Community 39 - "MpcConfig"
Cohesion: 0.13
Nodes (30): derive_horizons(), mpc_state_dimension(), MpcConfig, Config do bloco MPC — vive inteiro no `graph_json` (spec §2.1, decisão…, Deriva `Ts_mpc`, `Np` e `Nc` (spec §2.2-5, RF-603). Função pura: devolve `Np`…, Dimensão do estado agregado do modelo do-mpc (spec §2.2-7). Soma, por par…, mpc_skeleton(), Mesa de casos de `ottima_core.flowgraph.mpc_config` (spec F4… (+22 more)

### Community 40 - "test_failure.py"
Cohesion: 0.15
Nodes (41): BusTrail, assert_bit_estavel(), bad_tag_ids_before(), bad_values(), collect_bus(), events_of_kind(), index_of_first(), make_config() (+33 more)

### Community 41 - "harness_factory"
Cohesion: 0.14
Nodes (67): Event, LogCaptureFixture, MonkeyPatch, collect(), harness_factory(), Redis, Fábrica de assinantes; a inscrição está confirmada quando a fábrica retorna., mpc_host_echo_worker() (+59 more)

### Community 42 - "test_backpressure.py"
Cohesion: 0.09
Nodes (43): backpressure(), count_rows(), event_payloads(), events_seen(), get_health(), health_app(), make_pipeline(), publish_samples() (+35 more)

### Community 43 - "Plano F6a — Portabilidade & dados"
Cohesion: 0.14
Nodes (13): Aderência (DoD do plano F6a), Contratos verbatim (spec F6 §2.1-4 — forma normativa do arquivo de projeto), Etapa 0 — Emendas documentais e constantes (spec §1.3; antes de qualquer código de feature), Etapa 1 — Contrato de portabilidade (spec §2; decisão A-2; F6R-05), Etapa 2 — Export e import (spec §3.1/§3.2; RF-102 emendado, RF-103), Etapa 3 — Health, log estruturado e superfície do Script (spec §3.3/§3.4), Etapa 4 — Schema: EU nas portas e faixa da DV (spec §4.1 backend, §4.2), Etapa 5 — Runtime: débitos herdados da F5 (spec §5) (+5 more)

### Community 44 - "test_flows.py"
Cohesion: 0.14
Nodes (40): _aresta(), _cenario(), _conexao(), _flow(), _grafo_read_write(), _mensagens(), _no(), _projeto() (+32 more)

### Community 45 - "test_flows_mpc.py"
Cohesion: 0.13
Nodes (41): _aresta(), _auto_models(), _cenario_mpc(), _conexao(), _cv(), _dv(), _flow(), _grafo_mpc() (+33 more)

### Community 46 - "FlowsPage.tsx"
Cohesion: 0.06
Nodes (40): ADR-0007, useCanMutate(), SEM_FILTRO, FlowPropsModal(), Props, CelulaDesejado(), COLUNAS, FlowForm() (+32 more)

### Community 47 - "test_certificates.py"
Cohesion: 0.11
Nodes (31): _admin_id(), _bruto(), _coluna(), _conexao(), _digest(), _projeto_da(), parametrize, API de certificados (RF-202, ADR-021): app cert de instância e trust por… (+23 more)

### Community 48 - "OpcSimServer"
Cohesion: 0.08
Nodes (37): Namespace, cmd_estado(), cmd_hist(), cmd_modo(), cmd_mv(), cmd_sp(), cmd_tags(), _comando_por_var() (+29 more)

### Community 49 - "test_mpc_discretize.py"
Cohesion: 0.10
Nodes (34): _delay_samples(), discretize_iopdt(), discretize_sopdt(), PairSS, Discretização ZOH-exata por par SOPDT/IOPDT no `Ts_mpc` (spec F4 §3.1; TDD…, IOPDT: integrador retangular `acc += Ki*Ts*u` — idêntico ao `_Iopdt` do TFS, 1…, Modelo discreto de um par da matriz MPC, no `Ts_mpc`, sem o atraso. `a`: matriz…, `round(theta/ts)`: convenção banker's (half-even) do `round()` do Python. NOTA… (+26 more)

### Community 50 - "routers/flows.py"
Cohesion: 0.16
Nodes (32): ProjectFilter, put, _carregar(), _comandar(), create_flow(), delete_flow(), deploy_flow(), get_flow() (+24 more)

### Community 51 - "MpcBlock"
Cohesion: 0.06
Nodes (29): Block, _LocalRemote, MpcHost, MpcPrediction, MpcStatus, _clamp(), _empty_prediction(), MpcBlock (+21 more)

### Community 52 - "test_connection.py"
Cohesion: 0.15
Nodes (40): collect_events(), make_config(), make_runtime(), of_kind(), ConnectionConfig, ConnectionRuntime, ConnectionSnapshot, MonkeyPatch (+32 more)

### Community 53 - "test_subscriptions.py"
Cohesion: 0.15
Nodes (35): collect_events(), collect_values(), make_config(), of_kind(), of_tag(), ConnectionConfig, ConnectionRuntime, MonkeyPatch (+27 more)

### Community 54 - "RecorderPipeline"
Cohesion: 0.06
Nodes (26): health(), Sempre 200: a degradação vai no corpo (spec F2 §2.2-8). Sem lifespan (app cru…, health(), Sempre 200: a degradação vai no corpo (spec F2 §2.2-8/§6.6). Sem pipeline…, datetime, MpcState, Samples + eventos + mpc_samples + ssto_runs descartados por overflow; nunca…, Payloads que não parsearam: lixo no canal, não pressão — contador separado. (+18 more)

### Community 55 - "TrendOperacao.tsx"
Cohesion: 0.05
Nodes (69): LegendaOperacao(), LegendaOperacaoProps, ROTULO_CATEGORIA, calcularRangeXOperacao(), corSecaoFutura(), ParametrosRangeXOperacao, pluginSecaoFutura(), ColunasOperacao (+61 more)

### Community 56 - "generate_app_certificate"
Cohesion: 0.14
Nodes (32): app_cert_paths(), generate_app_certificate(), Gera o certificado autoassinado de instância de aplicação (spec F2 §5.3).…, Monta os caminhos do certificado de aplicação, sem tocar no disco., Lê os metadados do certificado de aplicação. Devolve `exists=False` quando o…, read_app_certificate(), OttimaSystem — pacote compartilhado (modelos, schemas, barramento, segurança)., _falha_na_gravacao() (+24 more)

### Community 57 - "mpc_config.py"
Cohesion: 0.09
Nodes (28): ConstraintVar, CvVar, DvVar, EconomicsConfig, _exigir_prefixo(), Horizons, Limits, ModeValues (+20 more)

### Community 58 - "test_heartbeat.py"
Cohesion: 0.18
Nodes (32): beating(), collect_values(), heartbeat_tags(), make_config(), make_runtime(), of_tag(), ConnectionConfig, ConnectionRuntime (+24 more)

### Community 59 - "test_ssto_model.py"
Cohesion: 0.11
Nodes (36): PairSS, SSTO — camada de alvos de regime permanente por LP acima do MPC (ADR-027).…, build_steady_state_model(), pair_steady_state_gain(), ndarray, Modelo de regime permanente do SSTO: `G`, `Gd` e a base de predição (ADR-027…, Ganho de regime permanente de UM par, na leitura que o `kind` da linha exige.…, `G`/`Gd` + metadados de ordem (ADR-027 §3). `row_ids`: CVs e depois Restrições… (+28 more)

### Community 60 - "ModalConfigBloco.tsx"
Cohesion: 0.11
Nodes (23): inteiroDoCampo(), matrizDoFormulario(), nomeParam(), numeroDoCampo(), CamposTfs(), PARAMS, Props, trocarElemento() (+15 more)

### Community 61 - "test_pipeline.py"
Cohesion: 0.15
Nodes (33): delete, channel_opc_values(), count_rows(), instrumented(), make_pipeline(), purge(), Any, AsyncSession (+25 more)

### Community 62 - "ottima_opc_worker/security.py"
Cohesion: 0.13
Nodes (26): BaseException, CertMismatchError, CertMissingError, _configure_channel(), configure_client(), _configure_identity(), _decrypt_password(), _is_certificate_status() (+18 more)

### Community 63 - "Plano F6b — Superfícies (Projetos, certificados, pendências, EU, DV)"
Cohesion: 0.14
Nodes (13): Aderência (DoD do plano F6b), Etapa 1 — Fundação: helper, primitivos de arquivo e módulos compartilhados (spec §6.0; F6R-10/11), Etapa 2 — Página `/engenharia/projetos` (spec §6.1; decisão A-13; RF-101/102/103), Etapa 3 — Certificados (spec §6.2; decisão A-7; RF-202, ADR-021), Etapa 4 — Pendência de segredo na tabela de Conexões (spec §6.3; decisão A-4), Etapa 5 — EU nas portas e faceplate de DV (spec §4.1 frontend, §4.2, §6.4/§6.5), Etapa 6 — Débitos de frontend da F5 (spec §6.6, os seis), Etapa 7 — Fechamento do plano F6b (+5 more)

### Community 64 - "Spec F5 — Tela de operação (faceplates, trend com predição, eventos e banner)"
Cohesion: 0.06
Nodes (32): 10. Aderência ao aceite F5 (PRD §8), 1.1 Dentro da F5, 1.2 Fora da F5 — com destino registrado, 1.3 Emendas a documentos anteriores (consolidação; F5R-26), 1. Escopo da F5, 2.1 Emenda PRD §7.1 → v1.3: `ts` e `prediction.ts` no `mpc.state` (decisão A-2; F5R-01), 2.2 Hypertable `mpc_samples` (decisão A-1; migration `0003_mpc_samples`, SQL cru, três passos como a 0002), 2.3 Recorder (F5R-12) (+24 more)

### Community 65 - "set_server_certificate"
Cohesion: 0.14
Nodes (27): ConnectionCreate, ConnectionOut, ConnectionUpdate, _carregar(), clear_server_certificate(), create_connection(), delete_connection(), _excede_o_declarado() (+19 more)

### Community 66 - "ottima_core/security.py"
Cohesion: 0.14
Nodes (21): LoginOut, create_access_token(), decode_access_token(), decrypt_secret(), encrypt_secret(), verify_password(), test_fernet_roundtrip_e_chave_errada(), test_hash_argon2id_e_verificacao() (+13 more)

### Community 67 - "flowgraph/__init__.py"
Cohesion: 0.11
Nodes (40): NodeConfig, Modelo tipado do `graph_json` de um flow + validação compartilhada (RF-302/307,…, FirstOrderConfig, FlowEdge, FlowGraph, FlowNode, GraphParseError, IopdtParams (+32 more)

### Community 68 - "solver.py"
Cohesion: 0.10
Nodes (27): Protocol, _active_bounds(), _empty(), GurobiBackend, Bounds, ndarray, OSQPBackend, Bounds (+19 more)

### Community 69 - "e2e/conftest.py"
Cohesion: 0.09
Nodes (32): FixtureRequest, admin(), _aguardar_flow_parado_mpc(), ambiente_mpc(), _ativar_sentinela(), compose(), conexao_health(), _conf() (+24 more)

### Community 70 - "test_mpc_bumpless.py"
Cohesion: 0.19
Nodes (18): _cv(), _integrating_config(), _mv(), _par_integrating(), _par_selfreg(), Contratos de `mpc.init_bumpless` — arme/re-arme sem salto (spec F4 §3.6; TDD…, Avalia `y_{row_id}` (aux do modelo) em `mpc.x0`/`tvp_template[k=0]` diretamente…, Modelo do bloco usa K=2.0 (config), mas a "planta real" simulada aqui tem K=2.4… (+10 more)

### Community 71 - "make_user"
Cohesion: 0.10
Nodes (17): admin_headers(), client(), make_user(), operator_headers(), fixture, Fixtures da API: settings de teste, app com get_db/get_redis sobrescritos,…, Settings isoladas do .env local, com segredos determinísticos de teste., Cria usuários direto no banco da sessão de teste (senha já em Argon2id). (+9 more)

### Community 72 - "ConnectionConfig"
Cohesion: 0.06
Nodes (37): ConnectionConfig, Tag configurada de uma conexão., Configuração de uma conexão OPC-UA, tal como o worker a enxerga., Só há watchdog com o par de node_ids: sem os dois não há handshake (ADR-009)., Tudo que exige recriar a sessão asyncua quando muda (tarefa 1.4)., Conjunto de tags em ordem estável: muda ⇒ recria só a subscription (tarefa 1.4)., TagConfig, _cancel() (+29 more)

### Community 73 - "publish_event"
Cohesion: 0.12
Nodes (19): EventMessage, publish_event(), Any, datetime, Redis, Publisher canônico do canal `events` (spec F2 §7.1, ADR-020). Única forma de…, events_sub(), fixture (+11 more)

### Community 74 - "create_flow"
Cohesion: 0.14
Nodes (52): parametrize, counter_graph(), create_connection(), create_flow(), create_project(), delete_flow(), async_sessionmaker, AsyncSession (+44 more)

### Community 75 - "test_server.py"
Cohesion: 0.16
Nodes (24): _any_task_done(), _client_credentials(), _differs(), _equals(), _greater_than(), Any, Client, fixture (+16 more)

### Community 76 - "4. Cenários"
Cohesion: 0.11
Nodes (17): 1. Precondições de ambiente, 2. Regras de execução com a tool `browser`, 3. Evidências, 4. Cenários, 5. O que este roteiro NÃO cobre, 6. Ordem de gate, B-F5-01 — Login operador, navegação ao grupo Operação, seletor e redirect direto, B-F5-02 — Faceplates: barras verticais, mono tabular, lâmpada `building` no deploy recém-feito (+9 more)

### Community 77 - "_get"
Cohesion: 0.11
Nodes (29): OttimaSystem — API REST., me(), health(), Health check público (sem autenticação)., _amostra(), _get(), _inserir(), _instantes() (+21 more)

### Community 78 - "test_mpc_builder.py"
Cohesion: 0.15
Nodes (30): _co(), _config_integradora(), _cv(), _du_config(), _dv(), _move_weight_config(), _mv(), _mv_plan() (+22 more)

### Community 79 - "mpc_golden_export.py"
Cohesion: 0.15
Nodes (46): _arredondamento_bankers(), build_golden(), _cenario_caps_cv_restricao(), _cenario_caps_dv(), _cenario_caps_mv(), _cenario_config_minima_valida(), _cenario_horizons_dimensao_aviso(), _cenario_horizons_np_abaixo() (+38 more)

### Community 80 - "FlowCommand"
Cohesion: 0.17
Nodes (23): FlowCommand, ConstraintOut, CvOut, DvOut, list_mpcs(), ModeCommand, _mpc_nodes(), MpcNodeOut (+15 more)

### Community 81 - "models/__init__.py"
Cohesion: 0.15
Nodes (16): DeclarativeBase, Base, Base declarativa e mixin de timestamps (SQLAlchemy 2.0; DDL: spec F1 §3.1)., TimestampMixin, OpcConnection, Conexão OPC-UA (RF-201/206, ADR-009/021; DDL: spec F1 §3.1)., Flow, Flow (ADR-005/007/011/017; DDL: spec F1 §3.1). (+8 more)

### Community 82 - "Validacao do bloco MPC (422 pt-BR string unica)"
Cohesion: 0.11
Nodes (24): Etapa 4 do F4a: paleta, no dinamico e modal 7 abas, MpcConfig (Pydantic, espelho do spec 2.1), Componentes do modal MPC (MpcModal + TabGeneral..TabSummary), Paleta com MPC arrastavel + no com portas dinamicas, validate_graph libera mpc e valida spec 2.2 inteiro, B-F4-01: paleta com MPC habilitado e no sem portas antes de configurar, B-F4-02: modal 7 abas, criacao de variaveis e matriz de modelos, B-F4-04: portas dinamicas apos salvar e 422 do servidor em pt-BR (+16 more)

### Community 83 - "certs.py"
Cohesion: 0.13
Nodes (27): AppCertificateInfo, AppCertPaths, _application_uri_of(), _discard(), _ensure_dir(), _info_from_certificate(), _load_certificate(), Certificate (+19 more)

### Community 84 - "test_td_hotswap.py"
Cohesion: 0.16
Nodes (26): PubSub, _armar_em_auto(), _bloco_mpc(), coletor_eventos(), ColetorEventos, grafo_com_mv_extra(), grafo_com_peso_de_cv(), motivos_de_modo() (+18 more)

### Community 85 - "impactoSave.ts"
Cohesion: 0.14
Nodes (14): DadosMpc, GraphJson, NoSerializado, DADOS_BASE, VARIAVEIS_BASE, configFuncional(), ehMpc(), igual() (+6 more)

### Community 86 - "routers/projects.py"
Cohesion: 0.11
Nodes (36): patch, Project, ProjectCreate, ProjectImportOut, ProjectUpdate, Request, activate_project(), _carregar() (+28 more)

### Community 87 - "Plano F5b — Operação: tela de operação"
Cohesion: 0.14
Nodes (13): Aderência ao aceite F5 (PRD §8) — Definition of Done da FASE, Etapa 1 — Canal único de sessão (spec §7.1; F5R-04/22), Etapa 2 — `resolverAlarmes` e faixa anunciadora real (spec §7.2; F5R-02/03/19), Etapa 3 — Navegação, Home e `/eventos` (spec §7.3/§7.5), Etapa 4 — Tela `/operacao/:flowId/:blockId` (spec §7.4; RF-701/702/704; ADR-016), Etapa 5 — Trend central com predição (spec §7.4-6; §3; decisão A-11), Etapa 6 — F-3: vetores-golden Python→TS (spec §7.6; decisão A-9; F5R-13), Etapa 7 — Gate final da fase F5 (+5 more)

### Community 88 - "ValueHeartbeat"
Cohesion: 0.12
Nodes (12): Path, Redis, Heartbeat de valor da conexão; vive fora da sessão (spec §2.2-6)., Redis, TagConfig, Republicação periódica de valor por conexão (report-by-exception + heartbeat)., Cria a task do heartbeat e retorna já., Cancela a task. Idempotente. (+4 more)

### Community 89 - "ADR-011 — Hot-swap de flows sem interrupção; sem versionamento"
Cohesion: 0.13
Nodes (22): ADR-004 — Loops vivos em asyncio; sem Celery, Solver bloqueante via loop.run_in_executor, ADR-007 — Execução por scan cycle com Ts individual por flow, Scan cycle com Ts por flow (lista fixa 0.5–60 s), ADR-009 — Watchdog de comunicação por bit alternante (NOT cruzado), Watchdog por bit alternante (NOT cruzado), ADR-011 — Hot-swap de flows sem interrupção; sem versionamento, Hot-swap de flows sem versionamento (+14 more)

### Community 90 - "User"
Cohesion: 0.11
Nodes (35): HTTPException, User, BaseModel, Schemas de gestão de usuários (spec F1 §5.5): criação e atualização parcial., UserCreate, UserUpdate, hash_password(), _carregar() (+27 more)

### Community 91 - "Plano F4a — MPC: config & montagem"
Cohesion: 0.15
Nodes (20): Comandos canonicos (stack, gate E2E, precondicoes), Gate E2E de 3 camadas (L1 smoke, L2 pytest e2e, L3 browser), Proibicoes rapidas para agentes, TDD estrito em logica pura; malha fechada MPC<->TFS como aceite, Workflow Superpowers: um plano por fase F1..F6, Rodada de gate da F2 (L1 + L2 + L3 browser-tool), Rodada de gate da F3 (L2 = 24 cenários), Plano F4a — MPC: config & montagem (+12 more)

### Community 92 - "bus.py"
Cohesion: 0.06
Nodes (45): Contratos do barramento Redis pub/sub — payloads verbatim do PRD §7.1…, Logging estruturado JSON em stdout (RNF-07; spec F1 §7.1)., Bloco MPC: cadência, modos e write-back do runtime (spec F4…, Definição pronta para subir ou entrar em hot-swap, com o que o supervisor…, StagedDefinition, flow_origin(), mpc_block_origin(), publish_flow_deployed() (+37 more)

### Community 93 - "test_mpc_worker.py"
Cohesion: 0.23
Nodes (24): _config(), _cv(), _mv(), _par(), Connection, fixture, Contratos de `mpc.worker` — processo filho do MPC (spec F4 §3.3/§3.6/§4.9/§5.1;…, Mata + junta — sem processo órfão ao fim do teste (mesmo padrão de… (+16 more)

### Community 94 - "test_f4_failure.py"
Cohesion: 0.13
Nodes (22): armar_ate_remoto(), armar_auto_com_retentativa(), armar_remoto_direto(), criar_tag_leitura_dummy(), EstadoMpcStream, evento_mpc(), mpc_block_health(), Any (+14 more)

### Community 95 - "flow-runtime"
Cohesion: 0.21
Nodes (20): ADR-002 — Barramento interno via Redis pub/sub, Barramento interno Redis pub/sub, Postgres/TimescaleDB único, ADR-006 — Separação de processos: opc-worker × flow-runtime × recorder, flow-runtime, opc-worker, recorder, Deploy Docker Compose on-prem (+12 more)

### Community 96 - "compilerOptions"
Cohesion: 0.10
Nodes (19): compilerOptions, isolatedModules, jsx, lib, module, moduleResolution, noEmit, noFallthroughCasesInSwitch (+11 more)

### Community 97 - "_solve"
Cohesion: 0.14
Nodes (34): _build_runtime(), MpcConfig, Boot: monta o controller + o propagador + as funções de avaliação reutilizadas…, Um ciclo completo de execução (spec §3.3/§3.6/§4.9): estado, solve…, _solve(), _BackendQuebrado, _config(), MpcConfig (+26 more)

### Community 98 - "MpcWorker — processo dedicado por bloco MPC"
Cohesion: 0.13
Nodes (19): Invariante: nunca bloquear o event loop, Invariante: script block restrito a math+numpy com timeout ~70% do Ts, MpcHost (lado runtime do processo MPC), Decisao F3 #4: executor do Script = ProcessPool dedicado, E2E-F3-06: script busy-loop => script_timeout com saidas mantidas; excecao => script_error, RF-514: falhas de script (timeout/excecao), Bloco Python-Script, Evento script_error (+11 more)

### Community 99 - "ADR-013 — Modelo do MPC: matriz SOPDT + processo integrador; horizontes derivados do TSS"
Cohesion: 0.13
Nodes (19): ADR-005 — Canvas com React Flow; execução 100% no backend, Execução do grafo exclusivamente no backend, Canvas React Flow (@xyflow/react), ADR-008 — Configuração do MPC por formulário estruturado (modal com abas), Configuração do MPC por formulário com abas, sem código, Bumpless via tracking de MV (readback por MV), Hot-swap de flows entre varreduras, ADR-013 — Modelo do MPC: matriz SOPDT + processo integrador; horizontes derivados do TSS (+11 more)

### Community 100 - "build_mpc(config, ts_flow) -> BuiltMpc"
Cohesion: 0.12
Nodes (19): build_mpc(config, ts_flow) -> BuiltMpc, BuiltMpc (controller do-mpc pronto + indices de var), Etapa 2 do F4a: montagem do-mpc (biblioteca pura, TDD), init_bumpless(built, u_now, y_now, d_now), SolveRequest (dataclass picklavel), SolveResult (dataclass picklavel), worker_main(conn, config_json, ts_flow), Realimentacao por bias (DMC) (+11 more)

### Community 101 - "devDependencies"
Cohesion: 0.11
Nodes (19): devDependencies, openapi-typescript, @playwright/test, tailwindcss, @tailwindcss/vite, @types/react, @types/react-dom, typescript (+11 more)

### Community 102 - "ottima_flow_runtime/state.py"
Cohesion: 0.07
Nodes (25): RuntimeState, FlowMetrics, FlowSnapshot, _iso_utc(), Any, datetime, Protocol, Snapshot em memória dos flows; fonte única do `/health` (spec F3 §2.2-10,… (+17 more)

### Community 103 - "dependencies"
Cohesion: 0.11
Nodes (19): class-variance-authority, clsx, @fontsource/ibm-plex-mono, @fontsource/plus-jakarta-sans, @fontsource/sora, dependencies, class-variance-authority, clsx (+11 more)

### Community 104 - "Log de eventos persistido"
Cohesion: 0.16
Nodes (17): ADR-003 — Postgres/TimescaleDB único, retenção de 1 mês, Continuous aggregates para trends, Retenção nativa de 1 mês, ADR-009 — Watchdog de comunicação por bit alternante (NOT cruzado), Failsafe: parar de escrever MVs em falha de comunicação, Watchdog por bit alternante (NOT cruzado), Política de overrun do solver, ADR-016 — Tela de operação: faceplate + tendência com predição do MPC (+9 more)

### Community 105 - "Plano F6c — Suíte RNF-09, cenários de portabilidade e guia de implantação"
Cohesion: 0.17
Nodes (11): Aderência ao aceite F6 (PRD §8) — Definition of Done da FASE, Etapa 1 — Marcador `rnf09` e composição da suíte (spec §7-1/4; ADR-022), Etapa 2 — Cenários de portabilidade (spec §9.2-L2: E2E-F6-01/02/03), Etapa 3 — RNF-09: prova de dinâmica pela malha TFS (spec §7-2/3/5; decisão A-8 revista), Etapa 4 — Ambiente L3 e roteiro de browser (spec §9.2-L3), Etapa 5 — Guia de implantação e comissionamento (spec §8; PRD §9-5; decisão A-12), Etapa 6 — Gate final da fase F6 (spec §9.2/§9.3), Interfaces consumidas (produzidas no F6a/F6b — não redefinir) (+3 more)

### Community 106 - "Derivacao de horizontes Ts_mpc/Np/Nc (funcao pura)"
Cohesion: 0.13
Nodes (16): derive_horizons(multiplier, ts_flow, tss) -> Horizons, discretize_iopdt(Ki, theta, ts) -> PairSS, discretize_sopdt(K, tau1, tau2, theta, ts) -> PairSS, mpc_state_dimension(config, ts_mpc) -> int, Teste de carga slow (RNF-02), Setup E2E: projeto -> opcsim -> tags do pid -> flow MPC+TFS, B-F4-03: horizontes ao vivo e Resumo bloqueando/liberando o salvar, RF-522: discretizacao ZOH do TFS no Ts do flow (+8 more)

### Community 107 - "test_script.py"
Cohesion: 0.05
Nodes (49): ScriptBlock, bloco(), bus(), eventos(), pool(), processo_vivo(), fixture, PubSub (+41 more)

### Community 108 - "set_mv"
Cohesion: 0.25
Nodes (19): BlockId, _cv_do_bloco(), _mpc_config(), _mv_do_bloco(), _publicar_comando(), AsyncSession, FlowId, HTTPException (+11 more)

### Community 109 - "MpcBlock (blocks/mpc.py)"
Cohesion: 0.20
Nodes (15): Invariante: seguranca de processo (watchdog, modos, boot parado), Etapa 3 do F4a: API aceita MPC + ponte de deploy, Ponte F4a: deploy de flow com mpc => deploy_rejected(mpc_not_ready), MpcBlock (blocks/mpc.py), Evento deploy_rejected, Decisao A-13: emendas da spec F3 aplicadas antes desta spec, Decisao A-4: modos/SP/MV manual volateis + tracking, E2E-F4-03: armar LOCAL->REMOTO(MAN)->AUTO sem salto (+7 more)

### Community 110 - "ADR-012 — Projeto como unidade de agrupamento e portabilidade (JSON)"
Cohesion: 0.18
Nodes (15): ADR-007 — Execução por scan cycle com Ts individual por flow, Execução por scan cycle (semântica PLC), ADR-011 — Hot-swap de flows sem interrupção; sem versionamento, Sem versionamento de flows, ADR-012 — Projeto como unidade de agrupamento e portabilidade (JSON), Export/import de projeto em JSON, Projeto como unidade de agrupamento, schema_version do JSON de projeto (+7 more)

### Community 111 - "Semantica de invalidez: executa com o valor e propaga flag"
Cohesion: 0.16
Nodes (15): Cold start: entrada null => bloco nao executa, Decisao F3 #6: invalidez propaga + suprime escrita, E2E-F3-02: deploy Read->Script->Write altera espelho R do opcsim; flow_deployed; running, E2E-F3-10: script em erro desde a 1a varredura => saidas null => write_suppressed, Semantica de invalidez: executa com o valor e propaga flag, Bloco OPC-Read, Bloco OPC-Write, RF-501: bloco OPC-Read (+7 more)

### Community 112 - "index.tsx"
Cohesion: 0.08
Nodes (36): DESCRICAO, FlowPalette(), MIME_BLOCO, Props, NoFirstOrder, NoKalman, NoMpc, NoTfs (+28 more)

### Community 113 - "api/tests/test_events.py"
Cohesion: 0.32
Nodes (14): _evento(), _inserir(), Any, Consulta do log de eventos (RF-803): ordenação, filtros, limites e papéis…, test_filtro_origin_e_exato(), test_filtro_severity(), test_filtros_combinados(), test_janela_inclusiva_nos_dois_extremos() (+6 more)

### Community 114 - "MCP Tools: code-review-graph"
Cohesion: 0.40
Nodes (4): Key Tools, MCP Tools: code-review-graph, When to use graph tools FIRST, Workflow

### Community 115 - "ADR-001…024 (decisões de arquitetura normativas)"
Cohesion: 0.14
Nodes (14): Override E2E (portas de teste publicadas em 127.0.0.1), Stack compose 'ottima' (7 serviços de produção), Módulo de certificados (core + API, layout /certs), ADR-001…024 (decisões de arquitetura normativas), Migrations Alembic como única fonte do schema, Auth JWT HS256 + Argon2id, TTL 12 h, sem refresh, Compose de 7 serviços + nginx same-origin (proxy /api e /ws), DDL completo (users, projects, opc_connections, tags, flows) (+6 more)

### Community 116 - "Supervisor (ciclo de vida dos FlowTasks)"
Cohesion: 0.12
Nodes (18): 8 constantes KIND_MPC_* em bus.py, Router /api/operate (routers/operate.py), Boot parado, E2E-F3-07: RF-207 — watchdog congelado => failed(comm_failure); nao volta sozinho; re-deploy manual, E2E-F3-08: project_activated para tudo; boot parado apesar de desired_state=running, Canal flow.commands, Evento flow_overrun, RF-101: project_activated encerra flows do projeto anterior (+10 more)

### Community 117 - "test_writes.py"
Cohesion: 0.13
Nodes (40): Config de `opc_read` e `opc_write` — idêntica; quem discrimina é…, TagConfig, Bancada, esperar_valor(), make_config(), of_kind(), publicar(), Any (+32 more)

### Community 118 - "test_api_e2e.py"
Cohesion: 0.30
Nodes (13): admin(), _ativo(), _garantir_sentinela(), _novo_nome(), Client, fixture, Camada L2 do gate E2E da F1 (docs/specs/F1-testes-e2e.md): API contra o compose…, A API não expõe "desativar" e excluir o ativo dá 409: um projeto sentinela… (+5 more)

### Community 119 - "test_mpc_load.py"
Cohesion: 0.22
Nodes (12): CaptureFixture, _config_2x2(), _cv(), _mv(), _pair(), _percentile(), Carga (RNF-02) — `make_step` de um MPC 2x2 (Np=60) dentro de 70% do Ts_mpc de…, Par SOPDT bem acima do limiar `Ts/10` (tau1=20.0, tau2=8.0 >> 0.5) — nunca… (+4 more)

### Community 120 - "ADR-010 — Modos LOCAL/REMOTO e MAN/AUTO com transferência bumpless"
Cohesion: 0.18
Nodes (13): ADR-001 — FastAPI all-in (abandono do Django), FastAPI all-in backend, RBAC trivial de 2 papéis (coluna role + dependências), ADR-010 — Modos LOCAL/REMOTO e MAN/AUTO com transferência bumpless, Modos LOCAL/REMOTO, Modos MAN/AUTO do MPC (sub-modo de REMOTO), ADR-015 — Papéis: admin e OPERADOR (rename de visualizador), Papel admin (+5 more)

### Community 121 - "ADR-014 — Orçamento de tempo do MPC e multiplicador de execução"
Cohesion: 0.21
Nodes (13): ADR-004 — Loops vivos em asyncio; sem Celery, Loops vivos como tasks asyncio, Solver CPU-bound via loop.run_in_executor, Isolamento de jitter por separação de processos, Ts por flow de lista fixa, Horizontes Np/Nc derivados do TSS, ADR-014 — Orçamento de tempo do MPC e multiplicador de execução, Multiplicador de execução por bloco MPC (+5 more)

### Community 122 - "ottima_core.flowgraph (validacao de grafo compartilhada)"
Cohesion: 0.15
Nodes (13): flowgraph.py no core (modelo tipado + validações), ottima_flow_runtime.definition (extracao do supervisor), Etapa 0 do F4a: debitos herdados (0.1..0.7), ottima_core.flowgraph como pacote (parse/validate), ottima_core.pubsub.ChannelListener, Decisao F3 #5: tipagem — Script bivalente, resto estrito, E2E-F3-01: CRUD + validacoes 422 (ciclo, exec_order duplicado, tag inexistente), ottima_core.flowgraph (validacao de grafo compartilhada) (+5 more)

### Community 123 - "fixtures.ts"
Cohesion: 0.10
Nodes (30): ADMIN, adminApi(), adminToken(), AmbienteE2E, criarAmbiente(), ensureOperator(), entrarNoShell(), fazerLogin() (+22 more)

### Community 124 - "ResumeOrchestrator"
Cohesion: 0.06
Nodes (26): Exception, Lock, EstadoMpcTransplante, Tira uma foto do estado transplantável (TD-006/TD-005) — cópias defensivas dos…, Aplica um snapshot (TD-006 hot-swap; TD-005 retomada pós `comm_restored`):…, Estado transplantável de um `MpcBlock` para hot-swap sem queda de modo (TD-006)…, _parse_e_validar(), async_sessionmaker (+18 more)

### Community 125 - "Semantica de exec_order e tabela de portas persistente"
Cohesion: 0.29
Nodes (8): Invariante: execucao estrita por exec_order crescente, E2E-F3-03: ACEITE jitter — Script+TFS a Ts=0,5 s, p95 do desvio de fronteira < 50 ms, E2E-F3-05: exec_order invertido => atraso deterministico de 1 varredura + warnings no save, Semantica de exec_order e tabela de portas persistente, RF-307: exec_order presente, unico, contiguo 1..N, RF-401: execucao em ordem de exec_order por varredura, FlowTask/scheduler com deadline absoluto, Aplicar-na-fronteira (determinismo RF-401)

### Community 126 - "conftest.py"
Cohesion: 0.26
Nodes (11): db_engine(), db_session(), migrated_database_url(), fixture, Fixtures compartilhadas (spec F1 §9): Timescale real via testcontainers,…, Transação externa + sessão em SAVEPOINT: commit dentro do teste não vaza (spec…, decode_responses=True é contrato da F2: todo consumidor recebe str, não bytes., redis_client() (+3 more)

### Community 127 - "Contrato de canais do barramento (PRD §7.1)"
Cohesion: 0.18
Nodes (12): Regra do Estado Publicado (comandado × confirmado), Regra da Plaqueta (rótulos caps + Archivo Narrow + tracking), Assinatura 'tinta que ainda não secou' (predição tracejada desvanecendo), Plano F2 — Aquisição, Plano F3 — Motor + canvas, Contrato de canais do barramento (PRD §7.1), Predição publicada em mpc.state.*, não persistida (RF-625, ADR-016), Vocabulário kind do canal events (match por kind, mensagens pt-BR) (+4 more)

### Community 128 - "definition.py"
Cohesion: 0.13
Nodes (26): Connection, build_definition(), _instantiate(), _instantiate_mpc(), _make_write_opc(), _mpc_pid_tag_ids(), _mv_direta_escreve_sem_watchdog(), _mv_ids_de_functional() (+18 more)

### Community 129 - "Serviço api (FastAPI, porta interna 8000)"
Cohesion: 0.29
Nodes (11): Serviço api (FastAPI, porta interna 8000), Serviço flow-runtime (porta interna 8002), Serviço frontend (nginx, única porta exposta), Serviço opc-worker (porta interna 8001), Serviço recorder (porta interna 8003), Serviço redis (barramento pub/sub, redis:7.4-alpine), Serviço timescaledb (timescale/timescaledb:2.17.2-pg17), Barramento (Redis pub/sub: opc.values.*, opc.writes) (+3 more)

### Community 130 - "generate-contracts.mjs"
Cohesion: 0.29
Nodes (10): ARQUIVO_SAIDA, interfaceDe(), interfacesWsPayloads(), main(), nomeDoRef(), RAIZ_REPO, rodarExportadorPython(), tabelaPortContracts() (+2 more)

### Community 131 - "ValueError"
Cohesion: 0.12
Nodes (15): model_validator, model_validator, field_validator, model_validator, Portas fixas do bloco `tfs` (spec §3.4): y1/y2, sem depender de outro campo., Chave de `output_eu` só existe se houver a porta correspondente (spec §4.1) —…, ConnectionCreate, _ConnectionFields (+7 more)

### Community 132 - "routers/history.py"
Cohesion: 0.16
Nodes (16): HistoryResponse, HistoryResponse, HistorySeries, BaseModel, Schema colunar do histórico (RF-802): formato consumido direto pelo uPlot no…, _as_utc(), _e_tag_id(), get_history() (+8 more)

### Community 133 - "Hot-swap (banco + dica, aplicacao atomica na fronteira)"
Cohesion: 0.31
Nodes (10): Invariante: hot-swap atomico entre varreduras, B-F4-06: hot-swap — editar config do MPC com flow rodando nao para o flow, Decisao F3 #7: transporte do hot-swap = banco + dica, E2E-F3-04: ACEITE hot-swap — PUT em flow rodando aplica em <=2xTs sem stop, estado TFS continuo, Hot-swap (banco + dica, aplicacao atomica na fronteira), RF-304: hot-swap na proxima varredura, Watermark backstop de 10 s, Decisao A-11: hot-swap de config MPC => worker novo + shed a LOCAL (+2 more)

### Community 134 - "RF-206/207 watchdog por conexão e política de falha"
Cohesion: 0.20
Nodes (10): Serviço opcsim (simulador OPC-UA de teste, Basic256Sha256), Watchdog (bit alternante com NOT cruzado, congelamento >10 s), Gate de escrita stateless (sessão up ∧ watchdog_alive), opcsim como member do workspace (dev-only), Task de watchdog (threshold injetável nos testes, 10 s fixo em produção), RNF-03 segurança de processo (escrita só com deploy + watchdog + REMOTO), RF-206/207 watchdog por conexão e política de falha, Gate de escrita stateless (sessão up ∧ watchdog_alive, sem latch) (+2 more)

### Community 135 - "PRD OttimaSystem v1.2 (requisitos, contratos, fases)"
Cohesion: 0.33
Nodes (10): Direção de design 'Console OttimaSystem', Glossário OttimaSystem (vocabulário do domínio fixado), PRD OttimaSystem v1.2 (requisitos, contratos, fases), Índice da documentação do projeto (PRD, GLOSSARY, ADRs), Spec F1 — Fundação, Spec F1 — Testes E2E (gate de conclusão da fase), Paleta de penas --pen-1..6 (OKLCH, ≤6 séries), Plano de implementação F1 (superpowers, task-by-task) (+2 more)

### Community 136 - "PRD §4 domain model: User, Project, OpcConnection, Tag, Flow, Block/Edge in graph_json, Event and Sample hypertables"
Cohesion: 0.24
Nodes (10): ADR-003 — Postgres/TimescaleDB único, retenção de 1 mês, Decision: single Postgres+TimescaleDB — relational tables + hypertable, native 1-month retention, continuous aggregates, ADR-005 — Canvas com React Flow; execução 100% no backend, Decision: React Flow editor, graph serialized as JSON in Postgres; frontend only edits, execution exclusively in flow-runtime, ADR-020 — Log de eventos persistido, banner de alarmes, sem ACK, Decision: persisted event log (hypertable, 1-month retention; ts/severity/origin/message/payload), active-alarm banner derived from current state, no ACK; realtime fanout via events channel, Reference stack: React+Vite+shadcn+React Flow+uPlot, FastAPI+SQLAlchemy 2.0 async, Postgres/TimescaleDB, Redis pub/sub, uv, Docker Compose, Log de eventos: event hypertable (info/warning/alarm), 1-month retention, feeds no-ACK alarm banner and audit (+2 more)

### Community 137 - "CLAUDE.md (archived) — OttimaSystem agent operating rules"
Cohesion: 0.27
Nodes (10): ADR-004 — Loops vivos em asyncio; sem Celery, Decision: MPC/scripts/OPC sessions as asyncio tasks in dedicated workers; Celery out; blocking solve via run_in_executor, ADR-006 — Separação de processos: opc-worker × flow-runtime × recorder, Decision: distinct asyncio processes (opc-worker sole OPC-UA talker, flow-runtime executes flows, recorder writes hypertable) connected only by the bus, CLAUDE.md (archived) — OttimaSystem agent operating rules, ADRs 001-023 are normative; ADR wins any conflict, Invariant: never block the asyncio event loop, Invariant: opc-worker is the only process that speaks OPC-UA (+2 more)

### Community 138 - "RBAC com papéis admin e operador"
Cohesion: 0.24
Nodes (10): ADR-001 — FastAPI all-in (abandono do Django), FastAPI all-in (API + WebSocket + workers async), SQLAlchemy 2.0 async, ADR-010 — Modos LOCAL/REMOTO e MAN/AUTO com transferência bumpless, Modos LOCAL/REMOTO + MAN/AUTO com bumpless, ADR-015 — Papéis: admin e OPERADOR (rename de visualizador), RBAC com papéis admin e operador, ADR-016 — Tela de operação: faceplate + tendência com predição do MPC (+2 more)

### Community 139 - "Canal mpc.state.<flow_id>.<block_id>"
Cohesion: 0.11
Nodes (19): Invariante: barramento limitado aos canais do PRD 7.1, fire-and-forget, Invariante: predicoes do MPC nao sao persistidas, MpcState (bus.py; refina o stub F3), MpcVarState{v, sp?}, ottima_core.pubsub.PatternListener, Etapa 4 do F4b: integracao L2 (malha fechada MPC<->TFS via API real), WS /ws fanout mpc_state (implementacao), O que o roteiro L3 NAO cobre (+11 more)

### Community 140 - "build_contracts"
Cohesion: 0.31
Nodes (10): build_contracts(), main(), Monta o payload completo (porta + WS) — puro, sem I/O., test_json_tem_os_5_tipos_de_bloco(), test_main_imprime_json_valido_com_as_duas_secoes(), test_saida_e_deterministica_entre_execucoes(), test_schemas_ws_presentes(), test_script_e_mpc_sao_regras_dinamicas_com_source() (+2 more)

### Community 141 - "Decision: two mode axes — LOCAL/REMOTO (PID vs MPC, bumpless both ways via PID mode writes AUTO<->RCAS/CAS/ROUT) and MAN/AUTO sub-mode of REMOTO; MV tracking in LOCAL"
Cohesion: 0.22
Nodes (9): ADR-001 — FastAPI all-in (abandono do Django na reescrita), Decision: rewrite with FastAPI all-in + SQLAlchemy 2.0 async, no Django, ADR-010 — Modos LOCAL/REMOTO e MAN/AUTO com transferência bumpless, Decision: two mode axes — LOCAL/REMOTO (PID vs MPC, bumpless both ways via PID mode writes AUTO<->RCAS/CAS/ROUT) and MAN/AUTO sub-mode of REMOTO; MV tracking in LOCAL, ADR-015 — Papéis: admin e OPERADOR (rename de visualizador), Decision: two roles — admin (engineering + all operation) and operador (modes, SP, MV in MAN; sees everything; no engineering edits), Bumpless: control transfer without MV jump; MPC initializes at current MVs, PID does SP/OUT-tracking, MV tracking: in LOCAL the MPC MV output follows the PID readback tag for bumpless LOCAL->REMOTO (+1 more)

### Community 142 - "Decision: Redis pub/sub internal bus (opc.values.<conn_id> out, opc.writes in)"
Cohesion: 0.22
Nodes (9): ADR-002 — Barramento interno via Redis pub/sub, Decision: Redis pub/sub internal bus (opc.values.<conn_id> out, opc.writes in), ADR-016 — Tela de operação: faceplate + tendência com predição do MPC, Decision: per-MPC operation screen — main faceplate (modes/status/commands), small faceplates per variable, central uPlot trend with prediction overlay from now; predictions published on mpc.state.* and never persisted, Invariant: pub/sub is fire-and-forget; UI reflects published state, never command echo, Barramento: internal Redis pub/sub — opc.values.* (reads) and opc.writes (write commands), Faceplate: operation panel of an element — main (modes/status/commands) and small (one variable each), Predicao: future PV/MV trajectory from the last solve, published on mpc.state.*, never persisted (+1 more)

### Community 143 - "Decision: per-pair model matrix (MV->CV, DV->CV); response type per CV — self-regulating SOPDT(K,t1,t2,th) or integrating (Ki,th); Np/Nc derived from TSS, not user-edited; hard MV limits and rate limit"
Cohesion: 0.22
Nodes (9): ADR-008 — Configuração do MPC por formulário estruturado (modal com abas), Decision: full no-code form — double-click on MPC block opens tabbed config modal; system assembles do-mpc model internally, ADR-013 — Modelo do MPC: matriz SOPDT + processo integrador; horizontes derivados do TSS, Decision: per-pair model matrix (MV->CV, DV->CV); response type per CV — self-regulating SOPDT(K,t1,t2,th) or integrating (Ki,th); Np/Nc derived from TSS, not user-edited; hard MV limits and rate limit, ADR-019 — Categorias de variáveis do MPC: CV com SP, Restrição por faixa (com precedência), Decision: four variable categories — MV (hard limits, Du max), CV (setpoint tracking), Restricao (low/high band, precedence over CVs), DV (feedforward); model matrix rows = CVs+Restricoes, columns = MVs+DVs, Restricao: MPC variable controlled within a low/high band, no SP, with precedence over CVs (soft constraint, dominant slack penalty), SOPDT: second-order plus dead time model (K, tau1, tau2, theta) per MV->CV / DV->CV pair (+1 more)

### Community 144 - "PRD.md (archived) — OttimaSystem product requirements v1.0"
Cohesion: 0.31
Nodes (9): ADR-012 — Projeto como unidade de agrupamento e portabilidade (JSON), Decision: Project groups flows + system configs; exportable/importable as JSON with schema_version, never historical data, ADR-021 — Segurança OPC-UA: anônimo, usuário/senha e certificado desde a v1, Decision: per-connection security — None / Basic256Sha256 Sign / SignAndEncrypt; anonymous, user/password or X.509 certificate auth, all from v1; instance certificate management, ADR-023 — Escopo de plataforma da v1: pt-BR, auth local, HTTP interno, Compose on-prem, Decision: pt-BR-only UI, local user/password auth (Argon2/bcrypt + JWT), plain HTTP on plant network, Docker Compose on a single on-prem Linux host, PRD.md (archived) — OttimaSystem product requirements v1.0, PRD §7.2 project JSON export/import contract with schema_version, no secrets, no history (+1 more)

### Community 145 - "tfs.py"
Cohesion: 0.08
Nodes (13): _Element, _FirstOrder, _Iopdt, Block, PortSample, Bloco TFS: matriz 2x2 de funções de transferência (RF-521/522, ADR-022, spec F3…, Entradas `u1,u2`; saídas `y1,y2`. `matrix[J][K]` = contribuição de `uK` para…, Estágio de 1a ordem exato no ZOH: `x <- a*x + (1-a)*u`. Abaixo de… (+5 more)

### Community 146 - "_DropOldestBuffer"
Cohesion: 0.15
Nodes (10): async_sessionmaker, AsyncSession, _DropOldestBuffer, Any, Redis, Grava o conteúdo atual do buffer e só então o remove de lá., INSERT multi-linha, fatiado no teto de binds do asyncpg; nunca um INSERT por…, Buffer com teto: cheio, o mais antigo sai e o descarte é contado (spec §6.4). (+2 more)

### Community 147 - "ottima_flow_runtime/main.py"
Cohesion: 0.18
Nodes (16): ChannelListener, FastAPI, build_event_listener(), Assinante do canal `events` com os `kind` que o runtime consome (§2.2-8; TD-005…, check_database(), check_redis(), health(), _heartbeat_loop() (+8 more)

### Community 148 - "scripts"
Cohesion: 0.22
Nodes (9): scripts, build, dev, e2e, generate:api, generate:contracts, preview, test:unit (+1 more)

### Community 149 - "test_ssto_solver.py"
Cohesion: 0.11
Nodes (24): get_backend(), HiGHSBackend, LP por `scipy.optimize.linprog(method="highs")` — backend default (ADR-027 §7)., Resolve o backend por nome (`EconomicsConfig.solver`). `osqp` é registrado por…, test_registro_resolve_osqp_por_nome(), Mesa de casos dos backends de solver do SSTO (ADR-027 §7). Cobre o **caso…, LP não resolve QP: o detuning (ADR-027 §8) exige backend QP — falhar alto é…, A interface é `Protocol` runtime-checkable: o registro aceita qualquer backend… (+16 more)

### Community 150 - "errors_of"
Cohesion: 0.25
Nodes (11): base_tags(), errors_of(), Resolução do controlador 3: a bivalência é propriedade da porta do Script., test_grafo_de_referencia_sem_erros_nem_warnings(), test_grafo_em_ordem_nao_gera_warning(), test_read_booleano_em_entrada_de_script_e_aceito(), test_read_booleano_em_entrada_numerica_do_tfs_e_recusado(), test_read_numerico_em_write_booleano_e_recusado() (+3 more)

### Community 151 - "schemas/flows.py"
Cohesion: 0.29
Nodes (9): FlowCreate, FlowDetail, FlowOut, FlowSaved, FlowUpdate, BaseModel, Schemas de flows (RF-302/306/307): CRUD do diagrama de blocos e envelope do…, Linha da lista (spec §5.1): sem `graph_json`, que por flow pode ser grande. (+1 more)

### Community 152 - "Decision: solver timeout ~70% of effective Ts_mpc — on overrun keep last MV, raise alarm, skip to next scan; per-block multiplier N (Ts_mpc = N x Ts_flow)"
Cohesion: 0.29
Nodes (7): ADR-007 — Execução por scan cycle com Ts individual por flow, Decision: cyclic scan semantics; per-flow Ts from fixed list {0.5,1,2,5,10,30,60}s; blocks read latest bus snapshot, ADR-014 — Orçamento de tempo do MPC e multiplicador de execução, Decision: solver timeout ~70% of effective Ts_mpc — on overrun keep last MV, raise alarm, skip to next scan; per-block multiplier N (Ts_mpc = N x Ts_flow), Multiplicador: N such that the MPC block executes every N flow scans (Ts_mpc = N x Ts_flow), Scan cycle: every Ts all blocks evaluated in topological order with latest known values, PRD §9 risks and mitigations: IPOPT vs short Ts, dead-time state explosion, pub/sub delivery, hot-swap concurrency, PLC-dependent bumpless

### Community 153 - "Decision: per-connection watchdog with two OPC bits (read+write), crossed NOT, frozen >10s declares comm failure; failure stops writes and flows"
Cohesion: 0.33
Nodes (7): ADR-009 — Watchdog de comunicação por bit alternante (NOT cruzado), Decision: per-connection watchdog with two OPC bits (read+write), crossed NOT, frozen >10s declares comm failure; failure stops writes and flows, ADR-017 — Vários projetos armazenados, um ativo; boot em estado parado, Decision: N projects stored, exactly one active; on server boot all flows start stopped awaiting explicit deploy, Deploy: explicit act of putting a flow into execution; after boot all flows start stopped, Watchdog: alternating bit with crossed NOT between system and PLC; frozen >10s means comm failure, PRD RNF-03 process safety: no plant write without deployed flow + live watchdog + REMOTO; boot never resumes loops

### Community 154 - "Decision: fifth palette block TFS — transfer-function matrix up to 2x2, each element SOPDT or IOPDT, discrete-time at flow Ts, persistent internal state"
Cohesion: 0.33
Nodes (7): ADR-022 — Bloco TFS: simulação de processo por função de transferência, Decision: fifth palette block TFS — transfer-function matrix up to 2x2, each element SOPDT or IOPDT, discrete-time at flow Ts, persistent internal state, Strict TDD on pure logic; MPC<->TFS closed loop is the acceptance suite (RNF-09), IOPDT: integrating plus dead time model (Ki, theta) for integrating CVs/Restricoes and the TFS block, TFS: simulation block, transfer-function matrix up to 2x2, each element SOPDT or IOPDT, discrete time at flow Ts, PRD §8 implementation phases F1-F6 with acceptance criteria (F1 fundacao ... F6 portabilidade & hardening), PRD RNF-09 quality: closed-loop MPC<->TFS suite (no hardware) covering bumpless, constraint precedence, overrun, hot-swap

### Community 155 - "Matriz de modelos SOPDT/integrador com horizontes derivados do TSS"
Cohesion: 0.48
Nodes (7): ADR-008 — Configuração do MPC por formulário estruturado (modal com abas), do-mpc, Formulário MPC sem código (modal com abas), ADR-013 — Modelo do MPC: matriz SOPDT + integrador; horizontes derivados do TSS, Matriz de modelos SOPDT/integrador com horizontes derivados do TSS, ADR-019 — Categorias de variáveis do MPC: CV com SP, Restrição por faixa (com precedência), Quatro categorias de variáveis: MV, CV (SP), Restrição (faixa com precedência), DV

### Community 156 - "env.py"
Cohesion: 0.48
Nodes (6): do_run_migrations(), include_object(), Connection, run_async_migrations(), run_migrations_offline(), run_migrations_online()

### Community 157 - "cert_servidor"
Cohesion: 0.29
Nodes (7): cert_servidor(), certs_dir(), fixture, Mesmo diretório temporário que o app enxerga (conftest aponta certs_dir p/…, Statements UPDATE emitidos em `opc_connections` na sessão do teste. É o…, PEM e DER de um certificado real, gerado fora do certs_dir: faz papel do…, updates_na_conexao()

### Community 158 - "pipeline.py"
Cohesion: 0.09
Nodes (28): AsyncEngine, LogRecord, get_settings(), create_engine(), create_session_factory(), async_sessionmaker, AsyncSession, Engine e session factory assíncronas (SQLAlchemy 2.0 + asyncpg). (+20 more)

### Community 159 - "await_until"
Cohesion: 0.11
Nodes (28): Débito m3: uma SEGUNDA `CancelledError` chegando enquanto `run()` já está…, `stats()` é a fonte do futuro `/health` (F4b 2.3): `size` fixo, `busy` reflete…, test_dupla_cancelacao_durante_replace_nao_encolhe_o_pool(), test_stats_conta_respawns_e_reflete_ocupacao(), publish(), pubsub_client_ids(), datetime, fixture (+20 more)

### Community 160 - "Plano F5a — Operação: dados & serviços"
Cohesion: 0.15
Nodes (12): Aderência (DoD do plano F5a), Contratos verbatim (PRD §7.1 v1.3 — vigente após a tarefa 0.1), Etapa 0 — Emendas documentais e débitos de contrato (spec §1.3 e §4.3; antes de qualquer código de feature), Etapa 1 — Contratos: `ts` e `prediction.ts` (spec §2.1; F5R-01), Etapa 2 — Hypertable `mpc_samples` e recorder (spec §2.2/§2.3), Etapa 3 — APIs novas, WS `events` e `script_recovered` (spec §2.4/§4.1/§4.2/§5/§7.2-2), Etapa 4 — F-1: boot assíncrono do worker e reescopo do lock (spec §6; F5R-05/06), Etapa 5 — Integração L2 e fechamento do plano F5a (+4 more)

### Community 163 - "api/tests/test_tags.py"
Cohesion: 0.60
Nodes (5): _conexao(), test_cria_lista_filtra(), test_nome_duplicado_na_conexao_409(), test_patch_e_delete(), test_validacoes_e_papeis()

### Community 164 - "test_ssto_detuning.py"
Cohesion: 0.18
Nodes (16): _config(), _entrada(), ndarray, Caso obrigatório 5 do brief — LP flipping e detuning (ADR-027 §8). Montagem…, Sem detuning: 2e-6 de diferença de preço troca o vértice inteiro., O empate passa a ser resolvido pela proximidade do que já estava em vigor., Nem com peso alto o QP viola o limite duro (ADR-027 §5)., Fail fast: config inconsistente derruba a montagem, não o ciclo. (+8 more)

### Community 165 - "WSClient"
Cohesion: 0.13
Nodes (9): _payload_of(), Any, FastAPI, Tudo o que o cliente ainda tem para receber, até o cano secar., Volta quando o servidor consumiu o envio. O comando é aplicado sem nenhum…, Cliente WS in-process: fala ASGI direto, no mesmo event loop do teste. O…, Desconexão do lado do cliente, como um browser que fecha a aba., Trava o envio do servidor para este cliente (TCP cheio). (+1 more)

### Community 166 - "Continuous aggregate samples_1m (avg/min/max/count/worst_quality)"
Cohesion: 0.40
Nodes (5): Regra do Canal Redundante (severidade = cor + ícone + texto), Continuous aggregate (agregação materializada Timescale para trends), Continuous aggregate samples_1m (avg/min/max/count/worst_quality), GET /api/history (bruto ≤2 h, CAgg acima, resposta colunar), Trend de engenharia (uPlot re-vestido, polling 5 s, BAD = gap + rótulo)

### Community 167 - "Decision: live flow edits take effect on the next scan without interruption; no flow versioning"
Cohesion: 0.40
Nodes (5): ADR-011 — Hot-swap de flows sem interrupção; sem versionamento, Decision: live flow edits take effect on the next scan without interruption; no flow versioning, ADR-018 — Contrato do bloco Python-Script, Decision: user-defined ports (IN1..INn in, OUT1..OUTn assigned), persistent per-instance state dict, scope restricted to math+numpy, timeout ~70% of flow Ts, Hot-swap: live flow edit applied atomically on next scan, preserving unchanged block state

### Community 168 - "RF-401 scan cycle por exec_order com atraso determinístico de 1 scan"
Cohesion: 0.40
Nodes (5): Hot-swap (stage validado, troca atômica, preservação por block_id), Scheduler FlowTask com deadline absoluto e skip de overrun, RF-307 exec_order único 1..N por bloco (ADR-024), RF-304 hot-swap atômico na próxima varredura (ADR-011), RF-401 scan cycle por exec_order com atraso determinístico de 1 scan

### Community 169 - "script_pool: guarda do teto C2 + stats"
Cohesion: 0.50
Nodes (5): script_pool: guarda do teto C2 + stats(), /health com campos MPC e script_pool, B-F4-05: minors m4 (virgula/ponto, Aplicar fecha, booleano, EU nas portas, grade), Debito 5: ProcessPool invisivel no /health, Debitos menores m1/m3/m4 (UI e pool)

### Community 170 - "RNF-09 suíte de malha fechada MPC↔TFS"
Cohesion: 0.40
Nodes (5): RF-621..623 modos LOCAL/REMOTO, MAN/AUTO e bumpless, Bloco MPC (RF-601..625, do-mpc, SOPDT/IOPDT, TSS→Np/Nc), RNF-09 suíte de malha fechada MPC↔TFS, Bloco TFS de simulação (RF-521/522), tests/ recebe a suíte de malha fechada MPC↔TFS na F4 (RNF-09)

### Community 171 - "package.json"
Cohesion: 0.40
Nodes (4): name, private, type, version

### Community 172 - "ottima-core"
Cohesion: 0.40
Nodes (5): ottima-api, ottima-core, ottima-flow-runtime, ottima-opc-worker, ottima-recorder

### Community 173 - "test_auto_laco_e_ciclo"
Cohesion: 0.31
Nodes (9): link(), Aresta de um bloco para ele mesmo: o menor ciclo possível., A varredura precisa cobrir todos os componentes, não só o do primeiro nó., Milhares de nós encadeados: travessia iterativa, nunca RecursionError. Com…, script_node(), test_auto_laco_e_ciclo(), test_cadeia_profunda_nao_estoura_a_pilha(), test_ciclo_de_tres_nos_e_erro() (+1 more)

### Community 174 - "sim"
Cohesion: 0.40
Nodes (4): fixture, OpcSimServer, Fixtures compartilhadas dos testes do opc-worker. O helper de espera…, sim()

### Community 175 - "Minor"
Cohesion: 0.05
Nodes (36): Achados, Apêndice — claims verificados e confirmados, Claims normativos sem teste correspondente em §9, Conformidade por requisito, Critical, F5R-01 — A âncora da predição está adiantada exatamente 1×Ts_mpc, F5R-02 — A família TTL contradiz o produtor: o dedupe do runtime é latch de condição, não repetição periódica, F5R-03 — O bootstrap da faixa não enxerga nenhum evento de cessação (+28 more)

### Community 176 - "Retenção 1 mês + continuous aggregate (RF-801, ADR-003)"
Cohesion: 0.50
Nodes (4): Pipeline do recorder (flush 1 s ou 1000 linhas, drop-oldest 100k), Retenção 1 mês + continuous aggregate (RF-801, ADR-003), Hypertables samples/events + retention policies de 1 mês, Recorder dumb pipe (buffers separados, backpressure drop-oldest)

### Community 177 - "ottima_core.contracts_export"
Cohesion: 0.50
Nodes (4): ottima_core.contracts_export, generate-contracts.mjs -> contracts.gen.ts, Debito 2: contrato de porta em 3 lugares -> TS gerado do Pydantic, Debito 4: PortValue do WS declarado 2x (fora do OpenAPI)

### Community 179 - "Campo grafite (paleta neutra escura dessaturada)"
Cohesion: 0.67
Nodes (3): Campo grafite (paleta neutra escura dessaturada), Regra da Chapa (profundidade tonal + linha 1px, sem sombras), Tokens CSS OKLCH exatos (tokens.css, Tailwind v4 @theme)

### Community 180 - "Bumpless (transferência sem salto na MV)"
Cohesion: 0.67
Nodes (3): Bumpless (transferência sem salto na MV), LOCAL / REMOTO (eixo de modo do MPC), MV tracking (MV do MPC segue readback do PID em LOCAL)

### Community 181 - "Scan cycle (avaliação a cada Ts em ordem de exec_order)"
Cohesion: 0.67
Nodes (3): exec_order (inteiro único 1..N por bloco), Flow (grafo de blocos executado em scan cycle), Scan cycle (avaliação a cada Ts em ordem de exec_order)

### Community 182 - "TFS (bloco de simulação, matriz até 2×2 SOPDT/IOPDT)"
Cohesion: 0.67
Nodes (3): IOPDT (modelo integrador com tempo morto), SOPDT (modelo 2ª ordem com tempo morto), TFS (bloco de simulação, matriz até 2×2 SOPDT/IOPDT)

### Community 183 - "ADR-005 — Canvas com React Flow; execução 100% no backend"
Cohesion: 0.67
Nodes (3): ADR-005 — Canvas com React Flow; execução 100% no backend, Execução do grafo exclusivamente no backend, React Flow (@xyflow/react) canvas editor

### Community 184 - "ADR-023 — Escopo de plataforma da v1: pt-BR, auth local, HTTP interno, Compose on-prem"
Cohesion: 0.67
Nodes (3): ADR-023 — Escopo de plataforma da v1: pt-BR, auth local, HTTP interno, Compose on-prem, Docker Compose on-prem (deploy v1), Escopo de plataforma v1 (pt-BR, auth local Argon2/bcrypt+JWT, HTTP sem TLS)

### Community 185 - "Camadas L1/L1s/L2/L3 e 19 cenários do gate da F1"
Cohesion: 0.67
Nodes (3): deploy/smoke.sh (roteiro executável do aceite compose up), Camadas L1/L1s/L2/L3 e 19 cenários do gate da F1, Suíte L2 tests/e2e (marker e2e, contra stack compose real)

### Community 188 - "Collector"
Cohesion: 0.07
Nodes (50): OpcValue, Collector, create_tag(), Harness, mpc_graph_valido(), mpc_host_echo_plan_worker(), mpc_host_slow_solve_worker(), publish_tag_value() (+42 more)

### Community 190 - "ottima_opc_worker/connection.py"
Cohesion: 0.05
Nodes (47): DataChangeNotif, DataValue, RuntimeError, Runtime de uma conexão OPC-UA: máquina de estados, backoff e eventos (spec F2…, Tentativa de conexão invalidada por um fail() concorrente., _SupersededAttemptError, Heartbeat de valor de uma conexão: report-by-exception + republicação (spec F2…, ConnectionSnapshot (+39 more)

### Community 200 - "_avisos_watchdog"
Cohesion: 0.28
Nodes (9): _aviso_watchdog(), _avisos_watchdog(), _avisos_watchdog_mpc(), FlowGraph, FlowNode, MV com `pid` escreve pelas próprias tags do binding…, TD-004: um aviso por bloco que escreve numa conexão sem watchdog completo — o…, Parse + validação semântica + avisos de watchdog (TD-004) num passo só, para… (+1 more)

### Community 201 - "test_mpc_economics.py"
Cohesion: 0.13
Nodes (24): economics_config_hash(), SHA-256 da versão do problema econômico (ADR-027 §9): custos, limites e ranks.…, base_config(), _mpc_graph_node(), parametrize, Mesa de casos do bloco `economics` do `MpcConfig` (ADR-027 §9, RF-901/902). O…, Nó `mpc` mínimo do `graph_json` (spec F3 §2.1) — só a forma importa aqui., `economics` é chave prevista de `data` no bloco `mpc` — sem isto o parse… (+16 more)

### Community 202 - "conexoes_sem_watchdog"
Cohesion: 0.29
Nodes (6): conexoes_sem_watchdog(), AsyncSession, Consulta de conexões do projeto: compartilhada entre API e flow-runtime., `conn_id -> nome` das conexões do projeto sem watchdog completo (TD-004). Sem…, TD-004: falta um dos dois node_ids (ou os dois) já conta como sem watchdog; a…, test_traz_so_conexoes_do_projeto_sem_watchdog_completo()

### Community 203 - "test_parse_exige_matriz_2x2_no_tfs"
Cohesion: 0.50
Nodes (5): off(), Elemento SOPDT habilitado; `params` sobrescreve os defaults., Elemento SOPDT desabilitado (bem-formado, mas fora da soma da linha)., sopdt(), test_parse_exige_matriz_2x2_no_tfs()

### Community 215 - "ws.py"
Cohesion: 0.07
Nodes (28): _apply_client_message(), _authenticate(), _flow_id_of(), _flow_ids(), flow_status_ws(), FlowStatusHub, _mpc_id_of(), _mpc_ids() (+20 more)

### Community 257 - "test_stop_loga_desmonte_cancelado_por_fora"
Cohesion: 0.14
Nodes (11): CancellingRuntime, ExplodingRuntime, ConnectionConfig, LogCaptureFixture, Task, Tasks vivas do worker: nenhuma pode sobrar depois de um `stop()`., Dublê de runtime que falha ao parar (ex.: disconnect travado no transporte)., Dublê cujo `stop()` é cancelado por fora (task interna morta no meio). (+3 more)

### Community 271 - "FlowStatus"
Cohesion: 0.11
Nodes (18): FlowStatus, PortValue, Valor de uma porta de bloco numa varredura (spec F3 §4.2, decisão A-3)., Fonte única dos contratos de porta por bloco + payloads do WS, exportados como…, test_flow_status_aceita_ports_vazio_em_transicao_de_estado(), test_flow_status_com_ports_serializa_verbatim_spec_f3_42(), test_nomes_de_canais_prd_71(), test_payloads_verbatim_prd_71() (+10 more)

### Community 272 - "Settings"
Cohesion: 0.11
Nodes (25): BaseSettings, Configuração via variáveis OTTIMA_* (spec F1 §7.2)., Valida os segredos no boot: a chave de assinatura JWT é fatal, a Fernet é…, Settings, validate_secrets(), AppCertificateGenerateIn, AppCertificateGenerateOut, AppCertificateOut (+17 more)

### Community 273 - "Decisão"
Cohesion: 0.11
Nodes (17): 10. Integração com o MPC dinâmico e fallback, 11. Auditoria — sem canal de barramento novo, 1. Camada e localização, 2. Formulação, 3. G e Gd reutilizam o modelo existente — não há segundo modelo de ganho, 4. Linhas integradoras (`kind="integrating"`), 5. Mapeamento das categorias existentes (ADR-019 preservado), 6. Inviabilidade — duas linhas de defesa (+9 more)

### Community 274 - "runtime_test_helpers.py"
Cohesion: 0.15
Nodes (39): counters(), disabled_element(), edge(), graph(), node(), port_value(), Any, Helpers de teste do flow-runtime, importados por nome qualificado pelos… (+31 more)

### Community 277 - "test_td_flow_props.py"
Cohesion: 0.17
Nodes (15): StatusStream, assinar_status(), cadencia_mediana(), AmbienteMpc, Any, Client, fixture, OpcSim (+7 more)

### Community 278 - "OpcWrite"
Cohesion: 0.09
Nodes (36): MpcState, OpcWrite, BaseModel, Registro imutável de uma execução do SSTO (ADR-027 §11, RF-903). Viaja como…, Publicado em `mpc.state.<flow_id>.<block_id>` a cada execução (spec F4 §5.1,…, SstoRun, Escreve `mode_cmd` em toda MV com `pid` (com ou sem `mode_read` — a escrita em…, write_mode_cmd() (+28 more)

### Community 279 - "test_pipeline_ssto.py"
Cohesion: 0.15
Nodes (22): MpcModes, MpcPrediction, MpcVarState, Estado publicado de uma variável do MPC (spec F4 §5.1) — `sp` só existe em CV…, `ts` (UTC, spec F5 §2.1-2) é o instante da fronteira em que o solve que…, MpcState, _state(), pipeline() (+14 more)

### Community 281 - "setup_planta.py"
Cohesion: 0.23
Nodes (18): config_mpc(), criar_tags(), env_deploy(), ganho_recomendado(), login(), main(), montar_grafo(), montar_modelos() (+10 more)

### Community 284 - "schemas/projects.py"
Cohesion: 0.47
Nodes (5): ProjectCreate, ProjectOut, ProjectUpdate, BaseModel, Schemas de projetos (RF-101, ADR-017): criação, atualização parcial e saída.

### Community 285 - "schemas/events.py"
Cohesion: 0.40
Nodes (4): EventOut, BaseModel, Schema de leitura do log de eventos (RF-803): as mesmas 5 chaves do canal…, Schemas Pydantic compartilhados entre a API e os workers.

### Community 286 - "ADR-025 — Retomada automática completa após `comm_restored`"
Cohesion: 0.40
Nodes (4): ADR-025 — Retomada automática completa após `comm_restored`, Consequências, Contexto, Decisão

### Community 287 - "planta_virtual/supervisor_mpc.py"
Cohesion: 0.31
Nodes (16): agora(), alvos(), aplicar_sp(), armar(), _env(), estado_bloco(), flow_id(), log() (+8 more)

### Community 288 - "build_mpc"
Cohesion: 0.16
Nodes (19): build_mpc(), BuiltMpc, PairInit, Montagem do-mpc do bloco MPC (spec F4 §3.2-3.5; TDD estrito). `build_mpc` monta…, Monta o `do_mpc.controller.MPC` do bloco (spec F4 §3.2-3.5)., Metadados de um par HABILITADO para `init_bumpless` (spec F4 §3.6, tarefa 2.3).…, Controller do-mpc pronto + metadados de índice para o worker (spec F4 §3,…, init_bumpless() (+11 more)

### Community 290 - "test_f4_ws.py"
Cohesion: 0.20
Nodes (15): _config_mpc_leve(), _grafo_hot_swap(), AmbienteMpc, Any, Client, EventStream, OpcSim, rnf09 (+7 more)

### Community 291 - "FakeClock"
Cohesion: 0.19
Nodes (16): FakeClock, datetime, Mudança de modo publica fora da fronteira (spec F4 §5.2): `ts` é o instante da…, Fora de AUTO, `prediction` é vazia e ancorada no PRÓPRIO `ts` do quadro — nunca…, `prediction.ts` é a fronteira em que `host.dispatch()` foi chamado — nunca o…, `host.dispatch()` recusando (worker ocupado/morto, spec §3.5) não pode mover a…, Clock controlado (spec F5 §2.1, tarefa 1.2): cada chamada devolve o próximo…, Como `_resultado_ok`, mas com `prediction_mv` populado — os testes de ts… (+8 more)

### Community 293 - "plant_ops.py"
Cohesion: 0.42
Nodes (8): caminhos(), chamar_metodo(), _com_cliente(), escrever(), _formatar(), main(), Todos os nos de processo lidos pelo `snapshot`, na ordem de exibicao., snapshot()

### Community 294 - "All Reports by Category"
Cohesion: 0.08
Nodes (23): Active (Last 3 Days), All Reports by Category, Analysis, Architecture, Archive, Bugs, CI, Commits (+15 more)

### Community 295 - "test_bus_ssto.py"
Cohesion: 0.22
Nodes (12): gain_model_hash(), SHA-256 da matriz `models` — a "referência ao modelo de ganho usado" da…, _config(), SstoRun, Contrato de auditoria do SSTO no barramento (ADR-027 §11). Decisão normativa…, "Referência ao modelo de ganho usado" (ADR-027 §11): o hash da matriz `models`,…, _run(), test_gain_model_hash_e_estavel() (+4 more)

### Community 296 - "schemas/auth.py"
Cohesion: 0.38
Nodes (6): LoginIn, LoginOut, BaseModel, Schemas de autenticação (spec F1 §5.1): entrada de login e saída de…, Usuário exposto pela API — nunca inclui password_hash., UserOut

### Community 298 - "_propaga"
Cohesion: 0.28
Nodes (9): _propaga(), DM, Propaga o modelo agregado em malha aberta a partir do repouso, com entradas…, Saída agregada da linha avaliada num `x` arbitrário, com bias zerado (`tvp`…, O par IOPDT é incremental — `dy/dt = Ki·(u − u_op)`. Com a MV parada no ponto…, Mesma regra da MV para a coluna de distúrbio: a DV entra no modelo em desvio do…, test_coluna_dv_parada_no_ponto_de_operacao_nao_deriva_a_linha_integradora(), test_coluna_mv_parada_no_ponto_de_operacao_nao_deriva_a_linha_integradora() (+1 more)

### Community 299 - "SolveResult"
Cohesion: 0.08
Nodes (37): DM, DMStruct, _aplicar_banda_morta(), _apply_tvp(), _audit_record(), _clamp_frozen(), _current_bias(), _effective_sp() (+29 more)

### Community 309 - "test_timescale_ssto.py"
Cohesion: 0.18
Nodes (5): Hypertable `ssto_runs` — auditoria imutável do SSTO (ADR-027 §11, migration…, Downgrade simétrico da 0004. Síncrono de propósito: `alembic.command` chama…, Round-trip dos vetores em JSONB: o registro tem de voltar do banco idêntico ao…, test_downgrade_remove_ssto_runs(), test_grava_e_le_um_registro_completo()

### Community 314 - "Bloco 2 — Critical resolvíveis por reescrita da spec"
Cohesion: 0.10
Nodes (20): Bloco 1 — Exige decisão do dono do produto (CLAUDE.md item 4), Bloco 2 — Critical resolvíveis por reescrita da spec, Bloco 3 — Important (34), Bloco 4 — Minor (21), F6R-01 — A decisão A-8 está tecnicamente bloqueada [Critical], F6R-02 — §3.1-3 amplia RF-102 sem emenda, e o aceite depende da ampliação [Critical], F6R-03 — Import quebra a premissa de confiança do ADR-018 [Critical → reclassificado de SEC-01 Important], F6R-04 — A exclusão do campo `service` dos logs se apoia em premissa falsa [Important] (+12 more)

### Community 323 - "Achados"
Cohesion: 0.10
Nodes (19): Achados, Revisão da spec F6 — coerência normativa, escopo e aderência ao aceite, RFC-01 — A camada 2 do import reprova o próprio bundle normativo da spec [Critical], RFC-02 — E2E-F6-04 é inexecutável e contradiz o próprio §1.2 [Critical], RFC-03 — §3.1-3 amplia RF-102 sem emenda, e o aceite depende dessa ampliação [Critical], RFC-04 — O modelo de pendências é cego ao estado da instalação; `auth_mode = certificate` não gera pendência nenhuma [Critical], RFC-05 — A emenda ao PRD §7.2 (§1.3-1) não lista tudo que muda [Important], RFC-06 — `opc.values` vira "nunca" sem emendar o PRD §7.1 e §7.3 [Important] (+11 more)

### Community 325 - "test_e2e_td_08_predicao_tem_np_mais_um_ponto_e_parte_do_u_prev"
Cohesion: 0.26
Nodes (13): _horizontes_do_bloco(), AmbienteMpc, Any, Client, OpcSim, L2 F5a (spec F5 §9.2, tarefa 5.1): concorrência, building, prediction_ts.…, E2E-F5-06: ts monotônico; prediction_ts presente; em regime: ≈ ts − Ts_mpc. (b)…, `horizons` da projeção `/api/operate/mpcs`. O servidor é a fonte: a projeção… (+5 more)

### Community 326 - "test_e2e_td_06_salvar_avisa_e_armar_e_recusado"
Cohesion: 0.23
Nodes (13): conexao_sem_watchdog(), criar_flow_sem_watchdog(), grafo_mv_direta(), Any, Client, EventStream, fixture, L2 do fechamento de tech debts — conexão sem watchdog é somente leitura… (+5 more)

### Community 327 - "Connection"
Cohesion: 0.33
Nodes (6): mpc_host_ok_result(), mpc_host_reinit_capturing_worker(), mpc_host_slow_build_worker(), Connection, Ecoa `request.reinit` no campo `detail` da resposta — prova o que o host…, Atraso real e finito (`MPC_SLOW_BUILD_DELAY_S`) antes do handshake `("ready",…

### Community 328 - "test_e2e_f6_05_overrun_pela_malha_tfs"
Cohesion: 0.24
Nodes (11): AmbienteMpc, Any, Client, EventStream, OpcSim, rnf09, Camada L2 da F6c (spec F6 §7): suíte RNF-09, cenários de dinâmica pela malha…, E2E-F6-06 (RNF-09, spec §7-3, ADR-011): Flow MPC↔TFS rodando em AUTO. Muda a… (+3 more)

### Community 330 - "StatusStream"
Cohesion: 0.24
Nodes (5): PubSub, Assinatura de `flow.status.<flow_id>` aberta ANTES do gatilho (estilo do…, Amostras consecutivas, sem lacuna: coleta por mensagem recebida, nunca por…, Tudo o que chegou na janela; lista vazia é a prova de que o flow não está…, StatusStream

### Community 331 - "ottima_core/tags.py"
Cohesion: 0.29
Nodes (6): project_tags(), AsyncSession, Consulta de tags do projeto: compartilhada entre API e flow-runtime., Tags visíveis ao flow: as do projeto dele, via conexão (o `graph_json` não tem…, Duas conexões, dois projetos: `project_tags` não pode vazar tag de outro…, test_so_traz_tags_das_conexoes_do_projeto()

### Community 333 - "Achados"
Cohesion: 0.11
Nodes (17): Achados, FACT-01 — OperateSelectorPage.tsx:48 não contém a mensagem citada [Important], FACT-02 — flows.py:55 é a constante errada para "projeto inexistente" [Important], FACT-03 — stop_host_background não remove o host do mapa [Critical], FACT-04 — projects.py:77-108 corta a função 4 linhas antes do fim [Minor], FACT-05 — opc-worker/main.py:108-135 estende 7 linhas além do fim [Minor], FACT-06 — docker-compose.yml:43-48 aponta para depends_on, não healthcheck [Minor], FACT-07 — models/tag.py:29 não é o campo eu [Minor] (+9 more)

### Community 334 - "trendOperacao.check.ts"
Cohesion: 0.27
Nodes (9): amostraViva(), carimbo(), historico(), Ponto, TOKENS_CSS, valorToken(), chaveHistoricoOperacao(), useHistoryMpc() (+1 more)

### Community 337 - "test_kind_fora_de_hint_kinds_nao_dispara_reconcile"
Cohesion: 0.24
Nodes (11): Contador, contar_mensagens_vistas(), contar_passadas(), publicar_dica(), MonkeyPatch, Contador observável, para provar (ou negar) um efeito sem esperar tempo., Conta passadas de reconciliação CONCLUÍDAS, inclusive as que saem no watermark.…, Conta mensagens do canal já classificadas pelo assinante. (+3 more)

### Community 338 - "schemas/tags.py"
Cohesion: 0.47
Nodes (5): BaseModel, Schemas de tags OPC (RF-203): nome lógico, node_id, direção, tipo, EU e…, TagCreate, TagOut, TagUpdate

### Community 339 - "Achados"
Cohesion: 0.12
Nodes (15): Achados, Revisão da spec F6 — conformidade com DESIGN.md/PRODUCT.md e arquitetura de informação, UX-01 — Lâmpada âmbar de pendência de segredo colide com a Regra da Cor Anormal no cenário que a própria fase testa [Important], UX-02 — `application_uri` como plaqueta contradiz o tratamento que DESIGN.md já dá a identificadores técnicos equivalentes [Important], UX-03 — Estado de erro do certificado ilegível e o aviso de re-trust não têm tratamento de canal redundante especificado [Important], UX-04 — Certificado de instalação na página de Conexões (decisão A-7) não tem mitigação visual de escopo especificada [Important], UX-05 — Fluxo de import não mostra prévia antes de criar; o engenheiro comita às cegas [Important], UX-06 — `detail` de import com até 10 problemas concatenados numa string não tem tratamento de apresentação; um split ingênuo por `;` quebra em dados reais [Important] (+7 more)

### Community 341 - "SteadyStateOptimizer"
Cohesion: 0.10
Nodes (20): ndarray, QuadraticTerm, MpcConfig, SolverResult, SSTO: montagem e resolução do LP de alvos de regime permanente (ADR-027…, Otimizador de alvos de um bloco MPC (ADR-027 §2). Instância longa: monta…, Variáveis de decisão do LP — só MVs, sempre (ADR-027 §5)., `c = c_mv + Σ_i c_row_i · G_i` (ADR-027 §9). Preço de linha é projetado no… (+12 more)

### Community 352 - "Achados"
Cohesion: 0.14
Nodes (13): Achados, API-01 — Reuso de `ConnectionCreate._coerencia` reprova todo bundle com `auth_mode: user_password` [Critical], API-02 — Todo `*Create` reusado na camada 2 exige o id do pai, que o bundle não carrega e que não existe antes do insert [Important], API-03 — `Flow.desired_state` do bundle não passa por nenhum schema Pydantic; só o CHECK do banco o protege [Critical], API-04 — `GET /api/health` da API não herda o mecanismo de heartbeat dos outros três serviços; a spec só especifica o formato JSON [Critical], API-05 — Ordem camada 3 / camada 4 para `tag_ref`: a spec descreve a tradução como pós-flush mas classifica a falha como camada 3; os modelos de `parse.py` não aceitam `tag_ref` [Important], API-06 — Teto de 4 MiB não é aplicável a um corpo JSON tipado sem abrir mão da amarração automática do FastAPI [Important], API-07 — Predicado de `pending_secrets` (§3.2-7) não é o mesmo de §6.3-1, apesar da spec afirmar que é [Important] (+5 more)

### Community 353 - "Achados"
Cohesion: 0.14
Nodes (13): Achados, Resposta obrigatória — Eixo 1: E2E-F6-02 é falso-verde por coincidência de id?, Revisão da spec F6 — o plano de testes prova o que promete?, TST-01 — E2E-F6-02 nunca testa desambiguação por conexão, o caso que motivou `tag_ref` ser objeto [Important], TST-02 — Overrun: "`grafo_mpc_tfs` com o mesmo config pesado" é irrealizável como está escrito [Critical], TST-03 — Hot-swap: reescrita para `grafo_mpc_tfs` elimina o `mpc2` (irmão de controle), a peça central da prova [Critical], TST-04 — Import/export com nome duplicado *dentro do próprio bundle* nunca é testado por nome [Important], TST-05 — Falta teste de import com `pid` de MPC parcialmente preenchido no bundle [Important] (+5 more)

### Community 354 - "Tech Debt Registry"
Cohesion: 0.14
Nodes (13): Commands, Critical (Blocks Feature Work), Debt Item Format, Guidelines, High (Causes Frequent Issues), Low (Track for Later), Medium (Slows Development), Metrics (+5 more)

### Community 355 - "WatchdogTask"
Cohesion: 0.14
Nodes (10): Task de watchdog viva; None fora de `up` ou em conexão sem o par de node_ids., _describe(), Client, Exception, Registra a transição do bit lido e arma `watchdog_alive` na primeira delas., Detalhe curto para o payload do evento, no mesmo idioma de `subscriptions.py`.…, Handshake de life-bit com o PLC, por conexão (ADR-009, RF-206). Pressupõe…, Cria a task do watchdog e retorna já. (+2 more)

### Community 356 - "Achados"
Cohesion: 0.17
Nodes (11): Achados, FE-01 — `output_eu` não tem onde morar no modelo de dados do frontend [Critical], FE-02 — Campo de EU por porta de saída do Script exige tornar `n_outputs` controlado, o que quebra o padrão atual do modal [Important], FE-03 — Download autenticado (export de projeto e `.der` do certificado) não tem caminho executável com o `api()` atual [Critical], FE-04 — `api()` força `Content-Type: application/json` em qualquer corpo; o "mesmo primitivo" de upload do §6.2-3 não serve ao import do §6.1-6 sem modificação [Critical], FE-05 — Nenhuma invalidação de `queryKey` especificada para `["projects"]`; reintroduz o próprio bug que a §6.1 existe para fechar [Critical], FE-06 — Tique de TTL "no provider" não diz como chega até `AnnunciatorBar`; a forma óbvia (bump no `EstadoContext`) re-renderiza toda página que usa `useCanalAoVivo` [Important], FE-07 — Confirmado: existe exatamente **um** ciclo de import em runtime (não mais de um); a correção não nomeia o módulo neutro nem quais símbolos migram [Minor] (+3 more)

### Community 357 - "Archive Directory"
Cohesion: 0.20
Nodes (8): Archive Directory, Archive Process, Archive Registries, Archiving Reports, Finding Archived Reports, Notes, Structure, Registry Archive

### Community 358 - "Achados"
Cohesion: 0.20
Nodes (9): Achados, Revisão da spec F6 — superfície de segurança do export/import e dos certificados, SEC-01 — Import de bundle quebra a premissa de confiança do bloco Script (ADR-018) sem revisão nem aviso [Important], SEC-02 — Regra de exclusão do §2.1-1 é subconjunto de §2.3: implementador que reusa o schema existente vaza `server_cert_file` e mascara a pendência do §6.3 [Important], SEC-03 — `graph_json`/código do bloco Script viaja verbatim no bundle sem qualquer aviso sobre credencial embutida em script [Important], SEC-04 — Import não tem teto de contagem (flows/conexões/tags), e a validação síncrona da camada 4 roda no único worker uvicorn que também serve o `/ws` de operação [Important], SEC-05 — Export não gera evento de auditoria, embora a própria spec justifique o RBAC citando a sensibilidade do que é exportado [Important], SEC-06 — Aviso de re-trust do certificado de aplicação é genérico e sua única superfície de UI é escopada ao projeto ativo, embora o certificado seja da instalação inteira [Important] (+1 more)

### Community 359 - "StubPool"
Cohesion: 0.14
Nodes (11): ScriptResult, async_sessionmaker, AsyncSession, fixture, Fixtures compartilhadas dos testes do flow-runtime. As fixtures de…, Factory commitada de verdade: o supervisor não vê transação aberta de teste., session_factory(), _truncate() (+3 more)

### Community 360 - ".stop"
Cohesion: 0.20
Nodes (8): _cancel(), _log_teardown_results(), Any, Derruba poll, consumidor, todas as tasks e o pool — nesta ordem. Idempotente.…, Para a task e tira o flow do mapa e do `/health`. A entrada sai do mapa mesmo…, Registra o que o gather engoliu: desmonte silencioso esconde flow órfão…, Cancela e aguarda a task; erro dela não pode impedir o resto do desmonte., Task

### Community 361 - "Report Registry"
Cohesion: 0.33
Nodes (5): 2026-08-06, 2026-08-07, Archive, Report Registry, YYYY-MM-DD

### Community 365 - "blocks/base.py"
Cohesion: 0.10
Nodes (14): ABC, Block, null_outputs(), Protocolo comum dos blocos executáveis e as duas regras de base (spec F3 §3.0).…, Bloco de um flow. `block_id` é o id do nó React Flow (chave do hot-swap,…, Handles de entrada declarados (não necessariamente conectados)., Executa uma varredura e devolve os valores das portas de saída., Zera o estado interno (deploy/stop). Blocos sem estado não precisam… (+6 more)

### Community 372 - "test_reassinatura_limpa_respeita_o_freio"
Cohesion: 0.33
Nodes (4): ClosingRedis, Cliente cujo `pubsub()` sempre devolve assinante que encerra a escuta na hora., `listen()` que termina limpo não pode virar rajada de reassinatura queimando…, test_reassinatura_limpa_respeita_o_freio()

## Knowledge Gaps
- **704 isolated node(s):** `COR_LAMPADA`, `AGUARDO`, `ROTULO_EFEITO`, `TOM_EFEITO`, `ADR-0011` (+699 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **108 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TagRef` connect `TagRef` to `definition.py`, `test_flowgraph_mpc.py`, `MpcConfig`, `_avisos_watchdog`, `ottima_core/tags.py`, `mpc_golden_export.py`, `validate.py`, `errors_of`, `routers/projects.py`, `ResumeOrchestrator`?**
  _High betweenness centrality (0.079) - this node is a cross-community bridge._
- **Why does `publish_event()` connect `publish_event` to `opc-worker/tests/test_supervisor.py`, `ConnectionRuntime`, `FlowTask`, `WriteConsumer`, `OpcWriteBlock`, `harness_factory`, `test_backpressure.py`, `routers/flows.py`, `RecorderPipeline`, `Collector`, `test_pipeline.py`, `ottima_opc_worker/connection.py`, `set_server_certificate`, `create_flow`, `test_kind_fora_de_hint_kinds_nao_dispara_reconcile`, `routers/projects.py`, `User`, `bus.py`, `blocks/base.py`, `ResumeOrchestrator`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Why does `await_until()` connect `await_until` to `opc-worker/tests/test_supervisor.py`, `test_failure.py`, `PatternListener`, `test_backpressure.py`, `test_script.py`, `test_server.py`, `FakeClock`, `MpcHost`, `runtime_test_helpers.py`, `test_kind_fora_de_hint_kinds_nao_dispara_reconcile`, `test_connection.py`, `test_subscriptions.py`, `test_writes.py`, `test_pipeline.py`, `test_watchdog.py`, `RecorderPipeline`, `test_heartbeat.py`, `opc-worker/tests/test_security.py`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Are the 104 inferred relationships involving `await_until()` (e.g. with `test_bloco_identico_mantem_o_estado_interno_do_tfs()` and `test_bloco_removido_desaparece_e_bloco_novo_nasce_null()`) actually correct?**
  _`await_until()` has 104 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `MpcConfig` (e.g. with `TagRef` and `ValidationResult`) actually correct?**
  _`MpcConfig` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `MpcBlock` (e.g. with `MpcModes` and `MpcPrediction`) actually correct?**
  _`MpcBlock` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 62 inferred relationships involving `harness_factory()` (e.g. with `test_bloco_identico_mantem_o_estado_interno_do_tfs()` and `test_bloco_removido_desaparece_e_bloco_novo_nasce_null()`) actually correct?**
  _`harness_factory()` has 62 INFERRED edges - model-reasoned connections that need verification._