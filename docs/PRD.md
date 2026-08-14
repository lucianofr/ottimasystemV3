# PRD — OttimaSystem (reescrita, v1)

**Produto:** OttimaSystem — plataforma on-premise de Controle Avançado de Processos (APC) com MPC
**Versão do documento:** 2.3 · 2026-08-14 · **Status:** aprovado para implementação (F1-F6 concluídas)
**Changelog 1.1:** adicionado o requisito de **ordem de execução explícita por bloco** (`exec_order`) — RF-307 e RF-401 revisados, ADR-024 criado (altera ADR-007). Sem impacto retroativo em F1/F2; efetivo a partir da F3.
**Changelog 1.2:** payload do canal `flow.status.<flow_id>` estendido com `ports` (valores de porta por varredura, para o canvas ao vivo) — resolve a lacuna do RF-404, que exigia publicar valores de portas sem definir onde. Decisão aprovada no brainstorm da F3 (2026-08-04, `docs/specs/F3-motor-canvas.md` Anexo A-3).
**Changelog 1.3:** payload do canal `mpc.state.<flow_id>.<block_id>` ganha `ts` e `prediction.ts`; consumidor `recorder` adicionado (§7.1); nova hypertable `MpcSample` (§4, retenção 1 mês, CAgg `mpc_samples_1m`); RF-703 passa a citar a fonte concreta (`mpc_samples`/`mpc_samples_1m`). PRD avança de 1.2 para v1.3 — decisão A-2 · F5R-01/11/26 (spec F5 §1.3-1, `docs/specs/F5-operacao.md`, 2026-08-06).
**Changelog 1.4:** §7.2 (JSON de projeto) reescrito para espelhar o schema real do bundle de export/import (`ts_seconds`, `direction`, `security_*`/`watchdog_*` planos, `data_type`/`description` nas tags, `auth_mode`/`auth_username` nas conexões, `exported_at`, `desired_state`, `tag_ref` objeto no `graph`); **RF-102** deixa de amarrar o export ao projeto **ativo** e passa a exportar **um projeto** (por id); §7.1 remove `api(WS)` dos consumidores de `opc.values.<conn_id>`; §7.3 detalha o `/ws` como `flow.status`, `mpc.state`, `events`. PRD avança de 1.3 para v1.4 — decisão A-14 · F6R-02 · RFC-05/06 (spec F6 §2.1-4, `docs/specs/F6-portabilidade-hardening.md`, 2026-08-08).
**Changelog 1.5:** dois blocos de filtro de sinal acrescentados à paleta — **Filtro 1ª ordem** e **Filtro Kalman**; RF-301 passa de 5 para **7 blocos**, nova §5.13 com RF-531/532/533, §1 e §4 atualizados. ADR-026 criado. Sem impacto retroativo: os cinco blocos originais e seus contratos seguem inalterados.
**Changelog 1.6:** nova camada **SSTO** (otimização econômica de regime permanente por LP acima do MPC) — §5.14 com **RF-901..RF-906**, fase **F7** no §8, hypertable `SstoRun` no §4 e o campo opcional `ssto` no payload de `mpc.state.<flow_id>.<block_id>` (§7.1). Nenhum canal novo. PRD avança de 1.5 para v1.6 — ADR-027 (2026-08-10).
**Changelog 1.7:** **disponibilidade de MV por ciclo** (ADR-028): `mpc.state.<flow_id>.<block_id>` ganha `vars.<mv_id>.status` (§7.1, campo opcional, só MV); **RF-604** ganha a semântica de status das tags de leitura de modo/readback; novos **RF-626/627/628** (classificação por ciclo, modo degradado e shed por perda total); **RF-625** passa a citar `status` por MV; novo evento `mpc_mv_status_changed` (§5.12/RF-803, sem mudança de schema). PRD avança de 1.6 para v1.7 — ADR-028 (`docs/adr/ADR-028-disponibilidade-de-mv-por-ciclo.md`, 2026-08-11).
**Changelog 1.8:** reorganização cosmética — **§5.13 (Blocos de filtro)** passa a **§5.11**, logo após os demais blocos de canvas (§5.6-§5.10, TFS termina em RF-52x e MPC começa em RF-60x, com os filtros RF-53x já entre os dois); Tela de operação avança de §5.11 para **§5.12** e Histórico e eventos, de §5.12 para **§5.13**. §5.14 (SSTO) inalterado. Nenhum RF renumerado, nenhum conteúdo ou contrato alterado — só a posição das seções. PRD avança de 1.7 para v1.8 — TD-013 (`docs/reports/_tech-debt.md`).
**Changelog 1.9:** watchdog de comunicação deixa de ser configurado **por conexão OPC** e passa a ser **por flow** — uma conexão pode ser um gateway na frente de vários PLCs independentes, e o watchdog precisa monitorar especificamente por onde cada flow escreve seu controle. `OpcConnection` perde `watchdog_read_node_id`/`watchdog_write_node_id`/`watchdog_period_ms`; `Flow` ganha esses três campos mais `watchdog_enabled` e `watchdog_connection_id` (§4); RF-206/207 e §7.2 (bundle) atualizados. Também corrigido: o sistema copia o bit lido sem inverter (o PLC aplica o NOT), não o contrário como documentado antes. PRD avança de 1.8 para v1.9 — ADR-009 revisado (2026-08-11).
**Changelog 2.0:** **função objetivo por variável do MPC** — cada MV/CV/Restrição ganha `objective` no config (editável no modal do bloco): CV `none/maximize/minimize/observe_limit/target/psv`, MV `none/maximize/minimize/psv/equalize`, Restrição `none/maximize/minimize`. O SSTO deixa de exigir `economics.enabled`: `optimization_enabled` liga a camada por `economics` habilitado **ou** qualquer variável com `objective ≠ "none"`; os objetivos viram termos lineares do LP (preço por span, âncoras L1 no SP do operador ou no valor preferido da MV, equalização em fração de escala) e a camada dinâmica persegue o alvo de MV via TVP `utarget_*`. Na Operação, card **"Otimizador"** abaixo do faceplate principal com status da última execução, valor atual e alvo por variável; novo `GET /api/history/ssto/last` para o cold-start. RF-607/901 revisados, novos **RF-907..RF-910**, endpoint novo no §7.3. PRD avança de 1.9 para v2.0 — ADR-027 estendido (2026-08-11).
**Changelog 2.1:** lote de operação/configuração do MPC — **timeout do watchdog configurável por flow** (`watchdog_timeout_s`, 2–120 s, default 10; RF-206); **canal `opc.values` no `/ws`** com assinatura filtrada por tag (decisão F6 A-1 **revertida**: faceplates e ponta viva do trend na taxa OPC, coalescidos a 250 ms no cliente); **página Configurações** (admin) com retenção de eventos (1–90 dias, default 30 — ADR-020 revisado) e **nível de log dos 4 serviços aplicado em runtime** (≤10 s, poll); **zero/span por variável do MPC** — ganhos da matriz passam a ser **adimensionais %/%** (RF-602 revisado) e a escala do faceplate é a faixa de instrumento; **`max_rate` (EU/s)** no lugar de `du_max` (EU/ciclo) — RF-604 revisado, migração automática dos configs gravados; novos campos por variável (description ≤14, trajetória de referência por CV, track SP opt-out, fail actions por CV/Restrição/MV, faixa do SP no SSTO, SP remoto por tag, modo local no shed) — **RF-609..RF-615**; janela de tempo por **valor inteiro + seg/min** nas duas telas de trend. PRD avança de 2.0 para v2.1 (2026-08-11).
**Changelog 2.2:** novo bloco **Fuzzy** (lógica difusa via FLL colado, `pyfuzzylite`) — RF-301 passa de 7 para **8 blocos**; nova **§5.12** com **RF-541..543**, logo após os blocos de filtro (§5.11), Tela de operação avança de §5.12 para **§5.13**, Histórico e eventos de §5.13 para **§5.14** e SSTO de §5.14 para **§5.15** (mesma reorganização cosmética do changelog 1.8, nenhum RF renumerado); §4 (`Block/Edge`) e §7.2 ganham o node `fuzzy`. ADR-029 criado. PRD avança de 2.1 para v2.2 — decisão do usuário no Gate (2026-08-14).
**Changelog 2.3:** tela **FUZZY OPERATE** — novo **RF-544** (§5.12): página de operação do bloco `fuzzy` com funções de pertinência, normas, regras com grau de ativação e trend das portas, animada por execução do engine. Canal novo **`fuzzy.state.<flow_id>.<block_id>`** (§7.1, produtor flow-runtime, consumidores api(WS) e recorder, throttle de 0,25 s na origem), nova hypertable **`FuzzySample`** (§4, retenção 1 mês + CAgg `fuzzy_samples_1m`) e as rotas `/operate/fuzzy…` e `/history/fuzzy` mais a chave `fuzzy_state` no `/ws` (§7.3). Nenhum contrato existente alterado. ADR-030 criado. PRD avança de 2.2 para v2.3 (2026-08-14).
**Autor:** Luciano França Rocha (LFR Automação), consolidado em sessão de grilling
**Documentos-irmãos (normativos):** `adr/ADR-001 … ADR-030` · `GLOSSARY.md`

> Convenção: itens `RF-xxx` são requisitos funcionais; `RNF-xxx`, não-funcionais. Referências `(ADR-nnn)` apontam a decisão de arquitetura que governa o requisito. Em conflito entre este PRD e um ADR, **o ADR prevalece** e o PRD deve ser corrigido.

---

## 1. Visão e objetivo

O OttimaSystem executa **estratégias de controle avançado (APC)** sobre plantas industriais: o engenheiro monta a lógica num **canvas de blocos** (leitura/escrita OPC-UA, MPC, script Python, simulador TFS, filtros de sinal, fuzzy), o **motor** executa essa lógica ciclicamente no servidor, e o **operador** conduz o MPC por uma tela de operação com faceplates e tendência com **predição futura**. O controle regulatório permanece nos PIDs do PLC; o OttimaSystem assume e devolve malhas de forma **bumpless** e falha sempre para o lado seguro (PLC no comando).

Esta v1 é uma **reescrita completa do zero** do sistema legado (Django), sem compromisso de compatibilidade, sobre a stack definida nos ADR-001…006.

**Não-objetivos da v1:** versionamento de flows; ACK de alarmes; ideal resting values **completo** (a v2.0 implementa o caso do alvo econômico — RF-909, MV persegue `mv_target` via TVP `utarget_*` com peso fixo suave — mas sem UI de calibração do peso nem suporte a `MvVar.psv` clássico fora do SSTO); identificação de modelos (ferramenta de step-test); AD/LDAP; HTTPS; i18n; multi-projeto ativo; histórico > 1 mês; app mobile; relatórios.

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
- **OpcConnection** (id, project_id, nome, endpoint, security_policy, security_mode, auth[anon|userpass|cert], credenciais/refs de certificado) (ADR-021)
- **Tag** (id, connection_id, nome lógico, node_id OPC, direção[R|W], tipo de dado, EU, descrição)
- **Flow** (id, project_id, nome, Ts∈{0.5,1,2,5,10,30,60}, estado_desejado[rodando|parado], graph_json, watchdog_enabled:boolean, watchdog_connection_id, watchdog_read_node_id, watchdog_write_node_id, watchdog_period_ms, watchdog_timeout_s) (ADR-007, 009, 011, 017)
- **Block/Edge** — dentro de `graph_json` (React Flow): nós tipados {opc_read, opc_write, mpc, script, tfs, first_order, kalman, fuzzy} com `config` própria — incluindo **`exec_order`** (int, 1..N, único no flow; ADR-024); arestas ligam portas tipadas (ADR-005)
- **Event** — hypertable (ts, severidade, origem, mensagem, payload JSON), retenção **configurável pelo admin, 1–90 dias (default 30)** (ADR-020 revisado)
- **Sample** — hypertable (ts, tag_id, valor, qualidade), retenção 1 mês + continuous aggregate 1 min (ADR-003)
- **MpcSample** — hypertable (ts, flow_id, block_id, var_id, v, sp, auto), retenção 1 mês + continuous aggregate `mpc_samples_1m` (ADR-003)
- **FuzzySample** — hypertable (ts, flow_id, block_id, var_id, v), `var_id` = porta `IN1..OUTn` (ADR-029), retenção 1 mês + continuous aggregate `fuzzy_samples_1m` (ADR-003, ADR-030)
- **SstoRun** — hypertable (ts, flow_id, block_id, run_id, config_hash, model_hash, status, solver, solve_ms, objective, e os vetores mv/cv_ss/bias/dv/costs/delta_mv/mv_target/cv_target/given_up/active_constraints/duals em JSONB), **só INSERT**, retenção 1 mês (ADR-027, ADR-003)
- **HistoryRetentionSettings** — singleton (id=1): `retention_days` (variáveis, 1–120) + `events_retention_days` (eventos, 1–90) (ADR-003/020 revisados)
- **SystemSettings** — singleton (id=1): `log_level` (DEBUG/INFO/WARNING/ERROR/CRITICAL), aplicado em runtime aos 4 serviços (RF-805)

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
- **RF-206** **Watchdog por flow**: um flow habilita o watchdog (`watchdog_enabled`) apontando uma conexão OPC-UA (`watchdog_connection_id`) e um par de nós distintos (leitura/escrita); o sistema copia o bit lido para a escrita (sem inverter) em ciclo fixo de 1–2 s; bit congelado por **> `watchdog_timeout_s`** (2–120 s, default 10, configurável por flow — e sempre ≥ 2× o período de toggle) ⇒ falha de comunicação daquele flow. (ADR-009)
- **RF-207** Em falha de comunicação/OPC de um flow: **cessam imediatamente as escritas** daquele flow e **o flow para**; flows-irmãos que usam a mesma conexão, mas não o watchdog em falha, seguem rodando; evento de alarme é gerado. Retomada exige deploy manual. (ADR-009, 017)

### 5.4 Editor de flows (canvas)
- **RF-301** Canvas React Flow com paleta de **8 blocos**: OPC-Read, OPC-Write, MPC, Python-Script, TFS, Filtro 1ª ordem, Filtro Kalman, Fuzzy; arrastar, conectar, configurar por duplo-clique. (ADR-005, 022, 026, 029)
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
- **RF-602** Matriz de modelos: linhas = CVs+Restrições, colunas = MVs+DVs; tipo de resposta **por linha**: autorregulável → **SOPDT** (K, τ1, τ2, θ) por par; integrador → **IOPDT** (Ki, θ) por par. Os ganhos `K`/`Ki` são declarados **adimensionais (%/%)**: `K = ΔCV% / ΔMV%` sobre as faixas de instrumento (zero/span, RF-609) — o motor converte para EU multiplicando por `span_linha/span_coluna` na montagem.
- **RF-603** **TSS por CV/Restrição**; Np/Nc **não editáveis**, derivados: `Ts_mpc = multiplicador × Ts_flow`; `Np = ceil(max(TSS)/Ts_mpc)` com teto de segurança; `Nc = max(2, ceil(Np/4))`. (ADR-013, 014)
- **RF-604** Por MV: limites duros min/max, **taxa máxima de variação `max_rate` (EU/s** — o Δu por ciclo do solve é `max_rate × Ts_mpc`; migração dos `du_max` gravados é automática**)** e tags de integração com o PID: tag de escrita (**SP** para RCAS/CAS ou **OUT** para ROUT — modo-alvo configurável por MV), tag de comando de modo do PID, tag de leitura de modo (opcional) e **tag de readback da MV** (tracking). As duas tags de leitura (modo real e readback) são também a fonte do **status de disponibilidade da MV** (RF-626). (ADR-010, 028)
- **RF-605** Pesos: peso relativo de rastreamento por CV e prioridade por Restrição (penalidade de slack sempre dominante sobre pesos de CV). (ADR-019)
- **RF-606** **Multiplicador de execução** N: o MPC executa a cada N varreduras (`Ts_mpc = N × Ts_flow`); entre execuções, saídas mantêm o último valor. (ADR-014)
- **RF-607** Abas do modal: **Geral** (nome, multiplicador) · **Variáveis** (MV/CV/Restrição/DV + tags do PID + **combobox "Função objetivo" por variável**, RF-901; cada variável com **description ≤14, zero/span** — RF-609/610; CV com **trajetória τ** (RF-611), **track SP** (RF-612) e **prioridade**; seção **Avançado** por variável com **fail action** (RF-613), **faixa do SP %** e **SP remoto** de CV (RF-614/615) e **modo local no shed** de MV) · **Modelos** (matriz) · **Horizontes** (TSS, Ts_mpc calculado, Np/Nc exibidos) · **Restrições & Limites** (faixas, limites de MV, taxa máx.) · **Pesos** · resumo de validação. Regras de objetivo no espelho client-side: linha `integrating` desabilita o combobox e zera para `none`; `psv` de MV abre o campo "Valor preferido" (persistido no save, validado dentro de `limits`); `equalize` com exatamente 1 MV bloqueia o Aplicar com a mensagem pt-BR do servidor.
- **RF-608** Montagem interna do do-mpc: conversão SOPDT/IOPDT → espaço de estados discreto; **tempo morto por aumento de estados**; validação alerta quando θ/Ts_mpc gera dimensão de estado excessiva. (ADR-013)
- **RF-609** **Faixa de instrumento por variável (zero/span).** MV/CV/Restrição/DV têm `zero` (default 0) e `span` (> 0, default 100): a faixa é `[zero, zero+span]`. Usos: conversão %/%→EU dos ganhos (RF-602), normalização dos custos dinâmicos e dos preços/âncoras/equalize do SSTO (RF-901), escala da barra do faceplate (RF-702) e a banda do SP (RF-615). Os defaults 0/100 dão razão 1 na conversão — configs gravados antes do campo comportam-se bit a bit igual.
- **RF-610** **Descrição curta por variável** (`description`, ≤ 14 caracteres, MV/CV/Restrição) exibida sob o nome no faceplate.
- **RF-611** **Trajetória de referência por CV** (`traj_tau_s`, ≥ 0): com τ > 0, a referência escrita no horizonte é a exponencial `r_k = SP − (SP − y₀)·e^(−(k+1)·Ts_mpc/τ)`; τ = 0 é o degrau de sempre.
- **RF-612** **Track SP opt-out por CV** (`track_sp`, default `true`): fora de AUTO, o SP rastreia o PV (bumpless) só quando ligado; desligado, o SP do operador é preservado em MAN/LOCAL.
- **RF-613** **Fail actions por variável** (avaliadas só em REMOTO, debounce de 2 execuções do MPC — mesma régua do shed RF-628): MV `no_action`/`shed_local`/`manual`; CV/Restrição acrescentam `simulate_manual`/`simulate_shed_local`, que sustentam o **valor previsto** da linha por até `fail_timeout_s` (default 60 s) antes da ação final. Disparo gera o evento `mpc_fail_action_triggered` (`{var_id, action, reason}`); `shed_local` usa a mesma rotina do shed global (com razão distinta no payload do `mpc_shed`). Em qualquer devolução da MV ao controle local, o valor escrito no `mode_cmd` é o **`local_shed_mode` da MV quando configurado** (exige MV com PID), senão `mode_values.auto`. Default `no_action` reproduz o comportamento anterior bit a bit.
- **RF-614** **SP remoto por tag OPC-UA** (`remote_sp_tag_id`, só leitura): a cada varredura o SP da CV vem da tag (clamp em `sp_limits`; qualidade ruim/ausente mantém o último, sem evento); CV com SP remoto ignora o `track_sp` e tem a escrita manual de SP recusada (422) e desabilitada na UI.
- **RF-615** **Faixa do SP no SSTO** (`sp_range_pct`, % do span da CV; `null` = livre): com SP do operador disponível, os limites da linha no LP ficam presos a `SP ± pct/100 × span` (o estático que conflite cede à banda; linha integradora ignora — seus limites são ±ε de taxa).

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

### 5.12 Bloco Fuzzy (ADR-029)
- **RF-541** Usuário cola o texto **FLL** (FuzzyLite Language) no modal do bloco e seleciona a quantidade de **entradas e saídas** (1..8 cada); entradas viram portas numéricas **IN1..INn** e saídas **OUT1..OUTn**, mapeadas **posicionalmente** à ordem de declaração de `input_variables`/`output_variables` no FLL — não por nome. Cada saída tem sua **`output_eu`** (paridade com Script/TFS). O FLL é validado no **save** (parser + `is_ready` da `pyfuzzylite`, 422 em caso de erro) e de novo na **construção do engine no deploy**. (ADR-029)
- **RF-542** Saída **não-finita** (`nan`/`inf` — p.ex. nenhuma regra ativa com `default: nan`) mantém o **último valor bom daquela porta** com `ok=False`; antes da primeira saída boa, valor `null`. `nan` **nunca** propaga com `ok=True`. Exceção na avaliação do engine mantém todas as saídas do bloco + `ok=False`. (ADR-029)
- **RF-543** **Reset** zera o engine (`Engine.restart()`); `lock-previous` do FLL, quando configurado, opera **entre varreduras** mas não sobrevive a `stop`/deploy do flow. **Hot-swap** preserva o estado do bloco quando a config não muda (regras do RF-304). (ADR-029)
- **RF-544** **Tela FUZZY OPERATE (ADR-030).** Página de operação por bloco `fuzzy` (combobox dos blocos fuzzy do projeto ativo) que mostra, para o bloco escolhido: as **funções de pertinência** de cada variável de entrada e saída (curvas amostradas **no servidor** — o frontend nunca parseia FLL, ADR-005/029), as **normas** em uso (conjunction, disjunction, implication, activation, aggregation e defuzzificador), a **tabela de regras** com o grau de ativação de cada uma e destaque da **regra dominante**, e uma **tendência** das portas do bloco com os mesmos recursos do trend de operação (`fuzzy_samples`/`fuzzy_samples_1m`, janela ajustável, ≤6 penas). A cada execução do engine, o canal `fuzzy.state.<flow_id>.<block_id>` (§7.1) anima o valor crisp de entrada, os graus de pertinência, a regra ativada e o valor defuzzificado — o operador enxerga a inferência acontecendo, não só o resultado.

### 5.13 Tela de operação (ADR-016)
- **RF-701** Tela dedicada por bloco MPC (seletor de MPC ativo): **faceplate principal** (LOCAL/REMOTO, MAN/AUTO, status de watchdog/solver, contador de overrun, comandos) no topo.
- **RF-702** **Faceplates menores** na base: um por variável do MPC — CV (PV + entrada de SP), MV (valor + entrada manual quando MAN), Restrição (valor + faixa), DV (somente leitura) — com EU e limites. A **escala da barra é a faixa de instrumento `[zero, zero+span]`** (RF-609); os limites de engenharia seguem como clamp dos comandos. O **PV ao vivo vem do canal `opc.values`** (assinatura filtrada por tag no `/ws`, taxa OPC — decisão F6 A-1 revertida), com fallback ao `mpc.state` para variável sem tag mapeada; descrição curta (RF-610) aparece sob o nome; CV com SP remoto (RF-614) tem a entrada de SP desabilitada.
- **RF-703** **Centro — tendência (uPlot):** histórico das variáveis selecionadas (`mpc_samples`/`mpc_samples_1m`) **+ overlay da predição** de PVs e MVs no horizonte Np, a partir de "agora"; janela de tempo ajustável por **valor inteiro + unidade (segundos/minutos)** — mesma entrada no trend de engenharia. A **ponta viva adensa na taxa OPC** para as variáveis com tag mapeada (o histórico REST segue amostrado por Ts_mpc — o adensamento é só da borda viva); a **linha "agora" é o relógio de parede** e anda a cada segundo mesmo sem dado novo (zoom manual a congela); **reset de layout** zera zoom X, volta ao vivo e limpa as escalas Y por variável (inclusive a preferência persistida) — habilitado também ao vivo no trend de engenharia.
- **RF-704** Comandos de operação fluem: UI → REST (autorizado a operador) → `flow.commands` → runtime → estado republicado; todos geram evento de auditoria. (ADR-020)
- **RF-705** **Banner de alarmes ativos** (condições vigentes: watchdog, overrun, script em falha, conexão caída), sem ACK. (ADR-020)

### 5.14 Histórico e eventos
- **RF-801** recorder grava toda leitura publicada na hypertable `samples`; retenção **configurável pelo admin, 1–120 dias (default 30)** via `add_retention_policy`, aplicada a `samples`/`samples_1m`/`mpc_samples`/`mpc_samples_1m`; continuous aggregate de 1 min para trends longos. (ADR-003)
- **RF-802** API de histórico: consulta por tags + janela, com downsampling automático (bruto ≤ ~2 h; agregado acima).
- **RF-803** Log de eventos consultável e filtrável (severidade, origem, período) na UI; retenção **`events` configurável pelo admin, 1–90 dias (default 30)** — mesma mecânica de `add_retention_policy` + `drop_chunks` imediato (ADR-020 revisado).
- **RF-805** **Página Configurações (admin):** retenções de variáveis e de eventos e o **nível de log dos serviços** (DEBUG…CRITICAL, default INFO) — o PUT persiste no singleton `system_settings`, aplica no root logger da API na hora e propaga aos demais serviços em ≤ 10 s (poll `watch_log_level`); mudança gera o evento `system_log_level_changed`. A página é admin-only (operador é redirecionado; o PUT é 403 para operador; o GET segue operador).

### 5.15 Otimização econômica de regime permanente — SSTO (ADR-027)
- **RF-901** Cada variável do bloco MPC aceita uma **função objetivo** editável no modal (aba Variáveis) e efetiva no LP do SSTO: **MV** `none`/`maximize`/`minimize`/`psv`/`equalize`; **CV** `none`/`maximize`/`minimize`/`observe_limit`/`target`/`psv`; **Restrição** `none`/`maximize`/`minimize` — `"none"` (default) = desligado, config salvo antes da feature carrega idêntico. Os objetivos viram **termos lineares do LP** (`maximize`/`minimize` = preço `∓1/span` na coluna ou na linha projetada por `c_row·G`; `target`/`psv`/`observe_limit` = âncora L1 no SP do operador com pesos decrescentes; `psv` de MV = âncora no valor preferido configurado; `equalize` = nivelamento em fração da escala `(u−min)/span`). **Todos os `span` destes termos — e os do custo dinâmico do MPC — são o span de instrumento (zero/span, RF-609)**, não mais a largura de `limits`/`sp_limits`/`range`. O campo legado `economics.costs` (preço cru por id, negativo maximiza) permanece como termo **aditivo**. O SSTO liga quando `economics.enabled = true` **ou** qualquer variável com `objective ≠ "none"` (`optimization_enabled`). **Validação** (Pydantic → 422 no save, mesma mensagem no espelho client-side do modal): objetivo exige linha `selfreg` (`integrating` decide taxa, ADR-027 §4); MV `psv` exige `psv` preenchido e dentro de `limits` (e `psv` fora do PSV é rejeitado); `equalize` exige ≥2 MVs marcadas. O `economics_config_hash` passa a cobrir objetivos **e zero/span/sp_range_pct** — mudar `objective` ou uma faixa de instrumento é uma versão nova do problema econômico (e o `gain_model_hash` cobre o span de todas as variáveis, pois o span muda o ganho efetivo em EU — RF-602). (ADR-027 estendido)
- **RF-902** A cada execução do MPC, e no mesmo ciclo, o sistema resolve um **LP de regime permanente** que calcula os alvos MVˢˢ\*/CVˢˢ\* a partir de `ΔCVˢˢ = G·ΔMV + Gd·ΔDV`, onde `G`/`Gd` são o ganho estático do modelo já usado pelo controlador. MV é a única variável de decisão, com limites **duros**; CV/Restrição são limites **suaves**; DV nunca é otimizada.
- **RF-903** Toda execução gera um **registro de auditoria imutável** (hypertable `ssto_runs`, retenção 1 mês): entradas, custos, solução, status, linhas desistidas em ordem, conjunto ativo, shadow prices, solver e tempo.
- **RF-904** **Inviabilidade:** folga penalizada por linha como 1ª defesa e **desistência por rank** (`priority`) como 2ª — a linha menos importante sai primeiro, iterativamente. Limite de MV nunca é relaxado.
- **RF-905** **Fallback:** com o SSTO desligado, inviável ou em falha, o MPC opera com o SP manual do operador, como na F4 — a camada econômica nunca interrompe o controle. Falha gera evento `ssto_infeasible`.
- **RF-906** **Anti-flipping:** penalização quadrática opcional sobre `‖ΔMV − ΔMV_anterior‖` (detuning, backend QP), configurável por bloco.
- **RF-907** **Âncoras nunca causam inviabilidade:** os pares de folga das preferências (`target`/`psv`/`observe_limit`/`equalize`) absorvem qualquer conflito com as restrições — o dev absorve tudo e as âncoras **não** entram no loop de desistência por rank (`given_up`); só linhas de limite de CV/Restrição participam dele. (ADR-027 §6 estendido)
- **RF-908** **Ordem de dominância dos termos** no objetivo do LP, por construção dos pesos: folga de limite (`slack_weight×priority`) ≫ `target` ≫ `maximize`/`minimize` ≫ `psv` = `equalize` ≫ `observe_limit` — um `target` vence qualquer preço; um `psv` cede a preços e só decide o grau de liberdade que sobraria solto; `observe_limit` move a CV do SP só o necessário para viabilizar as restrições. Pesos são constantes de módulo documentadas (não config) até uma planta real pedir calibração.
- **RF-909** **A camada dinâmica persegue o alvo de MV:** toda MV com `objective ≠ "none"` ganha um TVP `utarget_<mv>` e um termo quadrático suave `U_TARGET_WEIGHT·((u−utarget)/span)²` no custo (lterm, nunca mterm) — em planta "gorda" (mais MVs que CVs), o grau de liberdade extra segue o alvo econômico em vez de ficar solto. O TVP recebe o `mv_target` do `SstoRun` do ciclo; sem execução do SSTO (desligado/falha), o fallback é o `u_applied` (âncora neutra = posição atual, comportamento idêntico ao de antes). (ADR-027 §10, decisão "MVˢˢ\* não rastreado na v1" **revisada**)
- **RF-910** **Sumário do otimizador na Operação:** abaixo do faceplate principal, um card **"Otimizador"** lista as variáveis com `objective ≠ "none"` (MV→CV→Restrição) com valor **atual** (estado ao vivo) e **alvo** calculado (`mv_target`/`cv_target`), badge de status da última execução (`optimal`→"Ótimo", `relaxed`→"Relaxado", `infeasible`→"Inviável", `unbounded`→"Ilimitado", `error`→"Erro"), valor da função objetivo e aviso de desistências (`given_up`). O quadro `mpc.state` carrega o `ssto` **adiante** (o runtime publica a execução uma vez por ciclo e depois `null` — o card retém o último); o cold-start é `GET /api/history/ssto/last` (200 com `null` quando o bloco nunca executou). Estados: sem variável otimizada ⇒ card ausente; otimizada sem execução ⇒ "Aguardando primeira execução do otimizador".

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
| `opc.values.<conn_id>` | opc-worker | flow-runtime, recorder, api(WS, filtrado por assinatura de tag) | {tag_id, ts, value, quality} |
| `opc.writes` | flow-runtime, api | opc-worker | {conn_id, tag_id, value, source, ts} |
| `flow.status.<flow_id>` | flow-runtime | api(WS) | {state, scan_ms, overruns, ts, ports{block_id→{porta:{v, ok}}}} |
| `flow.commands` | api | flow-runtime | {flow_id, cmd, args, user, ts} |
| `mpc.state.<flow_id>.<block_id>` | flow-runtime | api(WS), recorder | {ts, modes, status, vars{var_id→{v, sp?, status?}}, cost, prediction{ts, t[], cv[][], mv[][]}, ssto?} |
| `fuzzy.state.<flow_id>.<block_id>` | flow-runtime | api(WS), recorder | {ts, ok, inputs[{port, name, v, terms[{term, degree}]}], rules[], outputs[{port, name, v, terms[...]}]} |
| `events` | todos | api(WS→banner), gravação | {ts, severity, origin, message, payload} |

> `ssto` (ADR-027) é **opcional** e só aparece no quadro em que a camada de alvos executou: `{run_id, config_hash, model_hash, status, solver, solve_ms, objective, mv, cv_ss, bias, dv, costs, delta_mv, mv_target, cv_target, given_up[], active_constraints[], duals}`. O recorder o materializa em `ssto_runs`. **Nenhum canal novo foi criado.** O runtime publica a execução **uma vez por ciclo** e depois `null` — o consumidor do sumário (RF-910) retém o último quadro com `ssto` (carry-forward no redutor do canal) e usa `GET /api/history/ssto/last` como cold-start.

> `vars.<var_id>.sp` só existe em CV; `vars.<var_id>.status` só existe em MV (RF-626), com valores `rcas_ok` | `local_override` | `bad_quality` | `out_of_service`. Ambos são campos opcionais (`null` quando não se aplicam) — consumidor que ignora `status` continua válido. A transição de `status` gera o evento `mpc_mv_status_changed` (`payload: {var_id, from, to}`; `warning` ao sair de `rcas_ok`, `info` ao voltar); o status **não é persistido** em `mpc_samples`. (ADR-028)

> `fuzzy.state.<flow_id>.<block_id>` (ADR-030) carrega o estado INTERNO do motor por execução — fuzzificação (`inputs[].terms[].degree` = μ do termo), grau de ativação por regra (`rules[]`, ordem de declaração do FLL com rule blocks concatenados) e defuzzificação (`outputs[].v` + grau agregado por termo) —, o que `flow.status` não expressa: lá só trafega o valor final da porta. Publicado **somente após `engine.process()` bem-sucedido** (cold start e exceção não publicam) e com **throttle de 0,25 s na origem**: a animação da tela (RF-544) não precisa de mais que ~4 Hz e o custo por varredura tem de continuar sub-ms no event loop compartilhado (ADR-029). `v: null` é o não-finito do RF-542 — `nan`/`inf` nunca entram no JSON do canal. O recorder materializa as portas em `fuzzy_samples`.

> `opc.values.<conn_id>` no `/ws` (decisão F6 A-1 **revertida**, 2026-08-11): o cliente assina por `tag_id` (`{"subscribe": {"opc_values": [<tag_id>...]}}`) e recebe o envelope `{channel: "opc.values.<conn_id>", data: {tag_id, ts, value, quality}}` só das tags assinadas; o cliente coalesce a 250 ms antes de renderizar. Alimenta o PV dos faceplates e a ponta viva do trend de operação na taxa OPC (RF-702/703).

### 7.2 JSON de projeto (export/import) (ADR-012)
```json
{"schema_version": 1, "exported_at": "2026-08-07T21:40:00Z",
 "project": {"name": "Planta C-101", "description": "Coluna debutanizadora"},
 "connections": [{"name": "gateway-1", "endpoint": "opc.tcp://10.0.0.5:4840",
   "security_policy": "basic256sha256", "security_mode": "sign_and_encrypt",
   "auth_mode": "user_password", "auth_username": "ottima"}],
 "tags": [{"connection": "gateway-1", "name": "TT-101", "node_id": "ns=2;s=TT101",
   "direction": "r", "data_type": "float", "eu": "C", "description": "Temperatura de topo"}],
 "flows": [{"name": "Coluna C-101", "ts_seconds": 1.0, "desired_state": "stopped",
   "watchdog_enabled": true, "watchdog_connection": "gateway-1",
   "watchdog_read_node_id": "ns=2;s=WD_R", "watchdog_write_node_id": "ns=2;s=WD_W",
   "watchdog_period_ms": 1500, "watchdog_timeout_s": 10,
   "graph": {"nodes": [{"id": "n1", "type": "fuzzy", "config": {
     "fll": "Engine: tsukamoto\nInputVariable: X\n...", "n_inputs": 1, "n_outputs": 4,
     "output_eu": {"OUT1": "%"}}}], "edges": []}}]}
```
Nós do `graph` que referenciam tags (blocos `opc_read`/`opc_write` e variáveis do MPC) usam o objeto `tag_ref: {"connection": "...", "tag": "..."}` em vez de id numérico interno — omitido no exemplo acima (demais nós de `graph` também omitidos, por brevidade). Sem segredos; credenciais re-informadas no import (RF-102/103).

### 7.3 API (grupos)
`/auth` · `/users` · `/projects` (+ `/activate`, `/export`, `/import`) · `/connections` (+ certificados) · `/tags` · `/flows` (+ `/deploy`, `/stop`) · `/operate` (modos, SP, MV, **`/fuzzy` e `/fuzzy/{flow_id}/{block_id}`**) · `/history` (+ `/mpc`, **`/ssto/last`**, **`/fuzzy`**) · `/events` · `/history-retention` · `/system-settings` · `/ws` (flow.status, mpc.state, **fuzzy.state**, events, **opc.values filtrado por tag**).

## 8. Fases de implementação e critérios de aceite

| Fase | Entrega | Aceite |
|---|---|---|
| **F1 — Fundação** | Compose, schema DB (+hypertables/retenção), auth/RBAC, CRUD de projetos/conexões/tags | Login admin/operador; retenção ativa; `docker compose up` sobe tudo |
| **F2 — Aquisição** | opc-worker (3 modos de segurança), barramento, recorder, watchdog | Leituras de servidor real chegam ao trend; bit de watchdog alternando; queda ⇒ alarme em <12 s e bloqueio de escrita |
| **F3 — Motor + canvas** | Editor React Flow (5 blocos), scan cycle, hot-swap, blocos Read/Write/Script/TFS | Flow Script+TFS roda a 0.5 s sem jitter >10%; edição aplica na varredura seguinte sem parar |
| **F4 — MPC** | Modal com abas, montagem do-mpc (SOPDT/IOPDT, TSS→Np/Nc), modos, bumpless, multiplicador, orçamento, **disponibilidade de MV por ciclo (RF-626..628)** | Malha fechada MPC↔TFS: assume/devolve sem salto de MV; restrição vence CV; overrun mantém MV + alarme; **MV tirada de RCAS durante a execução é congelada e volta sem salto, com as demais MVs seguindo em AUTO** |
| **F5 — Operação** | Tela de operação (faceplates + trend com predição), eventos/banner, auditoria | Operador conduz LOCAL/REMOTO/MAN/AUTO, escreve SP/MV; predição sobreposta ao histórico |
| **F6 — Portabilidade & hardening** | Export/import JSON, gestão de certificados, health/heartbeats, testes RNF-09 | Projeto exportado importa limpo em instalação nova (re-informando segredos); suíte MPC↔TFS verde |
| **F7 — Otimização econômica (SSTO)** | Camada `target_calculation` (LP/QP plugável), inviabilidade por rank + folga, auditoria `ssto_runs`, integração como referência do MPC com fallback manual, **função objetivo por variável (RF-901/907/908) com rastreio dinâmico do alvo de MV (RF-909) e sumário na Operação (RF-910)** | Alvo ótimo respeita todos os limites; inviabilidade desiste da linha de menor prioridade e registra a ordem; SSTO desligado reproduz o comportamento da F4 bit a bit; **`target` domina o preço, `psv` cede a ele, `equalize` nivela frações de escala, `observe_limit` sai do SP só o necessário; MV persegue `mv_target` (TVP `utarget_*`) com fallback na posição atual; card "Otimizador" mostra status/atual/alvo e popula no cold-start sem esperar o próximo ciclo** |

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
