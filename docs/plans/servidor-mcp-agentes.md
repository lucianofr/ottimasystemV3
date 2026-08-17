# Plano — Servidor MCP para agentes (`packages/ottima-mcp`)

> Executa o **ADR-036** (Proposto, 2026-08-17). Cada fase é autocontida para uma sessão nova
> de agente: referências de arquivo:linha incluídas, snippets copy-ready embutidos.
> Vocabulário: GLOSSARY.md (Servidor MCP, Superfície curada, Conta `agente`,
> Comandado ≠ confirmado, Cursor de eventos).
>
> **Regra de ouro de todas as fases:** copiar dos padrões citados, nunca inventar API.
> O backend NÃO muda em nenhuma fase — o pacote é um cliente, como o frontend.

---

## Fase 0 — Descoberta de documentação (CONCLUÍDA — consolidação)

Fatos levantados por 5 subagentes em 2026-08-17, verificados no código-fonte. Executores das
fases seguintes DEVEM reler os trechos citados antes de codar — não confiar de memória.

### APIs permitidas (backend OttimaSystem — únicas superfícies que o pacote pode tocar)

**Auth** (`services/api/src/ottima_api/routers/auth.py:17-41`,
`packages/ottima-core/src/ottima_core/schemas/auth.py:9-32`):
- `POST /api/auth/login` body `{username, password}` → `LoginOut{access_token, token_type:"bearer", expires_in:int, user:UserOut{id,username,name,role,is_active,...}}`. 401 genérico.
- JWT HS256, TTL 12h (`config.py:23`), **sem refresh** → re-login em 401.
- REST: header `Authorization: Bearer <jwt>`. WS: **só** query `?token=` (`ws.py:~388-398`).
- Rate-limit no login via nginx: 30 req/min por IP, burst 20 (`frontend/nginx.conf:24-29`) — sem retry agressivo.

**Rede** (`deploy/docker-compose.yml:28-45,172-179`; `frontend/nginx.conf:30-34`):
- Única porta publicada: nginx `${OTTIMA_HTTP_PORT:-80}`. API interna `api:8000`, nunca exposta.
- Base URL do pacote: `OTTIMA_URL` (ex.: `http://localhost:8080` na stack e2e). Paths: `/api/...` e `/ws` (literal, **sem barra final** — `canalPrimitivos.ts:52-58`).

**Operate** (`services/api/src/ottima_api/routers/operate.py`):
- `GET /api/operate/mpcs` → `list[MpcNodeOut{flow_id, flow_name, flow_ts_seconds, block_id, name, multiplier, variables:{mvs[],cvs[],constraints[],dvs[]}, horizons:{ts_mpc,np,nc}}]` (linhas 86-206). Projeção de **config**, não estado vivo. Sem projeto ativo → `[]`.
- `POST /api/operate/{flow_id}/{block_id}/mode` body `{axis:"local_remote"|"man_auto", value:"local"|"remote"|"man"|"auto"}` (par validado, linhas 64-84) → **202 sem corpo**.
- `POST .../sp` body `{var_id, value}` — 422 se `remote_sp` ou fora de `sp_limits` (linhas 280-305).
- `POST .../mv` body `{var_id, value}` — 422 se fora de `limits` (linhas 308-330).
- `GET /api/operate/fuzzy` e `GET /api/operate/fuzzy/{flow_id}/{block_id}` → `FuzzyNodeOut`/`FuzzyDetailOut`. **Fuzzy não tem escrita** — só leitura.

**Monitoramento** (`routers/history.py`, `events.py`, `health.py`):
- `GET /api/history?tag_ids=1,2&start=&end=` — máx 6 tags, janela ≤31d, downsample raw≤2h/1m → `HistoryResponse{mode, start, end, series:[{tag_id,t[],v[],q[],v_min?,v_max?}]}` (history.py:212-267).
- `GET /api/history/mpc?flow_id=&block_id=&var_ids=a,b` — máx 14 vars; série `{var_id, t[], v[], sp[], auto[], ...}` — **inclui modos e SP históricos** (history.py:270-346).
- `GET /api/history/ssto/last?flow_id=&block_id=` → `SstoLastOut{ts, run:SstoRun}` ou **200 `null`** (nunca rodou) (history.py:503-531). `SstoRun` completo em `ottima_core/bus.py:124-153`.
- `GET /api/events?severity=&origin=&start=&end=&limit=` (≤1000, default 100, ordenação fixa `ts DESC`) → `list[EventOut{ts,severity,origin,message,payload}]` (events.py:23-45). **SEM cursor por id hoje**; tabela `events` sem coluna id (`ottima_core/models/timeseries.py:33-41`).
- `GET /api/health` (público) → `{status:"ok"|"degraded", service, version, redis_ok, db_ok}`; `GET /api/health/workers` (operador) → `{opc_worker:{up,...}, flow_runtime:{...}, recorder:{...}, calc_worker:{...}}` (health.py:69-113).

**Flows** (`routers/flows.py`; `ottima_core/schemas/flows.py`; `ottima_core/flowgraph/`):
- `POST /api/flows` body `FlowCreate{project_id, name, ts_seconds∈{0.5,1,2,5,10,30,60}}` → 201, grafo nasce `{nodes:[],edges:[]}`.
- `GET /api/flows` → `list[FlowOut]` (sem graph_json); `GET /api/flows/{id}` → `FlowDetail` (com).
- `PUT /api/flows/{id}` body `FlowUpdate` — todos os campos opcionais; `graph_json` presente = objeto **INTEIRO** `{nodes,edges}` (nunca patch); campos `None` preservam o salvo. 200 → `FlowSaved{flow:FlowDetail, warnings:list[str]}` (avisos RF-307 não bloqueiam). 422 = **string única** unida por `" | "` (flows.py:72-77). Flow rodando: PUT publica `reload` (hot-swap ADR-011).
- `POST /api/flows/{id}/deploy` | `/stop` → 202 sem corpo; grava `desired_state` + publica intenção. Confirmação vem em `flow.status.{id}` (runtime, `scheduler.py:156-203,427-446`).
- `DELETE /api/flows/{id}` → 409 se rodando.
- **Shape do nó**: `{id, type∈NODE_TYPES, position:{x,y}, data:{exec_order, label?, ...config FLATTENED}}` — config NÃO aninhada sob `"config"` (`flowgraph/parse.py:30-52` `_CONFIG_KEYS`). Chave desconhecida em `data` = 422.
- **Aresta**: `{id, source, target, sourceHandle, targetHandle}` (camelCase).
- `NODE_TYPES = ("opc_read","opc_write","script","fuzzy","tfs","mpc","first_order","kalman","pid")` (`parse.py:15-25`) — fonte canônica única.
- `exec_order`: inteiro ≥1, único, **contíguo 1..N** (`validate.py:~187-207`, ADR-024). Mutações devem renumerar.
- Portas MPC por instância: entradas = ids de cvs+constraints+dvs; saídas = ids de mvs + `MPC_FIXED_OUTPUT_PORTS=("local","auto")` (`mpc_config.py:53`, `validate.py:~103-160`).
- Contratos de porta/config exportáveis: `ottima_core.contracts_export.build_contracts()` (puro, sem I/O; executável `uv run python -m ottima_core.contracts_export`) — reusar para `block_catalog`, **não** duplicar literais.
- Exemplo mínimo válido `opc_read→mpc` (rastreado de `packages/ottima-core/tests/test_flowgraph_mpc.py:19-246`; exemplo verbatim mais simples em `test_flowgraph.py:33-114 base_graph()`): ver ADR/relatório; usar essas fixtures como referência nos testes do pacote.

**WS `/ws`** (`services/api/src/ottima_api/ws.py`; shapes em `ottima_core/bus.py`):
- Cliente→servidor: `{"subscribe": {...}}` / `{"unsubscribe": {...}}` com chaves opcionais `flow_status:[int]`, `mpc_state:["<flow_id>/<block_id>"]`, `fuzzy_state:[...]`, `opc_values:[tag_id]`, `events:true`.
- Servidor→cliente: envelope `{"channel": "<canal>", "data": {...}}`. Canais: `flow.status.<id>` → `FlowStatus{state, scan_ms, overruns, ts, ports}`; `mpc.state.<fid>.<bid>` → `MpcState{ts, modes:{local_remote,man_auto}, status:{solver,overruns,last_solve_ms,armed,input_valid}, vars:{<var_id>:{v,sp,status}}, cost, prediction, ssto}`; `events` → `EventMessage`.
- Fila 8 drop-oldest por assinatura (`ws.py:70,83-92`) — assinar SÓ o id esperado, sessão curta.
- Close `1008` = auth recusada, **nunca reconectar** (`canalPrimitivos.ts:44,58-60`); outros códigos = queda de rede.
- **Sem replay**: assinar ANTES de disparar o comando, senão a confirmação pode passar.

### SDK `mcp` 2.0.0 (repo `modelcontextprotocol/python-sdk` tag v2.0.0)

- Pin: `mcp>=2.0.0,<3`. Python ≥3.10 (repo usa 3.12). **v2 renomeou** `FastMCP`→`MCPServer`.
- Servidor stdio mínimo (`docs_src/run/tutorial001.py`):
  ```python
  from mcp.server import MCPServer
  mcp = MCPServer("ottima")

  @mcp.tool()
  def minha_tool(q: str) -> str: ...

  if __name__ == "__main__":
      mcp.run()  # default stdio
  ```
- Params tipados viram JSON Schema; refinamento com `Annotated[x, Field(...)]`, `Literal`, `| None`, `BaseModel` (`docs_src/tools/tutorial003.py`, `tutorial004.py`).
- `async def` suportado nativamente (`func_metadata.py:84-108`).
- Lifespan para client HTTP autenticado persistente (`docs_src/lifespan/tutorial001.py`):
  ```python
  @asynccontextmanager
  async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
      cliente = await ClienteOttima.conectar()   # login + httpx.AsyncClient
      try:
          yield AppContext(ottima=cliente)
      finally:
          await cliente.fechar()

  mcp = MCPServer("ottima", lifespan=app_lifespan)

  @mcp.tool()
  async def mpc_list(ctx: Context[AppContext]) -> list[dict]:
      return await ctx.request_context.lifespan_context.ottima.get("/api/operate/mpcs")
  ```
  `Context` é injetado por **anotação de tipo**, nome do parâmetro é livre.
- Erros: exceção Python comum (ex. `ToolError`, `ValueError`) → `CallToolResult(is_error=True)` com `str(e)` como conteúdo (`server.py:415-424`) — **rota correta para repassar 422 pt-BR verbatim**. `MCPError` = erro de protocolo, NÃO usar para erro de negócio.
- Retorno `BaseModel`/`dict`/`list` → `structured_content` direto; primitivo é envolvido em `{"result": ...}` (`func_metadata.py:110-144`).
- Elicitation existe server-side (`ctx.elicit`) — gate futuro viável; suporte do cliente Claude Code **não verificado** (não depender).

### Fiação do monorepo (`pyproject.toml` raiz + `services/api/pyproject.toml:1-20`)

- uv workspace: `members = ["packages/*", ...]` — `packages/ottima-mcp` entra pelo glob, **sem editar** a lista.
- Consumo do core: dependência `"ottima-core"` + `[tool.uv.sources] ottima-core = { workspace = true }`; hatchling; layout `src/ottima_mcp/`.
- Ruff único na raiz: adicionar `ottima_mcp` a `known-first-party` (`pyproject.toml:56`).
- Testes: `packages/ottima-mcp/tests/test_*.py`, sem `__init__.py`; `uv run pytest` exclui `e2e`/`slow` por default (`addopts`, `pyproject.toml:39`); e2e assume stack de pé (`tests/e2e/conftest.py:1-6`), base `E2E_BASE_URL` (fallback `http://localhost:8080`).
- Conta `agente`: **não existe seed**; criar via `POST /api/users` `{username,name,password,role:"admin"}` autenticado como admin do seed (`routers/users.py:14+`, `seed.py:18-39`).
- `.mcp.json` atual tem só `code-review-graph` (stdio, sem env). Campo `env` é schema padrão do Claude Code (fonte: `code.claude.com/docs/en/mcp` + `anthropics/claude-plugins-official/.../stdio-server.json`).

### Anti-padrões (guardas para TODAS as fases)

1. **NUNCA** `from mcp.server.fastmcp import FastMCP` — é a API v1; o ambiente local tem `mcp==1.29.0` instalado fora do workspace, não deixar o pin escorregar.
2. **NUNCA** reportar sucesso de escrita por HTTP 200/202 — 202 é intenção (RNF-05).
3. **NUNCA** validar faixa/modo no pacote — repassar o 422 pt-BR do backend verbatim (exceção comum → `is_error=True`).
4. **NUNCA** inventar endpoint: não existe escrita fuzzy, refresh de token, GET de estado vivo do MPC (só `/ws`), cursor `since_id` em `/api/events`, patch parcial de `graph_json`.
5. **NUNCA** enviar `graph_json` parcial no PUT — sempre o objeto inteiro lido antes (read-modify-write).
6. **NUNCA** aninhar config sob `data.config` — campos FLATTENED em `data`.
7. **NUNCA** assinar interesses largos no `/ws` — um id, sessão curta, fechar depois.
8. **NUNCA** expor ferramenta fora da superfície curada (users/certs/connections-write/tags-write/projects-write/system-settings/history-retention).

---

## Fase 1 — Pacote, config e cliente HTTP autenticado

**Implementar** (copiar padrões citados):
1. `packages/ottima-mcp/pyproject.toml` — copiar forma de `services/api/pyproject.toml:1-20`; nome `ottima-mcp`; deps: `"ottima-core"`, `"mcp>=2.0.0,<3"`, `"httpx"`, `"websockets"`; `[project.scripts] ottima-mcp = "ottima_mcp.__main__:main"`; `requires-python = ">=3.12,<3.13"`.
2. Raiz `pyproject.toml:56`: acrescentar `ottima_mcp` em `known-first-party`.
3. `src/ottima_mcp/config.py` — env vars (nomenclatura FIXADA aqui): `OTTIMA_URL` (obrigatória), `OTTIMA_MCP_USERNAME`, `OTTIMA_MCP_PASSWORD` (obrigatórias). Sem defaults mágicos: faltou → erro de partida com mensagem clara.
4. `src/ottima_mcp/cliente.py` — `ClienteOttima`: `httpx.AsyncClient(base_url=OTTIMA_URL)`; `login()` via `POST /api/auth/login` (shape `auth.py:17-35`); guarda `access_token`; injeta `Authorization: Bearer`; em **401 de qualquer chamada**: 1 re-login + 1 retry (nunca loop — rate-limit do nginx); métodos `get/post/put/delete` que devolvem JSON ou levantam `ErroOttima(str(detail))` com o `detail` string do backend (404/409/422 — shape `{"detail": "<string>"}` garantido por `app.py:21-31`).

**Verificação:**
- `uv sync` resolve o workspace com o pacote novo.
- `uv run pytest packages/ottima-mcp` — testes unitários do cliente com `httpx.MockTransport` (sem dep nova): login ok, bearer injetado, 401→re-login→retry único, 422 vira `ErroOttima` com texto pt-BR intacto.
- `uv run ruff check packages/ottima-mcp` limpo.

**Guardas:** anti-padrões 1 e 3; nenhuma dependência além das 4 listadas.

---

## Fase 2 — Servidor MCP + ferramentas de leitura (REST)

**Implementar:**
1. `src/ottima_mcp/server.py` — `MCPServer("ottima", lifespan=...)` guardando `ClienteOttima` (copiar snippet lifespan da Fase 0). `src/ottima_mcp/__main__.py` — `main()` chama `mcp.run()`.
2. Ferramentas async de leitura, uma função por ferramenta, descrição pt-BR objetiva, params `Annotated[..., Field(description=...)]`:
   - `mpc_list()` → `GET /api/operate/mpcs` (devolver a lista crua — já é projeção curada).
   - `fuzzy_list()`, `fuzzy_detail(flow_id, block_id)`.
   - `ssto_last(flow_id, block_id)` — 200 `null` = "nunca executou SSTO" em texto, não erro.
   - `trend(tag_ids: list[int], start?, end?)` → `/api/history` (máx 6 — deixar o 422 do backend falar).
   - `mpc_history(flow_id, block_id, var_ids: list[str], start?, end?)`.
   - `events_query(severity?, origin?, start?, end?, limit?=100)` → devolve `{eventos: [...], cursor: "<ts ISO do mais recente>"}` — **cursor opaco reservado** (`# ponytail: cursor codifica ts; v2 migra events p/ coluna id e passa a codificar id sem quebrar contrato`).
   - `system_health()` → agrega `/api/health` + `/api/health/workers`.
   - `flow_list()`, `flow_get(flow_id)` (leitura; a escrita fica na Fase 4).
   - `block_catalog()` → importa `ottima_core.contracts_export.build_contracts()` + `NODE_TYPES` de `flowgraph.parse` — nunca literais duplicados.

**Verificação:**
- Unit: cada ferramenta com `MockTransport` (shapes de resposta copiados das fixtures/reports da Fase 0).
- Smoke real (stack de pé, `OTTIMA_E2E=1 bash deploy/smoke.sh` antes): rodar o servidor stdio e listar ferramentas + chamar `mpc_list`/`system_health` com um cliente MCP mínimo (o próprio SDK tem cliente) — teste marcado `@pytest.mark.e2e`.
- `grep -rn "fastmcp" packages/ottima-mcp` → vazio.

**Guardas:** anti-padrões 1, 4, 8. Nenhuma ferramenta de escrita nesta fase.

---

## Fase 3 — Confirmação publicada + ferramentas de escrita de operação

**Fatos confirmados no runtime (2026-08-17, `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py` e `supervisor_mpc.py` lidos linha a linha — substituem qualquer suposição)**:
- `kind` sempre em `payload["kind"]`, garantido pelo publisher canônico (`ottima_core/bus.py:296-329`, `publish_event`).
- **`mpc_state.vars[cv_id].sp` é o comando aplicado, não convergência física**: `_build_state` lê direto de `self._sp` (`mpc.py:1091`), o mesmo dict que `_command_sp` escreve (`mpc.py:1045`) e que é republicado a cada fronteira de scan (`mpc.py:513-518`) — diferente de `vars[mv_id].v`, que é `self._mv_last` (`mpc.py:1098`), a saída FISICAMENTE aplicada após rampa de `max_rate` (`mpc.py:507-510`). **SP e MV não são a mesma categoria de campo.**
- **`_command_sp` e `_command_mv` são idempotentes: reenviar o valor já vigente retorna sem publicar nem emitir evento** (`mpc.py:1043-1044` e `:1063-1064`, comentário `# idempotente`). Sem fallback de estado, um evento perdido (fila 8) seguido de retry do MESMO valor trava para sempre — nenhum novo evento jamais sai.
- **`_command_mode` é idempotente nos dois eixos** (`mpc.py:991-992`, `:1003-1004`) — mas `modes[axis]` é campo publicado persistente (mesma categoria de `sp`), então o fallback de estado já cobre o caso.
- **Trap silencioso adicional (achado desta verificação, mesma classe do de SP/MV)**: comandar `axis="man_auto"` (qualquer valor) enquanto `local_remote=="local"` não emite `mpc_arm_failed` nem `mpc_mode_changed` — o gate de armamento do supervisor só existe para `value=="auto"` E `block.local_remote=="remote"` (`supervisor_mpc.py:105-110`); fora dessa condição o comando cai direto em `block.command()` → `mpc.py:1001-1002` retorna sem publicar nada (ADR-010: sub-modo só existe em REMOTO). A REST (`operate.py`) só valida o PAR eixo/valor, nunca eixo-vs-estado-atual — o 202 sai igual.

**Implementar:**
1. `src/ottima_mcp/confirmacao.py` — cliente WS efêmero (`websockets`): conecta `ws(s)://<host>/ws?token=<jwt>` (derivar de `OTTIMA_URL`; path `/ws` sem barra final), envia UM subscribe com os dois interesses da espera — `{"subscribe": {"mpc_state": ["<fid>/<bid>"], "events": true}}` —, acumula o **último `MpcState` observado** e testa o predicado de sucesso/falha a cada mensagem até bater ou estourar o timeout, fecha. Close 1008 → erro de sessão (re-login e 1 retry). **Assinar ANTES de POSTar o comando** (sem replay no hub). `events` é canal global sem filtro por flow: filtrar client-side por `payload.kind` + origem; janela curta torna a fila 8 aceitável.
2. Timeout default derivado: `ts_mpc = flow_ts_seconds × multiplier` (de `mpc_list`); `timeout = max(2×ts_mpc, 10s)` — o fator 2× existe especificamente para sobreviver a UMA publicação de fronteira perdida na fila 8, parâmetro opcional da ferramenta.
3. Ferramentas de escrita (subscribe → POST → aguardar → devolver resultado). Predicado por ferramenta, **nenhum usa `vars[mv_id].v` como sucesso** (é física, não comando — ADR-028):
   - `mpc_set_mode(flow_id, block_id, axis: Literal["local_remote","man_auto"], value: Literal["local","remote","man","auto"])` — sucesso: `mpc_state.modes[axis] == value` OU evento `mpc_mode_changed{payload.axis,to}` esperado (campo publicado persiste — cobre idempotência e evento perdido pela mesma via). **Falha rápida**: evento `mpc_arm_failed` do bloco → erro com `payload.reason`. **Diagnóstico de timeout dedicado**: se `axis=="man_auto"` e o último `modes.local_remote` observado for `"local"`, erro explícito citando ADR-010 (sub-modo só existe em REMOTO; comando foi silenciosamente ignorado, não é lentidão) em vez de "timeout genérico".
   - `mpc_write_sp(flow_id, block_id, var_id, value)` — sucesso: evento `payload.kind=="mpc_sp_written"` do bloco com var/valor esperados **OU** `mpc_state.vars[var_id].sp` igual a `value` (tolerância float) — cobre tanto o evento perdido na fila 8 quanto o retry do mesmo valor (idempotente-sem-evento, `mpc.py:1043-1044`). Anexar o `MpcState` mais recente como contexto.
   - `mpc_write_mv(flow_id, block_id, var_id, value)` — sucesso: **só** evento `payload.kind=="mpc_mv_written"` (sem fallback de `v` — ramparia por `max_rate` e mentiria sobre a MV ter sido comandada quando só está convergindo, ou vice-versa). **Diagnóstico de timeout dedicado** (sem round-trip extra — usa o `MpcState` já observado na mesma assinatura): se `modes.local_remote != "remote"` ou `modes.man_auto != "man"`, erro citando ADR-010 (`operate.py:308-330`: só materializa em REMOTO+MAN); senão, erro citando a idempotência (`mpc.py:1063-1064`): "se o valor já é o vigente, nenhum novo evento sai — confira `mpc_state` antes de reenviar o MESMO valor; reenviar não vai gerar novo evento."
   - Timeout sem diagnóstico específico aplicável → erro genérico COM o último `MpcState` observado anexado (o agente decide; nunca "sucesso").
4. `mpc_state(flow_id, block_id)` — leitura one-shot pelo mesmo canal: espera a **primeira** publicação (timeout idem) e devolve `MpcState` completo.

**Verificação:**
- Unit: hub WS falso (servidor `websockets` local no teste) — **fixtures de `MpcState`/`EventMessage` copiadas verbatim dos campos confirmados acima, com fonte comentada; proibido inventar payload** (um hub falso que publica o que o predicado espera passa verde por construção e não prova nada — motivo desta correção). Casos obrigatórios:
  - `mpc_write_sp`: confirma por evento; confirma **sem** evento novo só com `vars[var_id].sp` já no valor (simula retry pós-idempotência); timeout com nem evento nem estado batendo.
  - `mpc_write_mv`: confirma só por evento (estado com `v` divergente NÃO impede sucesso, nem `v` coincidente por acaso gera sucesso sem evento); timeout fora de REMOTO+MAN produz o diagnóstico ADR-010; timeout com REMOTO+MAN e sem evento produz o diagnóstico de idempotência.
  - `mpc_set_mode`: confirma por estado OU evento; `mpc_arm_failed` → falha rápida com razão; timeout de `man_auto` com `local_remote=="local"` observado produz o diagnóstico ADR-010.
  - Close 1008 → erro de sessão, re-login+retry único. Espelhar o padrão de dublê de `canalAoVivo.check.ts:296+` (SocketFalso) em Python.
- E2E (`@pytest.mark.e2e`, planta virtual):
  - `mpc_set_mode` man→auto num MPC do projeto ativo — retorno traz estado confirmado.
  - `mpc_write_sp` dentro da faixa; fora da faixa → `is_error` com a mensagem 422 pt-BR do backend; **reenviar o MESMO SP já aplicado** → sucesso via fallback de estado (sem depender de novo evento).
  - **Trap da rampa**: `mpc_write_mv` (REMOTO+MAN) num MPC com `max_rate` pequeno o suficiente para `v` NÃO alcançar `value` dentro do timeout — a ferramenta DEVE suceder via `mpc_mv_written` com `v` ainda em rampa no estado anexo. Falha se o predicado regredir para `v ≈ value`.
  - `mpc_write_mv` em LOCAL — timeout com o diagnóstico ADR-010 específico, nunca sucesso, nunca timeout mudo.
  - `mpc_set_mode(axis="man_auto")` com o bloco em LOCAL — timeout com o diagnóstico ADR-010, nunca sucesso, nunca timeout mudo.

**Guardas:** anti-padrões 2, 3, 7. Nenhuma revalidação local de faixa/modo — só interpretação de sinal já publicado pelo runtime.

---

## Fase 4 — Engenharia de flows (grafo)

**Implementar** em `src/ottima_mcp/grafo.py` + ferramentas:
1. Camada read-modify-write: `flow_get` → mutar dict → `PUT /api/flows/{id}` com `graph_json` **inteiro**; devolver `FlowSaved.warnings` sempre que não-vazio. 422 (string única `" | "`) repassado verbatim.
2. Ferramentas:
   - `flow_create(project_id, name, ts_seconds)`.
   - `flow_add_block(flow_id, type: Literal[...NODE_TYPES], config: dict, position?: {x,y}, label?)` — monta `data = {exec_order: N+1, label?, **config}` (FLATTENED); id de nó gerado único.
   - `flow_remove_block(flow_id, block_id)` — remove nó + arestas incidentes + **renumera exec_order 1..N**.
   - `flow_update_block(flow_id, block_id, config_patch?: dict, position?, exec_order?, label?)` — merge raso em `data`; se `exec_order` mudar, renumerar o resto mantendo contiguidade.
   - `flow_connect(flow_id, source, source_handle, target, target_handle)` / `flow_disconnect(flow_id, edge_id)`.
   - `flow_deploy(flow_id)` / `flow_stop(flow_id)` — 202 + aguardar via canal da Fase 3 com interesses `{"flow_status": [id], "events": true}`: sucesso quando `flow.status.{id}` publicar `state == "running"|"stopped"`; **falha rápida** em evento `payload.kind == "deploy_rejected"` do flow (payload traz `reason` — ex.: projeto inativo, grafo inválido; `tests/test_supervisor.py:207-236`) ou `state == "failed"` → erro com o `FlowStatus`/razão anexos.
3. Descrições das ferramentas ensinam o agente: portas MPC = ids das variáveis + saídas fixas `local`/`auto`; prefixos `mv_/cv_/co_/dv_`; consultar `block_catalog` antes de montar config.

**Verificação:**
- Unit: mutações sobre o exemplo mínimo da Fase 0 (fixture copiada de `test_flowgraph.py:33-114`) — adicionar/remover/conectar/renumerar preservam validade estrutural do dict; PUT recebe o objeto inteiro.
- E2E: criar flow novo no projeto ativo, montar `opc_read→mpc` com `block_catalog` + mutações, `flow_deploy` até `running`, `flow_stop`, `DELETE` via API (limpeza) — ciclo completo sem tocar nos flows existentes.

**Guardas:** anti-padrões 5, 6; deploy/stop seguem a regra de confirmação (anti-padrão 2); nunca editar flow de outro projeto que não o ativo no e2e.

---

## Fase 5 — Integração: conta `agente`, `.mcp.json`, bootstrap

**Implementar:**
1. `src/ottima_mcp/bootstrap.py` (`python -m ottima_mcp.bootstrap`): com credenciais de ADMIN (`OTTIMA_ADMIN_USERNAME`/`OTTIMA_ADMIN_PASSWORD` — mesmos nomes do `.env` do deploy), cria o usuário `agente` via `POST /api/users` `{username:"agente", name:"Agente MCP", password:<OTTIMA_MCP_PASSWORD>, role:"admin"}`; idempotente (409/nome em uso → ok, reporta "já existe").
2. `.mcp.json` raiz: adicionar entrada `ottima` preservando `code-review-graph`:
   ```json
   "ottima": {
     "type": "stdio",
     "command": "uv",
     "args": ["run", "--project", "packages/ottima-mcp", "ottima-mcp"],
     "cwd": "<raiz do repo>",
     "env": {
       "OTTIMA_URL": "http://localhost:8080",
       "OTTIMA_MCP_USERNAME": "agente",
       "OTTIMA_MCP_PASSWORD": "${OTTIMA_MCP_PASSWORD}"
     }
   }
   ```
   Senha por expansão de env — **nunca literal commitado**.
3. `packages/ottima-mcp/README.md` curto: env vars, bootstrap, registro no Claude Code, aviso do perímetro (token admin, planta virtual — ADR-036 Consequências).

**Verificação:**
- Stack de pé: `python -m ottima_mcp.bootstrap` cria a conta; `GET /api/auth/me` com o token do `agente` devolve `role:"admin"`.
- `claude mcp list` (ou cliente equivalente) enxerga o servidor `ottima` e lista as ~20 ferramentas.
- Um comando de escrita disparado pelo agente aparece no log de eventos com `user:<id do agente>` ≠ id do admin (auditoria distinguindo autoria — consultar `events_query`).

**Guardas:** senha nunca em arquivo versionado; não mexer no seed do backend (`seed.py` intocado).

---

## Fase 6 — Verificação final

1. `uv run ruff check .` e `uv run pytest` (unit, raiz) verdes.
2. E2E dirigido: `OTTIMA_E2E=1 bash deploy/smoke.sh` → `E2E_BASE_URL=http://localhost:8080 ... uv run pytest -m e2e packages/ottima-mcp tests/e2e -v` — inclui os cenários das Fases 2-5.
3. Greps anti-padrão (todos vazios):
   - `grep -rn "fastmcp\|FastMCP" packages/ottima-mcp`
   - `grep -rn "status_code == 202" packages/ottima-mcp | grep -i "sucesso\|success"` (sanidade)
   - `grep -rn "sp_limits\|max_rate" packages/ottima-mcp/src` — pacote não revalida domínio (aparecer só em descrição de ferramenta é aceitável; em `if`, não).
   - `grep -rn "users\|certificates\|system-settings" packages/ottima-mcp/src/ottima_mcp/server.py` — superfície curada respeitada (exceto bootstrap.py, que é utilitário fora do servidor).
4. Smoke vivo com agente real: sessão Claude Code no repo, pedir "liste os MPCs e escreva um SP dentro da faixa" — observar comandado→confirmado e o evento auditado.
5. Docs: ADR-036 Status Proposto→Aceito (decisão do usuário); GLOSSARY já atualizado; CHANGELOG se o projeto adotar.

---

## Fora de escopo (v1) — deliberado

- Cursor `since_id` real no backend (migração da hypertable `events` p/ coluna id) — v2, contrato opaco já reservado.
- Supervisão contínua (watch/stream) — v2.
- Gate de confirmação humana (elicitation) — `if` por ferramenta, reintroduzível; suporte do cliente a verificar antes.
- Papel `engenharia` no backend (containment do token admin) — condição para planta real.
- WebMCP/camada visual no frontend — explicitamente rejeitado na entrevista (ADR-036).
