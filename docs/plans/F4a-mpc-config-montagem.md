# Plano F4a — MPC: config & montagem

> **Para executores agênticos:** execução tarefa a tarefa com subagente por tarefa + revisão independente (padrão F3). Checkboxes das tabelas rastreiam conclusão. Cada tarefa cita os RF que implementa.

**Fase:** F4 (PRD §8) · plano 1 de 2 (decisão A-1 da spec) · 2026-08-04
**Executa:** `docs/specs/F4-mpc.md` §1, §2, §3, §7, §8 (débitos) — o runtime (§4, §5.2, §6) é do plano F4b
**Fontes normativas:** `docs/PRD.md` v1.2 · `docs/adr/ADR-001…024` (prevalecem) · `docs/GLOSSARY.md` · `PRODUCT.md`/`DESIGN.md` (frontend) · specs F1/F2/F3 (com emendas 2026-08-04)
**Objetivo:** flow com bloco MPC **valida, salva e edita** (modal 7 abas, portas dinâmicas) e a montagem do-mpc existe como biblioteca pura testada; deploy de flow com MPC segue **rejeitado** até o F4b (ponte §3.1).
**Stack:** do-mpc ≥5.1 (+casadi transitivo, produção flow-runtime — stack declarada PRD §10) · React Flow existente · nenhuma dep frontend nova.

## Regras globais (valem para todas as tarefas)

1. **Governança:** ADR > PRD > spec > plano. Worktree único da fase `ottimaSystemV3-f4`, branch `f4-mpc` (os dois planos na mesma branch); Conventional Commits pt-BR; identificadores em inglês, strings pt-BR, sem emojis.
2. **Ciclo de conclusão de etapa:** bateria da etapa **toda verde** (pytest; superfícies de UI validadas com a tool nativa `browser`, screenshot por passo). Vermelho ⇒ corrigir ⇒ re-executar ⇒ repetir até verde.
3. **TDD estrito em lógica pura** (CLAUDE.md §Testes): validação/derivação (`flowgraph`), discretização, montagem do-mpc, init bumpless. RED→GREEN→REFACTOR com prova vermelha antes da implementação.
4. **Dependências novas:** somente `do-mpc` (flow-runtime, produção). Qualquer outra exige aprovação do usuário.
5. **Caminho absoluto em toda edição de subagente** (armadilha nº1 do ledger F3: caminho relativo resolve na main).
6. **DoD do plano:** §Aderência ao final; o aceite da FASE fecha só no F4b + `docs/plans/tests-e2e-f4.md`.

## Contratos verbatim (PRD §7.1 v1.2)

| Canal | Produtor | Consumidores | Payload (JSON) |
|---|---|---|---|
| `mpc.state.<flow_id>.<block_id>` | flow-runtime | api(WS) | {modes, status, vars, cost, prediction{t[], cv[][], mv[][]}} |
| `flow.commands` | api | flow-runtime | {flow_id, cmd, args, user, ts} |
| `events` | todos | api(WS→banner), gravação | {ts, severity, origin, message, payload} |

Payload `mpc.state` detalhado: spec F4 §5.1. Config do bloco no `graph_json`: spec F4 §2.1 (esqueleto normativo). Nenhum canal novo (ADR-002).

## Interfaces produzidas (consumidas pelo F4b — assinaturas exatas)

```python
# ottima_core.pubsub (tarefa 0.1)
class ChannelListener:  # canal fixo
    def __init__(self, redis: Redis, channel: str, handler: Callable[[str], Awaitable[None]], *, name: str) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
class PatternListener:  # psubscribe; handler(channel, data)
    def __init__(self, redis: Redis, pattern: str, handler: Callable[[str, str], Awaitable[None]], *, name: str) -> None: ...

# ottima_core.flowgraph (tarefas 0.4/1.1/1.2)
def parse_graph(raw: dict) -> FlowGraph: ...                       # mantida
def validate_graph(graph: FlowGraph, tags: Mapping[int, TagRef]) -> GraphCheck: ...  # mantida
class MpcConfig(BaseModel): ...                                    # espelho tipado do spec §2.1
def derive_horizons(multiplier: int, ts_flow: float, tss: Sequence[float]) -> Horizons: ...  # Horizons{ts_mpc, np, nc}
def mpc_state_dimension(config: MpcConfig, ts_mpc: float) -> int: ...

# ottima_flow_runtime.mpc (tarefas 2.1/2.2/2.3 — puras, sem processo)
def discretize_sopdt(K: float, tau1: float, tau2: float, theta: float, ts: float) -> PairSS: ...
def discretize_iopdt(Ki: float, theta: float, ts: float) -> PairSS: ...   # PairSS{a,b,c,delay}
def build_mpc(config: MpcConfig, ts_flow: float) -> BuiltMpc: ...          # controller do-mpc pronto + índices de var
def init_bumpless(built: BuiltMpc, u_now: Mapping[str, float], y_now: Mapping[str, float], d_now: Mapping[str, float]) -> None: ...

# ottima_core.bus (tarefa 1.3)
class MpcVarState(BaseModel): v: float; sp: float | None = None
class MpcState(BaseModel): ...  # vars: dict[str, MpcVarState] (refina o stub F3; forma PRD intacta)
KIND_MPC_MODE_CHANGED / KIND_MPC_SP_WRITTEN / KIND_MPC_MV_WRITTEN / KIND_MPC_OVERRUN /
KIND_MPC_SOLVER_ERROR / KIND_MPC_SHED / KIND_MPC_ARM_FAILED / KIND_MPC_INPUT_INVALID
```

---

## Etapa 0 — Débitos herdados (spec F4 §8; Etapa 0 por ordem do usuário)

| # | Tarefa | Arquivos | Verificar | Débito/Gov. |
|---|---|---|---|---|
| 0.1 | **`ottima_core.pubsub`**: `ChannelListener`/`PatternListener` com o laço resiliente único (reconexão, confirmação de psubscribe, fechamento defensivo — o comportamento mais completo das 3 cópias, o de `ws.py:195-221`); migrar `services/flow-runtime/src/ottima_flow_runtime/events.py`, `.../snapshot.py` e `services/api/src/ottima_api/ws.py` para consumi-lo | `packages/ottima-core/src/ottima_core/pubsub.py` (novo) · os 3 consumidores · `packages/ottima-core/tests/test_pubsub.py` | pytest: reconexão após queda da fixture Redis; confirmação; stop idempotente; `grep -rn "psubscribe" services packages` só acha o pacote e usos | débito 1 · RNF-05 |
| 0.2 | **Fonte única Pydantic→TS**: `packages/ottima-core/src/ottima_core/contracts_export.py` despeja JSON dos contratos (portas por tipo de bloco, `PortValue`, `FlowStatus`, `MpcState`/`MpcVarState`); `frontend/scripts/generate-contracts.mjs` emite `frontend/src/lib/contracts.gen.ts`; `frontend/package.json:10` ganha `generate:contracts` encadeado em `generate:api`; `graph.ts:86-108` e `nodes/index.tsx:49,64,85-86,108-109` e `useFlowStatus.ts:17-31` passam a importar do gerado | `contracts_export.py` (novo) · `generate-contracts.mjs` (novo) · `contracts.gen.ts` (gerado, commitado) · `frontend/src/features/flows/{graph.ts,nodes/index.tsx,useFlowStatus.ts}` | `npm run generate:api` regenera sem diff espúrio; `npm run build` verde; grep prova ausência de literais de porta fora do gerado | débitos 2+4 · spec §8 |
| 0.3 | **`_project_tags` único**: mover para `ottima_core/tags.py` (`project_tags(session, project_id) -> dict[int, TagRef]`); apagar as cópias de `supervisor.py:567-585` e `services/api/src/ottima_api/routers/flows.py:67-84` | `packages/ottima-core/src/ottima_core/tags.py` (novo) · os 2 consumidores · teste movido junto | pytest dos 2 serviços verde; grep sem duplicata | débito 3 |
| 0.4 | **Cortes de teto**: `supervisor.py` (630) extrai `definition.py` (~200 ln: stage/instanciação de blocos/fiação/`_conn_ids`); `flowgraph.py` (737) vira pacote `flowgraph/` com `parse.py`/`validate.py`/`__init__.py` re-exportando `parse_graph`/`validate_graph` (import público inalterado). Na mesma passada: **notas normativas do banker's rounding** na validação de atraso (ex-`flowgraph.py:530`) e em `blocks/tfs.py:104`, citando spec F4 §3.1 (débito m2) | `services/flow-runtime/src/ottima_flow_runtime/{supervisor,definition}.py` · `packages/ottima-core/src/ottima_core/flowgraph/{__init__,parse,validate}.py` · `blocks/tfs.py` | pytest workspace verde sem mudança de comportamento (refactor puro); `wc -l` < 800 em todos; `lsp references parse_graph` sem quebra de import | débito 6 + m2 · teto CLAUDE.md |
| 0.5 | **`await_until` único**: util compartilhado (`tests/testkit/await_until.py`, importável pelo workspace); apagar as 5 cópias (`services/flow-runtime/tests/conftest.py:58`, `services/opc-worker/tests/conftest.py:35`, `services/recorder/tests/test_backpressure.py:56`, `services/recorder/tests/test_pipeline.py:55`, `tests/opcsim/tests/test_server.py:39`) | util novo · 5 consumidores | pytest workspace verde; grep `def await_until` só no util | débito 7 |
| 0.6 | **script_pool**: guarda do teto C2 no cancelamento repetido (`script_pool.py:262` — respawn pós-cancelamento nunca encolhe o pool) + `pool.stats() -> {size, busy, respawns}` (o `/health` liga no F4b 2.3) | `services/flow-runtime/src/ottima_flow_runtime/script_pool.py` · `services/flow-runtime/tests/test_script.py` | teste de regressão: N ciclos cancel/timeout mantêm `size` constante; `stats()` conta respawns | débito 5 (metade) + m3 |
| 0.7 | **Minors de frontend (m1 + m4, exceto EU nas portas — vai na 4.1)**: `unhandled_exception` no mapa `MOTIVOS` (`frontend/src/features/flows/useLastFlowState.ts:30-36`); saída booleana de Script exibida como booleano; inserção em grade por próximo slot livre (não `nodes.length`); params TFS aceitam vírgula E ponto; "Aplicar" fecha modal via `close()` explícito | `frontend/src/features/flows/{useLastFlowState.ts,nodes/index.tsx,FlowEditorPage.tsx,ConfigModals.tsx}` | `npm run build` + `npm run test:unit` verdes; validação browser na rodada da Etapa 4 | débitos m1+m4 |

**Conclusão:** `uv run pytest` (workspace) + `uv run ruff check . && uv run ruff format --check .` + `npm run build` + `npm run test:unit` verdes. Refactors sem mudança de comportamento — nenhum teste existente reescrito, só movidos.

---

## Etapa 1 — Core: config, validação e derivação (TDD)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 1.1 | **`MpcConfig`** (Pydantic, espelho exato do spec §2.1): `variables{mvs[MvVar], cvs[CvVar], constraints[ConstraintVar], dvs[DvVar]}`, `models{linha→{coluna→PairModel}}`, `multiplier`; `PidBinding` opcional por MV (presente ⇒ write/mode_cmd/readback/target_mode/mode_values obrigatórios; `mode_read_tag_id` opcional — decisão A-8); ids `mv_/cv_/co_/dv_` validados por prefixo; **`derive_horizons`** e **`mpc_state_dimension`** (fórmulas §2.2-5/§2.2-7, puras) | `packages/ottima-core/src/ottima_core/flowgraph/mpc_config.py` · `packages/ottima-core/tests/test_mpc_config.py` | pytest: parse do esqueleto §2.1 verbatim; `derive_horizons(5, 1.0, [600])` → `Horizons(5.0, 120, 30)`; Np<2 e Np>120 detectáveis; dimensão bate à mão num 2×2 com θ | RF-601..604/606 · ADR-013/014 · spec §2.1/§2.2-5 |
| 1.2 | **`validate_graph` libera `mpc`** (remove a rejeição ex-`flowgraph.py:238-241`) e valida §2.2 inteiro: tetos (MVs 1..4, CVs+Restr 1..6, DVs 0..4), matriz (linha ⇒ ≥1 par com MV; MV e DV ⇒ ≥1 par; params por kind), números (§2.2-4), horizontes (Np<2/Np>120 ⇒ erro), integridade de tags do `pid` (§2.2-6), **portas dinâmicas** (entradas = ids CV/Restr/DV **obrigatórias**; saídas = ids MV; numérica estrita) e **warnings** Np>60 / dimensão>120 (§2.2-7); `_conn_ids` coleta tags do config MPC (§2.2-8 — em `definition.py` pós-0.4) | `packages/ottima-core/src/ottima_core/flowgraph/validate.py` · `services/flow-runtime/src/ottima_flow_runtime/definition.py` · `packages/ottima-core/tests/test_flowgraph_mpc.py` | pytest: mesa §2.2 completa (cada regra com caso que reprova E caso que passa; mensagens pt-BR string única); warnings não bloqueiam; `_conn_ids` inclui conexão referenciada só pelo `pid` | RF-601..608 · spec §2.2 |
| 1.3 | **`bus.py`**: `MpcVarState{v, sp?}`; `MpcState.vars: dict[str, MpcVarState]`; `status`/`modes` com chaves normativas §5.1; 8 KINDs novos §5.3; regenerar contratos TS (0.2) | `packages/ottima-core/src/ottima_core/bus.py` · `packages/ottima-core/tests/test_bus_events.py` · `frontend/src/lib/contracts.gen.ts` | pytest: round-trip JSON do §5.1 verbatim (incl. `prediction` vazia fora de AUTO); TS regenerado sem drift | RF-625 · spec §5.1/§5.3 |

**Conclusão:** `uv run pytest packages services/flow-runtime` verde.

---

## Etapa 2 — Montagem do-mpc (biblioteca pura no flow-runtime; TDD)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 2.1 | Dep `do-mpc` no flow-runtime + **`discretize.py`**: SOPDT→2 estados (ZOH exato: pólos `e^(−Ts/τ)`; τ2=0 ⇒ 1ª ordem; τ≈0 ⇒ passagem direta, mesmo limiar do TFS), IOPDT→1 estado (`acc += Ki·Ts·u`), atraso `delay = round(θ/Ts)` (banker's, nota §3.1); `PairSS{a, b, c, delay}` | `services/flow-runtime/pyproject.toml` · `services/flow-runtime/src/ottima_flow_runtime/mpc/discretize.py` · `tests/test_mpc_discretize.py` | TDD: degrau SOPDT vs solução analítica amostrada (erro <1e-6 em regime, <1% no transiente); IOPDT rampa exata; θ desloca exatamente `delay` amostras; `round(2.5)=2` documentado no teste | ADR-013 · spec §3.1 · RF-608 |
| 2.2 | **`builder.py`** (`build_mpc`): agrega pares em LTI bloco-diagonal (atrasos como shift register), estado aumentado `u_prev` por MV, do-mpc `Model('discrete')` com DVs+bias como `_tvp`; objetivo §3.4 (normalização por span; `w_slack = 1e4 × max(w_cv, default 1.0) × priority`; `R_Δu = 0.1`); bounds duros de MV; `\|u−u_prev\| ≤ du_max` e `Δu ≡ 0 p/ k≥Nc` como constraints; `n_horizon=Np`, `t_step=Ts_mpc`, `n_robust=0`, IPOPT silencioso | `services/flow-runtime/src/ottima_flow_runtime/mpc/builder.py` · `tests/test_mpc_builder.py` | TDD: dimensões = `mpc_state_dimension`; degrau de SP grande satura o plano em `du_max`; **precedência: SP fora da faixa da Restrição ⇒ faixa vence** (slack ≈ 0, erro de SP > 0); movimentos nulos após Nc | RF-602/603/605 · ADR-019 · spec §3.2-3.5 |
| 2.3 | **`init_bumpless`** (§3.6, rotina única): `x_ss(u, d)` nos autorreguláveis; estado de saída = CV medida nos integradores; atrasos preenchidos; `u_prev := u_vigente`; `bias := y_medido − C·x`; `set_initial_guess()` | `services/flow-runtime/src/ottima_flow_runtime/mpc/builder.py` · `tests/test_mpc_bumpless.py` | TDD: pós-init, predição em t=0 = y_medido exato; primeira MV do `make_step` dista ≤ `du_max` de u_vigente (autorregulável E integrador); bias corrige erro de ganho de 20% em regime | RF-622/623 · ADR-010 · spec §3.6 |
| 2.4 | **Carga (RNF-02)**: teste `slow` — 2×2 SOPDT, TSS ⇒ Np=60, `make_step` médio e p95 < 70%×Ts_mpc de referência (5 s ⇒ 3,5 s); tempos reportados no log | `services/flow-runtime/tests/test_mpc_load.py` (`@pytest.mark.slow`) | `uv run pytest -m slow services/flow-runtime` verde com margem reportada | RNF-02 · PRD §9-1 |

**Conclusão:** `uv run pytest services/flow-runtime` (incl. `-m slow` uma vez) verde.

---

## Etapa 3 — API: flows aceita MPC; ponte de deploy

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 3.1 | Rotas `/api/flows` inalteradas passam a aceitar grafo com `mpc` (via 1.2); testes de API: 422s (matriz incoerente, Np>120, tag de direção errada, `pid` incompleto), warnings no response do PUT, POST/GET round-trip do config §2.1. **PONTE [remover no F4b 2.2]:** stage em `definition.py` rejeita grafo com `mpc` ⇒ `deploy_rejected` (`reason: "mpc_not_ready"`) — flow salva mas não roda até o F4b | `services/api/tests/test_flows_mpc.py` · `services/flow-runtime/src/ottima_flow_runtime/definition.py` · `services/flow-runtime/tests/test_supervisor.py` | pytest: 422 pt-BR string única (contrato `api.ts` F3); deploy de flow com mpc ⇒ `deploy_rejected` e flow parado; OpenAPI regenerado (`frontend/openapi.json` + `generate:api`) | RF-302 · spec §2.2 · F3 §4.3 |

**Conclusão:** `uv run pytest` (workspace) verde.

---

## Etapa 4 — Frontend: paleta, nó dinâmico e modal 7 abas

> Cada tarefa termina com validação **browser-tool** contra o stack composto (`up -d --build --no-deps frontend`), screenshot por passo; roteiro completo B-F4 em `docs/plans/tests-e2e-f4.md`.

| # | Tarefa | Arquivos | Validação browser | RF/ADR |
|---|---|---|---|---|
| 4.1 | **Paleta + nó**: MPC arrastável (substitui o bloco desabilitado `FlowPalette.tsx:47-78`); nó MPC com portas dinâmicas do config (entradas CV/Restr/DV à esquerda, saídas MV à direita), handles = ids estáveis, rótulo `nome (EU)`; EU nas portas de Script/TFS (m4 restante); visual DESIGN.md §Shapes via contrato gerado (0.2) | `frontend/src/features/flows/{FlowPalette.tsx,nodes/index.tsx,graph.ts}` | B-F4-01 (arrastar MPC; nó com plaqueta e sem portas até configurar) | RF-301 · spec §7.1/§7.2 |
| 4.2 | **Modal — abas Geral · Variáveis · Modelos**: Geral (nome, multiplicador, Ts_mpc derivado read-only); Variáveis (4 listas add/remove, id gerado `mv_<rand>` imutável, nome/EU/kind, `pid` opcional por MV com selects de tag filtrados por direção + `target_mode` + `mode_values`); Modelos (matriz linhas×colunas, célula `enabled` + params conforme kind da linha) | `frontend/src/features/flows/mpc/{MpcModal.tsx,TabGeneral.tsx,TabVariables.tsx,TabModels.tsx}` (novos; 200-400 ln cada) | B-F4-02 (criar 1 MV + 1 CV + 1 DV; matriz aparece; params SOPDT) | RF-601/602/604/607 · spec §7.3 |
| 4.3 | **Modal — abas Horizontes · Restrições & Limites · Pesos · Resumo**: Horizontes (TSS por linha; Ts_mpc/Np/Nc read-only via espelho de `derive_horizons` no contrato gerado; warnings Np>60/dim>120 ao vivo); R&L (faixas, limites, `du_max`, `initial_value`); Pesos (w por CV, priority por Restrição); Resumo (erros bloqueiam salvar, warnings não); vírgula/ponto; "Aplicar" com `close()`; salvar = PUT com 422 exibido como string pt-BR | `frontend/src/features/flows/mpc/{TabHorizons.tsx,TabLimits.tsx,TabWeights.tsx,TabSummary.tsx}` · `MpcModal.tsx` | B-F4-03 (TSS ⇒ Np/Nc mudam ao vivo; warning Np>60; salvar bloqueado com matriz vazia, liberado ao completar) · B-F4-04 (nó re-renderiza portas após salvar; 422 do servidor exibido) | RF-603/605/607/608 · spec §7.3/§7.4 |

**Conclusão:** `npm run build` + `test:unit` verdes; B-F4-01..04 verdes com evidências.

---

## Etapa 5 — Fechamento do plano F4a

| # | Tarefa | Verificar | Governança |
|---|---|---|---|
| 5.1 | Rodada de regressão completa: `uv run pytest` + ruff + `npm run build` + `test:unit` + **L1** + **L2 F1/F2/F3 (24 cenários — zero regressão)** + Playwright F1. Flow com MPC salvo NÃO roda (ponte 3.1 observável via `deploy_rejected`) | tudo verde na mesma rodada | regra global 2 |
| 5.2 | Encerramento parcial: CLAUDE.md §Comandos ganha `generate:contracts`; ledger da fase em `.superpowers/sdd/F4-mpc/progress.md` | seção reflete comandos reais | CLAUDE.md §Comandos |

---

## Aderência (DoD do plano F4a)

| Critério | Tarefas |
|---|---|
| Débitos 1-7 + m1-m4 fechados com prova | 0.1-0.7, 4.1 |
| Flow com MPC valida/salva/edita (RF-601..608, lado config) | 1.1/1.2/3.1/4.2/4.3 |
| Montagem do-mpc provada pura (precedência, bumpless, carga) | 2.1-2.4 |
| Zero regressão F1/F2/F3 | 5.1 |

## RF por tarefa (rastreabilidade)

| RF | Tarefas |
|---|---|
| RF-601 | 1.1, 1.2, 4.2 |
| RF-602 | 1.1, 2.2, 4.2 |
| RF-603 | 1.1, 2.2, 4.3 |
| RF-604 | 1.1, 2.2, 4.2 |
| RF-605 | 2.2, 4.3 |
| RF-606 | 1.1 (runtime no F4b) |
| RF-607 | 4.2, 4.3 |
| RF-608 | 1.2, 2.1 |
| RF-625 | 1.3 (publicação no F4b) |
