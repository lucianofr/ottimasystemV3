# Plan 006: O registro de Bloco para de arrastar o React Flow para o chunk inicial, sem perder a garantia de completude do ARCH-18

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de
> verificação e confirme o resultado esperado antes de passar ao próximo passo. Se qualquer
> condição da seção "Condições de PARADA" ocorrer, pare e relate — não improvise. Ao
> terminar, atualize a linha de status deste plano em `docs/reports/advisor/README.md`.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 5c6d231..HEAD -- frontend/src/features/flows/registro.ts frontend/src/features/flows/nodes/index.tsx frontend/src/features/flows/registro.check.ts frontend/src/app/router.tsx`
> Se algum arquivo em escopo mudou desde que este plano foi escrito, compare os excertos de
> "Estado atual" com o código vivo antes de prosseguir; divergência é condição de PARADA.
> **Atenção: `registro.ts` e `nodes/index.tsx` são código NOVO** (ARCH-18/TD-021, aterrissado
> em 2026-08-16) e estão em área que o dono acabou de mexer.

## Status

- **Prioridade**: P1
- **Esforço**: M
- **Risco**: MED
- **Depende de**: nenhum (mas só faz sentido com o plano 005 já mesclado, o que é o caso)
- **Categoria**: perf
- **Planejado em**: commit `5c6d231`, 2026-08-16 (as medições de bundle abaixo são de
  `ab10746`, seu pai imediato; o commit intermediário só tocou um teste Python)

## Por que isso importa

O plano 005 tirou o editor de canvas do chunk inicial com `React.lazy`, e isso funcionou:
medido em `improve` antes do ARCH-18 aterrissar, o chunk principal caiu de **775,38 kB para
505,52 kB** (−269,86 kB, −34,8%) e o `@xyflow/react` passou a viver só no chunk do editor.

O ARCH-18 (registro único de tipo de Bloco, TD-021) desfez isso — e desfez em silêncio, com
build verde, typecheck limpo e nenhum teste falhando. Medição na `main` já mesclada
(`ab10746`):

| Estado | chunk inicial | chunk do editor | `xyflow` em |
|---|---|---|---|
| `main` @ `9e71b89` (antes do 005) | `index-WdBv0nrU.js` 774,22 kB | — | `index` |
| `main` @ `ab10746` (com o 005) | `index-BcPGUG4Z.js` **708,80 kB** | `FlowEditorPage-B2DGhlzl.js` 67,98 kB | **`index`** |
| `improve` @ `984ba64` (005 sem ARCH-18) | `index-C-ePFuwf.js` 505,52 kB | `FlowEditorPage-CaUlad6z.js` 270,90 kB | chunk do editor |

O fatiamento continua existindo, mas ficou oco: o chunk do editor encolheu de 270,90 para
67,98 kB porque as ~203 kB do React Flow migraram para o inicial. O 005 entrega hoje
**−65,42 kB (−8,45%)** em vez de −269,86 kB (−34,8%) — perdeu 75% do valor.

Quem paga é o operador: `/operacao`, `/operacao/:flowId/:blockId`, `/operacao/fuzzy` e
`/eventos` nunca renderizam um `<ReactFlow>`, e voltaram a baixar, parsear e compilar a
biblioteca inteira na partida, em painel de planta.

**Isto não é um argumento contra o ARCH-18.** A garantia que ele comprou é real e tem de ser
preservada: `Record<TipoBloco, DefinicaoBloco>` faz **o build quebrar** quando um tipo novo
esquece uma entrada, em vez de a falta aparecer em runtime/E2E. O que este plano faz é
separar os DADOS do registro (rótulo, descrição, defaults) dos COMPONENTES de nó, mantendo as
duas metades com completude verificada pelo compilador.

## Estado atual

### A cadeia que traz o React Flow para o chunk inicial

Todo hop é import de **valor** (o bundler não pode apagar nenhum), e o primeiro está numa rota
que todo usuário autenticado carrega:

```
frontend/src/app/CanalAoVivo.tsx:29
  import { deGraphJson } from "../features/flows/graph";
frontend/src/features/flows/graph.ts:25
  import { PADRAO_FIRST_ORDER, PADRAO_KALMAN, PADRAO_PID, REGISTRO_BLOCO, ROTULO_BLOCO } from "./registro";
frontend/src/features/flows/registro.ts:18-27
  import { NoEscritaOpc, NoFiltroKalman, NoFiltroPrimeiraOrdem, NoFuzzy, NoLeituraOpc,
           NoMpc, NoPid, NoScriptPython, NoTfsMatriz } from "./nodes";
frontend/src/features/flows/nodes/index.tsx:24
  import { BlocoChapa, LinhaResumo, type Porta } from "./BlocoChapa";
frontend/src/features/flows/nodes/BlocoChapa.tsx:1
  import { Handle, Position } from "@xyflow/react";
```

`CanalAoVivo` é o provedor do canal ao vivo — está em toda rota autenticada. Portanto
`graph.ts` mora permanentemente no chunk inicial, e hoje arrasta `registro.ts` → `nodes` →
`BlocoChapa` → `@xyflow/react` consigo. Os componentes de nó ficam **retidos** num `Record`
exportado, então tree-shaking não os resgata.

### `registro.ts` — o elo a cortar

```ts
// linha 1
import type { NodeTypes } from "@xyflow/react";
// linhas 18-27 — ESTE é o import de valor a remover
import {
  NoEscritaOpc, NoFiltroKalman, NoFiltroPrimeiraOrdem, NoFuzzy, NoLeituraOpc,
  NoMpc, NoPid, NoScriptPython, NoTfsMatriz,
} from "./nodes";

// linha 64
type ComponenteNo = NodeTypes[string];

// linhas 66-76
export interface DefinicaoBloco {
  rotulo: string;
  descricao: string;
  /** Função, não objeto: `tfs`/`script`/`fuzzy`/`mpc` embutem array/objeto mutável ... */
  defaults: () => ConfigDoBloco;
  Node: ComponenteNo;          // <- o campo que obriga o registro a conhecer os componentes
}

// linha 100 — 9 entradas, cada uma com rotulo/descricao/defaults/Node
export const REGISTRO_BLOCO: Record<TipoBloco, DefinicaoBloco> = { ... };

// linha 167
const TIPOS_DO_REGISTRO = Object.keys(REGISTRO_BLOCO) as TipoBloco[];

// linhas 171-173
export const ROTULO_BLOCO: Record<TipoBloco, string> = Object.fromEntries(
  TIPOS_DO_REGISTRO.map((tipo) => [tipo, REGISTRO_BLOCO[tipo].rotulo]),
) as Record<TipoBloco, string>;

// linhas 175-180 — mapa de COMPONENTES derivado, precisa mudar de casa
/** Referência estável: `nodeTypes` novo a cada render faz o React Flow remontar os nós. */
export const TIPOS_DE_NO: NodeTypes = Object.fromEntries(
  TIPOS_DO_REGISTRO.map((tipo) => [tipo, REGISTRO_BLOCO[tipo].Node]),
);
```

### `nodes/index.tsx` — onde os componentes moram

Define os 9 componentes de nó (`NoLeituraOpc`, `NoEscritaOpc`, …) e, na linha 319, só
reexporta o mapa:

```tsx
/** ARCH-18/TD-021: mapa derivado de `REGISTRO_BLOCO` (`registro.ts`), não mantido aqui à
 *  parte — reexportado para `FlowEditorPage.tsx` continuar importando `TIPOS_DE_NO` de
 *  `"./nodes"` sem mudança. */
export { TIPOS_DE_NO } from "../registro";
```

### Consumidores do registro (confirme com grep antes de mudar)

- `graph.ts:25` — usa `PADRAO_*`, `REGISTRO_BLOCO[tipo].defaults()` (linha 652) e
  `ROTULO_BLOCO`. **Só dados.** Nunca `.Node`.
- `FlowPalette.tsx:4,34` — usa `REGISTRO_BLOCO[tipo].descricao`. **Só dados.**
- `registro.check.ts:4` — importa `REGISTRO_BLOCO`, `ROTULO_BLOCO`, `TIPOS_DE_NO`; a linha 21
  assere `expect(typeof definicao.Node).toBe("function")` e a linha 39 assere que
  `TIPOS_DE_NO` tem exatamente uma entrada por tipo.
- `FlowEditorPage.tsx` — importa `TIPOS_DE_NO` de `"./nodes"`. **É o único consumidor de
  produção dos componentes**, e é a rota já `lazy` (plano 005).

### Convenções do repositório que se aplicam aqui

- **TypeScript strict**; comentários e strings de UI em pt-BR, identificadores em inglês
  (`CLAUDE.md:68-69`). **Sem emoji**.
- O `build` é `tsc --noEmit -p tsconfig.build.json && vite build`; erro de tipo derruba antes
  do bundle. `npm run typecheck` (`tsconfig.json`) cobre também os `*.check.ts`.
- Os `*.check.ts` rodam em **Node puro** via `playwright.unit.config.ts`. Hoje
  `registro.check.ts` já alcança `nodes/index.tsx` e o `@xyflow/react` por meio de
  `registro.ts`, e a suíte passa (633) — então importar `./nodes` de um `.check.ts`
  **não** é um problema novo. Só o grafo do BUNDLE precisa mudar.
- Exemplar de módulo separado por causa de fronteira de carregamento:
  `frontend/src/features/trend/zoomX.ts:1-6` documenta exatamente esse tipo de decisão.

### Invariantes que este plano NÃO pode violar

- **A garantia do ARCH-18/TD-021 fica de pé, nas DUAS metades.** Depois da divisão, esquecer
  um tipo no mapa de dados OU no mapa de componentes tem de continuar quebrando o **build**,
  não aparecer em runtime. Isso significa que o mapa de componentes também é
  `Record<TipoBloco, …>`, nunca `NodeTypes` (que é index signature solta — foi justamente o
  problema que o ARCH-18 corrigiu, ver `registro.check.ts:8-9`).
- **Referência estável do mapa de nós**: `nodeTypes` novo a cada render faz o React Flow
  remontar todos os nós (comentário de `registro.ts:175-177`). O mapa continua sendo uma
  const de módulo, nunca criada dentro de componente.
- **ADR-005**: o frontend não executa lógica de flow. Isto é só organização de módulos.
- Não troque `@xyflow/react` por outra biblioteca; a stack é fechada (`CLAUDE.md:157`).
- Não mexa em `vite.config.ts`: **nada de `manualChunks`**, nada de silenciar o aviso de
  chunk. A correção é no grafo de imports, não na configuração do bundler.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Dependências | `cd frontend && npm install` | exit 0 |
| Typecheck (cobre `*.check.ts`) | `cd frontend && npm run typecheck` | exit 0, sem erro |
| Build | `cd frontend && npm run build` | exit 0 |
| **A prova deste plano** | `cd frontend && grep -l xyflow dist/assets/*.js` | **só** um `FlowEditorPage-*.js` |
| Checks unitários | `cd frontend && npm run test:unit` | **633 passed**, sem regressão |
| Contrato gerado (gate do CI) | `cd frontend && npm run generate:contracts && git diff --exit-code -- src/lib/contracts.gen.ts` | sem diff |

`npm run e2e` e qualquer coisa que exija a stack de 9 serviços **não** é executável sem
`deploy/.env`; se o stack do dono estiver no ar, rodar Playwright bate no bundle DELE e dá
verde falso. Reporte como não executado.

## Escopo

**Em escopo** (os únicos arquivos que você deve modificar):
- `frontend/src/features/flows/registro.ts`
- `frontend/src/features/flows/nodes/index.tsx`
- `frontend/src/features/flows/registro.check.ts`

**Fora de escopo** (NÃO toque):
- `frontend/src/app/router.tsx` — o `lazy`/`Suspense` do plano 005 está correto e é
  pré-requisito deste; não mexa.
- `frontend/src/app/CanalAoVivo.tsx` — **não** tente resolver isto tornando `deGraphJson`
  lazy ou movendo o parse. `graph.ts` no chunk inicial é legítimo: é a leitura tolerante do
  `graph_json`, usada pelo canal ao vivo. O elo errado é `registro → nodes`, não este.
- `frontend/src/features/flows/graph.ts` e `FlowPalette.tsx` — só consomem dados; se a
  divisão estiver certa, nenhum dos dois precisa de uma linha de mudança. Se você achar que
  precisa, **pare e relate**: é sinal de que o corte foi no lugar errado.
- `frontend/src/features/flows/nodes/BlocoChapa.tsx` e os componentes de nó individuais.
- `frontend/vite.config.ts`.

## Fluxo de git

- Commite na branch do worktree em que você está (não crie branch nova, não faça push, não
  abra PR).
- **Conventional Commits com mensagem em pt-BR** (`CLAUDE.md:70`). Sugestão:
  `perf(frontend): registro de bloco deixa de arrastar o React Flow para o chunk inicial`
  Inclua no corpo os dois tamanhos de chunk (antes e depois).

## Passos

### Passo 1: medir a linha de base

```
cd frontend && npm run build && grep -l xyflow dist/assets/*.js
```

**Verifique**: anote o tamanho do `index-*.js` (esperado ~708,80 kB) e confirme que o
`grep -l` lista **o `index-*.js`** — é o defeito que você vai corrigir. Se ele já listar
apenas um `FlowEditorPage-*.js`, o defeito não existe mais: **pare e relate**.

### Passo 2: o mapa de componentes muda de casa, com completude preservada

Em `frontend/src/features/flows/nodes/index.tsx`, substitua o reexport da linha 319 por uma
definição local do mapa, tipada `Record<TipoBloco, ComponenteNo>` (importe `TipoBloco` de
`../graph` como **`import type`**, e derive `ComponenteNo` de `NodeTypes[string]` também por
`import type`, como `registro.ts` já fazia). As 9 entradas são explícitas, apontando para os
componentes definidos neste próprio arquivo.

Mantenha o comentário registrando as duas razões da forma escolhida: (a) `Record<TipoBloco,
…>` e não `NodeTypes`, para a falta de um tipo quebrar o build (a garantia do ARCH-18); e
(b) const de módulo, para a referência ser estável e o React Flow não remontar os nós.

Acrescente também uma linha dizendo por que o mapa mora AQUI e não em `registro.ts`: o
registro é alcançado pelo chunk inicial via `graph.ts`, e tocar os componentes de lá arrasta
o `@xyflow/react` para dentro dele.

**Verifique**: `cd frontend && npm run typecheck` → exit 0.

### Passo 3: cortar o elo em `registro.ts`

1. Remova o import de valor das linhas 18-27 (`from "./nodes"`).
2. Remova o campo `Node: ComponenteNo` de `DefinicaoBloco` (linha 75) e a linha `Node: …` das
   9 entradas de `REGISTRO_BLOCO`.
3. Remova `export const TIPOS_DE_NO` (linhas 178-180).
4. Remova `type ComponenteNo` (linha 64) e o `import type { NodeTypes }` (linha 1), que ficam
   sem uso. **Depois disto, `registro.ts` não pode ter nenhuma referência a `@xyflow/react`
   nem a `./nodes`** — nem de tipo, para não deixar a porta entreaberta.

`ROTULO_BLOCO` e `TIPOS_DO_REGISTRO` continuam como estão.

**Verifique**:
`grep -n 'xyflow\|"./nodes"' frontend/src/features/flows/registro.ts` → **nada**.
`cd frontend && npm run typecheck` → exit 0.

### Passo 4: ajustar o check

Em `frontend/src/features/flows/registro.check.ts`:
1. Importe `TIPOS_DE_NO` de `"./nodes"` em vez de `"./registro"`.
2. Remova `expect(typeof definicao.Node).toBe("function")` (linha 21) — o campo não existe
   mais. Ajuste o nome do teste, que hoje diz "rótulo, descrição, defaults e Node
   preenchidos".
3. **Mantenha intacto** o teste da linha 37 ("ROTULO_BLOCO e TIPOS_DE_NO têm exatamente uma
   entrada por tipo"): ele é a rede que prova a completude das duas metades em runtime, e
   agora vale mais do que antes, porque os dois mapas passaram a ser mantidos em arquivos
   diferentes.

**Verifique**: `cd frontend && npm run test:unit` → **633 passed**, sem regressão.

### Passo 5: a prova

```
cd frontend && npm run build && grep -l xyflow dist/assets/*.js
```

**Verifique**: o `grep -l` lista **apenas** um `FlowEditorPage-*.js`, nunca o `index-*.js`; e
o `index-*.js` caiu de ~708,80 kB para a ordem de ~505 kB. Reporte os dois números.

## Plano de teste

Nenhum teste novo de comportamento: a mudança é de organização de módulos, e o
comportamento observável (paleta, criação de bloco, render do canvas) é o mesmo.

O que substitui o teste novo, e é mais forte aqui:

1. **A prova mecânica no artefato de build** (Passo 5): `grep -l xyflow` no `dist/`. É o único
   check que pega esta classe de regressão — nem typecheck nem `test:unit` pegam, e foi
   exatamente por isso que o ARCH-18 a introduziu em silêncio.
2. **`registro.check.ts:37`, preservado**: prova que os dois mapas têm uma entrada por tipo,
   agora atravessando dois arquivos.
3. **A garantia de build do ARCH-18, verificada à mão uma vez**: comente temporariamente uma
   entrada do mapa de componentes do Passo 2, rode `npm run typecheck` e confirme que ele
   **FALHA** por chave faltando em `Record<TipoBloco, …>`; então reverta. Sem isso não há como
   saber se a divisão preservou a garantia ou a esvaziou — é o mesmo raciocínio do RED de um
   teste. Não deixe o comentário no commit.

## Critérios de conclusão

Verificáveis por máquina. TODOS têm de valer:

- [ ] `cd frontend && npm run typecheck` sai 0 sem erro
- [ ] `cd frontend && npm run build` sai 0
- [ ] `cd frontend && grep -l xyflow dist/assets/*.js` lista **apenas** um `FlowEditorPage-*.js`
- [ ] `index-*.js` na ordem de ~505 kB (reporte o número exato, antes e depois)
- [ ] `grep -n 'xyflow\|"./nodes"' frontend/src/features/flows/registro.ts` → nada
- [ ] `cd frontend && npm run test:unit` → **633 passed**, sem regressão
- [ ] `cd frontend && npm run generate:contracts && git diff --exit-code -- src/lib/contracts.gen.ts` → sem diff
- [ ] `grep -n 'manualChunks\|chunkSizeWarningLimit' frontend/vite.config.ts` → nada
- [ ] O item 3 do plano de teste foi executado e revertido
- [ ] `git status --porcelain` não lista arquivo fora da lista "Em escopo"
- [ ] Linha de status deste plano atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

Pare e relate (não improvise) se:

- Os excertos de "Estado atual" não corresponderem ao código vivo — `registro.ts` e
  `nodes/index.tsx` são código de 2026-08-16 e o dono trabalha nessa área.
- O Passo 1 mostrar que o `grep -l xyflow` já lista apenas o chunk do editor (defeito já
  resolvido por outro caminho).
- `graph.ts` ou `FlowPalette.tsx` precisarem de mudança: significa que o corte foi no lugar
  errado, porque os dois só consomem dados.
- Depois do Passo 5 o `index-*.js` **não** cair, ou o `grep -l` continuar listando-o. Nesse
  caso existe um segundo caminho de import trazendo o `@xyflow/react` para o chunk inicial —
  encontre-o e relate, **não** parta para `manualChunks`.
- O item 3 do plano de teste mostrar que a falta de uma entrada **não** quebra o typecheck: a
  garantia do ARCH-18 foi perdida, e a divisão precisa de outra forma.

## Notas de manutenção

- **O que um revisor deve escrutinar**: que `registro.ts` não tem nenhuma referência a
  `@xyflow/react` ou `./nodes`, nem de tipo; que o mapa de componentes é
  `Record<TipoBloco, …>` e não `NodeTypes`; e os dois números de chunk no commit.
- **Esta regressão não tem gate.** O CI de `ADR-035` (`.github/workflows/gates.yml`) roda
  ruff, `test:unit`, typecheck, build e a checagem de contrato gerado — **nenhum deles pega
  `xyflow` voltando ao chunk inicial**. Depois deste plano, o lugar certo de travar é um passo
  novo no `gates.yml` que falhe quando `dist/assets/index-*.js` contiver `xyflow`. Vale fazer
  agora, e não esperar a segunda recaída: esta já é a segunda vez que o assunto aparece (a
  primeira foi o próprio ARCH-18 desfazendo o plano 005 em silêncio).
- **Interação futura**: qualquer módulo alcançado pelo chunk inicial que passe a importar
  `./nodes`, `BlocoChapa` ou `@xyflow/react` como valor reabre o problema. O ponto de entrada
  a vigiar é `CanalAoVivo.tsx` → `graph.ts`, porque é o que garante presença em toda rota.
