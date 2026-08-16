# Spec F5 — Tela de operação (faceplates, trend com predição, eventos e banner)

**Fase:** F5 (PRD §8) · **Status:** aprovado em blocos em sessão de brainstorm (2026-08-06); revisado por agente RFC e emendado no mesmo dia — achados F5R-01..27 aplicados (Anexo B)
**Fontes normativas:** `docs/PRD.md` v1.2→v1.3 (RF/RNF, contratos §7, fases §8) · `docs/adr/ADR-001…024` (prevalecem em conflito) · `docs/GLOSSARY.md` · `PRODUCT.md`/`DESIGN.md` (frontend) · specs F1/F2/F3/F4 (vinculantes) · relatório de gate F4 §8.2 (dívidas herdadas) · revisão `docs/reports/review/review-spec-f5-operacao-20260806.md`
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
| Emenda PRD v1.3 (§1.3-1): `ts` e `prediction.ts` no `mpc.state`, recorder como consumidor, `MpcSample` no §4, fonte concreta no RF-703 | decisão A-2 · F5R-01/11 |
| `GET /api/history/mpc` com downsampling | RF-703/802 (padrão) · §2.4 |
| `GET /api/operate/mpcs` (descoberta) | RF-701 · decisão A-7 |
| `GET /api/health/workers` (heartbeat na UI) | RNF-07 · decisão A-8 |
| Fanout do canal `events` no `/ws` | ADR-020 · decisão A-5 |
| Evento `script_recovered` no rearme do latch do Script | decisão A-4 (F5R-02b) · §7.2-2 |
| F-1: boot assíncrono do worker MPC (deploy **e** reload) + reescopo do lock global | spec F4 §4.1 (letra) · §6 · F5R-06 |
| Emenda spec F4 §4.2/§5.1 (§1.3-4): `building` publicado em qualquer modo | F5R-05 · §6.2 |
| Socket único de sessão no cliente + assinatura sob demanda por condição ativa | decisão A-6 · §7.1 · F5R-04 |
| Faixa anunciadora real (tabela de cessação em 4 famílias) | RF-705 · ADR-020 · decisão A-4 |
| Tela `/operacao/:flowId/:blockId` (faceplates, comutadores, trend+predição) | RF-701..704 · ADR-016 |
| Página `/eventos` (UI do RF-803) | RF-803 · decisão A-13 |
| Home como visão geral (lâmpadas de workers + flows) | RNF-07 · DESIGN §Layout · decisão A-10 |
| F-3: vetores-golden Python→TS para `mpcLogic` (escopo amplo, com detecção de drift dos dois lados) | dívida F4 §8.2 · decisão A-9 · F5R-13 |
| Débitos F4: handler global 422, 404 no `/operate`, `_empty_result` único | decisão A-9 · §4.3/§8 |

### 1.2 Fora da F5 — com destino registrado

| Item | Destino | Governança |
|---|---|---|
| `opc.values.<conn_id>` no `/ws` (trend de engenharia segue polling) | F6 ou nunca — só com consumidor real | decisão A-5; reaponta o registro F2 §1.2/F3 §1.2 (§1.3-5) |
| EU nas portas de Script/TFS (exige campo novo de schema) | F6 | emenda 2026-08-05 do roteiro F4 |
| Export/import, UI de certificados, suíte completa RNF-09 | F6 | PRD §8 |
| ACK de alarmes | fora da v1 | ADR-020 |
| `mpc_state_dimension` conservador (2 estados por par SOPDT degenerado) | fica como está — letra da spec F4 §2.2-7; aviso conservador | decisão A-9 |
| Protocolo `Commandable`/`Healthy` (5 `isinstance` em `supervisor_mpc.py`) | revisitar no 2º bloco comandável | decisão A-9 |
| Persistir predição/custo/status do MPC | nunca | ADR-016 |
| Teto de blocos MPC por flow (o volume §2.2-5 assume 1 por flow como caso de projeto) | registrado como limite de dimensionamento; teto formal se aparecer o caso real | F5R-25 |

> Nota (spec F6 §4.1): a linha "EU nas portas de Script/TFS (exige campo novo de schema) | F6" (§1.2) é cumprida por `docs/specs/F6-portabilidade-hardening.md` §4.1.

> Nota (spec F6 §7): a parte "suíte completa RNF-09" da linha "Export/import, UI de certificados, suíte completa RNF-09 | F6" (§1.2) é cumprida por `docs/specs/F6-portabilidade-hardening.md` §7.

### 1.3 Emendas a documentos anteriores (consolidação; F5R-26)

O PRD tem regra explícita de correção (`PRD.md` §nota inicial); specs anteriores recebem **nota de remissão** a esta spec no trecho alterado. Aplicação: **Etapa 0 do plano F5a**, antes de qualquer código.

| # | Documento · trecho | O que muda |
|---|---|---|
| 1 | PRD §7.1 (canal `mpc.state`) + changelog v1.3 + §4 + RF-703 | payload ganha `ts` e `prediction.ts` (§2.1); coluna Consumidores passa a "api(WS), recorder"; §4 ganha a hypertable `MpcSample`; RF-703 cita a fonte concreta (`mpc_samples`/`mpc_samples_1m`) |
| 2 | Spec F4 §5.2 ("Recorder ignora `mpc.state`") | revogada por §2.2-7; a proibição protegida (persistir predição) permanece |
| 3 | Spec F4 §6.1 (`/api/operate`: flow inexistente ⇒ 422) | 404, §4.3-2 |
| 4 | Spec F4 §4.2/§5.1 (`solver=building` só descrito no deploy; código publica só em AUTO) | `building` publicado sempre que o host não está pronto, em qualquer modo, precedendo `idle` (§6.2) |
| 5 | Spec F2 §1.2 / F3 §1.2 ("valores de tag → F5") | reapontado: F6 ou nunca, só com consumidor real (§1.2) |
| 6 | Spec F4 §5.3 (tabela de kinds) | linha nova `script_recovered` (info), §7.2-2 |

---

## 2. Dados & contratos

### 2.1 Emenda PRD §7.1 → v1.3: `ts` e `prediction.ts` no `mpc.state` (decisão A-2; F5R-01)

1. `MpcState` (`ottima_core/bus.py`) ganha `ts: datetime` (UTC), carimbado pelo flow-runtime no instante que gerou o quadro: nas execuções, o instante da fronteira de varredura (mesmo relógio do `ts` de `flow.status` — `task.last_scan_ts` já expõe esse instante); nas publicações imediatas (mudança de modo, SP/MV materializada, transição de solver — spec F4 §5.2), o instante da publicação. É a âncora do **recorder** (§2.3).
2. `MpcPrediction` ganha `ts: datetime` (UTC) — o instante da fronteira em que o solve **que produziu esta predição** foi despachado, carimbado pelo bloco no momento do `dispatch()` e devolvido junto com o resultado. `MpcState.ts` e `prediction.ts` divergem porque o resultado de um solve é aplicado e publicado na fronteira **seguinte** à do disparo (spec F4 §4.2; `blocks/mpc.py:277-283` faz `poll()` antes de `dispatch()`): usar `MpcState.ts` como âncora do overlay adiantaria o plano inteiro em 1×Ts_mpc. A âncora do **overlay** é `t_abs[k] = prediction.ts + prediction.t[k]`. Quadro sem predição (fora de AUTO) publica `prediction.ts` igual ao `ts` do quadro, com `t: []`.
3. Emenda submetida junto com esta spec — mesmo rito da emenda `ports` da F3 (PRD v1.2); escopo completo em §1.3-1. Nenhum consumidor **de produção** quebra (nada consome `mpc.state` antes da F5); quatro módulos de teste que constroem `MpcState` passam a informar `ts` (campo obrigatório de propósito — o recorder depende dele): `test_bus_events.py`, `test_ws_mpc.py`, `test_mpc_block.py`, `test_supervisor_mpc.py`. `contracts.gen.ts` regenera.

### 2.2 Hypertable `mpc_samples` (decisão A-1; migration `0003_mpc_samples`, SQL cru, três passos como a 0002)

1. Colunas: `ts timestamptz NOT NULL` · `flow_id bigint NOT NULL` · `block_id text NOT NULL` · `var_id text NOT NULL` · `v double precision NOT NULL` · `sp double precision NULL` · `auto boolean NOT NULL` (F5R-21: sem ela, SP em PV-tracking é indistinguível de SP comandado no histórico; o quadro sabe — `auto := modes.local_remote == "remote" AND modes.man_auto == "auto"`).
2. Hypertable com `chunk_time_interval => INTERVAL '1 day'` — mesmo intervalo de `samples` (`0002_timescale.py:23`), a tabela de natureza comparável; os 7 dias da 0002 são de `events`, de escrita esparsa (F5R-08). `add_retention_policy(..., INTERVAL '1 month')` (ADR-003).
3. Continuous aggregate `mpc_samples_1m`: `time_bucket('1 minute', ts)` com `avg(v) AS v`, `min(v) AS v_min`, `max(v) AS v_max`, `avg(sp) AS sp`, `bool_or(auto) AS auto` por `(flow_id, block_id, var_id)` — criada em `autocommit_block()` com `WITH NO DATA`, mais `add_continuous_aggregate_policy(start_offset => INTERVAL '1 hour', end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute')` e `add_retention_policy('mpc_samples_1m', INTERVAL '1 month')` — os três passos da 0002 (`0002_timescale.py:46-68`), não só a view (F5R-07).
4. Índice `(flow_id, block_id, var_id, ts DESC)`.
5. Volume — caso **típico** (F5R-25): 10 flows × ~10 vars × 2 Hz (Ts_mpc mín. = 0,5 s) = 200 linhas/s, ~2× `samples`; aceito. Teto de config: 14 vars × 10 flows = 280 linhas/s, com **1 bloco MPC por flow como caso de projeto** — mais de um MPC por flow multiplica linearmente e não tem teto declarado (registrado em §1.2).
6. Handle Core em `models/timeseries.py` (`TIMESERIES_METADATA`, fora do autogenerate — padrão F1).
7. O que **não** entra: `prediction`, `cost`, `status` — ADR-016 proíbe persistir predição; custo/status são deriváveis do log de eventos. A nota "Recorder ignora `mpc.state`" da spec F4 §5.2 fica **revogada** (§1.3-2); a proibição que ela protegia permanece em vigor por esta seção.

### 2.3 Recorder (F5R-12)

1. Terceiro listener no pipeline existente: `PatternListener("mpc.state.*")` ao lado de `opc.values.*` e `events` (`ottima_core.pubsub`).
2. `flow_id`/`block_id` saem do nome do canal; `ts`, `vars` e `auto` (derivado dos `modes`, §2.2-1) do payload; uma linha por `var_id` (`sp` NULL quando a variável não publica `sp` — só CV tem).
3. Buffer **próprio** (`_DropOldestBuffer`), com teto (`mpc_queue_max`, parametrizável como os demais) e contador de descarte somando em `dropped_total`, visível no `/health` do recorder ao lado de `buffered_samples`/`buffered_events` (`pipeline.py:95-127`); entra em `flush()` **depois** de `events` e `samples` (auditoria primeiro, spec F2 §6.3), no desmonte cruzado de `start()` e no `stop()` (`pipeline.py:146-206`). Mesmo lote de 1 s (`FLUSH_INTERVAL_S`) e mesmo backoff; payload malformado é logado e descartado sem derrubar nada (RNF-05). `MAX_BIND_PARAMS` acomoda as 7 colunas sem ajuste (~4.600 linhas/statement).
4. Grava em **todos os modos** — o canal publica inclusive fora de AUTO (spec F4 §5.2) e o operador precisa do passado do tracking antes de armar. Publicações imediatas geram linhas normais; duplicata eventual de `(ts, var)` é inócua (hypertable sem PK, como `samples`).

### 2.4 `GET /api/history/mpc` (router `history`; `require_operator`; padrões F1 §6.1; F5R-10/23)

1. Query: `flow_id` · `block_id` · `var_ids` (csv de ids de variável, deduplicado, teto **14** = 4 MV + 6 CV/Restr + 4 DV **[NOVA — implementação]**) · `start`/`end` (ISO-8601, naive = UTC), **opcionais com o mesmo default do RF-802** (`end = agora`, `start = end − 1 h`).
2. Downsampling idêntico ao RF-802 (`RAW_WINDOW_HOURS`/`MAX_WINDOW_DAYS` de `schemas/history.py`, sem número novo): janela ≤ 2 h ⇒ bruto; acima ⇒ `mpc_samples_1m`. Response `{mode: "raw"|"1m", start, end, series: [{var_id, t: [], v: [], sp: [], auto: [], v_min?, v_max?}]}` — mesma forma de `HistoryResponse`/`HistorySeries` (`schemas/history.py:13-26`), com `var_id` no lugar de `tag_id`, `sp` alinhado a `t` (`null` onde não havia), `auto` alinhado a `t` (bool; no `1m`, `bool_or` do bucket) e sem `q` (o estado publicado do MPC não carrega qualidade por variável). **Uma série por `var_id` pedido, sempre** — inclusive vazia (mesma disciplina de `routers/history.py:91`); `var_id` desconhecido ⇒ série vazia.
3. Reprovações: 422 pt-BR string única para `var_ids` vazio/malformado, `start ≥ end`, teto de vars excedido, janela > `MAX_WINDOW_DAYS` (31 d, coerente com a retenção); **404** para flow inexistente (§4.3-2) e 422 para `block_id` inexistente ou não-MPC. O handler global §4.3-1 cobre as de forma.

---

## 3. Semântica da predição (nota normativa; fato verificado em `mpc/worker.py::_extract_prediction`)

1. `t[] = [0, Ts_mpc, …, Np×Ts_mpc]` — **Np+1 pontos**, relativos a `prediction.ts` (§2.1-2).
2. `prediction.cv[i][k]` = valor previsto da linha `i` **no instante** `t[k]` (trajetória contínua; linhas = CVs na ordem do config, depois Restrições).
3. `prediction.mv[i] = [u_prev, u_0, …, u_{Np-1}]`: o índice 0 é a MV **que estava em vigor entrando no ciclo**; o índice `j ≥ 1` é a MV aplicada **no intervalo `[t[j-1], t[j])`** (convenção ZOH; F5R-17). Renderização: degrau **alinhado à esquerda** (uPlot `stepped`, `align: -1`) — o valor pertence ao intervalo que termina no seu ponto; `align: +1` deslocaria o plano inteiro em **um passo** (`Ts_mpc`) e é **proibido**.
4. Fora de AUTO a predição chega vazia (`t: []`, `prediction.ts = ts`) — o overlay some; histórico e faceplates seguem vivos.
5. A âncora do overlay é `prediction.ts` (§2.1-2), **nunca** o `ts` do quadro (F5R-01: o resultado publicado num quadro foi calculado na fronteira anterior).

---

## 4. API nova e correções de API

### 4.1 `GET /api/operate/mpcs` — descoberta (decisão A-7; router `operate`; `require_operator`)

1. Projeta, dos flows do **projeto ativo**, todos os nós `type=mpc` do `graph_json`:

```json
[{"flow_id": 59, "flow_name": "Coluna C-101", "flow_ts_seconds": 1.0,
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

2. Nome do campo de Ts segue o domínio: `flow_ts_seconds` (o campo da API é `ts_seconds`, `schemas/flows.py:20,38` — F5R-14); `Ts_mpc = multiplier × flow_ts_seconds`.
3. Só o que seletor e faceplates consomem — **sem** `pid`, `models`, pesos, TSS, `initial_value` (config de engenharia não vaza para a operação).
4. Estado rodando/parado **não** entra: é estado publicado (WS). Sem projeto ativo ⇒ lista vazia. Flow cujo `graph_json` não parseia ⇒ pulado com log, nunca 5xx (a descoberta é leitura de tela de operação; F5R-23).

### 4.2 `GET /api/health/workers` — heartbeat na UI (decisão A-8; router `health`; `require_operator` por rota, preservando o `/api/health` público)

1. A API consulta em paralelo os `/health` internos de opc-worker, flow-runtime e recorder com **`urllib.request` em `asyncio.to_thread`** (stdlib; mesmo mecanismo dos healthchecks do compose — três chamadas com timeout de 1 s não justificam um cliente HTTP novo na imagem; F5R-09), timeout 1 s cada. URLs em `Settings` (`OTTIMA_HEALTH_URL_OPC_WORKER` etc.); defaults cravados: `http://opc-worker:8001/health`, `http://flow-runtime:8002/health`, `http://recorder:8003/health` (`deploy/docker-compose.yml:60,88,114`) **[NOVA — implementação]**.
2. Response `{opc_worker: {up, ...corpo do /health}, flow_runtime: {...}, recorder: {...}}`; serviço fora do ar ou timeout ⇒ `{up: false}` — a rota responde **200 sempre** (agregador nunca propaga 5xx de terceiro).

### 4.3 Correções de contrato (decisão A-9; Etapa 0 do plano F5a)

1. **Handler global de `RequestValidationError`**: todo 422 de forma da API sai como `detail` **string única pt-BR** — inclusive enums Pydantic, que hoje vazam como lista FastAPI (dívida API-wide da F4). Os 422 de domínio já são string única; isto unifica os de forma.
2. **`/api/operate` com flow inexistente ⇒ 404** (`Flow não encontrado`), alinhado à convenção dos demais routers (emenda §1.3-3; `flows.py:55` já usa 404 com a mesma mensagem — usar constante única, sem terceira cópia da string). `block_id` inexistente/não-MPC e categoria/faixa erradas seguem 422.
3. **`_empty_result`** deduplicado: função única em módulo comum do pacote `mpc`, com a assinatura do host (kw-only, `wall_ms` obrigatório — chamador sintético sempre sabe o que mediu; F5R-27); chamadores do worker ajustados.

---

## 5. WebSocket `/ws` — canal `events` (decisão A-5; mesmo protocolo F3 §5.3/F4 §6.2)

1. Protocolo estende com chave booleana: `{"subscribe": {"events": true}}` / `{"unsubscribe": {"events": true}}` — canal único, sem ids **[NOVA — implementação]** (forma). No parser é um **ramo próprio** (flag `sub.events: bool`), não o par `(atributo, parse de lista)` das duas chaves de id (`ws.py:234-241`; F5R-15): valor que não seja o booleano `true` (`false`, número, lista) é logado e ignorado, como qualquer corpo inesperado, e **não** inverte a ação — `unsubscribe` é a única forma de desassinar.
2. Hub ganha um `ChannelListener("events")` ao lado dos dois `PatternListener`; fanout `{"channel": "events", "data": {…payload EventMessage…}}` aos sockets optantes.
3. Escopo F5 fechado: `flow_status` + `mpc_state` + `events`. `opc.values.*` **fora** (§1.2) — sem consumidor, seria código morto testado.

---

## 6. Runtime — F-1: boot assíncrono do worker e reescopo do lock (letra da spec F4 §4.1; F5R-05/06)

1. `host.start()` sai do caminho síncrono do lock global em **todos** os caminhos que o chamam: `_deploy` (`supervisor.py:293-294`) **e** `reconcile_mpc_hosts` do hot-swap (`supervisor_mpc.py:349-350`). Deploy/reload estagiam e retornam; o build do worker (spawn + montagem do-mpc) roda como task de fundo.
2. O flow varre desde a primeira fronteira. **Emenda a F4 §4.2/§5.1 (§1.3-4):** `status.solver = "building"` passa a ser publicado sempre que o host não estiver pronto, **em qualquer modo** — precedendo `idle`, que fica reservado a "worker pronto e ocioso fora de AUTO". Sem isso o valor segue inalcançável no deploy (`blocks/mpc.py:563-575` força `idle` fora de AUTO e deploy nasce LOCAL) e o operador não tem estado publicado que explique o `mpc_arm_failed {worker_not_ready}` da janela de build (PRODUCT princípio 2).
3. O **ciclo de vida do host deixa de ser serializado pelo lock global**: o lock passa a proteger só o mapa `_runtimes`; a espera de desmonte de host roda fora dele (lock por flow, ou desmonte destacado com o `MpcHost` já removido do mapa) **[NOVA — implementação]** (forma). Sem isso o bloqueio de até `_BOOT_TIMEOUT_S = 30 s` apenas **migra** do deploy para o stop — `MpcHost.stop()` espera boot em voo (`host.py:263-268`) e `supervisor_mpc.py:320-321` o chama com o lock na mão — e o reload continua bloqueando (F5R-06).
4. Invariantes preservadas: REMOTO antes de pronto ⇒ `mpc_arm_failed {reason: worker_not_ready}` (já existente nos **dois** eixos — `supervisor_mpc.py:109,151-152`); shed/hot-swap/watchdog de armar intocados; as 6 invariantes dos fix rounds da F4 valem byte a byte.
5. `stop` do próprio flow durante o build encerra o build **sem processo órfão**: `_stopped` primeiro, thread de spawn concluída, processo morto e juntado (`host.py:263-290`). Nota técnica normativa: `_spawn_and_wait_ready()` usa `asyncio.to_thread` (`host.py:342-344`), que **não é cancelável** — "cancelar o build" é sempre *marcar parado, deixar a thread terminar e então matar/juntar o processo*, nunca abortar antes de nascer (F5R-06).

---

## 7. Frontend (autoridade visual: PRODUCT.md/DESIGN.md; tudo pt-BR, GLOSSARY, sem emojis)

### 7.1 Socket único de sessão (decisão A-6; F5R-04/22)

1. Provider `CanalAoVivo` no `AppShell`: **um** WebSocket por aba, vivo enquanto houver sessão. Reconexão/backoff/1008 num lugar só. O ciclo de vida inteiro muda de casa, não só o hook (F5R-22): `abrirCanalAoVivo` e `AmbienteAoVivo` (`useFlowStatus.ts:191-289`) migram para o provider **com o harness de dublês que os testa** (o check de desmonte migra junto); `analisarMensagem` generaliza por canal (hoje filtra por `PREFIXO_CANAL`); `comandoAssinatura` vira gerador de **delta multi-canal**; `mesclarPorts` ("ports vazio preserva o anterior") sobrevive no redutor por canal — sem ela o canvas apaga a cada transição de estado.
2. Páginas registram interesse via `useAssinatura({flow_status: [id]} | {mpc_state: ["fid/bid"]})`; o provider agrega interesses, envia deltas de `subscribe`/`unsubscribe`, roteia mensagens por canal e reassina tudo após reconectar.
3. `events` sempre assinado (o banner é do shell). 1008 ⇒ `sessao_invalida`, sem reconexão (contrato F3).
4. `useFlowStatus(flowId)` mantém assinatura pública idêntica — o editor F3 não muda de forma; só a implementação passa a consumir do provider.
5. **Assinatura derivada de condição ativa (F5R-04):** quando `resolverAlarmes` acusa condição ativa de família "estado publicado" ou "contador publicado" (§7.2-1), o **provider** assina o `mpc_state`/`flow_status` daquela origem e a mantém até a condição cessar; então desassina. Em operação normal (sem condição ativa) o shell assina apenas `events`. É o provider quem faz isso, não a página: a faixa não pode depender da tela aberta. Custo registrado para não ser redescoberto no plano: assinar `flow_status` de todos os flows por precaução traria a tabela `ports` **inteira** de cada flow a cada varredura (spec F3 §4.2) — 10 flows a 2 Hz de payload de canvas em toda tela; e a fila por socket é de 8 mensagens com descarte do mais antigo (`ws.py:45-48,68-74`), seguro para condição derivada de estado (a próxima publicação re-deriva), mas hostil a fanout inflado.

### 7.2 Faixa anunciadora real (decisão A-4; RF-705, ADR-020; F5R-02/03/19)

1. **Tabela normativa de cessação** — a condição "ativa" é derivada no cliente, stateless, por **quatro famílias**. Os produtores **latcham** (emitem 1 vez e só rearmam na recuperação — `scheduler.py:232-238`, `blocks/mpc.py:313-314,412-443`, `blocks/script.py:95,113-116`), então cessação por "silêncio" seria falso *all clear*; cada família espelha o rearme do seu produtor:

| Família | Kinds | Ativa desde | Cessa quando |
|---|---|---|---|
| Par de eventos | `comm_failure`→`comm_restored` · `flow_failed`→`flow_deployed` · `script_timeout`\|`script_error`→`script_recovered` | evento de abertura | evento par com a **mesma `origin`** |
| Estado publicado | `mpc_solver_error` · `mpc_input_invalid` · `mpc_shed` | evento | `mpc.state` do bloco publica `solver ≠ "error"` / `input_valid = true` / `armed = true`, respectivamente |
| Contador publicado | `flow_overrun` · `mpc_overrun` | evento | **duas publicações consecutivas** do mesmo produtor com `overruns` inalterado (`flow.status.overruns` / `mpc.state.status.overruns`) — espelho literal do rearme do latch (`scheduler.py:232`, `blocks/mpc.py:313`) |
| Notificação pontual (TTL) | `mpc_arm_failed` | evento | **60 s** sem repetição do mesmo `kind`+`origin` **[NOVA — implementação]** — é tentativa discreta do operador, não condição vigente |

2. **`script_recovered`** (F5R-02b): kind novo em `bus.py` (severity `info`), publicado pelo runtime no ponto onde o latch do Script já rearma (`blocks/script.py:95` — o primeiro sucesso após `script_timeout`/`script_error`); linha nova na tabela de kinds da F4 §5.3 (§1.3-6). Quem latcha, anuncia o rearme.
3. **Bootstrap na montagem do shell (F5R-03)** — os eventos de cessação são `info`, então buscar só warning/alarm criaria alarmes-fantasma de até 1 mês no reload. Dois grupos:
   - **Famílias "par de eventos"** (condição derivada do último evento por origem, independente de severidade): `GET /api/events?origin=flow:<id>&limit=20` por flow do projeto ativo e `GET /api/events?origin=conn:<id>&limit=20` por conexão (≤10 + ≤5 chamadas, cache 60 s — mesmo padrão de `useLastFlowState`, F3 §6.1). A condição está ativa se o **último** evento da família naquela origem for o de abertura.

     > Emenda (execução da F5, aprovada pelo dono do plano em 2026-08-07): o grupo consulta **também** `GET /api/events?origin=flow:<id>/block:<id>&limit=20` para os blocos **Script** dos flows do projeto ativo, com teto de 20 blocos. Motivo: o Script publica com origem de bloco (`blocks/script.py:62`, `flow:<id>/block:<id>`) e a API filtra `origin` por igualdade exata (`routers/events.py:44`), então `origin=flow:<id>` nunca casa com `script_timeout`/`script_error`/`script_recovered`; como o Script latcha (publica uma vez e só reemite no rearme), um `script_error` ativo há mais de 2 h também escapava do segundo grupo — o alarme ficava invisível na faixa após um reload.
   - **Famílias "estado publicado", "contador publicado" e TTL**: `GET /api/events?severity=warning&start=<agora−2h>&limit=500` + idem `alarm` (o endpoint aceita uma severidade por chamada). Janela de 2 h: essas famílias cessam por estado vivo (primeiro quadro chega ≤ Ts_mpc após a assinatura §7.1-5) ou por decaimento de 60 s — evento mais velho já se resolveu.
   Depois disso, só WS. `resolverAlarmes(eventos, flowStatus, mpcStates, agora)` é função pura com check próprio (sem parâmetro de períodos: nenhuma família depende de Ts após F5R-02).
4. Renderização (DESIGN §Layout): colapsada em 1 linha quando vazio; com condições ativas, contagem por severidade + lista expansível (cor + ícone + texto — Regra do Canal Redundante); clique navega a `/eventos`. Sem ACK (ADR-020).

### 7.3 Navegação e Home (decisão A-10)

1. Nav do shell em dois grupos: **Operação · Eventos** | Conexões · Tags · Flows · Trend. Rotas novas: `/operacao`, `/operacao/:flowId/:blockId`, `/eventos`.
2. RBAC: operação e eventos são de **operador** (admin herda); telas de engenharia seguem como estão (mutação só admin, `useCanMutate`).
3. **Home = visão geral do console** (DESIGN §Layout): lâmpadas dos 3 workers (`GET /api/health/workers`, polling 5 s — lâmpada de estado, nunca só cor) + flows do projeto ativo com estado ("Último estado", padrão F3 §6.1) + atalho por flow para a operação quando houver MPC.

### 7.4 Tela `/operacao/:flowId/:blockId` (RF-701/702/704; ADR-016)

1. `/operacao` sem parâmetro: seletor via `GET /api/operate/mpcs`; um único MPC ⇒ redirect direto. O MPC aberto vive na URL (F5 do browser restaura a tela — sala de controle).
2. Assina `mpc_state` do bloco e `flow_status` do flow; MPC ausente na revalidação de `GET /api/operate/mpcs` (refetch ao montar/focar — flow excluído ou projeto trocado) ⇒ volta ao seletor com aviso.
3. **Faceplate principal (topo):** plaqueta `nome · flow`; **comutadores de posição** LOCAL/REMOTO e MAN/AUTO (MAN/AUTO só renderiza em REMOTO — ADR-010); lâmpadas: flow (`flow.status.state` + motivo), solver (`ok|building|overrun|error|idle` — **`building` é o estado de partida esperado do deploy**, §6.2, com os comutadores desabilitados e rótulo do motivo enquanto durar — Regra do Canal Redundante), `input_valid`; contadores `overruns` e `last_solve_ms` em mono tabular.
4. **Comando pendente-até-confirmar** (Regra do Estado Publicado — visual): 1 gesto, sem diálogo; ao comandar, posição/valor comandado em fantasma + outline azul até o `mpc.state` seguinte confirmar; sem materialização em **3×Ts_mpc (mín. 5 s)** ⇒ reverte ao publicado **[NOVA — implementação]** — estritamente **maior** que a janela de confirmação do runtime (`CONFIRM_MISSES_LIMIT = 2` ticks, `mpc_arming.py:34`), para que o desfecho publicado (confirmação ou `mpc_arm_failed`) sempre chegue antes do timeout do cliente (F5R-18).
5. **Faceplates de variável (base; RF-702):** um por MV/CV/Restrição/DV, cada um com **barra vertical** com escala demarcada (`limits`/`sp_limits`/`range` — DESIGN §Shapes, convenção intocável), PV grande em mono tabular + EU (Regra do Número Tabular).
   - CV: entrada de SP **habilitada só em AUTO** (fora, SP rastreado exibido dessaturado — PV-tracking da decisão A-4 da F4); clamp client-side em `sp_limits` (espelho leve; servidor é a barreira).
   - MV: entrada manual **só em REMOTO+MAN**; clamp em `limits`; fora do modo, campo desabilitado com o valor publicado.
   - Restrição: faixa low/high marcada na barra; somente leitura. DV: somente leitura.
   - Toda escrita segue o pendente-até-confirmar do item 4 e flui UI → REST `/api/operate` → `flow.commands` → runtime → estado republicado (RF-704; auditoria é do runtime, F4 §4.8).
6. **Trend central (uPlot re-vestido; RF-703; DESIGN "tinta que ainda não secou"):**
   - Histórico: `GET /api/history/mpc` — janelas 15 min · 30 min · 2 h · 8 h (default **30 min**), polling 5 s.
   - **Borda viva:** cada `mpc.state` (ts + vars) faz append nas séries — o "agora" nunca espera o poll; o poll re-sincroniza **[NOVA — implementação]**.
   - Overlay de predição do último quadro: âncora **`prediction.ts`** (§3.5); CVs/Restrições tracejadas no **mesmo matiz mais claro** com fade ao horizonte; **MVs como degraus fantasma `stepped align: -1`** (§3.3); linha-cursor "agora"; pena de SP **no matiz da própria CV, pontilhada** (`[2, 4]`) — o Azul Industrial nunca desenha dado (A Regra do Azul Único, DESIGN §Colors): pena azul sem entrada na legenda é linha órfã na tela do operador **[EMENDA 2026-08-16 — defeito reportado em operação]** —, **dessaturada nos trechos com `auto = false`** (SP em PV-tracking não é SP comandado — §2.2-1, F5R-21); Restrição com banda low/high sombreada no Poço. Três estilos, um matiz por variável: sólido = PV medido, pontilhado = SP comandado, tracejado = futuro.
   - Defaults (decisão A-11, revisão F5R-16; **[EMENDA 2026-08-16 — pedido do operador]**): CVs (**só PV**) ligadas **até o teto de 8 penas**, na ordem do config; Restrições ligadas como banda low/high com a pena de PV contando no teto; MVs, DVs **e a pena de SP de cada CV** são **opt-in** pela legenda clicável — o SP não é mais um traço que a pena da CV arrasta junto, é uma LINHA própria da legenda (mesma cor da CV, faixa pontilhada, custo de 1 pena no teto, sem editor de faixa: desenha na escala da CV); acima de 8 penas o excedente nasce desligado e a legenda o indica. Eixo futuro dimensionado por Np×Ts_mpc.
   - Fora de AUTO: overlay some (§3.4); histórico e barra "agora" seguem.

### 7.5 Página `/eventos` (decisão A-13; RF-803)

1. Tabela ts desc: severidade (lâmpada + texto), origem, mensagem, payload expansível (`<details>`), filtros severidade/origem/período (`GET /api/events`). **Filtro de origem como select** (F5R-24), populado das origens conhecidas (`GET /api/flows` + `GET /api/operate/mpcs` + `GET /api/connections`, mais as origens distintas presentes no resultado carregado) — a API filtra por igualdade exata (`routers/events.py:43`), então a UI nunca pede texto livre.
2. Sem filtro de período ("ao vivo"): eventos novos do WS que casem com os filtros ativos entram no topo com marca de recém-chegado; filtro de período ativo ⇒ consulta histórica pura, sem prepend.

### 7.6 F-3 — vetores-golden Python→TS (decisão A-9; F5R-13)

1. `uv run python -m ottima_core.mpc_golden_export` (novo) emite JSON de casos, commitado em `frontend/src/features/flows/mpc/mpcLogic.golden.json` **[NOVA — implementação]** (caminho).
2. Escopo do golden: `derive_horizons` (Ts_mpc/Np/Nc), dimensão de estados, tetos 1..4/1..6/0..4, limiares Np<2/Np>120/Np>60/dim>120, banker's rounding, **e um caso por regra de `_check_mpc_caps/_matrix/_numbers/_horizons` com o veredito** (regra que reprovou; aprovado/reprovado; warning ou erro) — não o texto pt-BR, que é livre por convenção. Cobre também o espelho de `validarConfigMpc`/`paramsValidosParaKind` (`mpcLogic.ts:283-442`), não só as funções numéricas.
3. `mpcLogic.check.ts` assere igualdade campo a campo contra o golden — divergência do lado TS vira teste vermelho.
4. O determinismo do export não basta (não detecta mudança no Python): um teste em `ottima-core` compara a saída de `mpc_golden_export` com o JSON **commitado** e falha se divergir ("regenere o golden") — mudança no Python também vira vermelho, dos dois lados do espelho.
5. A F5 não adiciona regra espelhada nova (validação de SP/MV é servidor + runtime); o golden congela as existentes.

---

## 8. Débitos herdados — veredito (decisão A-9)

| # | Débito (relatório gate F4 §8.2) | Veredito F5 | Onde |
|---|---|---|---|
| F-1 | Boot de worker síncrono sob o lock do supervisor (deploy **e** reload; stop esperava build em voo com o lock) | **Fecha na F5** nos três caminhos de comando (`_deploy`, `_stop`, `reconcile_mpc_hosts`); ver o débito residual abaixo | §6 · plano F5a |
| F-3 | Regras client-side espelhadas à mão | **Fecha na F5** (golden amplo, drift bidirecional) | §7.6 · plano F5b |
| — | `_empty_result` duplicado (assinaturas divergentes) | **Fecha na F5** (Etapa 0; assinatura kw-only do host) | §4.3-3 |
| — | 422 de enum como lista FastAPI | **Fecha na F5** (handler global) | §4.3-1 |
| — | `/api/operate` 422 vs 404 | **Fecha na F5** (unifica 404) | §4.3-2 · §1.3-3 |
| — | `prediction_mv` semântica por índice | **Confirmada e fixada** (nota normativa) | §3 |
| — | `solver="building"` inalcançável | **Fecha na F5** (emenda §1.3-4: publicado em qualquer modo) | §6.2 |
| — | `mpc_state_dimension` conservador | Fica (letra da spec F4 §2.2-7) | §1.2 |
| — | Protocolo `Commandable`/`Healthy` | Fica (revisitar no 2º bloco comandável) | §1.2 |
| — | EU nas portas de Script/TFS | Diferido F6 (schema novo) | §1.2 |
| — | `shutdown_mpc` síncrono sob o lock em `_force_stop` (`on_project_activated`), `_pass`/`_reconcile_flow` e `_handback_failed_mpc` | Fica (herdado da F4, **não** é regressão da F5): se o host estiver em build, esses caminhos ainda seguram o lock por até `_BOOT_TIMEOUT_S = 30 s`. O reescopo de §6-3 vale para os três caminhos de comando (deploy/stop/reload), não para estes | §6.3 · achado da revisão de fechamento da F5 |

> Nota (spec F6 §5.2): a linha `shutdown_mpc` síncrono sob o lock (§8) fecha em `docs/specs/F6-portabilidade-hardening.md` §5.2 — com correção de registro: são três contextos reais, e o quarto chamador que o ledger da F5 não registrou é `_deploy` sobre `old_runtime` (`supervisor.py:338`).

---

## 9. Testes e gate E2E

### 9.1 Unit/integração (padrões F1 §9 · F2 §11.1 · F3 §7.1 · F4 §9.1)

- **ottima-core:** `MpcState.ts`/`MpcPrediction.ts` no contrato · golden: export determinístico **e** export × JSON commitado iguais (§7.6-4).
- **recorder:** linhas corretas de `mpc.state` (uma por var; `sp` NULL fora de CV; `auto` derivado dos modos; flow/block do canal) · buffer próprio com teto/descarte no `/health` · ordem de flush (events → samples → mpc_samples) · payload malformado ignorado sem derrubar o pipeline.
- **api:** `/api/history/mpc` (raw×1m na fronteira de 2 h, defaults de janela, 422s, teto 14, janela >31 d, `var_id` desconhecido ⇒ série vazia, 404 de flow, RBAC) · `/api/operate/mpcs` (projeção sem `pid`/`models`, só projeto ativo, `graph_json` inválido pulado com log, RBAC) · `/api/health/workers` (agrega, down ⇒ `up:false`, timeout, sempre 200) · handler global (enum inválido ⇒ string única pt-BR) · 404 de flow no `/operate`.
- **flow-runtime (clock controlado):** F-1 — deploy com build pesado não bloqueia `stop`/`deploy` de outro flow; **`reload` de flow com MPC pesado não bloqueia comando de outro flow**; **`stop` de flow em build não bloqueia `deploy` de outro flow** (latências medidas — é a inversão que o E2E não cobre); nenhum worker órfão após stop durante build (`stats()["alive"]` falso, processo juntado) · `building` publicado em **qualquer** modo até pronto, transição building→idle (LOCAL) e building→ok (AUTO) · `ts` presente e crescente no `mpc.state` · **em regime, `prediction.ts == ts − Ts_mpc` e `prediction.mv[i][0] == vars.<mv_id>.v` do quadro anterior** (F5R-01 — sem este teste o overlay deslocado é invisível) · `script_recovered` publicado no primeiro sucesso após timeout/erro, uma vez só.
- **ws:** fanout `events` · os 3 tipos de assinatura no mesmo socket · unsubscribe para · `{"subscribe": {"events": false}}` é no-op logado (§5.1-1).
- **frontend `test:unit`:** `resolverAlarmes` (4 famílias; par por origem; contador com `overruns` inalterado ×2; TTL 60 s; bootstrap dos dois grupos; condição ativa sem estado da origem ⇒ ativa, nunca silenciosa) · máquina do canal único (agregação de interesses, deltas, reconexão reassina, 1008, **assinatura sob demanda: condição ativa gera `subscribe` da origem, cessação gera `unsubscribe`**, `mesclarPorts` preservado no redutor) · golden `mpcLogic` (§7.6) · redutor pendente-até-confirmar (materializa, ignora, expira em 3×Ts_mpc) · clamps de faceplate · montagem de séries do trend (append da borda viva, âncora `prediction.ts`, `align:-1`, quadro com `t: []` remove o overlay sem apagar as séries, SP dessaturada onde `auto=false`).

### 9.2 Gate E2E — 3 camadas (protocolo F2 §11.2/F3 §7.2/F4 §9.2)

**L1** — `deploy/smoke.sh`: inalterado + `GET /api/health/workers` com os 3 `up: true` + políticas de retenção de `mpc_samples` **e** `mpc_samples_1m` presentes em `timescaledb_information.jobs` (o smoke já verifica "retenção ativa"; F5R-07).

**L2** — `tests/e2e`, cenários novos (malha MPC↔TFS via API real; opcsim):

| Cenário | Prova |
|---|---|
| E2E-F5-01 | flow MPC rodando ⇒ `mpc_samples` ganha linhas na cadência Ts_mpc; **grava também em LOCAL** (tracking), com `auto=false`; `sp` NULL fora de CV; `ts` do payload = `ts` gravado |
| E2E-F5-02 | `/api/history/mpc`: bruto ≤ 2 h e `1m` acima (CAgg materializada — prova a política de refresh); teto/422/404; RBAC |
| E2E-F5-03 | `/api/operate/mpcs` projeta o config (sem `pid`/`models`); flow inexistente no `/operate` ⇒ **404** |
| E2E-F5-04 | WS `events`: subscribe ⇒ evento publicado chega; unsubscribe ⇒ para |
| E2E-F5-05 | **F-1:** deploy de flow MPC pesado não bloqueia `stop` de outro flow (latência medida); **`building` observável em `mpc.state` no deploy (em LOCAL), antes de `idle`**; armar na janela de build ⇒ `mpc_arm_failed {worker_not_ready}` |
| E2E-F5-06 | `ts` e `prediction.ts` presentes; `ts` monotônico; em regime `prediction.ts == ts − Ts_mpc` |
| E2E-F5-07 | handler global: enum inválido em `/operate/mode` ⇒ 422 string única pt-BR |

**Regressão:** os 34 cenários L2 F1-F4 verdes na mesma rodada; Playwright F1 serializado após a L2.

**L3** — roteiro browser `docs/plans/tests-e2e-f5.md` (**executado pelo controlador** — a tool `browser` é bloqueada a subagentes; herda a seção de armadilhas do roteiro F4 §2):

| ID | Passo |
|---|---|
| B-F5-01 | Login operador → nav Operação → seletor → tela do MPC |
| B-F5-02 | Faceplates: barras verticais com escala, EU, limites/faixas; valores mono tabular; lâmpada `building` no deploy recém-feito |
| B-F5-03 | Armar LOCAL→REMOTO(MAN)→AUTO pela UI; pendente (fantasma + outline azul) → confirmado pelo estado publicado |
| B-F5-04 | SP em AUTO e MV em MAN (clamp, materialização, auditoria em `/eventos`); entradas desabilitadas fora do modo |
| B-F5-05 | Trend: histórico sólido → linha-agora → predição tracejada **partindo do agora, sem degrau na emenda** (âncora `prediction.ts`); MVs degraus fantasma; SP dessaturada no trecho pré-AUTO; janelas; legenda alterna MVs |
| B-F5-06 | Congelar watchdog do opcsim ⇒ alarme na faixa em **qualquer** tela; restaurar + re-deploy ⇒ cessa |
| B-F5-07 | `/eventos`: filtros (origem por select); prepend ao vivo com marca de recém-chegado |
| B-F5-08 | Home: lâmpadas dos workers; parar um serviço ⇒ lâmpada down (compose stop/start do recorder) |
| B-F5-09 | RBAC: operador opera (modos/SP/MV) e não vê mutações de engenharia |

### 9.3 Precondições de ambiente

Herdam o protocolo F3/F4 (CLAUDE.md §Comandos): L2 e Playwright serializados; credenciais sempre inline; `down -v` só com autorização explícita + dump prévio; sempre os dois arquivos compose.

---

## 10. Aderência ao aceite F5 (PRD §8)

| Critério | Evidência na spec |
|---|---|
| Operador conduz LOCAL/REMOTO/MAN/AUTO | §7.4-3/4 (comutadores + pendente-até-confirmar, `building` visível na janela de build) · B-F5-03 · E2E-F4-03/07/08 (regressão) |
| Escreve SP/MV | §7.4-5 · B-F5-04 |
| **Predição sobreposta ao histórico** | §2 (mpc_samples + ts/prediction.ts) · §3 (semântica + âncora) · §7.4-6 (overlay) · **teste de âncora §9.1** (`prediction.ts == ts − Ts_mpc`; sem ele o overlay deslocado passaria visualmente) · E2E-F5-06 · B-F5-05 |
| Eventos/banner | §7.2 (4 famílias espelhando o latch dos produtores; bootstrap por origem) · §7.5 · B-F5-06/07 |
| Auditoria | runtime F4 §4.8 (já audita) · `/eventos` exibe (B-F5-04/07) |

---

## Anexo A — Decisões do brainstorm (2026-08-06)

| # | Lacuna | Decisão aprovada |
|---|---|---|
| A-1 | RF-703 pede histórico "via Timescale", mas só tags R têm passado em `samples` (CV entra pela porta, SP é volátil, MV escreve em tag W) | **Hypertable `mpc_samples`** gravada pelo recorder assinando `mpc.state.*`; cobre todas as variáveis + SP (+ coluna `auto`, F5R-21); revoga o "Recorder ignora `mpc.state`" da F4 §5.2 (a proibição de persistir predição permanece) |
| A-2 | `mpc.state` não tem instante; recorder e overlay precisam de âncora | **Emenda PRD §7.1 → v1.3:** `mpc.state` ganha `ts` (âncora do recorder) e, pela revisão F5R-01, `prediction.ts` (âncora do overlay — o resultado publicado foi calculado na fronteira anterior) |
| A-3 | Semântica por índice de `prediction.mv` estava "a confirmar" | **Confirmada no código** (`_extract_prediction`): `mv[0]` = u_prev vigente; `mv[j]` vale no intervalo `[t[j-1], t[j])` ⇒ degrau alinhado à esquerda (`stepped align:-1`), fixado como norma (§3) |
| A-4 | "Alarme ativo" sem evento de cessação para a maioria dos kinds | **Tabela normativa de cessação derivada no cliente**, em **4 famílias que espelham o latch dos produtores** (par de eventos — incl. `script_recovered` novo —, estado publicado, contador publicado, TTL 60 s só para `mpc_arm_failed`); bootstrap por origem + janela 2 h; `resolverAlarmes` pura |
| A-5 | Quais canais entram no `/ws` na F5 | **Só `events`**; `opc.values` fica fora (sem consumidor real — trend de engenharia segue polling); registro F2/F3 reapontado |
| A-6 | Topologia de socket no cliente (banner é de toda tela) | **Socket único de sessão no AppShell** + registro de assinaturas por página + **assinatura sob demanda dirigida por condição ativa** (F5R-04); `useFlowStatus` preserva assinatura pública |
| A-7 | Descoberta dos MPCs para o seletor | **`GET /api/operate/mpcs`**: projeção server-side do config (sem `pid`/`models`); nada de N+1 nem parsing de grafo no cliente |
| A-8 | RNF-07 "heartbeat visível na UI" com `/health` internos inalcançáveis do browser | **`GET /api/health/workers`**: API agrega os 3 `/health` via `urllib.request` em `asyncio.to_thread` (stdlib, F5R-09); lâmpadas na Home; sempre 200 |
| A-9 | Dívidas F4 §8.2 sem veredito | **F-1 (ampliado a reload+stop), F-3 (golden amplo), `_empty_result`, handler 422 global e unificação 404 entram na F5**; dimensão conservadora, protocolo de capacidade e EU Script/TFS ficam (§8) |
| A-10 | Navegação/rotas da operação | **Grupo Operação** (`/operacao/:flowId/:blockId` + `/eventos`) antes de Engenharia; MPC na URL; **Home vira visão geral** com lâmpadas de workers |
| A-11 | O que o trend de operação mostra por default | **CVs (PV) ligadas até o teto de 8 penas; MVs, DVs e a pena de SP de cada CV opt-in** pela legenda; janela default 30 min (15 min/30 min/2 h/8 h) — SP saiu do default e virou pena própria por **emenda 2026-08-16** (§7.4-6) |
| A-12 | Estrutura documental da execução | **1 spec + 2 planos**: F5a dados & serviços · F5b tela de operação (fronteira = contratos gerados, padrão F4) |
| A-13 | Atualização da página `/eventos` | **REST com filtros + prepend ao vivo do WS** quando sem filtro de período; marca de recém-chegado; origem por select (F5R-24) |

## Anexo B — Revisão aplicada (2026-08-06)

Revisão por agente RFC (modo review): `docs/reports/review/review-spec-f5-operacao-20260806.md` — veredito **APPROVE WITH CHANGES**, 27 achados, todos aplicados nesta versão. Verificações positivas registradas no apêndice do relatório (F5R-A: `mpc_samples` × ADR-016 sustentado; F5R-B: emendas com rito; ~25 claims de código conferidos).

| Achados | Aplicação |
|---|---|
| F5R-01 (âncora da predição) | §2.1-2 · §3.1/3.5 · §7.4-6 · testes §9.1/E2E-F5-06 |
| F5R-02 (latch × TTL) + escolha **(b)** `script_recovered` | §7.2-1/2 · §1.3-6 · §9.1 |
| F5R-03 (bootstrap sem cessações) | §7.2-3 (dois grupos, por origem + janela 2 h) |
| F5R-04 (estado publicado sem assinatura) | §7.1-5 (assinatura sob demanda) |
| F5R-05 (`building` inalcançável) | §6.2 · §1.3-4 · §7.4-3 · E2E-F5-05 |
| F5R-06 (head-of-line no reload/stop) | §6.1/6.3/6.5 · §9.1 (3 latências + órfão) |
| F5R-07..16 (Important) | §2.2-3 CAgg 3 passos · §2.2-2 chunk 1 d · §4.2-1 urllib stdlib (escolha) · §2.4-2 forma `HistoryResponse` · §1.3-1 escopo da emenda · §2.3-3 recorder enumerado · §7.6 golden amplo + drift Python (escolha) · §4.1-2 `flow_ts_seconds` · §5.1-1 ramo próprio no parser · §7.4-6 teto 8 penas |
| F5R-17..27 (Minor) | §3.3 intervalo `[t,t)` e passo inteiro · §7.4-4 janela 3×Ts_mpc · TTL sem fallback (família reduzida) · §2.1-3 testes que constroem `MpcState` · §2.2-1 coluna `auto` (escolha) · §7.1-1 raio real do refactor · §2.4-3/§4.1-4 validações · §7.5-1 origem por select · §2.2-5 caso típico vs teto · §1.3 emendas consolidadas · §4.3-3 assinatura kw-only |
