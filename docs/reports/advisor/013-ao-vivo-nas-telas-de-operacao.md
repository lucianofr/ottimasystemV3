# Plan 013: Telas de operação deixam de mostrar número congelado como se fosse ao vivo

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado antes de passar ao próximo. Se qualquer condição da seção "Condições de
> PARADA" ocorrer, pare e relate — não improvise. **O Passo 2 exige uma decisão de apresentação que
> este plano fixa de propósito** (travessão + aviso, o padrão que `tagsOnline.ts` já usa) — não
> invente outra. Ao terminar, atualize a sua linha na tabela de status de
> `docs/reports/advisor/README.md` — a menos que um revisor o tenha despachado e dito que ele
> mantém o índice.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 37b0caa..HEAD -- frontend/src/features/operate frontend/src/features/loop frontend/src/features/fuzzy frontend/src/app/CanalAoVivo.tsx frontend/src/features/tags/tagsOnline.ts`
> Se qualquer arquivo em escopo mudou desde que este plano foi escrito, compare os excertos de
> "Estado atual" com o código vivo antes de prosseguir; em caso de divergência, trate como
> condição de PARADA.

## Status

- **Prioridade**: P1 — **o achado de maior severidade desta auditoria**
- **Esforço**: M
- **Risco**: LOW — puramente aditivo no render; nenhum reducer, assinatura ou envio de comando muda
- **Depende de**: nenhum
- **Categoria**: bug / segurança de processo
- **Planejado em**: commit `37b0caa`, 2026-09-19

## Por que isso importa

Durante uma queda do WebSocket, as telas de operação **continuam mostrando o último valor recebido
como se fosse a leitura de agora** — PV, SP, MV, e as lâmpadas de flow/solver/modo — sem nenhum
indicador de que os dados pararam de chegar. Um operador de turno olhando o faceplate durante um
distúrbio de planta vê números confiantes e congelados, e age sobre eles.

Isto não é uma opinião sobre UX: **o próprio repositório já decidiu essa regra e já a implementou —
em outra tela.**

`frontend/src/features/tags/tagsOnline.ts:39-43`, verbatim:
> `aoVivo === false` (socket em `conectando`/`reconectando`) descarta a leitura em mão de propósito:
> `tagValues` congela no último lote recebido e **exibir aquele número como se fosse a leitura de
> agora é a falha perigosa desta tela**.

E implementa: `celulaOnline(leitura, aoVivo)` devolve `valor: null` quando `!aoVivo` (`:46-48`), e a
página desenha travessão. A tela de Tags — que **não escreve na planta** — tem a proteção. As telas
de operação — que **escrevem SP e MV num MPC vivo** — não têm.

Segundo reforço, também do próprio repo: `frontend/src/app/AppShell.tsx:53-56` documenta que um
congelamento silencioso da tela de operação é *"o pior modo de falha numa sala de controle"*, e por
isso criou o `VigiaSessao`. Mas o `VigiaSessao` só reage a `estado === "sessao_invalida"` — o caso
**terminal** (logout). O caso **transitório**, `"reconectando"`, que é o comum e o demorado, não
produz nada em tela nenhuma.

E o caso transitório pode durar muito: `frontend/src/features/flows/canalPrimitivos.ts:50-52` faz
backoff exponencial até 15 s por tentativa, **sem teto de tentativas**, somado a um detector de
socket mudo de 30 s (`canalPrimitivos.ts:33-36`). Minutos de tela congelada e confiante.

O dado está à mão. `OperatePage.tsx:58` já faz `const canal = useCanalAoVivo()` — e `canal.estado`
está nesse mesmo objeto (`CanalAoVivo.tsx:83`). As telas simplesmente nunca leem esse campo.

## Estado atual

**O tipo que já existe** — `frontend/src/app/CanalAoVivo.tsx:80-90`:
```ts
type EstadoConexaoCanal = "conectando" | "aberto" | "reconectando" | "sessao_invalida";

export interface EstadoDoCanal {
  estado: EstadoConexaoCanal;
  flowStatus: ReadonlyMap<number, FlowStatus>;
  mpcStates: ReadonlyMap<string, MpcState>;
  fuzzyStates: ReadonlyMap<string, FuzzyState>;
  loopStates: ReadonlyMap<string, LoopState>;
  ...
```

**Os Maps nunca são limpos na queda** — `CanalAoVivo.tsx:431-453`: os ramos `mpc_state`,
`fuzzy_state` e `loop_state` só fazem `new Map(atual.X)` + `.set(...)`. Não há ramo que apague. E
isso é **deliberado**: `CanalAoVivo.tsx:708-711` registra a decisão de não apagar entradas na
desassinatura, porque `resolverAlarmes`/`estadoMaisNovoQueEvento` (`alarmes.ts`) dependem do dado
para resolver reocorrência de alarme.

> **Consequência para este plano, e é importante**: a correção **NÃO é limpar os Maps na queda**.
> Isso quebraria a resolução de alarmes, exatamente o problema que `:708-711` diz que seria "PIOR".
> A correção é **no render** — decidir, na hora de desenhar, se o valor em mão pode ser apresentado
> como ao vivo. É o que `tagsOnline.ts` faz.

**As quatro telas que ignoram `canal.estado`** (todas confirmadas por leitura em `37b0caa`):

| Arquivo | Linha | O que lê | O que ignora |
|---|---|---|---|
| `frontend/src/features/operate/OperatePage.tsx` | `:58-59` | `canal.mpcStates.get(...)` | `canal.estado` |
| `frontend/src/features/loop/LoopOperatePage.tsx` | `:112-114` | `canal.loopStates.get(...)` | `canal.estado` |
| `frontend/src/features/fuzzy/FuzzyOperatePage.tsx` | `:57-59` | `canal.fuzzyStates.get(...)` | `canal.estado` |
| `frontend/src/features/operate/TrendOperacao.tsx` | `:583` | `canal.tagValues` | `canal.estado` |

Mais `frontend/src/features/operate/FaceplateVariavel.tsx:212-215`, que lê `canal.tagValues` e faz o
fallback documentado para `mpc.state` — também sem consultar `estado`.

`OperatePage.tsx:53-59`, verbatim:
```tsx
  useAssinatura({
    flow_status: [flowId],
    mpc_state: [`${String(flowId)}/${blockId}`],
    opc_values: tagIds,
  });
  const canal = useCanalAoVivo();
  const mpcState = canal.mpcStates.get(`${String(flowId)}/${blockId}`);
```

**Os dois precedentes que provam que a convenção já existe e funciona**:

1. `frontend/src/features/tags/tagsOnline.ts:45-48` — o gate por `aoVivo`:
```ts
export function celulaOnline(leitura: LeituraTag | undefined, aoVivo: boolean): CelulaOnline {
  if (leitura === undefined || !aoVivo) {
    return { valor: null, quality: SEM_DADO, tone: "neutral" };
  }
```
2. `frontend/src/features/flows/FlowEditorPage.tsx:207-244` (`CabecalhoAoVivo`) — avisa quando
   `aoVivo.conexao !== "aberta"`, reusando `ROTULO_CONEXAO` de
   `frontend/src/features/flows/useFlowStatus.ts:46-50`. **Reutilize esse rótulo**; não escreva um
   texto novo.

> **ARMADILHA DE TIPO — leia antes do Passo 2.** Existem **dois** unions quase idênticos para o
> estado da conexão, e eles diferem exatamente no discriminador de "aberto":
>
> - `frontend/src/app/CanalAoVivo.tsx:80` —
>   `type EstadoConexaoCanal = "conectando" | "aberto" | "reconectando" | "sessao_invalida";`
>   (**`aberto`**, masculino)
> - `frontend/src/features/flows/useFlowStatus.ts:28` —
>   `export type EstadoConexao = "conectando" | "aberta" | "reconectando" | "sessao_invalida";`
>   (**`aberta`**, feminino)
>
> `ROTULO_CONEXAO` (`useFlowStatus.ts:46-50`) é
> `Record<Exclude<EstadoConexao, "sessao_invalida">, string>` — ou seja, tem chaves
> `conectando` / **`aberta`** / `reconectando`, e **não tem chave `aberto`**. Passar um
> `EstadoConexaoCanal` direto para ele **não compila**.
>
> **O que fazer**: as duas chaves que interessam a este plano (`conectando`, `reconectando`) têm
> grafia **idêntica** nos dois unions. Então o reaproveitamento é seguro desde que você estreite o
> tipo localmente, num único lugar — é o que o Passo 1 manda fazer em `aoVivo.ts`. **NÃO renomeie
> nenhum dos dois unions e não os unifique**: isso é mudança transversal que alcançaria
> `FlowEditorPage.tsx`, `useFlowStatus.check.ts` e todo consumidor do editor, muito além do escopo
> deste plano. Se você achar que unificar é o certo, **relate como sugestão no seu relatório** e
> siga sem unificar.

**O que já está testado e serve de padrão** — `frontend/src/features/flows/useFlowStatus.check.ts`
cobre a lógica de conexão do editor. É o modelo para o check novo do Passo 1.

## Convenções do repositório que se aplicam aqui

- **Falhar para o lado seguro é inegociável** (`PRODUCT.md:62`). Aqui isso tem tradução concreta, e
  ela já está escrita em `tagsOnline.ts:39-43`: número congelado **não** se apresenta como número.
- **Regra do Número Tabular / Regra do Canal Redundante** (`tagsOnline.ts:29-31` e `:43`): travessão
  vem **sem** a EU ao lado (travessão não é número); qualidade ruim vai **ao lado** do valor, não no
  lugar dele. Siga as duas — elas já resolveram as perguntas de apresentação que este plano levanta.
- **Estado publicado é a única verdade** (ADR-002, `PRODUCT.md:63`). Não introduza valor otimista nem
  "último conhecido" apresentado como corrente.
- **UI 100% pt-BR** (ADR-023). Rótulos em pt-BR; identificadores em inglês.
- **TypeScript strict**; componentes shadcn/ui; `data-testid` em tudo que o Playwright toca
  (`CLAUDE.md`: "data-testid: operate-*, faceplate-*, fuzzy-*, eventos-*, home-*").
- **Commits em Conventional Commits, mensagem pt-BR.** Exemplo real:
  `fix(frontend): rótulo visível único (inválido) e tooltip com quality+substatus`.
- **Não criar segunda convenção ao lado da existente.** O gate por `aoVivo` já tem forma e nome na
  casa; estenda-o, não o reinvente.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Checagens puras | `cd frontend && npm run test:unit` | tudo passa |
| Typecheck | `cd frontend && npm run typecheck` | exit 0 |
| Build | `cd frontend && npm run build` | exit 0 |
| Gate aplicado | `grep -rn 'aoVivo\|conexaoAberta' frontend/src/features/operate frontend/src/features/loop frontend/src/features/fuzzy` | ≥ 1 hit por diretório |
| Maps intactos | `git diff -- frontend/src/app/CanalAoVivo.tsx` | **vazio**, ou só adição de tipo exportado |
| Spec lista | `cd frontend && npx playwright test --list` | exit 0 |
| Chunk inicial limpo | `grep -l xyflow frontend/dist/assets/index-*.js` | nenhuma saída |

**NÃO rode `npm run e2e` nem `npx playwright test` sem `--list`.** O stack de 8 serviços do dono
está no ar com planta simulada viva; `frontend/e2e/fixtures.ts::criarAmbiente` ativa projeto próprio
e derrubaria os flows dele; e `playwright.config.ts:11` aponta para o container **do dono** servindo
o bundle da `main` — rodar dá **verde falso** sobre código que não é o seu. A verificação em browser
fica com o revisor (runbook nos Passos 1-3 do plano 009).

**NÃO rode** `uv run pytest`, `docker compose`, `deploy/smoke.sh`, `scripts/setup-l3.py`.
**NÃO invoque** nenhuma ferramenta do servidor MCP `ottima` desta sessão — comandam a planta viva.

## Escopo

**Em escopo** (únicos arquivos a modificar/criar):
- `frontend/src/features/operate/aoVivo.ts` (**criar**) — a função pura do gate
- `frontend/src/features/operate/aoVivo.check.ts` (**criar**) — checagens puras
- `frontend/src/features/operate/OperatePage.tsx`
- `frontend/src/features/operate/FaceplateVariavel.tsx`
- `frontend/src/features/operate/FaceplatePrincipal.tsx`
- `frontend/src/features/loop/LoopOperatePage.tsx`
- `frontend/src/features/fuzzy/FuzzyOperatePage.tsx`
- `frontend/src/app/CanalAoVivo.tsx` — **somente** se for preciso exportar o tipo
  `EstadoConexaoCanal` (hoje é module-private, `:80`). Nada além disso.

**Fora de escopo** (NÃO toque, mesmo parecendo relacionado):
- **A lógica do reducer, da assinatura e do backoff** em `CanalAoVivo.tsx`. Especialmente: **não
  limpe os Maps na queda** — `:708-711` documenta por que isso seria pior.
- `frontend/src/features/operate/TrendOperacao.tsx` (`:583`). Está no achado, mas é a tela de
  tendência da operação, tem 1052 linhas, é o arquivo dos planos 002/007 do advisor anterior e do
  TD-026. Misturá-la aqui amplia o raio e o risco de revisão. **Fica para plano próprio** — registre
  no seu relato que ficou de fora e por quê.
- `frontend/src/features/tags/tagsOnline.ts` — **já está certo**. É o modelo, não o alvo.
- `frontend/src/app/AppShell.tsx` — é do plano 012. Não adicione banner global aqui; o aviso pertence
  à tela que mostra o número.
- `frontend/src/features/flows/*` — `useFlowStatus.ts` e `FlowEditorPage.tsx` são leitura de
  referência (`ROTULO_CONEXAO`), não alvo de edição.
- `frontend/nginx.conf`, `docs/`, qualquer backend.

## Fluxo de git

- Branch: `advisor/013-ao-vivo-nas-telas-de-operacao`.
- Commits separados por tela, para o revisor poder aceitar parcialmente:
  1. `feat(frontend): gate aoVivo como funcao pura + checks` (Passo 1)
  2. `fix(frontend): faceplate do MPC nao mostra valor congelado como ao vivo` (Passo 2)
  3. `fix(frontend): telas de malha e fuzzy respeitam o estado da conexao` (Passo 3)
- Sem push, sem PR, a menos que o operador peça.
- Em worktree: caminho **ABSOLUTO** em todo `read`/`write`/`edit`, `cwd` explícito em todo shell,
  confirmação por shell depois de cada escrita (`CLAUDE.md`, "Subagente em worktree").

## Passos

### Passo 1: a função pura do gate (RED → GREEN)

Crie `frontend/src/features/operate/aoVivo.ts`. Uma função pura, sem React, no estilo de
`tagsOnline.ts::celulaOnline` — é isso que a torna testável em `npm run test:unit` sem browser.

Forma a produzir (assinatura e nomes são a parte load-bearing; o corpo é seu):

```ts
import type { EstadoConexaoCanal } from "../../app/CanalAoVivo";

/** `true` só com o socket aberto. `conectando`/`reconectando`/`sessao_invalida` ⇒ falso.
 *
 * Mesmo critério de `tagsOnline.ts:39-43`: com o canal fora, os Maps de estado congelam no
 * último lote recebido e exibir aquele número como se fosse a leitura de agora é a falha
 * perigosa de uma tela de operação. */
export function canalAoVivo(estado: EstadoConexaoCanal): boolean {
  return estado === "aberto";
}
```

Se `EstadoConexaoCanal` não estiver exportado em `CanalAoVivo.tsx:80`, **exporte o tipo** (só a
palavra `export`; não mova nem renomeie nada). Essa é a única edição permitida naquele arquivo.

Depois crie `frontend/src/features/operate/aoVivo.check.ts` cobrindo os **quatro** valores do union
— um por caso, sem parametrização redundante. (Os 3 casos de `rotuloConexao` entram no Passo 2.)
- `"aberto"` → `true`
- `"conectando"` → `false`
- `"reconectando"` → `false`
- `"sessao_invalida"` → `false`

Siga o padrão de `frontend/src/features/flows/useFlowStatus.check.ts` (leia-o inteiro antes).

**Verifique**:
- `cd frontend && npm run typecheck` → exit 0
- `cd frontend && npm run test:unit` → tudo passa, com os 4 novos
- **RED genuíno**: troque temporariamente o corpo para `return true`, rode `npm run test:unit` →
  **deve falhar** nos três casos. Reverta editando de volta (**não** use `git checkout`/`stash`/
  `reset`), rode de novo → passa. Registre os dois resultados no relato.

### Passo 2: o faceplate do MPC

Em `frontend/src/features/operate/OperatePage.tsx`:
- `:58-59` já tem `const canal = useCanalAoVivo()`. Calcule `const aoVivo = canalAoVivo(canal.estado);`.
- Passe `aoVivo` para baixo, para `FaceplatePrincipal` e `FaceplateVariavel`.
- **Não** transforme `mpcState` em `undefined` quando `!aoVivo`. O estado continua sendo usado para
  coisas que não são "número ao vivo" (rótulos de configuração, lista de variáveis). Gate só o que é
  apresentado como corrente.

Em `frontend/src/features/operate/FaceplateVariavel.tsx`:
- `:212-215` lê `canal.tagValues` e faz fallback para `mpc.state`. Com `!aoVivo`, o valor exibido
  passa a ser **travessão sem EU** — exatamente o `valor: null` de `tagsOnline.ts:31`. Reutilize o
  caminho de "sem dado" que já existe; não crie um ramo de render novo.

Em `frontend/src/features/operate/FaceplatePrincipal.tsx`:
- As lâmpadas (`LampadaInputValido`/`LampadaFlow`/`LampadaSolver`, `:70-77` e `:92-102`) **não podem
  continuar verdes** com canal fora. Elas já colapsam `undefined` para o lado seguro (verificado:
  neutro/alerta, nunca verde falso) — então o caminho é tratá-las como "sem confirmação" quando
  `!aoVivo`, não inventar uma quarta cor.
- Adicione **um** aviso visível de conexão com `data-testid="operate-aviso-conexao"`, usando os
  textos de `ROTULO_CONEXAO` (`frontend/src/features/flows/useFlowStatus.ts:46-50`) **por meio de
  uma função pura em `aoVivo.ts`** que estreite o tipo — ver a ARMADILHA DE TIPO em "Estado atual".
  Forma sugerida, testável em Node sem render:
  ```ts
  /** `null` quando não há aviso a mostrar (canal aberto, ou sessão inválida — caso em que o
   *  `VigiaSessao` de AppShell.tsx:58-66 já deslogou). */
  export function rotuloConexao(estado: EstadoConexaoCanal): string | null {
    if (estado === "conectando" || estado === "reconectando") return ROTULO_CONEXAO[estado];
    return null;
  }
  ```
  Acrescente 3 casos ao `aoVivo.check.ts` do Passo 1 (os dois rótulos não-nulos e o `null` de
  `"aberto"`). **Não escreva texto de aviso novo.**

**Verifique**:
- `cd frontend && npm run typecheck` → exit 0
- `cd frontend && npm run test:unit` → tudo passa
- `grep -n 'aoVivo' frontend/src/features/operate/FaceplateVariavel.tsx` → ≥ 1 hit

### Passo 3: malha e fuzzy

Mesma forma, nos dois arquivos:
- `frontend/src/features/loop/LoopOperatePage.tsx:112-114` — `LoopResolvido` lê
  `canal.loopStates.get(...)`; acrescente `aoVivo` e gate as barras PV/SP/OUT (`:184-192`) e os
  badges (`loop-badge-target`, `loop-badge-actual`).
  **Atenção específica desta tela**: a botoeira de modo (`:165-181`) usa
  `podeComandar(estado, modo)`. Com canal fora, `estado` é congelado — **os botões devem ficar
  desabilitados**, porque comandar modo com base em estado velho é exatamente o gesto perigoso.
  A assinatura real é `podeComandar(estado: LoopState, modo: ModoLoop): boolean`
  (`LoopOperatePage.tsx:31-33`): `estado` é **não-nulável**, então ela nunca vê "estado ausente" e
  **não é o lugar do gate**. Gate no **call site** (`:169`), sem alterar `podeComandar`:
  ```tsx
  disabled={!aoVivo || !podeComandar(estado, modo)}
  ```
- `frontend/src/features/fuzzy/FuzzyOperatePage.tsx:57-59` — mesma forma para `canal.fuzzyStates`.
  As curvas de pertinência vêm de `GET /api/operate/fuzzy/...` (REST, não WS), então **essas
  continuam desenhadas** — gate só o que vem do canal ao vivo (valores de porta, tendência).
  Registre essa distinção no comentário do código.

**Verifique**:
- `cd frontend && npm run typecheck` → exit 0
- `cd frontend && npm run test:unit` → tudo passa
- `grep -rn 'aoVivo' frontend/src/features/loop frontend/src/features/fuzzy` → ≥ 1 hit em cada
- `cd frontend && npm run build` → exit 0
- `grep -l xyflow frontend/dist/assets/index-*.js` → nenhuma saída

### Passo 4: o que você NÃO vai verificar, escrito no relato

Registre explicitamente no seu relatório final, para o revisor não assumir que foi feito:

1. **Prova em browser pendente.** O comportamento só é observável derrubando o socket com a tela
   aberta, o que exige stack. Você entregou typecheck + `test:unit` + build.
2. **`TrendOperacao.tsx:583` ficou de fora**, com o motivo (raio de revisão, histórico TD-026 /
   planos 002 e 007).
3. **Os Maps de `CanalAoVivo` não foram tocados**, e por quê (`:708-711`).
4. `git diff --stat` completo do que você mudou.

## Plano de teste

- **Novo**: `frontend/src/features/operate/aoVivo.check.ts` — 7 casos no total: 4 de `canalAoVivo`
  (Passo 1) + 3 de `rotuloConexao` (Passo 2).
- **Padrão estrutural**: `frontend/src/features/flows/useFlowStatus.check.ts` (para a forma do
  check) e `frontend/src/features/tags/tagsOnline.ts` (para a semântica do gate).
- **A lógica de apresentação das telas** (travessão vs número, lâmpada, botoeira desabilitada) não é
  testável em `test:unit` sem render — e o repo não tem render de componente em Node. **Não introduza
  um framework de render novo** (jsdom/testing-library) para isso: seria uma segunda convenção. A
  cobertura dessas três decisões fica no spec de browser, que é o Passo 4 do revisor. Registre isso.
- **Nenhum teste existente deve mudar.** Se algum mudar, você alterou comportamento além do gate —
  pare e relate.
- **Verificação**: `cd frontend && npm run test:unit` → tudo passa, com os 7 novos.

## Critérios de conclusão

Todos devem valer:

- [ ] `frontend/src/features/operate/aoVivo.ts` existe, com a função pura e o docstring citando `tagsOnline.ts`
- [ ] `frontend/src/features/operate/aoVivo.check.ts` cobre os 4 valores do union **e** os 3 de `rotuloConexao`, passando
- [ ] O RED do Passo 1 foi reproduzido e revertido (registrado no relato)
- [ ] `OperatePage`, `FaceplateVariavel`, `FaceplatePrincipal`, `LoopOperatePage`, `FuzzyOperatePage` consomem o gate
- [ ] A botoeira de modo de `LoopOperatePage` fica desabilitada com canal fora
- [ ] O aviso de conexão usa `ROTULO_CONEXAO` existente, com `data-testid="operate-aviso-conexao"`
- [ ] `git diff -- frontend/src/app/CanalAoVivo.tsx` é vazio **ou** contém só `export` no tipo
- [ ] `git diff -- frontend/src/features/tags/tagsOnline.ts` → **vazio**
- [ ] `git diff -- frontend/src/features/operate/TrendOperacao.tsx` → **vazio**
- [ ] `cd frontend && npm run typecheck` → exit 0
- [ ] `cd frontend && npm run test:unit` → tudo passa
- [ ] `cd frontend && npm run build` → exit 0
- [ ] `grep -l xyflow frontend/dist/assets/index-*.js` → nenhuma saída
- [ ] O relato contém os 4 registros do Passo 4
- [ ] Linha de status atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

Pare e relate (não improvise) se:

- Os excertos de "Estado atual" não baterem com o código vivo (drift desde `37b0caa`).
- Você concluir que a correção exige **limpar os Maps** de `CanalAoVivo` na queda: **não faça**.
  `CanalAoVivo.tsx:708-711` documenta que isso quebraria `resolverAlarmes` e seria "PIOR". Relate.
- Exportar `EstadoConexaoCanal` quebrar o build (circularidade de import entre `app/` e
  `features/operate/`): relate; a saída pode ser mover o tipo para um módulo neutro, e isso é
  decisão de estrutura que não cabe aqui.
- `FaceplatePrincipal.tsx` não ter um caminho de "sem confirmação" reutilizável para as lâmpadas, e
  a única saída for uma cor nova: relate as cores existentes em vez de inventar. Isso toca o
  `DESIGN.md`, que é normativo.
- Você concluir que precisa **alterar a assinatura de `podeComandar`** para encaixar o gate: não
  altere. O gate é no call site (Passo 3). Relate se o call site não aceitar a mudança.
- Algum teste existente precisar mudar.
- Você se pegar editando `TrendOperacao.tsx`, `tagsOnline.ts` ou `AppShell.tsx`: **pare**, são fora
  de escopo.

## Notas de manutenção

- **O que interage com isto**: qualquer superfície nova que leia os Maps de `CanalAoVivo`. A regra
  passa a ser: ler `mpcStates`/`loopStates`/`fuzzyStates`/`tagValues` sem passar por `canalAoVivo` é
  bug. Vale uma linha no `CLAUDE.md` se o dono concordar — mas **não edite o `CLAUDE.md` neste
  plano**; proponha no relato.
- **O que um revisor deve olhar no PR**: (1) `git diff -- frontend/src/app/CanalAoVivo.tsx` tem no
  máximo um `export`; (2) nenhuma tela passou a esconder **configuração** (lista de variáveis,
  rótulos, limites) — só **valor apresentado como corrente**; (3) a botoeira de malha desabilita com
  canal fora; (4) o aviso reusa os textos de `ROTULO_CONEXAO` via estreitamento local em
  `aoVivo.ts`, sem texto novo e **sem renomear nenhum dos dois unions**; (5) `tagsOnline.ts` intocado.
- **Decisão de apresentação que este plano fixa, e por quê**: travessão sem EU + aviso de conexão,
  porque `tagsOnline.ts:29-31` e `:43` já resolveram as duas perguntas (travessão não carrega EU;
  severidade vai ao lado do valor). Uma segunda convenção aqui seria o defeito, não a solução.
- **Adiado de propósito**:
  - `TrendOperacao.tsx:583` — mesmo achado, arquivo de alto risco de revisão. Plano próprio.
  - `AnnunciatorBar.tsx:78` destructure só `{ eventos, flowStatus, mpcStates }` e nunca olha
    `estado`: o banner global de alarmes também não sabe que o canal caiu. É a versão app-wide deste
    achado, e toca `AppShell.tsx` (plano 012). Fica para depois dos dois, para não conflitar.
  - `REACT-02` (`useLoopSurface` com `staleTime: Infinity` em `useLoops.ts:27-41`) e `REACT-03`
    (`useAssinatura` lê o interesse uma vez no mount, `CanalAoVivo.tsx:~975`) são achados reais e
    separados deste; estão no índice como vetados sem plano.
- **Verificação em browser que o revisor deve fazer** (runbook no plano 009): com a tela
  `/operacao/:flowId/:blockId` aberta, derrubar o container `api` (ou bloquear `/ws`) e confirmar
  que (a) o aviso aparece, (b) os valores viram travessão, (c) as lâmpadas saem do verde, (d) ao
  religar, tudo volta sem reload da página.
