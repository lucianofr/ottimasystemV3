# Graph Report - ottimaSystemV3  (2026-08-10)

## Corpus Check
- 448 files · ~411,543 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 5366 nodes · 12898 edges · 291 communities (207 shown, 84 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 794 edges (avg confidence: 0.71)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `845aa48d`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- api.ts
- opc-worker/tests/test_supervisor.py
- mpcLogic.ts
- test_flowgraph_mpc.py
- test_flowgraph.py
- OpcSim
- _SupersededAttemptError
- graph.ts
- WSClient
- ChannelListener
- test_flow_commands.py
- app.py
- ValueSnapshot
- FakeClock
- Ambiente
- Supervisor
- TagRef
- MpcHost
- FlowEditorPage.tsx
- FlowTask
- PortSample
- entradas
- test_f3_engine.py
- test_operate.py
- test_watchdog.py
- ConnectionRuntime
- ScriptPool
- test_mpc_block.py
- ws.py
- opc-worker/tests/test_security.py
- deps.py
- 4. Cenários
- logging.py
- worker.py
- test_tfs.py
- Spec F6 — Portabilidade & hardening (export/import, certificados, suíte RNF-09)
- opc-worker/tests/test_health.py
- test_f3_lifecycle.py
- channel_flow_status
- harness_factory
- test_failure.py
- generate_app_cert
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
- TrendPage.tsx
- generate_app_certificate
- mpc_config.py
- test_heartbeat.py
- ModalConfigBloco.tsx
- ottima_opc_worker/main.py
- test_pipeline.py
- ottima_opc_worker/connection.py
- Plano F6b — Superfícies (Projetos, certificados, pendências, EU, DV)
- Spec F5 — Tela de operação (faceplates, trend com predição, eventos e banner)
- routers/connections.py
- ottima_core/security.py
- flowgraph/__init__.py
- graphMpc.ts
- e2e/conftest.py
- build_mpc
- make_user
- ConnectionConfig
- publish_event
- test_mpc_arming.py
- test_server.py
- 4. Cenários
- _get
- test_mpc_builder.py
- mpc_golden_export.py
- operate.py
- models/__init__.py
- Validacao do bloco MPC (422 pt-BR string unica)
- certs.py
- bus.py
- MpcConfig
- HTTPException
- Plano F5b — Operação: tela de operação
- ValueHeartbeat
- ADR-011 — Hot-swap de flows sem interrupção; sem versionamento
- User
- Plano F4a — MPC: config & montagem
- PairInit
- test_mpc_worker.py
- Any
- flow-runtime
- compilerOptions
- create_tag
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
- WatchdogTask
- MpcBlock (blocks/mpc.py)
- ADR-012 — Projeto como unidade de agrupamento e portabilidade (JSON)
- Semantica de invalidez: executa com o valor e propaga flag
- index.tsx
- api/tests/test_events.py
- MCP Tools: code-review-graph
- ADR-001…024 (decisões de arquitetura normativas)
- Supervisor (ciclo de vida dos FlowTasks)
- await_until
- test_api_e2e.py
- test_mpc_load.py
- ADR-010 — Modos LOCAL/REMOTO e MAN/AUTO com transferência bumpless
- ADR-014 — Orçamento de tempo do MPC e multiplicador de execução
- ottima_core.flowgraph (validacao de grafo compartilhada)
- fixtures.ts
- contracts_export.py
- Semantica de exec_order e tabela de portas persistente
- conftest.py
- Contrato de canais do barramento (PRD §7.1)
- .__aexit__
- Serviço api (FastAPI, porta interna 8000)
- generate-contracts.mjs
- schemas/connections.py
- bloco
- Hot-swap (banco + dica, aplicacao atomica na fronteira)
- RF-206/207 watchdog por conexão e política de falha
- PRD OttimaSystem v1.2 (requisitos, contratos, fases)
- PRD §4 domain model: User, Project, OpcConnection, Tag, Flow, Block/Edge in graph_json, Event and Sample hypertables
- CLAUDE.md (archived) — OttimaSystem agent operating rules
- RBAC com papéis admin e operador
- Canal mpc.state.<flow_id>.<block_id>
- schemas/flows.py
- Decision: two mode axes — LOCAL/REMOTO (PID vs MPC, bumpless both ways via PID mode writes AUTO<->RCAS/CAS/ROUT) and MAN/AUTO sub-mode of REMOTO; MV tracking in LOCAL
- Decision: Redis pub/sub internal bus (opc.values.<conn_id> out, opc.writes in)
- Decision: per-pair model matrix (MV->CV, DV->CV); response type per CV — self-regulating SOPDT(K,t1,t2,th) or integrating (Ki,th); Np/Nc derived from TSS, not user-edited; hard MV limits and rate limit
- PRD.md (archived) — OttimaSystem product requirements v1.0
- FakeClock
- _DropOldestBuffer
- ottima_flow_runtime/main.py
- scripts
- routers/history.py
- eventos
- processo_vivo
- Decision: solver timeout ~70% of effective Ts_mpc — on overrun keep last MV, raise alarm, skip to next scan; per-block multiplier N (Ts_mpc = N x Ts_flow)
- Decision: per-connection watchdog with two OPC bits (read+write), crossed NOT, frozen >10s declares comm failure; failure stops writes and flows
- Decision: fifth palette block TFS — transfer-function matrix up to 2x2, each element SOPDT or IOPDT, discrete-time at flow Ts, persistent internal state
- Matriz de modelos SOPDT/integrador com horizontes derivados do TSS
- env.py
- cert_servidor
- ottima_recorder/main.py
- test_snapshot.py
- Plano F5a — Operação: dados & serviços
- api/tests/test_tags.py
- react-router
- WSClient
- Continuous aggregate samples_1m (avg/min/max/count/worst_quality)
- Decision: live flow edits take effect on the next scan without interruption; no flow versioning
- RF-401 scan cycle por exec_order com atraso determinístico de 1 scan
- script_pool: guarda do teto C2 + stats
- RNF-09 suíte de malha fechada MPC↔TFS
- package.json
- ottima-core
- pool
- sim
- .stall
- Retenção 1 mês + continuous aggregate (RF-801, ADR-003)
- ottima_core.contracts_export
- Publishes
- Campo grafite (paleta neutra escura dessaturada)
- Bumpless (transferência sem salto na MV)
- Scan cycle (avaliação a cada Ts em ordem de exec_order)
- TFS (bloco de simulação, matriz até 2×2 SOPDT/IOPDT)
- ADR-005 — Canvas com React Flow; execução 100% no backend
- ADR-023 — Escopo de plataforma da v1: pt-BR, auth local, HTTP interno, Compose on-prem
- Camadas L1/L1s/L2/L3 e 19 cenários do gate da F1
- api-types.ts
- api/tests/test_health.py
- ValueSubscription
- entrypoint-api.sh
- smoke.sh
- Faceplates com barras verticais PV/SP/OUT (convenção intocável)
- Filosofia ISA-101 (cor reservada a estado)
- Monorepo layout: docs/, frontend/, packages/ottima-core, services/{api,opc-worker,flow-runtime,recorder}, deploy/, tests/ as uv workspace
- ProcessPool dedicado do bloco Script
- tests/testkit/await_until.py (util unico)
- ottima_core.tags.project_tags
- ConnectionRuntime (máquina connecting→up→failed, backoff + jitter)
- @fontsource/spline-sans-mono
- test_auto_arm_blocked_reason_exige_readback_da_mv_direta
- @tanstack/react-query
- test_publish_de_fronteira_usa_a_mv_desta_mesma_varredura
- test_get_app_com_pem_corrompido_devolve_500_em_pt_br
- blocks/__init__.py
- ottima_flow_runtime/__init__.py
- test_busy_loop_nao_trava_o_event_loop
- test_import_esta_bloqueado_no_escopo
- test_dupla_cancelacao_durante_replace_nao_encolhe_o_pool
- test_stats_conta_respawns_e_reflete_ocupacao
- test_envio_do_job_roda_fora_do_event_loop
- test_handshake_de_boot_falho_loga_o_tamanho_do_pool_que_sobrou
- ottima_opc_worker/__init__.py
- FlowStatusHub
- test_auto_arm_blocked_reason_exige_readback_do_pid
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
- delete
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
- .advance
- Settings
- pipeline.py
- FakeHost
- FakeSnapshot
- test_ws_mpc.py
- Writes
- setup_planta.py
- parametrize
- Block
- schemas/events.py
- schemas/tags.py
- planta_virtual/supervisor_mpc.py
- _config
- plant_ops.py
- FlowStatus
- schemas/auth.py
- BaseModel
- probe_sessao.py
- _block

## God Nodes (most connected - your core abstractions)
1. `await_until()` - 169 edges
2. `mpc_node()` - 64 edges
3. `MpcConfig` - 62 edges
4. `mpc_graph()` - 62 edges
5. `mpc_tags()` - 62 edges
6. `has()` - 57 edges
7. `errors_of()` - 53 edges
8. `harness_factory()` - 53 edges
9. `ConnectionRuntime` - 51 edges
10. `collect()` - 51 edges

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

## Communities (291 total, 84 thin omitted)

### Community 0 - "api.ts"
Cohesion: 0.05
Nodes (77): ADR-0015, ADR-0020, AnnunciatorBar(), AppShell(), NAV_ENGENHARIA, AuthGuard(), HomePage(), App() (+69 more)

### Community 1 - "opc-worker/tests/test_supervisor.py"
Cohesion: 0.06
Nodes (78): _BrokenPubSub, CancellingRuntime, ClosingRedis, Contador, contar_mensagens_vistas(), contar_passadas(), create_connection(), create_project() (+70 more)

### Community 2 - "mpcLogic.ts"
Cohesion: 0.05
Nodes (74): Label(), CabecalhoAoVivo(), DadosMpc, ParModeloMpc, TipoLinhaMpc, VariaveisMpc, VariavelCv, VariavelDv (+66 more)

### Community 3 - "test_flowgraph_mpc.py"
Cohesion: 0.11
Nodes (97): _auto_models(), co(), cv(), dv(), errors_of(), has(), integrating_params(), mpc_graph() (+89 more)

### Community 4 - "test_flowgraph.py"
Cohesion: 0.06
Nodes (99): parse_graph(), Valida a forma do `graph_json` e devolve o modelo tipado. Levanta…, base_graph(), base_tags(), edge_of(), errors_of(), has(), link() (+91 more)

### Community 5 - "OpcSim"
Cohesion: 0.07
Nodes (71): AmbienteMpc, armar_auto_com_retentativa(), armar_remoto_direto(), assinar_mpc_state(), _config_mpc_malha(), criar_flow_mpc(), deploy_flow(), evento_mpc() (+63 more)

### Community 6 - "_SupersededAttemptError"
Cohesion: 0.05
Nodes (31): backoff_delay(), build_client(), _disconnect_quiet(), Client, FailureReason, RuntimeError, TagConfig, VariantType (+23 more)

### Community 7 - "graph.ts"
Cohesion: 0.04
Nodes (64): Editor(), novoId(), alcanca(), ArestaSerializada, avisosInversao(), Bloco, BlocoEdge, mpc() (+56 more)

### Community 8 - "WSClient"
Cohesion: 0.16
Nodes (13): channel_mpc_state(), _payload_of(), Any, Tudo o que o cliente ainda tem para receber, até o cano secar., Volta quando o servidor consumiu o envio. O comando é aplicado sem nenhum…, Regressão do roteio duplo: o segundo `PatternListener` do hub (`mpc.state.*`)…, Cliente WS in-process: fala ASGI direto, no mesmo event loop do teste. O…, Abre a conexão e volta com o socket aceito, autenticado e registrado no hub. (+5 more)

### Community 9 - "ChannelListener"
Cohesion: 0.08
Nodes (28): ChannelListener, _close(), Any, PubSub, Redis, Só volta com a inscrição confirmada: a publicação seguinte não se perde.…, Assinante resiliente de um canal fixo (`SUBSCRIBE`); `handler` recebe só o…, Fecha o assinante sem nunca levantar: é caminho de desmonte. (+20 more)

### Community 10 - "test_flow_commands.py"
Cohesion: 0.08
Nodes (56): eventos(), Assinante do canal `events` num segundo cliente, como faz o worker (ADR-020).…, _admin_id(), _conexao(), _projeto(), Auditoria da API no canal `events` (ADR-020, spec F2 §7.2): o que emite e o que…, CRUD de users, CRUD de projects sem ativação e qualquer GET: canal silencioso…, Trocar `dependencies=[require_admin]` pelo parâmetro nomeado não pode afrouxar… (+48 more)

### Community 11 - "app.py"
Cohesion: 0.19
Nodes (10): create_app(), lifespan(), FastAPI, Settings, App factory da API: rotas sob /api, logging JSON e ciclo de vida do engine., Cria engine, session factory, Redis e o hub do /ws na subida; descarta na…, OttimaSystem — API REST., Alvo do uvicorn em produção: ottima_api.main:app. (+2 more)

### Community 12 - "ValueSnapshot"
Cohesion: 0.07
Nodes (37): PidBinding, Amarração de tags do PID de uma MV (spec §2.1-3, RF-604)., PatternListener, Laço resiliente de assinatura ao barramento pub/sub do Redis (canal fixo ou…, Assinante resiliente de um padrão glob (`PSUBSCRIBE`); `handler` recebe…, Definição pronta para subir ou entrar em hot-swap, com o que o supervisor…, StagedDefinition, mpc_block_origin() (+29 more)

### Community 13 - "FakeClock"
Cohesion: 0.09
Nodes (47): events_of(), FakeClock, flow(), datetime, fixture, Redis, Contratos do laço de varredura (RF-401/402/404, ADR-004/007/024, spec F3 §2.2,…, Fábrica de assinantes: devolve a lista que recebe os payloads crus de um canal. (+39 more)

### Community 14 - "Ambiente"
Cohesion: 0.08
Nodes (51): Ambiente, congelar_watchdog(), esperar_ate(), esperar_conexao(), evento_de(), EventStream, publicar_escrita(), PubSub (+43 more)

### Community 15 - "Supervisor"
Cohesion: 0.07
Nodes (25): Exception, FlowTask, FlowCommand, async_sessionmaker, AsyncSession, Block, Connection, Flow (+17 more)

### Community 16 - "TagRef"
Cohesion: 0.08
Nodes (56): FlowEdge, FlowGraph, FlowNode, MvVar, Variável manipulada. Sem `pid` ⇒ MV "direta" (spec §2.1-3). Coordenada da…, _check_cycles(), _check_edge_endpoints(), _check_exec_order() (+48 more)

### Community 17 - "MpcHost"
Cohesion: 0.07
Nodes (35): MpcHost, Any, Connection, SpawnProcess, Mata + junta + fecha o pipe. Roda numa thread (ADR-004); nunca levanta — mesmo…, Dono do processo do worker MPC de UM bloco (spec F4 §3.6/§4.2/§4.9). Ver…, Sobe o processo e espera o handshake `("ready", n_x)` — `ready` fica `False`…, `True` só quando há um worker vivo e pronto para receber o PRÓXIMO dispatch —… (+27 more)

### Community 18 - "FlowEditorPage.tsx"
Cohesion: 0.05
Nodes (57): ADR-0011, ADR-0023, AGUARDO, COR_LAMPADA, ADR-0024, DESCRICAO, FlowPalette(), MIME_BLOCO (+49 more)

### Community 19 - "FlowTask"
Cohesion: 0.07
Nodes (20): PortValue, FlowTask, datetime, Redis, Ancora a grade e sobe a task. Idempotente: deploy em rodando é no-op (RNF-05)., Encerra a task. Idempotente e nunca levanta: é caminho de desmonte (RNF-05).…, Falha imposta de fora: `comm_failure` derruba os flows da conexão caída…, Uma varredura: blocos na ordem da tupla, lendo e escrevendo a tabela de portas. (+12 more)

### Community 20 - "PortSample"
Cohesion: 0.04
Nodes (71): ABC, Block, has_cold_input(), null_outputs(), PortSample, Protocolo comum dos blocos executáveis e as duas regras de base (spec F3 §3.0).…, Valor de uma porta numa varredura. `v is None` é cold start (nunca houve valor…, Bloco de um flow. `block_id` é o id do nó React Flow (chave do hot-swap,… (+63 more)

### Community 21 - "entradas"
Cohesion: 0.12
Nodes (23): entradas(), PortSample, Tag de readback configurada e ainda sem nenhum valor publicado: a saída sai…, Sem tag de readback configurada não há o que esperar — vale o hold de sempre. É…, Mesma regra na MV direta — e aqui ela é a que importa de verdade: a porta da MV…, MV direta com `readback_tag_id`: em LOCAL a saída acompanha a variável OPC-UA à…, `quality != 0` invalida a leitura (mesma regra do `opc_read`, spec F3 §3.1):…, LOCAL -> REMOTO entra em MAN com a MV manual := valor vigente (spec §4.4).… (+15 more)

### Community 22 - "test_f3_engine.py"
Cohesion: 0.11
Nodes (48): aresta(), assinantes_de_status(), bloco(), de_varredura(), deploy(), elemento_iopdt(), evento_de_bloco(), grafo_script_tfs() (+40 more)

### Community 23 - "test_operate.py"
Cohesion: 0.09
Nodes (48): _aresta(), _cenario(), comandos(), _conexao(), _cv(), _flow(), _grafo_mpc(), _id_do_usuario() (+40 more)

### Community 24 - "test_watchdog.py"
Cohesion: 0.09
Nodes (44): assert_bit_stable(), await_bit(), await_flips(), connected(), make_config(), make_watchdog(), Client, ConnectionConfig (+36 more)

### Community 25 - "ConnectionRuntime"
Cohesion: 0.07
Nodes (32): BlockReason, OpcWrite, RejectReason, ConnectionRuntime, Conta as reaberturas do gate de escrita; muda ⇒ período de bloqueio novo., Conexão com canal seguro: só nela um prazo estourado pode ser cert divergente., Mantém uma sessão OPC-UA viva e traduz suas transições em eventos (spec §3.6)., ConnectionState (+24 more)

### Community 26 - "ScriptPool"
Cohesion: 0.07
Nodes (39): Bloco Python-Script (RF-511..514, ADR-018, spec F3 §3.3, decisões A-4/A-5/A-6).…, build_definition(), _instantiate(), _instantiate_mpc(), _make_write_opc(), Any, Block, Connection (+31 more)

### Community 27 - "test_mpc_block.py"
Cohesion: 0.18
Nodes (19): _entra_remoto_auto(), Contratos do bloco MPC — cadência, modos, aplicar-na-fronteira e write-back…, MAN->AUTO tem que partir do ÚLTIMO VALOR DA MV EM MAN (spec §4.4) — nunca de um…, Entrar em AUTO com host pronto e zero solves concluídos: `status.solver`…, A mesma emenda vale em AUTO — este caminho já funcionava antes da tarefa…, spec §4.2: "worker indisponível -> conta e pula sem acumular fila" — SEM novo…, A realimentação por bias precisa do `u` FISICAMENTE aplicado — a posição real…, _resultado_ok() (+11 more)

### Community 28 - "ws.py"
Cohesion: 0.18
Nodes (13): _apply_client_message(), _authenticate(), _flow_ids(), _mpc_ids(), Any, AsyncSession, Settings, User (+5 more)

### Community 29 - "opc-worker/tests/test_security.py"
Cohesion: 0.10
Nodes (46): certs_dir(), certs_dir_vazio(), endpoint_mudo(), failures(), falha_unica(), make_config(), pin_server_certificate(), ConnectionConfig (+38 more)

### Community 30 - "deps.py"
Cohesion: 0.10
Nodes (26): EventOut, HTTPAuthorizationCredentials, get_app_settings(), get_current_user(), get_db(), get_redis(), AsyncSession, Redis (+18 more)

### Community 31 - "4. Cenários"
Cohesion: 0.09
Nodes (21): 1. Precondições de ambiente, 2. Regras de execução com a tool `browser`, 3. Evidências, 4. Cenários, 5. O que este roteiro NÃO cobre, 6. Ordem de gate, B-F6-01 — `/engenharia/projetos`: CRUD, exclusão do ativo recusada, B-F6-02 — Ativar: confirmação nomeia o projeto e o nº de flows a parar; invalidação de cache sem reload (+13 more)

### Community 32 - "logging.py"
Cohesion: 0.08
Nodes (29): DataValue, LogRecord, JsonFormatter, Logging estruturado JSON em stdout (RNF-07; spec F1 §7.1)., Serializa cada registro como uma linha JSON com timestamp UTC., Substitui os handlers do logger raiz por um único handler JSON em stdout., setup_logging(), Heartbeat de valor de uma conexão: report-by-exception + republicação (spec F2… (+21 more)

### Community 33 - "worker.py"
Cohesion: 0.10
Nodes (35): DM, DMStruct, BuiltMpc, Montagem do-mpc do bloco MPC (spec F4 §3.2-3.5; TDD estrito). `build_mpc` monta…, Controller do-mpc pronto + metadados de índice para o worker (spec F4 §3,…, Init bumpless — rotina única de armar/re-armar (spec F4 §3.6; TDD estrito).…, _empty_result(), `MpcHost` — dono, no processo pai, do processo filho do worker MPC (spec F4… (+27 more)

### Community 34 - "test_tfs.py"
Cohesion: 0.06
Nodes (54): _Element, _FirstOrder, Block, PortSample, Entradas `u1,u2`; saídas `y1,y2`. `matrix[J][K]` = contribuição de `uK` para…, Estágio de 1a ordem exato no ZOH: `x <- a*x + (1-a)*u`. Abaixo de…, Dois estágios de 1a ordem em série; ganho K aplicado no final da cascata., Fila de atraso na entrada + núcleo dinâmico de um elemento habilitado da… (+46 more)

### Community 35 - "Spec F6 — Portabilidade & hardening (export/import, certificados, suíte RNF-09)"
Cohesion: 0.05
Nodes (39): 10. Débitos herdados — veredito, 11. Aderência ao aceite F6 (PRD §8), 12. Mapa de seções por plano (RFC-09), 1.1 Dentro da F6, 1.2 Fora da F6 — com destino registrado, 1.3 Emendas a documentos anteriores (consolidação), 1. Escopo da F6, 2.1 Schemas de bundle próprios (decisão A-2; emenda PRD §7.2 → v1.4; F6R-05) (+31 more)

### Community 36 - "opc-worker/tests/test_health.py"
Cohesion: 0.08
Nodes (27): app(), App real com get_db na sessão em SAVEPOINT e get_redis no Redis efêmero dos…, Runtime que não subiu o supervisor está surdo a todo `deploy`: nunca…, StubRedis, test_check_redis_marca_estado(), test_health_responde_200_com_nome_do_servico(), test_health_sem_supervisor_nao_responde_ok(), app_state_limpo() (+19 more)

### Community 37 - "test_f3_lifecycle.py"
Cohesion: 0.09
Nodes (38): aguardar_parado(), ativar_projeto(), esperar_runtime_saudavel(), esperar_todos(), evento_de_flow(), fabrica_de_flows(), flow_no_runtime(), id_da_sentinela() (+30 more)

### Community 38 - "channel_flow_status"
Cohesion: 0.15
Nodes (36): channel_flow_status(), connect(), hub(), make_token(), operator_token(), fixture, parametrize, WebSocket `/ws`: auth, protocolo, fanout e isolamento entre clientes (RF-305,… (+28 more)

### Community 39 - "harness_factory"
Cohesion: 0.05
Nodes (158): FlowStatus, ScriptResult, collect(), harness_factory(), async_sessionmaker, AsyncSession, fixture, Redis (+150 more)

### Community 40 - "test_failure.py"
Cohesion: 0.15
Nodes (41): BusTrail, assert_bit_estavel(), bad_tag_ids_before(), bad_values(), collect_bus(), events_of_kind(), index_of_first(), make_config() (+33 more)

### Community 41 - "generate_app_cert"
Cohesion: 0.23
Nodes (11): AppCertificateGenerateIn, AppCertificateGenerateOut, AppCertificateOut, BaseModel, Schemas de certificados: app cert de instância e trust por conexão (RF-202,…, ServerCertificateOut, generate_app_cert(), get_app_cert() (+3 more)

### Community 42 - "test_backpressure.py"
Cohesion: 0.10
Nodes (41): backpressure(), count_rows(), event_payloads(), events_seen(), get_health(), health_app(), make_pipeline(), publish_samples() (+33 more)

### Community 43 - "Plano F6a — Portabilidade & dados"
Cohesion: 0.14
Nodes (13): Aderência (DoD do plano F6a), Contratos verbatim (spec F6 §2.1-4 — forma normativa do arquivo de projeto), Etapa 0 — Emendas documentais e constantes (spec §1.3; antes de qualquer código de feature), Etapa 1 — Contrato de portabilidade (spec §2; decisão A-2; F6R-05), Etapa 2 — Export e import (spec §3.1/§3.2; RF-102 emendado, RF-103), Etapa 3 — Health, log estruturado e superfície do Script (spec §3.3/§3.4), Etapa 4 — Schema: EU nas portas e faixa da DV (spec §4.1 backend, §4.2), Etapa 5 — Runtime: débitos herdados da F5 (spec §5) (+5 more)

### Community 44 - "test_flows.py"
Cohesion: 0.15
Nodes (38): _aresta(), _cenario(), _conexao(), _flow(), _grafo_read_write(), _mensagens(), _no(), _projeto() (+30 more)

### Community 45 - "test_flows_mpc.py"
Cohesion: 0.13
Nodes (39): _aresta(), _auto_models(), _cenario_mpc(), _conexao(), _cv(), _dv(), _flow(), _grafo_mpc() (+31 more)

### Community 46 - "FlowsPage.tsx"
Cohesion: 0.08
Nodes (36): ADR-0007, CelulaDesejado(), COLUNAS, FlowForm(), FlowsPage(), GraphJson, CHAVE, formatarTs() (+28 more)

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
Cohesion: 0.11
Nodes (40): delete, FlowCreate, FlowSaved, FlowUpdate, project_tags(), AsyncSession, Tags visíveis ao flow: as do projeto dele, via conexão (o `graph_json` não tem…, Duas conexões, dois projetos: `project_tags` não pode vazar tag de outro… (+32 more)

### Community 51 - "MpcBlock"
Cohesion: 0.05
Nodes (33): Block, _LocalRemote, MpcHost, MpcPrediction, MvVar, PidBinding, _clamp(), _empty_prediction() (+25 more)

### Community 52 - "test_connection.py"
Cohesion: 0.15
Nodes (40): collect_events(), make_config(), make_runtime(), of_kind(), ConnectionConfig, ConnectionRuntime, ConnectionSnapshot, MonkeyPatch (+32 more)

### Community 53 - "test_subscriptions.py"
Cohesion: 0.15
Nodes (35): collect_events(), collect_values(), make_config(), of_kind(), of_tag(), ConnectionConfig, ConnectionRuntime, MonkeyPatch (+27 more)

### Community 54 - "RecorderPipeline"
Cohesion: 0.08
Nodes (20): OpcValue, T, Payloads que não parsearam: lixo no canal, não pressão — contador separado., Assina os canais e sobe as tasks de leitura e de flush; retorna já. Idempotente., Cancela as tasks, encerra as inscrições e faz o flush final. Idempotente.…, Um ciclo de gravação: eventos primeiro, samples depois. Auditoria tem…, Parse e enfileira uma amostra; payload inválido é descartado com log., Flush a cada `flush_interval_s`, quando um buffer enche ou no backoff do retry. (+12 more)

### Community 55 - "TrendPage.tsx"
Cohesion: 0.12
Nodes (26): TrendChart(), TrendChartProps, JanelaId, JANELAS, ROTULO_MODO, TrendPage(), ADR-0017, CLASSES_PENA (+18 more)

### Community 56 - "generate_app_certificate"
Cohesion: 0.14
Nodes (32): app_cert_paths(), generate_app_certificate(), Gera o certificado autoassinado de instância de aplicação (spec F2 §5.3).…, Monta os caminhos do certificado de aplicação, sem tocar no disco., Lê os metadados do certificado de aplicação. Devolve `exists=False` quando o…, read_app_certificate(), OttimaSystem — pacote compartilhado (modelos, schemas, barramento, segurança)., _falha_na_gravacao() (+24 more)

### Community 57 - "mpc_config.py"
Cohesion: 0.11
Nodes (22): field_validator, ConstraintVar, CvVar, DvVar, _exigir_prefixo(), Horizons, Limits, ModeValues (+14 more)

### Community 58 - "test_heartbeat.py"
Cohesion: 0.18
Nodes (32): beating(), collect_values(), heartbeat_tags(), make_config(), make_runtime(), of_tag(), ConnectionConfig, ConnectionRuntime (+24 more)

### Community 59 - "ModalConfigBloco.tsx"
Cohesion: 0.09
Nodes (28): Input, Select, inteiroDoCampo(), matrizDoFormulario(), nomeParam(), numeroDoCampo(), CamposTfs(), PARAMS (+20 more)

### Community 60 - "ottima_opc_worker/main.py"
Cohesion: 0.18
Nodes (15): check_database(), check_redis(), _heartbeat_loop(), lifespan(), FastAPI, Serviço opc-worker: lifespan com supervisor e `/health` por conexão (RNF-07). O…, Faz ping no Redis e registra o resultado em app.state.redis_ok., Faz um SELECT 1 no banco e registra o resultado em app.state.db_ok. (+7 more)

### Community 61 - "test_pipeline.py"
Cohesion: 0.19
Nodes (29): channel_opc_values(), count_rows(), instrumented(), make_pipeline(), purge(), Any, fixture, Table (+21 more)

### Community 62 - "ottima_opc_worker/connection.py"
Cohesion: 0.09
Nodes (36): BaseException, AppCertPaths, Caminhos dos três arquivos do certificado de aplicação., Runtime de uma conexão OPC-UA: máquina de estados, backoff e eventos (spec F2…, CertMismatchError, CertMissingError, _configure_channel(), configure_client() (+28 more)

### Community 63 - "Plano F6b — Superfícies (Projetos, certificados, pendências, EU, DV)"
Cohesion: 0.14
Nodes (13): Aderência (DoD do plano F6b), Etapa 1 — Fundação: helper, primitivos de arquivo e módulos compartilhados (spec §6.0; F6R-10/11), Etapa 2 — Página `/engenharia/projetos` (spec §6.1; decisão A-13; RF-101/102/103), Etapa 3 — Certificados (spec §6.2; decisão A-7; RF-202, ADR-021), Etapa 4 — Pendência de segredo na tabela de Conexões (spec §6.3; decisão A-4), Etapa 5 — EU nas portas e faceplate de DV (spec §4.1 frontend, §4.2, §6.4/§6.5), Etapa 6 — Débitos de frontend da F5 (spec §6.6, os seis), Etapa 7 — Fechamento do plano F6b (+5 more)

### Community 64 - "Spec F5 — Tela de operação (faceplates, trend com predição, eventos e banner)"
Cohesion: 0.06
Nodes (32): 10. Aderência ao aceite F5 (PRD §8), 1.1 Dentro da F5, 1.2 Fora da F5 — com destino registrado, 1.3 Emendas a documentos anteriores (consolidação; F5R-26), 1. Escopo da F5, 2.1 Emenda PRD §7.1 → v1.3: `ts` e `prediction.ts` no `mpc.state` (decisão A-2; F5R-01), 2.2 Hypertable `mpc_samples` (decisão A-1; migration `0003_mpc_samples`, SQL cru, três passos como a 0002), 2.3 Recorder (F5R-12) (+24 more)

### Community 65 - "routers/connections.py"
Cohesion: 0.15
Nodes (29): ConnectionCreate, ConnectionOut, ConnectionUpdate, encrypt_secret(), _carregar(), clear_server_certificate(), create_connection(), delete_connection() (+21 more)

### Community 66 - "ottima_core/security.py"
Cohesion: 0.15
Nodes (20): LoginOut, create_access_token(), decode_access_token(), decrypt_secret(), verify_password(), test_fernet_roundtrip_e_chave_errada(), test_hash_argon2id_e_verificacao(), test_jwt_expirado_rejeitado() (+12 more)

### Community 67 - "flowgraph/__init__.py"
Cohesion: 0.08
Nodes (36): NodeConfig, Modelo tipado do `graph_json` de um flow + validação compartilhada (RF-302/307,…, FlowEdge, FlowGraph, FlowNode, GraphParseError, IopdtParams, _is_int() (+28 more)

### Community 68 - "graphMpc.ts"
Cohesion: 0.23
Nodes (26): deGraphJson(), inteiro(), inteiroSimples(), lerAresta(), lerElemento(), lerMatriz(), lerNo(), lerOutputEu() (+18 more)

### Community 69 - "e2e/conftest.py"
Cohesion: 0.12
Nodes (27): FixtureRequest, admin(), _aguardar_flow_parado_mpc(), ambiente_mpc(), _ativar_sentinela(), _conf(), _criar_tag(), criar_tag_leitura_dummy() (+19 more)

### Community 70 - "build_mpc"
Cohesion: 0.16
Nodes (26): build_mpc(), Monta o `do_mpc.controller.MPC` do bloco (spec F4 §3.2-3.5)., init_bumpless(), Arma/re-arma o `BuiltMpc` sem salto (spec F4 §3.6). 1. Pares autorreguláveis:…, _cv(), _first_mv(), _integrating_config(), _mv() (+18 more)

### Community 71 - "make_user"
Cohesion: 0.10
Nodes (17): admin_headers(), client(), make_user(), operator_headers(), fixture, Fixtures da API: settings de teste, app com get_db/get_redis sobrescritos,…, Settings isoladas do .env local, com segredos determinísticos de teste., Cria usuários direto no banco da sessão de teste (senha já em Argon2id). (+9 more)

### Community 72 - "ConnectionConfig"
Cohesion: 0.06
Nodes (35): ConnectionConfig, Tag configurada de uma conexão., Configuração de uma conexão OPC-UA, tal como o worker a enxerga., Só há watchdog com o par de node_ids: sem os dois não há handshake (ADR-009)., Tudo que exige recriar a sessão asyncua quando muda (tarefa 1.4)., Conjunto de tags em ordem estável: muda ⇒ recria só a subscription (tarefa 1.4)., TagConfig, _cancel() (+27 more)

### Community 73 - "publish_event"
Cohesion: 0.13
Nodes (18): EventMessage, publish_event(), Any, datetime, Redis, Publisher canônico do canal `events` (spec F2 §7.1, ADR-020). Única forma de…, events_sub(), fixture (+10 more)

### Community 74 - "test_mpc_arming.py"
Cohesion: 0.18
Nodes (14): _FakeBlock, `mpc_arming.watch_arm` — shed (spec §4.5, RF-604): reset do contador de misses…, Só o que `watch_arm` lê do bloco de verdade (`MpcBlock.pid_bindings`/`.ts_mpc`)., `mode_read` roteirizado por tick: cada `get()` consome o próximo bool da lista…, Callbacks contadores compartilhados pelos dois runners abaixo., Sobe `watch_arm` com o roteiro dado e ESPERA a task terminar sozinha…, Sobe `watch_arm` em background, deixa rodar exatamente `len(matches)` ticks (a…, _run_n_ticks_then_cancel() (+6 more)

### Community 75 - "test_server.py"
Cohesion: 0.14
Nodes (25): Helpers de teste do opc-worker, importados por nome qualificado pelos arquivos…, _any_task_done(), _client_credentials(), _differs(), _equals(), _greater_than(), Any, Client (+17 more)

### Community 76 - "4. Cenários"
Cohesion: 0.11
Nodes (17): 1. Precondições de ambiente, 2. Regras de execução com a tool `browser`, 3. Evidências, 4. Cenários, 5. O que este roteiro NÃO cobre, 6. Ordem de gate, B-F5-01 — Login operador, navegação ao grupo Operação, seletor e redirect direto, B-F5-02 — Faceplates: barras verticais, mono tabular, lâmpada `building` no deploy recém-feito (+9 more)

### Community 77 - "_get"
Cohesion: 0.16
Nodes (24): _amostra(), _get(), _inserir(), _instantes(), Any, datetime, fixture, parametrize (+16 more)

### Community 78 - "test_mpc_builder.py"
Cohesion: 0.13
Nodes (34): _co(), _config_integradora(), _cv(), _du_config(), _dv(), _mv(), _mv_plan(), _par() (+26 more)

### Community 79 - "mpc_golden_export.py"
Cohesion: 0.22
Nodes (36): _arredondamento_bankers(), build_golden(), _cenario_caps_cv_restricao(), _cenario_caps_dv(), _cenario_caps_mv(), _cenario_config_minima_valida(), _cenario_horizons_dimensao_aviso(), _cenario_horizons_np_abaixo() (+28 more)

### Community 80 - "operate.py"
Cohesion: 0.20
Nodes (24): BlockId, _cv_do_bloco(), ModeCommand, _mpc_config(), _mv_do_bloco(), MvCommand, _publicar_comando(), AsyncSession (+16 more)

### Community 81 - "models/__init__.py"
Cohesion: 0.16
Nodes (15): DeclarativeBase, Base, Base declarativa e mixin de timestamps (SQLAlchemy 2.0; DDL: spec F1 §3.1)., TimestampMixin, OpcConnection, Conexão OPC-UA (RF-201/206, ADR-009/021; DDL: spec F1 §3.1)., Flow, Flow (ADR-005/007/011/017; DDL: spec F1 §3.1). (+7 more)

### Community 82 - "Validacao do bloco MPC (422 pt-BR string unica)"
Cohesion: 0.11
Nodes (24): Etapa 4 do F4a: paleta, no dinamico e modal 7 abas, MpcConfig (Pydantic, espelho do spec 2.1), Componentes do modal MPC (MpcModal + TabGeneral..TabSummary), Paleta com MPC arrastavel + no com portas dinamicas, validate_graph libera mpc e valida spec 2.2 inteiro, B-F4-01: paleta com MPC habilitado e no sem portas antes de configurar, B-F4-02: modal 7 abas, criacao de variaveis e matriz de modelos, B-F4-04: portas dinamicas apos salvar e 422 do servidor em pt-BR (+16 more)

### Community 83 - "certs.py"
Cohesion: 0.14
Nodes (25): AppCertificateInfo, _application_uri_of(), _discard(), _ensure_dir(), _info_from_certificate(), _load_certificate(), Certificate, Path (+17 more)

### Community 84 - "bus.py"
Cohesion: 0.07
Nodes (31): Contratos do barramento Redis pub/sub — payloads verbatim do PRD §7.1…, flow_origin(), publish_flow_deployed(), publish_flow_stopped(), publish_mpc_hot_swap(), publish_rejected(), Redis, Barramento de eventos do runtime: o que ele escuta e o que ele emite (spec F3… (+23 more)

### Community 85 - "MpcConfig"
Cohesion: 0.13
Nodes (29): derive_horizons(), mpc_state_dimension(), MpcConfig, Config do bloco MPC — vive inteiro no `graph_json` (spec §2.1, decisão A-8/A-9)., Deriva `Ts_mpc`, `Np` e `Nc` (spec §2.2-5, RF-603). Função pura: devolve `Np`…, Dimensão do estado agregado do modelo do-mpc (spec §2.2-7). Soma, por par…, mpc_skeleton(), Mesa de casos de `ottima_core.flowgraph.mpc_config` (spec F4… (+21 more)

### Community 86 - "HTTPException"
Cohesion: 0.17
Nodes (22): HTTPException, Project, ProjectCreate, ProjectOut, ProjectUpdate, BaseModel, Schemas de projetos (RF-101, ADR-017): criação, atualização parcial e saída., activate_project() (+14 more)

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
Cohesion: 0.18
Nodes (20): User, BaseModel, Schemas de gestão de usuários (spec F1 §5.5): criação e atualização parcial., UserCreate, UserUpdate, hash_password(), me(), _carregar() (+12 more)

### Community 91 - "Plano F4a — MPC: config & montagem"
Cohesion: 0.15
Nodes (20): Comandos canonicos (stack, gate E2E, precondicoes), Gate E2E de 3 camadas (L1 smoke, L2 pytest e2e, L3 browser), Proibicoes rapidas para agentes, TDD estrito em logica pura; malha fechada MPC<->TFS como aceite, Workflow Superpowers: um plano por fase F1..F6, Rodada de gate da F2 (L1 + L2 + L3 browser-tool), Rodada de gate da F3 (L2 = 24 cenários), Plano F4a — MPC: config & montagem (+12 more)

### Community 92 - "PairInit"
Cohesion: 0.29
Nodes (7): ndarray, PairInit, Metadados de um par HABILITADO para `init_bumpless` (spec F4 §3.6, tarefa 2.3).…, _pair_input_value(), Entrada vigente da coluna do par, JÁ em desvio do ponto de linearização — mesma…, `x = x_ss(u, d)` de um par autorregulável: resolve `(I−A)·x = B·u_eff` (spec…, _steady_state()

### Community 93 - "test_mpc_worker.py"
Cohesion: 0.26
Nodes (20): _config(), _cv(), _mv(), _par(), Connection, fixture, SpawnProcess, Contratos de `mpc.worker` — processo filho do MPC (spec F4 §3.3/§3.6/§4.9/§5.1;… (+12 more)

### Community 94 - "Any"
Cohesion: 0.14
Nodes (15): armar_ate_remoto(), compose(), conexao_health(), EstadoMpcStream, _health_do_runtime(), Any, Roda `docker compose` do stack e2e no diretório do deploy. Escopo…, `/health` do opc-worker, lido de dentro do container. (+7 more)

### Community 95 - "flow-runtime"
Cohesion: 0.21
Nodes (20): ADR-002 — Barramento interno via Redis pub/sub, Barramento interno Redis pub/sub, Postgres/TimescaleDB único, ADR-006 — Separação de processos: opc-worker × flow-runtime × recorder, flow-runtime, opc-worker, recorder, Deploy Docker Compose on-prem (+12 more)

### Community 96 - "compilerOptions"
Cohesion: 0.10
Nodes (19): compilerOptions, isolatedModules, jsx, lib, module, moduleResolution, noEmit, noFallthroughCasesInSwitch (+11 more)

### Community 97 - "create_tag"
Cohesion: 0.18
Nodes (16): _carregar(), create_tag(), delete_tag(), get_tag(), list_tags(), _publicar(), AsyncSession, delete (+8 more)

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
Nodes (19): class-variance-authority, clsx, @fontsource/archivo, @fontsource/archivo-narrow, dependencies, class-variance-authority, clsx, @fontsource/archivo (+11 more)

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
Cohesion: 0.12
Nodes (9): Contratos do ProcessPool de scripts e do bloco Script (RF-511..514,…, ADR-004: a subida do processo do respawn também roda fora do loop.…, Determinismo (spec §3.3): OUTx ausente é erro, não 0.0 sintético., Regressão do teto (débito m3): mesmo sob N cancelamentos em sequência, ciclo…, Achado 1 do fix round 1 (revisão da tarefa 0.6): a blindagem vive DENTRO de…, test_cancelamento_durante_replace_nos_outros_ramos_nao_encolhe_o_pool(), test_dez_ciclos_de_cancelamento_preservam_o_tamanho_do_pool(), test_respawn_nao_trava_o_event_loop() (+1 more)

### Community 108 - "WatchdogTask"
Cohesion: 0.14
Nodes (10): Task de watchdog viva; None fora de `up` ou em conexão sem o par de node_ids., _describe(), Client, Exception, Registra a transição do bit lido e arma `watchdog_alive` na primeira delas., Detalhe curto para o payload do evento, no mesmo idioma de `subscriptions.py`.…, Handshake de life-bit com o PLC, por conexão (ADR-009, RF-206). Pressupõe…, Cria a task do watchdog e retorna já. (+2 more)

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
Cohesion: 0.15
Nodes (17): NoLeitura, NoMpc, NoTfs, portasFixas(), VariavelMv, VariavelRestricao, Props, LinhaResumo() (+9 more)

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

### Community 117 - "await_until"
Cohesion: 0.14
Nodes (41): Config de `opc_read` e `opc_write` — idêntica; quem discrimina é…, TagConfig, Bancada, esperar_valor(), make_config(), of_kind(), publicar(), Any (+33 more)

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
Cohesion: 0.29
Nodes (10): ADMIN, adminApi(), adminToken(), ensureOperator(), fazerLogin(), OPERATOR, RUN_ID, garantirSentinela() (+2 more)

### Community 124 - "contracts_export.py"
Cohesion: 0.22
Nodes (13): MpcState, Publicado em `mpc.state.<flow_id>.<block_id>` a cada execução (spec F4 §5.1,…, build_contracts(), main(), Fonte única dos contratos de porta por bloco + payloads do WS, exportados como…, Monta o payload completo (porta + WS) — puro, sem I/O., test_json_tem_os_5_tipos_de_bloco(), test_main_imprime_json_valido_com_as_duas_secoes() (+5 more)

### Community 125 - "Semantica de exec_order e tabela de portas persistente"
Cohesion: 0.29
Nodes (8): Invariante: execucao estrita por exec_order crescente, E2E-F3-03: ACEITE jitter — Script+TFS a Ts=0,5 s, p95 do desvio de fronteira < 50 ms, E2E-F3-05: exec_order invertido => atraso deterministico de 1 varredura + warnings no save, Semantica de exec_order e tabela de portas persistente, RF-307: exec_order presente, unico, contiguo 1..N, RF-401: execucao em ordem de exec_order por varredura, FlowTask/scheduler com deadline absoluto, Aplicar-na-fronteira (determinismo RF-401)

### Community 126 - "conftest.py"
Cohesion: 0.26
Nodes (11): db_engine(), db_session(), migrated_database_url(), fixture, Fixtures compartilhadas (spec F1 §9): Timescale real via testcontainers,…, Transação externa + sessão em SAVEPOINT: commit dentro do teste não vaza (spec…, decode_responses=True é contrato da F2: todo consumidor recebe str, não bytes., redis_client() (+3 more)

### Community 127 - "Contrato de canais do barramento (PRD §7.1)"
Cohesion: 0.18
Nodes (12): Regra do Estado Publicado (comandado × confirmado), Regra da Plaqueta (rótulos caps + Archivo Narrow + tracking), Assinatura 'tinta que ainda não secou' (predição tracejada desvanecendo), Plano F2 — Aquisição, Plano F3 — Motor + canvas, Contrato de canais do barramento (PRD §7.1), Predição publicada em mpc.state.*, não persistida (RF-625, ADR-016), Vocabulário kind do canal events (match por kind, mensagens pt-BR) (+4 more)

### Community 129 - "Serviço api (FastAPI, porta interna 8000)"
Cohesion: 0.29
Nodes (11): Serviço api (FastAPI, porta interna 8000), Serviço flow-runtime (porta interna 8002), Serviço frontend (nginx, única porta exposta), Serviço opc-worker (porta interna 8001), Serviço recorder (porta interna 8003), Serviço redis (barramento pub/sub, redis:7.4-alpine), Serviço timescaledb (timescale/timescaledb:2.17.2-pg17), Barramento (Redis pub/sub: opc.values.*, opc.writes) (+3 more)

### Community 130 - "generate-contracts.mjs"
Cohesion: 0.29
Nodes (10): ARQUIVO_SAIDA, interfaceDe(), interfacesWsPayloads(), main(), nomeDoRef(), RAIZ_REPO, rodarExportadorPython(), tabelaPortContracts() (+2 more)

### Community 131 - "schemas/connections.py"
Cohesion: 0.24
Nodes (9): model_validator, ConnectionCreate, _ConnectionFields, ConnectionOut, ConnectionUpdate, BaseModel, Schemas de conexões OPC-UA (RF-201, ADR-009/021): senha só entra, nunca sai…, Regras de coerência; o ValueError vira 422 no FastAPI. (+1 more)

### Community 132 - "bloco"
Cohesion: 0.18
Nodes (11): ScriptBlock, bloco(), RF-514: saídas verbatim da última varredura boa e cópia-mestre intacta. A…, Decisão A-5: `True` vira 1.0 antes do IPC. `IN1 is True` é a única checagem de…, Decisão A-6: valor conhecido com flag ruim executa o script e contamina a saída., RF-512: parar o flow zera o estado; as saídas voltam a `null`., test_dedupe_de_script_error_por_periodo_de_falha(), test_entrada_booleana_chega_como_float() (+3 more)

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

### Community 140 - "schemas/flows.py"
Cohesion: 0.29
Nodes (9): FlowCreate, FlowDetail, FlowOut, FlowSaved, FlowUpdate, BaseModel, Schemas de flows (RF-302/306/307): CRUD do diagrama de blocos e envelope do…, Linha da lista (spec §5.1): sem `graph_json`, que por flow pode ser grande. (+1 more)

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

### Community 145 - "FakeClock"
Cohesion: 0.22
Nodes (14): FakeClock, datetime, Fora de AUTO, `prediction` é vazia e ancorada no PRÓPRIO `ts` do quadro — nunca…, `prediction.ts` é a fronteira em que `host.dispatch()` foi chamado — nunca o…, `host.dispatch()` recusando (worker ocupado/morto, spec §3.5) não pode mover a…, Clock controlado (spec F5 §2.1, tarefa 1.2): cada chamada devolve o próximo…, Clock controlado (spec F5 §2.1-1): `ts` publicado em cada fronteira vem do…, Mudança de modo publica fora da fronteira (spec F4 §5.2): `ts` é o instante da… (+6 more)

### Community 146 - "_DropOldestBuffer"
Cohesion: 0.15
Nodes (10): _DropOldestBuffer, Any, async_sessionmaker, AsyncSession, Redis, Table, Grava o conteúdo atual do buffer e só então o remove de lá., INSERT multi-linha, fatiado no teto de binds do asyncpg; nunca um INSERT por… (+2 more)

### Community 147 - "ottima_flow_runtime/main.py"
Cohesion: 0.26
Nodes (12): build_event_listener(), Assinante do canal `events` com os dois `kind` que o runtime consome (§2.2-8).…, check_database(), check_redis(), _heartbeat_loop(), lifespan(), FastAPI, Serviço flow-runtime: lifespan com supervisor e `/health` por flow (RNF-07,… (+4 more)

### Community 148 - "scripts"
Cohesion: 0.25
Nodes (8): scripts, build, dev, e2e, generate:api, generate:contracts, preview, test:unit

### Community 149 - "routers/history.py"
Cohesion: 0.16
Nodes (16): HistoryResponse, HistoryResponse, HistorySeries, BaseModel, Schema colunar do histórico (RF-802): formato consumido direto pelo uPlot no…, _as_utc(), _e_tag_id(), get_history() (+8 more)

### Community 150 - "eventos"
Cohesion: 0.25
Nodes (8): eventos(), PubSub, E2E-F3-10 em unidade: antes do 1º sucesso não há saída para manter., Spec §3.0: entrada sem valor não executa — provado pelo contador no `state`., Eventos já publicados, terminando no sentinela — a ordem de entrega numa…, test_cold_start_nao_chama_o_script(), test_erro_desde_a_primeira_varredura_deixa_saidas_nulas(), test_transicao_erro_para_timeout_emite_os_dois_eventos()

### Community 151 - "processo_vivo"
Cohesion: 0.25
Nodes (8): processo_vivo(), RF-514: o orçamento estourado mata o processo e o pool volta ao tamanho nominal., Achado C2 da revisão F3: `FlowTask.stop()` cancela a varredura no `to_thread`.…, Achado 2 do fix round 1 (revisão da tarefa 0.6): o `_replace` blindado por…, test_cancelamento_no_meio_do_script_mata_o_worker_e_re_poe_o_pool(), test_mais_chamadas_simultaneas_que_workers_completam_todas(), test_pool_timeout_mata_o_worker_e_re_sobe(), test_stop_durante_replace_em_voo_nao_deixa_processo_orfao()

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

### Community 158 - "ottima_recorder/main.py"
Cohesion: 0.20
Nodes (11): check_redis(), _heartbeat_loop(), lifespan(), FastAPI, Serviço recorder: /health + heartbeat de Redis (F1) e o pipeline de gravação…, Faz ping no Redis e registra o resultado em app.state.redis_ok., Repete o ping no Redis a cada HEARTBEAT_INTERVAL_S segundos., Sobe Redis, banco, pipeline e heartbeat; encerra na ordem inversa. (+3 more)

### Community 159 - "test_snapshot.py"
Cohesion: 0.13
Nodes (22): publish(), pubsub_client_ids(), datetime, fixture, Redis, Contratos do espelho de valores do flow-runtime (RF-401, spec F3 §2.1, §3.0,…, Exceção no laço vira reassinatura com espera, não perda permanente do espelho.…, Publica um `OpcValue` e devolve quantos assinantes o receberam. (+14 more)

### Community 160 - "Plano F5a — Operação: dados & serviços"
Cohesion: 0.15
Nodes (12): Aderência (DoD do plano F5a), Contratos verbatim (PRD §7.1 v1.3 — vigente após a tarefa 0.1), Etapa 0 — Emendas documentais e débitos de contrato (spec §1.3 e §4.3; antes de qualquer código de feature), Etapa 1 — Contratos: `ts` e `prediction.ts` (spec §2.1; F5R-01), Etapa 2 — Hypertable `mpc_samples` e recorder (spec §2.2/§2.3), Etapa 3 — APIs novas, WS `events` e `script_recovered` (spec §2.4/§4.1/§4.2/§5/§7.2-2), Etapa 4 — F-1: boot assíncrono do worker e reescopo do lock (spec §6; F5R-05/06), Etapa 5 — Integração L2 e fechamento do plano F5a (+4 more)

### Community 163 - "api/tests/test_tags.py"
Cohesion: 0.60
Nodes (5): _conexao(), test_cria_lista_filtra(), test_nome_duplicado_na_conexao_409(), test_patch_e_delete(), test_validacoes_e_papeis()

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

### Community 173 - "pool"
Cohesion: 0.40
Nodes (5): bus(), pool(), fixture, Redis, Pool de 2 workers. Dois e não um: quando um teste mata um worker por timeout, a…

### Community 174 - "sim"
Cohesion: 0.40
Nodes (4): fixture, OpcSimServer, Fixtures compartilhadas dos testes do opc-worker. O helper de espera…, sim()

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

### Community 188 - "api-types.ts"
Cohesion: 0.25
Nodes (7): ADR-0021, components, $defs, operations, paths, ADR-0017, webhooks

### Community 190 - "ValueSubscription"
Cohesion: 0.11
Nodes (18): DataChangeNotif, Subscription de valores viva; None fora de `up`., coerce_value(), Any, Node, TagConfig, Uma subscription por conexão, com um monitored item por tag `direction='r'`., Subscription do asyncua criada por `start()`; None antes de subir ou após parar. (+10 more)

### Community 215 - "FlowStatusHub"
Cohesion: 0.09
Nodes (16): _flow_id_of(), flow_status_ws(), FlowStatusHub, _mpc_id_of(), Redis, Assinatura única de `flow.status.*` e `mpc.state.*` roteando aos sockets…, Assina os dois padrões e sobe as tasks de leitura; retorna já. Idempotente. O…, Para os laços, encerra as inscrições e fecha os sockets restantes. Nunca… (+8 more)

### Community 272 - "Settings"
Cohesion: 0.10
Nodes (28): AsyncEngine, BaseSettings, get_settings(), Configuração via variáveis OTTIMA_* (spec F1 §7.2)., Valida os segredos no boot: a chave de assinatura JWT é fatal, a Fernet é…, Settings, validate_secrets(), create_engine() (+20 more)

### Community 275 - "pipeline.py"
Cohesion: 0.11
Nodes (12): health(), get, Sempre 200: a degradação vai no corpo (spec §2.2-10). Sem lifespan (app cru dos…, health(), Sempre 200: a degradação vai no corpo (spec F2 §2.2-8). Sem lifespan (app cru…, health(), Sempre 200: a degradação vai no corpo (spec F2 §2.2-8/§6.6). Sem pipeline…, datetime (+4 more)

### Community 276 - "FakeHost"
Cohesion: 0.33
Nodes (3): FakeHost, Duplo de `MpcHost` — mesmo protocolo (`ready`/`dispatch`/`poll`/`stats`), sem…, SolveRequest

### Community 277 - "FakeSnapshot"
Cohesion: 0.40
Nodes (3): FakeSnapshot, Duplo de `ValueSnapshot` — só o `.get()` síncrono que o bloco usa., TagValue

### Community 279 - "test_ws_mpc.py"
Cohesion: 0.15
Nodes (15): connect(), hub(), make_token(), operator_token(), FastAPI, fixture, WebSocket `/ws`: fanout de `mpc.state.<flow_id>.<block_id>` (spec F4 §6.2,…, Payload de varredura do §4.2, com `ports` preenchido como o runtime publica. (+7 more)

### Community 281 - "setup_planta.py"
Cohesion: 0.23
Nodes (18): config_mpc(), criar_tags(), env_deploy(), ganho_recomendado(), login(), main(), montar_grafo(), montar_modelos() (+10 more)

### Community 285 - "schemas/events.py"
Cohesion: 0.40
Nodes (4): EventOut, BaseModel, Schema de leitura do log de eventos (RF-803): as mesmas 5 chaves do canal…, Schemas Pydantic compartilhados entre a API e os workers.

### Community 286 - "schemas/tags.py"
Cohesion: 0.47
Nodes (5): BaseModel, Schemas de tags OPC (RF-203): nome lógico, node_id, direção, tipo, EU e…, TagCreate, TagOut, TagUpdate

### Community 287 - "planta_virtual/supervisor_mpc.py"
Cohesion: 0.31
Nodes (16): agora(), alvos(), aplicar_sp(), armar(), _env(), estado_bloco(), flow_id(), log() (+8 more)

### Community 289 - "_config"
Cohesion: 0.67
Nodes (3): _config(), MpcConfig, 1 CV + 2 MVs (uma com `pid`, outra direta) — cobre a tabela de modos inteira.…

### Community 293 - "plant_ops.py"
Cohesion: 0.42
Nodes (8): caminhos(), chamar_metodo(), _com_cliente(), escrever(), _formatar(), main(), Todos os nos de processo lidos pelo `snapshot`, na ordem de exibicao., snapshot()

### Community 295 - "FlowStatus"
Cohesion: 0.12
Nodes (17): FlowStatus, PortValue, Valor de uma porta de bloco numa varredura (spec F3 §4.2, decisão A-3)., test_flow_status_aceita_ports_vazio_em_transicao_de_estado(), test_flow_status_com_ports_serializa_verbatim_spec_f3_42(), test_nomes_de_canais_prd_71(), test_payloads_verbatim_prd_71(), test_port_value_preserva_bool_e_float_no_round_trip() (+9 more)

### Community 296 - "schemas/auth.py"
Cohesion: 0.38
Nodes (6): LoginIn, LoginOut, BaseModel, Schemas de autenticação (spec F1 §5.1): entrada de login e saída de…, Usuário exposto pela API — nunca inclui password_hash., UserOut

### Community 298 - "BaseModel"
Cohesion: 0.31
Nodes (9): MpcModes, MpcPrediction, MpcStatus, MpcVarState, BaseModel, Estado publicado de uma variável do MPC (spec F4 §5.1) — `sp` só existe em CV…, test_mpc_var_state_sp_e_opcional_e_default_none(), mpc_state_json() (+1 more)

### Community 303 - "_block"
Cohesion: 0.18
Nodes (16): _block(), Events, SolveResult, `reset()` (hot-swap/stop) zera `self._overruns` (blocks/mpc.py:234) — o evento…, `worker.py::_handle` isola uma exceção de UM pedido e devolve `status="error"`…, O MESMO `status="error"` — mas desta vez `host.stats()["respawns"]` avançou: é…, Como `_resultado_ok`, mas com `prediction_mv` populado — os testes de ts…, _resultado_com_predicao() (+8 more)

## Knowledge Gaps
- **467 isolated node(s):** `When to use graph tools FIRST`, `Key Tools`, `Workflow`, `POS`, `TAGS` (+462 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **84 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TagRef` connect `TagRef` to `flowgraph/__init__.py`, `test_flowgraph.py`, `test_flowgraph_mpc.py`, `mpc_golden_export.py`, `routers/flows.py`, `MpcConfig`, `ScriptPool`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Why does `MpcConfig` connect `MpcConfig` to `worker.py`, `flowgraph/__init__.py`, `test_flowgraph.py`, `build_mpc`, `test_mpc_builder.py`, `mpc_golden_export.py`, `TagRef`, `operate.py`, `MpcHost`, `test_mpc_load.py`, `mpc_config.py`, `ScriptPool`, `test_mpc_worker.py`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Why does `ConnectionRuntime` connect `ConnectionRuntime` to `logging.py`, `_SupersededAttemptError`, `ConnectionConfig`, `WatchdogTask`, `ValueHeartbeat`, `ottima_opc_worker/connection.py`, `ValueSubscription`?**
  _High betweenness centrality (0.021) - this node is a cross-community bridge._
- **Are the 136 inferred relationships involving `await_until()` (e.g. with `test_bloco_identico_mantem_o_estado_interno_do_tfs()` and `test_bloco_removido_desaparece_e_bloco_novo_nasce_null()`) actually correct?**
  _`await_until()` has 136 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `MpcConfig` (e.g. with `TagRef` and `ValidationResult`) actually correct?**
  _`MpcConfig` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `When to use graph tools FIRST`, `Key Tools`, `Workflow` to the rest of the system?**
  _467 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `api.ts` be split into smaller, more focused modules?**
  _Cohesion score 0.05131313131313131 - nodes in this community are weakly interconnected._