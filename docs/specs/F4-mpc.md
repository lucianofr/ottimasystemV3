# Spec F4 — Bloco MPC (config, montagem, runtime e modos)

**Fase:** F4 (PRD §8) · **Status:** aprovado em blocos em sessão de brainstorm · 2026-08-04
**Fontes normativas:** `docs/PRD.md` v1.2 (RF/RNF, contratos §7, fases §8) · `docs/adr/ADR-001…024` (prevalecem em conflito) · `docs/GLOSSARY.md` · `PRODUCT.md`/`DESIGN.md` (frontend) · specs F1/F2/F3 (vinculantes; F3 com emendas de 2026-08-04)
**Execução:** 1 spec (esta) + 2 planos — F4a (config & montagem) e F4b (runtime & modos), conforme CLAUDE.md §Workflow.

Convenções herdadas: itens **[NOVA — implementação]** são decisões de implementação desta spec, sem lastro literal em RF/ADR; o Anexo A registra as decisões do brainstorm; testes citam itens numerados (ex.: §4.2-3).

---

## 1. Escopo da F4

**Entrega (PRD §8-F4):** modal com abas, montagem do-mpc (SOPDT/IOPDT, TSS→Np/Nc), modos, bumpless, multiplicador, orçamento.
**Aceite (PRD §8-F4):** malha fechada MPC↔TFS: assume/devolve sem salto de MV; restrição vence CV; overrun mantém MV + alarme.

### 1.1 Dentro da F4

| Item | Governança |
|---|---|
| Bloco MPC no editor: config no `graph_json`, portas dinâmicas, validação 422 | RF-301/302, RF-601..608, ADR-008/013/019 |
| Modal de configuração com 7 abas | RF-607, ADR-008 |
| Montagem do-mpc: discretização SOPDT/IOPDT, tempo morto por aumento de estados, TSS→Np/Nc | RF-603/608, ADR-013/014 |
| Runtime: processo dedicado por bloco, multiplicador, orçamento 70%, overrun | RF-606/624, ADR-004/014, decisão A-3 |
| Modos LOCAL/REMOTO e MAN/AUTO, bumpless, tracking, shed | RF-621..623, ADR-010, decisão A-4 |
| Publicação `mpc.state.<flow>.<block>` a cada execução | RF-625, ADR-016 |
| REST `/api/operate` mínimo (modo, SP, MV) | PRD §7.3, decisão A-2 |
| Fanout de `mpc.state` no `/ws` | decisão A-6 |
| Fechamento de **todos** os débitos herdados de F1–F3 (§8) | decisão A-5 |
| Teste de carga: solve 2×2, Np≤60 dentro de 70% do Ts_mpc no hardware de referência | RNF-02, PRD §9-1 |

### 1.2 Fora da F4 — com destino registrado

| Item | Destino | Governança |
|---|---|---|
| Tela de operação, faceplates, trend com predição | F5 | PRD §8, ADR-016 |
| WS de eventos e de valores de tag | F5 | spec F3 §1.2 |
| Suíte completa de malha fechada RNF-09 (a F4 entrega os cenários-núcleo §9.2) | F6 | PRD §8 |
| Export/import (o config MPC já viaja no `graph_json` sem segredos — tags são ids) | F6 | RF-102/103 |
| Ideal resting values de MVs excedentes | fora da v1 | ADR-019 |
| Estimador MHE (realimentação é bias DMC — §3.3) | fora da v1 | decisão A-7 |
| **Shed automático por overrun/falha de solver** — RF-624 manda manter MV + alarme; devolver é decisão do operador | fora da v1 | decisão A-12 |
| DV com trajetória futura (na F4, DV futura = último valor medido, constante no horizonte) | fora da v1 | §3.2 |

---

## 2. Bloco MPC — config e validação

### 2.1 Config no `graph_json` (decisão A-8/A-9)

O config vive inteiro no nó React Flow, como Script/TFS (export/import e hot-swap pelas vias existentes). Esqueleto normativo:

```json
{"name": "MPC da coluna", "multiplier": 5,
 "variables": {
   "mvs":  [{"id": "mv_x7k2", "name": "Vazão de refluxo", "eu": "m3/h",
             "limits": {"min": 0.0, "max": 100.0}, "du_max": 5.0,
             "initial_value": 0.0,
             "pid": {"write_tag_id": 12, "target_mode": "rcas",
                     "mode_cmd_tag_id": 13, "mode_read_tag_id": 14,
                     "readback_tag_id": 15,
                     "mode_values": {"auto": 1, "target": 3}}}],
   "cvs":  [{"id": "cv_a1b2", "name": "Temperatura de topo", "eu": "C",
             "kind": "selfreg", "tss": 600.0, "weight": 1.0,
             "sp_limits": {"min": 80.0, "max": 120.0}}],
   "constraints": [{"id": "co_c3d4", "name": "Nível do vaso", "eu": "%",
                    "kind": "integrating", "tss": 900.0,
                    "range": {"low": 20.0, "high": 80.0}, "priority": 1}],
   "dvs":  [{"id": "dv_e5f6", "name": "Vazão de carga", "eu": "m3/h"}]},
 "models": {"<linha_id>": {"<coluna_id>": {"enabled": true,
             "params": {"K": 1.2, "tau1": 120.0, "tau2": 30.0, "theta": 15.0}}}}}
```

1. **Ids estáveis** (`mv_`/`cv_`/`co_`/`dv_` + sufixo aleatório curto): gerados na criação da variável, imutáveis; são o handle da porta e a chave de estado — renomear variável não quebra aresta nem estado (decisão A-9).
2. **Matriz `models`:** linhas = CVs + Restrições, colunas = MVs + DVs (RF-602). `kind` da **linha** define a forma dos `params` de todos os pares da linha: `selfreg` → SOPDT `{K, tau1, tau2, theta}`; `integrating` → IOPDT `{Ki, theta}` (ADR-013).
3. **`pid` é opcional por MV** (decisão A-8). Presente ⇒ `write_tag_id`, `target_mode` (`rcas|cas|rout`), `mode_cmd_tag_id`, `readback_tag_id` e `mode_values` obrigatórios; `mode_read_tag_id` opcional (habilita confirmação de armar e shed — §4.4). Ausente ⇒ MV "direta" (malha simulada com TFS ou escrita externa ao bloco): nenhum `opc.writes`, LOCAL segura `initial_value` (default 0.0) até haver histórico. Misto permitido no mesmo bloco.
4. **`mode_values`:** valores numéricos escritos/lidos na tag de modo do PID (`auto` = devolver; `target` = assumir). Específicos do PLC — nunca inferidos.
5. **Portas do nó** (decisão A-10): entradas = uma por CV, Restrição e DV; saídas = uma por MV; todas numéricas. Entradas **obrigatórias** (validação de soltas — inclusive DV: declarou distúrbio, liga ou remove a variável). Saídas MV podem ficar desconectadas (malha real usa as tags do `pid`). A CV medida entra **pela porta** — condicionamento por Script a montante é suportado; é por essas portas que o TFS fecha malha sem PLC (ADR-022).

### 2.2 Validação (extensão de `ottima_core/flowgraph.py` — mesa pura; reprovações **422** pt-BR, string única)

1. Estrutura: `mpc` sai da lista de tipos rejeitados (spec F3 §5.2 previa: "a F4 libera"); config conforme §2.1.
2. ≥1 MV e ≥1 (CV ou Restrição) (RF-601). Tetos **[NOVA — implementação]**: MVs 1..4 · CVs+Restrições 1..6 · DVs 0..4.
3. Matriz: cada linha com ≥1 par habilitado **cuja coluna é MV** (CV movida só por DV é incontrolável); cada MV com ≥1 par habilitado; cada DV com ≥1 par habilitado (distúrbio declarado sem modelo não tem efeito — remova a variável); par habilitado exige `params` completos e válidos (K≠0, τ1>0, τ2≥0, θ≥0; Ki≠0, θ≥0).
4. Números: TSS>0 · `min<max` · `low<high` · `sp_limits.min<max` · `du_max>0` · `weight>0` · `priority` inteiro ≥1 · `multiplier` inteiro ≥1.
5. Horizontes (função pura compartilhada em `ottima-core`, usada pela API e pela aba Horizontes): `Ts_mpc = multiplier × Ts_flow`; `Np = ceil(max(TSS)/Ts_mpc)`; `Nc = max(2, ceil(Np/4))` (RF-603). **Np < 2 ⇒ 422** ("multiplicador grande demais para o TSS"); **Np > 120 ⇒ 422** ("aumente o multiplicador ou reduza o TSS") **[NOVA — implementação]**.
6. Integridade de tags do `pid`: existem, direção correta (`write`/`mode_cmd` = W; `readback`/`mode_read` = R), pertencem ao projeto do flow (mesma barreira da F3 §5.2).
7. **Warnings não-bloqueantes** (mesmo canal do aviso de inversão, F3 §5.2): `Np > 60` (referência de carga RNF-02) e **dimensão de estados > 120** (RF-608 pede alerta, não bloqueio). Dimensão = Σ por par habilitado (2 se SOPDT, 1 se IOPDT) + Σ `round(θ/Ts_mpc)` + n_MVs (estado aumentado `u_prev`, §3.5) — o bias é `_tvp`, não acrescenta estado.
8. As tags do config do MPC entram em `_conn_ids` — `comm_failure` da conexão derruba o flow do MPC como derruba o de um OPC-Read (RNF-03; spec F3 §2.2-8).

---

## 3. Montagem do-mpc (dentro do `MpcWorker`; TDD estrito)

1. **Discretização por par no Ts_mpc** (ZOH): SOPDT → 2 estados (forma canônica); IOPDT → 1 estado; tempo morto → `round(θ/Ts_mpc)` estados de atraso (shift register). **Convenção de arredondamento idêntica à do TFS** (`round` do Python = banker's), com nota normativa nos dois códigos (fecha débito m2, §8): simulação e modelo interno devem concordar no mesmo θ.
2. **Modelo agregado LTI discreto** bloco-diagonal: `x⁺ = A x + B u + B_d d`; `y = C x + bias`. No do-mpc (≥5.1): `Model('discrete')`; **DVs e bias como `_tvp`**, constantes no horizonte (`set_tvp_fun`). DV futura = último valor medido (§1.2).
3. **Realimentação por bias (DMC; decisão A-7):** o worker propaga o modelo em malha aberta com o `u` efetivamente aplicado (readback em malha real; plano/manual em malha direta); a cada execução, `bias = y_medido − C·x` entra constante no horizonte. Sem estimador de estados.
4. **Objetivo e precedência (ADR-019, RF-605):** variáveis normalizadas por span (CV: `sp_limits`; Restrição: `range`; MV: `limits`) para pesos comparáveis entre EUs. Custo = `Σ w_cv·(ŷ−SP)²_norm + Σ w_slack·s² + R_Δu·Δu²_norm`, com Restrição como soft constraint `low − s ≤ ŷ ≤ high + s`, `s ≥ 0`, e **`w_slack = 10⁴ × max(w_cv) × priority`** (com `max(w_cv) := 1.0` quando o bloco não tem CV) **[NOVA — implementação]** — dominância por construção: violação de faixa compra erro de SP, nunca o contrário. `R_Δu` default 0.1 **[NOVA — implementação]**.
5. **Δu duro e Nc:** o do-mpc não tem horizonte de controle nativo → estado aumentado `u_{k-1}`; restrição dura `|u_k − u_{k-1}| ≤ du_max` (RF-604); **Δu ≡ 0 para k ≥ Nc** (bloqueio de movimentos). Np/Nc derivados e exibidos, nunca editados (RF-603).
6. **Init bumpless — rotina única de armar/re-armar** (usada em MAN→AUTO, respawn e rebuild): pares autorreguláveis → `x = x_ss(u_vigente, d_vigente)`; pares integradores → estado de saída = CV medida; estados de atraso preenchidos com a entrada vigente do par; `u_{k-1} := u_vigente`; `bias := y_medido − C·x` (erro de predição inicial zero). Primeira MV do AUTO dista ≤ `du_max` do valor vigente — o "sem salto" do aceite é consequência da construção.
7. **Solver:** IPOPT default do do-mpc, saída suprimida, warm start entre execuções; `set_initial_guess()` após respawn. Limites duros de MV via bounds do otimizador.

---

## 4. Runtime, modos e bumpless (flow-runtime)

1. **`MpcWorker` — processo dedicado por bloco MPC** (decisão A-3; mesmo fundamento do ProcessPool do Script, F3 decisão #4, com afinidade obrigatória: o modelo não é picklável). Spawn no deploy do flow; build assíncrono (o flow varre desde já; `status.solver = "building"` até pronto). Por execução viaja `{y_medidos, u_aplicados, DVs, SPs, faixas}` → `{plano de MV, predição, custo, status, wall_ms}`. Estado (x, bias, u_prev, warm start) mora no worker. Kill ⇒ respawn ⇒ rebuild ⇒ re-init bumpless (§3.6). Segfault do IPOPT é falha isolada do bloco, nunca do runtime (ADR-004 satisfeito no espírito: o event loop jamais bloqueia).
2. **Cadência e orçamento (RF-606/624, ADR-014):** fronteira de execução = varreduras com `n mod multiplier = 0`. Em AUTO, o `step()` **dispara** o solve na fronteira e **nunca espera**; o resultado aplica na primeira fronteira de varredura após concluir (a tabela de portas só muda em fronteira — determinismo do RF-401 preservado). Deadline **70% × Ts_mpc** medido do disparo: estourou ⇒ kill + respawn em background + `overruns++` + `mpc_overrun` (dedupe por período, padrão `flow_overrun`) + mantém última MV + pula (nunca acumula fila). Worker indisponível na fronteira seguinte ⇒ conta overrun e pula, sem novo evento. Entre execuções as saídas seguram o último valor (RF-606). Fora de AUTO o worker fica ocioso; `prediction` vazia e `status.solver = "idle"`.
3. **Saída MV por modo (RF-621/622/623):** LOCAL → tracking do readback (com `pid`; via `ValueSnapshot`) ou hold de `initial_value`/último valor (sem `pid`); REMOTO+MAN → valor manual clampado em `limits`; REMOTO+AUTO → último plano aplicado. Com `pid`, publica em `opc.writes` **a cada varredura do flow** (`source = flow:<fid>/block:<bid>`, padrão F3 §3.2) — em LOCAL não escreve **nada** (RF-621); o gate de watchdog/modo do opc-worker (F2) permanece a última barreira (RNF-03).
4. **Transições (tabela normativa):**

| De → Para | Ação | Falha |
|---|---|---|
| LOCAL→REMOTO | escreve `mode_cmd = mode_values.target` por MV com `pid`; entra em **MAN**; MV manual := vigente | com `mode_read`: sem confirmação em 2×Ts_mpc ⇒ volta LOCAL + `mpc_arm_failed {reason: no_confirm}` |
| REMOTO→LOCAL | escreve `mode_cmd = mode_values.auto` (devolve o PID a SP/OUT-tracking); LOCAL | — |
| MAN→AUTO | exige worker pronto e entradas aquecidas e válidas; init bumpless §3.6; primeira execução na próxima fronteira | `mpc_arm_failed {reason: worker_not_ready\|cold_input\|invalid_input}`; permanece MAN |
| AUTO→MAN | MV manual := MV vigente (sem salto) | — |
| stop do flow em REMOTO | devolve (`mode_cmd = auto`) antes de encerrar a task | em `comm_failure` não há como escrever — o watchdog do lado do PLC devolve (ADR-009); documentado |

   Pré-condição de REMOTO: flow rodando e todas as entradas aquecidas (flow vivo ⟹ sem `comm_failure` pendente nas conexões referenciadas — §2.2-8). Boot/deploy ⇒ sempre LOCAL (RNF-03; decisão A-4). **SP faz PV-tracking fora de AUTO e congela ao entrar** (decisão A-4); nada de modos/SP/MV manual persiste no banco.
5. **Shed (RF-604 `mode_read`):** leitura de modo ≠ `target` por **2 execuções consecutivas** (operador tirou o PID de RCAS no painel) ⇒ REMOTO→LOCAL + `mpc_shed` alarm. Sem `mode_read`, sem shed (fire-and-forget coerente com estado publicado).
6. **Invalidez (simetria F3 §3.0/decisão A-6 da F3):** entrada CV/Restrição/DV com `ok=false` na fronteira ⇒ pula o solve, saídas mantêm valor com `ok=false` (OPC-Write a jusante suprime), escritas internas do `pid` suprimidas, `mpc_input_invalid` warning (dedupe). Cold start (`v=None`) ⇒ saídas nulas (§3.0 F3) e REMOTO bloqueado.
7. **Hot-swap (ADR-011; decisão A-11):** config do bloco MPC alterado com flow rodando ⇒ worker novo + **shed a LOCAL** + `mpc_mode_changed {reason: hot_swap}` — mudança de engenharia sob malha fechada nunca mantém AUTO. Blocos não alterados preservam estado (regra da F3 intacta).
8. **Comandos novos em `flow.commands`** (payload PRD §7.1 verbatim; `args` carrega o específico; idempotentes, inválido = log e ignora, padrão F3 §2.2-7):
   - `{cmd: "mpc_mode", args: {block_id, axis: "local_remote"|"man_auto", value}}` — mesmo valor = no-op; `man_auto` em LOCAL = ignorado (ADR-010: sub-modo só existe em REMOTO).
   - `{cmd: "mpc_sp", args: {block_id, var_id, value}}` — só materializa em AUTO (fora, PV-tracking manda); clamp em `sp_limits`.
   - `{cmd: "mpc_mv", args: {block_id, var_id, value}}` — só materializa em REMOTO+MAN; clamp em `limits`.
   O runtime materializa e audita (`mpc_mode_changed`/`mpc_sp_written`/`mpc_mv_written`, `user` no payload); a API não duplica.
9. **Falha de solver ≠ overrun (RF-624):** IPOPT sem convergência ⇒ mantém MV + `mpc_solver_error {reason: no_convergence}` alarm (worker vivo, sem kill); crash do worker ⇒ respawn + `{reason: crash}`. Sem shed automático (§1.2).
10. **`/health` (RNF-07):** cada flow ganha, por bloco MPC, `{mode, overruns, last_solve_ms, worker: {alive, respawns}}`; o script-pool ganha `{size, busy, respawns}` (débito #5, §8).

---

## 5. Barramento e eventos

### 5.1 Payload `mpc.state.<flow_id>.<block_id>` (detalha PRD §7.1; RF-625)

```json
{"modes": {"local_remote": "local|remote", "man_auto": "man|auto"},
 "status": {"solver": "ok|overrun|error|building|idle", "overruns": 3,
            "last_solve_ms": 412.7, "armed": true, "input_valid": true},
 "vars": {"<var_id>": {"v": 12.3, "sp": 12.5}},
 "cost": 0.184,
 "prediction": {"t": [0.0, 5.0, 10.0], "cv": [[...]], "mv": [[...]]}}
```

- `sp` presente só em CV (em AUTO, o congelado; fora, o rastreado). `armed = (local_remote == "remote")`.
- Ordem das linhas de `prediction.cv[][]` = CVs na ordem do config, depois Restrições; `mv[][]` = MVs na ordem do config; `t[]` em segundos relativos a "agora" (0, Ts_mpc, …, Np×Ts_mpc). Fora de AUTO, `prediction` vazia (`t: []`). O consumidor mapeia pela ordem do `graph_json` — nenhuma chave além do PRD.
- O stub `MpcState` do `bus.py` (F3) refina `vars` para o objeto acima — a forma externa do PRD (`{modes, status, vars, cost, prediction}`) não muda.

### 5.2 Publicação

A cada execução do MPC (cadência Ts_mpc, inclusive fora de AUTO — modos/valores vivos) **e** imediatamente em: mudança de modo, escrita de SP/MV materializada, transição de `status.solver`. Fire-and-forget (RNF-05). **Recorder ignora `mpc.state`** — predições nunca persistidas (ADR-016).

### 5.3 Vocabulário `kind` novo (extensão da tabela F3 §4.3; `origin = flow:<fid>/block:<bid>`; `user` no payload quando houver comandante — emenda F3 de 2026-08-04)

| `kind` | severity | quando |
|---|---|---|
| `mpc_mode_changed` | info | transição materializada; payload `{axis, from, to, user? \| reason: hot_swap\|shed}` |
| `mpc_sp_written` / `mpc_mv_written` | info | escrita materializada; payload `{var_id, value, user}` |
| `mpc_overrun` | warning | orçamento 70% estourado; dedupe por período (padrão `flow_overrun`) |
| `mpc_solver_error` | alarm | `{reason: no_convergence\|crash}` |
| `mpc_shed` | alarm | `mode_read` ≠ target por 2 execuções (§4.5) |
| `mpc_arm_failed` | warning | `{axis, reason: no_confirm\|worker_not_ready\|cold_input\|invalid_input}` |
| `mpc_input_invalid` | warning | solve pulado por entrada inválida; dedupe |

---

## 6. API `/api/operate` e WebSocket

### 6.1 Rotas (padrões F1 §6.1: `/api`, 422 pt-BR string única, sem paginação; papel **operator**; response **202** — Regra do Estado Publicado)

| Rota | Corpo | Validação da API |
|---|---|---|
| `POST /api/operate/{flow_id}/{block_id}/mode` | `{axis, value}` | flow existe; `block_id` é nó `mpc` do grafo; enum válido |
| `POST /api/operate/{flow_id}/{block_id}/sp` | `{var_id, value}` | var é CV do bloco; `value` dentro de `sp_limits` |
| `POST /api/operate/{flow_id}/{block_id}/mv` | `{var_id, value}` | var é MV do bloco; `value` dentro de `limits` |

A API valida forma e faixa e publica `flow.commands`; **não** conhece o modo vigente (isso é estado publicado) — o runtime re-valida (§4.8) e é quem audita. Nenhum evento emitido pela API.

### 6.2 WebSocket `/ws` (mesmo protocolo da F3 §5.3)

`{"subscribe": {"mpc_state": ["<flow_id>/<block_id>", …]}}` / `unsubscribe` análogo; fanout `{"channel": "mpc.state.<fid>.<bid>", "data": {…}}`. Implementado sobre `ottima_core.pubsub` (§8-1) — a assinatura Redis continua uma só por processo, roteada.

---

## 7. Frontend (autoridade visual: PRODUCT.md/DESIGN.md)

1. **Paleta:** MPC arrastável; badge "F4"/"Disponível na próxima fase" removidos (`FlowPalette.tsx`).
2. **Nó no canvas:** portas dinâmicas do config (entradas CV/Restrição/DV à esquerda, saídas MV à direita), rótulo `nome (EU)`, handles = ids estáveis (§2.1-1); DESIGN.md §Shapes (chapa, plaqueta, bisel 2–4 px). Na mesma leva: EU nas portas de Script/TFS (débito m4).
3. **Modal 7 abas (RF-607 verbatim):** **Geral** (nome, multiplicador; Ts_mpc derivado exibido) · **Variáveis** (4 listas com criar/remover; identidade: nome, EU, categoria, `kind` por CV/Restrição; tags do PID por MV — selects filtrados por direção — e `target_mode`/`mode_values`) · **Modelos** (matriz; célula habilitável; params conforme `kind` da linha) · **Horizontes** (TSS por linha; Ts_mpc/Np/Nc read-only; warnings §2.2-7 ao vivo) · **Restrições & Limites** (faixas low/high, limites min/max, Δu, `initial_value`) · **Pesos** (w por CV, prioridade por Restrição) · **Resumo de validação** (erros bloqueiam salvar; warnings não).
4. **Validação no cliente = espelho gerado do schema Pydantic** (fonte única, §8-2/4); o servidor é a barreira (422 exibido como string pt-BR — padrão `api.ts` da F3). Entradas numéricas aceitam vírgula e ponto; "Aplicar" fecha por `close()` explícito (débito m4).
5. **Sem superfície de operação** — modos/SP/MV não aparecem no editor (F5 é dona). O canvas mostra valores vivos das portas via `flow.status.ports` (F3).

---

## 8. Débitos herdados — fecham na F4 (decisão A-5; Etapa 0 do plano F4a, salvo indicação)

| # | Débito (origem) | Fechamento | Aceite |
|---|---|---|---|
| 1 | 3 cópias do laço pubsub (`events.py`, `snapshot.py`, `ws.py` — defeito I2 da F3 nasceu da divergência) | `ottima_core.pubsub` (`ChannelListener`/`PatternListener`); o fanout §6.2 nasce nele | grep prova ausência das cópias; fechamento defensivo único |
| 2 | Contrato de porta em 3 lugares (`flowgraph.py`, `graph.ts`, `nodes/index.tsx`) | lado TS gerado do modelo Pydantic (pipeline `generate:api` ganha o passo); portas dinâmicas do MPC nascem na fonte única | sem literais de porta duplicados no TS |
| 3 | `_project_tags` duplicado (supervisor.py / flows.py) | função única em `ottima-core` | grep |
| 4 | `PortValue` do WS declarado 2× (fora do OpenAPI) | mesmo gerador do #2 para payloads WS; `MpcState` já nasce gerado | `useFlowStatus.ts` importa tipo gerado |
| 5 | ProcessPool invisível no `/health` | §4.10 | L1 assere os campos |
| 6 | `supervisor.py` 630 / `flowgraph.py` 737 (teto 800; a F4 adiciona a ambos) | corte **antes** do código novo: `definition.py` (~200 ln); parse/validate separados | tetos respeitados pós-F4, revisão própria |
| 7 | 5 cópias de `await_until` | util de teste compartilhado do workspace | grep |
| m1 | `unhandled_exception` fora de `MOTIVOS` (`useLastFlowState.ts`) | acrescentar | flow quebrado mostra motivo real |
| m2 | banker's rounding sem nota (`flowgraph.py:530`, `tfs.py:104`) | nota normativa + mesma convenção no MPC (§3.1) | comentário cita esta spec |
| m3 | teto teórico C2 do script_pool sob cancelamento repetido | guarda no caminho de cancelamento | teste de regressão |
| m4 | UI: EU nas portas, bool de Script exibido como número, inserção por `nodes.length`, vírgula/ponto no TFS, "Aplicar" sem `close()` | corrigidos nas superfícies §7 (plano F4a) | roteiro L3 confere |

---

## 9. Testes e gate E2E

### 9.1 Unit/integração (padrões F1 §9 · F2 §11.1 · F3 §7.1)

- **Mesa pura (TDD estrito, CLAUDE.md §Testes):** discretização SOPDT/IOPDT vs solução analítica no Ts_mpc (degrau, tempo morto, θ≈0, convenção banker's) · montagem (dimensões, bounds, Δu duro, Δu≡0 para k≥Nc, normalização por span) · **precedência: slack dominante** (SP em conflito com faixa ⇒ faixa vence) · init bumpless (autorregulável e integrador; primeira MV ≤ du_max do vigente) · bias (erro de ganho do modelo vira offset corrigido em regime) · derivação Np/Nc e tetos (função pura §2.2-5) · validação §2.2 completa (mesa do `flowgraph`).
- **flow-runtime (clock controlado + worker real):** fronteiras com multiplicador · aplicar-na-fronteira (resultado nunca aparece no meio da varredura) · overrun determinístico (orçamento forçado ≥10× menor que o solve real) com kill/respawn e MV mantida · tabela de transições §4.4 (incl. `arm_failed` por confirmação, shed, stop gracioso devolvendo `mode_cmd=auto`) · tracking em LOCAL (readback e sem-`pid`) · supressão por invalidez · hot-swap ⇒ shed · comandos §4.8 (idempotência, clamps, ignorados fora do modo).
- **api:** rotas §6.1 (RBAC operator, 422 de faixa/categoria, 202 + publicação) · WS `mpc_state` (subscribe/fanout/token inválido).
- **Carga (RNF-02/PRD §9-1):** teste marcado `slow`: modelo 2×2, Np=60 — `make_step` < 70% do Ts_mpc de referência no hardware de referência.

### 9.2 Gate E2E — 3 camadas (protocolo F2 §11.2/F3 §7.2)

**L1** — `deploy/smoke.sh`: inalterado + campos novos do `/health` (§4.10).

**L2** — `tests/e2e`, cenários novos (malha MPC↔TFS via API real; opcsim para as tags do `pid`):

| Cenário | Prova |
|---|---|
| E2E-F4-01 | deploy de flow MPC+TFS; `mpc.state` publica na cadência Ts_mpc; boot em LOCAL |
| E2E-F4-02 | 422s de validação (matriz incoerente, Np_max, tag de direção errada) |
| E2E-F4-03 | armar LOCAL→REMOTO(MAN)→AUTO **sem salto** (ΔMV da 1ª execução ≤ du_max) |
| E2E-F4-04 | AUTO converge CV→SP na malha TFS (tolerância e janela definidas no plano) |
| E2E-F4-05 | **restrição vence CV**: SP conflitante com faixa ⇒ faixa respeitada, SP sacrificado |
| E2E-F4-06 | **overrun mantém MV + alarme**: modelo dimensionado para estourar o orçamento com folga ≥10×; MV congelada + `mpc_overrun` |
| E2E-F4-07 | devolver: AUTO→LOCAL congela MV e escreve `mode_cmd = mode_values.auto` no opcsim |
| E2E-F4-08 | `/operate`: RBAC, 422 de faixa, `mpc_mv` fora de MAN não materializa |
| E2E-F4-09 | shed: `mode_read` divergente por 2 execuções ⇒ LOCAL + `mpc_shed` |
| E2E-F4-10 | fanout WS de `mpc.state` + hot-swap do config ⇒ shed + worker novo |

E2E-F4-03/05/06 são literalmente o aceite da fase (PRD §8-F4).

**L3** — roteiro browser `B-F4-01..06` (controlador, screenshot por passo): paleta com MPC habilitado · modal 7 abas com validação viva (Np/warnings ao vivo) · salvar bloqueado com erro e liberado sem · portas dinâmicas no nó após salvar · 422 exibido como string pt-BR · minors m4 conferidos.

### 9.3 Precondições de ambiente

Herdam integralmente o protocolo da F3 (CLAUDE.md §Comandos): L2 e Playwright serializados; L1 exige flow-runtime recém-subido; `OTTIMA_E2E_REDIS_PORT` quando a 6379 estiver ocupada; credenciais sempre inline.

---

## 10. Aderência ao aceite F4 (PRD §8)

| Critério | Evidência na spec |
|---|---|
| Malha fechada MPC↔TFS assume/devolve **sem salto de MV** | §3.6 (init bumpless por construção) · §4.4 (transições) · E2E-F4-03/07 · TDD bumpless §9.1 |
| **Restrição vence CV** | §3.4 (dominância por construção) · E2E-F4-05 · TDD precedência §9.1 |
| **Overrun mantém MV + alarme** | §4.2 (deadline 70%, kill+respawn, MV mantida) · §4.9 (falha ≠ overrun) · E2E-F4-06 |
| Modal com abas / montagem / multiplicador / orçamento | §7.3 · §3 · §4.2 · L3 B-F4 |

---

## Anexo A — Decisões do brainstorm (2026-08-04)

| # | Lacuna | Decisão aprovada |
|---|---|---|
| A-1 | Estrutura documental (CLAUDE.md prevê divisão da F4) | **1 spec + 2 planos** (F4a config & montagem · F4b runtime & modos) |
| A-2 | Aceite exige transições de modo, mas tela de operação é F5 | **REST `/api/operate` mínimo na F4** (202, operator, auditoria pelo runtime); UI só na F5 |
| A-3 | Onde roda o `make_step()` (ADR-004 fixa o invariante, não o mecanismo) | **Processo dedicado por bloco MPC**: modelo montado no worker, timeout real (kill+respawn), crash isolado; thread rejeitada (não-matável, GIL incerto do casadi) |
| A-4 | Ciclo de vida de modos/SP/MV manual | **Volátil + tracking**: deploy ⇒ LOCAL; REMOTO entra em MAN; SP faz PV-tracking fora de AUTO e congela ao entrar; nada persiste no banco (RNF-03) |
| A-5 | Débito estrutural das fases anteriores | **Todos fecham na F4** (§8) — ordem do usuário: "feche todos os débitos das fases anteriores na F4" |
| A-6 | Transporte do `mpc.state` ao cliente | **Fanout no `/ws` entra na F4**; F5 vira consumo puro |
| A-7 | Realimentação do MPC (modelos de step-test não têm estados medidos) | **Bias de saída estilo DMC** via `_tvp`; MHE rejeitado (2º problema de otimização por execução em host de 4 vCPU) |
| A-8 | Aceite MPC↔TFS não tem PLC, mas RF-604 configura tags de PID | **`pid` opcional por MV**; ausente ⇒ MV direta (sem `opc.writes`, LOCAL = hold de `initial_value`); misto permitido |
| A-9 | Renomear variável quebraria aresta/estado | **Ids estáveis por variável** = handle de porta e chave de estado |
| A-10 | Por onde a CV medida entra | **Pela porta do canvas** (permite condicionamento por Script; TFS fecha malha) — readback/modo do PID via `ValueSnapshot` interno |
| A-11 | Hot-swap de config MPC sob malha fechada | **Worker novo + shed a LOCAL** — engenharia nunca mantém AUTO; operador re-arma |
| A-12 | Shed automático por overrun/falha de solver | **Não** (RF-624 literal: mantém MV + alarme; devolver é do operador) — registrado como não-objetivo |
| A-13 | Emendas pendentes da spec F3 | Aplicadas **antes** desta spec (`28ef789`): `deploy_rejected`, reasons de `flow_stopped`, correção do `/ws` no nginx, `user` no payload |
