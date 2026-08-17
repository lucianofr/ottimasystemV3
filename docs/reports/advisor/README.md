# Planos de melhoria — auditoria do advisor

Gerados em 2026-08-16 sobre o commit `8f9fe76` (branch `improve`, worktree
`.worktrees/improve`). Execute na ordem abaixo, salvo o que as dependências disserem. Cada
executor: leia o plano inteiro antes de começar, honre as Condições de PARADA e atualize a
sua linha na tabela ao terminar.

**Por que `docs/reports/advisor/` e não `plans/`**: neste repo `docs/plans/` já significa "plano de
fase do PRD §8" (`CLAUDE.md:82`), com processo próprio, e `docs/` é normativo — proibido de
editar sem o processo do item 4 do `CLAUDE.md`. Um `plans/` na raiz leria como a mesma
coisa. Estes são planos de conserto pontual, não de fase.

## Ordem de execução e status

| Plano | Título | Prioridade | Esforço | Depende de | Status |
|---|---|---|---|---|---|
| 004 | Flaky do `ts` do MPC contra `flow.status` | P1 | S | — | **FEITO** — **na `main`** (via `improve`) |
| 001 | Falha silenciosa de `recv()` nos pools de worker | P1 | S | 004 (satisfeita) | **FEITO** — **na `main`** (via `improve`) |
| 003 | Limite de tentativas no login | P1 | S | — | **FEITO** — **na `main`**; tranca **provada ao vivo**: 21 tentativas passam, da 22ª vem 429, solta em ~2 s |
| 005 | Editor de flow fora do bundle inicial | P2 | S | — | **FEITO** — **na `main`**; ganho foi degradado pelo ARCH-18 e **restaurado pelo 006** |
| 006 | Registro de bloco sem arrastar o React Flow | P1 | M | 005 | **FEITO** — `exec/006` @ `f777a12`, revisado e **mesclado na `main`** (`622272e`); ganho restaurado, verificado no estado mesclado |
| 002 | Tema reativo no trend de operação | P1 | S | — | **FEITO** — `exec/002b` @ `144d600`, mesclado (`df9c5c0`); `PW-OP-13` **verde em browser** contra stack reconstruído |
| 007 | Varredura de fibra do `PW-OP-11` sem teto arbitrário | P1 | S | 002 (regressão dele) | **FEITO** — `exec/007` @ `b10f637`, revisado e **mesclado na `main`** (`1572849`); **12 passed**, zero flaky |
| 008 | Trava de CI para o chunk inicial + `TD-026` | P1 | S | 006 | **FEITO** — `exec/008` @ `c81fc2a`, revisado e **mesclado na `main`**; RED/GREEN provados, 4 caminhos testados |

Valores de status: TODO · EM ANDAMENTO · FEITO · BLOQUEADO (com o motivo em uma linha) ·
REJEITADO (com a justificativa em uma linha).

**Gates de stack ficam com o revisor, por decisão.** O stack docker de 9 serviços do dono está
no ar com planta simulada viva, `deploy/.env` só existe na árvore da `main` (gitignored), e
`frontend/playwright.config.ts:11` aponta `baseURL` para `http://localhost:8080` — o container
do dono, servindo o bundle da `main`. Um executor que rodasse Playwright de dentro da sua
worktree (a) validaria o bundle da `main` e não a própria edição, dando **verde falso**;
(b) violaria `fullyParallel: false, workers: 1` ("backend compartilhado com estado real",
`playwright.config.ts:5-6`) se houvesse mais de um; e (c) derrubaria o flow em execução do
dono, porque `frontend/e2e/fixtures.ts::criarAmbiente` ativa projeto próprio. Por isso os
executores de 002/003/005 foram proibidos de rodar `npm run e2e`, `npx playwright test` sem
`--list`, `deploy/smoke.sh`, `pytest -m e2e` e QUALQUER `docker compose` — em especial o
`up -d --build --no-deps frontend` que aparece na tabela de comandos do plano 003 e
reconstruiria o container do dono. Eles entregam código + gates offline (typecheck, build,
`test:unit`, `nginx -t`, tamanho de chunk, `playwright --list`); a verificação de browser é
executada depois, **serializada, contra um stack só**.

## Notas de dependência

- **001 depende de 004, e é uma dependência dura.** O critério de conclusão do 001 manda
  rodar `uv run pytest services/flow-runtime/tests -q`, e essa pasta contém
  `test_supervisor_mpc.py::test_mpc_state_ts_de_execucao_bate_bit_a_bit_com_flow_status`,
  que **já é flaky em `8f9fe76`**: passa 3/3 isolado (~11 s) e falha ao rodar o arquivo
  inteiro (28 testes, 127 s). Como esse arquivo exercita `MpcHost` diretamente com spawn
  real de processo, um executor do 001 veria o vermelho e concluiria — erradamente — que a
  edição dele em `host.py` causou a falha. O 004 conserta a barreira do teste e remove a
  ambiguidade. O 001 também carrega esse aviso inline, porque o executor lê o plano, não
  este índice.
- 002, 003 e 005 são independentes entre si e de tudo o mais: arquivos disjuntos
  (`TrendOperacao.tsx`, `nginx.conf`, `router.tsx`), gates disjuntos.
- 003 e o achado de cabeçalhos de hardening (abaixo) tocam o MESMO arquivo
  (`frontend/nginx.conf`). Se ambos forem executados, faça em commits separados — o 003 diz
  explicitamente para não misturar.
- **Trabalho em paralelo na `main`, detectado em 2026-08-16.** Existe a branch
  `fix/arch-review-20260815` (commit `79c39cf`, "legenda de tendência mostra valor corrente e
  EU na linha" = **ARCH-04**), mais stashes e modificações não commitadas em
  `frontend/src/features/{operate/trendOperacao.ts,trend/useHistory.ts,fuzzy/historicoFuzzy.ts}`
  (**ARCH-02**), `packages/ottima-core/src/ottima_core/contracts_export.py` (**ARCH-06**),
  `bus.py`, `scheduler.py` e `services/flow-runtime/tests/test_mpc_builder.py`. Nada disso
  colide com o escopo declarado dos planos 001-005 hoje, mas é a MESMA área de feature do
  plano 002 (`TrendOperacao.tsx` fica ao lado de `trendOperacao.ts` e de `LegendaOperacao.tsx`,
  este último explicitamente fora de escopo no 002 por ser ARCH-04). **Antes de executar o
  002, rode a checagem de drift dele** — se `TrendOperacao.tsx` tiver sido tocado por esse
  trabalho, o plano precisa de reconcile antes de ir para um executor.

## Registro de execução

### 008 — APROVADO em 2026-08-16 (a trava que faltava)

- **Onde**: worktree `.worktrees/exec-008`, branch `exec/008`, commit `c81fc2a`
  (`ci(gates): barra o React Flow voltando ao chunk inicial`), a partir de `1572849`.
  **Mesclado na `main`.**
- **Diff**: 2 arquivos, +23/−1. `gates.yml` ganhou um 12º passo (`React Flow fora do chunk
  inicial`), entre `npm run build` e a checagem de contrato, reaproveitando o `dist/` já
  produzido. `_tech-debt.md` ganhou o `TD-026`. `git diff HEAD~1 -- frontend` vazio.
- **Por que ela cabe na ADR-035 e não a contradiz**: a trava é hermética — `npm run build` mais
  inspeção do `dist/`. Sem Docker, sem segredo, sem stack. A ADR excluiu do CI a stack de 9
  serviços e os testcontainers; esta trava não é nenhum dos dois. Ela não existia porque a classe
  de regressão não existia quando a ADR foi escrita. **`TD-023` segue fechado**, verificado.
- **RED/GREEN, feitos pelo executor**: GREEN na `main` (`index-DGiKasej.js` 505,43 kB, gate exit
  0). RED reproduzindo o estado defeituoso com `git archive 5c6d231 -- frontend` para `/tmp` —
  build deu `index-BcPGUG4Z.js` 708,80 kB e o gate saiu 1 com
  `@xyflow/react voltou ao chunk inicial (...) - ver plano 006 / ARCH-18`. Nenhum
  `git checkout`/`stash`/`reset`; diretório temporário removido.
- **Verificado por mim, os 4 caminhos do gate** — extraí o script do YAML e rodei contra 4
  cenários:

  | Cenário | Resultado |
  |---|---|
  | `dist/assets/index-*.js` ausente | exit 1 (não passa em silêncio) |
  | dois chunks casando o glob | exit 1 (ambiguidade barrada) |
  | um chunk contendo `xyflow` | exit 1, com a mensagem certa |
  | build real da `main` | **exit 0** |

  O caso do glob sem match é o sutil: o bash deixa o literal, e o teste `-e` pega — uma trava que
  passasse aqui seria pior do que trava nenhuma. Também confirmei o YAML: **12 passos**, com o
  novo entre `npm run build` e `Contrato gerado está em dia`.

#### Tranca do login (plano 003) — PROVADA AO VIVO

Era o único item que nunca tinha sido exercitado: eu só havia validado a sintaxe do `nginx.conf`
(`nginx -t`), nunca visto a tranca trancar. 30 tentativas sequenciais em
`POST /api/auth/login` com senha deliberadamente errada (nenhuma sessão criada):

```
ordem: 444444444444444444444TTTTTTTTT      (4 = 401, T = 429)
contagem: {401: 21, 429: 9}                primeira barrada: tentativa 22
```

Bate exatamente com a calibração escrita no plano — `burst=20 nodelay` mais 1 da taxa
`30r/m` = 21 tentativas aceitas, da 22ª em diante `429`.

**E a tranca solta rápido**: uma credencial VÁLIDA logo em seguida devolveu `200` com token, sem
esperar mais que os ~2 s da taxa. Ou seja, o operador que erra a senha algumas vezes não fica
trancado fora do painel — só quem metralha o endpoint é barrado. Era o risco que o plano
levantava (as suítes de gate logam muito), e está medido: não se materializa.

A **L2** (`uv run pytest -m e2e`) continua não executada, por decisão: `CLAUDE.md:165-167`
proíbe rodá-la junto com o Playwright, e o Playwright das três telas de trend acabou de rodar.

### 007 — APROVADO em 2026-08-16 (a prova de browser do 002, e a regressão que ela achou)

- **Onde**: worktree `.worktrees/exec-007`, branch `exec/007`, commit `b10f637`
  (`test(frontend): varredura de fibra do PW-OP-11 não depende de teto fixo de hooks`), a partir
  de `df9c5c0`. **Mesclado na `main`** em `1572849` (`--no-ff`).
- **Como o achado apareceu**: ao fechar a pendência de browser do plano 002, reconstruí o
  container do frontend a partir da `main` (`docker compose ... up -d --build --no-deps frontend`)
  e rodei `operate-trend.spec.ts` inteiro. `PW-OP-13` passou; **`PW-OP-11` — cenário
  pré-existente do dono — falhou 3x**, determinístico, em
  `Error: instância do uPlot não encontrada na fibra do React`.
- **Atribuição por medição, não por leitura.** Construí a imagem do frontend a partir de
  `5c6d231` (antes do plano 002), servi em `:8081` anexada à rede `ottima_default` e rodei só o
  `PW-OP-11`:

  | Bundle servido | `PW-OP-11` |
  |---|---|
  | `5c6d231`, `:8081` (`index-BcPGUG4Z.js`) | **passa** (7,4 s) |
  | `df9c5c0`, `:8080` (com o plano 002) | **falha 3x** |

  Regressão minha, do plano 002. O aparato de diagnóstico (worktree temporária, imagem,
  container) foi desmontado depois.
- **Causa raiz**: o helper `janelaAplicadaS` varre a lista de hooks da fibra do React com teto
  fixo `i < 40`. O fix do 002 acrescentou `useTema()` (`useSyncExternalStore`, que ocupa mais de
  um nó) ANTES do `useMotorTrend` — 23 chamadas diretas de hook viraram 24, várias delas hooks
  customizados que expandem, e o ref do uPlot passou do teto. **O defeito é o teto arbitrário,
  não o hook**: um teste que quebra porque o componente ganhou um hook, sem nada do
  comportamento sob teste mudar, quebraria de novo no próximo.
- **Conserto**: dois tetos `40` → `200` nos dois laços, com comentário registrando que o limite
  é guarda anti-loop-infinito e não orçamento de hooks. 1 arquivo, +5/−2, **zero linha de
  produção** (`git diff HEAD~1 -- frontend/src` vazio). A asserção não foi enfraquecida:
  `janelaAplicadaS` continua lendo `scales.x.min/max` da instância real do uPlot.
- **RED→GREEN real, feito pelo executor e reconferido por mim na `main` mesclada**:
  RED `1 failed` com a mensagem exata; GREEN **`12 passed (33,3 s)`**, zero failed, zero flaky,
  com `PW-OP-11` (7,5 s) e `PW-OP-13` (1,0 s) entre os verdes.
- **Desvio operacional aceito**: a worktree não tem `node_modules` nem `deploy/`. O executor
  criou um symlink `frontend/node_modules` → o da raiz **dentro da própria worktree** (uso só de
  leitura; não rodou `npm install` através dele, o que teria escrito na árvore do dono) e leu
  `deploy/.env` da raiz por caminho absoluto. Removeu o symlink ao final. Contido e correto.
- **Duas falhas minhas nesta rodada, registradas**: (1) despachei o 007 sem materializar
  `local://plano-007.md` — o executor parou corretamente em vez de adivinhar; (2) escolhi
  `cavecrew-builder`, que nesta sessão não tinha ferramenta de shell, e o plano exige
  RED/GREEN executado. Redespachado para `tdd-guide`, que tinha shell. Verificar a capacidade do
  agente contra o que o plano exige é parte do despacho, não do executor.

#### Prova de browser do plano 002 — FECHADA

- Container reconstruído da `main`: bundle `index-Cr749cPY.js` / `FlowEditorPage-Dv7tdIRv.js`
  dentro do `ottima-frontend-1`, `healthy` em 20 s.
- **Bônus de verificação do 006 no artefato servido**, não só no build local:
  `docker exec ottima-frontend-1 grep -l xyflow /usr/share/nginx/html/assets/*.js` →
  **só** o chunk do editor.
- `operate-trend.spec.ts` inteiro: **12 passed**, zero flaky. O `PW-OP-13` prova em browser o
  que o plano 002 pedia — alternar claro/escuro recria a instância do uPlot.
- Ambiente: `uv run python scripts/setup-l3.py` (idempotente) antes. A **L2**
  (`uv run pytest -m e2e`) **não** foi rodada — `CLAUDE.md:165-167` proíbe junto com o
  Playwright, e o L1 daria vermelho falso depois (`deploy/stop` deixa o flow como `stopped`).

### 006 — APROVADO em 2026-08-16 (a GUARDA fechada)

- **Onde**: worktree `.worktrees/exec-006`, branch `exec/006`, commit `f777a12`
  (`perf(frontend): registro de bloco deixa de arrastar o React Flow para o chunk inicial`),
  a partir de `5c6d231`. **Mesclado na `main`** em `622272e` (`--no-ff`).
- **Diff**: 3 arquivos, +27/−39. `registro.ts` perdeu o import de valor de `./nodes`, o campo
  `Node` de `DefinicaoBloco`, as 9 linhas `Node:` e o `TIPOS_DE_NO`; `nodes/index.tsx` ganhou
  o mapa local; `registro.check.ts` passou a importar o mapa de `./nodes` e perdeu a asserção
  `definicao.Node`.
- **A garantia do ARCH-18 saiu mais forte do que entrou.** O `TIPOS_DE_NO` antigo era
  `NodeTypes` (index signature solta, derivada por `Object.fromEntries`); o novo é
  `Record<TipoBloco, ComponenteNo>` com 9 chaves explícitas. `TipoBloco` é
  `(typeof TIPOS_BLOCO)[number]` — união fechada — então faltar um tipo quebra o BUILD nas
  DUAS metades, dados e componentes. Verificado por mim estaticamente (anotação + união
  fechada + typecheck verde) e pelo executor dinamicamente: comentar `pid: NoPid` produz
  `TS2741: Property 'pid' is missing`, revertido reescrevendo a linha, sem `git checkout`.
- **Verificado por mim no estado MESCLADO** (`df9c5c0`), não no relato nem na worktree isolada:

  | Critério | Resultado |
  |---|---|
  | `grep -l xyflow dist/assets/*.js` | **só** `FlowEditorPage-CLg2yehU.js` |
  | `index-*.js` | **505,43 kB** (era 708,80) |
  | `npm run typecheck` | limpo |
  | `npm run test:unit` | 633 passed |
  | `uv run ruff check .` | `All checks passed!` |
  | `grep -c manualChunks\|chunkSizeWarningLimit vite.config.ts` | 0 |

  $708{,}80 \rightarrow 505{,}43\ \text{kB} = -203{,}39\ \text{kB}\ (-28{,}7\%)$. Contra a base
  sem o 005 (`774,22 kB`), o ganho combinado volta a **−34,7%** — o valor original do plano 005,
  restaurado.
- **Desvio documentado, aprovado no mérito**: o executor não rodou o Passo 1 (baseline) antes
  de editar. Compensou depois extraindo `5c6d231` com `git archive` para `/tmp`, buildando lá e
  medindo 708,80 kB — número observado, não citado do plano, e sem nenhum comando destrutivo na
  worktree. Aceito: preserva a garantia probatória do passo.

### 002 (segunda execução) — APROVADO em 2026-08-16

- **Onde**: worktree `.worktrees/exec-002b`, branch `exec/002b`, commit `144d600`
  (`fix(frontend): trend de operação repinta ao alternar tema claro/escuro`), a partir de
  `5c6d231`. **Mesclado na `main`** em `df9c5c0` (`--no-ff`).
- **Por que houve segunda execução**: o `exec/002` original (`6b668b8`, contra `8f9fe76`) deixou
  de mesclar quando a `main` avançou — `git merge-tree` mostrou CONFLICT em
  `operate-trend.spec.ts`, e o número `PW-OP-12` que ele usou foi tomado pelo dono para *"a
  legenda de operação mostra valor e EU na linha"* (ARCH-04). Reconciliei o plano (SHA
  `ab10746`→`5c6d231`, baseline 596→633, cenário renomeado para `PW-OP-13`) e re-executei sobre
  a `main` — mais barato que resolver o conflito. O bug seguia intacto: `TrendOperacao.tsx:577`
  e `:581` com `useMemo(..., [])`, `:769` sem tema.
- **Diff**: 2 arquivos, +41/−3. `useTema()` fornece `temaId`; os dois `useMemo` passam a
  depender dele; `temaId` entra como primeiro campo da chave `estrutura`.
- **Juízo do executor, aprovado**: das duas asserções que o plano oferecia, escolheu identidade
  do nó DOM em vez de contar `<canvas>` — o uPlot mantém um só canvas e a contagem volta a 1
  depois da recriação, então contar não distingue "recriou" de "não fez nada". Marcar o
  `.u-wrap` vivo e exigir `toHaveCount(0)` depois do toggle distingue.
- **Verificado por mim no estado MESCLADO**: typecheck limpo; `npm run build` exit 0;
  `npm run test:unit` 633 passed; `npx playwright test operate-trend.spec.ts --list` → 12
  cenários, com `PW-OP-12` (do dono) e `PW-OP-13` (novo) coexistindo; e os dois greps de aceite
  (`useMemo(() => lerTemaTrend(), [])` e `useMemo(() => lerCoresPenaOperacao(), [])`) → nada.
- **PENDENTE, e não é falha do executor**: a prova de browser. `playwright.config.ts:11` aponta
  `baseURL` para `http://localhost:8080`, onde está o container do dono servindo o bundle da
  `main` com planta simulada viva — rodar o spec de dentro da worktree daria verde falso. O
  `--list` prova que o spec parseia e que o cenário está registrado, não que ele passa. Rode
  `cd frontend && npm run e2e` (ou só este spec) contra o stack já reconstruído a partir da
  `main` @ `df9c5c0` para fechar.

### 002 — APROVADO (verificação de browser pendente) em 2026-08-16

- **Onde**: worktree `.worktrees/exec-002`, branch `exec/002`, a partir de `46d2598`.
  **Não mesclado.** O executor não tinha ferramenta de shell nesta sessão, então **o revisor
  rodou todos os gates de máquina** e pediu o commit por mensagem.
- **Diff**: 2 arquivos, +38/−3 — `frontend/src/features/operate/TrendOperacao.tsx` (+10/−3) e
  `frontend/e2e/operate-trend.spec.ts` (+28). `LegendaOperacao.tsx` **não** aparece no diff,
  como exigido (é ARCH-04, e o dono está editando aquele arquivo).
- **O que mudou**: `useTema()` importado; os dois `useMemo` passaram de `[]` para `[temaId]`,
  com o comentário novo registrando por que (as duas funções leem
  `getComputedStyle(document.documentElement)`); `temaId` entrou como primeiro campo da
  `estrutura`, com o comentário espelhando `TrendChart.tsx:44-45`. O comentário §6.6-5 sobre a
  fonte da paleta de pena foi preservado, e a paleta continua vindo de
  `TOKENS_PENA_OPERACAO`, nunca de `tema.penas`.
- **Verificado pelo revisor** (o executor não pôde rodar nada): `npm run typecheck` → exit 0,
  zero erro · `npm run build` → exit 0, `index-DCakkpcd.js` 775,38 kB (inalterado, correto —
  este plano não mexe em bundle) · `npm run test:unit` → **596 passed**, sem regressão ·
  `npx playwright test operate-trend.spec.ts --list` → **Total: 11 tests**, incluindo
  `operate-trend.spec.ts:496:3 PW-OP-12: alternar claro/escuro recria a instância do uPlot`.
- **O cenário novo foi auditado e assere o invariante certo**: marca o canvas vivo com um
  atributo, aciona o `theme-toggle`, faz `poll` até o `data-theme` do `<html>` mudar, e então
  assere que o canvas marcado tem contagem **0** (instância destruída e remontada) e que existe
  canvas novo visível. **Não** compara hash de imagem — o comentário do próprio cenário explica
  que isso seria flaky por construção, porque o trend recebe dado novo a cada polling. O revisor
  confirmou que os dois `data-testid` de que ele depende existem: `theme-toggle` em
  `components/ui/theme-toggle.tsx:27` e `operate-trend-chart` em `TrendOperacao.tsx:917`.
- **LIMITE HONESTO DESTA APROVAÇÃO**: o plano 002 diz, com razão, que "a prova tem de ser de
  browser" — a correção é reatividade de DOM e repintura de canvas. Essa prova **não foi
  executada**: exige o stack, e o stack no ar é o do dono (ver a nota de gates acima). Então o
  que está aprovado é: o código espelha um padrão já provado em produção no `TrendChart.tsx`,
  os gates estáticos passam, e o cenário de regressão existe e parseia. **Falta rodar
  `npx playwright test operate-trend.spec.ts` contra um stack próprio antes de considerar o
  achado fechado.** Não marque este plano como verificado sem isso.

### 003 — APROVADO em 2026-08-16

- **Onde**: worktree `.worktrees/exec-003`, branch `exec/003`, commit `7a83bec`
  (`fix(deploy): teto de tentativas por IP no login, sem trancar usuário`), a partir de
  `46d2598`. **Não mesclado.**
- **Diff**: 1 arquivo, `frontend/nginx.conf`, +22/−0. Nada mais.
- **O que mudou**: `limit_req_zone $binary_remote_addr zone=login:10m rate=30r/m;` na linha 9,
  **antes** do `server {` da linha 11 (contexto `http`, o único lugar válido); e
  `location = /api/auth/login` com `limit_req zone=login burst=20 nodelay;`,
  `limit_req_status 429;` e as três diretivas de proxy repetidas — `location` novo não herda
  `proxy_pass`, e o `proxy_pass` ficou sem barra final, igual ao do `/api/`.
- **Verificado pelo revisor**: `grep -c 'limit_req ' frontend/nginx.conf` → **1** (nem `/ws` nem
  `/api/` genérico foram limitados, que era o risco de estrangular dado cíclico e comando de
  operação) · `limit_req_zone` na linha 9 vs `server {` na 11 · `grep -n 'ports:'
  deploy/docker-compose.yml` → só no serviço `frontend`, confirmando a premissa central (o
  `api` não publica porta, então o nginx é caminho obrigatório e o teto não é contornável) ·
  árvore limpa pós-commit, `main` limpa antes e depois.
- **DEFEITO NO PLANO, corrigido pelo revisor**: o comando de verificação do Nível 1 que o plano
  003 dava —
  `docker run --rm -v "...nginx.conf:...:ro" nginx:1.27-alpine nginx -t` — **é impossível de
  passar**, com ou sem a edição: num container solto o nginx não resolve o hostname `api`, que
  só existe na rede do compose. Prova: o `nginx.conf` ORIGINAL falha idêntico
  (`host not found in upstream "api"`, na linha do `proxy_pass` que já existia). O comando certo
  acrescenta `--add-host api:127.0.0.1`; com ele, edição e original passam os dois
  (`syntax is ok`, `test is successful`). A tabela de comandos do plano foi corrigida.
  Registro de honestidade: o revisor chegou a afirmar ao executor que o gate havia passado
  antes de conferir a saída, e corrigiu a afirmação na mensagem seguinte.
- **NÃO EXECUTADO**: Níveis 2 e 3 do plano (o 429 disparando ao vivo, `deploy/smoke.sh`, L2 e
  Playwright). Exigem stack e `deploy/.env`. **É exatamente o que a condição de PARADA do plano
  manda fazer nesse caso**: entregar o Nível 1 e não marcar os demais. O teto de 30r/m com
  `burst=20` foi dimensionado no papel contra os pontos de login das suítes, mas **não foi
  provado contra elas** — rodar L2 e Playwright depois do merge é obrigatório antes de
  considerar o plano fechado.

### 005 — APROVADO em 2026-08-16

- **Onde**: worktree `.worktrees/exec-005`, branch `exec/005`, commit `aec9948`
  (`perf(frontend): editor de flow sai do bundle inicial e vira chunk sob demanda`), a partir de
  `46d2598`. **Não mesclado.**
- **Diff**: 1 arquivo, `frontend/src/app/router.tsx`, +22/−2. `AppShell.tsx` não foi tocado — o
  `<Suspense>` ficou em `router.tsx`, envolvendo só o elemento da rota do editor, então o shell
  de navegação nunca desmonta e não há piscada nas rotas de operação.
- **Ganho medido pelo revisor, com rebuild próprio** (não é o número do executor):

  | | chunk principal | chunk do editor |
  |---|---|---|
  | antes | `index-*.js` **775,38 kB** (gzip 242,04) | — |
  | depois | `index-C-ePFuwf.js` **505,52 kB** (gzip 160,39) | `FlowEditorPage-CaUlad6z.js` 270,90 kB (gzip 82,40) |

  Redução de **269,86 kB no chunk inicial, −34,8%**. Controle independente: o build da worktree
  do plano 002, na MESMA base e sem esta mudança, deu 775,38 kB.
- **Verificado pelo revisor**: `grep -l 'xyflow' dist/assets/*.js` → **só**
  `FlowEditorPage-CaUlad6z.js`, nunca o `index-*.js` (o código do React Flow saiu de fato do
  bundle inicial) · `grep -n 'FlowEditorPage' src/app/router.tsx` → apenas o
  `lazy(() => import(...))` das linhas 25-26 e o uso na rota, nenhum import estático ·
  `grep -c 'manualChunks\|chunkSizeWarningLimit' vite.config.ts` → **0** (nem afinação manual de
  chunk, nem o aviso do Vite silenciado — o aviso ainda aparece em 505 kB, como deveria) ·
  `npm run typecheck` exit 0 · `npm run test:unit` 596 passed · `--list` 4 cenários ·
  árvore limpa, `main` limpa antes e depois.
- **Efeito colateral bem-vindo**: o import dinâmico separou também 13,23 kB de CSS do editor.
- **NÃO EXECUTADO**: `npm run e2e` real. O `--list` prova que `flows-editor.spec.ts` parseia,
  não que a rota fatiada carrega no browser. Rodar a spec do editor contra um stack próprio é
  obrigatório antes de fechar — é justamente a rota cujo carregamento mudou.
- **Mesclado em `improve` em 2026-08-16**, por instrução do dono. O 003 entrou por
  fast-forward (`7a83bec`); o 005 entrou por **merge commit** (`984ba64`,
  `merge: editor de flow fora do bundle inicial (plano 005)`) porque deixou de ser
  fast-forward depois do 003. Merge commit foi escolha deliberada em vez de rebase: o repo já
  usa merge commits (`merge: camada SSTO de alvos de regime permanente (ADR-027)`) e assim o
  hash **revisado** `aec9948` fica preservado no histórico como pai, em vez de ser reescrito.
- **Verificado no estado MESCLADO, não só na worktree isolada**: `npm run build` em `improve`
  produz `index-C-ePFuwf.js` 505,52 kB + `FlowEditorPage-CaUlad6z.js` 270,90 kB — **hashes
  idênticos** aos do build isolado, ou seja o merge não alterou nada; `grep -l 'xyflow'
  dist/assets/*.js` → só o chunk do editor; `npm run test:unit` → 596 passed; e o
  `nginx -t` (com `--add-host`) do `nginx.conf` mesclado passa.

  **Atenção: esse 505,52 kB NÃO é o estado da `main`.** A medição acima é de `improve`, que não
  tem o ARCH-18. Na `main` mesclada o número é outro — ver a GUARDA abaixo, que disparou.

#### GUARDA: DISPAROU — e foi FECHADA pelo plano 006, mesclado na `main` em `622272e`

A guarda foi escrita como hipótese e **confirmou-se por medição no mesmo dia**. O ARCH-18
aterrissou na `main` (`9e71b89`) ANTES de o 005 chegar lá, e desfez o ganho — em silêncio, com
build verde, typecheck limpo, `test:unit` 596 e nenhum teste falhando.

**A cadeia, verificada linha por linha na `main`. Todo hop é import de VALOR** (o bundler não
pode apagar nenhum), e o primeiro está numa rota que todo usuário autenticado carrega:

```
app/CanalAoVivo.tsx:29        import { deGraphJson } from "../features/flows/graph"
features/flows/graph.ts:25    import { PADRAO_*, REGISTRO_BLOCO, ROTULO_BLOCO } from "./registro"
features/flows/registro.ts:27 } from "./nodes"
features/flows/nodes/index.tsx:24  import { BlocoChapa, LinhaResumo, type Porta } from "./BlocoChapa"
features/flows/nodes/BlocoChapa.tsx:1  import { Handle, Position } from "@xyflow/react"
```

O `registro.ts` do ARCH-18 passou a **importar os 9 componentes de nó como valor** para poder
guardar `Node: ComponenteNo` em cada entrada de `REGISTRO_BLOCO`. Como `graph.ts` é alcançado
pelo `CanalAoVivo` em toda rota, e os componentes ficam retidos num `Record` exportado
(tree-shaking não os resgata), o `@xyflow/react` voltou ao chunk inicial. `React.lazy` no
`FlowEditorPage` **não consegue mais** mantê-lo fora.

**Medição (`npm run build` + `grep -l xyflow dist/assets/*.js`):**

| Estado | chunk inicial | chunk do editor | `xyflow` em |
|---|---|---|---|
| `improve` @ `984ba64` (005 sem ARCH-18) | `index-C-ePFuwf.js` 505,52 kB | `FlowEditorPage-CaUlad6z.js` 270,90 kB | chunk do editor |
| `main` @ `9e71b89` (ARCH-18, sem 005) | `index-WdBv0nrU.js` 774,22 kB | — | `index` |
| **`main` @ `ab10746` (ARCH-18 + 005)** | `index-BcPGUG4Z.js` **708,80 kB** | `FlowEditorPage-B2DGhlzl.js` 67,98 kB | **`index`** |

O fatiamento continua existindo, mas ficou oco: o chunk do editor caiu de 270,90 para 67,98 kB
porque as ~203 kB do React Flow migraram para o inicial. **Na `main`, o plano 005 entrega
−65,42 kB (−8,45%), não os −269,86 kB (−34,8%)** medidos em `improve`. Perdeu 75% do valor.

**Não reporte o −34,8% como entregue.** O número real na `main` é −8,45%.

**Conserto: plano 006** (`006-registro-de-bloco-sem-arrastar-o-react-flow.md`), que separa os
DADOS do registro dos COMPONENTES de nó preservando a garantia de completude do ARCH-18 nas
duas metades (`Record<TipoBloco, …>` em ambas, para a falta de um tipo continuar quebrando o
build). O 005 **não** deve ser revertido: os −65,42 kB são reais e o `lazy` é pré-requisito do
006.

**O CI não pega esta classe de regressão.** O `gates.yml` do ADR-035 roda ruff, `test:unit`,
typecheck, build e a checagem de contrato gerado — nenhum deles olha em qual chunk o `xyflow`
caiu. Enquanto o 006 não entrar com o passo de gate correspondente, a verificação é manual:

```bash
cd frontend && npm run build && grep -l xyflow dist/assets/*.js
```

A saída tem de ser **apenas** um `FlowEditorPage-*.js`. Se listar `index-*.js`, o fatiamento
está desfeito.

**Desfecho**: o plano 006 restaurou o ganho e está na `main`. Medição no estado mesclado
(`df9c5c0`): `index-DGiKasej.js` **505,43 kB**, `xyflow` só em `FlowEditorPage-CLg2yehU.js`.
A guarda continua valendo como procedimento — o comando acima é a única prova desta classe de
regressão, e **o CI ainda não a tem**. O passo de gate está recomendado nas notas de manutenção
do plano 006.

### 001 — APROVADO em 2026-08-16

- **Onde**: worktree `.worktrees/exec-001`, branch `exec/001`, commit `46d2598`
  (`fix(flow-runtime): falha de recv no host MPC vira crash sintético em vez de travar o dispatch`),
  a partir de `93989f9` (ou seja, COM o fix do 004 na base — a dependência dura foi honrada
  de verdade, não pela escotilha de escape do plano, que o despacho cancelou explicitamente).
  **Não mesclado** — mesclar é decisão do dono.
- **Diff**: exatamente os 4 arquivos em escopo, +148/−7 —
  `mpc/host.py` (+50/−5), `script_pool.py` (+2/−2), `test_mpc_host.py` (+69),
  `test_script_pool_executor.py` (+32). Nenhum arquivo fora da lista.
- **O que mudou em produção**: `host.py::_receive` captura `Exception` (não `BaseException` —
  `CancelledError`/`KeyboardInterrupt` seguem propagando, registrado no docstring);
  `_await_response` ganhou `try/except Exception` que loga e cai em `outcome = _CRASHED`,
  reusando o ramo já existente que sintetiza `empty_result(status="error")` e chama
  `_schedule_respawn()`, com **`self._busy = False` num `finally`** — o coração do defeito;
  `dispatch()` ganhou o callback `_log_se_falhou` (guarda `task.cancelled()` antes de
  `task.exception()`, loga com `self._block_id`). Em `script_pool.py`, as duas tuplas
  `(OSError, EOFError, ValueError)` viraram `Exception` em `run()` e em
  `_enqueue_when_ready()`, com `except asyncio.CancelledError` preservado como PRIMEIRO ramo
  (débito m3 intacto). O sub-passo 3.3 (deixar `script_pool._receive` defensivo) foi pulado,
  como o próprio plano permite.
- **Verificado pelo revisor, re-rodando os critérios** (não é o relato do executor):
  `uv run ruff check .` → `All checks passed!` · `uv run ruff format --check .` →
  `303 files already formatted` · `uv run pytest services/flow-runtime/tests -q` →
  **`508 passed, 1 deselected, 1 xfailed in 439.92s`** · `uv run pytest packages/ottima-core/tests -q`
  → **`595 passed in 23.79s`**. Verde puro, zero vermelho tolerado. O `1 xfailed` é o
  `xfail(strict=True)` deliberado de `test_isolamento_temporal.py:101` (TD-016/ARCH-11).
- **Os 3 testes novos foram auditados um a um** e asseveram contrato observável, não
  encanamento:
  1. `test_falha_de_recv_por_erro_de_deserializacao_nao_deixa_busy_preso` — espera
     `respawns == 1` e então assere que um `dispatch()` seguinte é ACEITO. Sem o fix, `_busy`
     fica preso e devolve `False` para sempre. O docstring documenta a corrida que o teste
     precisou evitar: esperar só `host.ready is True` venceria ANTES de a task de fundo
     começar, porque `ready` já parte `True`.
  2. `..._entrega_resultado_sintetico_de_erro` — `poll()` devolve `status == "error"`, que é
     o que faz `blocks/mpc.py::_apply_result` emitir `mpc_solver_error` e o operador ver
     alarme. Sem o fix, `_pending_result` nunca é setado e o `poll()` fica `None` para sempre.
  3. `..._repoe_worker_sem_encolher_pool` — pool `size=1`: a primeira chamada devolve
     `error` e a SEGUNDA volta `ok` com `{"OUT1": 42.0}`. Prova as duas metades (falha
     graciosa + pool não encolheu) numa asserção só.
  Nenhum `assert True`, nenhum mock asseverando mock. `_block_id` foi conferido existente
  (`host.py:155`), então o caminho defensivo de log não tem `AttributeError` latente.
- **Desvio documentado, aprovado no mérito**: os 3 testes injetam a falha por
  `monkeypatch.setattr(<módulo>, "_receive", ...)` em vez de corromper o pipe de verdade.
  Isso foi decisão do revisor tomada ANTES do despacho, não improviso: o defeito está no
  HANDLER (converter exceção arbitrária em resultado sintético + respawn), não em como a
  exceção nasce; injetar testa o contrato, corromper testaria o CPython. O fake se
  auto-restaura na primeira chamada, então só um dispatch falha e o respawn pode funcionar.
- **Nit não bloqueante**: os fakes de `_receive` nos testes estão sem anotação de tipo nos
  parâmetros (`conn, timeout_s`). `CLAUDE.md:67` pede type hints; `ruff` sem `ANN` não pega.
- **INCIDENTE OPERACIONAL, relatado pelo próprio executor e verificado pelo revisor**: nas
  duas primeiras chamadas de `edit`, o executor usou path RELATIVO no cabeçalho `[FILE#TAG]`,
  que o tool resolveu contra a raiz da sessão — ou seja, escreveu `test_mpc_host.py` e
  `test_script_pool_executor.py` na `main`, não em WT. Ele detectou por
  `git status --porcelain`, conferiu por `git diff` que era inserção pura e reverteu com
  `git checkout --` nos dois arquivos, então refez com path absoluto. **Verificado pelo
  revisor**: os dois arquivos estão idênticos ao HEAD na `main`, sem resíduo, e nenhum deles
  constava do WIP do dono em nenhum snapshot — não havia trabalho dele ali para perder.
  Ainda assim, `git checkout --` na árvore do dono é comando destrutivo, e o próprio dono já
  tinha registrado o mesmo padrão antes (`stash@{2}`: "spill de graph.ts/test_scheduler.py de
  agentes com caminho relativo"). **Causa raiz: `task.isolation.mode` está `"none"` neste
  harness**, então subagente não recebe sandbox e todo path relativo cai na `main`. Disciplina
  de prompt reduz, mas não elimina — ligar a isolação do harness é o conserto estrutural.

### 004 — APROVADO em 2026-08-16

- **Onde**: worktree `.worktrees/exec-004`, branch `exec/004`, commit `93989f9`
  (`test(flow-runtime): gate do ts MPC espera o par flow.status chegar, não uma mensagem qualquer`),
  a partir de `8f9fe76`. **Mesclado em `improve` em 2026-08-16**, por instrução explícita do
  dono, com `git merge --ff-only exec/004` — fast-forward puro (`exec/004` descende de
  `8f9fe76`), zero conflito. `improve` passou a `93989f9`. A `main` não foi tocada e segue em
  `7f0f62c`. A worktree `.worktrees/exec-004` e a branch `exec/004` ficaram redundantes depois
  do ff e podem ser removidas (`git worktree remove .worktrees/exec-004 && git branch -d exec/004`)
  — não removidas aqui por serem destrutivas.
- **Diff**: 1 arquivo, `services/flow-runtime/tests/test_supervisor_mpc.py`, +17/−8. Nenhum
  arquivo sob `services/flow-runtime/src/`. Escopo limpo.
- **O que mudou**: a barreira `len(flow_status.received) >= 1` virou o predicado
  `par_da_mesma_varredura_chegou()`, que espera a MESMA condição da asserção (o `ts` do último
  `mpc.state` pertencer ao conjunto de `ts` de varredura coletados) e tolera lista vazia
  devolvendo `False`. O conjunto saiu para o helper `tss_de_varredura()`, que parseia cada
  payload UMA vez (antes `FlowStatus.model_validate_json(raw)` rodava duas vezes por mensagem).
  O docstring ganhou o parágrafo "Round 2" citando ADR-002, no estilo do "fix round 1" que já
  estava lá.
- **Verificado pelo revisor, re-rodando os critérios** (não é o relato do executor):
  `uv run ruff check .` → `All checks passed!` · `uv run ruff format --check .` →
  `303 files already formatted` · `uv run pytest services/flow-runtime/tests/test_supervisor_mpc.py -q`
  → **`28 passed in 122.37s`**. Comparação direta com a medição pré-plano na mesma máquina e
  mesmo comando: era `1 failed, 27 passed in 127.04s`.
- **A asserção não foi esvaziada** — o risco central deste plano. Auditado: continua
  pertinência exata (`in`), mesma mensagem pt-BR, e `grep` por
  `timedelta|abs(|total_seconds|round(|pytest.approx` no arquivo volta **vazio** — nenhuma
  tolerância de tempo foi introduzida. O executor também executou o RED obrigatório do Passo 3
  (deslocou o `ts` com `.replace(year=2000)`, teste falhou por timeout do `await_until` em
  19,18 s contra 13,15 s do verde, e reverteu); o resíduo foi conferido ausente por `grep`.
- **Desvio documentado, aprovado no mérito**: o Passo 3 pedia `timedelta(microseconds=1)`; o
  executor usou `.ts.replace(year=2000)` porque `datetime`/`timedelta` não estão importados no
  arquivo e importar sairia do escopo "apenas o corpo da função" que o plano fixou.
  Verificado: os imports realmente não existem no arquivo. A adaptação serve a intenção do
  plano e ficou em escopo.
- **Nit não bloqueante**: `tss_de_varredura()` ficou sem anotação de retorno (seria
  `-> set[datetime]`, que exigiria o import acima), enquanto
  `par_da_mesma_varredura_chegou() -> bool` tem. `CLAUDE.md:67` pede type hints; `ruff` com
  `select = ["E","F","I","UP","B","ASYNC"]` não cobre `ANN`, então nada falha. Vale fechar
  numa próxima passada pelo arquivo, junto com o import.
- **Contaminação**: nenhuma. `git -C . status --porcelain` na raiz não ganhou nenhum arquivo do
  executor (as 7 modificações presentes são trabalho do dono, na área da arch-review), e
  `.worktrees/improve` seguiu com apenas `?? advisor-plans/`.

## Achados vetados que ainda não têm plano

Todos confirmados por leitura do código citado. Estão aqui para não se perderem, em ordem
de leverage; qualquer um pode virar plano quando quiser.

- **Cabeçalhos de hardening ausentes no proxy da SPA.** `frontend/nginx.conf:10` define
  apenas `Content-Security-Policy`, sem `frame-ancestors`, `X-Frame-Options` nem
  `X-Content-Type-Options`. O comentário da linha 9 registra que o token JWT vive em
  `localStorage`. Sem `frame-ancestors`/`X-Frame-Options`, a SPA pode ser embutida em
  iframe de origem externa — clickjacking sobre `/operacao`, a tela que escreve SP e MV em
  planta viva. S, LOW, HIGH. Mesmo arquivo do plano 003, commit separado.
- **`db_engine` e `session_factory` recriam um `AsyncEngine` por teste.** `conftest.py:46`
  (raiz) e a fixture homônima em `services/flow-runtime/tests/conftest.py` não declaram
  `scope=`, então caem em `function`: cada teste que toca o banco cria e descarta um engine
  novo, com pool vazio, em vez de emprestar conexão de um pool aquecido. O isolamento por
  `SAVEPOINT` + rollback (`conftest.py:53-65`) não exige recriar o engine, só a conexão.
  Afeta ~114 testes de `services/api/tests` mais dezenas de `flow-runtime` e `ottima-core`.
  S, LOW, MED (o ganho em segundos não foi medido).
- **`routers/system_settings.py` só tem cobertura E2E.** Os outros 12 routers têm arquivo
  de teste homônimo em `services/api/tests/`; este não. O único teste que o exercita é
  `tests/e2e/test_settings_log_level.py`, marcado `e2e`, que exige o stack docker completo.
  A rota é `require_admin`, muta o log level do processo inteiro e publica evento de
  auditoria — RBAC e formas de erro só verificáveis subindo docker. S, LOW, HIGH.
- **`encrypt_secret` sem guarda de chave vazia.** `ottima_core/security.py:37-38` faz
  `Fernet(key.encode())` sem checar a chave; com `OTTIMA_FERNET_KEY` vazia isso levanta
  `ValueError`, e os dois call-sites (`routers/connections.py:164` e `:206`) não têm
  `try/except` — o resultado é 500 opaco no primeiro cadastro de conexão com senha.
  **A assimetria de boot NÃO é o achado**: `config.py:50-67` só loga `critical` para a
  chave Fernet enquanto aborta para a `SECRET_KEY`, e o docstring da linha 51 registra isso
  como decisão deliberada ("a chave de assinatura JWT é fatal, a Fernet é aviso"). O que
  falta é a falha graciosa no call-site, com mensagem de configuração em vez de 500 — e ela
  cai exatamente no comissionamento, quando a variável tende a estar faltando. S, LOW, HIGH.
- **Frontend sem lint nem formatador.** `frontend/package.json` não tem script de lint nem
  `eslint`/`prettier` em `devDependencies`, e não existe `eslint.config.*`, `.eslintrc*`,
  `.prettierrc*`, `.editorconfig` nem `.pre-commit-config.yaml` em lugar nenhum do repo.
  O lado Python tem `ruff` cobrindo lint e formato; o lado TS tem só `tsc --noEmit` — nada
  checa import não usado nem regra de hooks do React, justamente nos arquivos de maior
  churn (`graph.ts` 1056 linhas, `TrendOperacao.tsx` ~958, `CanalAoVivo.tsx` 940). M, MED
  (a primeira passada de eslint sem histórico gera onda de achados; mitigue com `warn`).
- **`CLAUDE.md` seção "Comandos" não ensina `npm install`.** O cabeçalho da seção
  (`CLAUDE.md:97`) pede explicitamente "manter esta seção atualizada", e o bloco começa com
  `uv sync --all-packages` e vai direto para `cd frontend && npm run build`. Não há
  `npm install`/`npm ci` em nenhuma linha; a única ocorrência no repo fora de
  Dockerfile/compose está em `docs/superpowers/plans/2026-08-03-F1-fundacao.md:3525`,
  artefato histórico. Num clone limpo o primeiro comando de frontend falha. Uma linha
  resolve. S, LOW, HIGH. **Atenção**: `CLAUDE.md` está na raiz, não em `docs/`, então não
  cai na proibição do item 4 — mas confirme com o dono antes de editar, porque é o
  documento normativo do projeto.

## Direção — opções para o dono do produto pesar

Não são defeitos; são caminhos com evidência no próprio repositório. Esforço aqui é
grosseiro de propósito.

- **`ssto_runs` é uma tabela de auditoria que ninguém pode ler.** A migration
  `packages/ottima-core/alembic/versions/0004_ssto_runs.py` cria a hypertable com o índice
  composto exato `ix_ssto_runs_flow_block_ts (flow_id, block_id, ts DESC)` (linha 45) e
  política de retenção de 1 mês (linha 47); o recorder a materializa; o RF-903 e o ADR-027
  §11 a chamam de "auditoria imutável". Mas a API expõe **só**
  `GET /api/history/ssto/last` (`routers/history.py:478`) — um ponto, enquanto
  `/api/history/mpc` e `/api/history/fuzzy` são consultas por faixa. A pergunta que
  justifica a tabela existir ("por que o otimizador desistiu daquela linha às 14:30, e
  qual restrição estava ativa?") é hoje inalcançável pela interface. O dado está lá,
  indexado para exatamente essa consulta. Um endpoint de faixa mais uma superfície de
  leitura fecharia a assimetria. Coarse: M para o endpoint, M-L com tela.
- **Nenhuma exportação tabular em nenhum lugar do sistema.** Zero ocorrências de `csv`,
  `text/csv` ou `StreamingResponse` em todo o repositório. `/api/history` existe e é bem
  desenhada (janela obrigatória, downsampling automático), mas devolve JSON para consumo da
  própria SPA. Um engenheiro de controle que precise de um relatório de desempenho de malha
  exporta à mão, e isso é fricção que o produto poderia absorver — o caminho de dados já
  está pronto. Coarse: S-M. Confiança na evidência: alta para a ausência, média para a
  demanda (nenhum documento do repo pede isso explicitamente).
- **`GurobiBackend` é um lugar reservado declarado.**
  `services/flow-runtime/src/ottima_flow_runtime/target_calculation/solver.py:193` levanta
  `NotImplementedError("GurobiBackend ainda não implementado (ADR-027 §7)")`, e
  `services/flow-runtime/tests/test_ssto_solver.py:107` assere o raise. É intenção
  registrada e deliberadamente não entregue, com o seam de backend já pronto — vale saber
  se ainda é o caminho ou se deve sair. Coarse: indefinido até haver caso de uso.

## Achados considerados e rejeitados

Para ninguém re-auditar.

- **`estaZoomadoEmX` coage `undefined` para 0 e reporta "zoomado".**
  `frontend/src/features/trend/zoomX.ts:20`. Parecia defeito de tipo — e **é
  comportamento deliberado, documentado e coberto por teste**:
  `frontend/src/features/trend/zoomX.check.ts:36-39` assere exatamente
  `estaZoomadoEmX(undefined, undefined, X) === true`, com o raciocínio no comentário
  ("o fallback `0` mantém a decisão conservadora — preserva o que está na tela — em vez de
  assumir 'não está zoomado' e apagar o recorte"). O conserto proposto inverteria a decisão
  e quebraria o teste. Não é achado.
- **"Os 19 minutos da suíte são dominados por compilação IPOPT".** Contagem certa
  (22 chamadas a `build_mpc()` no run default: 15 em `test_mpc_builder.py`, 7 em
  `test_mpc_bumpless.py`), magnitude errada. Medido: os dois arquivos juntos custam
  **48,26 s** de pytest para 21 testes (o mais lento 4,75 s, típico ~2,1 s), contra 1158 s
  da suíte — ~4%. O pior arquivo isolado é `test_supervisor_mpc.py`, com **127,04 s** para
  28 testes (~11%). O custo é difuso, não concentrado no solver, então não há um alvo único
  que justifique trocar o worker real por stub (mudança de risco MED que enfraqueceria a
  cobertura de `build_mpc`). O caminho com melhor relação custo/risco para tempo de suíte é
  o engine de sessão compartilhado, listado acima.
- **Nenhuma rota de listagem pagina.** Confirmado em `routers/tags.py:57-62` e no mesmo
  padrão em `connections.py`, `flows.py`, `calculated_tags.py`: `select(...).order_by(...)`
  sem `limit`. Rejeitado porque a RNF-01 dimensiona o sistema em ~100 tags OPC, ≤5
  servidores e um único host on-prem: paginar 4 rotas contra um volume que o próprio
  requisito limita a centenas de linhas é trabalho especulativo contra um não-requisito
  documentado. Reconsidere se a RNF-01 mudar.
- **Matriz colunar do trend reconstruída inteira a cada tique vivo.**
  `features/trend/useHistory.ts:108-135` (`montarMatriz`) e os equivalentes em
  `TrendOperacao.tsx:601-606` e `historicoFuzzy.ts` refazem a matriz completa a cada ponto
  novo, até 4×/s (`FLUSH_OPC_MS = 250`). Rejeitado: o teto real é 6-8 penas em janelas
  tipicamente de minutos, e a reescrita para append incremental duplicaria a lógica de
  carry-forward/gap em dois caminhos (rebuild e append), que é justamente a lógica coberta
  por `useHistory.check.ts`/`trendOperacao.check.ts`. Custo/risco MED contra ganho não
  medido. Reconsidere só com telemetria mostrando jank em janela longa.
- **Profundidade de JSON não limitada no import de projeto.**
  `routers/projects.py:343-346` faz `json.loads(corpo)` com `except json.JSONDecodeError`,
  que não cobre `RecursionError`. O teto de tamanho existe e está correto (4 MiB, streaming,
  `_ler_corpo_import`). Rejeitado como prioridade: `RecursionError` sobe até o middleware do
  Starlette e vira 500, não mata o processo, e a rota é `require_admin` — quem consegue
  chamá-la já pode apagar todos os projetos. O defeito real é cosmético (500 opaco em vez do
  422 pt-BR consistente do resto do endpoint). Vale carona num plano que já toque o arquivo.
- **Ausência de CI e gates não mecanizados.** Não é achado novo: já está registrado como
  **TD-023** em `docs/reports/_tech-debt.md`, com a nota de que exige decisão com ADR
  ("CI é escolha de arquitetura, não conserto mecânico").
- **`ruff format --check` vermelho em 18 arquivos.** Era o candidato número um do
  levantamento anterior; foi **resolvido** no commit `70ce9e9` ("style: aplica ruff format
  nos 18 arquivos fora do padrão"). Verificado em `8f9fe76`: `303 files already formatted`.
- **Tudo que a auditoria de arquitetura de 2026-08-15 já cobriu.** `ARCH-01` a `ARCH-22` em
  `docs/reports/arch/arch-review-20260815.md`, com débito aberto `TD-016` a `TD-024`. Não
  foi re-auditado por design. Um único ponto de contato foi verificado e separado: a
  divergência de tema do plano 002 **não** é `ARCH-02/03/04` (aqueles são duplicação de
  alinhamento de pena, merge de borda viva e legenda; este é reatividade de tema num
  consumidor do motor novo).

## O que esta auditoria NÃO cobriu

- **Camadas E2E (L1/L2/L3) e qualquer verificação contra o stack docker.** `deploy/.env` é
  obrigatório e gitignored, e não existe nesta worktree; nada foi executado contra os 9
  serviços, contra o opcsim ou contra planta simulada.
- **A suíte completa de `uv run pytest`** (~19 min). Foram medidos, deliberadamente, apenas
  `test_mpc_builder.py` + `test_mpc_bumpless.py` (48,26 s) e `test_supervisor_mpc.py`
  (127,04 s). Os demais pesos da suíte são inferência de contagem, não medição.
- **`uv run pytest -m slow`** (carga do MPC, RNF-02).
- **O grafo do `code-review-graph`.** O MCP respondeu com 0 nós para esta worktree, e
  construí-lo escreveria artefato — proibido pelas regras da auditoria. A exploração foi por
  leitura, grep e ast-grep, exatamente a saída que `CLAUDE.md:193` prevê. (A auditoria de
  arquitetura de 15/08 registrou a mesma limitação, por timeout.)
- **`docs/PRD.md` e `docs/adr/`** como objeto de crítica. Foram lidos como fonte normativa
  (para não relitigar decisão fechada), nunca auditados.
- **Cobertura de linha medida.** Não foi rodado `coverage`; o cruzamento de cobertura foi
  mecânico (qual módulo de produção é importado por algum teste), não quantitativo.
- **`services/recorder/` e `services/calc-worker/` em profundidade.** Entraram na varredura
  de corretude, mas com peso menor por churn baixo no período.
