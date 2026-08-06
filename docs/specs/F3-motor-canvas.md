# Spec F3 — Motor + canvas

**Fase:** F3 (PRD §8) · **Status:** aprovado seção a seção em sessão de brainstorm · 2026-08-04
**Fontes normativas:** `docs/PRD.md` v1.2 (RF/RNF, contratos §7, fases §8) · `docs/adr/ADR-001…024` (prevalecem em conflito) · `docs/GLOSSARY.md` · `PRODUCT.md`/`DESIGN.md` (frontend) · `docs/specs/F1-fundacao.md` e `docs/specs/F2-aquisicao.md` (vinculantes)
**Convenção de rastreabilidade:** cada decisão cita o RF-xxx/ADR-nnn/spec-F1/F2 que a governa; decisões sem cobertura nos documentos estão marcadas **[NOVA — implementação]** e foram aprovadas pelo usuário nesta sessão (Anexo A).

Este documento especifica **implementação**. Ele não redefine produto, arquitetura nem visual; onde repete conteúdo normativo, é citação.

---

## 1. Escopo da F3

**Entrega (PRD §8-F3):** Editor React Flow (5 blocos), scan cycle, hot-swap, blocos Read/Write/Script/TFS.
**Aceite (PRD §8-F3):** flow Script+TFS roda a 0,5 s sem jitter >10%; edição aplica na varredura seguinte sem parar.

### 1.1 Dentro da F3

| Item | Governança |
|---|---|
| flow-runtime real (substitui esqueleto F1): scheduler scan-cycle por flow, snapshot do barramento (`opc.values.*`), execução em ordem de `exec_order`, estados rodando/parado/falha, consumo de `flow.commands`, publicação de `flow.status` com valores de porta | RF-401..405 · ADR-004/006/007/024 · §2 |
| Blocos executáveis: OPC-Read, OPC-Write, Python-Script (ProcessPool), TFS (matriz 2×2 SOPDT/IOPDT) | RF-501/502/511-514/521-522 · ADR-018/022 · §3 |
| Hot-swap: banco+dica (`cmd=reload`), stage validado, troca atômica na fronteira de varredura, estado preservado por `block_id` | RF-304 · ADR-011 · §4.1 |
| Contrato F2 §3.7 honrado: runtime assina `events`; `comm_failure` ⇒ para flows que usam tags da conexão; `project_activated` ⇒ encerra execução do projeto anterior (gancho RF-101 da F1); boot parado | RF-207/101/104 · ADR-009/017 · §2.2 |
| API: `/api/flows` CRUD + `/deploy` + `/stop`; validação server-side do grafo; `desired_state` persistido, não auto-aplicado | RF-302/306/307 · PRD §7.3 · §5 |
| WS mínimo `/ws`: fanout de `flow.status.<id>` para o canvas ao vivo — eventos/faixa anunciadora continuam F5 | RF-305 · **[NOVA — implementação]** decisão #2 · §5.3 |
| Frontend: `/engenharia/flows` (lista, CRUD, deploy/parar por estado publicado) + `/engenharia/flows/:id` (canvas React Flow re-vestido, paleta 5 blocos com MPC desabilitado, modo visualização ao vivo) | RF-301..307 · DESIGN.md §Shapes · §6 |
| Emenda pontual PRD §7.1: payload de `flow.status` ganha `ports` — submetida junto com este spec (PRD v1.2) | **[NOVA — implementação]** decisão #3 · §4.2 |
| Gate E2E 3 camadas com cenários novos; medição de jitter e de hot-swap no aceite | spec F2 §11 (protocolo reusado) · §7 |

**Zero migration nova:** o DDL de `flows` está completo desde a F1 (spec F1 §3.1).
**Dependências novas:** `numpy` (flow-runtime — escopo do script, ADR-018, e matemática do TFS) · `@xyflow/react` (frontend — stack declarada, ADR-005/PRD §10).

### 1.2 Fora da F3 — com destino registrado

| Item | Destino | Governança |
|---|---|---|
| Bloco MPC: modal, montagem do-mpc, runtime, modos, `mpc.state.*` | F4 (paleta já mostra o bloco desabilitado — §6.2) | PRD §8 · ADR-008/010/013/014 |
| `/operate`, tela de operação, faceplates | F5 | PRD §8 |
| WS de eventos (faixa anunciadora com dados reais) e de valores de tag | F5 (mesma infra do §5.3) | spec F2 §1.2 |
| UI do log de eventos | F5 | RF-803 |
| Export/import, UI de certificados | F6 | PRD §8 |
| Browse do address space (era "reavaliar na F3") | Segue adiado — RF-203 o marca "desejável"; node_id manual provado desde a F2. Reavaliar na F6 | RF-203 |

> Nota (spec F5 §1.2): o registro de valores de tag é reapontado — fica F6 ou nunca, só com consumidor real; eventos (faixa anunciadora) seguem F5 (spec F5 §1.2).

---

## 2. Motor de execução (flow-runtime)

### 2.1 Mapa de módulos (referência; caminhos exatos no plano)

```
services/flow-runtime/src/ottima_flow_runtime/
  main.py          # FastAPI /health + lifespan: sobe o Supervisor (padrão opc-worker F2)
  supervisor.py    # ciclo de vida dos FlowTasks: comandos, watermark, guardas de projeto
  snapshot.py      # psubscribe opc.values.* → último {value, quality, ts} por tag_id
  scheduler.py     # FlowTask: laço de varredura com deadline absoluto
  blocks/          # base.py, opc_read.py, opc_write.py, script.py, tfs.py
  script_pool.py   # ProcessPool dedicado + protocolo de round-trip do state
  events.py        # assina `events` (comm_failure, project_activated) + emissões próprias
  state.py         # snapshot em memória p/ /health
```

**Validação de grafo compartilhada:** `ottima_core/flowgraph.py` — parse do `graph_json` → modelo tipado + regras (RF-302/307). Uma implementação, dois consumidores: API valida no save, runtime valida no stage. Mesmo padrão de `schemas`/`bus` da F1/F2. **[NOVA — implementação]**

### 2.2 Decisões

1. **Ciclo de vida:** flow só executa por comando `deploy`; boot **parado** (ADR-017); `desired_state` do banco é exibição, nunca auto-aplicado (RF-306). Deploy: lê `graph_json` do banco → valida → instancia blocos → task asyncio. Flow de projeto inativo ⇒ deploy rejeitado (evento warning). **[NOVA — implementação]** (forma)
2. **Scheduler com deadline absoluto:** âncora `t0` no deploy; varredura n dispara em `t0 + n×Ts` (sem deriva acumulada). Varredura que estoura Ts ⇒ **pula as fronteiras perdidas** (nunca acumula fila — mesma filosofia do RF-624), incrementa `overruns`, evento warning `flow_overrun` na 1ª ocorrência por período (dedupe). Jitter = desvio do disparo real vs fronteira teórica (RNF-02). **[NOVA — implementação]** (política de skip)
3. **Varredura:** blocos em ordem crescente de `exec_order` (ADR-024, RF-401). A tabela de valores de porta **persiste entre varreduras**: bloco lê o valor corrente das entradas ao executar — aresta em ordem normal enxerga o valor desta varredura; aresta invertida enxerga o da anterior (atraso de 1 scan determinístico). A semântica do RF-401 cai naturalmente da implementação.
4. **Executor:** Script via ProcessPool (§3.3, decisão #4). **TFS executa inline** no loop — aritmética de estado-espaço 2×2 é O(µs), não é CPU-bound; pagar IPC nela seria ruído de jitter. MPC (F4) usará executor próprio (ADR-004). **[NOVA — implementação]**
5. **Publicação:** `flow.status.<id>` a cada varredura `{state, scan_ms, overruns, ts, ports}` (payload §4.2) + publicação imediata em transição de estado (deploy/stop/falha). **`ts` = instante de disparo da varredura** (fronteira real), não o fim — é a referência da medição de jitter. **[NOVA — implementação]**
6. **Estados e falha:** `stopped → running → stopped|failed`. Exceção/timeout de **script** não derruba o flow (RF-514: mantém saídas + alarme). Exceção **não tratada** do laço ⇒ `failed` + evento alarm `flow_failed` + task encerra; falha de um flow não afeta os demais (RF-402, task isolada). Retomada só por deploy manual.
7. **Comandos (`flow.commands`):** `deploy`, `stop`, `reload` (dica de hot-swap). Idempotentes (RNF-05): deploy em rodando = no-op; stop em parado = no-op; `flow_id` desconhecido = log e ignora. Eventos edge-triggered emitidos pelo **runtime** ao materializar o efeito (`flow_deployed`, `flow_stopped`, `flow_failed`; `origin` = `flow:<id>` exato — o `user` do comando vai no **payload**, e evento sem usuário comandante **omite** a chave `user`; emenda 2026-08-04) — a API não duplica auditoria: comando perdido = nada aconteceu = nenhum evento. **[NOVA — implementação]** (divisão de auditoria)
8. **Contrato F2 §3.7:** assina `events`; `kind=comm_failure` ⇒ para (estado `failed`, `reason=comm_failure`) todo flow rodando cujo grafo referencia tag da conexão caída (conjunto de `conn_id`s resolvido no stage). `kind=project_activated` ⇒ para **todos** os flows rodando (pertencem ao projeto anterior) — cumpre o gancho RF-101 registrado na F1 (spec F1 §6.2).
9. **Watermark backstop (10 s, padrão spec F2 §2.2-1):** pega dica perdida (`updated_at` de flow rodando mudou ⇒ stage), flow deletado ⇒ stop, projeto desativado ⇒ stop. Perda de mensagem nunca produz estado errado, só atraso ≤10 s (RNF-05). **[NOVA — implementação]**
10. **`/health` (RNF-07):** `{status, service, version, flows:{<id>:{state, scan_ms, overruns, last_scan_ts}}}`; `status` reflete só dependências do serviço (Redis/banco), como na F2 §2.2-8 — flow em falha é condição operacional (alarme), não unhealth do serviço.

---

## 3. Os quatro blocos executáveis

### 3.0 Regras de base (todos os blocos)

- **Identidade** = id do nó React Flow (`block_id`, string): chave de preservação de estado no hot-swap (ADR-011); `exec_order` vive em `config` e não participa da identidade (ADR-024).
- **Invalidez** (decisão #6): metadado por porta. Entrada com valor conhecido porém flag inválida ⇒ bloco **executa com o valor** e propaga a flag às saídas (determinismo preservado; TFS continua integrando, script roda). O script não enxerga a flag — o contrato IN/OUT do ADR-018 é fechado.
- **Cold start** **[NOVA — implementação]**: entrada `null` (nunca recebeu valor desde o deploy) ⇒ bloco **não executa** nessa varredura e saídas ficam `null`/inválidas — não se inventa 0.0 para dentro de uma malha.
- Tipagem conforme decisão #5: estrita, exceto portas de Script (bivalentes).

### 3.1 OPC-Read (RF-501)

| Aspecto | Definição |
|---|---|
| Config | `tag_id` (obrigatória, direção `r`, do projeto do flow) |
| Portas | 1 saída; tipo = numérico (`float`/`int`) ou booleano (`bool`), herdado da tag |
| Semântica | lê o snapshot do barramento (último `{value, quality, ts}` da tag); **inválida ⇔ `quality ≠ 0`** ou sem valor. **[NOVA — implementação]**: uncertain também invalida — conservador, fail-safe |

### 3.2 OPC-Write (RF-502)

| Aspecto | Definição |
|---|---|
| Config | `tag_id` (direção `w`); tipo da entrada casa **exatamente** com a tag (decisão #5) |
| Portas | 1 entrada, 0 saídas |
| Semântica | a cada varredura publica `OpcWrite{conn_id, tag_id, value, source:"flow:<fid>/block:<bid>", ts}` — coerção de Variant é do worker (spec F2 §4.3, bool→`value≠0`) |
| Supressão | entrada inválida ou `null` ⇒ **não publica** + warning `write_suppressed` deduplicado por bloco por período **[NOVA — implementação]** (decisão #6). Conexão em falha: coberta por RF-207 (flow para) + gate do worker (spec F2 §3.4) — defesa em profundidade, sem lógica duplicada |

### 3.3 Python-Script (RF-511..514 · ADR-018 · decisão #4)

- **Config:** `n_inputs`/`n_outputs` (0..8 cada — teto **[NOVA — implementação]**), `code`.
- **Portas:** IN1..INn bivalentes (bool entra como 0.0/1.0 — decisão #5), OUT1..OUTn numéricas (ligar OUT em porta booleana converte ≠0 → true).
- **Escopo do `exec()`:** `IN1..INn`, `state`, `math`, `numpy` (+ alias `np` **[NOVA]**), builtins de **lista fechada definida em código** (`abs`, `min`, `max`, `round`, `len`, `range`, `float`, `int`, `bool` — a lista exata é constante do runtime, exaustiva no plano); `__import__` fora — honra "apenas math e numpy" (ADR-018) sem sandboxing pesado (modelo de ameaça = admin autenticado).
- **Execução:** ProcessPool dedicado do runtime (decisão #4); timeout `0.7×Ts` (RF-514); cópia-mestre do `state` no runtime, atualizada **só em retorno OK** — timeout/exceção nunca corrompe estado. Custo de IPC (~0,1-1 ms/chamada) folgado no orçamento de 350 ms a Ts=0,5 s.
- **Falhas (RF-514):** timeout ⇒ mata o worker + re-spawn + mantém últimas saídas + alarm `script_timeout`; exceção ⇒ mantém últimas saídas + alarm `script_error` (traceback no payload). **OUTx não atribuído = erro de script** **[NOVA — determinismo]**. Antes do 1º sucesso, saídas são `null` (§3.0). Eventos deduplicados por bloco por período de falha (padrão F2).
- **`state`:** zera ao parar (RF-512); sobrevive hot-swap se o bloco não mudou (ADR-011); valor não-picklável ⇒ `script_error`. Dimensão do pool = constante de código (não knob de env — padrão spec F2 §10.1).

### 3.4 TFS (RF-521/522 · ADR-022)

- **Config:** matriz 2×2; elemento `{enabled, kind: sopdt|iopdt, params}` — SOPDT `{K, tau1, tau2, theta}`, IOPDT `{Ki, theta}`.
- **Portas** **[NOVA — implementação]**: fixas `u1,u2 → y1,y2` (numéricas); entrada `uK` é obrigatória ⇔ há elemento habilitado na coluna K; linha toda desabilitada ⇒ `yJ = 0.0` (ganho zero, ADR-022).
- **Discretização (ZOH no Ts do flow, RF-522):** SOPDT = dois estágios de 1ª ordem exatos em série (`a = e^(−Ts/τ)`), ganho K no final; `τ < Ts/10` degrada o estágio para passagem direta **[NOVA — robustez numérica]**. IOPDT: `acc += Ki·Ts·u`. **Tempo morto** por fila de atraso na entrada do elemento, `d = round(θ/Ts)` amostras; validação rejeita `d > 7200` **[NOVA — teto de buffer]**.
- **Estado por elemento** (`x1`, `x2`/`acc`, fila de atraso): zera no deploy/stop; preservado entre varreduras e no hot-swap se o bloco não mudou (ADR-011). `yJ = Σ` contribuições habilitadas da linha.
- Execução **inline** no loop (§2.2-4).

---

## 4. Hot-swap e barramento/eventos

### 4.1 Hot-swap (RF-304 · ADR-011 · decisão #7)

1. **Gatilho:** `PUT /api/flows/{id}` grava `graph_json` validado; flow rodando ⇒ API publica `flow.commands {cmd:"reload"}`. Runtime relê do **banco** (fonte única da verdade), valida, monta definição *staged*; dica perdida ⇒ watermark ≤10 s (§2.2-9).
2. **Aplicação atômica** na fronteira da próxima varredura — nunca no meio de uma (ADR-011). Flow parado: save é só persistência; deploy futuro lê o vigente.
3. **Preservação de estado por `block_id`** — critério de "bloco não alterado" **[NOVA — implementação]**: compara tipo + **config funcional** (Script: `code`+`n_inputs`+`n_outputs` · TFS: matriz · Read/Write: `tag_id`). `exec_order`, posição no canvas e rótulo **mudam sem resetar estado** (ADR-024: fora da identidade). Alterado ⇒ re-instancia zerado; removido ⇒ descarta; novo ⇒ nasce `null`.
4. **Mudança de `ts_seconds`** em flow rodando **[NOVA — implementação]**: a timebase inteira muda (discretização TFS, timeout de script, fronteiras) ⇒ **todos** os blocos re-instanciam + scheduler re-ancora. Semântica limpa; caso raro na prática.
5. **Staged inválido** (corrida/bug — a API já valida no save): mantém a definição vigente + warning `reload_rejected` **[NOVA — implementação]**. Hot-swap nunca derruba um flow rodando.

### 4.2 Payload `flow.status` estendido (emenda PRD §7.1 — decisão #3; PRD v1.2)

```json
{"state": "running", "scan_ms": 3.2, "overruns": 0, "ts": "…",
 "ports": {"<block_id>": {"out": {"v": 42.5, "ok": true},
                          "in":  {"v": null, "ok": false}}}}
```

`ports` presente em toda publicação de varredura; `v` numérico/bool/`null`, `ok` = flag de invalidez (decisão #6) — o canvas desenha inválido dessaturado + rótulo (DESIGN.md, Regra do Canal Redundante). `flow.commands` permanece verbatim (`{flow_id, cmd, args, user, ts}`); cmds da F3: `deploy` · `stop` · `reload`. Nenhum canal novo (disciplina F2).

### 4.3 Vocabulário `kind` novo (extensão da tabela spec F2 §7.3; match sempre por `kind`, mensagens pt-BR) **[NOVA — implementação]**

| `kind` | severity | origem | quando |
|---|---|---|---|
| `flow_deployed` / `flow_stopped` | info | flow-runtime | efeito materializado; `flow_stopped` leva `reason: user\|project_activated\|flow_deleted\|shutdown` (emenda 2026-08-04) |
| `flow_failed` | alarm | flow-runtime | exceção não tratada ou `reason: comm_failure` (RF-207) |
| `flow_overrun` | warning | flow-runtime | 1ª ocorrência por período (dedupe) |
| `script_timeout` / `script_error` | alarm | flow-runtime, `origin=flow:<fid>/block:<bid>` | RF-514 |
| `write_suppressed` | warning | flow-runtime | §3.2 (dedupe) |
| `reload_rejected` | warning | flow-runtime | §4.1-5 |
| `deploy_rejected` | warning | flow-runtime | §2.2-1 — deploy rejeitado (projeto inativo, grafo inválido); `reload_rejected` fica reservado ao staged inválido do hot-swap (emenda 2026-08-04) |
| `flow_created` / `flow_updated` / `flow_deleted` | info | api | auditoria CRUD + dica de reconcile (padrão spec F2 §7.2) |

---

## 5. API `/api/flows`, validação de grafo e WS

### 5.1 Rotas (padrões spec F1 §6.1: `/api`, erros pt-BR, sem paginação)

| Rota | Papel | Regras |
|---|---|---|
| `GET /api/flows?project_id=` | operator | lista leve (id, nome, ts, `desired_state`, `updated_at`) — sem `graph_json` |
| `GET /api/flows/{id}` | operator | completo, com `graph_json` |
| `POST /api/flows` | admin | nome único por projeto (DDL F1); `graph_json` default vazio |
| `PUT /api/flows/{id}` | admin | valida §5.2 antes de gravar; flow rodando ⇒ publica `reload` (§4.1) |
| `DELETE /api/flows/{id}` | admin | flow rodando ⇒ **409** "pare antes de excluir" **[NOVA — implementação]** (espelha DELETE de projeto ativo, spec F1 §6.2) |
| `POST /api/flows/{id}/deploy` · `/stop` | admin (PRD §2) | seta `desired_state` (RF-306) + publica `flow.commands`; response **202** — comando é intenção, a UI confirma pelo estado publicado (DESIGN.md, Regra do Estado Publicado) |

Auditoria: `flow_created/updated/deleted` pela API (§4.3); `flow_deployed/stopped/failed` pelo runtime ao materializar (§2.2-7). Sem teto duro de flows (~10 é dimensionamento RNF-01, não limite de CRUD — diferente do ≤5 de conexões, que é RF-201).

### 5.2 Validação de grafo (`ottima_core/flowgraph.py` — compartilhada, §2.1)

Reprovações (**422** pt-BR):
- estrutura: `nodes[]`/`edges[]` React Flow; tipos ∈ {`opc_read`, `opc_write`, `script`, `tfs`} — **node `mpc` ⇒ 422 na F3** (decisão #1; a F4 libera);
- portas: compatibilidade de tipos (decisão #5); handles existentes;
- **ciclos** (RF-302; topologia rebaixada a validação — ADR-024);
- **entradas obrigatórias soltas** (RF-302): `in` do Write, IN1..INn do Script, `uK` do TFS conforme §3.4;
- **`exec_order`**: presente em todo nó, único, contíguo 1..N (RF-307, ADR-024);
- integridade referencial **[NOVA — implementação]**: `tag_id` existe, direção correta, tag pertence ao projeto do flow (`graph_json` não tem FK — a validação é a barreira);
- configs por tipo com os tetos da §3.

**Aviso de inversão** (RF-307, não-bloqueante): save responde `200 {flow, warnings[]}` — aresta A→B com `exec_order(B) < exec_order(A)` gera warning textual; o editor também calcula localmente para feedback imediato. **[NOVA — implementação]** (forma)

### 5.3 WebSocket `/ws` (RF-305 · decisão #2)

- Upgrade em `GET /ws` (URL literal, sem barra final). **Emenda 2026-08-04:** a afirmação original ("o nginx da F1 já proxeia com headers prontos") era falsa — o `location /ws/` da F1 não casava `GET /ws`; o proxy do nginx foi corrigido na F3 (`7298aa8`).
- **Auth:** `?token=` na URL de conexão, papel operator. **[NOVA — implementação]** (forma; risco aceito coerente com HTTP interno, ADR-023)
- **Protocolo** **[NOVA — implementação]**: cliente envia `{"subscribe": {"flow_status": [<flow_id>…]}}` / `unsubscribe` análogo; servidor responde fanout `{"channel": "flow.status.<id>", "data": {…}}`. A API mantém **uma** assinatura Redis compartilhada (psubscribe) e roteia para os clientes — não uma por socket.
- Escopo F3: somente `flow_status` (canvas ao vivo). Eventos/valores de tag → F5 na mesma infra. Sem replay (RNF-05: fire-and-forget; UI orientada a estado publicado).

---

## 6. Frontend: lista de flows e editor canvas (autoridade: PRODUCT.md/DESIGN.md)

### 6.1 `/engenharia/flows` — lista (padrões spec F2 §9.1)

- Tabela em chapa: nome, Ts, estado desejado (banco) e **"Último estado"** derivado de `GET /api/events` (último `flow_deployed/stopped/failed` por `origin=flow:<id>`, polling 5 s — padrão aprovado para conexões na F2; estado vivo contínuo é do editor via WS).
- **Escopo pelo projeto ativo no cliente** — herda a decisão do usuário de 2026-08-04 (F2): lista e criação operam no projeto ativo.
- Criar (nome, Ts da lista fixa ADR-007), excluir (409 se rodando), **Deploy/Parar** com estado *comandado* pendente até o estado *publicado* confirmar (Regra do Estado Publicado — visual).
- RBAC: operador vê tudo; mutações e deploy/parar só admin (`useCanMutate`, padrão F2 §9.1).
- Navegação do shell: link **"Flows"** em plaqueta — ordem Conexões · Tags · Flows · Trend. Strings 100% pt-BR (RNF-08), termos do GLOSSARY, sem emojis.

### 6.2 `/engenharia/flows/:id` — editor (RF-301..307)

- **React Flow re-vestido** (DESIGN.md §Shapes: nó = equipamento de painel — chapa, plaqueta de título, portas rotuladas, bisel 2-4 px; visual default proibido). Única dependência npm nova: `@xyflow/react`.
- **Paleta:** 5 blocos (RF-301); MPC presente, desabilitado, badge "F4" (decisão #1). Inserção auto-numera `exec_order` (próximo livre — ADR-024).
- **`exec_order`:** badge visível no nó; edição manual no modal de config; compactação automática ao excluir; **aviso de inversão não-bloqueante** no editor + `warnings[]` do save (§5.2) (ADR-024).
- **Validação de conexão no arraste** (RF-302): tipos (decisão #5), ciclo, e **no máx. 1 aresta por porta de entrada** **[NOVA — implementação]** (regra FBD padrão). Espelho leve client-side para feedback imediato; a fonte da verdade é a validação do servidor (§5.2).
- **Config por duplo-clique** (RF-301), modal por tipo:
  - Read/Write: seletor de tag filtrado por direção e projeto ativo (reusa `useTags` da F2);
  - Script: `n_inputs`/`n_outputs` (0..8) + código em `<textarea>` mono com tratamento de Tab — **sem editor de código de terceiros na v1** **[NOVA — implementação]** (zero dependência extra);
  - TFS: matriz 2×2, habilitação + params por elemento, validações §3.4.
- **Modo visualização ao vivo (RF-305):** com o flow rodando, o editor assina `flow_status` do flow aberto via WS e mostra: valores nas portas (mono tabular — Regra do Número Tabular; inválido dessaturado + rótulo — Regra do Canal Redundante), lâmpada de estado, `scan_ms`/`overruns` no cabeçalho da chapa. Admin **e** operador; para operador o canvas é somente-leitura (sem paleta, sem arraste, sem save — PRD §2).
- **Editar rodando é o caminho feliz** (ADR-011): salvar aplica na varredura seguinte; o canvas segue vivo durante o swap.

Estrutura: `frontend/src/features/flows/` (FlowsPage, FlowEditorPage, `nodes/` custom por tipo, `useFlows`, `useFlowStatus` WS hook).

---

## 7. Testes e gate E2E

### 7.1 Unit/integração (padrões spec F1 §9 · spec F2 §11.1)

- **`ottima_core.flowgraph`:** mesa pura de validação — tipos, ciclos, `exec_order` (unicidade/contiguidade), entradas soltas, integridade de tag, tetos de config, node `mpc` rejeitado.
- **flow-runtime:** scheduler com clock controlado (fronteiras absolutas, skip de overrun, re-âncora em mudança de Ts) · semântica `exec_order` (aresta normal = mesma varredura; invertida = anterior) · blocos: Read (quality→invalidez), Write (supressão + `source`), **Script com ProcessPool real** (timeout mata worker, exceção, state round-trip, OUT ausente, não-picklável), **TFS vs solução analítica** (degrau SOPDT/IOPDT, tempo morto, τ≈0) · hot-swap (preserva por `block_id`; config muda ⇒ re-instancia; Ts muda ⇒ tudo) · comandos idempotentes · `comm_failure` para os flows certos · `project_activated` para tudo · watermark backstop.
- **api:** CRUD flows, 422s da validação, deploy/stop 202 + comando publicado, DELETE 409, WS (subscribe/fanout/auth).
- **frontend `test:unit`:** espelho client-side (tipos/ciclo/inversão), checks puros — padrão F2.

### 7.2 Gate E2E — 3 camadas (protocolo spec F2 §11.2; desde `down -v` + override opcsim)

**L1** — `deploy/smoke.sh` estendido: `flow-runtime /health` ok, zero flows no boot.

**L2** (`pytest -m e2e`):

| ID | Cenário | Cobre |
|---|---|---|
| E2E-F3-01 | CRUD + validações 422 (ciclo, `exec_order` duplicado, tag inexistente) | RF-302/307 |
| E2E-F3-02 | Deploy Read→Script→Write ⇒ espelho R do opcsim muda; `flow_deployed`; status `running` | RF-401/501/502 |
| E2E-F3-03 | **ACEITE jitter:** Script+TFS a Ts=0,5 s, ≥120 s de coleta ⇒ p95 do desvio de fronteira < 50 ms, zero overruns | PRD §8-F3 · RNF-02 |
| E2E-F3-04 | **ACEITE hot-swap:** PUT em flow rodando ⇒ efeito ≤2×Ts, sem stop/deploy no meio, estado TFS contínuo | RF-304 · ADR-011 |
| E2E-F3-05 | `exec_order` invertido ⇒ atraso determinístico de 1 varredura no valor escrito + `warnings[]` no save | RF-401 · ADR-024 |
| E2E-F3-06 | Script busy-loop ⇒ `script_timeout`, saídas mantidas, flow segue; exceção ⇒ `script_error` c/ traceback | RF-514 |
| E2E-F3-07 | **RF-207:** congelar watchdog ⇒ flow da conexão `failed(comm_failure)`; flow Script+TFS puro segue; descongelar ⇒ **não** volta sozinho; deploy manual retoma | RF-207 · ADR-009/017 |
| E2E-F3-08 | `project_activated` para tudo; restart do runtime ⇒ tudo `stopped` apesar de `desired_state=running` (boot parado) | RF-101/104 |
| E2E-F3-09 | WS: subscribe ⇒ `flow.status` com `ports`; token inválido rejeitado | RF-305 |
| E2E-F3-10 | Script em erro desde a 1ª varredura ⇒ saídas `null` ⇒ `write_suppressed`, espelho não muda | §3.0/§3.2 |

**L3** — roteiro browser-tool do controlador (screenshot por passo, regra fixada na F2):

| ID | Passo |
|---|---|
| B-F3-01 | Login admin → link Flows |
| B-F3-02 | Criar flow (Ts 0,5 s) → na lista |
| B-F3-03 | Editor: arrastar 4 blocos; MPC desabilitado badge F4; conexão incompatível recusada; badges `exec_order` |
| B-F3-04 | Configurar via modais; salvar; warning de inversão quando aplicável |
| B-F3-05 | Deploy → pendente → rodando (estado publicado); valores ao vivo mudando nas portas |
| B-F3-06 | Editar script rodando → salvar → efeito no canvas sem parada (hot-swap observado) |
| B-F3-07 | Congelar watchdog → flow em falha; restaurar → segue parado; re-deploy manual |
| B-F3-08 | Operador: canvas somente-leitura, sem paleta/save/deploy |

**Regressão:** suíte F1+F2 completa (pytest, ruff, L1/L2 existentes, Playwright F1, `test:unit`) verde na mesma rodada.
**Regra do plano (herdada da F2, normativa):** toda tarefa que entrega UI ou comportamento fim-a-fim termina com validação browser — não só no gate final.
**Passa:** L1+L2 verdes na mesma rodada partindo de `down -v` + roteiro L3 completo com evidências.

---

## 8. Aderência ao aceite F3 (PRD §8)

| Critério | Evidência no spec |
|---|---|
| **Flow Script+TFS a 0,5 s sem jitter >10%** | §2.2-2 (scheduler deadline absoluto); **E2E-F3-03** (p95 medido) |
| **Edição aplica na varredura seguinte sem parar** | §4.1; **E2E-F3-04** + B-F3-06 |
| Entrega: editor React Flow (5 blocos) | §6.2; B-F3-03 |
| Entrega: scan cycle | §2; E2E-F3-02/05 |
| Entrega: hot-swap | §4.1; E2E-F3-04 |
| Entrega: blocos Read/Write/Script/TFS | §3; E2E-F3-02/06/10 |

---

## Anexo A — Decisões do brainstorm (2026-08-04)

| # | Lacuna | Decisão aprovada |
|---|---|---|
| 1 | Bloco MPC na paleta da F3 (RF-301 diz 5 blocos; runtime MPC é F4) | Presente e **desabilitado** (badge "F4", não arrastável); grafo com node `mpc` ⇒ 422 na F3 |
| 2 | Canvas ao vivo (RF-305 exige WebSocket; spec F2 §1.2 registrava /ws → F5) | **WS mínimo na F3**: fanout só de `flow.status.*`; eventos/faixa anunciadora continuam F5 |
| 3 | Valores de porta sem canal no PRD §7.1 (lacuna do RF-404) | **Estender payload de `flow.status`** com `ports`; emenda pontual do PRD §7.1 (v1.2) submetida com este spec; nenhum canal novo |
| 4 | Executor do bloco Script (ADR-018 não fixa qual) | **ProcessPool dedicado**: timeout real (kill+respawn), state round-trip picklado, cópia-mestre no runtime atualizada só em sucesso — jitter protegido por construção |
| 5 | Regras de compatibilidade da tipagem de portas (RF-302) | **Script bivalente, resto estrito**: IN aceita ambos (bool→0/1), OUT numérica (→bool converte ≠0); TFS só numérico; OPC-Write casamento exato com a tag |
| 6 | Semântica de invalidez a jusante (RF-501 não diz o que blocos fazem) | **Propaga + suprime escrita**: bloco executa normalmente e propaga flag; OPC-Write com entrada inválida não publica + `write_suppressed` deduplicado |
| 7 | Transporte do hot-swap (RF-304 "próxima varredura" × pub/sub fire-and-forget) | **Banco + dica** (padrão F2): PUT grava, publica `cmd=reload`; runtime relê do banco; watermark 10 s como backstop |
| 8 | Baseline da branch F3 (implementação F2 só em `f2-aquisicao`) | **Merge `f2-aquisicao` → `main` antes**; docs v1.1 + spec F3 commitados na main; worktree `ottimaSystemV3-f3` criada da main |
