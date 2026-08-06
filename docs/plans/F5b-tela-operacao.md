# Plano F5b — Operação: tela de operação

> **Para executores agênticos:** execução tarefa a tarefa com subagente por tarefa + revisão independente (padrão F3/F4, skill subagent-driven-development; ledger em `.superpowers/sdd/F5b-tela-operacao/progress.md`). Checkboxes das tabelas rastreiam conclusão. **Pré-requisito: plano F5a concluído** (Etapa 5 do F5a verde) — este plano consome os contratos, rotas e o canal WS de lá. **Toda tarefa que entrega UI termina com validação browser** (tool nativa `browser`, screenshot por passo — regra herdada da F2).

**Fase:** F5 (PRD §8) · plano 2 de 2 (decisão A-12 da spec) · 2026-08-06
**Executa:** `docs/specs/F5-operacao.md` §7, §9.1 (frontend) e §9.2 (gate L3) — dados & serviços são do plano F5a
**Fontes normativas:** `docs/PRD.md` v1.3 · `docs/adr/ADR-001…024` (prevalecem) · `docs/GLOSSARY.md` · `PRODUCT.md`/`DESIGN.md` (autoridade visual) · specs F1-F4 (com emendas §1.3) · spec F5
**Objetivo:** operador conduz LOCAL/REMOTO/MAN/AUTO e escreve SP/MV pela UI com pendente-até-confirmar; predição sobreposta ao histórico (âncora `prediction.ts`); faixa anunciadora real; `/eventos`; Home visão geral; F-3 (golden Python→TS) fechado; **gate completo da fase verde**.
**Stack:** nenhuma dependência frontend nova — uPlot existente (trend F2) re-vestido; pilha React/router existente. Tudo pt-BR, GLOSSARY, sem emojis.

## Regras globais

Idênticas ao plano F5a (governança, worktree `ottimaSystemV3-f5`/branch `f5-operacao`, ciclo verde por etapa, TDD com prova RED em lógica pura, caminho absoluto em subagente, credenciais inline, lacuna ⇒ perguntar), mais:

1. **Validação browser por tarefa de UI** contra o stack composto (`cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --no-deps frontend`), em `http://localhost:8080`; screenshot por passo. O roteiro completo B-F5 (`docs/plans/tests-e2e-f5.md`) roda só no gate (Etapa 7) — a validação por tarefa é o esqueleto do cenário correspondente, não o roteiro inteiro.
2. **`data-testid` novos são estáveis e semânticos** (convenção do repo: `operate-*`, `faceplate-*`, `eventos-*`, `home-*`), criados junto com o componente — o roteiro L3 depende deles.
3. **Identificadores do frontend seguem a convenção existente da base** (funções pt-BR como `mesclarPorts`/`derivarHorizontes` onde já é o padrão; componentes/arquivos em inglês onde já é o padrão, ex. `AnnunciatorBar.tsx`).
4. Testes puros em arquivos `*.check.ts` colocalizados (`npm run test:unit`), padrão do repo.

## Interfaces consumidas (produzidas no F5a — não redefinir)

`contracts.gen.ts` com `MpcState.ts`/`MpcPrediction.ts` · `GET /api/history/mpc` · `GET /api/operate/mpcs` · `GET /api/health/workers` · WS `{"subscribe": {"events": true}}` com fanout `{"channel": "events", "data": …}` · `KIND_SCRIPT_RECOVERED` · `frontend/openapi.json` regenerado (`npm run generate:api`). Semântica da predição: spec F5 §3 (nota normativa — `mv` degrau `stepped align: -1`; âncora `prediction.ts`, NUNCA `MpcState.ts`).

## Interfaces internas deste plano (consumidas entre tarefas — assinaturas exatas)

```ts
// frontend/src/app/CanalAoVivo.tsx (tarefa 1.1) — socket único de sessão
type Interesse = { flow_status?: number[]; mpc_state?: string[] };   // mpc_state ids "flowId/blockId"
function CanalAoVivoProvider({ children }): JSX.Element;             // montado no AppShell; `events` sempre assinado
function useAssinatura(interesse: Interesse): void;                  // registra no mount, remove no unmount
function useCanalAoVivo(): {
  flowStatus: ReadonlyMap<number, FlowStatus>;                       // redutor preserva mesclarPorts
  mpcStates: ReadonlyMap<string, MpcState>;                          // chave "flowId/blockId"
  eventos: readonly EventMessage[];                                  // mais novo primeiro, teto de memória
  estado: "conectando" | "aberto" | "reconectando" | "sessao_invalida";
};

// frontend/src/app/alarmes.ts (tarefa 2.1) — pura, stateless
type CondicaoAtiva = { familia: "par" | "estado" | "contador" | "ttl";
  kind: string; origin: string; desde: string; severity: "warning" | "alarm"; message: string };
function resolverAlarmes(eventos: readonly EventMessage[],
  flowStatus: ReadonlyMap<number, FlowStatus>, mpcStates: ReadonlyMap<string, MpcState>,
  agora: Date): CondicaoAtiva[];

// frontend/src/features/operate/pendencia.ts (tarefa 4.2) — redutor puro
type Pendencia = { alvo: string; valorComandado: unknown; expiraEm: number };
function reduzirPendencia(atual: Pendencia | null, acao:
  { tipo: "comandar"; alvo: string; valor: unknown; tsMpcSegundos: number; agora: number } |
  { tipo: "estadoPublicado"; state: MpcState; agora: number } |
  { tipo: "tique"; agora: number }): Pendencia | null;
```

---

## Etapa 1 — Canal único de sessão (spec §7.1; F5R-04/22)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 1.1 | **Provider `CanalAoVivo`** no `AppShell`: **um** WebSocket por aba, vivo enquanto houver sessão; reconexão/backoff/1008 num lugar só. O ciclo de vida inteiro muda de casa, não só o hook (F5R-22): `abrirCanalAoVivo` e `AmbienteAoVivo` (`useFlowStatus.ts:191-289`) migram para o provider **com o harness de dublês que os testa** (o check de desmonte migra junto); `analisarMensagem` generaliza por canal (hoje filtra por `PREFIXO_CANAL` — `useFlowStatus.ts:52`); `comandoAssinatura` vira gerador de **delta multi-canal** (subscribe/unsubscribe só do que mudou); `mesclarPorts` ("ports vazio preserva o anterior" — `useFlowStatus.ts:92-94`) sobrevive no redutor por canal — sem ela o canvas apaga a cada transição; `events` sempre assinado (o banner é do shell); reconexão reassina tudo; 1008 ⇒ `sessao_invalida`, sem reconexão (contrato F3) | `frontend/src/app/CanalAoVivo.tsx` (novo, 300-400 ln) · `frontend/src/app/AppShell.tsx` · `frontend/src/app/canalAoVivo.check.ts` (novo) · `frontend/src/features/flows/useFlowStatus.ts` | RED: máquina do canal — agregação de interesses de N páginas, deltas mínimos, reconexão reassina, 1008 sem reconexão, redutor preserva `mesclarPorts`, roteamento por canal (`flow.status.*`/`mpc.state.*`/`events`) | decisão A-6 · §7.1-1/2/3 |
| 1.2 | **`useAssinatura` + `useFlowStatus` reimplementado sobre o provider** preservando assinatura pública idêntica (§7.1-4 — o editor F3 não muda de forma; só a implementação consome do provider); páginas registram interesse via `useAssinatura({flow_status: [id]} \| {mpc_state: ["fid/bid"]})` | `frontend/src/app/CanalAoVivo.tsx` · `frontend/src/features/flows/useFlowStatus.ts` · `useFlowStatus.check.ts` (migração do harness) | `useFlowStatus.check.ts` continua verde sem reescrever asserts de comportamento; `npm run build` + `test:unit` verdes. Browser: editor F3 com flow rodando — canvas vivo segue atualizando (regressão visual) | §7.1-2/4 |

**Conclusão:** `npm run build` + `npm run test:unit` verdes; validação browser da 1.2 com screenshot.

---

## Etapa 2 — `resolverAlarmes` e faixa anunciadora real (spec §7.2; F5R-02/03/19)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 2.1 | **`resolverAlarmes` pura** (tabela normativa §7.2-1 — cessação espelha o latch dos produtores, 4 famílias): **par de eventos** `comm_failure`→`comm_restored` · `flow_failed`→`flow_deployed` · `script_timeout`\|`script_error`→`script_recovered`, cessa com o evento par da **mesma `origin`**; **estado publicado** `mpc_solver_error`/`mpc_input_invalid`/`mpc_shed`, cessa quando o `mpc.state` do bloco publica `solver ≠ "error"`/`input_valid = true`/`armed = true`; **contador publicado** `flow_overrun`/`mpc_overrun`, cessa com **duas publicações consecutivas** do mesmo produtor com `overruns` inalterado (espelho do rearme — `scheduler.py:232`, `blocks/mpc.py:313`); **TTL** só `mpc_arm_failed`: 60 s sem repetição do mesmo `kind`+`origin`. Sem parâmetro de períodos (nenhuma família depende de Ts); condição ativa **sem estado da origem ⇒ ativa**, nunca silenciosa | `frontend/src/app/alarmes.ts` (novo) · `frontend/src/app/alarmes.check.ts` (novo) | RED: os casos de §9.1 — par por origem (2 origens independentes); estado publicado cessa/não cessa; contador com `overruns` inalterado ×2 (e NÃO cessa com 1); TTL expira/renova; sem estado ⇒ ativa | decisão A-4 · RF-705 · ADR-020 |
| 2.2 | **Bootstrap na montagem do shell** (§7.2-3 — dois grupos; sem ele, alarmes-fantasma de até 1 mês no reload): famílias "par de eventos": `GET /api/events?origin=flow:<id>&limit=20` por flow do projeto ativo + `origin=conn:<id>` por conexão (≤10 + ≤5 chamadas, cache 60 s — padrão `useLastFlowState.ts:112-133`), condição ativa se o **último** evento da família naquela origem é o de abertura; demais famílias: `GET /api/events?severity=warning&start=<agora−2h>&limit=500` + idem `alarm` (uma severidade por chamada — `schemas/events.py`). Depois do bootstrap, só WS | `frontend/src/app/bootstrapAlarmes.ts` (novo — fetch dos dois grupos + cache 60 s) · `frontend/src/app/bootstrapAlarmes.check.ts` (novo) · `frontend/src/app/CanalAoVivo.tsx` (consome no mount) | RED: bootstrap dos dois grupos (último evento = abertura ⇒ ativa; par já fechado ⇒ inativa; janela 2 h aplicada) | F5R-03 · §7.2-3 |
| 2.3 | **Assinatura sob demanda dirigida por condição ativa** (§7.1-5; F5R-04): quando `resolverAlarmes` acusa condição de família "estado publicado" ou "contador publicado", o **provider** assina `mpc_state`/`flow_status` daquela origem e mantém até cessar; cessou ⇒ unsubscribe. Em operação normal o shell assina só `events`. É o provider, não a página — a faixa não depende da tela aberta. NUNCA assinar `flow_status` de todos os flows por precaução (traria a tabela `ports` inteira de cada flow a cada varredura; fila por socket = 8 com drop-oldest — `ws.py:45-48,68-74`) | `frontend/src/app/CanalAoVivo.tsx` · `canalAoVivo.check.ts` | RED: condição ativa gera `subscribe` da origem; cessação gera `unsubscribe`; sem condição, só `events` assinado | F5R-04 · §7.1-5 |
| 2.4 | **`AnnunciatorBar` real** (hoje stub F1 — `AnnunciatorBar.tsx:1-13`): colapsada em 1 linha quando vazio ("Sem alarmes ativos"); com condições: contagem por severidade + lista expansível (cor + ícone + texto — Regra do Canal Redundante, DESIGN §Layout); clique navega a `/eventos`; sem ACK (ADR-020). Alimentada por `useCanalAoVivo()` + `resolverAlarmes` | `frontend/src/app/AnnunciatorBar.tsx` · `frontend/src/app/AppShell.tsx` | Browser: congelar o watchdog do opcsim (tag `ns=2;s=sim.control.freeze_*`) ⇒ faixa acusa `comm_failure` em tela de engenharia; restaurar ⇒ cessa (esqueleto do B-F5-06); screenshot dos dois estados | RF-705 · decisão A-4 |

**Conclusão:** `npm run test:unit` verde; browser da 2.4 com evidências.

---

## Etapa 3 — Navegação, Home e `/eventos` (spec §7.3/§7.5)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 3.1 | **Rotas e nav** (decisão A-10): rotas novas `/operacao`, `/operacao/:flowId/:blockId`, `/eventos`; nav do shell em dois grupos: **Operação · Eventos** \| Conexões · Tags · Flows · Trend; RBAC: operação e eventos são de **operador** (admin herda); telas de engenharia intocadas (mutação só admin — `useAuth.tsx:81-83` `useCanMutate`) | `frontend/src/app/router.tsx` · `frontend/src/app/AppShell.tsx` | Browser: nav renderiza os dois grupos; login operador acessa `/operacao` e `/eventos`; rotas de engenharia continuam acessíveis (leitura); screenshot | decisão A-10 · §7.3-1/2 |
| 3.2 | **Home = visão geral do console** (§7.3-3; DESIGN §Layout): lâmpadas dos 3 workers via `GET /api/health/workers`, polling 5 s — **lâmpada de estado, nunca só cor** (rótulo junto); flows do projeto ativo com estado ("Último estado", padrão F3 §6.1 — `useLastFlowState`); atalho por flow para a operação quando houver MPC (via `GET /api/operate/mpcs`) | `frontend/src/app/HomePage.tsx` · hook novo `frontend/src/app/useWorkersHealth.ts` (polling 5 s) | Browser: Home com 3 lâmpadas `up` + flows listados + atalho de operação visível no flow com MPC (esqueleto do B-F5-08); screenshot | RNF-07 · decisão A-10 |
| 3.3 | **Página `/eventos`** (§7.5; decisão A-13; RF-803): tabela ts desc — severidade (lâmpada + texto), origem, mensagem, payload expansível (`<details>`); filtros severidade/origem/período via `GET /api/events`; **origem como select** (F5R-24), populado de `GET /api/flows` + `GET /api/operate/mpcs` + `GET /api/connections` + origens distintas do resultado carregado (a API filtra igualdade exata — `routers/events.py:43`; a UI nunca pede texto livre); sem filtro de período ⇒ eventos novos do WS que casem com os filtros entram no topo com **marca de recém-chegado**; com período ⇒ consulta histórica pura, sem prepend | `frontend/src/features/events/EventsPage.tsx` (novo) · `frontend/src/features/events/eventos.ts` (lógica pura de filtro/prepend) · `eventos.check.ts` (novo) · `frontend/src/app/router.tsx` | RED: prepend só sem filtro de período; casamento com filtros ativos; marca de recém-chegado; dedupe. Browser: filtros funcionam, prepend vivo com marca (esqueleto do B-F5-07); screenshot | RF-803 · F5R-24 |

**Conclusão:** `npm run build` + `test:unit` verdes; browser 3.1-3.3 com evidências.

---

## Etapa 4 — Tela `/operacao/:flowId/:blockId` (spec §7.4; RF-701/702/704; ADR-016)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 4.1 | **Seletor e roteamento** (§7.4-1/2): `/operacao` sem parâmetro lista via `GET /api/operate/mpcs`; **um único MPC ⇒ redirect direto**; o MPC aberto vive na URL (F5 do browser restaura — sala de controle); a página assina `mpc_state` do bloco + `flow_status` do flow via `useAssinatura`; revalidação ao montar/focar (refetch de `/api/operate/mpcs`) — MPC ausente (flow excluído/projeto trocado) ⇒ volta ao seletor com aviso | `frontend/src/features/operate/OperateSelectorPage.tsx` (novo) · `frontend/src/features/operate/OperatePage.tsx` (novo) · `frontend/src/features/operate/useMpcs.ts` (novo) · `frontend/src/app/router.tsx` | Browser: seletor lista; com 1 MPC redireciona; URL restaura a tela; MPC removido ⇒ aviso + seletor (esqueleto do B-F5-01); screenshot | RF-701 · §7.4-1/2 |
| 4.2 | **Redutor pendente-até-confirmar** (§7.4-4; F5R-18; Regra do Estado Publicado): 1 gesto, sem diálogo; ao comandar, posição/valor em fantasma + outline azul até o `mpc.state` seguinte confirmar; sem materialização em **3×Ts_mpc (mín. 5 s)** ⇒ reverte ao publicado — janela estritamente **maior** que a confirmação do runtime (`CONFIRM_MISSES_LIMIT = 2` ticks — `mpc_arming.py:34`), para o desfecho publicado (confirmação ou `mpc_arm_failed`) sempre chegar antes do timeout do cliente | `frontend/src/features/operate/pendencia.ts` (novo) · `pendencia.check.ts` (novo) | RED: materializa quando o estado publicado confirma; ignora estado que não confirma o alvo; expira em 3×Ts_mpc revertendo; piso de 5 s aplicado quando 3×Ts_mpc < 5 s | RF-704 · §7.4-4 |
| 4.3 | **Faceplate principal** (§7.4-3): plaqueta `nome · flow`; comutadores LOCAL/REMOTO e MAN/AUTO (**MAN/AUTO só renderiza em REMOTO** — ADR-010); lâmpadas: flow (`flow.status.state` + motivo), solver (`ok\|building\|overrun\|error\|idle` — **`building` é o estado de partida esperado do deploy**, §6.2, com comutadores desabilitados + rótulo do motivo enquanto durar — Regra do Canal Redundante), `input_valid`; contadores `overruns`/`last_solve_ms` em mono tabular (Regra do Número Tabular); comandos → `POST /api/operate/{fid}/{bid}/mode` com pendente-até-confirmar (4.2) | `frontend/src/features/operate/FaceplatePrincipal.tsx` (novo) · `OperatePage.tsx` | Browser: deploy recém-feito mostra `building` com comutadores desabilitados; armar LOCAL→REMOTO(MAN)→AUTO com fantasma+outline até confirmar (esqueleto dos B-F5-02/03); screenshot por transição | RF-701 · ADR-010 · §6.2 |
| 4.4 | **Faceplates de variável** (§7.4-5; RF-702): um por MV/CV/Restrição/DV — **barra vertical com escala demarcada** (`limits`/`sp_limits`/`range` — DESIGN §Shapes, convenção intocável), PV grande mono tabular + EU; CV: entrada de SP **só em AUTO** (fora: SP rastreado dessaturado — PV-tracking), clamp client-side em `sp_limits` (espelho leve; servidor é a barreira); MV: entrada manual **só em REMOTO+MAN**, clamp em `limits`, fora do modo campo desabilitado com o valor publicado; Restrição: faixa low/high na barra, somente leitura; DV somente leitura; toda escrita → `POST /sp`\|`/mv` → pendente-até-confirmar → `flow.commands` → runtime → estado republicado (auditoria é do runtime — F4 §4.8) | `frontend/src/features/operate/FaceplateVariavel.tsx` (novo) · `frontend/src/features/operate/clamp.ts` (novo) · `clamp.check.ts` | RED: clamps (dentro/fora/borda de `sp_limits`/`limits`). Browser: SP em AUTO materializa; MV editável só em REMOTO+MAN; campos desabilitados fora do modo (esqueleto do B-F5-04); screenshot | RF-702/704 · §7.4-5 |

**Conclusão:** `npm run build` + `test:unit` verdes; browser 4.1-4.4 com evidências.

---

## Etapa 5 — Trend central com predição (spec §7.4-6; §3; decisão A-11)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 5.1 | **Dados do trend**: `GET /api/history/mpc` — janelas 15 min · 30 min · 2 h · 8 h (default **30 min**), polling 5 s; **borda viva**: cada `mpc.state` (ts + vars) faz append nas séries — o "agora" nunca espera o poll; o poll re-sincroniza (dedupe por ts); montagem de séries em função pura | `frontend/src/features/operate/trendOperacao.ts` (novo — lógica pura) · `frontend/src/features/operate/useHistoryMpc.ts` (novo) · `trendOperacao.check.ts` (novo) | RED: append da borda viva; re-sync do poll sem duplicar pontos; troca de janela recarrega | RF-703 · §7.4-6 |
| 5.2 | **Overlay de predição**: âncora `t_abs[k] = prediction.ts + t[k]` (§3.5 — NUNCA `MpcState.ts`: o resultado publicado foi calculado na fronteira anterior, F5R-01); CVs/Restrições tracejadas no **mesmo matiz mais claro** com fade ao horizonte; **MVs como degraus fantasma `stepped align: -1`** (§3.3 — `align: +1` deslocaria o plano em 1×Ts_mpc e é **proibido**; `mv[0]` = u_prev vigente entrando no ciclo); linha-cursor "agora"; eixo futuro dimensionado por Np×Ts_mpc; quadro com `t: []` (fora de AUTO) ⇒ overlay some **sem apagar as séries** (§3.4); pena de SP = Azul Industrial (DESIGN §Primary) **dessaturada nos trechos com `auto = false`** (SP em PV-tracking não é SP comandado — §2.2-1, F5R-21); Restrição com banda low/high sombreada no Poço | `frontend/src/features/operate/TrendOperacao.tsx` (novo — uPlot re-vestido, molde `TrendChart.tsx`/`trendTheme.ts`) · `trendOperacao.ts` · `trendOperacao.check.ts` | RED: âncora `prediction.ts` (série futura começa em prediction.ts, não em ts); `align: -1` na config das penas de MV; `t: []` remove overlay preservando histórico; SP dessaturada exatamente onde `auto=false` | §3 · §7.4-6 · ADR-016 |
| 5.3 | **Defaults e legenda** (decisão A-11; F5R-16): CVs (PV + SP) ligadas **até o teto de 8 penas**, na ordem do config; Restrições ligadas como banda low/high com a pena de PV contando no teto; MVs **opt-in** pela legenda clicável; acima de 8 penas o excedente nasce desligado e a legenda o indica | `TrendOperacao.tsx` · `trendOperacao.ts` · `trendOperacao.check.ts` | RED: seleção default respeita teto 8 e ordem do config; excedente desligado. Browser: trend com histórico sólido → linha-agora → predição tracejada **partindo do agora sem degrau na emenda**; alternar MV pela legenda; janelas trocam (esqueleto do B-F5-05); screenshot | decisão A-11 · §7.4-6 |

**Conclusão:** `npm run build` + `test:unit` verdes; browser 5.3 com evidências.

---

## Etapa 6 — F-3: vetores-golden Python→TS (spec §7.6; decisão A-9; F5R-13)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 6.1 | **Export Python**: módulo novo `ottima_core.mpc_golden_export` executável por `uv run python -m ottima_core.mpc_golden_export` — emite JSON **determinístico** (chaves ordenadas, sem timestamps) com o escopo §7.6-2: `derive_horizons` (Ts_mpc/Np/Nc), dimensão de estados, tetos 1..4/1..6/0..4, limiares Np<2/Np>120/Np>60/dim>120, banker's rounding, e **um caso por regra** de `_check_mpc_caps`/`_check_mpc_matrix`/`_check_mpc_numbers`/`_check_mpc_horizons` com o **veredito** (regra que reprovou; aprovado/reprovado; warning ou erro — não o texto pt-BR, que é livre); teste em ottima-core compara a saída com o JSON **commitado** e falha se divergir ("regenere o golden") — mudança no Python também vira vermelho (§7.6-4, drift bidirecional) | `packages/ottima-core/src/ottima_core/mpc_golden_export.py` (novo) · `packages/ottima-core/tests/test_mpc_golden_export.py` (novo) · `frontend/src/features/flows/mpc/mpcLogic.golden.json` (gerado, **commitado**) | RED: export determinístico (duas execuções idênticas) E export × JSON commitado iguais | dívida F-3 · §7.6-1/2/4 |
| 6.2 | **Lado TS**: `mpcLogic.golden.check.ts` (novo, colocalizado a `mpcLogic.ts`) assere **igualdade campo a campo** contra o golden: `derivarHorizontes` (`mpcLogic.ts:219-229`), bankers (`:235-241`), `dimensaoEstado` (`:248-268`), tetos (`:205-207`), e o espelho de vereditos `validarConfigMpc`/`paramsValidosParaKind` (`:283-442`) — divergência do lado TS vira teste vermelho. A F5 não adiciona regra espelhada nova (§7.6-5 — validação de SP/MV é servidor + runtime); o golden congela as existentes | `frontend/src/features/flows/mpc/mpcLogic.golden.check.ts` (novo) | RED: golden com um valor adulterado de propósito falha; golden real passa; `npm run test:unit` verde | dívida F-3 · §7.6-3/5 |

**Conclusão:** `uv run pytest packages` + `npm run test:unit` verdes — o espelho está congelado dos dois lados.

---

## Etapa 7 — Gate final da fase F5

| # | Tarefa | Verificar | Governança |
|---|---|---|---|
| 7.1 | **Rodada de gate completa** desde `down -v` (**só com autorização explícita do usuário + dump prévio**) + `--build`: `uv run pytest` (workspace, incl. `-m slow`) + ruff → `cd frontend && npm run build && npm run test:unit` → **L1** (`OTTIMA_E2E=1 bash deploy/smoke.sh`, incl. workers + políticas mpc_samples) → **L2** 41 cenários (`uv run pytest -m e2e tests/e2e -v`) → Playwright F1 (serializado após a L2, credenciais inline) → **L3 = roteiro `docs/plans/tests-e2e-f5.md` INTEIRO** (tool `browser`, screenshot por passo, **executado pelo controlador** — a tool é bloqueada a subagentes). Qualquer vermelho ⇒ corrigir ⇒ rodada completa de novo (nunca re-executar só o cenário que falhou) | tudo verde na mesma rodada; evidências em `.superpowers/sdd/F5-operacao/evidencias-l3/` | spec §9 · aceite PRD §8-F5 |
| 7.2 | **Encerramento**: CLAUDE.md §Comandos (rotas/telas novas; L2 = 41); relatório de gate `.superpowers/sdd/F5-operacao/RELATORIO-GATE-F5.md` (template F3/F4); revisão ampla da branch (leitura de conjunto além do gate, padrão F3); merge `--no-ff` na main **após aceite do usuário** | seção reflete comandos reais; relatório completo; revisão sem Critical/Important aberto | CLAUDE.md §Workflow |

---

## Aderência ao aceite F5 (PRD §8) — Definition of Done da FASE

| Critério | Tarefas que o provam |
|---|---|
| **Operador conduz LOCAL/REMOTO/MAN/AUTO** | 4.2/4.3 (comutadores + pendente-até-confirmar; `building` visível na janela de build) + B-F5-03 + E2E-F4-03/07/08 (regressão) |
| **Escreve SP/MV** | 4.4 + B-F5-04 |
| **Predição sobreposta ao histórico** | 5.1/5.2/5.3 + teste de âncora do F5a (1.2, `prediction.ts == ts − Ts_mpc`) + E2E-F5-06 + B-F5-05 |
| **Eventos/banner** | 2.1-2.4 (4 famílias espelhando o latch; bootstrap por origem) + 3.3 + B-F5-06/07 |
| **Auditoria** | runtime F4 §4.8 (já audita) + `/eventos` exibe (B-F5-04/07) |

**A fase só encerra com a rodada de gate da Etapa 7 inteira verde**, incluindo o roteiro browser completo de `docs/plans/tests-e2e-f5.md`.

## Rastreabilidade (RF/decisão por tarefa)

| Norma | Tarefas |
|---|---|
| RF-701 (seleção/condução) | 4.1, 4.3 |
| RF-702 (faceplates) | 4.4 |
| RF-703 (trend com histórico + predição) | 5.1, 5.2, 5.3 |
| RF-704 (escrita SP/MV via REST) | 4.2, 4.3, 4.4 |
| RF-705 (faixa anunciadora) | 2.1, 2.2, 2.3, 2.4 |
| RF-803 (página de eventos) | 3.3 |
| RNF-07 (heartbeat na UI) | 3.2 |
| ADR-010 (MAN/AUTO só em REMOTO) | 4.3 |
| ADR-016 (predição volátil, nunca persistida) | 5.2 |
| ADR-020 (eventos, sem ACK) | 2.4, 3.3 |
| Decisões A-4/A-6/A-10/A-11/A-13 | 2.1-2.4 / 1.1-1.2 / 3.1-3.2 / 5.3 / 3.3 |
| F5R-02/03/04/13/16/18/21/22/24 | 2.1 / 2.2 / 2.3 / 6.1-6.2 / 5.3 / 4.2 / 5.2 / 1.1 / 3.3 |
| Dívida F-3 | 6.1, 6.2 |
