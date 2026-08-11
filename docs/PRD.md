# PRD — OttimaSystem (reescrita, v1)

**Produto:** OttimaSystem — plataforma on-premise de Controle Avançado de Processos (APC) com MPC
**Versão do documento:** 1.8 · 2026-08-11 · **Status:** aprovado para implementação (F1-F6 concluídas)
**Changelog 1.1:** adicionado o requisito de **ordem de execução explícita por bloco** (`exec_order`) — RF-307 e RF-401 revisados, ADR-024 criado (altera ADR-007). Sem impacto retroativo em F1/F2; efetivo a partir da F3.
**Changelog 1.2:** payload do canal `flow.status.<flow_id>` estendido com `ports` (valores de porta por varredura, para o canvas ao vivo) — resolve a lacuna do RF-404, que exigia publicar valores de portas sem definir onde. Decisão aprovada no brainstorm da F3 (2026-08-04, `docs/specs/F3-motor-canvas.md` Anexo A-3).
**Changelog 1.3:** payload do canal `mpc.state.<flow_id>.<block_id>` ganha `ts` e `prediction.ts`; consumidor `recorder` adicionado (§7.1); nova hypertable `MpcSample` (§4, retenção 1 mês, CAgg `mpc_samples_1m`); RF-703 passa a citar a fonte concreta (`mpc_samples`/`mpc_samples_1m`). PRD avança de 1.2 para v1.3 — decisão A-2 · F5R-01/11/26 (spec F5 §1.3-1, `docs/specs/F5-operacao.md`, 2026-08-06).
**Changelog 1.4:** §7.2 (JSON de projeto) reescrito para espelhar o schema real do bundle de export/import (`ts_seconds`, `direction`, `security_*`/`watchdog_*` planos, `data_type`/`description` nas tags, `auth_mode`/`auth_username` nas conexões, `exported_at`, `desired_state`, `tag_ref` objeto no `graph`); **RF-102** deixa de amarrar o export ao projeto **ativo** e passa a exportar **um projeto** (por id); §7.1 remove `api(WS)` dos consumidores de `opc.values.<conn_id>`; §7.3 detalha o `/ws` como `flow.status`, `mpc.state`, `events`. PRD avança de 1.3 para v1.4 — decisão A-14 · F6R-02 · RFC-05/06 (spec F6 §2.1-4, `docs/specs/F6-portabilidade-hardening.md`, 2026-08-08).
**Changelog 1.5:** dois blocos de filtro de sinal acrescentados à paleta — **Filtro 1ª ordem** e **Filtro Kalman**; RF-301 passa de 5 para **7 blocos**, nova §5.13 com RF-531/532/533, §1 e §4 atualizados. ADR-026 criado. Sem impacto retroativo: os cinco blocos originais e seus contratos seguem inalterados.
**Changelog 1.6:** nova camada **SSTO** (otimização econômica de regime permanente por LP acima do MPC) — §5.14 com **RF-901..RF-906**, fase **F7** no §8, hypertable `SstoRun` no §4 e o campo opcional `ssto` no payload de `mpc.state.<flow_id>.<block_id>` (§7.1). Nenhum canal novo. PRD avança de 1.5 para v1.6 — ADR-027 (2026-08-10).
**Changelog 1.7:** **disponibilidade de MV por ciclo** (ADR-028): `mpc.state.<flow_id>.<block_id>` ganha `vars.<mv_id>.status` (§7.1, campo opcional, só MV); **RF-604** ganha a semântica de status das tags de leitura de modo/readback; novos **RF-626/627/628** (classificação por ciclo, modo degradado e shed por perda total); **RF-625** passa a citar `status` por MV; novo evento `mpc_mv_status_changed` (§5.12/RF-803, sem mudança de schema). PRD avança de 1.6 para v1.7 — ADR-028 (`docs/adr/ADR-028-disponibilidade-de-mv-por-ciclo.md`, 2026-08-11).
**Changelog 1.8:** reorganização cosmética — **§5.13 (Blocos de filtro)** passa a **§5.11**, logo após os demais blocos de canvas (§5.6-§5.10, TFS termina em RF-52x e MPC começa em RF-60x, com os filtros RF-53x já entre os dois); Tela de operação avança de §5.11 para **§5.12** e Histórico e eventos, de §5.12 para **§5.13**. §5.14 (SSTO) inalterado. Nenhum RF renumerado, nenhum conteúdo ou contrato alterado — só a posição das seções. PRD avança de 1.7 para v1.8 — TD-013 (`docs/reports/_tech-debt.md`).
**Autor:** Luciano França Rocha (LFR Automação), consolidado em sessão de grilling
**Documentos-irmãos (normativos):** `adr/ADR-001 … ADR-028` · `GLOSSARY.md`

> Convenção: itens `RF-xxx` são requisitos funcionais; `RNF-xxx`, não-funcionais. Referências `(ADR-nnn)` apontam a decisão de arquitetura que governa o requisito. Em conflito entre este PRD e um ADR, **o ADR prevalece** e o PRD deve ser corrigido.

---

## 1. Visão e objetivo

O OttimaSystem executa **estratégias de controle avançado (APC)** sobre plantas industriais: o engenheiro monta a lógica num **canvas de blocos** (leitura/escrita OPC-UA, MPC, script Python, simulador TFS, filtros de sinal), o **motor** executa essa lógica ciclicamente no servidor, e o **operador** conduz o MPC por uma tela de operação com faceplates e tendência com **predição futura**. O controle regulatório permanece nos PIDs do PLC; o OttimaSystem assume e devolve malhas de forma **bumpless** e falha sempre para o lado seguro (PLC no comando).

Esta v1 é uma **reescrita completa do zero** do sistema legado (Django), sem compromisso de compatibilidade, sobre a stack definida nos ADR-001…006.

**Não-objetivos da v1:** versionamento de flows; ACK de alarmes; ideal resting values; identificação de modelos (ferramenta de step-test); AD/LDAP; HTTPS; i18n; multi-projeto ativo; histórico > 1 mês; app mobile; relatórios.

## 2. Papéis (ADR-015)

| Capacidade | admin | operador |
|---|:-:|:-:|
| Ver tudo (canvas ao vivo, trends, eventos, faceplates) | ✅ | ✅ |
| Operar modos LOCAL/REMOTO e MAN/AUTO | ✅ | ✅ |
| Escrever SP de CV; escrever MV em MAN | ✅ | ✅ |
| Deploy/parar flows; ativar projeto | ✅ | ❌ |
| Editar flows, blocos, conexões OPC, tags | ✅ | ❌ |
| Export/import de projeto; gestão de usuários | ✅ | ❌ |

RBAC por coluna `role` + dependências FastAPI (`require_admin`, `require_operator`). Toda ação de operação gera evento de auditoria (ADR-020).

## 3. Arquitetura de referência (resumo normativo)

**Stack (ADR-001…006):** React + Vite + shadcn/ui + React Flow + uPlot · FastAPI + SQLAlchemy 2.0 async · PostgreSQL + TimescaleDB (único) · Redis pub/sub (barramento) · workers asyncio dedicados · `uv` no ambiente Python · Docker Compose (ADR-023).

```
frontend (React+Vite) ⇄ api (FastAPI: REST + WebSocket)
                              │
                        Redis pub/sub  ←— barramento (ADR-002)
                        ↑      ↑      ↕
                 opc-worker  recorder  flow-runtime
                        │                (MPC/do-mpc, scripts, TFS)
                 Servidores OPC-UA        │
                 (asyncua, ≤5)      Postgres + TimescaleDB
```

| Serviço | Responsabilidade | ADRs |
|---|---|---|
| **api** | REST (auth, CRUD, comandos), WebSocket (valores, estado MPC, eventos), consulta de histórico | 001 |
| **opc-worker** | Único processo que fala OPC-UA: sessões, subscriptions → publica leituras; consome `opc.writes`; opera watchdog | 002, 006, 009, 021 |
| **flow-runtime** | Interpreta e executa flows (scan cycle); MPC (do-mpc), scripts, TFS; **SSTO** (alvos de regime permanente, no mesmo ciclo do MPC); publica estado/predições; recebe comandos | 004–007, 013, 014, 016, 018, 019, 022, 026, 027 |
| **recorder** | Assina o barramento e grava amostras na hypertable | 003 |
| **redis / db** | Barramento fire-and-forget / persistência única (cadastros + hypertables) | 002, 003 |

Loops vivos rodam em asyncio; `mpc.make_step()` e `exec()` de scripts sempre via executor, nunca no event loop (ADR-004). Sem Celery.

## 4. Modelo de domínio (entidades principais)

- **User** (id, nome, username, hash, role[admin|operador], ativo)
- **Project** (id, nome, descrição, ativo:boolean — no máx. 1 ativo; ADR-017)
- **OpcConnection** (id, project_id, nome, endpoint, security_policy, security_mode, auth[anon|userpass|cert], credenciais/refs de certificado, tags de watchdog {read_bit, write_bit}, período de toggle) (ADR-009, 021)
- **Tag** (id, connection_id, nome lógico, node_id OPC, direção[R|W], tipo de dado, EU, descrição)
- **Flow** (id, project_id, nome, Ts∈{0.5,1,2,5,10,30,60}, estado_desejado[rodando|parado], graph_json) (ADR-007, 011, 017)
- **Block/Edge** — dentro de `graph_json` (React Flow): nós tipados {opc_read, opc_write, mpc, script, tfs, first_order, kalman} com `config` própria — incluindo **`exec_order`** (int, 1..N, único no flow; ADR-024); arestas ligam portas tipadas (ADR-005)
- **Event** — hypertable (ts, severidade, origem, mensagem, payload JSON), retenção 1 mês (ADR-020)
- **Sample** — hypertable (ts, tag_id, valor, qualidade), retenção 1 mês + continuous aggregate 1 min (ADR-003)
- **MpcSample** — hypertable (ts, flow_id, block_id, var_id, v, sp, auto), retenção 1 mês + continuous aggregate `mpc_samples_1m` (ADR-003)
- **SstoRun** — hypertable (ts, flow_id, block_id, run_id, config_hash, model_hash, status, solver, solve_ms, objective, e os vetores mv/cv_ss/bias/dv/costs/delta_mv/mv_target/cv_target/given_up/active_constraints/duals em JSONB), **só INSERT**, retenção 1 mês (ADR-027, ADR-003)

## 5. Requisitos funcionais

### 5.1 Autenticação e usuários
- **RF-001** Login local por usuário e senha (Argon2/bcrypt), sessão via JWT. Sem AD/LDAP. (ADR-023)
- **RF-002** Admin faz CRUD de usuários e define o papel (admin/operador).
- **RF-003** Toda rota é protegida; autorização por dependência de papel. (ADR-015)

### 5.2 Projetos
- **RF-101** CRUD de projetos; N projetos armazenados, **apenas 1 ativo**; ativar um projeto encerra a execução do atual. (ADR-017)
- **RF-102** **Export** de **um projeto** (por id) em **JSON** contendo flows + configurações (conexões OPC, tags) com `schema_version`; **sem dados históricos e sem segredos** (senhas/chaves re-informadas no import). (ADR-012, 021)
- **RF-103** **Import** de projeto JSON com validação de schema; import cria projeto inativo.
- **RF-104** No boot do servidor, todos os flows sobem **parados**, aguardando deploy manual. (ADR-017)

### 5.3 Conexões OPC-UA, tags e watchdog
- **RF-201** CRUD de conexões OPC-UA (≤5 simultâneas): endpoint, SecurityPolicy None/Basic256Sha256, modo Sign/SignAndEncrypt, autenticação anônima, usuário/senha ou certificado X.509. (ADR-021)
- **RF-202** Gestão de certificados: gerar certificado de aplicação (autoassinado), exportá-lo (para trust list do servidor) e importar/confiar no certificado do servidor. (ADR-021)
- **RF-203** CRUD de tags (~100 R+W no total) com nome lógico, node_id, direção, tipo, EU e descrição; browse do address space é desejável, entrada manual de node_id é obrigatória.
- **RF-204** opc-worker mantém sessões persistentes com reconexão automática e publica cada leitura no canal `opc.values.<conn_id>` (payload: tag_id, ts, valor, qualidade). (ADR-002, 006)
- **RF-205** opc-worker consome `opc.writes` e executa escritas; toda escrita gera evento de auditoria com origem (bloco/usuário). (ADR-020)
- **RF-206** **Watchdog por conexão**: par de bits (leitura/escrita), sistema escreve NOT(bit lido) em ciclo fixo de 1–2 s; bit congelado por **> 10 s** ⇒ falha de comunicação. (ADR-009)
- **RF-207** Em falha de comunicação/OPC de uma conexão: **cessam imediatamente as escritas** daquela conexão e **param os flows** que a utilizam; evento de alarme é gerado. Retomada exige deploy manual. (ADR-009, 017)

### 5.4 Editor de flows (canvas)
- **RF-301** Canvas React Flow com paleta de **7 blocos**: OPC-Read, OPC-Write, MPC, Python-Script, TFS, Filtro 1ª ordem, Filtro Kalman; arrastar, conectar, configurar por duplo-clique. (ADR-005, 022, 026)
- **RF-302** Portas tipadas (numérico/booleano); o editor impede conexões de tipos incompatíveis, ciclos sem quebra explícita e entradas obrigatórias soltas.
- **RF-303** Cada flow define seu **Ts** na lista {0.5, 1, 2, 5, 10, 30, 60 s}. (ADR-007)
- **RF-304** **Hot-swap**: salvar um flow em execução aplica a nova definição **atomicamente na próxima varredura**, sem interrupção; blocos não alterados preservam estado; bloco MPC alterado é re-instanciado com partida bumpless (das MVs atuais). Sem versionamento. (ADR-011)
- **RF-305** O canvas em modo visualização mostra os **valores ao vivo** nas portas/blocos (via WebSocket) para admin e operador.
- **RF-306** Deploy/parar por flow (admin); estado desejado persistido, **não** auto-aplicado no boot. (ADR-017)
- **RF-307** Todo bloco possui **`exec_order`**: inteiro único de **1 a N** (N = total de blocos do flow). O editor auto-numera na inserção (próximo livre), permite edição manual, exibe o número como badge no nó, valida no salvamento (unicidade + sequência contígua 1..N), compacta a numeração ao excluir blocos e emite **aviso não-bloqueante** quando a ordem manual inverte o sentido de uma aresta. (ADR-024)

### 5.5 Motor de execução (flow-runtime)
- **RF-401** Execução por **scan cycle**: a cada Ts, avaliação de todos os blocos **em ordem crescente de `exec_order`** com os últimos valores conhecidos (snapshot do barramento). A ordenação topológica não é usada para execução (apenas como validação no editor). Se uma aresta A→B tiver `exec_order(B) < exec_order(A)`, B consome o valor de A da **varredura anterior** (atraso de 1 scan, determinístico). (ADR-007, 024)
- **RF-402** ~10 flows simultâneos como tasks asyncio independentes; falha de um flow não afeta os demais. (ADR-004, 006)
- **RF-403** Trabalho CPU-bound (solve do MPC, `exec` de script) roda via executor; o event loop nunca bloqueia. (ADR-004)
- **RF-404** Publica por varredura: `flow.status.<flow_id>` (rodando/parado/falha, duração do scan, overruns) e valores de portas para o canvas ao vivo.
- **RF-405** Consome canal `flow.commands` (deploy, parar, modos, SP, MV manual) originado da API; a UI reflete **estado publicado**, nunca eco de comando.

### 5.6 Blocos OPC-Read / OPC-Write
- **RF-501** OPC-Read: seleciona uma tag (direção R); saída = último valor + qualidade; qualidade ruim propaga flag de invalidez aos blocos a jusante.
- **RF-502** OPC-Write: seleciona uma tag (direção W); a cada varredura publica em `opc.writes` o valor da entrada; suprimido quando a conexão está em falha (RF-207) ou o flow está parado.

### 5.7 Bloco Python-Script (ADR-018)
- **RF-511** Usuário define no modal a quantidade de portas; entradas viram variáveis **IN1..INn** e o script atribui **OUT1..OUTn**.
- **RF-512** Dict **`state`** persistente entre varreduras por instância; sobrevive ao hot-swap se o bloco não mudou; zera ao parar o flow.
- **RF-513** Escopo restrito: apenas **`math` e `numpy`** disponíveis.
- **RF-514** Timeout ≈ **70% do Ts do flow**; ao estourar ou lançar exceção: mantém as últimas saídas + evento de alarme (com traceback no caso de exceção).

### 5.8 Bloco TFS — simulação (ADR-022)
- **RF-521** Matriz de funções de transferência **até 2×2**; cada elemento habilitável e configurável como **SOPDT** (K, τ1, τ2, θ) ou **IOPDT** (Ki, θ).
- **RF-522** Simulação em tempo discreto no Ts do flow (ZOH; tempo morto por buffer de atraso); estado interno persistente entre varreduras (regras do RF-304).

### 5.9 Bloco MPC — configuração (duplo-clique → modal com abas) (ADR-008, 013, 019)
- **RF-601** Categorias de variáveis: **MVs**, **CVs** (com SP), **Restrições** (faixa low/high, **precedência sobre CVs**), **DVs**. Validação: ≥1 MV e ≥1 (CV ou Restrição).
- **RF-602** Matriz de modelos: linhas = CVs+Restrições, colunas = MVs+DVs; tipo de resposta **por linha**: autorregulável → **SOPDT** (K, τ1, τ2, θ) por par; integrador → **IOPDT** (Ki, θ) por par.
- **RF-603** **TSS por CV/Restrição**; Np/Nc **não editáveis**, derivados: `Ts_mpc = multiplicador × Ts_flow`; `Np = ceil(max(TSS)/Ts_mpc)` com teto de segurança; `Nc = max(2, ceil(Np/4))`. (ADR-013, 014)
- **RF-604** Por MV: limites duros min/max, **Δu máx/ciclo**, e tags de integração com o PID: tag de escrita (**SP** para RCAS/CAS ou **OUT** para ROUT — modo-alvo configurável por MV), tag de comando de modo do PID, tag de leitura de modo (opcional) e **tag de readback da MV** (tracking). As duas tags de leitura (modo real e readback) são também a fonte do **status de disponibilidade da MV** (RF-626). (ADR-010, 028)
- **RF-605** Pesos: peso relativo de rastreamento por CV e prioridade por Restrição (penalidade de slack sempre dominante sobre pesos de CV). (ADR-019)
- **RF-606** **Multiplicador de execução** N: o MPC executa a cada N varreduras (`Ts_mpc = N × Ts_flow`); entre execuções, saídas mantêm o último valor. (ADR-014)
- **RF-607** Abas do modal: **Geral** (nome, multiplicador) · **Variáveis** (MV/CV/Restrição/DV + tags do PID) · **Modelos** (matriz) · **Horizontes** (TSS, Ts_mpc calculado, Np/Nc exibidos) · **Restrições & Limites** (faixas, limites de MV, Δu) · **Pesos** · resumo de validação.
- **RF-608** Montagem interna do do-mpc: conversão SOPDT/IOPDT → espaço de estados discreto; **tempo morto por aumento de estados**; validação alerta quando θ/Ts_mpc gera dimensão de estado excessiva. (ADR-013)

### 5.10 Bloco MPC — runtime, modos e bumpless (ADR-010, 014, 028)
- **RF-621** Eixos de modo por bloco MPC: **LOCAL/REMOTO** e, dentro de REMOTO, **MAN/AUTO**. Em LOCAL o sistema **não escreve MV**.
- **RF-622** **LOCAL:** a MV do bloco **segue (tracking) o readback da MV do PID**; transição LOCAL→REMOTO parte do valor vigente (bumpless). **REMOTO:** o sistema escreve o modo-alvo do PID (RCAS/CAS/ROUT) e o MPC assume; REMOTO→LOCAL devolve o PID a AUTO (SP/OUT-tracking no PLC).
- **RF-623** **MAN:** operador escreve as MVs pela UI (dentro dos limites duros); **AUTO:** MPC calcula. Transição MAN→AUTO é bumpless (MPC parte das MVs atuais).
- **RF-624** Orçamento do solver = **~70% do Ts_mpc**; overrun ⇒ mantém última MV + alarme + pula para a próxima execução (nunca acumula fila). Falha de convergência ⇒ mesmo tratamento, com evento distinto. (ADR-014)
- **RF-625** A cada solve, publica em `mpc.state.<flow_id>.<block_id>`: modos, status (watchdog/solver/overruns), MVs/CVs/Restrições atuais (com o **status de disponibilidade** por MV, RF-626), custo e **vetores de predição** (t futuro, CVs previstas, plano de MVs). Predições não são persistidas. (ADR-016, 028)
- **RF-626** **Disponibilidade de MV por ciclo (ADR-028).** A cada varredura, antes de montar o problema de otimização, cada MV é classificada em `rcas_ok` · `local_override` (modo real do PID ≠ modo-alvo) · `bad_quality` (readback ou modo com qualidade ruim) · `out_of_service` (tag configurada e sem valor no espelho). Precedência: ausência de leitura > qualidade ruim > divergência de modo. MV sem tags de leitura configuradas é sempre `rcas_ok` (comportamento pré-ADR-028). **Saturação não é status de disponibilidade.**
- **RF-627** **Modo degradado (ADR-028).** MV que não está `rcas_ok`: (a) é **congelada** na posição real medida — permanece no modelo, como distúrbio medido, para a predição das CVs seguir correta; (b) **não recebe escrita** no PID; (c) sua porta reporta a **posição real**, nunca o plano do MPC. As demais MVs seguem controlando normalmente — reclassificar uma MV não interrompe as outras. Ao voltar a `rcas_ok`, o movimento parte da posição física e o plano anterior à perda da malha é descartado (sem salto).
- **RF-628** **Shed por perda total (ADR-028, altera o comportamento do RF-604).** O shed do bloco (REMOTO→LOCAL + alarme `mpc_shed`) passa a exigir **nenhuma MV disponível** por 2 execuções consecutivas. Divergência parcial de modo **não** derruba o bloco. A confirmação de arme (2×Ts_mpc, `mpc_arm_failed {reason: no_confirm}`) permanece inalterada e continua exigindo confirmação de todas as MVs monitoradas.

### 5.11 Blocos de filtro de sinal (ADR-026)
- **RF-531** Ambos os blocos têm **uma entrada (`in`) e uma saída (`out`)**, numéricas; a entrada é obrigatória (RF-302). Estado interno persistente entre varreduras, com as regras de hot-swap do RF-304.
- **RF-532** **Filtro 1ª ordem:** parâmetro único **`tau`** (constante de tempo, em segundos), discretizado em ZOH no Ts do flow; `tau` abaixo de `Ts/10` degrada para passagem direta (mesma convenção do bloco TFS).
- **RF-533** **Filtro Kalman:** filtro escalar de passeio aleatório configurado por dois campos **na EU do próprio sinal**, ambos desvios padrão: **`measurement_noise`** (ruído da medição) e **`process_noise`** (variação esperada do valor verdadeiro por varredura). O estimador inicializa na primeira amostra válida após o reset. Variância e covariância são detalhe interno e não aparecem na interface.

### 5.12 Tela de operação (ADR-016)
- **RF-701** Tela dedicada por bloco MPC (seletor de MPC ativo): **faceplate principal** (LOCAL/REMOTO, MAN/AUTO, status de watchdog/solver, contador de overrun, comandos) no topo.
- **RF-702** **Faceplates menores** na base: um por variável do MPC — CV (PV + entrada de SP), MV (valor + entrada manual quando MAN), Restrição (valor + faixa), DV (somente leitura) — com EU e limites.
- **RF-703** **Centro — tendência (uPlot):** histórico das variáveis selecionadas (`mpc_samples`/`mpc_samples_1m`) **+ overlay da predição** de PVs e MVs no horizonte Np, a partir de "agora"; janela de tempo ajustável.
- **RF-704** Comandos de operação fluem: UI → REST (autorizado a operador) → `flow.commands` → runtime → estado republicado; todos geram evento de auditoria. (ADR-020)
- **RF-705** **Banner de alarmes ativos** (condições vigentes: watchdog, overrun, script em falha, conexão caída), sem ACK. (ADR-020)

### 5.13 Histórico e eventos
- **RF-801** recorder grava toda leitura publicada na hypertable `samples`; retenção **1 mês** via `add_retention_policy`; continuous aggregate de 1 min para trends longos. (ADR-003)
- **RF-802** API de histórico: consulta por tags + janela, com downsampling automático (bruto ≤ ~2 h; agregado acima).
- **RF-803** Log de eventos consultável e filtrável (severidade, origem, período) na UI; retenção 1 mês. (ADR-020)

### 5.14 Otimização econômica de regime permanente — SSTO (ADR-027)
- **RF-901** O bloco MPC aceita uma **função objetivo econômica** por variável (`economics.costs`: preço por MV, CV ou Restrição; preço negativo maximiza), desligada por default.
- **RF-902** A cada execução do MPC, e no mesmo ciclo, o sistema resolve um **LP de regime permanente** que calcula os alvos MVˢˢ\*/CVˢˢ\* a partir de `ΔCVˢˢ = G·ΔMV + Gd·ΔDV`, onde `G`/`Gd` são o ganho estático do modelo já usado pelo controlador. MV é a única variável de decisão, com limites **duros**; CV/Restrição são limites **suaves**; DV nunca é otimizada.
- **RF-903** Toda execução gera um **registro de auditoria imutável** (hypertable `ssto_runs`, retenção 1 mês): entradas, custos, solução, status, linhas desistidas em ordem, conjunto ativo, shadow prices, solver e tempo.
- **RF-904** **Inviabilidade:** folga penalizada por linha como 1ª defesa e **desistência por rank** (`priority`) como 2ª — a linha menos importante sai primeiro, iterativamente. Limite de MV nunca é relaxado.
- **RF-905** **Fallback:** com o SSTO desligado, inviável ou em falha, o MPC opera com o SP manual do operador, como na F4 — a camada econômica nunca interrompe o controle. Falha gera evento `ssto_infeasible`.
- **RF-906** **Anti-flipping:** penalização quadrática opcional sobre `‖ΔMV − ΔMV_anterior‖` (detuning, backend QP), configurável por bloco.

## 6. Requisitos não-funcionais

- **RNF-01 Dimensionamento:** ≥10 flows simultâneos, ~100 tags OPC, ≤5 servidores OPC-UA, 1 mês de retenção — num único host on-prem. (ADR-012)
- **RNF-02 Tempo:** jitter de scan < 10% do Ts em regime; solve do MPC dentro do orçamento de 70% do Ts_mpc no hardware de referência (4 vCPU) com matriz 2×2 e Np ≤ 60.
- **RNF-03 Segurança de processo:** nenhuma escrita em planta sem flow em deploy + watchdog vivo + REMOTO; boot nunca reassume malhas sozinho. (ADR-009, 010, 017)
- **RNF-04 Segurança de acesso:** senhas com Argon2/bcrypt; JWT com expiração; auditoria de toda escrita de operação; segredos fora do export. (ADR-020, 021, 023)
- **RNF-05 Resiliência:** perda do Redis ou queda de um serviço não corrompe estado persistido; opc-worker reconecta sozinho; consumidores toleram perda de mensagens (dados cíclicos). Comandos são idempotentes e refletidos por estado publicado. (ADR-002)
- **RNF-06 Deploy:** `docker compose up` num Linux on-prem sobe o sistema completo; volumes persistentes para Postgres e certificados; HTTP interno. (ADR-023)
- **RNF-07 Observabilidade:** logs estruturados por serviço; endpoint de health por serviço; heartbeat de opc-worker/flow-runtime visível na UI. (ADR-006)
- **RNF-08 Idioma:** toda a UI em pt-BR. (ADR-023)
- **RNF-09 Qualidade:** suíte de testes de malha fechada **MPC↔TFS** (sem hardware) cobrindo bumpless, precedência de restrição, overrun e hot-swap. (ADR-022)

## 7. Contratos-chave

### 7.1 Canais do barramento (Redis pub/sub) (ADR-002)

| Canal | Produtor | Consumidores | Payload (JSON) |
|---|---|---|---|
| `opc.values.<conn_id>` | opc-worker | flow-runtime, recorder | {tag_id, ts, value, quality} |
| `opc.writes` | flow-runtime, api | opc-worker | {conn_id, tag_id, value, source, ts} |
| `flow.status.<flow_id>` | flow-runtime | api(WS) | {state, scan_ms, overruns, ts, ports{block_id→{porta:{v, ok}}}} |
| `flow.commands` | api | flow-runtime | {flow_id, cmd, args, user, ts} |
| `mpc.state.<flow_id>.<block_id>` | flow-runtime | api(WS), recorder | {ts, modes, status, vars{var_id→{v, sp?, status?}}, cost, prediction{ts, t[], cv[][], mv[][]}, ssto?} |
| `events` | todos | api(WS→banner), gravação | {ts, severity, origin, message, payload} |

> `ssto` (ADR-027) é **opcional** e só aparece no quadro em que a camada de alvos executou: `{run_id, config_hash, model_hash, status, solver, solve_ms, objective, mv, cv_ss, bias, dv, costs, delta_mv, mv_target, cv_target, given_up[], active_constraints[], duals}`. O recorder o materializa em `ssto_runs`. **Nenhum canal novo foi criado.**

> `vars.<var_id>.sp` só existe em CV; `vars.<var_id>.status` só existe em MV (RF-626), com valores `rcas_ok` | `local_override` | `bad_quality` | `out_of_service`. Ambos são campos opcionais (`null` quando não se aplicam) — consumidor que ignora `status` continua válido. A transição de `status` gera o evento `mpc_mv_status_changed` (`payload: {var_id, from, to}`; `warning` ao sair de `rcas_ok`, `info` ao voltar); o status **não é persistido** em `mpc_samples`. (ADR-028)

### 7.2 JSON de projeto (export/import) (ADR-012)
```json
{"schema_version": 1, "exported_at": "2026-08-07T21:40:00Z",
 "project": {"name": "Planta C-101", "description": "Coluna debutanizadora"},
 "connections": [{"name": "gateway-1", "endpoint": "opc.tcp://10.0.0.5:4840",
   "security_policy": "basic256sha256", "security_mode": "sign_and_encrypt",
   "auth_mode": "user_password", "auth_username": "ottima",
   "watchdog_read_node_id": "ns=2;s=WD_R", "watchdog_write_node_id": "ns=2;s=WD_W",
   "watchdog_period_ms": 1500}],
 "tags": [{"connection": "gateway-1", "name": "TT-101", "node_id": "ns=2;s=TT101",
   "direction": "r", "data_type": "float", "eu": "C", "description": "Temperatura de topo"}],
 "flows": [{"name": "Coluna C-101", "ts_seconds": 1.0, "desired_state": "stopped",
   "graph": {"nodes": [], "edges": []}}]}
```
Nós do `graph` que referenciam tags (blocos `opc_read`/`opc_write` e variáveis do MPC) usam o objeto `tag_ref: {"connection": "...", "tag": "..."}` em vez de id numérico interno — omitido no exemplo acima (`graph` vazio, por brevidade). Sem segredos; credenciais re-informadas no import (RF-102/103).

### 7.3 API (grupos)
`/auth` · `/users` · `/projects` (+ `/activate`, `/export`, `/import`) · `/connections` (+ certificados) · `/tags` · `/flows` (+ `/deploy`, `/stop`) · `/operate` (modos, SP, MV) · `/history` · `/events` · `/ws` (flow.status, mpc.state, events).

## 8. Fases de implementação e critérios de aceite

| Fase | Entrega | Aceite |
|---|---|---|
| **F1 — Fundação** | Compose, schema DB (+hypertables/retenção), auth/RBAC, CRUD de projetos/conexões/tags | Login admin/operador; retenção ativa; `docker compose up` sobe tudo |
| **F2 — Aquisição** | opc-worker (3 modos de segurança), barramento, recorder, watchdog | Leituras de servidor real chegam ao trend; bit de watchdog alternando; queda ⇒ alarme em <12 s e bloqueio de escrita |
| **F3 — Motor + canvas** | Editor React Flow (5 blocos), scan cycle, hot-swap, blocos Read/Write/Script/TFS | Flow Script+TFS roda a 0.5 s sem jitter >10%; edição aplica na varredura seguinte sem parar |
| **F4 — MPC** | Modal com abas, montagem do-mpc (SOPDT/IOPDT, TSS→Np/Nc), modos, bumpless, multiplicador, orçamento, **disponibilidade de MV por ciclo (RF-626..628)** | Malha fechada MPC↔TFS: assume/devolve sem salto de MV; restrição vence CV; overrun mantém MV + alarme; **MV tirada de RCAS durante a execução é congelada e volta sem salto, com as demais MVs seguindo em AUTO** |
| **F5 — Operação** | Tela de operação (faceplates + trend com predição), eventos/banner, auditoria | Operador conduz LOCAL/REMOTO/MAN/AUTO, escreve SP/MV; predição sobreposta ao histórico |
| **F6 — Portabilidade & hardening** | Export/import JSON, gestão de certificados, health/heartbeats, testes RNF-09 | Projeto exportado importa limpo em instalação nova (re-informando segredos); suíte MPC↔TFS verde |
| **F7 — Otimização econômica (SSTO)** | Camada `target_calculation` (LP/QP plugável), inviabilidade por rank + folga, auditoria `ssto_runs`, integração como referência do MPC com fallback manual | Alvo ótimo respeita todos os limites; inviabilidade desiste da linha de menor prioridade e registra a ordem; SSTO desligado reproduz o comportamento da F4 bit a bit |

## 9. Riscos e mitigações

1. **IPOPT vs Ts curto** — mitigado por multiplicador (ADR-014), orçamento 70% e teto de Np; teste de carga na F4 com hardware de referência.
2. **Explosão de estados por tempo morto** (θ≫Ts_mpc) — validação no formulário com alerta e teto (RF-608).
3. **Pub/sub sem garantia de entrega** — aceitável para dados cíclicos; comandos usam canal próprio + UI orientada a estado publicado (RNF-05).
4. **Hot-swap concorrente** — troca atômica de definição entre varreduras com preservação de estado por id de bloco (RF-304); testes dedicados na F3.
6. **`exec_order` incoerente com o fluxo de dados** — usuário pode ordenar um consumidor antes do produtor (atraso de 1 scan não intencional); mitigado pelo aviso de inversão no editor (RF-307) e pela auto-numeração na inserção.
5. **Bumpless dependente do PLC** — exige SP/OUT-tracking configurado no PID do PLC; documentar pré-requisitos de comissionamento por malha (guia de integração, F6).
7. **LP flipping no SSTO** — solução de LP vive num vértice: custos quase paralelos a uma aresta fazem o alvo saltar entre extremos por ruído de medida. Mitigado pelo detuning quadrático opcional (RF-906, backend QP); com `ρ = 0` o comportamento de vértice é escolha explícita do usuário. (ADR-027)
8. **Alvo econômico vs. proteção de faixa** — preço agressivo empurra a planta contra os limites. Mitigado por limite de MV duro e inviolável, faixas de CV/Restrição como restrição do próprio LP, desistência por rank auditada e fallback para o SP do operador (RF-902/904/905).

## 10. Referências

- `adr/ADR-001…026` — decisões de arquitetura (normativas)
- `GLOSSARY.md` — vocabulário do domínio
- do-mpc · asyncua · React Flow (@xyflow/react) · TimescaleDB · uPlot · SciPy/HiGHS · OSQP
