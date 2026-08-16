# ADR-035 — Mecanização dos gates: CI hermético, sem segredo e sem stack

**Status:** Aceito · 2026-08-16

## Contexto

O `CLAUDE.md` documenta os gates do projeto desde a F1, mas nada os executa. `.github/` existia
vazio, sem nenhum workflow, e `core.hooksPath` aponta para um diretório global do usuário
(`~/.config/git/hooks`) — então nem hook local do repositório dispara.

O custo disso não é hipotético. No commit `e38f528` dois gates documentados estavam **vermelhos ao
mesmo tempo**, e ninguém percebeu até uma auditoria olhar:

- `uv run ruff format --check .` reprovava 18 arquivos, desde antes daquele branch, com o mesmo
  resultado no checkout principal — e não era drift de configuração (`line-length = 100` está no
  `pyproject.toml` desde `059c786`, o primeiro commit do workspace `uv`);
- `npm run typecheck` reprovava `mpcLogic.check.ts:318` (fixture de `TagOut` sem `project_id`) —
  **recorrência literal do TD-010**, porque `*.check.ts` fica fora do typecheck do `build` por
  design e só o comando próprio o pega.

Os gates do projeto se separam em dois grupos com requisitos muito diferentes:

| Grupo | Gates | Requisito |
|---|---|---|
| Hermético | `ruff check`, `ruff format --check`, `npm run test:unit`, `npm run typecheck`, `npm run build`, contrato gerado em dia | nada além de Node e `uv`. Segundos a poucos minutos |
| Com infraestrutura | `uv run pytest` (workspace), gate E2E de 3 camadas (L1 `smoke.sh`, L2 `tests/e2e`, L3 Playwright) | Docker (testcontainers), stack de 9 serviços, `opcsim`, e credenciais de `deploy/.env` |

Dois detalhes decidem o desenho: `playwright.unit.config.ts` **não declara projeto de navegador**
(o `test:unit` é checagem pura em Node, reaproveitando o runner do Playwright de propósito), e
`generate-contracts.mjs` chama `uv run python -m ottima_core.contracts_export` — ou seja, a
checagem de contrato gerado precisa de Python e Node no mesmo job.

## Decisão

### O CI roda só o grupo hermético

`.github/workflows/gates.yml`, um job em `ubuntu-latest`, disparado em `push` de qualquer branch e
por `workflow_dispatch`, executando exatamente os gates herméticos na ordem do `CLAUDE.md`, mais a
checagem de que `contracts.gen.ts` está em dia (`npm run generate:contracts` seguido de
`git diff --exit-code`) — a trava de forma que o ARCH-06 previu e a ADR-034 tornou norma.

`npm run typecheck` é passo **próprio**, e não um efeito colateral do `build`: é essa separação que
teria pego o vermelho de `e38f528`.

### Os gates de infraestrutura não entram agora

`uv run pytest` e o gate E2E ficam **fora**, e isso é decisão, não esquecimento:

- **pytest** precisa de Docker no runner para os testcontainers e leva ~20 min; o TD-009 já
  registrou uma rodada inteira de vermelhos falsos causada só por contenção de recurso entre
  suítes concorrentes. Mecanizar antes de resolver isolamento importaria o problema para dentro do
  CI, onde ele é mais caro de diagnosticar.
- **E2E** precisa da stack de 9 serviços com `opcsim`, e das credenciais de `deploy/.env` — ou
  seja, criaria a primeira superfície de segredo do repositório. Além disso, a L2 e o Playwright
  **não podem rodar juntos** (o E2E-16 publica `project_activated` duas vezes e derruba
  E2E-F3-03/04/08), então o pipeline teria de serializá-los explicitamente.

Os dois continuam sendo responsabilidade de quem abre o PR, como hoje, e permanecem registrados no
TD-023 como pendência explícita.

### Nenhum segredo

Nenhum passo lê `deploy/.env`, `OTTIMA_*` ou qualquer `secrets.*`. O repositório continua sem
segredo configurado no GitHub. Essa é a propriedade que torna o workflow seguro de rodar em push de
qualquer branch.

### Gancho local (pre-commit) não é adotado

`core.hooksPath` já aponta para um diretório global do usuário, então um hook em `.git/hooks` do
projeto nunca dispararia; adotar um gerenciador (lefthook, husky) seria dependência nova para
resolver um problema que o CI já resolve, e imporia a escolha de ferramenta a qualquer máquina que
clone o repositório. Fica de fora.

### Disparo em `push`, não em `pull_request`

Repositório de dono único, com o fluxo de "um worktree por fase" do `CLAUDE.md`: o push da branch
já cobre todo código que existe. Acrescentar `pull_request` duplicaria as rodadas sem cobrir nada
novo. Se um dia entrar contribuição de fork, o gatilho deve ser acrescentado — é uma linha.

## Consequências

- (+) Os dois vermelhos comprovados em `e38f528` passam a ser barrados: `ruff format --check` e
  `npm run typecheck` são passos próprios do workflow.
- (+) A recorrência do TD-010 fica estruturalmente fechada — `*.check.ts` continua fora do
  `build` por design, e o gate que o cobre agora roda sozinho.
- (+) `contracts.gen.ts` desatualizado vira vermelho, fechando o mecanismo que a ADR-034 exige e
  que até agora dependia de alguém lembrar de rodar o gerador.
- (+) Sem segredo e sem Docker, o workflow roda em runner hospedado padrão, sem custo de
  infraestrutura e sem risco de vazamento.
- (−) Regressão de backend (Python) e de integração continua invisível ao CI: só a lente local
  pega. É a maior lacuna que sobra, e é consciente.
- (−) O gate E2E continua manual, incluindo a serialização L2-vs-Playwright e o redeploy do flow da
  planta depois de cada rodada.
- (−) Um `push` com trabalho em andamento vai gerar vermelho de rotina. Aceito: `cancel-in-progress`
  limita o desperdício, e vermelho ruidoso é preferível a gate que ninguém executa.
