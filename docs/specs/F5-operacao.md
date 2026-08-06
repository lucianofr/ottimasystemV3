# Spec F5 — Tela de operação (faceplates, trend com predição, eventos e banner)

**Fase:** F5 (PRD §8) · **Status:** aprovado em blocos em sessão de brainstorm · 2026-08-06
**Fontes normativas:** `docs/PRD.md` v1.2→v1.3 (RF/RNF, contratos §7, fases §8) · `docs/adr/ADR-001…024` (prevalecem em conflito) · `docs/GLOSSARY.md` · `PRODUCT.md`/`DESIGN.md` (frontend) · specs F1/F2/F3/F4 (vinculantes) · relatório de gate F4 §8.2 (dívidas herdadas)
**Execução:** 1 spec (esta) + 2 planos — F5a (dados & serviços) e F5b (tela de operação), decisão A-12.

Convenções herdadas: itens **[NOVA — implementação]** são decisões de implementação desta spec, sem lastro literal em RF/ADR; o Anexo A registra as decisões do brainstorm; testes citam itens numerados (ex.: §2.2-3).

---

## 1. Escopo da F5

**Entrega (PRD §8-F5):** tela de operação (faceplates + trend com predição), eventos/banner, auditoria.
**Aceite (PRD §8-F5):** operador conduz LOCAL/REMOTO/MAN/AUTO, escreve SP/MV; predição sobreposta ao histórico.

### 1.1 Dentro da F5

| Item | Governança |
|---|---|
| Hypertable `mpc_samples` + recorder assinando `mpc.state.*` | RF-703 · ADR-003 · decisão A-1 |
| Emenda PRD §7.1 (v1.3): `mpc.state` ganha `ts` | decisão A-2 |
| `GET /api/history/mpc` com downsampling | RF-703/802 (padrão) · §2.4 |
| `GET /api/operate/mpcs` (descoberta) | RF-701 · decisão A-7 |
| `GET /api/health/workers` (heartbeat na UI) | RNF-07 · decisão A-8 |
| Fanout do canal `events` no `/ws` | ADR-020 · decisão A-5 |
| F-1: boot assíncrono do worker MPC no deploy | spec F4 §4.1 (letra) · §6 |
| Socket único de sessão no cliente | decisão A-6 · §7.1 |
| Faixa anunciadora real (tabela de cessação) | RF-705 · ADR-020 · decisão A-4 |
| Tela `/operacao/:flowId/:blockId` (faceplates, comutadores, trend+predição) | RF-701..704 · ADR-016 |
| Página `/eventos` (UI do RF-803) | RF-803 · decisão A-13 |
| Home como visão geral (lâmpadas de workers + flows) | RNF-07 · DESIGN §Layout · decisão A-10 |
| F-3: vetores-golden Python→TS para `mpcLogic` | dívida F4 §8.2 · decisão A-9 |
| Débitos F4: handler global 422, 404 no `/operate`, `_empty_result` único | decisão A-9 · §4.3/§8 |

### 1.2 Fora da F5 — com destino registrado

| Item | Destino | Governança |
|---|---|---|
| `opc.values.<conn_id>` no `/ws` (trend de engenharia segue polling) | F6 ou nunca — só com consumidor real | decisão A-5; revoga o registro F2 §1.2/F3 §1.2 "valores de tag → F5" |
| EU nas portas de Script/TFS (exige campo novo de schema) | F6 | emenda 2026-08-05 do roteiro F4 |
| Export/import, UI de certificados, suíte completa RNF-09 | F6 | PRD §8 |
| ACK de alarmes | fora da v1 | ADR-020 |
| `mpc_state_dimension` conservador (2 estados por par SOPDT degenerado) | fica como está — letra da spec F4 §2.2-7; aviso conservador | decisão A-9 |
| Protocolo `Commandable`/`Healthy` (5 `isinstance` em `supervisor_mpc.py`) | revisitar no 2º bloco comandável | decisão A-9 |
| Persistir predição/custo/status do MPC | nunca | ADR-016 |

---

## 2. Dados & contratos

### 2.1 Emenda PRD §7.1 → v1.3: `ts` no `mpc.state` (decisão A-2)

`MpcState` (`ottima_core/bus.py`) ganha `ts: datetime` (UTC), carimbado pelo flow-runtime no instante que gerou o quadro: nas execuções, o instante da fronteira de varredura (mesmo relógio do `ts` de `flow.status`); nas publicações imediatas (mudança de modo, SP/MV materializada, transição de solver — spec F4 §5.2), o instante da publicação. É a âncora única do recorder (§2.3) e do overlay de predição (§3): `t_abs[k] = ts + prediction.t[k]`. Emenda submetida junto com esta spec — mesmo rito da emenda `ports` da F3 (PRD v1.2). Nenhum consumidor existente quebra (o campo é novo e nada consome `mpc.state` antes da F5). `contracts.gen.ts` regenera.

### 2.2 Hypertable `mpc_samples` (decisão A-1; migration `0003_mpc_samples`, SQL cru, padrão da 0002)

1. Colunas: `ts timestamptz NOT NULL` · `flow_id bigint NOT NULL` · `block_id text NOT NULL` · `var_id text NOT NULL` · `v double precision NOT NULL` · `sp double precision NULL`.
2. Hypertable com chunk de 7 dias; `add_retention_policy(..., INTERVAL '1 month')` (mesma política de `samples`/`events`, ADR-003).
3. Continuous aggregate `mpc_samples_1m`: `time_bucket('1 minute', ts)` com `avg(v)` e `avg(sp)` por `(flow_id, block_id, var_id)`.
4. Índice `(flow_id, block_id, var_id, ts DESC)`.
5. Volume pior caso **[NOVA — implementação]**: 10 flows × ~10 vars × 2 Hz (Ts_mpc mín. = 0,5 s) = 200 linhas/s — mesma ordem de `samples`; aceito.
6. Handle Core em `models/timeseries.py` (`TIMESERIES_METADATA`, fora do autogenerate — padrão F1).
7. O que **não** entra: `prediction`, `cost`, `status` — ADR-016 proíbe persistir predição; custo/status são deriváveis do log de eventos. A nota "Recorder ignora `mpc.state`" da spec F4 §5.2 fica **revogada**; a proibição que ela protegia (persistir predição) permanece em vigor por esta seção.

### 2.3 Recorder

1. Segundo `PatternListener` (`mpc.state.*`) no pipeline existente, ao lado de `opc.values.*` e `events` (`ottima_core.pubsub`).
2. `flow_id`/`block_id` saem do nome do canal; `ts` e `vars` do payload; uma linha por `var_id` (`sp` NULL quando a variável não publica `sp` — só CV tem).
3. Mesmo lote de 1 s (`FLUSH_INTERVAL_S`) e mesma resiliência do pipeline; payload malformado é logado e descartado sem derrubar nada (RNF-05).
4. Grava em **todos os modos** — o canal publica inclusive fora de AUTO (spec F4 §5.2) e o operador precisa do passado do tracking antes de armar. Publicações imediatas (mudança de modo, SP/MV materializada) geram linhas normais; duplicata eventual de `(ts, var)` é inócua (hypertable sem PK, como `samples`).

### 2.4 `GET /api/history/mpc` (router `history`; `require_operator`; padrões F1 §6.1)

1. Query: `flow_id` · `block_id` · `var_ids` (csv de ids de variável, deduplicado, teto **14** = 4 MV + 6 CV/Restr + 4 DV **[NOVA — implementação]**) · `start`/`end` (ISO-8601, naive = UTC).
2. Downsampling idêntico ao RF-802: janela ≤ 2 h ⇒ bruto; acima ⇒ `mpc_samples_1m`. Response `{mode: "raw"|"1m", series: {<var_id>: {t: [], v: [], sp: []}}}` — `sp` alinhado a `t` com `null` onde não havia.
3. Reprovações 422 pt-BR string única (var_ids vazio/malformado, start ≥ end, teto excedido) — handler global §4.3 cobre as de forma.

---

## 3. Semântica da predição (nota normativa; fato verificado em `mpc/worker.py::_extract_prediction`)

1. `t[] = [0, Ts_mpc, …, Np×Ts_mpc]` — **Np+1 pontos**, relativos ao `ts` do quadro (§2.1).
2. `prediction.cv[i][k]` = valor previsto da linha `i` **no instante** `t[k]` (trajetória contínua; linhas = CVs na ordem do config, depois Restrições).
3. `prediction.mv[i] = [u_prev, u_0, …, u_{Np-1}]`: o índice 0 é a MV **que estava em vigor entrando no ciclo**; o índice `j ≥ 1` é a MV aplicada **no intervalo `(t[j-1], t[j]]`**. Consequência de renderização: degrau **alinhado à esquerda** (uPlot `stepped`, `align: -1`); `align: +1` deslocaria o plano em meio passo e é **proibido**.
4. Fora de AUTO a predição chega vazia (`t: []`) — o overlay some; histórico e faceplates seguem vivos.

---

## 4. API nova e correções de API

### 4.1 `GET /api/operate/mpcs` — descoberta (decisão A-7; router `operate`; `require_operator`)

1. Projeta, dos flows do **projeto ativo**, todos os nós `type=mpc` do `graph_json`:

```json
[{"flow_id": 59, "flow_name": "Coluna C-101", "flow_ts": 1.0,
  "block_id": "mpc_x7k2", "name": "MPC da coluna", "multiplier": 5,
  "variables": {
    "mvs":  [{"id": "mv_a", "name": "Refluxo", "eu": "m3/h",
              "limits": {"min": 0.0, "max": 100.0}, "du_max": 5.0}],
    "cvs":  [{"id": "cv_b", "name": "Temp topo", "eu": "C",
              "sp_limits": {"min": 80.0, "max": 120.0}}],
    "constraints": [{"id": "co_c", "name": "Nível", "eu": "%",
                     "range": {"low": 20.0, "high": 80.0}}],
    "dvs":  [{"id": "dv_d", "name": "Carga", "eu": "m3/h"}]}}]
```

2. Só o que seletor e faceplates consomem — **sem** `pid`, `models`, pesos, TSS, `initial_value` (config de engenharia não vaza para a operação).
3. Estado rodando/parado **não** entra: é estado publicado (WS). Sem projeto ativo ⇒ lista vazia.

### 4.2 `GET /api/health/workers` — heartbeat na UI (decisão A-8; router `health`; `require_operator`)

1. A API consulta em paralelo (httpx, timeout 1 s cada) os `/health` internos de opc-worker, flow-runtime e recorder; URLs em `Settings` (`OTTIMA_HEALTH_URL_OPC_WORKER` etc.; defaults = nomes de serviço do compose) **[NOVA — implementação]**.
2. Response `{opc_worker: {up, ...corpo do /health}, flow_runtime: {...}, recorder: {...}}`; serviço fora do ar ou timeout ⇒ `{up: false}` — a rota responde **200 sempre** (agregador nunca propaga 5xx de terceiro).

### 4.3 Correções de contrato (decisão A-9; Etapa 0 do plano F5a)

1. **Handler global de `RequestValidationError`**: todo 422 de forma da API sai como `detail` **string única pt-BR** — inclusive enums Pydantic, que hoje vazam como lista FastAPI (dívida API-wide da F4). Os 422 de domínio já são string única; isto unifica os de forma.
2. **`/api/operate` com flow inexistente ⇒ 404** (`Flow não encontrado`), alinhado à convenção dos demais routers. Emenda consciente à spec F4 §6.1, que mandava 422; `block_id` inexistente/não-MPC e categoria/faixa erradas seguem 422.
3. **`_empty_result`** deduplicado: função única em módulo comum do pacote `mpc` (`worker.py` e `host.py` importam).

---

## 5. WebSocket `/ws` — canal `events` (decisão A-5; mesmo protocolo F3 §5.3/F4 §6.2)

1. Protocolo estende com chave booleana: `{"subscribe": {"events": true}}` / `{"unsubscribe": {"events": true}}` — canal único, sem ids **[NOVA — implementação]** (forma).
2. Hub ganha um `ChannelListener("events")` ao lado dos dois `PatternListener`; fanout `{"channel": "events", "data": {…payload EventMessage…}}` aos sockets optantes.
3. Escopo F5 fechado: `flow_status` + `mpc_state` + `events`. `opc.values.*` **fora** (§1.2) — sem consumidor, seria código morto testado.

---

## 6. Runtime — F-1: boot assíncrono do worker no deploy (letra da spec F4 §4.1)

1. `host.start()` sai do caminho síncrono do lock global do supervisor: o deploy estagia o flow e retorna; o build do worker (spawn + montagem do-mpc) roda como task em background.
2. O flow varre desde a primeira fronteira; o bloco MPC publica `status.solver = "building"` até o worker ficar pronto — o valor deixa de ser inalcançável.
3. `stop`/`deploy`/`reload` de **outro** flow não esperam build alheio (fim do head-of-line blocking de até `_BOOT_TIMEOUT_S`).
4. Invariantes preservadas: REMOTO antes de pronto ⇒ `mpc_arm_failed {reason: worker_not_ready}` (já existente); shed/hot-swap/watchdog intocados; as 6 invariantes dos fix rounds da F4 valem byte a byte.
5. `stop` do próprio flow durante o build cancela o build limpo (worker morto, sem respawn órfão) **[NOVA — implementação]**.

---

## 7. Frontend (autoridade visual: PRODUCT.md/DESIGN.md; tudo pt-BR, GLOSSARY, sem emojis)

### 7.1 Socket único de sessão (decisão A-6)

1. Provider `CanalAoVivo` no `AppShell`: **um** WebSocket por aba, vivo enquanto houver sessão. Reconexão/backoff/1008 num lugar só (reusa as puras testadas de `useFlowStatus`: `urlDoWs`, `atrasoReconexao`, `deveReconectar`; `analisarMensagem` generaliza por canal).
2. Páginas registram interesse via `useAssinatura({flow_status: [id]} | {mpc_state: ["fid/bid"]})`; o provider agrega interesses, envia deltas de `subscribe`/`unsubscribe`, roteia mensagens por canal e reassina tudo após reconectar.
3. `events` sempre assinado (o banner é do shell). 1008 ⇒ `sessao_invalida`, sem reconexão (contrato F3).
4. `useFlowStatus(flowId)` mantém assinatura pública idêntica — o editor F3 não muda de forma; só a implementação passa a consumir do provider.

### 7.2 Faixa anunciadora real (decisão A-4; RF-705, ADR-020)

1. **Tabela normativa de cessação** — a condição "ativa" é derivada no cliente, stateless, por três famílias:

| Família | Kinds | Ativa desde | Cessa quando |
|---|---|---|---|
| Par de eventos | `comm_failure`→`comm_restored` · `flow_failed`→`flow_deployed` | evento de abertura | evento par com a **mesma `origin`** |
| Estado publicado | `mpc_solver_error` · `mpc_input_invalid` · `mpc_shed` | evento | `mpc.state` do bloco publica `solver ≠ "error"` / `input_valid = true` / re-armado (`armed = true`) respectivamente |
| TTL | `flow_overrun` · `mpc_overrun` · `script_timeout` · `script_error` · `mpc_arm_failed` | evento | sem repetição do mesmo `kind`+`origin` por **3× o período**, mínimo 30 s **[NOVA — implementação]**. Período: Ts do flow (`GET /api/flows`, campo `ts`) para kinds de flow/script; Ts_mpc (`multiplier × flow_ts` de `GET /api/operate/mpcs`) para kinds de MPC; origem sem período conhecido ⇒ fallback 90 s (1,5× o Ts máximo da lista ADR-007) |

2. Bootstrap na montagem do shell: `GET /api/events?severity=warning&limit=200` + `GET /api/events?severity=alarm&limit=200` (o endpoint aceita uma severidade por chamada) e, para os períodos do TTL, `GET /api/flows` + `GET /api/operate/mpcs` (cache, refetch a 60 s); depois só WS. `resolverAlarmes(eventos, flowStatus, mpcStates, periodos, agora)` é função pura com check próprio.
3. Renderização (DESIGN §Layout): colapsada em 1 linha quando vazio; com condições ativas, contagem por severidade + lista expansível (cor + ícone + texto — Regra do Canal Redundante); clique navega a `/eventos`. Sem ACK (ADR-020).

### 7.3 Navegação e Home (decisão A-10)

1. Nav do shell em dois grupos: **Operação · Eventos** | Conexões · Tags · Flows · Trend. Rotas novas: `/operacao`, `/operacao/:flowId/:blockId`, `/eventos`.
2. RBAC: operação e eventos são de **operador** (admin herda); telas de engenharia seguem como estão (mutação só admin).
3. **Home = visão geral do console** (DESIGN §Layout): lâmpadas dos 3 workers (`GET /api/health/workers`, polling 5 s — lâmpada de estado, nunca só cor) + flows do projeto ativo com estado ("Último estado", padrão F3 §6.1) + atalho por flow para a operação quando houver MPC.

### 7.4 Tela `/operacao/:flowId/:blockId` (RF-701/702/704; ADR-016)

1. `/operacao` sem parâmetro: seletor via `GET /api/operate/mpcs`; um único MPC ⇒ redirect direto. O MPC aberto vive na URL (F5 do browser restaura a tela — sala de controle).
2. Assina `mpc_state` do bloco e `flow_status` do flow; MPC ausente na revalidação de `GET /api/operate/mpcs` (refetch ao montar/focar — flow excluído ou projeto trocado) ⇒ volta ao seletor com aviso.
3. **Faceplate principal (topo):** plaqueta `nome · flow`; **comutadores de posição** LOCAL/REMOTO e MAN/AUTO (MAN/AUTO só renderiza em REMOTO — ADR-010); lâmpadas: flow (`flow.status.state` + motivo), solver (`ok|building|overrun|error|idle`), `input_valid`; contadores `overruns` e `last_solve_ms` em mono tabular.
4. **Comando pendente-até-confirmar** (Regra do Estado Publicado — visual): 1 gesto, sem diálogo; ao comandar, posição/valor comandado em fantasma + outline azul até o `mpc.state` seguinte confirmar; sem materialização em **2×Ts_mpc (mín. 5 s)** ⇒ reverte ao publicado **[NOVA — implementação]** (o comando pode ter sido legitimamente ignorado pelo runtime — spec F4 §4.8).
5. **Faceplates de variável (base; RF-702):** um por MV/CV/Restrição/DV, cada um com **barra vertical** com escala demarcada (`limits`/`sp_limits`/`range` — DESIGN §Shapes, convenção intocável), PV grande em mono tabular + EU (Regra do Número Tabular).
   - CV: entrada de SP **habilitada só em AUTO** (fora, SP rastreado exibido dessaturado — PV-tracking da decisão A-4 da F4); clamp client-side em `sp_limits` (espelho leve; servidor é a barreira).
   - MV: entrada manual **só em REMOTO+MAN**; clamp em `limits`; fora do modo, campo desabilitado com o valor publicado.
   - Restrição: faixa low/high marcada na barra; somente leitura. DV: somente leitura.
   - Toda escrita segue o pendente-até-confirmar do item 4 e flui UI → REST `/api/operate` → `flow.commands` → runtime → estado republicado (RF-704; auditoria é do runtime, F4 §4.8).
6. **Trend central (uPlot re-vestido; RF-703; DESIGN "tinta que ainda não secou"):**
   - Histórico: `GET /api/history/mpc` — janelas 15 min · 30 min · 2 h · 8 h (default **30 min**), polling 5 s.
   - **Borda viva:** cada `mpc.state` (ts + vars) faz append nas séries — o "agora" nunca espera o poll; o poll re-sincroniza **[NOVA — implementação]**.
   - Overlay de predição do último quadro: âncora `ts` (§2.1); CVs/Restrições tracejadas no **mesmo matiz mais claro** com fade ao horizonte; **MVs como degraus fantasma `stepped align: -1`** (§3.3); linha-cursor "agora"; pena de SP = Azul Industrial (DESIGN §Primary); Restrição com banda low/high sombreada no Poço.
   - Defaults (decisão A-11): CVs + Restrições + SPs ligadas; MVs **opt-in** pela legenda clicável; eixo futuro dimensionado por Np×Ts_mpc; ~8 penas visíveis por legibilidade **[NOVA — implementação]**.
   - Fora de AUTO: overlay some (§3.4); histórico e barra "agora" seguem.

### 7.5 Página `/eventos` (decisão A-13; RF-803)

1. Tabela ts desc: severidade (lâmpada + texto), origem, mensagem, payload expansível (`<details>`), filtros severidade/origem/período (`GET /api/events`).
2. Sem filtro de período ("ao vivo"): eventos novos do WS que casem com os filtros ativos entram no topo com marca de recém-chegado; filtro de período ativo ⇒ consulta histórica pura, sem prepend.

### 7.6 F-3 — vetores-golden Python→TS (decisão A-9)

1. `uv run python -m ottima_core.mpc_golden_export` (novo) emite JSON de casos: `derive_horizons` (Ts_mpc/Np/Nc), dimensão de estados, tetos 1..4/1..6/0..4, limiares Np<2/Np>120/Np>60/dim>120, banker's rounding — commitado em `frontend/src/features/flows/mpc/mpcLogic.golden.json` **[NOVA — implementação]** (caminho).
2. `mpcLogic.check.ts` assere igualdade campo a campo contra o golden: divergência TS×Python vira teste vermelho, não bug silencioso. A F5 não adiciona regra espelhada nova (validação de SP/MV é servidor + runtime); o golden congela as existentes.

---

## 8. Débitos herdados — veredito (decisão A-9)

| # | Débito (relatório gate F4 §8.2) | Veredito F5 | Onde |
|---|---|---|---|
| F-1 | Boot de worker síncrono sob o lock do supervisor | **Fecha na F5** (cedo — a tela torna a latência visível) | §6 · plano F5a |
| F-3 | Regras client-side espelhadas à mão | **Fecha na F5** (golden) | §7.6 · plano F5b |
| — | `_empty_result` duplicado | **Fecha na F5** (Etapa 0) | §4.3-3 |
| — | 422 de enum como lista FastAPI | **Fecha na F5** (handler global) | §4.3-1 |
| — | `/api/operate` 422 vs 404 | **Fecha na F5** (unifica 404) | §4.3-2 |
| — | `prediction_mv` semântica por índice | **Confirmada e fixada** (nota normativa) | §3 |
| — | `mpc_state_dimension` conservador | Fica (letra da spec F4 §2.2-7) | §1.2 |
| — | Protocolo `Commandable`/`Healthy` | Fica (revisitar no 2º bloco comandável) | §1.2 |
| — | EU nas portas de Script/TFS | Diferido F6 (schema novo) | §1.2 |

---

## 9. Testes e gate E2E

### 9.1 Unit/integração (padrões F1 §9 · F2 §11.1 · F3 §7.1 · F4 §9.1)

- **ottima-core:** `MpcState.ts` no contrato; `mpc_golden_export` determinístico (mesma entrada ⇒ mesmo JSON).
- **recorder:** linhas corretas de `mpc.state` (uma por var; `sp` NULL fora de CV; flow/block do canal), lote, payload malformado ignorado sem derrubar o pipeline.
- **api:** `/api/history/mpc` (raw×1m na fronteira de 2 h, 422s, teto 14, RBAC) · `/api/operate/mpcs` (projeção sem `pid`/`models`, só projeto ativo, RBAC) · `/api/health/workers` (agrega, down⇒`up:false`, timeout, sempre 200) · handler global (enum inválido ⇒ string única pt-BR) · 404 de flow no `/operate`.
- **flow-runtime (clock controlado):** F-1 — deploy com build pesado não bloqueia `stop`/`deploy` de outro flow; `solver="building"` publicado e transiciona; `ts` presente e crescente no `mpc.state`; stop durante build cancela limpo (§6.5).
- **ws:** fanout `events`; os 3 tipos de assinatura no mesmo socket; unsubscribe para.
- **frontend `test:unit`:** `resolverAlarmes` (3 famílias, TTL, bootstrap, mesma `origin`) · máquina do canal único (agregação de interesses, deltas, reconexão reassina, 1008) · golden `mpcLogic` (§7.6) · redutor pendente-até-confirmar (materializa, ignora, expira) · clamps de faceplate · montagem de séries do trend (append da borda viva, alinhamento da predição, `align:-1`).

### 9.2 Gate E2E — 3 camadas (protocolo F2 §11.2/F3 §7.2/F4 §9.2)

**L1** — `deploy/smoke.sh`: inalterado + `GET /api/health/workers` com os 3 `up: true`.

**L2** — `tests/e2e`, cenários novos (malha MPC↔TFS via API real; opcsim):

| Cenário | Prova |
|---|---|
| E2E-F5-01 | flow MPC rodando ⇒ `mpc_samples` ganha linhas na cadência Ts_mpc; `sp` NULL fora de CV; `ts` do payload = `ts` gravado |
| E2E-F5-02 | `/api/history/mpc`: bruto ≤ 2 h e `1m` acima; teto/422; RBAC |
| E2E-F5-03 | `/api/operate/mpcs` projeta o config (sem `pid`/`models`); flow inexistente no `/operate` ⇒ **404** |
| E2E-F5-04 | WS `events`: subscribe ⇒ evento publicado chega; unsubscribe ⇒ para |
| E2E-F5-05 | **F-1:** deploy de flow MPC pesado não bloqueia `stop` de outro flow (latência medida); `building` observável em `mpc.state` antes de `idle` |
| E2E-F5-06 | `ts` presente e monotônico em quadros consecutivos de `mpc.state` |
| E2E-F5-07 | handler global: enum inválido em `/operate/mode` ⇒ 422 string única pt-BR |

**Regressão:** os 34 cenários L2 F1-F4 verdes na mesma rodada; Playwright F1 serializado após a L2.

**L3** — roteiro browser `docs/plans/tests-e2e-f5.md` (**executado pelo controlador** — a tool `browser` é bloqueada a subagentes; herda a seção de armadilhas do roteiro F4 §2):

| ID | Passo |
|---|---|
| B-F5-01 | Login operador → nav Operação → seletor → tela do MPC |
| B-F5-02 | Faceplates: barras verticais com escala, EU, limites/faixas; valores mono tabular |
| B-F5-03 | Armar LOCAL→REMOTO(MAN)→AUTO pela UI; pendente (fantasma + outline azul) → confirmado pelo estado publicado |
| B-F5-04 | SP em AUTO e MV em MAN (clamp, materialização, auditoria em `/eventos`); entradas desabilitadas fora do modo |
| B-F5-05 | Trend: histórico sólido → linha-agora → predição tracejada; MVs degraus fantasma; janelas; legenda alterna MVs |
| B-F5-06 | Congelar watchdog do opcsim ⇒ alarme na faixa em **qualquer** tela; restaurar + re-deploy ⇒ cessa |
| B-F5-07 | `/eventos`: filtros; prepend ao vivo com marca de recém-chegado |
| B-F5-08 | Home: lâmpadas dos workers; parar um serviço ⇒ lâmpada down (compose stop/start do recorder) |
| B-F5-09 | RBAC: operador opera (modos/SP/MV) e não vê mutações de engenharia |

### 9.3 Precondições de ambiente

Herdam o protocolo F3/F4 (CLAUDE.md §Comandos): L2 e Playwright serializados; credenciais sempre inline; `down -v` só com autorização explícita + dump prévio; sempre os dois arquivos compose.

---

## 10. Aderência ao aceite F5 (PRD §8)

| Critério | Evidência na spec |
|---|---|
| Operador conduz LOCAL/REMOTO/MAN/AUTO | §7.4-3/4 (comutadores + pendente-até-confirmar) · B-F5-03 · E2E-F4-03/08 (regressão) |
| Escreve SP/MV | §7.4-5 · B-F5-04 |
| **Predição sobreposta ao histórico** | §2 (mpc_samples + ts) · §3 (semântica) · §7.4-6 (overlay) · B-F5-05 |
| Eventos/banner | §7.2 (tabela de cessação) · §7.5 · B-F5-06/07 |
| Auditoria | runtime F4 §4.8 (já audita) · `/eventos` exibe (B-F5-04/07) |

---

## Anexo A — Decisões do brainstorm (2026-08-06)

| # | Lacuna | Decisão aprovada |
|---|---|---|
| A-1 | RF-703 pede histórico "via Timescale", mas só tags R têm passado em `samples` (CV entra pela porta, SP é volátil, MV escreve em tag W) | **Hypertable `mpc_samples`** gravada pelo recorder assinando `mpc.state.*`; cobre todas as variáveis + SP; revoga o "Recorder ignora `mpc.state`" da F4 §5.2 (a proibição de persistir predição permanece) |
| A-2 | `mpc.state` não tem instante; recorder e overlay precisam de âncora | **Emenda PRD §7.1 → v1.3:** `mpc.state` ganha `ts` carimbado pelo runtime (mesmo rito da emenda `ports` da F3) |
| A-3 | Semântica por índice de `prediction.mv` estava "a confirmar" | **Confirmada no código** (`_extract_prediction`): `mv[0]` = u_prev vigente; `mv[j]` vale no intervalo `(t[j-1], t[j]]` ⇒ degrau alinhado à esquerda (`stepped align:-1`), fixado como norma (§3) |
| A-4 | "Alarme ativo" sem evento de cessação para a maioria dos kinds | **Tabela normativa de cessação derivada no cliente** (3 famílias: par de eventos, estado publicado, TTL 3× período mín. 30 s); bootstrap REST + WS; `resolverAlarmes` pura |
| A-5 | Quais canais entram no `/ws` na F5 | **Só `events`**; `opc.values` fica fora (sem consumidor real — trend de engenharia segue polling); registro F2/F3 reapontado |
| A-6 | Topologia de socket no cliente (banner é de toda tela) | **Socket único de sessão no AppShell** + registro de assinaturas por página; `useFlowStatus` preserva assinatura pública |
| A-7 | Descoberta dos MPCs para o seletor | **`GET /api/operate/mpcs`**: projeção server-side do config (sem `pid`/`models`); nada de N+1 nem parsing de grafo no cliente |
| A-8 | RNF-07 "heartbeat visível na UI" com `/health` internos inalcançáveis do browser | **`GET /api/health/workers`**: API agrega os 3 `/health` via httpx; lâmpadas na Home; sempre 200 |
| A-9 | Dívidas F4 §8.2 sem veredito | **F-1, F-3, `_empty_result`, handler 422 global e unificação 404 entram na F5**; dimensão conservadora, protocolo de capacidade e EU Script/TFS ficam (§8) |
| A-10 | Navegação/rotas da operação | **Grupo Operação** (`/operacao/:flowId/:blockId` + `/eventos`) antes de Engenharia; MPC na URL; **Home vira visão geral** com lâmpadas de workers |
| A-11 | O que o trend de operação mostra por default | **CVs+Restrições+SPs ligadas; MVs opt-in** pela legenda; janela default 30 min (15 min/30 min/2 h/8 h) |
| A-12 | Estrutura documental da execução | **1 spec + 2 planos**: F5a dados & serviços · F5b tela de operação (fronteira = contratos gerados, padrão F4) |
| A-13 | Atualização da página `/eventos` | **REST com filtros + prepend ao vivo do WS** quando sem filtro de período; marca de recém-chegado |
