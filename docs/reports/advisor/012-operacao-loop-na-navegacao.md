# Plan 012: `/operacao/loop` entra na navegação, e o contrato de nav deixa de ser solto

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado antes de passar ao próximo. Se qualquer condição da seção "Condições de
> PARADA" ocorrer, pare e relate — não improvise. Ao terminar, atualize a sua linha na tabela de
> status de `docs/reports/advisor/README.md` — a menos que um revisor o tenha despachado e dito que
> ele mantém o índice.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 37b0caa..HEAD -- frontend/src/app/AppShell.tsx frontend/src/app/router.tsx frontend/src/features/loop frontend/e2e`
> Se qualquer arquivo em escopo mudou desde que este plano foi escrito, compare os excertos de
> "Estado atual" com o código vivo antes de prosseguir; em caso de divergência, trate como
> condição de PARADA.

## Status

- **Prioridade**: P1
- **Esforço**: S para a navegação · M se incluir o spec Playwright do Passo 4
- **Risco**: LOW — aditivo; a única asserção que pode precisar de ajuste é de layout do cabeçalho
- **Depende de**: nenhum. Idealmente **depois** do plano 010 (`LOOP_TYPES` fonte única), porque o
  teste que o 010 acrescenta é a rede que impede um kernel novo de repetir este buraco
- **Categoria**: bug / UX / testes
- **Planejado em**: commit `37b0caa`, 2026-09-19

## Por que isso importa

Existe uma tela de operação **entregue, com backend completo, e inalcançável pelo produto**.

`/operacao/loop` (`LoopOperatePage`, ADR-039) é a única superfície que comanda o modo — MAN/AUTO/
CAS/RCAS/ROUT/OOS — de um bloco `pid_loop` ou `fuzzy_loop` **em execução**. Tem rota
(`router.tsx:50`), tem hooks (`useLoops.ts`), tem três endpoints REST (`GET /api/operate/loop`,
`/{flow_id}/{block_id}`, `/{flow_id}/{block_id}/surface`) e histórico próprio
(`GET /api/history/loop`). Não tem **nenhum** link apontando para ela.

O irmão direto dela, Fuzzy (mesma família de ADR, mesmo padrão de construção), **tem** item de
navegação. Loop não tem. Um operador de turno — que o `PRODUCT.md:16` descreve explicitamente como
não-engenheiro, em sala de controle 24/7, com "ação em 1 gesto" — só chega à tela digitando a URL.

A causa não é descuido pontual, e é isso que torna o Passo 3 a parte importante deste plano:
**o contrato de navegação não é pinhado por teste nenhum.** Dos 9 `data-testid` de nav do
`AppShell.tsx`, exatamente **um** é asserido em algum lugar — `nav-configuracoes`, em
`settings-page.spec.ts:36` e `:139`, e só para visibilidade admin-vs-operador. Os outros oito
(`nav-operacao`, `nav-fuzzy`, `nav-eventos`, `nav-projetos`, `nav-conexoes`, `nav-tags`,
`nav-flows`, `nav-trend`) aparecem **somente** em `AppShell.tsx`. Nada falharia se um item fosse
removido ou apontasse para rota inexistente. Foi assim que a tela embarcou invisível, e é assim que
a próxima embarcaria.

Isto também **estende o TD-026** (regressão de tela de operação só detectada por Playwright manual):
esta superfície não tem nem caminho de descoberta nem gate de regressão — é a tela plant-facing
menos defendida do produto. Não é reafirmação do TD-026; é evidência nova dele.

## Estado atual

**A navegação, verbatim em `37b0caa`** — `frontend/src/app/AppShell.tsx:10-31`:
```tsx
/* Navegação em dois grupos (decisão A-10, spec F5 §7.3-1): Operação·Eventos são de
   operador (admin herda); Projetos·Conexões·Tags·Flows·Trend seguem visíveis para leitura —
   a ocultação de mutações é a tarefa 6.5. */
const NAV_OPERACAO = [
  { rotulo: "Operação", para: "/operacao", testid: "nav-operacao" },
  { rotulo: "Fuzzy", para: "/operacao/fuzzy", testid: "nav-fuzzy" },
  { rotulo: "Eventos", para: "/eventos", testid: "nav-eventos" },
] as const;

const NAV_ENGENHARIA = [
  { rotulo: "Projetos", para: "/engenharia/projetos", testid: "nav-projetos" },
  { rotulo: "Conexões", para: "/engenharia/conexoes", testid: "nav-conexoes" },
  { rotulo: "Tags", para: "/engenharia/tags", testid: "nav-tags" },
  { rotulo: "Flows", para: "/engenharia/flows", testid: "nav-flows" },
  { rotulo: "Trend", para: "/engenharia/trend", testid: "nav-trend" },
] as const;

/* Configurações gerais (RF-805): grupo próprio, só admin — operador nem vê o item (a rota
   também redireciona, SettingsPage). */
const NAV_ADMIN = [
  { rotulo: "Configurações", para: "/configuracoes", testid: "nav-configuracoes" },
] as const;
```

**O comentário da linha 10 já está desatualizado**: diz "Navegação em **dois** grupos", mas há
**três** (`NAV_ADMIN` foi acrescentado depois, com o próprio comentário explicando). Não reescreva o
comentário inteiro neste plano — mas se você acrescentar um item, ajuste a contagem se ela aparecer.

**A rota existe** — `frontend/src/app/router.tsx:50`:
```tsx
<Route path="/operacao/loop" element={<LoopOperatePage />} />
```

**Confirmação de que não há outro caminho de entrada**: `grep -rn 'operacao/loop' frontend/src frontend/e2e`
devolve apenas `router.tsx:11` (import) e `router.tsx:50` (rota). Nenhum `to="/operacao/loop"`,
nenhum `navigate("/operacao/loop")`, nenhum spec.

**Os `data-testid` que a tela já expõe** (não invente nenhum) — `LoopOperatePage.tsx`:
`loop-aguardando` (:132), `loop-faceplate` (:146), `loop-badge-target` (:149),
`loop-badge-actual` (:154), `loop-badge-pv-ruim` (:159), `loop-botoeira` (:165),
`loop-modo-<modo>` (:170, um por modo comandável), `loop-erro-comando` (:213),
`loop-sintonia` (:219), `loop-selecao` (:299), `loop-combobox` (:302).

**O gating que o spec vai asserir** — `LoopOperatePage.tsx:166-180`:
```tsx
{MODOS_COMANDAVEIS.map((modo) => (
  <button key={modo} disabled={!podeComandar(estado, modo)}
    data-testid={`loop-modo-${modo}`} onClick={() => void comandar("mode", { target: modo })}
```

**O modelo de spec a seguir** — `frontend/e2e/fuzzy-operate.spec.ts:1-30`. Leia o cabeçalho inteiro:
ele documenta **por que** o grafo é mínimo, por que roda **sem deploy** (nada é publicado no canal
de estado, então o spec exercita só o que vem da REST, nunca valor ao vivo) e o que fica para a L2.
Copie essa postura. A fixture é `criarAmbiente` de `frontend/e2e/fixtures.ts`.

**A única asserção de nav existente** — `frontend/e2e/settings-page.spec.ts:36` e `:139`.

## Convenções do repositório que se aplicam aqui

- **TypeScript strict**; componentes shadcn/ui; **UI e comentários em pt-BR**, identificadores de
  código em inglês (`CLAUDE.md`, "Convenções de código"). `docs/GLOSSARY.md` é o cânone de
  vocabulário — "malha" é o termo do ADR-039 para o bloco de loop; não invente "Loop"/"PID" no
  rótulo sem conferir o glossário.
- **`data-testid` obrigatório** em superfícies que o Playwright toca: o `CLAUDE.md` registra
  "data-testid: operate-*, faceplate-*, fuzzy-*, eventos-*, home-* (o roteiro L3 depende deles)".
  Use o prefixo `nav-` já estabelecido no `AppShell.tsx`.
- **O frontend nunca executa lógica de flow** (ADR-005). O spec não deve calcular nada de controle;
  só constatar o que a REST devolveu.
- **Commits em Conventional Commits, mensagem pt-BR.** Exemplo real:
  `fix(frontend): rótulo visível único (inválido) e tooltip com quality+substatus`.
- **`*.check.ts`** são checagens puras em Node (`npm run test:unit`); `e2e/*.spec.ts` são browser
  (`npm run e2e`, **manual** — ver abaixo). Não confunda as duas camadas.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Checagens puras | `cd frontend && npm run test:unit` | tudo passa |
| Typecheck | `cd frontend && npm run typecheck` | exit 0 |
| Build | `cd frontend && npm run build` | exit 0 |
| Nav ganhou item | `grep -c 'nav-malha' frontend/src/app/AppShell.tsx` | `1` |
| Contrato pinhado | `grep -rln 'NAV_OPERACAO\|nav-operacao' frontend/src --include=*.check.ts` | ≥ 1 arquivo |
| Spec parseia | `cd frontend && npx playwright test loop-operate.spec.ts --list` | lista os cenários, exit 0 |
| Nada de xyflow no chunk inicial | `cd frontend && npm run build && grep -l xyflow dist/assets/index-*.js` | **nenhuma** saída |

**NÃO rode `npm run e2e` nem `npx playwright test` sem `--list`.** O stack de 8 serviços do dono
está no ar com planta simulada viva. `frontend/e2e/fixtures.ts::criarAmbiente` **ativa projeto
próprio**, o que derruba os flows em execução do dono; e `playwright.config.ts:11` aponta `baseURL`
para `http://localhost:8080` — o container **do dono**, servindo o bundle da `main`, não o da sua
worktree. Rodar dá **verde falso** sobre código que não é o seu. Use `--list` para provar que o spec
parseia; a execução em browser fica com o revisor, serializada contra um stack reconstruído
(procedimento no runbook do plano 009).

**NÃO rode** `uv run pytest`, `docker compose`, `deploy/smoke.sh` nem `scripts/setup-l3.py`.
**NÃO invoque** nenhuma ferramenta do servidor MCP `ottima` desta sessão — elas comandam a planta viva.

## Escopo

**Em escopo** (únicos arquivos a modificar/criar):
- `frontend/src/app/AppShell.tsx` — acrescentar **um** item a `NAV_OPERACAO`
- `frontend/src/app/appShell.check.ts` (**criar**, ou o `*.check.ts` já existente que cubra o shell —
  verifique antes com `ls frontend/src/app/*.check.ts`)
- `frontend/e2e/loop-operate.spec.ts` (**criar**, Passo 4 — opcional se o revisor pedir só a nav)
- `frontend/e2e/settings-page.spec.ts` — **apenas** se o Passo 3 exigir mover a asserção de
  visibilidade admin; prefira não tocar

**Fora de escopo** (NÃO toque, mesmo parecendo relacionado):
- `frontend/src/features/loop/LoopOperatePage.tsx` e o resto de `features/loop/` — a tela **já está
  pronta e correta**. Este plano é sobre alcançá-la e pinhá-la, não sobre reescrevê-la.
- `frontend/src/app/router.tsx` — a rota já existe e está certa.
- `NAV_ENGENHARIA` e `NAV_ADMIN` — não reorganize grupos, não renomeie rótulos existentes, não mude
  a ordem dos itens atuais.
- `frontend/nginx.conf` — é dos planos 013.
- `frontend/src/features/operate/*` e `features/trend/*` — telas irmãs, fora daqui.
- `docs/` inteiro, inclusive o comentário desatualizado de `AppShell.tsx:10` além do ajuste de
  contagem mencionado.
- Qualquer backend.

## Fluxo de git

- Branch: `advisor/012-operacao-loop-na-navegacao`.
- **Dois commits separados**: um para a nav + check (Passos 1-3), outro para o spec (Passo 4). O
  revisor pode querer mesclar o primeiro sem o segundo, já que o spec precisa de stack para rodar.
- Sugestões de mensagem:
  `fix(frontend): tela de malha entra na navegacao de operacao` e
  `test(frontend): spec da tela de malha e contrato de navegacao pinhado`
- Sem push, sem PR, a menos que o operador peça.
- Em worktree: caminho **ABSOLUTO** em todo `read`/`write`/`edit`, `cwd` explícito em todo shell,
  confirmação por shell depois de cada escrita (`CLAUDE.md`, "Subagente em worktree").

## Passos

### Passo 1: acrescentar o item de navegação

Em `frontend/src/app/AppShell.tsx`, adicione **uma** entrada a `NAV_OPERACAO`. Posição: depois de
`Fuzzy`, antes de `Eventos` — `Eventos` é transversal (não é uma tela de bloco), e as duas telas de
bloco devem ficar juntas.

```tsx
const NAV_OPERACAO = [
  { rotulo: "Operação", para: "/operacao", testid: "nav-operacao" },
  { rotulo: "Fuzzy", para: "/operacao/fuzzy", testid: "nav-fuzzy" },
  { rotulo: "Malha", para: "/operacao/loop", testid: "nav-malha" },
  { rotulo: "Eventos", para: "/eventos", testid: "nav-eventos" },
] as const;
```

**Confirme o rótulo no glossário antes de gravar**: `grep -in 'malha\|loop' docs/GLOSSARY.md`. Se o
glossário fixar outro termo para o bloco de loop, **use o do glossário** e registre a escolha no seu
relato. O rótulo é string de UI, e o `CLAUDE.md` diz que o `GLOSSARY.md` governa nomes na UI.

Se o comentário de `:10-12` mencionar contagem de grupos ou de itens e ela passar a estar errada,
corrija **só a contagem**, sem reescrever a justificativa.

**Verifique**:
- `grep -c 'nav-malha' frontend/src/app/AppShell.tsx` → `1`
- `cd frontend && npm run typecheck` → exit 0

### Passo 2: verificar que o cabeçalho ainda cabe

O cabeçalho é um `flex` com três `<nav>` e separadores (`AppShell.tsx:82-103`), e agora tem **10**
itens em vez de 9. Isto é o único risco visual real do plano.

Não há browser disponível para você (ver a seção de comandos). Faça o que dá para fazer sem ele:
- `cd frontend && npm run build` → exit 0
- Leia `AppShell.tsx:78-104` e confirme se há `flex-wrap` ou truncamento. **Não há** `flex-wrap` no
  `<header>` em `37b0caa` — ele é `flex h-14 items-center justify-between`.
- Registre no seu relato, explicitamente: **"o cabeçalho passou de 9 para 10 itens e não tem
  `flex-wrap`; precisa de conferência visual em browser pelo revisor."**

**Não** adicione `flex-wrap`, não reduza `padding`, não troque fonte para fazer caber. Se couber,
ótimo; se não couber, é ajuste de design e pertence ao `DESIGN.md`, não a este plano. Relate.

**Verifique**: `cd frontend && npm run build` → exit 0.

### Passo 3: pinhar o contrato de navegação (a parte que impede a recorrência)

Este é o passo que justifica o plano existir. Sem ele, o próximo item esquecido embarca do mesmo jeito.

Crie (ou estenda, se já existir — confirme com `ls frontend/src/app/*.check.ts`) um
`frontend/src/app/appShell.check.ts`. O teste **não** renderiza React: ele importa as constantes de
nav e as cruza com a tabela de rotas, como função pura. Siga o padrão dos `*.check.ts` vizinhos
(leia um inteiro antes de escrever — por exemplo `frontend/src/features/operate/faceplateVariavel.check.ts`).

Para o cruzamento com as rotas ser possível sem renderizar, o `AppShell.tsx` precisa **exportar** as
três constantes de nav (hoje são module-private). Exporte-as — é uma mudança de uma palavra por
constante, sem efeito em runtime:
```tsx
export const NAV_OPERACAO = [ ... ] as const;
```

O check deve assertar, no mínimo:

1. **Toda rota de operação/engenharia/admin tem item de nav, e vice-versa.** Mantenha a lista de
   rotas esperadas **no próprio arquivo de teste**, como literal, com um comentário dizendo que ela
   espelha `router.tsx` e por quê. Não tente parsear `router.tsx` — fragiliza o teste.
   ```ts
   /** Espelha frontend/src/app/router.tsx:43-68. Se uma rota nova entrar lá e não aqui,
    *  este teste falha — que é exatamente o contrato que se quer pinhar. */
   const ROTAS_COM_NAV = ["/operacao", "/operacao/fuzzy", "/operacao/loop", "/eventos", ...];
   ```
   `/login` e `/` (HomePage) ficam **fora** da lista de nav, deliberadamente — registre isso no
   comentário do teste para o próximo leitor não "consertar".
2. **Nenhum `testid` duplicado** entre os três grupos.
3. **Todo item tem rótulo não-vazio e `para` começando com `/`.**
4. **`NAV_ADMIN` continua sendo o único grupo condicionado a `role === "admin"`** — isto é o que
   `settings-page.spec.ts:139` já verifica em browser; pinhar em Node torna a regra visível sem
   precisar de stack.

**Verifique**:
- `cd frontend && npm run test:unit` → tudo passa, incluindo os novos
- `grep -rln 'NAV_OPERACAO' frontend/src --include=*.check.ts` → ≥ 1 arquivo
- **RED genuíno**: remova temporariamente a linha de `Malha` do `NAV_OPERACAO`, rode
  `npm run test:unit` → **deve falhar**. Restaure a linha (edite de volta; **não** use
  `git checkout`/`stash`/`reset`) e rode de novo → passa. Registre os dois resultados no relato.

### Passo 4 (opcional, segundo commit): spec Playwright da tela de malha

Crie `frontend/e2e/loop-operate.spec.ts` **no padrão de `fuzzy-operate.spec.ts`**: cabeçalho em
comentário explicando o grafo mínimo, por que roda sem deploy, e o que fica para a L2.

> **DUAS RESTRIÇÕES QUE DEFINEM O ESCOPO DO SPEC — leia antes de escrever.**
>
> **1. Sem flow em deploy, a tela só mostra o cartão de espera.**
> `LoopOperatePage.tsx:130-138`: quando não há estado ao vivo, o componente retorna cedo com
> `loop-aguardando` ("Aguardando estado da malha (o bloco precisa estar rodando)…"). Portanto
> `loop-faceplate`, `loop-badge-target`, `loop-badge-actual`, `loop-botoeira` e `loop-modo-*`
> **não existem no DOM** até um flow deployado publicar em `loop.state.*`. Como o executor está
> **proibido** de dar deploy no stack do dono, qualquer cenário que dependa deles é inalcançável
> aqui.
>
> **2. O ambiente do L3 não tem bloco de malha.** `scripts/setup-l3.py` monta apenas o grafo
> MPC↔TFS (`grafo_mpc_tfs`, bloco `mpc1`); `grep -c 'pid_loop\|fuzzy_loop' scripts/setup-l3.py`
> → **0**. Então `GET /api/operate/loop` devolve lista vazia lá, e até o combobox ficaria vazio se
> o spec dependesse do ambiente pronto. **O spec tem de montar o próprio grafo** com um bloco de
> malha via `fixtures.ts::criarAmbiente`, exatamente como `fuzzy-operate.spec.ts` faz com os dois
> blocos fuzzy dele.

Grafo mínimo, montado pelo próprio spec: `opc_read` → `pid_loop` (ou `fuzzy_loop`), **sem deploy**.
O spec exercita só o que é derivado de configuração — `GET /api/operate/loop` projeta do
`graph_json`, sem precisar de runtime —, exatamente a postura documentada em
`fuzzy-operate.spec.ts:16-21`.

Cenários, usando **só** `data-testid` já existentes e **só** o que renderiza a frio:

- **PW-LOOP-01** — a navegação leva à tela: clicar em `nav-malha` resulta em URL `/operacao/loop`;
  `loop-selecao` visível. (É o cenário que prova o conserto do Passo 1.)
- **PW-LOOP-02** — `loop-combobox` lista o bloco de malha do grafo que o spec montou, vindo de
  `GET /api/operate/loop`. Prova a projeção a partir do `graph_json`, sem runtime.
- **PW-LOOP-03** — selecionado o bloco **sem flow em deploy**, a tela mostra `loop-aguardando`.
  É o contrato honesto da tela: sem estado publicado, ela **não** finge faceplate.

**O que NÃO entra no Playwright, e por quê**: badges (`loop-badge-target`/`-actual`), botoeira e
`loop-modo-*` desabilitado por `permitted` exigem `loop.state` publicado, logo flow em deploy. Esse
comportamento pertence à **L2**, em `tests/e2e/` (suíte python, marcada `e2e`, que tem stack real e
pode deployar). Registre no cabeçalho do spec que a cobertura de modo/permitted vive lá, para o
próximo leitor não achar que é esquecimento.

**Verifique**:
- `cd frontend && npx playwright test loop-operate.spec.ts --list` → lista os 3 cenários, exit 0
- `cd frontend && npm run test:unit` → tudo passa (o spec novo **não** pode aparecer aqui; confirme
  que `playwright.unit.config.ts` não o captura — o plano 006 do advisor anterior registrou essa
  separação)
- **Não rode o spec.** Registro no relato: "spec parseia; execução em browser pendente do revisor
  contra stack reconstruído".

## Plano de teste

- **Novo (Passo 3)**: `frontend/src/app/appShell.check.ts` — contrato de navegação como função
  pura, 4 asserções. É o teste que paga o plano inteiro.
- **Novo (Passo 4)**: `frontend/e2e/loop-operate.spec.ts` — 3 cenários alcançáveis a frio, padrão
  `fuzzy-operate.spec.ts`.
- **Padrão estrutural**: para o check, um `*.check.ts` vizinho (ex.:
  `frontend/src/features/operate/faceplateVariavel.check.ts`). Para o spec, `fuzzy-operate.spec.ts`
  na íntegra.
- **Nenhum teste existente precisa mudar.** Se `settings-page.spec.ts` quebrar, é porque você mexeu
  em `NAV_ADMIN` — volte atrás.
- **Verificação**: `cd frontend && npm run test:unit` → tudo passa, com os novos.

## Critérios de conclusão

Todos devem valer:

- [ ] `grep -c 'nav-malha' frontend/src/app/AppShell.tsx` → `1`
- [ ] `grep -rn 'operacao/loop' frontend/src` devolve a rota **e** o item de nav
- [ ] As três constantes de nav estão exportadas
- [ ] `frontend/src/app/appShell.check.ts` existe, com as 4 asserções
- [ ] O RED do Passo 3 foi reproduzido e revertido (registrado no relato)
- [ ] `cd frontend && npm run typecheck` → exit 0
- [ ] `cd frontend && npm run test:unit` → tudo passa
- [ ] `cd frontend && npm run build` → exit 0
- [ ] `grep -l xyflow frontend/dist/assets/index-*.js` → nenhuma saída (trava do CI, `gates.yml:75-87`)
- [ ] `cd frontend && npx playwright test loop-operate.spec.ts --list` → exit 0 (se fez o Passo 4)
- [ ] O relato registra: cabeçalho 9→10 itens sem `flex-wrap`, conferência visual pendente
- [ ] `git status --porcelain` lista só os arquivos em escopo
- [ ] Linha de status atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

Pare e relate (não improvise) se:

- Os excertos de "Estado atual" não baterem com o código vivo (drift desde `37b0caa`).
- `NAV_OPERACAO` já contiver um item para `/operacao/loop`: significa que alguém consertou; relate e
  faça **só** o Passo 3.
- O `docs/GLOSSARY.md` fixar um termo para o bloco de loop que conflite com "Malha" de forma que
  você não consiga resolver lendo o glossário: relate os dois termos, não escolha.
- Exportar as constantes de nav quebrar o build (circularidade de import, por exemplo): relate em
  vez de reorganizar módulos.
- Você concluir que precisa mexer em `LoopOperatePage.tsx` para o spec funcionar: **não mexa**.
  Relate o que faltou (provavelmente um `data-testid` ausente) e deixe para o revisor decidir.
- `npm run build` passar a emitir mais de um chunk inicial, ou `xyflow` aparecer no chunk inicial:
  pare — a trava do CI (`gates.yml:75-87`) reprovaria, e a causa não é óbvia deste plano.

## Notas de manutenção

- **O que interage com isto**: qualquer rota nova. O Passo 3 é deliberadamente uma lista literal
  espelhando `router.tsx` — o custo de adicionar uma rota passa a ser "atualizar o teste", que é
  exatamente o atrito que se quer. Não "melhore" o teste parseando o router: fragiliza.
- **O que um revisor deve olhar no PR**: (1) o diff em `AppShell.tsx` é **uma linha** mais a palavra
  `export` em três constantes — nada de reordenação; (2) o check falha de verdade quando um item
  some (o RED do Passo 3); (3) `LoopOperatePage.tsx` não foi tocado; (4) a conferência visual do
  cabeçalho foi feita em browser antes de mesclar.
- **Pendente de browser, por decisão**: a execução do `loop-operate.spec.ts` fica com o revisor,
  serializada contra um stack reconstruído — runbook nos Passos 1-3 do plano 009
  (`docs/reports/advisor/009-td-026-rebaixado-com-prova-de-suite-completa.md`).
- **Relação com o TD-026**: este plano reduz o custo do TD-026 para **esta** tela (ela ganha um
  spec), mas não fecha o item — o gatilho continua sendo de processo, não de máquina. Não marque o
  TD-026 como resolvido.
- **Adiado de propósito**: `LoopOperatePage.tsx` tem 332 linhas e um único `*.check.ts` no
  diretório (`HeatmapSuperficie.check.ts`, 1.4K) — a página em si não tem checagem pura. Extrair
  lógica dela para testável é trabalho próprio, e exige tocar numa tela plant-facing que hoje
  funciona; não cabe num plano de alcançabilidade.
