# Graph Report - ottimaSystemV3  (2026-08-04)

## Corpus Check
- 291 files · ~192,852 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3661 nodes · 8791 edges · 197 communities (166 shown, 31 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 767 edges (avg confidence: 0.71)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `470eae05`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- await_until
- graph.ts
- channel_flow_status
- opc-worker/tests/test_supervisor.py
- WriteConsumer
- api.ts
- test_flow_commands.py
- test_blocks.py
- flow-runtime
- FlowEditorPage.tsx
- test_heartbeat.py
- test_flowgraph.py
- FakeClock
- flowgraph.py
- FlowTask
- OpcSimServer
- FlowStatusHub
- test_tfs.py
- ConnectionRuntime
- Settings
- ottima_opc_worker/state.py
- f3_support.py
- Supervisor
- test_flows.py
- opc-worker/tests/test_security.py
- test_failure.py
- test_pipeline.py
- PortSample
- await_until
- test_certificates.py
- User
- TagsPage.tsx
- e2e/conftest.py
- ConnectionForm.tsx
- .write
- ScriptPool
- test_backpressure.py
- test_f3_engine.py
- ConnectionConfig
- generate_app_certificate
- Spec F4 — Bloco MPC (config, montagem, runtime e modos)
- ConnectionSnapshot
- RecorderPipeline
- TrendPage.tsx
- Supervisor
- routers/connections.py
- TfsBlock
- test_subscriptions.py
- ValueHeartbeat
- ModalConfigBloco.tsx
- models/__init__.py
- certs.py
- routers/tags.py
- test_server.py
- EventStream
- routers/projects.py
- HTTPException
- _get
- ValueSnapshot
- RuntimeState
- Ambiente
- ottima_core/security.py
- ValueSubscription
- FlowDefinition
- bus.py
- FlakyRedis
- compilerOptions
- test_script.py
- devDependencies
- opc-worker/tests/test_health.py
- routers/history.py
- deps.py
- generate_app_cert
- dependencies
- Contrato de canais do barramento (PRD §7.1)
- _Rejected
- ChannelListener
- ottima_recorder/main.py
- Any
- WatchdogTask
- _DropOldestBuffer
- ADR-012 — Projeto como unidade de agrupamento e portabilidade (JSON)
- schemas/events.py
- api/tests/test_events.py
- __main__.py
- ottima_opc_worker/connection.py
- RF-206/207 watchdog por conexão e política de falha
- test_api_e2e.py
- fixtures.ts
- ottima_flow_runtime/main.py
- Serviço api (FastAPI, porta interna 8000)
- conftest.py
- ADR-010 — Modos LOCAL/REMOTO e MAN/AUTO com transferência bumpless
- ADR-014 — Orçamento de tempo do MPC e multiplicador de execução
- Log de eventos persistido
- OpcWriteBlock
- RF-304 hot-swap atômico na próxima varredura (ADR-011)
- ADR-001…024 (decisões de arquitetura normativas)
- PRD OttimaSystem v1.2 (requisitos, contratos, fases)
- schemas/connections.py
- parse_graph
- ottima_opc_worker/main.py
- RNF-09 suíte de malha fechada MPC↔TFS
- Editor canvas (React Flow re-vestido, MPC desabilitado badge F4)
- ADR-013 — Modelo do MPC: matriz SOPDT + processo integrador; horizontes derivados do TSS
- PRD §4 domain model: User, Project, OpcConnection, Tag, Flow, Block/Edge in graph_json, Event and Sample hypertables
- CLAUDE.md (archived) — OttimaSystem agent operating rules
- router.tsx
- errors_of
- schemas/flows.py
- ottima_flow_runtime/supervisor.py
- Barramento interno Redis pub/sub
- Hot-swap de flows entre varreduras
- Decision: two mode axes — LOCAL/REMOTO (PID vs MPC, bumpless both ways via PID mode writes AUTO<->RCAS/CAS/ROUT) and MAN/AUTO sub-mode of REMOTO; MV tracking in LOCAL
- Decision: Redis pub/sub internal bus (opc.values.<conn_id> out, opc.writes in)
- Decision: per-pair model matrix (MV->CV, DV->CV); response type per CV — self-regulating SOPDT(K,t1,t2,th) or integrating (Ki,th); Np/Nc derived from TSS, not user-edited; hard MV limits and rate limit
- PRD.md (archived) — OttimaSystem product requirements v1.0
- test_auto_laco_e_ciclo
- .fire
- schemas/auth.py
- schemas/tags.py
- ws.py
- flow-runtime/tests/test_events.py
- index.tsx
- useHistory.ts
- Decision: solver timeout ~70% of effective Ts_mpc — on overrun keep last MV, raise alarm, skip to next scan; per-block multiplier N (Ts_mpc = N x Ts_flow)
- Decision: per-connection watchdog with two OPC bits (read+write), crossed NOT, frozen >10s declares comm failure; failure stops writes and flows
- Decision: fifth palette block TFS — transfer-function matrix up to 2x2, each element SOPDT or IOPDT, discrete-time at flow Ts, persistent internal state
- scripts
- env.py
- cert_servidor
- status_to_quality
- Plano F4a — MPC: config & montagem
- Stack compose 'ottima' (7 serviços de produção)
- ADR-003 — Postgres/TimescaleDB único, retenção de 1 mês
- app.py
- test_tags.py
- StubPool
- app
- Plano F4b — MPC: runtime & modos
- api-types.ts
- Retenção 1 mês + continuous aggregate (RF-801, ADR-003)
- Gate E2E em 3 camadas (L1 smoke, L2 pytest e2e, L3 browser/Playwright)
- Bloco Python-Script (RF-511..514, ADR-018)
- Decision: live flow edits take effect on the next scan without interruption; no flow versioning
- package.json
- ottima-core
- logging.py
- StubSessionFactory
- Harness
- backoff_delay
- _SupersededAttemptError
- SwitchableFactory
- ExplodingRuntime
- ConnectionRuntime (máquina connecting→up→failed, backoff + jitter)
- Campo grafite (paleta neutra escura dessaturada)
- Bumpless (transferência sem salto na MV)
- Scan cycle (avaliação a cada Ts em ordem de exec_order)
- ADR-023 — Escopo de plataforma da v1: pt-BR, auth local, HTTP interno, Compose on-prem
- Camadas L1/L1s/L2/L3 e 19 cenários do gate da F1
- .functional_config
- api/tests/test_health.py
- @tanstack/react-query
- @xyflow/react
- .now
- entrypoint-api.sh
- smoke.sh
- Faceplates com barras verticais PV/SP/OUT (convenção intocável)
- Filosofia ISA-101 (cor reservada a estado)
- react
- blocks/__init__.py
- ottima_recorder/__init__.py
- Regra do Azul Único (uma cor de interação, nunca codifica dado)
- Monorepo layout: docs/, frontend/, packages/ottima-core, services/{api,opc-worker,flow-runtime,recorder}, deploy/, tests/ as uv workspace
- Hot-swap (edição aplicada atomicamente na próxima varredura)
- Hypertable (tabela particionada por tempo, retenção 1 mês)
- Loop vivo (task asyncio contínua, nunca job de fila)
- Projeto (N armazenados, 1 ativo por vez)
- Restrição (variável em faixa com precedência sobre CVs)
- Grupos de API (PRD §7.3)
- Fases de implementação F1–F6 (PRD §8)
- JSON de projeto export/import (PRD §7.2)
- Infra de testes (testcontainers + rollback por SAVEPOINT)
- Heartbeat de valor (republicação a cada 10 s)
- opcsim
- ottima-workspace
- Princípio: operação e engenharia são mundos distintos
- v1: reescrita completa do sistema legado Django, sem compatibilidade

## God Nodes (most connected - your core abstractions)
1. `OpcSimServer` - 103 edges
2. `ConnectionSnapshot` - 76 edges
3. `await_until()` - 75 edges
4. `ConnectionRuntime` - 72 edges
5. `PortSample` - 55 edges
6. `base_graph()` - 50 edges
7. `ConnectionConfig` - 50 edges
8. `Supervisor` - 46 edges
9. `publish_event()` - 42 edges
10. `await_until()` - 42 edges

## Surprising Connections (you probably didn't know these)
- `Rodada de gate da F2 (L1 + L2 + L3 browser-tool)` --semantically_similar_to--> `Gate E2E em 3 camadas (L1 smoke, L2 pytest e2e, L3 browser/Playwright)`  [INFERRED] [semantically similar]
  docs/plans/F2-aquisicao.md → CLAUDE.md
- `Rodada de gate da F3 (L2 = 24 cenários)` --semantically_similar_to--> `Gate E2E em 3 camadas (L1 smoke, L2 pytest e2e, L3 browser/Playwright)`  [INFERRED] [semantically similar]
  docs/plans/F3-motor-canvas.md → CLAUDE.md
- `Segurança de processo: escrita só com deploy + watchdog vivo + REMOTO; boot parado` --semantically_similar_to--> `RNF-03 segurança de processo (escrita só com deploy + watchdog + REMOTO)`  [INFERRED] [semantically similar]
  CLAUDE.md → docs/PRD.md
- `Princípio: falhar para o lado seguro é inegociável` --semantically_similar_to--> `Segurança de processo: escrita só com deploy + watchdog vivo + REMOTO; boot parado`  [INFERRED] [semantically similar]
  PRODUCT.md → CLAUDE.md
- `Script block: escopo math+numpy, timeout ~70% do Ts, state persistente (ADR-018)` --semantically_similar_to--> `Bloco Python-Script (RF-511..514, ADR-018)`  [INFERRED] [semantically similar]
  CLAUDE.md → docs/PRD.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Barramento Redis pub/sub (produtores e consumidores no compose)** — deploy_docker_compose_redis, deploy_docker_compose_api, deploy_docker_compose_opc_worker, deploy_docker_compose_flow_runtime, deploy_docker_compose_recorder [EXTRACTED 1.00]
- **Gate E2E de 3 camadas (L1 smoke / L2 pytest e2e / L3 browser)** — claude_gate_e2e, docs_specs_f1_testes_e2e_camadas, docs_specs_f2_aquisicao_gate, docs_specs_f3_motor_canvas_gate [EXTRACTED 1.00]
- **Aceitação de malha fechada MPC↔TFS (RNF-09)** — docs_prd_rnf09, docs_prd_mpc_bloco, docs_prd_tfs_bloco, claude_tdd_malha_fechada, tests_readme_mpc_tfs_destino [EXTRACTED 1.00]
- **Pipeline de dados: opc-worker publica no barramento Redis; flow-runtime, recorder e FastAPI consomem** — docs_adr_adr_006_separacao_opc_worker_flow_runtime_opc_worker, docs_adr_adr_002_barramento_redis_pubsub_redis_pubsub_bus, docs_adr_adr_006_separacao_opc_worker_flow_runtime_flow_runtime, docs_adr_adr_006_separacao_opc_worker_flow_runtime_recorder [EXTRACTED 1.00]
- **Subsistema MPC: formulário de configuração, modelo SOPDT/integrador, orçamento de solver, categorias de variáveis e simulação TFS** — docs_adr_adr_008_mpc_config_formulario_abas_formulario_mpc_abas, docs_adr_adr_013_modelo_sopdt_tss_integrador_matriz_sopdt, docs_adr_adr_014_orcamento_solver_multiplicador_timeout_solver_70pct, docs_adr_adr_014_orcamento_solver_multiplicador_multiplicador_execucao_mpc, docs_adr_adr_019_cv_sp_restricoes_por_faixa_precedencia_categorias_variaveis_mpc, docs_adr_adr_022_bloco_tfs_simulacao_bloco_tfs [INFERRED 0.85]
- **Padrão failsafe: watchdog de comunicação, boot parado, overrun visível e trilha de eventos protegem a planta** — docs_adr_adr_009_watchdog_bit_alternante_watchdog_bit_alternante, docs_adr_adr_009_watchdog_bit_alternante_failsafe_para_escrita, docs_adr_adr_017_projeto_ativo_unico_boot_parado_boot_parado_deploy, docs_adr_adr_014_orcamento_solver_multiplicador_politica_overrun, docs_adr_adr_020_log_eventos_sem_ack_log_eventos_persistido [INFERRED 0.75]
- **Process-safety write gate: watchdog alive + REMOTO mode + explicit deploy after boot** — docs_archive_adr_adr_009_watchdog_bit_alternante_decisao, docs_archive_adr_adr_010_modos_local_remoto_man_auto_bumpless_decisao, docs_archive_adr_adr_017_projeto_ativo_unico_boot_parado_decisao, docs_archive_prd_seguranca_processo [EXTRACTED 1.00]
- **Closed-loop MPC<->TFS acceptance suite: bumpless, constraint precedence, overrun, hot-swap without hardware** — docs_archive_adr_adr_022_bloco_tfs_simulacao_decisao, docs_archive_adr_adr_010_modos_local_remoto_man_auto_bumpless_decisao, docs_archive_adr_adr_014_orcamento_solver_multiplicador_decisao, docs_archive_adr_adr_019_cv_sp_restricoes_por_faixa_precedencia_decisao, docs_archive_adr_adr_011_hot_swap_sem_versionamento_decisao, docs_archive_prd_malha_fechada_aceitacao [EXTRACTED 1.00]
- **Redis pub/sub bus ecosystem: decoupled producers/consumers, state-published UI, prediction and event fanout channels** — docs_archive_adr_adr_002_barramento_redis_pubsub_decisao, docs_archive_adr_adr_006_separacao_opc_worker_flow_runtime_decisao, docs_archive_adr_adr_016_tela_operacao_faceplate_tendencia_predicao_decisao, docs_archive_adr_adr_020_log_eventos_sem_ack_decisao, docs_archive_prd_contratos_barramento [EXTRACTED 1.00]
- **Redis pub/sub bus: producer and consumer processes** — docs_ottimasystem_docsv1_1_adr_adr_002_barramento_redis_pubsub_redis_pubsub, docs_ottimasystem_docsv1_1_adr_adr_006_separacao_opc_worker_flow_runtime_opc_worker, docs_ottimasystem_docsv1_1_adr_adr_006_separacao_opc_worker_flow_runtime_flow_runtime, docs_ottimasystem_docsv1_1_adr_adr_006_separacao_opc_worker_flow_runtime_recorder [EXTRACTED 1.00]
- **Flow execution semantics (scan cycle, exec_order, hot-swap, solver budget)** — docs_ottimasystem_docsv1_1_adr_adr_007_scan_cycle_ts_por_flow_scan_cycle, docs_ottimasystem_docsv1_1_adr_adr_024_ordem_execucao_explicita_exec_order, docs_ottimasystem_docsv1_1_adr_adr_011_hot_swap_sem_versionamento_hot_swap, docs_ottimasystem_docsv1_1_adr_adr_014_orcamento_solver_multiplicador_solver_budget [EXTRACTED 1.00]
- **Docker Compose on-prem v1 service topology** — docs_ottimasystem_docsv1_1_adr_adr_023_escopo_plataforma_v1_docker_compose, docs_ottimasystem_docsv1_1_adr_adr_001_fastapi_all_in_fastapi, docs_ottimasystem_docsv1_1_adr_adr_003_timescaledb_unico_retencao_1mes_timescaledb, docs_ottimasystem_docsv1_1_adr_adr_002_barramento_redis_pubsub_redis_pubsub, docs_ottimasystem_docsv1_1_adr_adr_006_separacao_opc_worker_flow_runtime_opc_worker, docs_ottimasystem_docsv1_1_adr_adr_006_separacao_opc_worker_flow_runtime_flow_runtime, docs_ottimasystem_docsv1_1_adr_adr_006_separacao_opc_worker_flow_runtime_recorder [EXTRACTED 1.00]

## Communities (197 total, 31 thin omitted)

### Community 0 - "await_until"
Cohesion: 0.06
Nodes (113): FlowStatus, await_until(), collect(), Collector, counter_graph(), counters(), create_connection(), create_flow() (+105 more)

### Community 1 - "graph.ts"
Cohesion: 0.07
Nodes (50): Editor(), alcanca(), ArestaSerializada, avisosInversao(), Bloco, BlocoEdge, POS, TAGS (+42 more)

### Community 2 - "channel_flow_status"
Cohesion: 0.05
Nodes (61): channel_flow_status(), admin_headers(), make_user(), operator_headers(), fixture, Fixtures da API: settings de teste, app com get_db/get_redis sobrescritos,…, Settings isoladas do .env local, com segredos determinísticos de teste., Cria usuários direto no banco da sessão de teste (senha já em Argon2id). (+53 more)

### Community 3 - "opc-worker/tests/test_supervisor.py"
Cohesion: 0.10
Nodes (68): Snapshot em memória do worker inteiro; a fonte do /health (spec §2.2-8)., WorkerState, CancellingRuntime, Contador, contar_mensagens_vistas(), contar_passadas(), create_connection(), create_project() (+60 more)

### Community 4 - "WriteConsumer"
Cohesion: 0.08
Nodes (31): BlockReason, OpcWrite, RejectReason, Tag configurada de uma conexão., TagConfig, _BlockedPeriod, _cancel(), coerce_value() (+23 more)

### Community 5 - "api.ts"
Cohesion: 0.07
Nodes (49): ADR-0007, ADR-0015, HomePage(), AuthContext, AuthProvider(), AuthState, CelulaDesejado(), COLUNAS (+41 more)

### Community 6 - "test_flow_commands.py"
Cohesion: 0.08
Nodes (56): eventos(), Assinante do canal `events` num segundo cliente, como faz o worker (ADR-020).…, _admin_id(), _conexao(), _projeto(), Auditoria da API no canal `events` (ADR-020, spec F2 §7.2): o que emite e o que…, CRUD de users, CRUD de projects sem ativação e qualquer GET: canal silencioso…, Trocar `dependencies=[require_admin]` pelo parâmetro nomeado não pode afrouxar… (+48 more)

### Community 7 - "test_blocks.py"
Cohesion: 0.08
Nodes (43): OpcReadBlock, Sem entradas; saída `out`. Invalidez (§3.1) é conservadora: `quality != 0`…, Último valor conhecido de uma tag, como veio do barramento. `value` continua…, TagValue, _AccumulatorBlock, bus(), drain(), FakeSnapshot (+35 more)

### Community 8 - "flow-runtime"
Cohesion: 0.06
Nodes (57): ADR-001 — FastAPI all-in (abandono do Django), FastAPI all-in (API + WebSocket + workers async), SQLAlchemy 2.0 async, ADR-002 — Barramento interno via Redis pub/sub, Canais do barramento: opc.values.<conn_id> / opc.writes, Redis pub/sub (barramento interno), ADR-003 — Postgres/TimescaleDB único, retenção de 1 mês, Retenção de 1 mês + continuous aggregates (+49 more)

### Community 9 - "FlowEditorPage.tsx"
Cohesion: 0.06
Nodes (44): ADR-0023, AGUARDO, CabecalhoAoVivo(), COR_LAMPADA, LampadaEstado(), novoId(), ADR-0011, ADR-0024 (+36 more)

### Community 10 - "test_heartbeat.py"
Cohesion: 0.18
Nodes (28): beating(), collect_values(), heartbeat_tags(), make_config(), make_runtime(), of_tag(), fixture, MonkeyPatch (+20 more)

### Community 11 - "test_flowgraph.py"
Cohesion: 0.13
Nodes (51): base_graph(), edge_of(), has(), node_of(), off(), parse_errors(), Mesa de casos de `ottima_core.flowgraph` (RF-302/307, ADR-024, spec F3 §5.2).…, Alguma mensagem contém todos os fragmentos. (+43 more)

### Community 12 - "FakeClock"
Cohesion: 0.11
Nodes (44): events_of(), FakeClock, flow(), fixture, Redis, Contratos do laço de varredura (RF-401/402/404, ADR-004/007/024, spec F3 §2.2,…, Fábrica de assinantes: devolve a lista que recebe os payloads crus de um canal., Fábrica de FlowTask já rodando e dormindo na primeira fronteira. (+36 more)

### Community 13 - "flowgraph.py"
Cohesion: 0.09
Nodes (50): NodeConfig, _check_cycles(), _check_edge_endpoints(), _check_exec_order(), _check_fan_in(), _check_handles(), _check_port_types(), _check_required_inputs() (+42 more)

### Community 14 - "FlowTask"
Cohesion: 0.07
Nodes (21): PortValue, FlowTask, datetime, Redis, Ancora a grade e sobe a task. Idempotente: deploy em rodando é no-op (RNF-05)., Encerra a task. Idempotente e nunca levanta: é caminho de desmonte (RNF-05).…, Falha imposta de fora: `comm_failure` derruba os flows da conexão caída…, Uma varredura: blocos na ordem da tupla, lendo e escrevendo a tabela de portas. (+13 more)

### Community 15 - "OpcSimServer"
Cohesion: 0.08
Nodes (43): Client asyncua vivo; None fora do estado `up`., assert_bit_stable(), await_bit(), await_flips(), connected(), make_config(), make_watchdog(), Client (+35 more)

### Community 16 - "FlowStatusHub"
Cohesion: 0.15
Nodes (12): _close(), _flow_id_of(), FlowStatusHub, PubSub, Redis, Assinatura única de `flow.status.*` roteando para os sockets inscritos (§5.3)., Assina o padrão e sobe a task de leitura; retorna já. Idempotente. O PSUBSCRIBE…, Para o laço, encerra a inscrição e fecha os sockets restantes. Nunca levanta. (+4 more)

### Community 17 - "test_tfs.py"
Cohesion: 0.12
Nodes (44): double_pole(), first_order(), iopdt(), off(), parametrize, Contratos do bloco TFS contra a solução analítica (RF-521/522, ADR-022, spec F3…, Cascata de dois ZOH exatos != ZOH exato do produto. O 2o estágio consome…, Sem excitação não há resposta: entrada 0.0 é valor legítimo, não invalidez. (+36 more)

### Community 18 - "ConnectionRuntime"
Cohesion: 0.06
Nodes (28): build_client(), ConnectionRuntime, _disconnect_quiet(), Client, FailureReason, Conta as reaberturas do gate de escrita; muda ⇒ período de bloqueio novo., Subscription de valores viva; None fora de `up`., Cria a task supervisora da conexão e retorna já. (+20 more)

### Community 19 - "Settings"
Cohesion: 0.16
Nodes (19): BaseSettings, get_settings(), Configuração via variáveis OTTIMA_* (spec F1 §7.2)., Valida os segredos no boot: a chave de assinatura JWT é fatal, a Fernet é…, Settings, validate_secrets(), test_settings_defaults(), test_settings_le_env_com_prefixo() (+11 more)

### Community 20 - "ottima_opc_worker/state.py"
Cohesion: 0.13
Nodes (18): DataValue, Heartbeat de valor de uma conexão: report-by-exception + republicação (spec F2…, _iso_utc(), Any, datetime, Configuração e snapshot em memória das conexões OPC-UA (spec F2 §2.2-2/3/8).…, ISO-8601 em UTC; datetime naive é tratado como UTC (o worker só grava aware)., Último valor conhecido de uma tag. (+10 more)

### Community 21 - "f3_support.py"
Cohesion: 0.10
Nodes (42): compose(), Roda `docker compose` do stack e2e no diretório do deploy. Escopo…, aresta(), assinantes_de_status(), ativar_projeto(), bloco(), elemento_iopdt(), esperar_runtime_saudavel() (+34 more)

### Community 22 - "Supervisor"
Cohesion: 0.09
Nodes (23): FlowCommand, _FlowRuntime, _log_teardown_results(), _project_tags(), Any, AsyncSession, O que o supervisor lembra de um flow que ele já materializou., Mantém as `FlowTask` alinhadas com os comandos e com o banco. (+15 more)

### Community 23 - "test_flows.py"
Cohesion: 0.15
Nodes (38): _aresta(), _cenario(), _conexao(), _flow(), _grafo_read_write(), _mensagens(), _no(), _projeto() (+30 more)

### Community 24 - "opc-worker/tests/test_security.py"
Cohesion: 0.11
Nodes (40): certs_dir(), certs_dir_vazio(), endpoint_mudo(), failures(), falha_unica(), make_config(), pin_server_certificate(), fixture (+32 more)

### Community 25 - "test_failure.py"
Cohesion: 0.15
Nodes (37): BusTrail, assert_bit_estavel(), bad_tag_ids_before(), bad_values(), collect_bus(), events_of_kind(), index_of_first(), make_config() (+29 more)

### Community 26 - "test_pipeline.py"
Cohesion: 0.13
Nodes (35): channel_opc_values(), await_until(), count_rows(), instrumented(), make_pipeline(), purge(), Any, fixture (+27 more)

### Community 27 - "PortSample"
Cohesion: 0.07
Nodes (27): ABC, Block, has_cold_input(), null_outputs(), PortSample, Protocolo comum dos blocos executáveis e as duas regras de base (spec F3 §3.0).…, Valor de uma porta numa varredura. `v is None` é cold start (nunca houve valor…, Bloco de um flow. `block_id` é o id do nó React Flow (chave do hot-swap,… (+19 more)

### Community 28 - "await_until"
Cohesion: 0.17
Nodes (37): await_until(), collecting(), Redis, Helpers compartilhados dos testes do opc-worker. Uma versão única de cada…, Aguarda a condição virar verdadeira, com polling — evita sleep cego nos testes., Assinante de teste de um canal; só devolve depois do SUBSCRIBE confirmado., Bancada, esperar_valor() (+29 more)

### Community 29 - "test_certificates.py"
Cohesion: 0.10
Nodes (34): _admin_id(), _bruto(), _coluna(), _conexao(), _digest(), _projeto_da(), parametrize, API de certificados (RF-202, ADR-021): app cert de instância e trust por… (+26 more)

### Community 30 - "User"
Cohesion: 0.13
Nodes (34): FlowCreate, FlowId, FlowSaved, FlowUpdate, User, ProjectFilter, put, _carregar() (+26 more)

### Community 31 - "TagsPage.tsx"
Cohesion: 0.18
Nodes (20): Select, Props, TagForm(), Valores, COLUNAS, CHAVE, Direcao, FiltrosTags (+12 more)

### Community 32 - "e2e/conftest.py"
Cohesion: 0.09
Nodes (30): FixtureRequest, admin(), _ativar_sentinela(), conexao_health(), _conf(), congelar_watchdog(), _criar_tag(), _deploy_env() (+22 more)

### Community 33 - "ConnectionForm.tsx"
Cohesion: 0.09
Nodes (31): useCanMutate(), AuthMode, ConnectionForm(), Props, SecurityMode, SecurityPolicy, Valores, valoresIniciais() (+23 more)

### Community 34 - ".write"
Cohesion: 0.13
Nodes (9): Server, _generate_certificate(), Any, Node, Path, Gera o par chave/certificado autoassinado do servidor. Bloqueante (RSA 2048)., Lê um node no address space do próprio servidor, sem abrir conexão OPC., Escreve um node no address space do próprio servidor, sem abrir conexão OPC. (+1 more)

### Community 35 - "ScriptPool"
Cohesion: 0.11
Nodes (22): _PoolState, Any, Connection, ProcessPool dedicado ao bloco Script (RF-511..514, ADR-018/004, spec F3 §3.3,…, Alvo do `spawn`: laço de jobs. Nível de módulo porque `spawn` precisa importá-…, Sobe um worker. Roda **numa thread** — nunca no event loop (ADR-004)., Espera um resultado no pipe. Roda **numa thread** — nunca no event loop…, Encerra o processo e fecha o pipe. Roda numa thread; nunca levanta. (+14 more)

### Community 36 - "test_backpressure.py"
Cohesion: 0.11
Nodes (43): await_until(), backpressure(), count_rows(), event_payloads(), events_seen(), get_health(), health_app(), make_pipeline() (+35 more)

### Community 37 - "test_f3_engine.py"
Cohesion: 0.16
Nodes (34): de_varredura(), deploy(), evento_de_bloco(), montar_grafo(), porta(), Client, Evento de bloco carrega o bloco no `origin`: `flow:<id>/block:<bid>` (§4.3)., `PUT` do grafo; devolve os `warnings[]` (RF-307: aviso de inversão não… (+26 more)

### Community 38 - "ConnectionConfig"
Cohesion: 0.11
Nodes (29): AppCertPaths, Caminhos dos três arquivos do certificado de aplicação., CertMismatchError, CertMissingError, _configure_channel(), configure_client(), _configure_identity(), _decrypt_password() (+21 more)

### Community 39 - "generate_app_certificate"
Cohesion: 0.13
Nodes (33): app_cert_paths(), AppCertificateInfo, generate_app_certificate(), Gera o certificado autoassinado de instância de aplicação (spec F2 §5.3).…, Metadados do certificado de aplicação lido do disco., Monta os caminhos do certificado de aplicação, sem tocar no disco., Lê os metadados do certificado de aplicação. Devolve `exists=False` quando o…, read_app_certificate() (+25 more)

### Community 40 - "Spec F4 — Bloco MPC (config, montagem, runtime e modos)"
Cohesion: 0.08
Nodes (24): 10. Aderência ao aceite F4 (PRD §8), 1.1 Dentro da F4, 1.2 Fora da F4 — com destino registrado, 1. Escopo da F4, 2.1 Config no `graph_json` (decisão A-8/A-9), 2.2 Validação (extensão de `ottima_core/flowgraph.py` — mesa pura; reprovações **422** pt-BR, string única), 2. Bloco MPC — config e validação, 3. Montagem do-mpc (dentro do `MpcWorker`; TDD estrito) (+16 more)

### Community 41 - "ConnectionSnapshot"
Cohesion: 0.15
Nodes (38): ConnectionSnapshot, Estado observável de uma conexão; alimenta o `/health` (spec §2.2-8)., fixture, sim(), collect_events(), make_config(), make_runtime(), of_kind() (+30 more)

### Community 42 - "RecorderPipeline"
Cohesion: 0.07
Nodes (25): health(), Sempre 200: a degradação vai no corpo (spec §2.2-10). Sem lifespan (app cru dos…, health(), Sempre 200: a degradação vai no corpo (spec F2 §2.2-8). Sem lifespan (app cru…, health(), Sempre 200: a degradação vai no corpo (spec F2 §2.2-8/§6.6). Sem pipeline…, PubSub, T (+17 more)

### Community 43 - "TrendPage.tsx"
Cohesion: 0.08
Nodes (35): uplot, Card(), Input, Label(), DESCRICAO, ItemPaleta(), Props, ROTULO_BLOCO (+27 more)

### Community 44 - "Supervisor"
Cohesion: 0.07
Nodes (30): _cancel(), _is_hint(), load_active_configuration(), _log_teardown_results(), async_sessionmaker, AsyncSession, Path, PubSub (+22 more)

### Community 45 - "routers/connections.py"
Cohesion: 0.15
Nodes (28): ConnectionCreate, ConnectionOut, ConnectionUpdate, _carregar(), clear_server_certificate(), create_connection(), delete_connection(), _excede_o_declarado() (+20 more)

### Community 46 - "TfsBlock"
Cohesion: 0.10
Nodes (11): TfsElement, _Element, _FirstOrder, _Iopdt, Entradas `u1,u2`; saídas `y1,y2`. `matrix[J][K]` = contribuição de `uK` para…, Estágio de 1a ordem exato no ZOH: `x <- a*x + (1-a)*u`. Abaixo de…, Dois estágios de 1a ordem em série; ganho K aplicado no final da cascata., Integrador retangular: `acc += Ki*Ts*u`; a saída é o próprio acumulador. (+3 more)

### Community 47 - "test_subscriptions.py"
Cohesion: 0.18
Nodes (26): OttimaSystem — worker OPC-UA., collect_events(), collect_values(), make_config(), of_kind(), of_tag(), MonkeyPatch, Redis (+18 more)

### Community 48 - "ValueHeartbeat"
Cohesion: 0.12
Nodes (12): Path, Redis, Heartbeat de valor da conexão; vive fora da sessão (spec §2.2-6)., Redis, TagConfig, Republicação periódica de valor por conexão (report-by-exception + heartbeat)., Cria a task do heartbeat e retorna já., Cancela a task. Idempotente. (+4 more)

### Community 49 - "ModalConfigBloco.tsx"
Cohesion: 0.13
Nodes (21): inteiroDoCampo(), matrizDoFormulario(), nomeParam(), numeroDoCampo(), CamposTfs(), PARAMS, Props, trocarElemento() (+13 more)

### Community 50 - "models/__init__.py"
Cohesion: 0.15
Nodes (15): DeclarativeBase, Base, Base declarativa e mixin de timestamps (SQLAlchemy 2.0; DDL: spec F1 §3.1)., TimestampMixin, OpcConnection, Conexão OPC-UA (RF-201/206, ADR-009/021; DDL: spec F1 §3.1)., Conexão OPC-UA (RF-201/206, ADR-009/021; DDL: spec F1 §3.1)., Flow (+7 more)

### Community 51 - "certs.py"
Cohesion: 0.15
Nodes (24): _application_uri_of(), _discard(), _ensure_dir(), _info_from_certificate(), _load_certificate(), Certificate, Path, Certificado de instância de aplicação OPC-UA e trust de certificados de… (+16 more)

### Community 52 - "routers/tags.py"
Cohesion: 0.19
Nodes (19): Tag OPC (RF-203; DDL: spec F1 §3.1)., Tag, _carregar(), create_tag(), delete_tag(), get_tag(), list_tags(), _publicar() (+11 more)

### Community 53 - "test_server.py"
Cohesion: 0.16
Nodes (25): client(), _any_task_done(), await_until(), _client_credentials(), _differs(), _equals(), _greater_than(), Any (+17 more)

### Community 54 - "EventStream"
Cohesion: 0.14
Nodes (23): esperar_conexao(), evento_de(), EventStream, PubSub, Espera o `/health` do worker refletir o estado pedido para a conexão., Double distinto a cada chamada e entre execuções. O espelho do opcsim sobrevive…, Predicado de evento do canal `events` por `kind` e `conn_id` (spec §7.3)., Assinatura do canal `events` aberta ANTES do gatilho. A inscrição é aberta na… (+15 more)

### Community 55 - "routers/projects.py"
Cohesion: 0.17
Nodes (21): Project, ProjectCreate, ProjectOut, ProjectUpdate, BaseModel, Schemas de projetos (RF-101, ADR-017): criação, atualização parcial e saída., activate_project(), _carregar() (+13 more)

### Community 56 - "HTTPException"
Cohesion: 0.19
Nodes (18): HTTPException, BaseModel, Schemas de gestão de usuários (spec F1 §5.5): criação e atualização parcial., UserCreate, UserUpdate, hash_password(), _carregar(), create_user() (+10 more)

### Community 57 - "_get"
Cohesion: 0.16
Nodes (24): _amostra(), _get(), _inserir(), _instantes(), Any, datetime, fixture, parametrize (+16 more)

### Community 58 - "ValueSnapshot"
Cohesion: 0.13
Nodes (14): _close(), Any, PubSub, Redis, Espelho em memória do último valor de cada tag (RF-401, spec F3 §2.1, §3.0).…, Grava o último valor da tag; payload ruim é descartado e o laço segue., Só volta com o PSUBSCRIBE confirmado: a publicação seguinte não se perde. O…, Fecha o assinante sem nunca levantar: é caminho de desmonte. (+6 more)

### Community 59 - "RuntimeState"
Cohesion: 0.10
Nodes (14): FlowMetrics, FlowSnapshot, _iso_utc(), Any, datetime, Protocol, Snapshot em memória dos flows; fonte única do `/health` (spec F3 §2.2-10,…, O que o `/health` precisa de um flow rodando; a `FlowTask` satisfaz isto. (+6 more)

### Community 60 - "Ambiente"
Cohesion: 0.18
Nodes (24): Ambiente, esperar_ate(), T, Espera por condição, nunca por `sleep` cego. Devolve o valor que a satisfez., Projeto ativo com uma conexão ao opcsim e as quatro tags que a suíte exercita., _evento_na_api(), _historico(), _pontos() (+16 more)

### Community 61 - "ottima_core/security.py"
Cohesion: 0.14
Nodes (21): LoginOut, create_access_token(), decode_access_token(), decrypt_secret(), encrypt_secret(), verify_password(), test_fernet_roundtrip_e_chave_errada(), test_hash_argon2id_e_verificacao() (+13 more)

### Community 62 - "ValueSubscription"
Cohesion: 0.10
Nodes (20): DataChangeNotif, coerce_value(), Any, Client, Node, Redis, TagConfig, Uma subscription por conexão, com um monitored item por tag `direction='r'`. (+12 more)

### Community 63 - "FlowDefinition"
Cohesion: 0.14
Nodes (15): FlowStatus, PortValue, Valor de uma porta de bloco numa varredura (spec F3 §4.2, decisão A-3)., test_flow_status_aceita_ports_vazio_em_transicao_de_estado(), test_flow_status_com_ports_serializa_verbatim_spec_f3_42(), test_payloads_verbatim_prd_71(), test_port_value_preserva_bool_e_float_no_round_trip(), Clock (+7 more)

### Community 64 - "bus.py"
Cohesion: 0.10
Nodes (28): channel_mpc_state(), EventMessage, MpcPrediction, MpcState, OpcValue, publish_event(), Any, BaseModel (+20 more)

### Community 65 - "FlakyRedis"
Cohesion: 0.11
Nodes (9): _BrokenPubSub, ClosingRedis, _EmptyPubSub, FlakyRedis, PubSub, Assinante que morre na primeira escuta, como numa queda de conexão do Redis., Cliente cujo primeiro `pubsub()` devolve um assinante que cai ao escutar., Assinante cuja escuta termina limpa na hora, sem levantar nada. (+1 more)

### Community 66 - "compilerOptions"
Cohesion: 0.10
Nodes (19): compilerOptions, isolatedModules, jsx, lib, module, moduleResolution, noEmit, noFallthroughCasesInSwitch (+11 more)

### Community 67 - "test_script.py"
Cohesion: 0.05
Nodes (43): OttimaSystem — motor de flows., bloco(), bus(), eventos(), pool(), processo_vivo(), fixture, PubSub (+35 more)

### Community 68 - "devDependencies"
Cohesion: 0.11
Nodes (19): devDependencies, openapi-typescript, @playwright/test, tailwindcss, @tailwindcss/vite, @types/react, @types/react-dom, typescript (+11 more)

### Community 69 - "opc-worker/tests/test_health.py"
Cohesion: 0.18
Nodes (16): app_state_limpo(), get_health(), fixture, Response, Testes do `/health` do opc-worker (RNF-07, spec F2 §2.2-8). O app é um…, Zera o estado que o lifespan povoaria: sem isto um teste herda o do anterior., Uma conexão saudável e uma caída: o `/health` tem de mostrar as duas., state_com_duas_conexoes() (+8 more)

### Community 70 - "routers/history.py"
Cohesion: 0.16
Nodes (16): HistoryResponse, HistoryResponse, HistorySeries, BaseModel, Schema colunar do histórico (RF-802): formato consumido direto pelo uPlot no…, _as_utc(), _e_tag_id(), get_history() (+8 more)

### Community 71 - "deps.py"
Cohesion: 0.08
Nodes (30): EventOut, HTTPAuthorizationCredentials, get_app_settings(), get_current_user(), get_db(), get_redis(), AsyncSession, Redis (+22 more)

### Community 72 - "generate_app_cert"
Cohesion: 0.23
Nodes (11): AppCertificateGenerateIn, AppCertificateGenerateOut, AppCertificateOut, BaseModel, Schemas de certificados: app cert de instância e trust por conexão (RF-202,…, ServerCertificateOut, generate_app_cert(), get_app_cert() (+3 more)

### Community 73 - "dependencies"
Cohesion: 0.12
Nodes (17): class-variance-authority, clsx, @fontsource/archivo, @fontsource/archivo-narrow, @fontsource/spline-sans-mono, dependencies, class-variance-authority, clsx (+9 more)

### Community 74 - "Contrato de canais do barramento (PRD §7.1)"
Cohesion: 0.13
Nodes (17): Barramento: apenas canais do PRD §7.1, fire-and-forget (ADR-002), Predições do MPC só publicadas, nunca persistidas (ADR-016), Regra da Plaqueta (rótulos caps + Archivo Narrow + tracking), Assinatura 'tinta que ainda não secou' (predição tracejada desvanecendo), Plano F2 — Aquisição, Plano F3 — Motor + canvas, WS /ws (fanout de flow.status para o canvas ao vivo), Contrato de canais do barramento (PRD §7.1) (+9 more)

### Community 75 - "_Rejected"
Cohesion: 0.17
Nodes (9): GraphParseError, Problemas estruturais do `graph_json`. `errors` traz todos, não só o primeiro., async_sessionmaker, Exception, Redis, Definição pronta para subir ou entrar em hot-swap, com o que o supervisor…, Grafo do banco recusado na montagem da definição. `messages` traz todas as…, _Rejected (+1 more)

### Community 76 - "ChannelListener"
Cohesion: 0.19
Nodes (9): ChannelListener, _close(), PubSub, Falha de um payload não pode derrubar a escuta do canal inteiro., Só volta com o SUBSCRIBE confirmado: a publicação seguinte não se perde.…, Fecha o assinante sem nunca levantar: é caminho de desmonte., Assinante resiliente de um canal do barramento. Mesma forma e mesmas garantias…, Assina o canal e sobe a escuta. Idempotente. (+1 more)

### Community 77 - "ottima_recorder/main.py"
Cohesion: 0.20
Nodes (11): check_redis(), _heartbeat_loop(), lifespan(), FastAPI, Serviço recorder: /health + heartbeat de Redis (F1) e o pipeline de gravação…, Faz ping no Redis e registra o resultado em app.state.redis_ok., Repete o ping no Redis a cada HEARTBEAT_INTERVAL_S segundos., Sobe Redis, banco, pipeline e heartbeat; encerra na ordem inversa. (+3 more)

### Community 78 - "Any"
Cohesion: 0.16
Nodes (12): aguardar_parado(), esperar_todos(), fabrica_de_flows(), Any, PubSub, Assinatura de `flow.status.<flow_id>` aberta ANTES do gatilho (estilo do…, Amostras consecutivas, sem lacuna: coleta por mensagem recebida, nunca por…, Tudo o que chegou na janela; lista vazia é a prova de que o flow não está… (+4 more)

### Community 79 - "WatchdogTask"
Cohesion: 0.13
Nodes (11): Task de watchdog viva; None fora de `up` ou em conexão sem o par de node_ids., _describe(), Client, Exception, Task de watchdog de uma conexão: handshake de life-bit com o PLC (spec F2…, Registra a transição do bit lido e arma `watchdog_alive` na primeira delas., Detalhe curto para o payload do evento, no mesmo idioma de `subscriptions.py`.…, Handshake de life-bit com o PLC, por conexão (ADR-009, RF-206). Pressupõe… (+3 more)

### Community 80 - "_DropOldestBuffer"
Cohesion: 0.11
Nodes (13): _DropOldestBuffer, Any, async_sessionmaker, AsyncSession, datetime, Redis, Table, Pipeline do recorder: barramento → hypertables (RF-801, ADR-003, spec F2… (+5 more)

### Community 81 - "ADR-012 — Projeto como unidade de agrupamento e portabilidade (JSON)"
Cohesion: 0.18
Nodes (15): ADR-007 — Execução por scan cycle com Ts individual por flow, Execução por scan cycle (semântica PLC), ADR-011 — Hot-swap de flows sem interrupção; sem versionamento, Sem versionamento de flows, ADR-012 — Projeto como unidade de agrupamento e portabilidade (JSON), Export/import de projeto em JSON, Projeto como unidade de agrupamento, schema_version do JSON de projeto (+7 more)

### Community 82 - "schemas/events.py"
Cohesion: 0.40
Nodes (4): EventOut, BaseModel, Schema de leitura do log de eventos (RF-803): as mesmas 5 chaves do canal…, Schemas Pydantic compartilhados entre a API e os workers.

### Community 83 - "api/tests/test_events.py"
Cohesion: 0.32
Nodes (14): _evento(), _inserir(), Any, Consulta do log de eventos (RF-803): ordenação, filtros, limites e papéis…, test_filtro_origin_e_exato(), test_filtro_severity(), test_filtros_combinados(), test_janela_inclusiva_nos_dois_extremos() (+6 more)

### Community 84 - "__main__.py"
Cohesion: 0.27
Nodes (7): Namespace, OttimaSystem — servidor OPC-UA de simulação para testes (dev-only)., main(), _parse_args(), CLI do opcsim: sobe o servidor de simulação e roda até SIGINT/SIGTERM., _serve(), Servidor OPC-UA de simulação usado pelos testes do opc-worker. Reproduz o…

### Community 85 - "ottima_opc_worker/connection.py"
Cohesion: 0.13
Nodes (15): BaseException, TagConfig, VariantType, Runtime de uma conexão OPC-UA: máquina de estados, backoff e eventos (spec F2…, Lê 1× o DataType de cada node de tag `w` e monta o cache `tag_id ->…, DataType real do node da tag, ou o fallback declarado. Nunca levanta., Codificação de escrita da tag: cache da sessão, senão fallback por `data_type`.…, Troca o conjunto de tags SEM derrubar a sessão (reconciliação, tarefa 1.4).… (+7 more)

### Community 86 - "RF-206/207 watchdog por conexão e política de falha"
Cohesion: 0.14
Nodes (14): Segurança de processo: escrita só com deploy + watchdog vivo + REMOTO; boot parado, Serviço opcsim (simulador OPC-UA de teste, Basic256Sha256), Watchdog (bit alternante com NOT cruzado, congelamento >10 s), Gate de escrita stateless (sessão up ∧ watchdog_alive), opcsim como member do workspace (dev-only), Task de watchdog (threshold injetável nos testes, 10 s fixo em produção), RNF-03 segurança de processo (escrita só com deploy + watchdog + REMOTO), RF-206/207 watchdog por conexão e política de falha (+6 more)

### Community 87 - "test_api_e2e.py"
Cohesion: 0.30
Nodes (13): admin(), _ativo(), _garantir_sentinela(), _novo_nome(), Client, fixture, Camada L2 do gate E2E da F1 (docs/specs/F1-testes-e2e.md): API contra o compose…, A API não expõe "desativar" e excluir o ativo dá 409: um projeto sentinela… (+5 more)

### Community 88 - "fixtures.ts"
Cohesion: 0.29
Nodes (10): ADMIN, adminApi(), adminToken(), ensureOperator(), fazerLogin(), OPERATOR, RUN_ID, garantirSentinela() (+2 more)

### Community 89 - "ottima_flow_runtime/main.py"
Cohesion: 0.26
Nodes (12): build_event_listener(), Assinante do canal `events` com os dois `kind` que o runtime consome (§2.2-8).…, check_database(), check_redis(), _heartbeat_loop(), lifespan(), FastAPI, Serviço flow-runtime: lifespan com supervisor e `/health` por flow (RNF-07,… (+4 more)

### Community 90 - "Serviço api (FastAPI, porta interna 8000)"
Cohesion: 0.26
Nodes (12): Arquitetura de referência (frontend⇄api⇄Redis⇄workers⇄OPC/Timescale), Serviço api (FastAPI, porta interna 8000), Serviço flow-runtime (porta interna 8002), Serviço frontend (nginx, única porta exposta), Serviço opc-worker (porta interna 8001), Serviço recorder (porta interna 8003), Serviço redis (barramento pub/sub, redis:7.4-alpine), Serviço timescaledb (timescale/timescaledb:2.17.2-pg17) (+4 more)

### Community 91 - "conftest.py"
Cohesion: 0.26
Nodes (11): db_engine(), db_session(), migrated_database_url(), fixture, Fixtures compartilhadas (spec F1 §9): Timescale real via testcontainers,…, Transação externa + sessão em SAVEPOINT: commit dentro do teste não vaza (spec…, decode_responses=True é contrato da F2: todo consumidor recebe str, não bytes., redis_client() (+3 more)

### Community 92 - "ADR-010 — Modos LOCAL/REMOTO e MAN/AUTO com transferência bumpless"
Cohesion: 0.20
Nodes (12): ADR-001 — FastAPI all-in (abandono do Django), FastAPI all-in backend, RBAC trivial de 2 papéis (coluna role + dependências), ADR-010 — Modos LOCAL/REMOTO e MAN/AUTO com transferência bumpless, Modos LOCAL/REMOTO, Modos MAN/AUTO do MPC (sub-modo de REMOTO), ADR-015 — Papéis: admin e OPERADOR (rename de visualizador), Papel admin (+4 more)

### Community 93 - "ADR-014 — Orçamento de tempo do MPC e multiplicador de execução"
Cohesion: 0.23
Nodes (12): ADR-004 — Loops vivos em asyncio; sem Celery, Loops vivos como tasks asyncio, Solver CPU-bound via loop.run_in_executor, Ts por flow de lista fixa, Horizontes Np/Nc derivados do TSS, ADR-014 — Orçamento de tempo do MPC e multiplicador de execução, Multiplicador de execução por bloco MPC, Timeout do solver = ~70% do Ts efetivo (+4 more)

### Community 94 - "Log de eventos persistido"
Cohesion: 0.24
Nodes (12): ADR-009 — Watchdog de comunicação por bit alternante (NOT cruzado), Failsafe: parar de escrever MVs em falha de comunicação, Watchdog por bit alternante (NOT cruzado), Política de overrun do solver, Faceplates da tela de operação, ADR-017 — Vários projetos armazenados, um ativo; boot em estado parado, Boot em estado parado; deploy explícito, Um único projeto ativo por vez (+4 more)

### Community 95 - "OpcWriteBlock"
Cohesion: 0.29
Nodes (3): OpcWriteBlock, Redis, Entrada `in`, nenhuma saída. Supressão (§3.2): entrada nula ou inválida não é…

### Community 96 - "RF-304 hot-swap atômico na próxima varredura (ADR-011)"
Cohesion: 0.18
Nodes (11): Execução por exec_order crescente, nunca topológica (ADR-024), Hot-swap: troca atômica de definição entre varreduras (ADR-011), flowgraph.py no core (modelo tipado + validações), Hot-swap (stage validado, troca atômica, preservação por block_id), Scheduler FlowTask com deadline absoluto e skip de overrun, RF-307 exec_order único 1..N por bloco (ADR-024), RF-304 hot-swap atômico na próxima varredura (ADR-011), RF-401 scan cycle por exec_order com atraso determinístico de 1 scan (+3 more)

### Community 97 - "ADR-001…024 (decisões de arquitetura normativas)"
Cohesion: 0.18
Nodes (11): Governança: ADRs normativos prevalecem sobre código/PRD, Módulo de certificados (core + API, layout /certs), ADR-001…024 (decisões de arquitetura normativas), Migrations Alembic como única fonte do schema, Auth JWT HS256 + Argon2id, TTL 12 h, sem refresh, DDL completo (users, projects, opc_connections, tags, flows), Segredos de conexão OPC cifrados com Fernet (OTTIMA_FERNET_KEY), Dependências RBAC (get_current_user, require_operator, require_admin) (+3 more)

### Community 98 - "PRD OttimaSystem v1.2 (requisitos, contratos, fases)"
Cohesion: 0.31
Nodes (11): OttimaSystem (plataforma APC on-premise), Direção de design 'Console OttimaSystem', Glossário OttimaSystem (vocabulário do domínio fixado), PRD OttimaSystem v1.2 (requisitos, contratos, fases), Índice da documentação do projeto (PRD, GLOSSARY, ADRs), Spec F1 — Fundação, Spec F1 — Testes E2E (gate de conclusão da fase), Paleta de penas --pen-1..6 (OKLCH, ≤6 séries) (+3 more)

### Community 99 - "schemas/connections.py"
Cohesion: 0.24
Nodes (9): model_validator, ConnectionCreate, _ConnectionFields, ConnectionOut, ConnectionUpdate, BaseModel, Schemas de conexões OPC-UA (RF-201, ADR-009/021): senha só entra, nunca sai…, Regras de coerência; o ValueError vira 422 no FastAPI. (+1 more)

### Community 100 - "parse_graph"
Cohesion: 0.18
Nodes (11): parse_graph(), Valida a forma do `graph_json` e devolve o modelo tipado. Levanta…, `POST /api/flows` grava `{"nodes": [], "edges": []}` (spec §5.1)., ADR-024/spec §4.1-3: mexer em ordem, rótulo ou posição não reinicia o estado., test_aresta_invertida_gera_warning_sem_erro(), test_grafo_de_referencia_parseia_com_config_tipada(), test_grafo_de_referencia_sem_erros_nem_warnings(), test_grafo_em_ordem_nao_gera_warning() (+3 more)

### Community 101 - "ottima_opc_worker/main.py"
Cohesion: 0.18
Nodes (16): AsyncEngine, create_engine(), create_session_factory(), async_sessionmaker, AsyncSession, Engine e session factory assíncronas (SQLAlchemy 2.0 + asyncpg)., check_database(), check_redis() (+8 more)

### Community 102 - "RNF-09 suíte de malha fechada MPC↔TFS"
Cohesion: 0.20
Nodes (10): Suíte de aceitação malha fechada MPC↔TFS (RNF-09), IOPDT (modelo integrador com tempo morto), SOPDT (modelo 2ª ordem com tempo morto), TFS (bloco de simulação, matriz até 2×2 SOPDT/IOPDT), RF-621..623 modos LOCAL/REMOTO, MAN/AUTO e bumpless, Bloco MPC (RF-601..625, do-mpc, SOPDT/IOPDT, TSS→Np/Nc), RNF-09 suíte de malha fechada MPC↔TFS, Bloco TFS de simulação (RF-521/522) (+2 more)

### Community 103 - "Editor canvas (React Flow re-vestido, MPC desabilitado badge F4)"
Cohesion: 0.20
Nodes (10): Regra do Canal Redundante (severidade = cor + ícone + texto), Regra do Estado Publicado (comandado × confirmado), Regra do Número Tabular (mono tabular + EU em todo valor), Continuous aggregate (agregação materializada Timescale para trends), Editor canvas React Flow re-vestido (paleta 5 blocos), Continuous aggregate samples_1m (avg/min/max/count/worst_quality), GET /api/history (bruto ≤2 h, CAgg acima, resposta colunar), Trend de engenharia (uPlot re-vestido, polling 5 s, BAD = gap + rótulo) (+2 more)

### Community 104 - "ADR-013 — Modelo do MPC: matriz SOPDT + processo integrador; horizontes derivados do TSS"
Cohesion: 0.27
Nodes (10): ADR-008 — Configuração do MPC por formulário estruturado (modal com abas), Configuração do MPC por formulário com abas, sem código, ADR-013 — Modelo do MPC: matriz SOPDT + processo integrador; horizontes derivados do TSS, Limites duros de MV e rate limit (Δu), Matriz de modelos SOPDT por par, Modelo integrador por par (Ki + θ), ADR-019 — Categorias de variáveis do MPC: CV com SP, Restrição por faixa (com precedência), Quatro categorias de variáveis do MPC (MV/CV/Restrição/DV) (+2 more)

### Community 105 - "PRD §4 domain model: User, Project, OpcConnection, Tag, Flow, Block/Edge in graph_json, Event and Sample hypertables"
Cohesion: 0.24
Nodes (10): ADR-003 — Postgres/TimescaleDB único, retenção de 1 mês, Decision: single Postgres+TimescaleDB — relational tables + hypertable, native 1-month retention, continuous aggregates, ADR-005 — Canvas com React Flow; execução 100% no backend, Decision: React Flow editor, graph serialized as JSON in Postgres; frontend only edits, execution exclusively in flow-runtime, ADR-020 — Log de eventos persistido, banner de alarmes, sem ACK, Decision: persisted event log (hypertable, 1-month retention; ts/severity/origin/message/payload), active-alarm banner derived from current state, no ACK; realtime fanout via events channel, Reference stack: React+Vite+shadcn+React Flow+uPlot, FastAPI+SQLAlchemy 2.0 async, Postgres/TimescaleDB, Redis pub/sub, uv, Docker Compose, Log de eventos: event hypertable (info/warning/alarm), 1-month retention, feeds no-ACK alarm banner and audit (+2 more)

### Community 106 - "CLAUDE.md (archived) — OttimaSystem agent operating rules"
Cohesion: 0.27
Nodes (10): ADR-004 — Loops vivos em asyncio; sem Celery, Decision: MPC/scripts/OPC sessions as asyncio tasks in dedicated workers; Celery out; blocking solve via run_in_executor, ADR-006 — Separação de processos: opc-worker × flow-runtime × recorder, Decision: distinct asyncio processes (opc-worker sole OPC-UA talker, flow-runtime executes flows, recorder writes hypertable) connected only by the bus, CLAUDE.md (archived) — OttimaSystem agent operating rules, ADRs 001-023 are normative; ADR wins any conflict, Invariant: never block the asyncio event loop, Invariant: opc-worker is the only process that speaks OPC-UA (+2 more)

### Community 107 - "router.tsx"
Cohesion: 0.16
Nodes (13): ADR-0020, AnnunciatorBar(), AppShell(), NAV_ENGENHARIA, AuthGuard(), App(), queryClient, Button (+5 more)

### Community 108 - "errors_of"
Cohesion: 0.24
Nodes (13): O que a validação precisa saber de uma tag; o chamador projeta a linha do banco., TagRef, base_tags(), errors_of(), Resolução do controlador 3: a bivalência é propriedade da porta do Script., test_read_booleano_em_entrada_de_script_e_aceito(), test_read_booleano_em_entrada_numerica_do_tfs_e_recusado(), test_read_numerico_em_write_booleano_e_recusado() (+5 more)

### Community 109 - "schemas/flows.py"
Cohesion: 0.29
Nodes (9): FlowCreate, FlowDetail, FlowOut, FlowSaved, FlowUpdate, BaseModel, Schemas de flows (RF-302/306/307): CRUD do diagrama de blocos e envelope do…, Linha da lista (spec §5.1): sem `graph_json`, que por flow pode ser grande. (+1 more)

### Community 110 - "ottima_flow_runtime/supervisor.py"
Cohesion: 0.18
Nodes (15): flow_origin(), publish_flow_deployed(), publish_flow_stopped(), publish_rejected(), Redis, Barramento de eventos do runtime: o que ele escuta e o que ele emite (spec F3…, `origin` de evento de flow; §6.1 filtra por igualdade nele., `user` ausente quando não há comando de usuário atrás da parada (ruling do… (+7 more)

### Community 111 - "Barramento interno Redis pub/sub"
Cohesion: 0.42
Nodes (9): ADR-002 — Barramento interno via Redis pub/sub, Barramento interno Redis pub/sub, Postgres/TimescaleDB único, ADR-006 — Separação de processos: opc-worker × flow-runtime × recorder, flow-runtime, Isolamento de jitter por separação de processos, opc-worker, recorder (+1 more)

### Community 112 - "Hot-swap de flows entre varreduras"
Cohesion: 0.25
Nodes (9): ADR-005 — Canvas com React Flow; execução 100% no backend, Execução do grafo exclusivamente no backend, Canvas React Flow (@xyflow/react), Bumpless via tracking de MV (readback por MV), Hot-swap de flows entre varreduras, ADR-022 — Bloco TFS: simulação de processo por função de transferência, Bloco TFS (simulação de processo), Discretização ZOH e tempo morto por buffer de atraso (+1 more)

### Community 113 - "Decision: two mode axes — LOCAL/REMOTO (PID vs MPC, bumpless both ways via PID mode writes AUTO<->RCAS/CAS/ROUT) and MAN/AUTO sub-mode of REMOTO; MV tracking in LOCAL"
Cohesion: 0.22
Nodes (9): ADR-001 — FastAPI all-in (abandono do Django na reescrita), Decision: rewrite with FastAPI all-in + SQLAlchemy 2.0 async, no Django, ADR-010 — Modos LOCAL/REMOTO e MAN/AUTO com transferência bumpless, Decision: two mode axes — LOCAL/REMOTO (PID vs MPC, bumpless both ways via PID mode writes AUTO<->RCAS/CAS/ROUT) and MAN/AUTO sub-mode of REMOTO; MV tracking in LOCAL, ADR-015 — Papéis: admin e OPERADOR (rename de visualizador), Decision: two roles — admin (engineering + all operation) and operador (modes, SP, MV in MAN; sees everything; no engineering edits), Bumpless: control transfer without MV jump; MPC initializes at current MVs, PID does SP/OUT-tracking, MV tracking: in LOCAL the MPC MV output follows the PID readback tag for bumpless LOCAL->REMOTO (+1 more)

### Community 114 - "Decision: Redis pub/sub internal bus (opc.values.<conn_id> out, opc.writes in)"
Cohesion: 0.22
Nodes (9): ADR-002 — Barramento interno via Redis pub/sub, Decision: Redis pub/sub internal bus (opc.values.<conn_id> out, opc.writes in), ADR-016 — Tela de operação: faceplate + tendência com predição do MPC, Decision: per-MPC operation screen — main faceplate (modes/status/commands), small faceplates per variable, central uPlot trend with prediction overlay from now; predictions published on mpc.state.* and never persisted, Invariant: pub/sub is fire-and-forget; UI reflects published state, never command echo, Barramento: internal Redis pub/sub — opc.values.* (reads) and opc.writes (write commands), Faceplate: operation panel of an element — main (modes/status/commands) and small (one variable each), Predicao: future PV/MV trajectory from the last solve, published on mpc.state.*, never persisted (+1 more)

### Community 115 - "Decision: per-pair model matrix (MV->CV, DV->CV); response type per CV — self-regulating SOPDT(K,t1,t2,th) or integrating (Ki,th); Np/Nc derived from TSS, not user-edited; hard MV limits and rate limit"
Cohesion: 0.22
Nodes (9): ADR-008 — Configuração do MPC por formulário estruturado (modal com abas), Decision: full no-code form — double-click on MPC block opens tabbed config modal; system assembles do-mpc model internally, ADR-013 — Modelo do MPC: matriz SOPDT + processo integrador; horizontes derivados do TSS, Decision: per-pair model matrix (MV->CV, DV->CV); response type per CV — self-regulating SOPDT(K,t1,t2,th) or integrating (Ki,th); Np/Nc derived from TSS, not user-edited; hard MV limits and rate limit, ADR-019 — Categorias de variáveis do MPC: CV com SP, Restrição por faixa (com precedência), Decision: four variable categories — MV (hard limits, Du max), CV (setpoint tracking), Restricao (low/high band, precedence over CVs), DV (feedforward); model matrix rows = CVs+Restricoes, columns = MVs+DVs, Restricao: MPC variable controlled within a low/high band, no SP, with precedence over CVs (soft constraint, dominant slack penalty), SOPDT: second-order plus dead time model (K, tau1, tau2, theta) per MV->CV / DV->CV pair (+1 more)

### Community 116 - "PRD.md (archived) — OttimaSystem product requirements v1.0"
Cohesion: 0.31
Nodes (9): ADR-012 — Projeto como unidade de agrupamento e portabilidade (JSON), Decision: Project groups flows + system configs; exportable/importable as JSON with schema_version, never historical data, ADR-021 — Segurança OPC-UA: anônimo, usuário/senha e certificado desde a v1, Decision: per-connection security — None / Basic256Sha256 Sign / SignAndEncrypt; anonymous, user/password or X.509 certificate auth, all from v1; instance certificate management, ADR-023 — Escopo de plataforma da v1: pt-BR, auth local, HTTP interno, Compose on-prem, Decision: pt-BR-only UI, local user/password auth (Argon2/bcrypt + JWT), plain HTTP on plant network, Docker Compose on a single on-prem Linux host, PRD.md (archived) — OttimaSystem product requirements v1.0, PRD §7.2 project JSON export/import contract with schema_version, no secrets, no history (+1 more)

### Community 117 - "test_auto_laco_e_ciclo"
Cohesion: 0.31
Nodes (9): link(), Aresta de um bloco para ele mesmo: o menor ciclo possível., A varredura precisa cobrir todos os componentes, não só o do primeiro nó., Milhares de nós encadeados: travessia iterativa, nunca RecursionError. Com…, script_node(), test_auto_laco_e_ciclo(), test_cadeia_profunda_nao_estoura_a_pilha(), test_ciclo_de_tres_nos_e_erro() (+1 more)

### Community 118 - ".fire"
Cohesion: 0.22
Nodes (3): Tempo consumido dentro de uma varredura (quem chama é o bloco-duplo)., Espera o laço chegar a dormir e devolve a fronteira que ele pediu., Salta exatamente para a fronteira pedida e libera o laço.

### Community 119 - "schemas/auth.py"
Cohesion: 0.38
Nodes (6): LoginIn, LoginOut, BaseModel, Schemas de autenticação (spec F1 §5.1): entrada de login e saída de…, Usuário exposto pela API — nunca inclui password_hash., UserOut

### Community 120 - "schemas/tags.py"
Cohesion: 0.47
Nodes (5): BaseModel, Schemas de tags OPC (RF-203): nome lógico, node_id, direção, tipo, EU e…, TagCreate, TagOut, TagUpdate

### Community 121 - "ws.py"
Cohesion: 0.11
Nodes (17): _apply_client_message(), _authenticate(), _flow_ids(), flow_status_ws(), Any, AsyncSession, WebSocket `/ws`: fanout de `flow.status.<id>` para o canvas ao vivo (RF-305,…, Só inteiros: item de forma inesperada é ignorado, não derruba a conexão. (+9 more)

### Community 122 - "flow-runtime/tests/test_events.py"
Cohesion: 0.29
Nodes (7): _handler(), MonkeyPatch, Redis, Contratos do assinante de canais do barramento do runtime (spec F3 §2.2-8)., Handler vazio: o que está sob teste é a inscrição, não o despacho., SUBSCRIBE que estoura fecha o pubsub: sem vazamento de conexão e inscrição.…, test_falha_ao_assinar_nao_vaza_inscricao_nem_conexao()

### Community 123 - "index.tsx"
Cohesion: 0.19
Nodes (13): NoEscrita, NoLeitura, NoScript, NoTfs, PORTAS_TFS_ENTRADA, PORTAS_TFS_SAIDA, useTagsDoEditor(), NoEscritaOpc() (+5 more)

### Community 124 - "useHistory.ts"
Cohesion: 0.24
Nodes (13): JANELAS, TrendPage(), carimbo(), resposta(), serie(), montarMatriz(), resumirSeries(), ResumoSerie (+5 more)

### Community 125 - "Decision: solver timeout ~70% of effective Ts_mpc — on overrun keep last MV, raise alarm, skip to next scan; per-block multiplier N (Ts_mpc = N x Ts_flow)"
Cohesion: 0.29
Nodes (7): ADR-007 — Execução por scan cycle com Ts individual por flow, Decision: cyclic scan semantics; per-flow Ts from fixed list {0.5,1,2,5,10,30,60}s; blocks read latest bus snapshot, ADR-014 — Orçamento de tempo do MPC e multiplicador de execução, Decision: solver timeout ~70% of effective Ts_mpc — on overrun keep last MV, raise alarm, skip to next scan; per-block multiplier N (Ts_mpc = N x Ts_flow), Multiplicador: N such that the MPC block executes every N flow scans (Ts_mpc = N x Ts_flow), Scan cycle: every Ts all blocks evaluated in topological order with latest known values, PRD §9 risks and mitigations: IPOPT vs short Ts, dead-time state explosion, pub/sub delivery, hot-swap concurrency, PLC-dependent bumpless

### Community 126 - "Decision: per-connection watchdog with two OPC bits (read+write), crossed NOT, frozen >10s declares comm failure; failure stops writes and flows"
Cohesion: 0.33
Nodes (7): ADR-009 — Watchdog de comunicação por bit alternante (NOT cruzado), Decision: per-connection watchdog with two OPC bits (read+write), crossed NOT, frozen >10s declares comm failure; failure stops writes and flows, ADR-017 — Vários projetos armazenados, um ativo; boot em estado parado, Decision: N projects stored, exactly one active; on server boot all flows start stopped awaiting explicit deploy, Deploy: explicit act of putting a flow into execution; after boot all flows start stopped, Watchdog: alternating bit with crossed NOT between system and PLC; frozen >10s means comm failure, PRD RNF-03 process safety: no plant write without deployed flow + live watchdog + REMOTO; boot never resumes loops

### Community 127 - "Decision: fifth palette block TFS — transfer-function matrix up to 2x2, each element SOPDT or IOPDT, discrete-time at flow Ts, persistent internal state"
Cohesion: 0.33
Nodes (7): ADR-022 — Bloco TFS: simulação de processo por função de transferência, Decision: fifth palette block TFS — transfer-function matrix up to 2x2, each element SOPDT or IOPDT, discrete-time at flow Ts, persistent internal state, Strict TDD on pure logic; MPC<->TFS closed loop is the acceptance suite (RNF-09), IOPDT: integrating plus dead time model (Ki, theta) for integrating CVs/Restricoes and the TFS block, TFS: simulation block, transfer-function matrix up to 2x2, each element SOPDT or IOPDT, discrete time at flow Ts, PRD §8 implementation phases F1-F6 with acceptance criteria (F1 fundacao ... F6 portabilidade & hardening), PRD RNF-09 quality: closed-loop MPC<->TFS suite (no hardware) covering bumpless, constraint precedence, overrun, hot-swap

### Community 128 - "scripts"
Cohesion: 0.29
Nodes (7): scripts, build, dev, e2e, generate:api, preview, test:unit

### Community 129 - "env.py"
Cohesion: 0.48
Nodes (6): do_run_migrations(), include_object(), Connection, run_async_migrations(), run_migrations_offline(), run_migrations_online()

### Community 130 - "cert_servidor"
Cohesion: 0.29
Nodes (7): cert_servidor(), certs_dir(), fixture, Mesmo diretório temporário que o app enxerga (conftest aponta certs_dir p/…, Statements UPDATE emitidos em `opc_connections` na sessão do teste. É o…, PEM e DER de um certificado real, gerado fora do certs_dir: faz papel do…, updates_na_conexao()

### Community 131 - "status_to_quality"
Cohesion: 0.29
Nodes (7): StatusCode OPC-UA → quality 0/1/2 (spec F1 §3.4-4). A severidade está nos 2…, status_to_quality(), Good⇒0, Uncertain⇒1, Bad⇒2, reservado⇒2 (spec F1 §3.4-4)., DataValue.StatusCode é opcional no asyncua: ausência de status não é dado bom., test_status_to_quality_mapeia_severidade_do_status_code(), test_status_to_quality_sem_status_code_e_bad(), StatusCode

### Community 132 - "Plano F4a — MPC: config & montagem"
Cohesion: 0.15
Nodes (12): Aderência (DoD do plano F4a), Contratos verbatim (PRD §7.1 v1.2), Etapa 0 — Débitos herdados (spec F4 §8; Etapa 0 por ordem do usuário), Etapa 1 — Core: config, validação e derivação (TDD), Etapa 2 — Montagem do-mpc (biblioteca pura no flow-runtime; TDD), Etapa 3 — API: flows aceita MPC; ponte de deploy, Etapa 4 — Frontend: paleta, nó dinâmico e modal 7 abas, Etapa 5 — Fechamento do plano F4a (+4 more)

### Community 133 - "Stack compose 'ottima' (7 serviços de produção)"
Cohesion: 0.33
Nodes (6): Layout do monorepo (packages/services/frontend/deploy), Override E2E (portas de teste publicadas em 127.0.0.1), Stack compose 'ottima' (7 serviços de produção), Compose de 7 serviços + nginx same-origin (proxy /api e /ws), Workspace uv + pacote ottima-core (modelos, schemas, bus, security), Produto instalável com um único docker compose up, sem infra corporativa

### Community 134 - "ADR-003 — Postgres/TimescaleDB único, retenção de 1 mês"
Cohesion: 0.33
Nodes (6): ADR-003 — Postgres/TimescaleDB único, retenção de 1 mês, Continuous aggregates para trends, Retenção nativa de 1 mês, ADR-016 — Tela de operação: faceplate + tendência com predição do MPC, Canal mpc.state.* (predições no barramento), Tendência com predição do MPC

### Community 135 - "app.py"
Cohesion: 0.22
Nodes (9): create_app(), lifespan(), FastAPI, App factory da API: rotas sob /api, logging JSON e ciclo de vida do engine., Cria engine, session factory, Redis e o hub do /ws na subida; descarta na…, OttimaSystem — API REST., Alvo do uvicorn em produção: ottima_api.main:app., health() (+1 more)

### Community 138 - "test_tags.py"
Cohesion: 0.60
Nodes (5): _conexao(), test_cria_lista_filtra(), test_nome_duplicado_na_conexao_409(), test_patch_e_delete(), test_validacoes_e_papeis()

### Community 140 - "app"
Cohesion: 0.19
Nodes (10): app(), App real com get_db na sessão em SAVEPOINT e get_redis no Redis efêmero dos…, Runtime que não subiu o supervisor está surdo a todo `deploy`: nunca…, StubRedis, test_check_redis_marca_estado(), test_health_responde_200_com_nome_do_servico(), test_health_sem_supervisor_nao_responde_ok(), App cru (sem lifespan) cai nos defaults: flow em falha não é unhealth do… (+2 more)

### Community 141 - "Plano F4b — MPC: runtime & modos"
Cohesion: 0.17
Nodes (11): Aderência ao aceite F4 (PRD §8) — Definition of Done da FASE, Etapa 1 — MpcWorker: processo dedicado (decisão A-3), Etapa 2 — Bloco MPC, supervisor e saúde, Etapa 3 — API `/api/operate` e fanout WS, Etapa 4 — Integração L2 (malha fechada MPC↔TFS via API real), Etapa 5 — Gate final da fase F4, Interfaces consumidas (produzidas no F4a — não redefinir), Interfaces internas deste plano (assinaturas exatas — consumidas entre tarefas) (+3 more)

### Community 142 - "api-types.ts"
Cohesion: 0.25
Nodes (7): ADR-0021, components, $defs, operations, paths, ADR-0017, webhooks

### Community 143 - "Retenção 1 mês + continuous aggregate (RF-801, ADR-003)"
Cohesion: 0.40
Nodes (5): Banco único Postgres/TimescaleDB; retenção via policies (ADR-003), Pipeline do recorder (flush 1 s ou 1000 linhas, drop-oldest 100k), Retenção 1 mês + continuous aggregate (RF-801, ADR-003), Hypertables samples/events + retention policies de 1 mês, Recorder dumb pipe (buffers separados, backpressure drop-oldest)

### Community 144 - "Gate E2E em 3 camadas (L1 smoke, L2 pytest e2e, L3 browser/Playwright)"
Cohesion: 0.50
Nodes (5): Gate E2E em 3 camadas (L1 smoke, L2 pytest e2e, L3 browser/Playwright), Rodada de gate da F2 (L1 + L2 + L3 browser-tool), Rodada de gate da F3 (L2 = 24 cenários), Gate E2E da F2 em 3 camadas (E2E-F2-01…09 + roteiro B-01…07), Gate E2E da F3 (E2E-F3-01..10 + roteiro B-F3-01..08)

### Community 145 - "Bloco Python-Script (RF-511..514, ADR-018)"
Cohesion: 0.40
Nodes (5): Invariante: nunca bloquear o event loop (ADR-004), Script block: escopo math+numpy, timeout ~70% do Ts, state persistente (ADR-018), ProcessPool dedicado do bloco Script, Bloco Python-Script (RF-511..514, ADR-018), Script ProcessPool (timeout kill+respawn, state picklado)

### Community 146 - "Decision: live flow edits take effect on the next scan without interruption; no flow versioning"
Cohesion: 0.40
Nodes (5): ADR-011 — Hot-swap de flows sem interrupção; sem versionamento, Decision: live flow edits take effect on the next scan without interruption; no flow versioning, ADR-018 — Contrato do bloco Python-Script, Decision: user-defined ports (IN1..INn in, OUT1..OUTn assigned), persistent per-instance state dict, scope restricted to math+numpy, timeout ~70% of flow Ts, Hot-swap: live flow edit applied atomically on next scan, preserving unchanged block state

### Community 147 - "package.json"
Cohesion: 0.40
Nodes (4): name, private, type, version

### Community 148 - "ottima-core"
Cohesion: 0.40
Nodes (5): ottima-api, ottima-core, ottima-flow-runtime, ottima-opc-worker, ottima-recorder

### Community 149 - "logging.py"
Cohesion: 0.29
Nodes (6): LogRecord, JsonFormatter, Logging estruturado JSON em stdout (RNF-07; spec F1 §7.1)., Serializa cada registro como uma linha JSON com timestamp UTC., Substitui os handlers do logger raiz por um único handler JSON em stdout., setup_logging()

### Community 150 - "StubSessionFactory"
Cohesion: 0.25
Nodes (3): Dublê de `async_sessionmaker`: o `SELECT 1` é executado ou explode, como no…, StubSessionFactory, test_check_database_marca_estado()

### Community 151 - "Harness"
Cohesion: 0.40
Nodes (3): Harness, Supervisor vivo com os colaboradores que os testes precisam observar., Publica em `flow.commands` como a API faz (spec §5.1).

### Community 152 - "backoff_delay"
Cohesion: 0.33
Nodes (6): backoff_delay(), Backoff exponencial com teto e full jitter (spec §2.2-2), `attempt` 0-based., Full jitter: o valor sorteado nunca sai de [0, topo] (spec §2.2-2)., Conexão fora do ar por horas acumula centenas de tentativas sem quebrar o float., test_backoff_nao_estoura_com_muitas_tentativas(), test_backoff_tem_full_jitter_dentro_do_intervalo()

### Community 153 - "_SupersededAttemptError"
Cohesion: 0.40
Nodes (4): RuntimeError, Aborta a tentativa se um fail() ocorreu enquanto o connect estava em voo. Sem…, Tentativa de conexão invalidada por um fail() concorrente., _SupersededAttemptError

### Community 156 - "ConnectionRuntime (máquina connecting→up→failed, backoff + jitter)"
Cohesion: 0.67
Nodes (3): Invariante: opc-worker é o único processo que fala OPC-UA (ADR-006), ConnectionRuntime (máquina connecting→up→failed, backoff + jitter), Supervisor (watermark 10 s no banco + dica via events)

### Community 157 - "Campo grafite (paleta neutra escura dessaturada)"
Cohesion: 0.67
Nodes (3): Campo grafite (paleta neutra escura dessaturada), Regra da Chapa (profundidade tonal + linha 1px, sem sombras), Tokens CSS OKLCH exatos (tokens.css, Tailwind v4 @theme)

### Community 158 - "Bumpless (transferência sem salto na MV)"
Cohesion: 0.67
Nodes (3): Bumpless (transferência sem salto na MV), LOCAL / REMOTO (eixo de modo do MPC), MV tracking (MV do MPC segue readback do PID em LOCAL)

### Community 159 - "Scan cycle (avaliação a cada Ts em ordem de exec_order)"
Cohesion: 0.67
Nodes (3): exec_order (inteiro único 1..N por bloco), Flow (grafo de blocos executado em scan cycle), Scan cycle (avaliação a cada Ts em ordem de exec_order)

### Community 160 - "ADR-023 — Escopo de plataforma da v1: pt-BR, auth local, HTTP interno, Compose on-prem"
Cohesion: 0.67
Nodes (3): ADR-023 — Escopo de plataforma da v1: pt-BR, auth local, HTTP interno, Compose on-prem, Docker Compose on-prem (deploy v1), Escopo de plataforma v1 (pt-BR, auth local Argon2/bcrypt+JWT, HTTP sem TLS)

### Community 161 - "Camadas L1/L1s/L2/L3 e 19 cenários do gate da F1"
Cohesion: 0.67
Nodes (3): deploy/smoke.sh (roteiro executável do aceite compose up), Camadas L1/L1s/L2/L3 e 19 cenários do gate da F1, Suíte L2 tests/e2e (marker e2e, contra stack compose real)

## Knowledge Gaps
- **265 isolated node(s):** `Regras globais (valem para todas as tarefas)`, `Contratos verbatim (PRD §7.1 v1.2)`, `Interfaces produzidas (consumidas pelo F4b — assinaturas exatas)`, `Etapa 0 — Débitos herdados (spec F4 §8; Etapa 0 por ordem do usuário)`, `Etapa 1 — Core: config, validação e derivação (TDD)` (+260 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **31 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `EventMessage` connect `bus.py` to `await_until`, `test_pipeline.py`, `test_backpressure.py`, `ConnectionSnapshot`, `RecorderPipeline`, `StubPool`, `ChannelListener`, `FakeClock`, `Supervisor`, `_DropOldestBuffer`, `Harness`, `SwitchableFactory`, `FlowDefinition`?**
  _High betweenness centrality (0.022) - this node is a cross-community bridge._
- **Why does `ConnectionConfig` connect `ConnectionConfig` to `ConnectionSnapshot`, `test_heartbeat.py`, `Supervisor`, `WatchdogTask`, `ValueHeartbeat`, `test_subscriptions.py`, `ConnectionRuntime`, `OpcSimServer`, `ottima_opc_worker/state.py`, `ottima_opc_worker/connection.py`, `test_failure.py`, `opc-worker/tests/test_security.py`, `_SupersededAttemptError`, `ExplodingRuntime`, `await_until`, `ValueSubscription`?**
  _High betweenness centrality (0.021) - this node is a cross-community bridge._
- **Why does `RecorderPipeline` connect `RecorderPipeline` to `bus.py`, `test_pipeline.py`, `test_backpressure.py`, `ottima_recorder/main.py`, `_DropOldestBuffer`, `SwitchableFactory`?**
  _High betweenness centrality (0.018) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `ConnectionSnapshot` (e.g. with `ConnectionRuntime` and `_SupersededAttemptError`) actually correct?**
  _`ConnectionSnapshot` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 73 inferred relationships involving `await_until()` (e.g. with `test_com_watchdog_nao_emite_restored_nesta_camada()` and `test_conecta_e_sobe_sem_emitir_restored()`) actually correct?**
  _`await_until()` has 73 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `ConnectionRuntime` (e.g. with `ValueHeartbeat` and `ConnectionConfig`) actually correct?**
  _`ConnectionRuntime` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `PortSample` (e.g. with `OpcReadBlock` and `OpcWriteBlock`) actually correct?**
  _`PortSample` has 8 INFERRED edges - model-reasoned connections that need verification._