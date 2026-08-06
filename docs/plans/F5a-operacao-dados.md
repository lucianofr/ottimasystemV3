# Plano F5a — Operação: dados & serviços

> **Para executores agênticos:** execução tarefa a tarefa com subagente por tarefa + revisão independente (padrão F3/F4, skill subagent-driven-development; ledger em `.superpowers/sdd/F5a-operacao-dados/progress.md`). Checkboxes das tabelas rastreiam conclusão. Cada tarefa cita a seção da spec, a decisão A-n e o achado F5R-n que implementa.

**Fase:** F5 (PRD §8) · plano 1 de 2 (decisão A-12 da spec) · 2026-08-06
**Executa:** `docs/specs/F5-operacao.md` §1.3, §2, §4, §5, §6 e §9.1/§9.2 (backend, L1, L2) — §3 é nota normativa consumida pelas tarefas; a tela (§7) é do plano F5b
**Fontes normativas:** `docs/PRD.md` v1.2→v1.3 · `docs/adr/ADR-001…024` (prevalecem) · `docs/GLOSSARY.md` · specs F1/F2/F3/F4 (com as emendas §1.3 aplicadas na Etapa 0) · spec F5
**Objetivo:** `mpc.state` com `ts` e `prediction.ts` ponta a ponta; hypertable `mpc_samples` gravada pelo recorder em todos os modos; `GET /api/history/mpc`, `GET /api/operate/mpcs`, `GET /api/health/workers`; canal `events` no `/ws`; `script_recovered`; F-1 fechado (boot assíncrono + lock reescopado); débitos de contrato F4 fechados; E2E-F5-01..07 verdes.
**Stack:** NENHUMA dependência nova. O agregador de health usa `urllib.request` da stdlib (decisão F5R-09 — `httpx` está só no grupo dev e a imagem builda `--no-dev`, `deploy/Dockerfile.python:8`).

## Regras globais (valem para todas as tarefas)

1. **Governança:** ADR > PRD > spec > plano. Worktree único da fase `ottimaSystemV3-f5`, branch `f5-operacao` (os dois planos na mesma branch); Conventional Commits pt-BR; identificadores em inglês no backend, strings pt-BR, sem emojis; teto 800 linhas/arquivo (típico 200-400).
2. **Ciclo de conclusão de etapa:** bateria da etapa **toda verde** (`uv run pytest` + `uv run ruff check . && uv run ruff format --check .`). Vermelho ⇒ corrigir ⇒ re-executar ⇒ repetir até verde.
3. **TDD estrito com prova RED** registrada no ledger em toda lógica nova (CLAUDE.md §Testes): teste vermelho antes da implementação, verde depois, refactor com suíte verde.
4. **Caminho absoluto em toda edição de subagente** (armadilha nº1 do ledger F3).
5. **Lacuna real de spec/schema ⇒ PARAR e perguntar** (CLAUDE.md item 4); nunca inventar contrato.
6. **Credenciais/env sempre inline de `deploy/.env`** — nunca `export` persistente (`OTTIMA_DATABASE_URL` exportada quebra os testcontainers da suíte unitária).
7. **DoD do plano:** §Aderência ao final; o aceite da FASE fecha só no F5b (gate + roteiro `docs/plans/tests-e2e-f5.md`).

## Contratos verbatim (PRD §7.1 v1.3 — vigente após a tarefa 0.1)

| Canal | Produtor | Consumidores | Payload (JSON) |
|---|---|---|---|
| `mpc.state.<flow_id>.<block_id>` | flow-runtime | api(WS), recorder | {ts, modes, status, vars, cost, prediction{ts, t[], cv[][], mv[][]}} |
| `events` | todos | api(WS→banner), gravação | {ts, severity, origin, message, payload} |
| `flow.commands` | api | flow-runtime | {flow_id, cmd, args, user, ts} |

Semântica de `ts`/`prediction.ts`: spec F5 §2.1. Semântica da predição (âncora, ZOH, `mv[0]`=u_prev): spec F5 §3 — nota normativa; toda tarefa que toca predição a obedece. Nenhum canal novo (ADR-002; `events` já existe — a F5 só o leva ao `/ws`).

## Interfaces produzidas (consumidas pelo F5b — assinaturas exatas)

```python
# ottima_core.bus (tarefa 1.1)
class MpcPrediction(BaseModel): ts: datetime; t: list[float]; cv: list[list[float]]; mv: list[list[float]]
class MpcState(BaseModel): ts: datetime; ...   # demais campos F4 §5.1 intactos
KIND_SCRIPT_RECOVERED = "script_recovered"     # severity "info" (spec F5 §7.2-2)

# REST novo (OpenAPI regenerado — o F5b consome via npm run generate:api)
GET /api/history/mpc?flow_id&block_id&var_ids&start&end   # §2.4; require_operator
  -> {mode: "raw"|"1m", start, end, series: [{var_id, t[], v[], sp[], auto[], v_min?[], v_max?[]}]}
GET /api/operate/mpcs                                     # §4.1 payload verbatim; require_operator
GET /api/health/workers                                   # §4.2; require_operator; sempre 200
  -> {opc_worker: {up, ...}, flow_runtime: {up, ...}, recorder: {up, ...}}

# WS /ws (tarefa 3.4; protocolo F3 §5.3/F4 §6.2 estendido)
{"subscribe": {"events": true}} / {"unsubscribe": {"events": true}}
fanout: {"channel": "events", "data": {…payload EventMessage…}}
```

---

## Etapa 0 — Emendas documentais e débitos de contrato (spec §1.3 e §4.3; antes de qualquer código de feature)

| # | Tarefa | Arquivos | Verificar | Débito/Gov. |
|---|---|---|---|---|
| 0.1 | **Emenda PRD → v1.3** (§1.3-1): §7.1 linha `mpc.state` ganha `ts` e `prediction.ts` no payload e consumidores "api(WS), recorder"; §4 ganha a hypertable `MpcSample` (colunas §2.2-1, retenção 1 mês, CAgg `mpc_samples_1m`); RF-703 cita a fonte concreta (`mpc_samples`/`mpc_samples_1m`); changelog v1.3 datado. Mesmo rito da emenda `ports` da F3 | `docs/PRD.md` | grep `prediction.ts`, `MpcSample`, `v1.3` no PRD; nenhuma outra linha do §7.1 alterada | decisão A-2 · F5R-01/11/26 |
| 0.2 | **Notas de remissão nas specs anteriores** (§1.3-2..6; specs não são reescritas, recebem nota no trecho alterado apontando a spec F5): F4 §5.2 "Recorder ignora `mpc.state`" → revogado por F5 §2.2-7 (proibição de persistir predição permanece); F4 §6.1 flow inexistente → 404 (F5 §4.3-2); F4 §4.2/§5.1 → `building` publicado em qualquer modo (F5 §6.2); F4 §5.3 → linha nova `script_recovered` (info, F5 §7.2-2); F2 §1.2 e F3 §1.2 "valores de tag → F5" → reapontado F6-ou-nunca (F5 §1.2) | `docs/specs/F4-mpc.md` · `docs/specs/F2-aquisicao.md` · `docs/specs/F3-motor-canvas.md` | grep "spec F5" acha as 5 notas nos trechos certos; diff não altera nenhuma frase normativa fora das notas | §1.3 · F5R-26 |
| 0.3 | **Handler global de `RequestValidationError`** (§4.3-1): todo 422 de forma sai `{"detail": "<string única pt-BR>"}` — primeiro erro da lista, formato `"<campo>: <motivo pt-BR>"`; enums Pydantic (que hoje vazam como lista FastAPI) inclusos. Registrar no app; varrer os testes de API que asseriam o formato-lista e ajustá-los | `services/api/src/ottima_api/app.py` · `services/api/tests/test_validation_handler.py` (novo) · testes existentes que asserem lista | RED: `POST /api/operate/{fid}/{bid}/mode` com `axis` inválido ⇒ 422 com `detail` `isinstance(str)` pt-BR; depois GREEN; `uv run pytest services/api` verde | decisão A-9 · dívida F4 |
| 0.4 | **`/api/operate` com flow inexistente ⇒ 404** (§4.3-2; emenda §1.3-3): constante única `MSG_FLOW_NAO_ENCONTRADO` em `services/api/src/ottima_api/messages.py` (novo, só a constante); `routers/flows.py:55` e `routers/operate.py:45,71-72` importam dela (hoje: 2 cópias da string, `/operate` responde 422); flow inexistente no `/operate` vira **404**; `block_id` inexistente/não-MPC e categoria/faixa erradas seguem 422 | `services/api/src/ottima_api/messages.py` (novo) · `routers/operate.py` · `routers/flows.py` · `services/api/tests/test_operate.py` | RED: flow inexistente espera 404 nos 3 endpoints do `/operate`; grep da string literal só acha `messages.py` | decisão A-9 · F5R-A |
| 0.5 | **`empty_result` único** (§4.3-3; F5R-27): função única `def empty_result(*, status: str, detail: str = "", wall_ms: float) -> SolveResult` em `mpc/worker.py` (dono de `SolveResult`; módulo comum — o host já importa `worker_main` de lá), assinatura kw-only do host com `wall_ms` obrigatório (chamador sintético sempre sabe o que mediu); apagar `_empty_result` do `host.py:128-140` e a versão posicional do `worker.py:238-247`; chamadores ajustados | `services/flow-runtime/src/ottima_flow_runtime/mpc/worker.py` · `mpc/host.py` · testes existentes de worker/host | grep `_empty_result` não acha nada; `empty_result` só em `worker.py` + usos; `uv run pytest services/flow-runtime` verde | decisão A-9 · F5R-27 |

**Conclusão:** `uv run pytest` (workspace) + ruff verdes. Emendas 0.1/0.2 são só documentos; 0.3-0.5 não mudam comportamento além do contratado.

---

## Etapa 1 — Contratos: `ts` e `prediction.ts` (spec §2.1; F5R-01)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 1.1 | **`bus.py`**: `MpcState.ts: datetime` (UTC) e `MpcPrediction.ts: datetime` **obrigatórios** (de propósito — o recorder depende deles, §2.1-3); `KIND_SCRIPT_RECOVERED = "script_recovered"` na tabela de kinds (`bus.py:125-162`), severity `info`; os 4 módulos de teste que constroem `MpcState` passam a informar `ts`: `packages/ottima-core/tests/test_bus_events.py`, `services/api/tests/test_ws_mpc.py`, `services/flow-runtime/tests/test_mpc_block.py`, `services/flow-runtime/tests/test_supervisor_mpc.py` | `packages/ottima-core/src/ottima_core/bus.py` · os 4 módulos de teste | RED: round-trip JSON do payload §5.1-v1.3 com `ts`/`prediction.ts`; quadro fora de AUTO serializa `prediction {ts == MpcState.ts, t: []}`; kind novo na tabela | RF-625 · decisão A-2 · §2.1 |
| 1.2 | **Carimbo no runtime**: `blocks/mpc.py` — `ts` do quadro: nas execuções, o instante da fronteira de varredura (mesmo relógio do `ts` de `flow.status` — `task.last_scan_ts` do scheduler já expõe esse instante); nas publicações imediatas (mudança de modo, SP/MV materializada, transição de solver — F4 §5.2), o instante da publicação. `prediction.ts`: o bloco guarda o instante da fronteira em que fez `host.dispatch()` (um solve em voo por vez — ocupado ⇒ `False`) e o aplica ao montar a predição do resultado consumido no `poll()` da fronteira **seguinte** (`blocks/mpc.py:277-283` faz poll antes de dispatch — é por isso que `MpcState.ts` NUNCA é a âncora do overlay, §3.5). Fora de AUTO: `prediction.ts = ts`, `t: []` | `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py` · `services/flow-runtime/tests/test_mpc_block.py` | RED (clock controlado): `ts` presente e **crescente**; em regime `prediction.ts == ts − Ts_mpc` **e** `prediction.mv[i][0] == vars.<mv_id>.v` do quadro anterior (§9.1 — sem este teste o overlay deslocado é invisível); publicação imediata carimba `ts` próprio | F5R-01 · §2.1/§3 |
| 1.3 | **Contratos TS regenerados**: `npm run generate:contracts` (o `contracts_export.py:94` já inclui `MpcState` em `_WS_MODELS` — só regen); `test_contracts_export.py` ganha assert de `ts`/`prediction.ts` no JSON exportado | `frontend/src/lib/contracts.gen.ts` (gerado, commitado) · `packages/ottima-core/tests/test_contracts_export.py` | `cd frontend && npm run build` verde (campos aditivos); diff do gen contém `ts` nos dois modelos | débito 0.2 da F4 (fonte única) |

**Conclusão:** `uv run pytest packages services/flow-runtime services/api` + `npm run build` verdes.

---

## Etapa 2 — Hypertable `mpc_samples` e recorder (spec §2.2/§2.3)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 2.1 | **Migration `0003_mpc_samples`** (SQL cru, molde da 0002): tabela `mpc_samples` (`ts timestamptz NOT NULL`, `flow_id bigint NOT NULL`, `block_id text NOT NULL`, `var_id text NOT NULL`, `v double precision NOT NULL`, `sp double precision NULL`, `auto boolean NOT NULL` — §2.2-1, F5R-21); `create_hypertable(chunk_time_interval => INTERVAL '1 day')` (§2.2-2 — intervalo de `samples`, não os 7 d de `events`; F5R-08); `add_retention_policy(INTERVAL '1 month')` (ADR-003); índice `(flow_id, block_id, var_id, ts DESC)`; CAgg `mpc_samples_1m` em `autocommit_block()` `WITH NO DATA` — `time_bucket('1 minute', ts)`, `avg(v) v`, `min(v) v_min`, `max(v) v_max`, `avg(sp) sp`, `bool_or(auto) auto` por `(flow_id, block_id, var_id)` — MAIS `add_continuous_aggregate_policy(start_offset '1 hour', end_offset '1 minute', schedule_interval '1 minute')` MAIS `add_retention_policy('mpc_samples_1m', '1 month')` — os TRÊS passos de `0002_timescale.py:46-68` (F5R-07); downgrade simétrico. Handle Core `mpc_samples_table` em `models/timeseries.py` (`TIMESERIES_METADATA`, fora do autogenerate — padrão F1); a CAgg NÃO ganha handle (motivo documentado em `routers/history.py:20-22`) | `packages/ottima-core/alembic/versions/0003_mpc_samples.py` (novo) · `packages/ottima-core/src/ottima_core/models/timeseries.py` · `packages/ottima-core/tests/test_timescale.py` | RED: upgrade aplica em banco Timescale de teste; hypertable + colunas/tipos conferem; políticas de `mpc_samples` E `mpc_samples_1m` presentes em `timescaledb_information.jobs`; downgrade limpa | RF-703 · ADR-003 · decisão A-1 |
| 2.2 | **Recorder** (§2.3; F5R-12): terceiro listener `PatternListener("mpc.state.*")` (`ottima_core.pubsub:172`) ao lado de `opc.values.*`/`events`; `flow_id`/`block_id` do nome do canal; `ts`/`vars` do payload; `auto := modes.local_remote == "remote" AND modes.man_auto == "auto"` (§2.2-1); uma linha por `var_id`, `sp` NULL quando a variável não publica `sp` (só CV tem); buffer **próprio** `_DropOldestBuffer` com teto `Settings.mpc_queue_max` (`ottima_core/config.py`, parametrizável como os demais) e `dropped_total` somando descarte, visível no `/health` ao lado de `buffered_samples`/`buffered_events` (`pipeline.py:95-127`); entra em `flush()` **depois** de `events` e `samples` (auditoria primeiro — F2 §6.3), no desmonte cruzado de `start()` e no `stop()` (`pipeline.py:146-206`); mesmo lote `FLUSH_INTERVAL_S` e mesmo backoff; payload malformado logado e descartado sem derrubar nada (RNF-05); `MAX_BIND_PARAMS` acomoda as 7 colunas sem ajuste (`pipeline.py:41`). Grava em **todos os modos** (§2.3-4); duplicata eventual de `(ts, var)` é inócua (sem PK, como `samples`) | `services/recorder/src/ottima_recorder/pipeline.py` · `packages/ottima-core/src/ottima_core/config.py` · `services/recorder/tests/test_pipeline.py` · `tests/test_backpressure.py` · `tests/test_health.py` | RED: linhas corretas (uma por var; `sp` NULL fora de CV; `auto` derivado; flow/block do canal; `ts` do payload = gravado); ordem de flush events→samples→mpc_samples; teto + `dropped_total` no `/health`; malformado ignorado com pipeline vivo | RF-703 · RNF-05 · decisão A-1 |

**Conclusão:** `uv run pytest packages services/recorder` verde.

---

## Etapa 3 — APIs novas, WS `events` e `script_recovered` (spec §2.4/§4.1/§4.2/§5/§7.2-2)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 3.1 | **`GET /api/history/mpc`** (§2.4; F5R-10/23): schemas em `ottima_core/schemas/history.py` — `MAX_MPC_VARS = 14` **[NOVA — implementação]** (4 MV + 6 CV/Restr + 4 DV), `MpcHistorySeries{var_id, t, v, sp, auto, v_min?, v_max?}` e `MpcHistoryResponse{mode, start, end, series}` (mesma forma de `HistoryResponse`/`HistorySeries` `:13-26`, com `var_id` no lugar de `tag_id`, `sp`/`auto` alinhados a `t`, sem `q`); rota no router `history` com `require_operator`: query `flow_id` · `block_id` · `var_ids` (csv dedup, teto 14) · `start`/`end` ISO-8601 opcionais (defaults RF-802: `end = agora`, `start = end − 1 h` — `history.py:95-101`); janela ≤ `RAW_WINDOW_HOURS` ⇒ `mpc_samples` bruto, acima ⇒ `mpc_samples_1m` via `table()/column()` (molde `history.py:23-31`); **uma série por `var_id` pedido, SEMPRE**, inclusive vazia (`history.py:91`); `var_id` desconhecido ⇒ série vazia; 422 pt-BR string única (`var_ids` vazio/malformado, `start ≥ end`, teto excedido, janela > `MAX_WINDOW_DAYS` 31 d, `block_id` inexistente ou não-MPC); **404** flow inexistente (constante 0.4); no `1m`, `auto` = `bool_or` do bucket | `packages/ottima-core/src/ottima_core/schemas/history.py` · `services/api/src/ottima_api/routers/history.py` · `services/api/tests/test_history_mpc.py` (novo) · `frontend/openapi.json` + `npm run generate:api` | RED: raw×1m na fronteira de 2 h; defaults de janela; todos os 422; 404; série vazia; RBAC (anônimo 401); OpenAPI regenerado sem diff espúrio | RF-703/802 · §2.4 |
| 3.2 | **`GET /api/operate/mpcs`** (§4.1; decisão A-7; F5R-14/23): rota no router `operate` com `require_operator`; projeta dos flows do **projeto ativo** todos os nós `type=mpc` do `graph_json` (`parse_graph`/`MpcConfig` já importados — `operate.py:26`); response §4.1-1 **verbatim**: `flow_id`, `flow_name`, `flow_ts_seconds` (do campo `ts_seconds` — `schemas/flows.py:20,38`), `block_id`, `name`, `multiplier`, `variables{mvs[{id,name,eu,limits,du_max}], cvs[{id,name,eu,sp_limits}], constraints[{id,name,eu,range}], dvs[{id,name,eu}]}`; **sem** `pid`/`models`/pesos/TSS/`initial_value` (§4.1-3 — config de engenharia não vaza); models de response inline no router (padrão `ModeCommand`, `operate.py:48-60`); sem projeto ativo ⇒ `[]`; `graph_json` que não parseia ⇒ flow pulado com log, nunca 5xx; estado rodando/parado NÃO entra (§4.1-4) | `services/api/src/ottima_api/routers/operate.py` · `services/api/tests/test_operate.py` · `frontend/openapi.json` | RED: projeção verbatim sem `pid`/`models`; só projeto ativo; inválido pulado com log; RBAC | RF-701 · decisão A-7 |
| 3.3 | **`GET /api/health/workers`** (§4.2; decisão A-8; F5R-09): `Settings` ganha `health_url_opc_worker`/`health_url_flow_runtime`/`health_url_recorder` com defaults `http://opc-worker:8001/health`, `http://flow-runtime:8002/health`, `http://recorder:8003/health` (`deploy/docker-compose.yml:60,88,114`) **[NOVA — implementação]**; rota no router `health` com `require_operator` **por rota** (o `GET /health` público de `health.py:10-12` permanece intacto); consulta os 3 em paralelo com `urllib.request` em `asyncio.to_thread`, timeout 1 s cada; response `{opc_worker: {up, ...corpo do /health}, flow_runtime: {...}, recorder: {...}}`; fora do ar/timeout ⇒ `{up: false}`; **200 sempre** (agregador nunca propaga 5xx de terceiro) | `packages/ottima-core/src/ottima_core/config.py` · `services/api/src/ottima_api/routers/health.py` · `services/api/tests/test_health.py` | RED: monkeypatch de `urllib.request.urlopen` (sucesso, erro, timeout); agrega os 3; sempre 200; RBAC da rota nova (401 anônimo); rota pública continua sem auth | RNF-07 · decisão A-8 |
| 3.4 | **WS `/ws` canal `events`** (§5; decisão A-5; F5R-15): hub ganha `ChannelListener("events")` (`pubsub.py:148`) ao lado dos 2 `PatternListener` (`ws.py:112-118`); no parser (`ws.py:213-241`) é um **ramo próprio** com flag booleana `sub.events` — nunca o par `(atributo, parse de lista)` das chaves de id; `{"subscribe": {"events": true}}` assina, `{"unsubscribe": {"events": true}}` desassina; valor que não seja `true` (`false`, número, lista) ⇒ logado e ignorado, **não inverte a ação**; fanout `{"channel": "events", "data": {…}}` aos optantes; escopo fechado F5: `flow_status` + `mpc_state` + `events` (`opc.values.*` fora — §1.2) | `services/api/src/ottima_api/ws.py` · `services/api/tests/test_ws_events.py` (novo) | RED: subscribe ⇒ evento publicado na fixture Redis chega; unsubscribe para; os 3 tipos de assinatura no mesmo socket; `{"subscribe": {"events": false}}` é no-op logado; `flow_status`/`mpc_state` intactos | ADR-020 · decisão A-5 |
| 3.5 | **`script_recovered`** (§7.2-2; F5R-02b): runtime publica evento `KIND_SCRIPT_RECOVERED` (severity `info`, kind da tarefa 1.1) no ponto onde o latch do Script **já rearma** (`blocks/script.py:95` — primeiro sucesso após `script_timeout`/`script_error`; latch em `:113-116`), uma vez por rearme; payload padrão dos eventos de bloco. Quem latcha, anuncia o rearme | `services/flow-runtime/src/ottima_flow_runtime/blocks/script.py` · `services/flow-runtime/tests/test_script.py` | RED: timeout→sucesso publica exatamente 1; sucesso→sucesso não publica; erro→sucesso publica; dois ciclos falha/rearme ⇒ 2 eventos | decisão A-4 · §7.2 |

**Conclusão:** `uv run pytest` (workspace) verde; `frontend/openapi.json` regenerado.

---

## Etapa 4 — F-1: boot assíncrono do worker e reescopo do lock (spec §6; F5R-05/06)

> A tarefa mais arriscada do plano. As 6 invariantes dos fix rounds da F4 valem **byte a byte** (§6.4); regressão da suíte flow-runtime inteira é parte do aceite de cada tarefa.

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 4.1 | **Boot assíncrono + `building` em qualquer modo** (§6.1/§6.2; emenda §1.3-4): `host.start()` sai do caminho síncrono do lock em **todos** os chamadores — `_deploy` (`supervisor.py:293-294`) E `reconcile_mpc_hosts` do hot-swap (`supervisor_mpc.py:349-350`): estagiam e retornam; o build (spawn + montagem do-mpc) roda como task de fundo; o flow varre desde a primeira fronteira. `blocks/mpc.py:563-575` (que hoje força `idle` fora de AUTO): `status.solver = "building"` publicado **sempre que o host não está pronto, em qualquer modo**, precedendo `idle` — `idle` fica reservado a "worker pronto e ocioso fora de AUTO". Invariantes preservadas: REMOTO antes de pronto ⇒ `mpc_arm_failed {worker_not_ready}` nos **dois** eixos (`supervisor_mpc.py:109,151-152`); shed/hot-swap/watchdog de armar intocados | `services/flow-runtime/src/ottima_flow_runtime/supervisor.py` · `supervisor_mpc.py` · `blocks/mpc.py` · `tests/test_supervisor_mpc.py` · `tests/test_mpc_block.py` | RED (clock controlado + worker dublê de build lento): `building` publicado em LOCAL no deploy; transições building→idle (LOCAL) e building→ok (AUTO); armar na janela de build ⇒ `arm_failed{worker_not_ready}`; suíte flow-runtime inteira verde | spec F4 §4.1 (letra) · F5R-05 |
| 4.2 | **Lock reescopado + stop sem órfão** (§6.3/§6.5; F5R-06): o lock global (`supervisor_mpc.py:245`) passa a proteger **só o mapa `_runtimes`**; a espera de desmonte roda fora dele (desmonte destacado com o `MpcHost` já removido do mapa) **[NOVA — implementação]** (forma); `stop` (`supervisor_mpc.py:320-321`) não segura o lock durante `MpcHost.stop()` — que espera boot em voo até `_BOOT_TIMEOUT_S = 30 s` (`host.py:85,263-268`); sem o reescopo o bloqueio só **migraria** do deploy para o stop/reload. Stop do flow durante o build encerra **sem processo órfão**: `_stopped` primeiro, thread de spawn concluída, processo morto e juntado (`host.py:263-290`); nota normativa: `asyncio.to_thread` não é cancelável (`host.py:342-344`) — "cancelar o build" = marcar parado, deixar a thread terminar e então matar/juntar, nunca abortar antes de nascer | `services/flow-runtime/src/ottima_flow_runtime/supervisor_mpc.py` · `mpc/host.py` · `tests/test_mpc_boot_async.py` (novo) | RED (worker dublê com build lento controlado) — **3 latências medidas**: (a) deploy de flow MPC pesado não bloqueia `stop`/`deploy` de outro flow; (b) `reload` de flow MPC pesado não bloqueia comando de outro flow; (c) `stop` de flow em build não bloqueia `deploy` de outro flow (é a inversão que o E2E não cobre — §9.1); **órfão**: após stop durante build, `stats()["alive"]` falso e processo juntado | F5R-06 · §6.3/§6.5 |

**Conclusão:** `uv run pytest services/flow-runtime` verde (incluindo `-m slow` uma vez — a carga da F4 não regride).

---

## Etapa 5 — Integração L2 e fechamento do plano F5a

> Setup: reusa a malha MPC↔TFS e os helpers do conftest da F4 (`tests/e2e/conftest.py`); opcsim como origem OPC. Precondições §9.3 da spec: L2 e Playwright serializados; credenciais inline; sempre os dois arquivos compose.

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 5.1 | **E2E-F5-01..07** (provas verbatim da tabela §9.2-L2): 01 flow MPC rodando ⇒ `mpc_samples` na cadência Ts_mpc, **grava também em LOCAL** com `auto=false`, `sp` NULL fora de CV, `ts` payload = gravado (`test_f5_data.py`); 02 `/api/history/mpc` bruto ≤ 2 h e `1m` acima (CAgg materializada — prova a política de refresh), teto/422/404, RBAC (`test_f5_data.py`); 03 `/api/operate/mpcs` projeta sem `pid`/`models` + flow inexistente no `/operate` ⇒ 404 (`test_f5_api.py`); 04 WS `events` subscribe⇒chega / unsubscribe⇒para (`test_f5_api.py`); 05 **F-1**: deploy de flow MPC pesado não bloqueia `stop` de outro (latência medida), `building` observável em `mpc.state` no deploy **em LOCAL** antes de `idle`, armar na janela ⇒ `mpc_arm_failed{worker_not_ready}` (`test_f5_runtime.py`); 06 `ts`/`prediction.ts` presentes, `ts` monotônico, em regime `prediction.ts == ts − Ts_mpc` (`test_f5_runtime.py`); 07 enum inválido em `/operate/mode` ⇒ 422 string única pt-BR (`test_f5_api.py`) | `tests/e2e/test_f5_data.py` · `tests/e2e/test_f5_api.py` · `tests/e2e/test_f5_runtime.py` (novos) · `tests/e2e/conftest.py` (helpers) | `uv run pytest -m e2e tests/e2e -v` — **41 cenários** (5 F1 + 9 F2 + 10 F3 + 10 F4 + 7 F5) verdes na mesma rodada | spec §9.2-L2 |
| 5.2 | **L1**: `deploy/smoke.sh` ganha `GET /api/health/workers` com os 3 `up: true` e a presença das políticas de retenção de `mpc_samples` **e** `mpc_samples_1m` em `timescaledb_information.jobs` (o smoke já verifica "retenção ativa" — F5R-07) | `deploy/smoke.sh` | `OTTIMA_E2E=1 bash deploy/smoke.sh` verde com flow-runtime recém-subido (o smoke assere `flows={}` no boot) | RNF-07 · spec §9.2-L1 |
| 5.3 | **Encerramento parcial**: CLAUDE.md §Comandos atualizado (L2 = 41 cenários; rotas novas `/api/history/mpc`, `/api/operate/mpcs`, `/api/health/workers`; envs `OTTIMA_HEALTH_URL_*`; `OTTIMA_MPC_QUEUE_MAX`); ledger `.superpowers/sdd/F5a-operacao-dados/progress.md` completo com as provas RED | `CLAUDE.md` · ledger | seção reflete comandos reais | CLAUDE.md §Comandos |

---

## Aderência (DoD do plano F5a)

| Critério | Tarefas |
|---|---|
| Emendas §1.3 aplicadas (PRD v1.3 + 5 notas de remissão) | 0.1, 0.2 |
| Débitos de contrato F4 fechados (handler 422, 404 unificado, `empty_result` único) | 0.3, 0.4, 0.5 |
| `mpc.state` com `ts`/`prediction.ts` ponta a ponta, com teste de âncora | 1.1, 1.2, 1.3, 5.1 (E2E-F5-06) |
| `mpc_samples` + CAgg + políticas, gravada pelo recorder em todos os modos | 2.1, 2.2, 5.1 (E2E-F5-01), 5.2 |
| `/api/history/mpc` + `/api/operate/mpcs` + `/api/health/workers` + WS `events` + `script_recovered` | 3.1-3.5, 5.1 (E2E-F5-02/03/04/07) |
| F-1 fechado: 3 latências + zero órfão + `building` em qualquer modo | 4.1, 4.2, 5.1 (E2E-F5-05) |
| Zero regressão F1-F4 | 5.1 (41 cenários), Etapa 4 (suíte flow-runtime), `-m slow` |

O aceite da FASE (PRD §8-F5) fecha no plano F5b, com o gate L3 de `docs/plans/tests-e2e-f5.md`.

## Rastreabilidade (RF/decisão por tarefa)

| Norma | Tarefas |
|---|---|
| RF-703 (histórico com Timescale) | 2.1, 2.2, 3.1, 5.1 |
| RF-701 (descoberta/seleção do MPC) | 3.2 |
| RF-704 (REST de operação — correção 404) | 0.4 |
| RF-705 / ADR-020 (eventos → banner) | 3.4, 3.5 |
| RF-802 (downsampling padrão) | 3.1 |
| RNF-05 (resiliência do recorder) | 2.2 |
| RNF-07 (heartbeat visível) | 3.3, 5.2 |
| Decisões A-1/A-2/A-5/A-7/A-8/A-9 | 2.1-2.2 / 0.1+1.1-1.2 / 3.4 / 3.2 / 3.3 / 0.3-0.5 |
| F5R-01/02b/05/06/07/08/09/12/14/15/21/23/26/27 | 1.1-1.2 / 3.5 / 4.1 / 4.2 / 2.1 / 2.1 / 3.3 / 2.2 / 3.2 / 3.4 / 2.1 / 3.1-3.2 / 0.1-0.2 / 0.5 |
