# Plano F4b — MPC: runtime & modos

> **Para executores agênticos:** execução tarefa a tarefa com subagente por tarefa + revisão independente (padrão F3). Checkboxes das tabelas rastreiam conclusão. Cada tarefa cita os RF que implementa. **Pré-requisito: plano F4a concluído** (Etapa 5 do F4a verde) — este plano consome as interfaces de lá.

**Fase:** F4 (PRD §8) · plano 2 de 2 (decisão A-1 da spec) · 2026-08-04
**Executa:** `docs/specs/F4-mpc.md` §4, §5, §6, §9 — config/montagem/débitos são do plano F4a
**Fontes normativas:** `docs/PRD.md` v1.2 · `docs/adr/ADR-001…024` (prevalecem) · `docs/GLOSSARY.md` · specs F1/F2/F3 (com emendas) · spec F4
**Objetivo:** bloco MPC **executa**: processo dedicado, orçamento 70%, modos LOCAL/REMOTO/MAN/AUTO com bumpless e tracking, `/api/operate`, `mpc.state` no barramento e no `/ws`; gate completo da fase verde.
**Stack:** nada novo além do F4a (do-mpc já declarado lá).

## Regras globais

Idênticas ao plano F4a (governança, ciclo verde por etapa, TDD em lógica pura, caminho absoluto em subagente). Branch `f4-mpc` continua; **remoção da ponte F4a §3.1 acontece na tarefa 2.2 deste plano**.

## Interfaces consumidas (produzidas no F4a — não redefinir)

`ottima_core.pubsub.{ChannelListener,PatternListener}` · `ottima_core.flowgraph.{MpcConfig,derive_horizons,mpc_state_dimension,parse_graph,validate_graph}` · `ottima_flow_runtime.mpc.{discretize_sopdt,discretize_iopdt,build_mpc,init_bumpless}` · `ottima_core.bus.{MpcState,MpcVarState,MpcPrediction,channel_mpc_state,KIND_MPC_*}` · `ottima_core.tags.project_tags` · `ValueSnapshot` (F3) · `Block`/`PortSample` (F3).

## Interfaces internas deste plano (assinaturas exatas — consumidas entre tarefas)

```python
# services/flow-runtime/src/ottima_flow_runtime/mpc/worker.py (tarefa 1.1) — processo filho
@dataclass(frozen=True)
class SolveRequest:  # picklável
    y: dict[str, float]; u_applied: dict[str, float]; d: dict[str, float]
    sp: dict[str, float]; reinit: bool
@dataclass(frozen=True)
class SolveResult:  # picklável
    u_plan: dict[str, float]           # primeiro movimento por MV
    prediction_t: list[float]; prediction_cv: list[list[float]]; prediction_mv: list[list[float]]
    cost: float; status: str           # "ok" | "no_convergence" | "error"
    wall_ms: float; detail: str = ""
def worker_main(conn: Connection, config_json: str, ts_flow: float) -> None: ...

# services/flow-runtime/src/ottima_flow_runtime/mpc/host.py (tarefa 1.2) — lado runtime
class MpcHost:
    def __init__(self, block_id: str, config: MpcConfig, ts_flow: float, *, worker_target: Callable = worker_main) -> None: ...
    async def start(self) -> None            # spawn + build assíncrono; ready=False até confirmar
    @property
    def ready(self) -> bool: ...             # building concluído
    def dispatch(self, req: SolveRequest) -> bool: ...   # False se ocupado/indisponível; nunca bloqueia
    def poll(self) -> SolveResult | None: ...            # consome resultado pronto (uma vez)
    def stats(self) -> dict: ...             # {alive: bool, respawns: int, last_solve_ms: float | None}
    async def stop(self) -> None: ...        # encerra processo
    # deadline interno: 70% × Ts_mpc a partir do dispatch ⇒ kill + respawn em background + resultado "overrun"

# services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py (tarefa 2.1)
class MpcBlock(Block):
    def __init__(self, block_id: str, *, config: MpcConfig, ts_flow: float,
                 snapshot: ValueSnapshot, host: MpcHost, publish: Callable[[MpcState], Awaitable[None]],
                 write_opc: Callable[[OpcWrite], Awaitable[None]], emit_event: Callable[..., Awaitable[None]]) -> None: ...
    # input_ports = ids de CVs+Restrições+DVs (ordem do config); output_ports = ids de MVs
    async def step(self, inputs: Mapping[str, PortSample]) -> dict[str, PortSample]: ...
    async def command(self, cmd: str, args: dict, user: str | None) -> None: ...  # mpc_mode|mpc_sp|mpc_mv
    def health(self) -> dict: ...            # {mode, overruns, last_solve_ms, worker: host.stats()}
```

---

## Etapa 1 — MpcWorker: processo dedicado (decisão A-3)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 1.1 | **`worker.py`**: `worker_main` roda no filho (`multiprocessing` contexto `spawn`, padrão do script_pool): `build_mpc(MpcConfig.model_validate_json(config_json), ts_flow)` no boot → manda `("ready", dim)`; loop `conn.recv()`: `SolveRequest.reinit ⇒ init_bumpless` antes do `make_step`; devolve `SolveResult` (predição extraída do controller; exceção ⇒ `status="error"` com traceback em `detail`, worker segue vivo; não-convergência do IPOPT ⇒ `status="no_convergence"` mantendo estado) | `services/flow-runtime/src/ottima_flow_runtime/mpc/worker.py` · `tests/test_mpc_worker.py` | pytest com processo real e modelo 1×1 rápido: ready chega; round-trip solve; `reinit` ⇒ primeira MV ≤ du_max do `u_applied`; exceção vira `status="error"` sem matar o worker | RF-403/621..624 · ADR-004/014 · spec §4.1 |
| 1.2 | **`host.py`**: spawn+build assíncronos (`ready=False`, `status building`); `dispatch` não-bloqueante (ocupado ⇒ `False`); deadline `0.7 × Ts_mpc` do dispatch ⇒ **kill do processo + respawn em background** (rebuild + próximo dispatch exige `reinit=True`) + resultado sintético `status="overrun"`; `poll()` entrega uma vez; crash espontâneo detectado (sentinel) ⇒ respawn + resultado `status="error", detail="crash"`; `worker_target` injetável para teste determinístico (worker que dorme) | `services/flow-runtime/src/ottima_flow_runtime/mpc/host.py` · `tests/test_mpc_host.py` | pytest: worker lento injetado ⇒ kill no deadline, `respawns` incrementa, dispatch durante rebuild ⇒ `False`; worker morto à força ⇒ respawn sozinho; `stop()` idempotente e sem processo órfão (verificar via `psutil`-free: `Process.is_alive()`) | RF-624 · ADR-014 · spec §4.1/§4.2 |

**Conclusão:** `uv run pytest services/flow-runtime/tests/test_mpc_worker.py services/flow-runtime/tests/test_mpc_host.py` verde; nenhum processo órfão após a suíte.

---

## Etapa 2 — Bloco MPC, supervisor e saúde

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 2.1 | **`blocks/mpc.py`**: portas por config (ordem §5.1); máquina de modos (§4.3/§4.4): LOCAL ⇒ MV=readback (`snapshot`, com `pid`) ou hold `initial_value`/último (sem `pid`), **nenhum** `opc.writes`; REMOTO+MAN ⇒ MV=manual clampado; REMOTO+AUTO ⇒ último plano aplicado; fronteira `n mod multiplier == 0` (contador desde o deploy): em AUTO com entradas quentes+válidas ⇒ `host.dispatch(SolveRequest)`; resultado via `poll()` **aplica só na fronteira de varredura seguinte** (buffer interno — determinismo RF-401); resultado `status="overrun"` ⇒ mantém MV + `overruns++` + `mpc_overrun` warning (dedupe); `status∈{"no_convergence","error"}` ⇒ mantém MV + `mpc_solver_error` alarm com `reason` no payload (§4.9); invalidez ⇒ pula solve + saídas `ok=false` + suprime writes + `mpc_input_invalid` dedupe; cold ⇒ `null_outputs`; SP PV-tracking fora de AUTO, congela ao entrar; com `pid` e REMOTO ⇒ `opc.writes` a cada varredura (`source="flow:<fid>/block:<bid>"`); publica `MpcState` na cadência Ts_mpc + em transição (§5.2), `prediction` vazia fora de AUTO, `status.solver ∈ {ok,overrun,error,building,idle}` | `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py` · `tests/test_mpc_block.py` | pytest com clock controlado + host fake: tabela de modos completa (MV por modo); aplicar-na-fronteira (resultado no meio da varredura NÃO muda porta); overrun mantém MV + evento; `no_convergence` ⇒ `mpc_solver_error` sem kill; tracking segue readback; writes suprimidos em LOCAL e sob invalidez; SP congela no valor rastreado | RF-501(analogia)/606/621..625 · spec §4.2/§4.3/§4.6/§4.9 |
| 2.2 | **Supervisor/definition**: instanciar `MpcBlock` no stage (**remove a PONTE F4a §3.1** — `deploy_rejected mpc_not_ready` morre aqui); handlers novos no dict de comandos (`supervisor.py:202`): `mpc_mode`/`mpc_sp`/`mpc_mv` roteados ao bloco (`flow_id` rodando + `block_id` existe, senão log e ignora — padrão F3 §2.2-7); transições §4.4: LOCAL→REMOTO escreve `mode_cmd=target` por MV com `pid` e entra MAN; confirmação `mode_read` em 2×Ts_mpc senão volta LOCAL + `mpc_arm_failed{no_confirm}`; MAN→AUTO exige `host.ready` + entradas ok (senão `mpc_arm_failed{worker_not_ready\|cold_input\|invalid_input}`); shed: `mode_read ≠ target` por 2 execuções ⇒ LOCAL + `mpc_shed`; **stop gracioso devolve** (`mode_cmd=auto`) antes de cancelar a task; hot-swap com bloco mpc alterado ⇒ host novo + shed + `mpc_mode_changed{reason:"hot_swap"}`; eventos materializados com `user` no payload (`mpc_mode_changed`/`mpc_sp_written`/`mpc_mv_written`) | `services/flow-runtime/src/ottima_flow_runtime/{supervisor,definition}.py` · `tests/test_supervisor_mpc.py` | pytest com Redis fixture: cada linha da tabela §4.4 (sucesso E falha); comandos idempotentes; `man_auto` em LOCAL ignorado; clamps; shed em exatamente 2 execuções; stop publica `mode_cmd=auto` no `opc.writes` antes do fim; hot-swap zera worker e sheda | RF-621..623/704(metade runtime) · ADR-010/011 · spec §4.4/§4.5/§4.7/§4.8 |
| 2.3 | **`/health`** (débito 5, fim): flows ganham `mpc: {<block_id>: MpcBlock.health()}`; script_pool `stats()` (F4a 0.6) exposto em `script_pool: {size, busy, respawns}` | `services/flow-runtime/src/ottima_flow_runtime/main.py` · `tests/test_health_mpc.py` | pytest: payload do `/health` com os campos §4.10; L1 assere na Etapa 5 | RNF-07 · spec §4.10 |

**Conclusão:** `uv run pytest services/flow-runtime` verde.

---

## Etapa 3 — API `/api/operate` e fanout WS

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 3.1 | **Router `/api/operate`** (§6.1): `POST /{flow_id}/{block_id}/mode {axis, value}` · `/sp {var_id, value}` · `/mv {var_id, value}`; `require_operator`; valida contra o `graph_json` (bloco é `mpc`; var da categoria certa; `sp_limits`/`limits` ⇒ 422 pt-BR string única); publica `FlowCommand{cmd: mpc_mode\|mpc_sp\|mpc_mv, args, user}` ⇒ **202**; nenhum evento pela API (runtime audita — §4.8); OpenAPI regenerado | `services/api/src/ottima_api/routers/operate.py` (novo) · `services/api/src/ottima_api/main.py` (include_router) · `services/api/tests/test_operate.py` · `frontend/openapi.json` + `generate:api` | pytest: RBAC (operador pode, anônimo 401); 422 de faixa/categoria/bloco inexistente; 202 + comando publicado (assinante de teste); axis/value enum | RF-704 (caminho REST) · ADR-015/020 · spec §6.1 |
| 3.2 | **WS `/ws` fanout `mpc_state`** (§6.2): `_apply_client_message` (`ws.py:245-272`) aceita chave `mpc_state` com ids `"<flow_id>/<block_id>"`; hub ganha segundo `PatternListener` (`mpc.state.*`, pacote pubsub F4a 0.1) roteando `{"channel": "mpc.state.<fid>.<bid>", "data": {…}}`; escopo F5 (eventos/valores) continua fora | `services/api/src/ottima_api/ws.py` · `services/api/tests/test_ws_mpc.py` | pytest: subscribe ⇒ recebe payload §5.1 publicado na fixture Redis; unsubscribe para; `flow_status` continua funcionando; token inválido fechado | spec §6.2 · decisão A-6 |

**Conclusão:** `uv run pytest` (workspace) verde.

---

## Etapa 4 — Integração L2 (malha fechada MPC↔TFS via API real)

> Setup comum no conftest: projeto → conexão opcsim → tags do `pid` (write/mode_cmd/mode_read/readback como tags do opcsim) → flow com MPC(1 MV com `pid`, 1 MV direta, 1 CV selfreg, 1 Restrição integrating, 1 DV) + TFS fechando a malha → helpers `/api/operate`. Reusa fixtures F2/F3 (`tests/e2e/conftest.py`).

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 4.1 | **E2E-F4-01..05**: 01 deploy ⇒ `mpc.state` na cadência Ts_mpc, boot LOCAL, `status building→idle`; 02 422s (matriz incoerente, Np>120, tag direção errada); 03 armar LOCAL→REMOTO(MAN)→AUTO **sem salto** (ΔMV 1ª execução ≤ du_max, série de `mpc.state`); 04 AUTO converge \|CV−SP\| < 2% do span em ≤ 20×Ts_mpc (malha TFS); 05 SP conflitante com faixa da Restrição ⇒ faixa respeitada, SP sacrificado | `tests/e2e/test_f4_mpc.py` · `tests/e2e/conftest.py` (helpers novos) | 5 cenários verdes contra o compose real | Aceite PRD §8-F4 · spec §9.2 |
| 4.2 | **E2E-F4-06..10**: 06 overrun (config pesado ≥10× o orçamento: Ts_flow=0,5, N=1, Np=120, dim>150) ⇒ MV congelada + `mpc_overrun` + contador; 07 AUTO→LOCAL congela MV e `mode_cmd=mode_values.auto` chega ao opcsim; 08 `/operate` RBAC + 422 de faixa + `mpc_mv` fora de MAN não materializa; 09 shed: escrever `mode_read ≠ target` no opcsim ⇒ 2 execuções ⇒ LOCAL + `mpc_shed`; 10 fanout WS de `mpc.state` + hot-swap do config (mudar peso) ⇒ shed + worker novo + flow segue rodando | `tests/e2e/test_f4_failure.py` · `tests/e2e/test_f4_ws.py` | 5 cenários verdes; total L2 da fase = 10 | RF-624 · spec §4.5/§4.7/§9.2 |

**Conclusão:** `uv run pytest -m e2e tests/e2e -v` — 34 cenários (5 F1 + 9 F2 + 10 F3 + 10 F4) verdes. Precondições §9.3 da spec (serializar com Playwright; flow-runtime recém-subido para o L1).

---

## Etapa 5 — Gate final da fase F4

| # | Tarefa | Verificar | Governança |
|---|---|---|---|
| 5.1 | **Rodada de gate completa** desde `down -v` (com autorização + dump prévio) + `--build`: `uv run pytest` (workspace, incl. `-m slow` carga) + ruff → **L1** (smoke + campos `/health` novos) → **L2** 34 cenários → Playwright F1 + `npm run test:unit` → **L3 = roteiro `docs/plans/tests-e2e-f4.md` INTEIRO** (browser-tool, screenshot por passo, executado pelo controlador — tool `browser` é bloqueada a subagente). Vermelho ⇒ corrigir ⇒ repetir a rodada completa | tudo verde na mesma rodada; evidências salvas | spec §9 · aceite PRD §8-F4 |
| 5.2 | Encerramento: CLAUDE.md §Comandos (L2 = 34 cenários; `/api/operate`; `generate:contracts` se ainda não registrado); relatório de gate `.superpowers/sdd/F4-mpc/RELATORIO-GATE-F4.md` (template F3); revisão ampla da branch (padrão F3 — leitura de conjunto além do gate); merge `--no-ff` na main **após aceite do usuário** | seção reflete comandos reais; relatório completo; revisão sem Critical/Important aberto | CLAUDE.md §Workflow |

---

## Aderência ao aceite F4 (PRD §8) — Definition of Done da FASE

| Critério | Tarefas que o provam |
|---|---|
| **Assume/devolve sem salto de MV** | F4a 2.3 (TDD bumpless) + 2.1/2.2 (modos) + 4.1 (E2E-F4-03) + 4.2 (E2E-F4-07) |
| **Restrição vence CV** | F4a 2.2 (TDD precedência) + 4.1 (E2E-F4-05) |
| **Overrun mantém MV + alarme** | 1.2 (host deadline) + 2.1 (bloco) + 4.2 (E2E-F4-06) |
| Modal com abas / montagem / multiplicador / orçamento | F4a (4.2/4.3, 2.1-2.4) + 1.1/1.2 + roteiro B-F4 |

**A fase só encerra com a rodada de gate da Etapa 5 inteira verde**, incluindo o roteiro browser completo de `docs/plans/tests-e2e-f4.md`.

## RF por tarefa (rastreabilidade)

| RF | Tarefas |
|---|---|
| RF-403 | 1.1, 1.2 |
| RF-606 | 2.1, 4.1 (E2E-F4-01) |
| RF-621 | 2.1, 2.2, 4.1 (E2E-F4-03) |
| RF-622 | 2.1, 2.2, 4.2 (E2E-F4-07/09) |
| RF-623 | 2.1, 2.2, 4.1 (E2E-F4-03) |
| RF-624 | 1.2, 2.1, 4.2 (E2E-F4-06) |
| RF-625 | 2.1, 3.2, 4.1/4.2 (E2E-F4-01/10) |
| RF-704 (REST) | 3.1, 4.2 (E2E-F4-08) |
