# Plan 005: A tela de operação para de baixar o editor de canvas que ela nunca abre

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de
> verificação e confirme o resultado esperado antes de passar ao próximo passo. Se
> qualquer condição da seção "Condições de PARADA" ocorrer, pare e relate — não
> improvise. Ao terminar, atualize a linha de status deste plano em
> `docs/reports/advisor/README.md`.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat 8f9fe76..HEAD -- frontend/src/app/router.tsx frontend/src/features/flows/FlowEditorPage.tsx frontend/package.json`
> Se algum arquivo em escopo mudou desde que este plano foi escrito, compare os excertos
> de "Estado atual" com o código vivo antes de prosseguir; divergência é condição de PARADA.

## Status

- **Prioridade**: P2
- **Esforço**: S
- **Risco**: LOW
- **Depende de**: nenhum
- **Categoria**: perf
- **Planejado em**: commit `8f9fe76`, 2026-08-16

## Por que isso importa

`frontend/src/app/router.tsx` importa as 15 páginas do sistema estaticamente, no topo do
módulo. Não há `React.lazy` nem `import()` em nenhuma rota, então tudo entra no mesmo
chunk inicial — e o `npm run build` já avisa que ele passou de 500 kB (está em ~775 kB).

`@xyflow/react` (React Flow) é usado **exclusivamente** pela árvore do editor de flow, a
rota `/engenharia/flows/:flowId`. Medido nos arquivos reais de `node_modules`:
`@xyflow/react/dist/umd/index.js` = 183,0 KB e a dependência direta
`@xyflow/system/dist/esm/index.mjs` = 148,3 KB — antes de contar `zustand` e `classcat`.
É o único pacote grande com uso restrito a uma rota: `@tanstack/react-query`,
`react-router` e `uplot` são usados por praticamente toda tela e não rendem fatiamento.

Quem paga: o operador. A HMI de operação (`/operacao`, `/operacao/:flowId/:blockId`,
`/operacao/fuzzy`, `/eventos`) nunca renderiza um `<ReactFlow>`, mas baixa, parseia e
compila esse código em todo carregamento inicial. Num painel de planta com hardware
modesto isso é tempo de partida gasto em código morto.

Depois deste plano: o editor de canvas vira um chunk próprio, buscado só quando o
engenheiro abre a rota do editor.

## Estado atual

Arquivos e papéis:

- `frontend/src/app/router.tsx` (53 linhas) — todas as rotas do sistema. É o arquivo a
  mudar.
- `frontend/src/features/flows/FlowEditorPage.tsx` (~795 linhas) — a página do editor de
  canvas. Exporta `FlowEditorPage` como **export nomeado**, não default. Isso importa para
  o `React.lazy`.
- `frontend/src/features/flows/nodes/` e `frontend/src/features/flows/graph.ts` — o resto
  da árvore que importa `@xyflow/react`.
- `frontend/src/app/AppShell.tsx` e `frontend/src/app/AuthGuard.tsx` — os layouts que
  envolvem as rotas autenticadas.

### `frontend/src/app/router.tsx` (arquivo completo)

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { LoginPage } from "../features/auth/LoginPage";
import { AuthProvider } from "../features/auth/useAuth";
import { ConnectionsPage } from "../features/connections/ConnectionsPage";
import { EventsPage } from "../features/events/EventsPage";
import { FlowEditorPage } from "../features/flows/FlowEditorPage";
import { FlowsPage } from "../features/flows/FlowsPage";
import { FuzzyOperatePage } from "../features/fuzzy/FuzzyOperatePage";
import { OperatePage } from "../features/operate/OperatePage";
import { OperateSelectorPage } from "../features/operate/OperateSelectorPage";
import { ProjectsPage } from "../features/projects/ProjectsPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { TagsPage } from "../features/tags/TagsPage";
import { TrendPage } from "../features/trend/TrendPage";
import { AppShell } from "./AppShell";
import { AuthGuard } from "./AuthGuard";
import { HomePage } from "./HomePage";

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<AuthGuard />}>
              <Route element={<AppShell />}>
                <Route path="/" element={<HomePage />} />
                <Route path="/operacao" element={<OperateSelectorPage />} />
                <Route path="/operacao/:flowId/:blockId" element={<OperatePage />} />
                <Route path="/operacao/fuzzy" element={<FuzzyOperatePage />} />
                <Route path="/eventos" element={<EventsPage />} />
                <Route path="/engenharia/projetos" element={<ProjectsPage />} />
                <Route path="/engenharia/conexoes" element={<ConnectionsPage />} />
                <Route path="/engenharia/tags" element={<TagsPage />} />
                <Route path="/engenharia/flows" element={<FlowsPage />} />
                <Route path="/engenharia/flows/:flowId" element={<FlowEditorPage />} />
                <Route path="/engenharia/trend" element={<TrendPage />} />
                <Route path="/configuracoes" element={<SettingsPage />} />
              </Route>
              {/* dentro do guarda: rota desconhecida sem sessão vai direto a /login */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
```

### Onde `@xyflow/react` é importado (confirme antes de mudar)

Rode `grep -rn "@xyflow/react" frontend/src` e confirme que TODAS as ocorrências estão
sob `frontend/src/features/flows/`. Os pontos conhecidos:
`features/flows/FlowEditorPage.tsx`, `features/flows/graph.ts:1` (só `import type`, que o
bundler apaga), `features/flows/nodes/BlocoChapa.tsx:1`, `features/flows/nodes/index.tsx:1`.

**Atenção ao `FlowsPage`**: é a LISTA de flows (`/engenharia/flows`), não o editor. Se ela
não importar `@xyflow/react` nem `nodes/` em runtime, deixe-a estática — o ganho vem do
editor. Confirme com
`grep -n "xyflow\|./nodes\|./graph" frontend/src/features/flows/FlowsPage.tsx`.

### Convenções do repositório que se aplicam aqui

- **TypeScript strict**. Comentários e strings de UI em pt-BR, identificadores em inglês
  (`CLAUDE.md:68-69`). **Sem emoji**.
- O `build` é `tsc --noEmit -p tsconfig.build.json && vite build`
  (`frontend/package.json:8`) — erro de tipo derruba o build antes do bundle.
- Componentes shadcn/ui já disponíveis em `frontend/src/components/ui/` para o fallback.

### Invariantes que este plano NÃO pode violar

- **ADR-005**: o frontend nunca executa lógica de flow. Isto é só o momento do download.
- Nenhuma mudança de comportamento observável: as mesmas rotas, os mesmos `data-testid`, a
  mesma navegação. Os `data-testid` são contrato dos roteiros L3 e das specs do Playwright
  (`CLAUDE.md:141`) — não renomeie nada.
- Não troque `@xyflow/react` por outra biblioteca: a stack é fechada (`CLAUDE.md:157`).

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Dependências | `cd frontend && npm install` | exit 0 |
| Typecheck | `cd frontend && npm run typecheck` | exit 0, sem erro |
| Build (imprime os tamanhos de chunk) | `cd frontend && npm run build` | exit 0; ver "Critérios" |
| Checks unitários | `cd frontend && npm run test:unit` | todos passam (baseline `8f9fe76`: 596 passed) |
| Playwright do editor | `cd frontend && npx playwright test flows-editor.spec.ts` | todos passam |
| Playwright completo | `cd frontend && npm run e2e` | todos passam |

Playwright exige `E2E_ADMIN_USERNAME`/`E2E_ADMIN_PASSWORD` **inline**
(`env VAR=... comando`), nunca exportados no shell (`CLAUDE.md:147-149`).

**Antes de mudar qualquer coisa, rode `npm run build` e ANOTE os tamanhos de chunk.** Eles
são a linha de base contra a qual o ganho vai ser medido; sem isso não há como provar que o
plano funcionou.

## Escopo

**Em escopo** (os únicos arquivos que você deve modificar):
- `frontend/src/app/router.tsx`
- `frontend/src/app/AppShell.tsx` — **somente se** o `<Suspense>` ficar melhor ali,
  envolvendo o `<Outlet />`. Prefira `router.tsx` se der.

**Fora de escopo** (NÃO toque):
- `frontend/src/features/flows/FlowEditorPage.tsx` — não mude a página, não troque o export
  nomeado por default só para simplificar o `lazy`. O adaptador de duas linhas no
  `React.lazy` resolve, e trocar a forma do export obrigaria a mexer em quem mais a importa.
- `frontend/vite.config.ts` — **não** configure `manualChunks`. Deixe o Vite particionar a
  partir do `import()` dinâmico; `manualChunks` é afinação que só se justifica com medição
  posterior, e mal usada piora o resultado.
- `frontend/src/features/flows/nodes/`, `graph.ts`, `mpc/` — não precisam mudar; entram no
  chunk do editor por consequência do grafo de import.
- Qualquer outra rota. Este plano divide UMA rota, a que tem o pacote grande com uso
  restrito. Fatiar as demais é otimização sem evidência.
- O aviso de `chunk > 500 kB` do Vite: **não** o silencie com
  `build.chunkSizeWarningLimit`. O objetivo é ficar abaixo dele, não calá-lo.

## Fluxo de git

- Branch: você já está em `improve`; commite nela (não faça push, não abra PR).
- **Conventional Commits com mensagem em pt-BR** (`CLAUDE.md:70`). Para este plano:
  `perf(frontend): editor de flow sai do bundle inicial e vira chunk sob demanda`

## Passos

### Passo 1: medir a linha de base

```
cd frontend && npm run build
```

Anote, do output do Vite: o nome e o tamanho do chunk JS principal (em `8f9fe76` é
`index-*.js`, ~775 kB) e a lista completa de chunks gerados. Guarde — os "Critérios de
conclusão" comparam contra estes números.

**Verifique**: build sai 0 e você tem os números anotados.

### Passo 2: confirmar que o pacote grande está restrito ao editor

```
grep -rn "@xyflow/react" frontend/src
grep -n "xyflow\|./nodes\|./graph" frontend/src/features/flows/FlowsPage.tsx
```

**Verifique**: todas as ocorrências de `@xyflow/react` sob `features/flows/`, e
`FlowsPage.tsx` sem nenhuma (ou apenas `import type`, que não gera código).

Se `FlowsPage.tsx` importar `@xyflow/react` em runtime, o plano ainda vale, mas você terá
de fatiar as duas rotas juntas — relate antes de seguir.

### Passo 3: tornar a rota do editor preguiçosa

Em `router.tsx`:

1. Remova o import estático de `FlowEditorPage` (linha 8).
2. Importe `lazy` e `Suspense` de `react` e declare o componente preguiçoso, com o
   adaptador para export nomeado:

```tsx
// O editor de canvas é a única rota que carrega @xyflow/react (~183 kB + ~148 kB de
// @xyflow/system). Fatiado para que a HMI de operação, que nunca renderiza <ReactFlow>,
// não pague o download e o parse desse código na partida.
const FlowEditorPage = lazy(() =>
  import("../features/flows/FlowEditorPage").then((m) => ({ default: m.FlowEditorPage })),
);
```

3. Envolva a região das rotas com `<Suspense>` e um fallback discreto. O lugar mais simples
   é dentro do `<Route element={<AppShell />}>`, envolvendo as rotas filhas; se a estrutura
   do `AppShell` não permitir (ele provavelmente renderiza um `<Outlet />`), ponha o
   `<Suspense>` em volta do `<Outlet />` dentro do `AppShell.tsx` — é o lugar canônico e
   mantém o shell de navegação visível enquanto o chunk carrega.

O fallback tem de ser em **pt-BR** e discreto: esta é uma HMI, e um spinner de tela cheia
piscando entre rotas é pior que um texto pequeno. Reuse um componente de
`frontend/src/components/ui/` se houver um adequado.

**Verifique**: `cd frontend && npm run typecheck` → exit 0.

### Passo 4: medir o ganho

```
cd frontend && npm run build
grep -l "xyflow" frontend/dist/assets/*.js
```

**Verifique**: comparado ao Passo 1, existe um chunk NOVO com o editor e o chunk principal
encolheu; o `grep -l` lista o chunk novo e **não** o `index-*.js`.

### Passo 5: provar que a rota ainda funciona

```
cd frontend && npx playwright test flows-editor.spec.ts
```

Depois a suíte inteira do Playwright. Ver "Plano de teste".

## Plano de teste

Nenhum teste unitário novo: a mudança é de particionamento de bundle e momento de
carregamento, não de lógica. Os checks de `*.check.ts` rodam em Node puro e não veem chunk
nenhum.

A prova é em três partes:

1. **Mecânica, no artefato de build**: o `grep -l "xyflow" frontend/dist/assets/*.js` do
   Passo 4 mostra o código no chunk novo e não no principal, e o tamanho do chunk principal
   caiu contra a linha de base do Passo 1.
2. **Regressão da rota fatiada**: `npx playwright test flows-editor.spec.ts` continua
   verde. Se a spec navegar direto para `/engenharia/flows/:flowId`, ela exercita exatamente
   o caminho novo (chunk sob demanda) e é a prova mais relevante deste plano.
3. **Regressão geral de navegação**: `npm run e2e` completo, porque o `<Suspense>` entrou
   num layout compartilhado por todas as rotas autenticadas e pode afetar o timing de
   qualquer spec que navegue.

Se alguma spec quebrar por *timing* (elemento consultado antes de o chunk chegar), a
correção certa é a spec esperar o elemento, não remover o `Suspense` — mas relate antes de
editar spec, porque tocar `frontend/e2e/` está fora do escopo declarado deste plano.

## Critérios de conclusão

Verificáveis por máquina. TODOS têm de valer:

- [ ] `cd frontend && npm run typecheck` sai 0 sem erro
- [ ] `cd frontend && npm run build` sai 0
- [ ] O chunk principal (`index-*.js`) ficou MENOR que a linha de base anotada no Passo 1
- [ ] `grep -l "xyflow" frontend/dist/assets/*.js` lista um chunk que **não** é o
      `index-*.js`
- [ ] `grep -n "from \"../features/flows/FlowEditorPage\"" frontend/src/app/router.tsx` não
      mostra import estático (só o `import()` dentro do `lazy`)
- [ ] `cd frontend && npm run test:unit` verde, sem regressão contra 596
- [ ] `cd frontend && npx playwright test flows-editor.spec.ts` verde
- [ ] `cd frontend && npm run e2e` verde
- [ ] `git status --porcelain` não lista arquivo fora da lista "Em escopo"
- [ ] Linha de status deste plano atualizada em `docs/reports/advisor/README.md`

Registre no commit os dois números: tamanho do chunk principal antes e depois. Sem eles não
há prova de ganho.

## Condições de PARADA

Pare e relate (não improvise) se:

- Os excertos de "Estado atual" não corresponderem ao código vivo.
- `FlowsPage.tsx` (a lista) importar `@xyflow/react` em runtime — o recorte muda.
- O chunk principal **não** encolher depois da mudança. Isso significaria que alguma outra
  rota alcança `@xyflow/react` por um caminho de import que o Passo 2 não achou; encontre
  esse caminho e relate, em vez de partir para `manualChunks`.
- Uma spec do Playwright quebrar e a correção parecer exigir editar `frontend/e2e/`.
- O `Suspense` causar piscada visível de layout na navegação entre rotas de operação. Isso é
  regressão de UX numa HMI e vale mais que o ganho de bundle: relate para decidir o
  posicionamento do fallback.

## Notas de manutenção

- **O que um revisor deve escrutinar**: que o fallback do `Suspense` não esconde o shell de
  navegação (o operador precisa continuar vendo onde está); e os dois números de tamanho de
  chunk no commit.
- **Interação futura**: qualquer import novo de `@xyflow/react` fora de `features/flows/`
  traz o pacote de volta ao chunk inicial e desfaz este plano em silêncio. Se isso virar
  recorrente, o lugar de travar é um teste de build que falha quando `index-*.js` contém
  `xyflow` — mas só vale a pena depois da primeira recaída.
- **Candidato adjacente, deliberadamente fora**: `uplot`, `react-query` e `react-router` são
  usados por praticamente toda rota e não rendem fatiamento. Se o chunk principal continuar
  acima de 500 kB depois deste plano, o próximo passo é medir com um visualizador de bundle
  antes de mexer em mais nada — nunca fatiar por palpite.
