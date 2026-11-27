# SPEC — Blocos malha: config completa no editor e tela MALHA

**Data:** 2026-11-27 · **Status:** implementada (plano `docs/superpowers/plans/2026-11-27-malha-config-e-operacao.md`)
**Baseline:** `main` @ `e061827`
**Depende de:** ADR-039 (shell de bloco), ADR-045 (fuzzy_loop multicanal), ADR-034 (espelho de
contrato), ADR-005 (frontend não executa lógica de flow)
**Requisitos:** PRD §5.20, RF-641…RF-646 (Changelog 3.5)
**Componentes afetados:** `frontend` (editor de flow, tela MALHA). Em `ottima-core` entra **um
teste** (sem mudança de código-fonte). **Nenhuma** mudança em `flow-runtime`, API, recorder,
migrations, canais ou no gerador de contratos.

---

## 1. Objetivo

O PID Malha (`pid_loop`) está entregue no servidor e no runtime, mas não pode ser comissionado
pelo produto:

1. **Editor:** o duplo-clique abre o modal só com rótulo, ordem de execução e "Historiar
   portas" — não há formulário do bloco.
2. **Tela MALHA** (`/operacao/loop`): escolher uma malha no combobox não faz nada.

Esta entrega torna o bloco **inteiramente configurável no flow** e a tela MALHA **utilizável
pelo operador**, incluindo tendência PV/SP/OUT. O Fuzzy Malha (`fuzzy_loop`) entra na parte que
compartilha a mesma causa-raiz.

## 2. Diagnóstico (verificado em `e061827`)

| # | Defeito | Onde | Causa |
|---|---|---|---|
| D1 | Modal do `pid_loop` sem campos | `frontend/src/features/flows/config/ModalConfigBloco.tsx:533` e `:654-676` | O `case "pid_loop"` aplica só o rótulo e não há ramo de renderização; o comentário adiava a "sintonia completa" para o plano fuzzy-loop, que não a entregou |
| D2 | Editor descarta config dos blocos malha | `frontend/src/features/flows/graph.ts:1316` (`pid_loop`) e `:1343` (`fuzzy_loop`); tipos `DadosPidLoop`/`DadosFuzzyLoop` em `:263`/`:282` | O normalizador reconstrói `data` só com 10 (PID) ou 13 (fuzzy) campos. Os demais — definidos por import de projeto, MCP ou API — somem ao carregar e **voltam ao default do servidor no primeiro Salvar pelo canvas** |
| D3 | Combobox da MALHA é no-op | `frontend/src/features/loop/LoopOperatePage.tsx:291` e `:339` | `const [params] = useSearchParams()` descarta o setter; `params.set(...)` muta o objeto sem navegar; o `Select` está preso em `value=""` |
| D4 | Sem troca de malha depois de selecionar | `LoopOperatePage.tsx` (`LoopResolvido`) | O combobox só existe no ramo "sem seleção" |
| D5 | Flow parado ⇒ tela vazia | idem, ramo `loop-aguardando` | Sem `LoopState` a página não mostra nem a config, que independe de execução |
| D6 | Barras e campos fixos em 0–100 | idem (`minimo={0} maximo={100}`) | Ignora `sp_lo_lim/sp_hi_lim` e `out_scale_*`, que `GET /api/operate/loop/{flow_id}/{block_id}` já devolve. Com limites editáveis (D1), o `max=100` do input barraria SP válido |
| D7 | Cartão de sintonia incompleto | idem (`loop-sintonia`) | Mostra KC/TI/TD; `LoopTuningOut` já traz N, BETA, GAMMA, GAP_BAND, GAP_GAIN, que a SPEC_PID §8 exige |

D2 é o mais grave: é perda silenciosa de configuração num bloco que escreve na planta.

O servidor (`PidLoopConfig`/`LoopBaseConfig` em
`packages/ottima-core/src/ottima_core/flowgraph/parse.py:540-596`) já valida os 35 campos e o
runtime consome todos (`shell_cfg_from`, `services/flow-runtime/.../definition.py:585-616`;
uso em `blocks/shell/block.py`). Falta só a superfície.

## 3. Metas, não-metas e anti-metas

**Metas**

- M1. Modal do `pid_loop` edita os 35 parâmetros de `PidLoopConfig` (RF-641).
- M2. Modal do `fuzzy_loop` ganha os campos de shell aplicáveis (RF-642).
- M3. Abrir e salvar um flow pelo canvas nunca altera config de bloco malha que o usuário não
  editou (RF-643).
- M4. Tela MALHA no padrão da tela FUZZY: seletor sempre visível, escalas reais, sintonia
  completa, comportamento definido com flow parado (RF-645).
- M5. Tendência PV/SP/OUT na tela MALHA (RF-646).

**Não-metas**

- Sintonia pela tela de operação — continua sendo edição de flow (ADR-039 §4.10).
- `MAX_DT` editável — não é campo de `LoopBaseConfig`; o runtime deriva `10 × Ts`.
- Tracking, override, feedforward, shed e modos remotos no `fuzzy_loop` — o bloco não tem
  essas portas (ADR-045).
- Layout do nó por classe de porta (SPEC_FUZZY §8, "polish posterior" do plano pid-loop).
- Plotar `mode` na tendência — transições já estão em Eventos.
- Refatorar `TrendFuzzy` ou o `MpcModal`.
- Endpoint, canal, tabela ou migration novos.

**Anti-metas** (falha mesmo que "funcione")

- Qualquer lógica de controle, validação de faixa ou cálculo de modo no frontend (ADR-005) —
  o modal coleta, o servidor valida.
- Default de config espelhado no frontend sem teste que o trave contra o servidor (ADR-034).
- Um Salvar pelo canvas que mude `out_hi_lim`, `n`, `ff_*` etc. sem o usuário ter tocado.
- Comando de operação habilitado sobre estado velho de um flow parado.

## 4. Abordagens consideradas

### 4.1 Dados do editor

| | Abordagem | Trade-off |
|---|---|---|
| **Escolhida** | `DadosPidLoop`/`DadosFuzzyLoop` passam a cobrir **todas** as chaves do contrato gerado (`PidLoopConfig`/`FuzzyLoopConfig` de `contracts.gen.ts`, forma gerada); os defaults do servidor são **espelhados à mão** em `registro.ts` e travados por um teste Python | Tipado; é o que o ADR-034 prescreve para leitor de `graph_json`. Custo: quem mudar um default no Pydantic precisa atualizar o espelho — o teste Python fica vermelho e aponta o arquivo |
| Descartada | Gerar a tabela de defaults em `contracts_export.py` | Sem cópia manual, mas o **ADR-034 proíbe** ("Não se gera tabela de defaults"; adendo de 2026-11-27: "default de config de bloco espelhado à mão") — exigiria emenda de ADR |
| Descartada | Normalizador repassa campos desconhecidos sem tipar (`...dados`) | Corrige a perda (D2) mas não dá formulário e foge do padrão tipado de `graph.ts` |

### 4.2 Formato do modal — **decisão do dono: opção A**

| | Abordagem | Trade-off |
|---|---|---|
| **A (escolhida)** | Seções dentro do `ModalConfigBloco` atual, avançadas recolhidas | Formulário único como os demais blocos; reuso entre PID e Fuzzy Malha |
| B | Modal próprio com abas, como o `MpcModal` | Segundo modal para manter; o padrão de abas do MPC desmonta a aba ao trocar e já perdeu campo (`MpcModal.tsx:176-184`) |
| C | Lista única sem recolher | 35 campos sem hierarquia |

### 4.3 Tendência

| | Abordagem | Trade-off |
|---|---|---|
| **Escolhida** | `TrendMalha` novo, irmão de `TrendFuzzy`, sobre as peças compartilhadas de `features/trend/` | Duplica o esqueleto do componente; não toca tela que funciona |
| Descartada | Extrair trend genérico de `TrendFuzzy` e usar nos dois | Menos duplicação, mas refatora tela de operação sem gate automático de navegador (TD-026) |

### 4.4 Escopo da tela MALHA — **decisão do dono: opção C** (seletor + padrão FUZZY + tendência)
### 4.5 Fuzzy Malha — **decisão do dono: opção B** (campos de shell comuns entram)

## 5. Desenho — editor de flow

### 5.1 Defaults do servidor, espelhados à mão (ADR-034)

`registro.ts` ganha duas constantes que espelham, literal a literal, os defaults de
`LoopBaseConfig`/`PidLoopConfig`/`FuzzyLoopConfig` (`parse.py:540-620`):

- `DEFAULT_SERVIDOR_PID_LOOP` — os 32 campos de `PidLoopConfig` que têm default (todos menos
  `sp_hi_lim`, `sp_lo_lim`, `kc`). Atenção a `ti_seconds: 0` e `sp_pv_track_in_man: true`.
- `DEFAULT_SERVIDOR_FUZZY_LOOP` — idem para `FuzzyLoopConfig` (menos `sp_hi_lim`, `sp_lo_lim`,
  `ke`, `ku`, e menos `fll`, que já vem de `PORT_CONTRACTS.fuzzy_loop.default_fll`).

Trava do espelho (ADR-034, "teste próprio"):

- **Python** (`packages/ottima-core/tests/`) — **é a trava de deriva**: compara os defaults de
  `PidLoopConfig`/`FuzzyLoopConfig` (via `model_fields`) com uma tabela literal e, na
  mensagem de falha, manda atualizar `frontend/src/features/flows/registro.ts`. Mudou default
  no servidor ⇒ vermelho. Roda no gate manual `uv run pytest` — **não** no CI (ADR-035), que
  não executa pytest.
- **TS** — não detecta deriva (compara literal com literal); garante duas outras coisas: a
  anotação `Omit<PidLoopConfig, …>` faz o `tsc` acusar campo novo esquecido no espelho, e o
  check de `graph.check.ts` prova que grafo só com os obrigatórios normaliza para a tabela.

Nada é gerado: `contracts_export.py` e `generate-contracts.mjs` não mudam.

### 5.2 Tipos, defaults e normalizador (`graph.ts`, `registro.ts`)

- `DadosPidLoop = DadosBase & PidLoopConfig` e `DadosFuzzyLoop = DadosBase & FuzzyLoopConfig`
  (todas as chaves; mesma forma de `DadosPid`).
- **Dois papéis, duas constantes** — hoje misturados em `PADRAO_PID_LOOP`:
  - `DEFAULT_SERVIDOR_*` (§5.1) é o fallback do **normalizador** para campo ausente no grafo
    gravado. Hoje o normalizador usa `PADRAO_PID_LOOP.ti_seconds = 60` (`graph.ts:1335`),
    enquanto o servidor assume `0`: um PID só-P gravado sem `ti_seconds` viraria PI no
    primeiro Salvar. Isso é corrigido aqui.
  - `PADRAO_PID_LOOP = { ...DEFAULT_SERVIDOR_PID_LOOP, sp_lo_lim: 0, sp_hi_lim: 100, kc: 1,
    ti_seconds: 60 }` é só o **bloco recém-arrastado** (valores de hoje). Idem
    `PADRAO_FUZZY_LOOP` (mantém `ke`, `ku` e demais valores atuais).
  - Campo **obrigatório** ausente (`sp_*_lim`, `kc`, `ke`, `ku`) não ocorre em grafo aceito
    pelo servidor; o fallback é `PADRAO_*`, como hoje.
- O normalizador (`graph.ts:1316` e `:1343`) lê **cada** chave do contrato com o helper do
  tipo certo (`numero`, booleano, enum de `shed_opt`, lista de strings de `permitted`).
  Campos nuláveis (`sp_rate_up`, `sp_rate_dn`, `out_rate_up`, `out_rate_dn`): `null` ou
  ausente ⇒ `null`; número finito ⇒ número.
- **Invariante (RF-643):** para todo grafo aceito pelo servidor,
  `serializar(normalizar(g))` preserva a config dos nós `pid_loop`/`fuzzy_loop` — campo
  presente mantém o valor; campo ausente aparece com o default do servidor (semântica
  idêntica para o runtime).

### 5.3 Formulário (`config/`)

Componentes novos, campos **não-controlados** lidos no Aplicar (padrão do modal):

- `CamposShellMalha` — seções de shell, parametrizado pelo tipo do bloco.
- `CamposPidMalha` — seção Sintonia do PID + `CamposShellMalha` completo.
- `CamposMalhaFuzzy` (existente) — passa a renderizar `CamposShellMalha` no recorte do fuzzy,
  no lugar da grade atual de limites de SP/escala de OUT.
- `montarDadosShellMalha` e `montarDadosPidLoop` em `config/campos.ts`, puros
  (`FormData → dados`), no molde de `montarDadosPid`.

Seções e campos (`id` do input = nome do campo no contrato; `data-testid="config-<id>"`):

| Seção | Campo | Rótulo (pt-BR) | Unidade | PID | Fuzzy |
|---|---|---|---|---|---|
| **Sintonia** (aberta) | `direct_acting` | Ação: Reversa (erro = SP − PV) / Direta (erro = PV − SP) | — | ✔ | já existe |
| | `kc` | Ganho KC | %span/EU | ✔ | — |
| | `ti_seconds` | Tempo integral TI (0 desliga) | s | ✔ | — |
| | `td_seconds` | Tempo derivativo TD (0 desliga) | s | ✔ | — |
| | `n` | Filtro derivativo N (Tf = TD/N) | — | ✔ | — |
| | `beta` | Peso do SP no proporcional (BETA) | 0–1 | ✔ | — |
| | `gamma` | Peso do SP no derivativo (GAMMA) | 0–1 | ✔ | — |
| | `gap_band` | Banda morta (meia-banda; 0 desliga) | EU | ✔ | — |
| | `gap_gain` | Ganho dentro da banda | 0–1 | ✔ | — |
| **Setpoint** (aberta) | `sp_lo_lim`, `sp_hi_lim` | SP mínimo / SP máximo | EU | ✔ | ✔ |
| | `sp_rate_up`, `sp_rate_dn` | Rampa de subida / descida (vazio = sem rampa) | EU/s | ✔ | ✔ |
| | `sp_pv_track_in_man` | SP acompanha a PV em manual | — | ✔ | ✔ |
| **Saída** (aberta) | `out_scale_lo`, `out_scale_hi` | Escala de OUT mínima / máxima — **estrutural** | EU | ✔ | ✔ |
| | `out_lo_lim`, `out_hi_lim` | Limite de saída mínimo / máximo | % | ✔ | ✔ |
| | `out_rate_up`, `out_rate_dn` | Rampa de saída subida / descida (vazio = sem rampa) | %/s | ✔ | ✔ |
| | `out_startup` | Saída de partida | % | ✔ | ✔ |
| | `pv_ftime` | Filtro de PV (0 desliga) | s | ✔ | ✔ |
| **Modos** (aberta) | `permitted` | Modos permitidos (caixas) | — | 6 modos | OOS/MAN/AUTO |
| | `normal` | Modo normal | — | MAN/AUTO/CAS/RCAS | MAN/AUTO |
| | `shed_opt` | Ao perder o modo remoto: ir para AUTO / MAN / modo normal | — | ✔ | — |
| | `shed_no_return` | Não retornar ao modo remoto sozinho | — | ✔ | — |
| **Tracking e override** (recolhida) | `track_enable` | Habilitar tracking (`trk_in_d`) | — | ✔ | — |
| | `track_in_manual` | Tracking também em manual | — | ✔ | — |
| | `trk_val` | Valor de tracking | % | ✔ | — |
| | `lo_val` | Valor de override local (`lo_in_d`) | % | ✔ | — |
| | `use_pv_for_bkcal` | BKCAL_OUT usa a PV | — | ✔ | — |
| **Feedforward** (recolhida) | `ff_enable` | Habilitar feedforward (`bias_in`) | — | ✔ | — |
| | `ff_gain` | Ganho | — | ✔ | — |
| | `ff_scale_lo`, `ff_scale_hi` | Escala do sinal mínima / máxima | EU | ✔ | — |

Regras do formulário:

- **Ação só por `direct_acting`.** `kc` é `> 0` no servidor; o texto de ajuda **não** repete o
  "Kc negativo inverte" do bloco `pid` (convenção diferente, GLOSSARY "Ganho (Kc)").
- **Seções recolhidas** usam `<details>` nativo: os inputs permanecem no DOM e entram no
  `FormData` mesmo fechados. Nada é desmontado ao recolher.
- **`permitted`:** uma caixa por modo comandável. No `pid_loop`, CAS/RCAS/ROUT ficam
  desabilitadas enquanto a porta correspondente (`cas_in`/`rcas_in`/`rout_in`) não tiver
  aresta chegando, com o motivo em texto associado por `aria-describedby` — é a mesma regra
  que o save aplica (`_check_loop_nodes`, `validate.py:627`); o modal já recebe `edges`. Modo
  remoto já marcado cuja porta foi desligada continua marcado e editável (o 422 do save
  orienta) — o modal nunca desmarca sozinho. Valor de `permitted` que não tem caixa (`iman`,
  `lo`, aceitos pelo servidor) é preservado como veio.
- **Aviso estrutural (RF-644):** junto de `out_scale_*`, o mesmo texto que `CamposMalhaFuzzy`
  já usa para FLL/canais — a troca re-instancia o bloco no próximo deploy e a malha aterrissa
  em MAN com a saída mantida.
- **Campos não exibidos no fuzzy** (shed, tracking, FF) não são tocados pelo Aplicar: o valor
  de `no.data` é preservado.
- **Validação de valores** segue no servidor (422 em pt-BR no Salvar), como nos demais blocos.
  Nenhuma regra de faixa é replicada no cliente.
- **RBAC:** o `fieldset` do modal já entra desabilitado para operador; nada novo.

### 5.4 Nó no canvas

Sem mudança de layout. `NoPidLoop` ganha uma linha de resumo "Ação — direta/reversa" (é o
parâmetro que o usuário citou primeiro e o erro de comissionamento mais comum).

## 6. Desenho — tela MALHA (`/operacao/loop`)

```
MALHA   [ Flow A · PID_MALHA            ▾ ]
┌──────────────────────────────────────────────────────────────┐
│ PID_MALHA   ALVO AUTO   REAL AUTO                            │
│ [OOS] [MAN] [AUTO] [CAS] [RCAS] [ROUT]                       │
│ PV  ▓▓▓▓▓▓░░░░  152,3                                        │
│ SP  ▓▓▓▓▓░░░░░  150,0                                        │
│ OUT ▓▓▓░░░░░░░   37,5                                        │
│ SP [______] Enviar        OUT (%) [______] Enviar            │
└──────────────────────────────────────────────────────────────┘
┌ Sintonia vigente (leitura) ─┐ ┌ Trend  PV · SP · OUT ─────────────────┐
│ ...                         │ │ [30 min ▾]  <  >  Exportar CSV  Reset │
└─────────────────────────────┘ └───────────────────────────────────────┘
```

- **Seleção** — molde de `FuzzyOperatePage.tsx:288-330`: `useSearchParams` com setter;
  combobox sempre visível com `value` = malha selecionada; sem seleção válida na URL, um
  efeito seleciona a primeira malha com `replace: true`. Estados vazio/erro/carregando
  mantidos.
- **Ao vivo** é um predicado puro, testado, com **quatro** termos — todos necessários, porque
  o `/ws` não tem replay e o provider retém o último quadro para sempre:
  1. canal aberto (`canal.estado === "aberto"`);
  2. último `flow_status` do flow em `running`;
  3. existe `LoopState` do bloco;
  4. esse `LoopState` é **novo**: o `ts` dele difere do `ts` que estava retido quando a
     página montou ou quando o canal reabriu pela última vez. Sem isto, voltar à tela depois
     de o flow parar (a página desmontada não assina `flow_status` e perde o quadro de
     parada) ou reconectar depois de uma queda mostraria o quadro antigo como atual.
  A página passa a assinar `flow_status: [flowId]` além de `loop_state`; o tipo
  `EstadoConexaoCanal` de `CanalAoVivo.tsx:80` passa a ser exportado (só o tipo).
  O `desired_state` REST do flow (`useFlow(flowId)`, a fonte que o editor usa em
  `rotuloDeEspera`, `useFlowStatus.ts:55`) **não** entra no predicado — é cache de
  requisição e pode estar velho; serve só para escolher o texto do aviso.
- **Fora do ao vivo:** botoeira e escritas desabilitadas, barras e badges sem valor ("—") e
  aviso `data-testid="loop-sem-estado"`: com o canal fora, o rótulo de conexão que a casa já
  usa; flow comandado a parar ou com `flow_status` `stopped` ⇒ "Flow parado — sem estado ao
  vivo"; `failed` ⇒ "Flow em falha — sem estado ao vivo"; nos demais casos (rodando, quadro
  novo ainda não chegou) ⇒ "Aguardando estado ao vivo da malha…". Num flow lento a espera
  dura até um Ts — é o preço de não mostrar número velho.
- **Limite conhecido:** se o processo `flow-runtime` morrer sem publicar parada, com a página
  aberta e o canal vivo, o último quadro continua valendo como atual — nenhum dos quatro
  termos enxerga isso. É o mesmo limite de toda tela de operação hoje; fechá-lo exige
  expiração por tempo e pertence ao plano advisor/013, para as três telas de uma vez.
- **Relação com o plano 013** (`docs/reports/advisor/013`, TODO): isto entrega, para a tela
  MALHA, o que o Passo 3 do 013 pede. O 013 continua dono do MPC e do FUZZY; ao executá-lo, a
  checagem de drift dele vai acusar `features/loop` — a parte de malha já estará feita.
- **Escalas** (de `useLoopConfig`): barras PV e SP em `[sp_lo_lim, sp_hi_lim]`; barra OUT em
  `[out_scale_lo, out_scale_hi]` (o `out` do `LoopState` já é EU); input de SP com
  `min/max` = limites de SP; input de OUT (%) com `min/max` = `[out_lo_lim, out_hi_lim]` —
  os mesmos limites que a API valida (`operate.py:354-358`).
- **Sintonia vigente** (somente leitura, visível também com flow parado): PID — KC, TI, TD,
  N, BETA, GAMMA, GAP_BAND, GAP_GAIN; fuzzy — KE, KDE, KU, TF_DE; ambos — Ação e limites de
  SP e de OUT. Tudo já está em `LoopDetailOut`.
- **Multicanal** (`n_loops > 1`): comportamento atual mantido — uma seção por canal.
- **Heatmap** do `fuzzy_loop`: mantido como está.

### 6.1 Tendência (`TrendMalha`)

- Variáveis: `pv`, `sp`, `out` por canal; ids no formato da API — sem sufixo no canal 0,
  `pv:1`, `sp:1`… nos demais (`_parse_loop_var_ids`, `history.py:238`).
- Histórico: `GET /api/history/loop` com polling de 5 s; hook `useHistoryLoop` no molde de
  `useHistoryFuzzy`. Ponta viva: `LoopState` por canal via `useBordaViva`. A PV é plotada como
  o recorder a grava — **inclusive com `pv_ok = false`** (`loop_samples` não tem coluna de
  qualidade; filtrar só a ponta viva faria o ponto reaparecer no poll seguinte). A falta de
  qualidade aparece no badge "PV sem qualidade" do faceplate.
- Recursos idênticos ao trend FUZZY (RF-544): `JanelaTempo` (default 30 min), voltar/avançar
  com janela congelada, badge bruto/1 min, escala Y por pena persistida
  (`ottima.loop.escalas.v1:<flow>/<bloco>`), valor no cursor, export CSV, reset de layout.
  Teto de 6 penas (`LIMITE_PENAS`); pré-seleção = PV/SP/OUT do canal 0.
- EU da legenda: PV e SP sem EU declarada (o bloco não a conhece); OUT idem.
- Disponível com flow parado (é histórico).

## 7. Testes

Lógica pura em `*.check.ts` (`npm run test:unit`), TDD:

| Alvo | Casos mínimos |
|---|---|
| Normalizador `pid_loop`/`fuzzy_loop` | grafo com os 35 campos fora do default sobrevive ao round-trip (RF-643); grafo só com os obrigatórios carrega com `DEFAULT_SERVIDOR_*` (inclui `ti_seconds = 0`, não 60); bloco recém-arrastado nasce com `PADRAO_*`; rampa `null` ↔ vazio |
| `montarDadosPidLoop` / `montarDadosShellMalha` | caixa desmarcada ⇒ `false`; rampa em branco ⇒ `null`; `permitted` a partir das caixas; recorte fuzzy não toca shed/tracking/FF |
| Modos remotos × arestas | CAS desabilitado sem aresta em `cas_in`; habilitado com; modo já marcado não é desmarcado |
| Seleção da MALHA | resolução de `?flow=&bloco=`; fallback na primeira malha; chave inexistente |
| Escalas e "ao vivo" | percentual da barra com limites ≠ 0–100; cada um dos quatro termos derruba o ao vivo sozinho (canal fora, `flow_status` parado, sem estado, quadro retido de antes da montagem/reconexão); texto do aviso por causa |
| Histórico da malha | ids por canal; mescla histórico + ponta viva |

Python (`ottima-core`): o teste de trava do espelho de defaults (§5.1).

Gates: `ruff`, `npm run typecheck`, `test:unit`, `build`, `generate:contracts` +
`git diff --exit-code` (tem de sair limpo — nada gerado muda), `uv run pytest` do
`ottima-core`.

Navegador (roteiro L3, stack com bundle novo — sem spec Playwright nova nesta entrega, mesma
política das superfícies pós-F1):

- B-ML-01: duplo-clique no PID Malha ⇒ seções visíveis; editar ação, KC, limite de saída e
  rampa; Aplicar, Salvar, recarregar ⇒ valores persistem.
- B-ML-02: marcar CAS sem `cas_in` ligado ⇒ caixa desabilitada com motivo.
- B-ML-03: MALHA abre na primeira malha; trocar no combobox muda a URL e o faceplate.
- B-ML-04: flow parado ⇒ aviso, comandos desabilitados, sintonia e trend histórico visíveis.
- B-ML-05: flow rodando ⇒ barras na escala configurada, comando de SP em AUTO, trend com
  ponta viva.
- B-ML-06: Fuzzy Malha — seções Setpoint/Saída/Modos no modal; round-trip.

## 8. Documentação tocada

- `docs/PRD.md` — Changelog 3.5; §5.20 nova (RF-641…646); §7.1 registra `loop.state` e §7.3
  registra `/operate/loop`, `/history/loop` e `loop.state` no `/ws` (item 1 da proposta
  `docs/reports/advisor/019`, omissão do ADR-039 — os RFs novos citam esses contratos).
- `docs/specs/SPEC_PID_with_SHELL.md` §8 e `SPEC_FUZZY_with_SHELL.md` §8 — ponteiro para
  esta spec no item "Sintonia"/"Faceplate".
- `CLAUDE.md` — seção Comandos: nota da tela MALHA e dos `data-testid` `loop-*`.

## 9. Deixado ao implementador

- Divisão de arquivos da tela MALHA (extrair seletor/faceplate/sintonia de
  `LoopOperatePage.tsx`, hoje com 362 linhas) e se os helpers de histórico da malha reusam
  `mesclarHistoricoVivo` de `features/trend/bordaViva.ts` diretamente.
- Textos de ajuda de cada campo (pt-BR, vocabulário do GLOSSARY).
- Grade e espaçamento das seções, dentro dos componentes shadcn/ui e do padrão de
  `CamposBlocoPid`.
