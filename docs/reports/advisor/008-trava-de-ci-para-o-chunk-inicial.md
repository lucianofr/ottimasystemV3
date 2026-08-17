# Plan 008: O CI passa a barrar o React Flow voltando ao chunk inicial, e a lacuna de regressão de browser fica registrada

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado esperado antes de passar ao próximo. Se qualquer condição da seção
> "Condições de PARADA" ocorrer, pare e relate — não improvise.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 1572849..HEAD -- .github/workflows/gates.yml docs/reports/_tech-debt.md frontend/vite.config.ts`
> Se algum arquivo em escopo mudou desde que este plano foi escrito, compare os excertos de
> "Estado atual" com o código vivo antes de prosseguir; divergência é condição de PARADA.

## Status

- **Prioridade**: P1
- **Esforço**: S
- **Risco**: LOW
- **Depende de**: 006 (mesclado; é o ganho que esta trava protege)
- **Categoria**: dx / tooling
- **Planejado em**: commit `1572849`, 2026-08-16

## Por que isso importa

Em 2026-08-16 uma regressão de performance entrou na `main` **com build verde, typecheck limpo,
`test:unit` 633 e nenhum teste falhando**. O plano 005 tirou o `@xyflow/react` do chunk inicial
com `React.lazy`; o ARCH-18 pôs os 9 componentes de nó dentro de `registro.ts`, que
`CanalAoVivo.tsx` alcança via `graph.ts` em **toda rota autenticada** — e a biblioteca voltou
para o chunk inicial. O chunk saltou de 505 kB para 708,80 kB e ninguém foi avisado. O plano 006
consertou. Nada impede de acontecer de novo amanhã.

Nenhum passo do `.github/workflows/gates.yml` olha em qual chunk o `@xyflow/react` caiu:

| Passo do CI hoje | Pegaria a regressão? |
|---|---|
| `ruff check` / `ruff format --check` | não (Python) |
| `npm run test:unit` | não (633 passaram durante a regressão) |
| `npm run typecheck` | não (typecheck estava limpo) |
| `npm run build` | não (build ficou verde) |
| Contrato gerado está em dia | não (nenhum model mudou) |

A trava é hermética: só `npm run build` + inspeção do `dist/`. Nada de Docker, nada de segredo,
nada da stack de 9 serviços — cabe exatamente dentro do escopo que a
[ADR-035](../../adr/ADR-035-mecanizacao-dos-gates.md) decidiu para o CI. **Não** há conflito
com a ADR nem com o TD-023: a ADR excluiu a stack e os testcontainers, e esta trava não é
nenhum dos dois. Ela não existia porque a classe de regressão não existia quando a ADR foi
escrita.

A segunda metade deste plano é registro, não código. A regressão de browser da tela de operação
(`PW-OP-11`, quebrado no mesmo dia por um hook novo em `TrendOperacao.tsx`) só foi pega porque
alguém rodou o Playwright à mão contra um stack reconstruído. Isso continua sendo verdade **por
decisão da ADR-035**, e está certo — mas hoje não está escrito em lugar nenhum do repositório, e
por isso depende de alguém lembrar. Um item de dívida transforma folclore em item rastreado.

## Estado atual

### `.github/workflows/gates.yml`, últimos passos

```yaml
      - name: npm run typecheck
        working-directory: frontend
        run: npm run typecheck

      - name: npm run build
        working-directory: frontend
        run: npm run build

      # Trava de forma prevista pelo ARCH-06/ADR-034: se um model Pydantic mudou sem o
      # `contracts.gen.ts` acompanhar, a geração produz diff e o passo falha.
      - name: Contrato gerado está em dia
        working-directory: frontend
        run: |
          npm run generate:contracts
          git diff --exit-code -- src/lib/contracts.gen.ts
```

O arquivo tem **11 passos** hoje. O cabeçalho dele (linhas 1-10) explica o critério de inclusão
("Só o que é HERMÉTICO entra aqui") e é o estilo de comentário a seguir: cada trava diz qual
vermelho real ela barra.

### O estado que a trava tem de recusar

Build da `main` @ `1572849` (correto, o que o CI verá no caso bom):

```
dist/assets/FlowEditorPage-CLg2yehU.js   270.02 kB
dist/assets/index-DGiKasej.js            505.43 kB
grep -l xyflow dist/assets/*.js  ->  dist/assets/FlowEditorPage-CLg2yehU.js
```

Build de `5c6d231` (o estado com a regressão, que a trava tem de barrar):

```
dist/assets/index-BcPGUG4Z.js            708.80 kB
grep -l xyflow dist/assets/*.js  ->  dist/assets/index-BcPGUG4Z.js
```

### `docs/reports/_tech-debt.md`

Registro de dívida do projeto. Maior número em uso: **TD-025**. Itens abertos usam
`- [ ] **TD-NNN**: ...`; resolvidos usam `- [x]` com blocos `**Resolved:**`, `**Resolution:**` e
`**Prova:**`. As "Priority Guidelines" do topo do arquivo definem os níveis
(Critical / High / Medium / Low) e a cadência de revisão. O TD-023 está **fechado** e não deve
ser reaberto: a decisão dele (E2E fora do CI) é deliberada e continua válida.

## Convenções do repositório que se aplicam aqui

- Comentários em **pt-BR**, identificadores em inglês, **sem emoji** (`CLAUDE.md:68-69`).
- Comentário de gate no `gates.yml` nomeia o vermelho concreto que ele barra — siga esse padrão.
- Conventional Commits em pt-BR (`CLAUDE.md:70`).

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| YAML válido e nº de passos | `uv run python -c "import yaml;d=yaml.safe_load(open('.github/workflows/gates.yml'));print(len(d['jobs']['gates']['steps']))"` | `12` |
| Build | `cd frontend && npm run build` | exit 0 |
| GREEN da trava | ver Passo 2 | passa em silêncio |
| RED da trava | ver Passo 3 | falha com a mensagem de erro |

Não rode `docker compose`, não reconstrua container, não rode Playwright, não rode
`uv run pytest`. Nada neste plano precisa da stack.

## Escopo

**Em escopo** (2 arquivos):
- `.github/workflows/gates.yml` — um passo novo.
- `docs/reports/_tech-debt.md` — um item novo, `TD-026`.

**Fora de escopo** (NÃO toque):
- `frontend/vite.config.ts` — **nada de `manualChunks`, nada de `chunkSizeWarningLimit`**. A
  trava mede o resultado; ela não muda como o bundle é fatiado.
- `frontend/package.json` — não crie script npm novo para isto. O comando do gate mora no
  workflow; quem quiser rodar local roda as duas linhas à mão (estão na nota de manutenção).
- `docs/adr/ADR-035-mecanizacao-dos-gates.md` — não reescreva a ADR. Esta trava está dentro do
  escopo que ela definiu, não contra ele.
- Qualquer passo existente do `gates.yml`, e o item TD-023 (fechado, decisão deliberada).
- `frontend/src/**` — nenhuma linha de produção muda neste plano.

## Fluxo de git

Commite na branch da sua worktree; sem push, sem PR. Sugestão de mensagem:
`ci(gates): barra o React Flow voltando ao chunk inicial`

## Passos

### Passo 1: o passo novo no workflow

No `.github/workflows/gates.yml`, **imediatamente depois** do passo `npm run build` e **antes**
de `Contrato gerado está em dia`, acrescente um passo chamado
`React Flow fora do chunk inicial`, com `working-directory: frontend`, que:

1. resolve o chunk inicial pelo glob `dist/assets/index-*.js` e **falha** se ele não existir ou
   se o glob casar mais de um arquivo — senão uma mudança de nome de chunk faria a trava passar
   sem ter verificado nada, que é pior do que não ter trava;
2. falha se esse arquivo contiver `xyflow`, com mensagem de erro que aponte o caminho do chunk e
   cite o plano 006 / ARCH-18 para quem for depurar;
3. passa em silêncio no caso bom.

Reaproveite o `dist/` que o passo `npm run build` anterior já produziu — **não** rode `build` de
novo dentro do passo novo.

Escreva o comentário acima do passo no estilo do arquivo, nomeando o vermelho real: o plano 005
tirou o `@xyflow/react` do chunk inicial com `React.lazy`, e o ARCH-18 o trouxe de volta ao pôr
os componentes de nó em `registro.ts` — que `CanalAoVivo.tsx` alcança via `graph.ts` em toda
rota — com build verde, typecheck limpo e 633 testes passando. Registre que nenhum outro passo
deste arquivo pega essa classe.

**Verifique**:
`uv run python -c "import yaml;d=yaml.safe_load(open('.github/workflows/gates.yml'));print(len(d['jobs']['gates']['steps']))"`
→ **12**.

### Passo 2: o GREEN — a trava passa na `main` atual

```bash
cd frontend && npm run build
```

Depois rode **o mesmo comando shell que você escreveu no passo do workflow**, à mão, dentro de
`frontend/`. Ele tem de **passar** (exit 0, sem mensagem de erro).

**Verifique também**: `grep -l xyflow dist/assets/*.js` lista só um `FlowEditorPage-*.js`.

### Passo 3: o RED — a trava recusa o estado com a regressão

Uma trava que nunca foi vista falhando não é trava. Reproduza o estado defeituoso **sem tocar
sua worktree nem a árvore do dono**, extraindo o commit `5c6d231` para um diretório temporário
fora do repositório:

```bash
mkdir -p /tmp/red-008 && git archive 5c6d231 -- frontend | tar -x -C /tmp/red-008
cd /tmp/red-008/frontend && npm install && npm run build
```

Rode o mesmo comando shell do passo do workflow dentro de `/tmp/red-008/frontend`.

**Verifique**: ele **FALHA**, com exit diferente de 0 e a mensagem de erro que você escreveu.
Anote a linha exata. Depois remova o diretório: `rm -rf /tmp/red-008`.

**Nunca** use `git checkout`, `git stash` ou `git reset` para chegar nesse estado — só
`git archive` para fora do repositório.

### Passo 4: registrar a lacuna que fica de pé

Em `docs/reports/_tech-debt.md`, acrescente um item aberto **`TD-026`**, no grupo de prioridade
que as "Priority Guidelines" do arquivo indicarem para "causa incidentes / atrasa o time"
(escolha pelo texto do próprio arquivo, não por palpite), com este conteúdo, na forma dos outros
itens:

- **O que**: regressão de comportamento da tela de operação só é detectada rodando o Playwright
  à mão contra um stack reconstruído.
- **Evidência de 2026-08-16**: `PW-OP-11` (zoom em X sobrevive à troca do eixo Y) ficou vermelho
  ao mesclar o fix de tema em `TrendOperacao.tsx` — o helper do cenário varre a lista de hooks
  da fibra do React com teto fixo, e um hook novo (`useTema`) pôs o ref do uPlot fora do
  alcance. Passou por `ruff`, `test:unit` 633, `typecheck` e `build` **todos verdes**. Só
  apareceu quando alguém reconstruiu o container e rodou `operate-trend.spec.ts`.
- **Por que continua aberto e não é esquecimento**: a ADR-035 decidiu que a stack de 9 serviços,
  o `opcsim` e as credenciais de `deploy/.env` ficam fora do CI. O item registra o **custo** da
  decisão, para ele ser revisto de olho aberto — não a contradiz.
- **Mitigação em uso hoje**: rodar `cd frontend && npm run e2e` (ou o spec afetado) contra o
  stack reconstruído a partir da `main` antes de considerar mesclada qualquer mudança em
  `frontend/src/features/operate/` ou `frontend/src/features/trend/`.

Não mexa em nenhum outro item do arquivo. Em especial, **não** reabra o TD-023.

**Verifique**: `grep -c 'TD-026' docs/reports/_tech-debt.md` → maior que 0, e
`grep -c '^- \[x\] \*\*TD-023' docs/reports/_tech-debt.md` → continua `1` (segue fechado).

## Plano de teste

Sem teste automatizado novo: o entregável **é** um gate, e a prova dele é o par RED/GREEN dos
Passos 2 e 3 — passa no estado bom, falha no estado ruim conhecido. É mais forte que um teste
unitário do comando, porque exercita o artefato real de build nos dois estados.

## Critérios de conclusão

- [ ] `uv run python -c "import yaml;d=yaml.safe_load(open('.github/workflows/gates.yml'));print(len(d['jobs']['gates']['steps']))"` → `12`
- [ ] Passo 2 (GREEN) executado: a trava passa na `main` atual
- [ ] Passo 3 (RED) executado: a trava falha no build de `5c6d231`, com a mensagem anotada
- [ ] `/tmp/red-008` removido
- [ ] `grep -c 'TD-026' docs/reports/_tech-debt.md` > 0
- [ ] `grep -c '^- \[x\] \*\*TD-023' docs/reports/_tech-debt.md` → 1
- [ ] `git diff --name-only HEAD~1` lista **só** `.github/workflows/gates.yml` e `docs/reports/_tech-debt.md`
- [ ] `git diff HEAD~1 -- frontend` → **vazio**
- [ ] `grep -c 'manualChunks\|chunkSizeWarningLimit' frontend/vite.config.ts` → 0

## Condições de PARADA

- O Passo 2 falhar: a `main` já está com o `@xyflow/react` no chunk inicial, e aí o problema é
  outro (uma regressão nova). Relate os tamanhos de chunk que você mediu, não conserte.
- O Passo 3 **passar** em vez de falhar: sua trava não pega a regressão que ela existe para
  pegar. Não a mantenha assim — relate o que observou.
- `npm install` em `/tmp/red-008` falhar por falta de rede: relate, e reporte o Passo 3 como não
  executado em vez de declarar a trava provada.
- Você concluir que precisa mexer em `vite.config.ts` para a trava passar: isso inverte o
  propósito da trava. Pare e relate.

## Notas de manutenção

- **O que um revisor deve escrutinar**: que a trava falha por chunk ausente/ambíguo (não só por
  `xyflow` presente), e que `git diff HEAD~1 -- frontend` está vazio.
- Comando equivalente para rodar na mão, sem CI:
  `cd frontend && npm run build && grep -l xyflow dist/assets/index-*.js` — **não** deve listar
  nada.
- Se um dia o editor de canvas passar a ser importado por uma rota que todo usuário carrega, a
  trava vai ficar vermelha com razão. A resposta certa nesse caso é rever a decisão do plano 005
  (e medir), nunca relaxar a trava.
- O ponto de entrada a vigiar é `CanalAoVivo.tsx` → `graph.ts`, porque é o que garante presença
  em toda rota autenticada.
