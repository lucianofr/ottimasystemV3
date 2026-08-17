# Plan 002: O trend da tela de operação repinta ao alternar claro/escuro, como as outras duas telas de tendência já fazem

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de
> verificação e confirme o resultado esperado antes de passar ao próximo passo. Se
> qualquer condição da seção "Condições de PARADA" ocorrer, pare e relate — não
> improvise. Ao terminar, atualize a linha de status deste plano em
> `docs/reports/advisor/README.md`.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat ab10746..HEAD -- frontend/src/features/operate/TrendOperacao.tsx frontend/src/features/trend/TrendChart.tsx frontend/src/lib/theme.ts frontend/e2e/operate-trend.spec.ts`
> Se algum arquivo em escopo mudou desde que este plano foi escrito, compare os
> excertos de "Estado atual" com o código vivo antes de prosseguir; divergência é
> condição de PARADA. Atenção: `TrendOperacao.tsx` e `TrendChart.tsx` foram reescritos
> em `ecda585` (2026-08-15) e o `PainelLegendaTrend.tsx`/`LegendaOperacao.tsx` ao lado
> deles mudou em `c02455a` (ARCH-04, 2026-08-16) — é código recente, e o dono trabalha
> nesta área. Os excertos de "Estado atual" abaixo foram reconferidos contra `ab10746`:
> `TrendOperacao.tsx:577`/`581` e `769` batem linha a linha.

## Status

- **Prioridade**: P1
- **Esforço**: S
- **Risco**: LOW
- **Depende de**: nenhum
- **Categoria**: bug
- **Planejado em**: commit `ab10746`, 2026-08-16 (revisado; a redação original era contra
  `8f9fe76`, e o plano foi reconciliado quando a `main` avançou)

## Por que isso importa

O uPlot pinta no canvas com as cores lidas **no momento da montagem da instância**.
Trocar o tema depois disso não repinta nada: só recriar a instância repinta. As três
telas de tendência do sistema consomem o mesmo motor (`features/trend/motorTrend.ts`,
extraído em `ecda585`), mas só duas resolvem isso — `TrendPage` e `TrendFuzzy`, via
`TrendChart`. O trend da tela de **operação** lê o tema uma única vez, num
`useMemo(..., [])`, e não coloca o tema na chave de recriação da instância.

Consequência prática: um operador que abre `/operacao/:flowId/:blockId` no tema claro e
alterna para escuro (ou o contrário) continua vendo o trend com a paleta antiga —
grade, texto de eixo, divisor "agora", traço de SP e faixa de restrição todos com as
cores do tema anterior, contra o fundo novo. Numa HMI industrial, eixo e grade
ilegíveis no trend central do operador não é cosmético. Só fechar e reabrir o faceplate
do bloco corrige (o `key` no componente pai força remonte).

Isso não é decisão de design: o `TrendChart` faz o oposto e **documenta por quê**, e o
docstring de `useTema` descreve exatamente este sintoma. É omissão que o refactor do
motor deixou para trás na tela de operação.

## Estado atual

Arquivos e papéis:

- `frontend/src/features/operate/TrendOperacao.tsx` (~958 linhas) — trend da tela de
  operação, com predição do MPC, divisor Histórico|Previsão e legenda própria. Consome
  `useMotorTrend`. É o arquivo a corrigir.
- `frontend/src/features/trend/TrendChart.tsx` — trend de engenharia e fuzzy. Consome o
  mesmo `useMotorTrend` e **já faz a coisa certa**. É o exemplar a copiar.
- `frontend/src/lib/theme.ts` — `type Tema = "light" | "dark"` (linha 3) e o hook
  `useTema()` (linha 32), reativo via `useSyncExternalStore`.
- `frontend/src/features/trend/trendTheme.ts` — `interface TemaTrend` (linha 32) e
  `lerTemaTrend()` (linha 55).
- `frontend/src/components/ui/theme-toggle.tsx` — o controle que o usuário aperta
  (linha 20), presente no shell.
- `frontend/src/styles/tokens.css:121-122` — `[data-theme="dark"]` com paleta própria
  completa, alternável no `<html>`.

### O defeito, em `TrendOperacao.tsx:577-585`

```tsx
  const tema = useMemo(() => lerTemaTrend(), []);
  // Paleta PRÓPRIA do trend de operação (§6.6-5) — não `tema.penas` (6, do trend de
  // engenharia): o resto do tema (grade, eixos, mono, accent, poço) segue vindo de
  // `lerTemaTrend()`, só a cor de pena tem fonte própria de 8 posições.
  const coresPena = useMemo(() => lerCoresPenaOperacao(), []);
  const cores = useMemo(
    () => atribuirCoresPenas(idsHistorico, coresPena),
    [idsHistorico, coresPena],
  );
```

Lista de dependências vazia nos dois `useMemo`: `lerTemaTrend()` e
`lerCoresPenaOperacao()` rodam uma vez, no primeiro render. O comentário explica a
FONTE da paleta de pena (por que não é `tema.penas`), não a reatividade — não há
justificativa registrada para o tema ficar de fora.

As duas funções leem o DOM e portanto dependem do tema ativo:

- `trendTheme.ts:55-56`:
  ```ts
  export function lerTemaTrend(): TemaTrend {
    const estilo = getComputedStyle(document.documentElement);
  ```
- `TrendOperacao.tsx:162-165` (função local do próprio arquivo):
  ```tsx
  function lerCoresPenaOperacao(): readonly string[] {
    const estilo = getComputedStyle(document.documentElement);
    return TOKENS_PENA_OPERACAO.map((token) => estilo.getPropertyValue(token).trim());
  }
  ```

### A segunda metade do defeito, em `TrendOperacao.tsx:769`

```tsx
  const estrutura = `${String(janelaSegundos)}|${idsEstrutura.join(",")}|${escalaAssinatura}|${foco ?? ""}`;

  const motor = useMotorTrend({
    estrutura,
    altura: ALTURA,
    dados: colunas === null ? null : colunas.dados,
```

`estrutura` é a chave de recriação da instância uPlot dentro do motor. O tema não
entra. Portanto, mesmo que `tema` passasse a ser reativo, a instância não seria
recriada e o canvas não repintaria.

### O exemplar correto, em `TrendChart.tsx:44-47`

```tsx
  // O tema entra na estrutura: o uPlot pinta no canvas com as cores lidas na montagem, então
  // alternar claro/escuro só reflete no gráfico recriando a instância.
  const tema = useTema();
  const estrutura = `${tema}|${String(janelaSegundos)}|${idsTexto.join(",")}|${assinaturaEscalas}`;
```

Note que ali `tema` é o **identificador** (`"light" | "dark"`) usado só como parte da
chave; `TrendChart` obtém as cores chamando `lerTemaTrend()`/`construirOpcoes` dentro
do `montarOpcoes`, que o motor sempre executa com a última closure do render corrente.

### O docstring que descreve o sintoma, em `frontend/src/lib/theme.ts:31-32`

```ts
/**  Assinatura do tema para quem desenha fora do DOM (canvas do uPlot): sem isso o gráfico
 *  mantém as cores lidas na montagem depois de alternar claro/escuro. */
export function useTema(): Tema {
```

### Onde o tema é consumido dentro de `TrendOperacao.tsx`

Para conferir que a correção cobre tudo, estes são os pontos que leem `tema`/`coresPena`
(confirme com `grep -n "tema\.\|coresPena" frontend/src/features/operate/TrendOperacao.tsx`):
`tema.agora` no plugin da linha "agora" (~linha 121), `tema.texto` no traço e legenda de
SP (~271, ~277), `tema.banda` na faixa de restrição (~331), `construirOpcoesOperacao`
(~381-462), e a cor de fallback do eixo Y (~715).

### Convenções do repositório que se aplicam aqui

- **TypeScript strict**; comentários e strings de UI em pt-BR, identificadores em inglês
  (`CLAUDE.md:68-69`).
- **Sem emoji** em código ou comentário.
- Componentes shadcn/ui; estado de servidor por WebSocket/REST tipados.
- Quando você registrar por que algo entra ou sai da `estrutura`, siga o estilo de
  comentário já usado em `TrendChart.tsx:44-45` e `:49-51` — o repo documenta essas
  decisões no ponto exato.

### Invariante que este plano NÃO pode violar

- **ADR-005**: o frontend nunca executa lógica de flow. Isto é puramente apresentação.
- Não mude `features/trend/motorTrend.ts`. O motor está correto e é compartilhado pelas
  três telas; o defeito é do consumidor. Recriar por mudança de `estrutura` é justamente
  o mecanismo que o motor já oferece.
- Não mexa na fonte da paleta de pena: continua sendo `TOKENS_PENA_OPERACAO` (8
  posições), nunca `tema.penas` (6). Isso é a decisão §6.6-5 registrada no comentário da
  linha 578-580.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Dependências | `cd frontend && npm install` | exit 0 |
| Typecheck (cobre `*.check.ts`) | `cd frontend && npm run typecheck` | exit 0, nenhuma saída de erro |
| Build (tsc strict + bundle) | `cd frontend && npm run build` | exit 0 |
| Checks unitários | `cd frontend && npm run test:unit` | todos passam (baseline em `ab10746`: **633 passed**) |
| Playwright de um spec | `cd frontend && npx playwright test operate-trend.spec.ts` | todos passam |

Playwright exige `E2E_ADMIN_USERNAME`/`E2E_ADMIN_PASSWORD` exportados e um frontend
servido. Passe-os **inline** (`env VAR=... comando`), nunca por export global — exportar
`OTTIMA_DATABASE_URL` no shell quebra os testcontainers da regressão unitária
(`CLAUDE.md:147-149`).

## Escopo

**Em escopo** (os únicos arquivos que você deve modificar):
- `frontend/src/features/operate/TrendOperacao.tsx`
- `frontend/e2e/operate-trend.spec.ts` (acrescentar um cenário)

**Fora de escopo** (NÃO toque):
- `frontend/src/features/trend/motorTrend.ts` — o motor está correto.
- `frontend/src/features/trend/TrendChart.tsx` — é o exemplar, já certo.
- `frontend/src/features/trend/trendTheme.ts` e `frontend/src/lib/theme.ts` — as APIs
  que você vai consumir já existem e bastam.
- `frontend/src/features/operate/LegendaOperacao.tsx` — a legenda de operação não mostrar
  valor nem EU é o **ARCH-04**, achado já auditado e registrado no TD-024. Não é este
  plano e não deve ser corrigido de carona.
- Qualquer consolidação de duplicação entre as três telas de trend — é ARCH-02/03/04,
  já registrado. Este plano corrige um bug de reatividade, não estrutura.

## Fluxo de git

- Branch: você já está em `improve`; commite nela (não faça push, não abra PR).
- **Conventional Commits com mensagem em pt-BR** (`CLAUDE.md:70`). Exemplos reais do
  histórico deste repo, do mesmo arquivo:
  - `fix(frontend): pena de SP sai do Azul Único e assume o matiz da própria CV`
  - `fix(frontend): divisor "agora" congela junto com o eixo sob zoom manual`
  Para este plano:
  `fix(frontend): trend de operação repinta ao alternar tema claro/escuro`

## Passos

### Passo 1: tornar `tema` e `coresPena` reativos

Em `TrendOperacao.tsx`, importe `useTema` de `../../lib/theme` (confira o path relativo
correto a partir de `features/operate/`; em `TrendChart.tsx:4` o import é
`from "../../lib/theme"` a partir de `features/trend/`).

Troque as linhas 577 e 581 por uma leitura dependente do identificador do tema:

```tsx
  const temaId = useTema();
  const tema = useMemo(() => lerTemaTrend(), [temaId]);
  const coresPena = useMemo(() => lerCoresPenaOperacao(), [temaId]);
```

Preserve o comentário existente das linhas 578-580 (ele explica a fonte da paleta, e
continua verdadeiro). Acrescente uma linha curta registrando por que `temaId` é a
dependência: as duas funções leem `getComputedStyle(document.documentElement)`, então o
valor muda quando o `data-theme` do `<html>` muda.

`cores` (linha 582) já depende de `coresPena`, então recalcula em cascata sem mudança.

**Verifique**: `cd frontend && npm run typecheck` → exit 0, sem erro.

### Passo 2: colocar o tema na chave de recriação da instância

Na linha 769, acrescente `temaId` como primeiro campo da `estrutura`, exatamente no
padrão de `TrendChart.tsx:47`:

```tsx
  const estrutura = `${temaId}|${String(janelaSegundos)}|${idsEstrutura.join(",")}|${escalaAssinatura}|${foco ?? ""}`;
```

Acrescente acima dela o comentário que registra a razão (mesma decisão que
`TrendChart.tsx:44-45` documenta): o uPlot pinta no canvas com as cores lidas na
montagem, então alternar claro/escuro só reflete recriando a instância.

**Verifique**: `cd frontend && npm run build` → exit 0.

### Passo 3: conferir que nada mais lê o tema fora dessas dependências

Rode `grep -n "lerTemaTrend\|lerCoresPenaOperacao\|useTema" frontend/src/features/operate/TrendOperacao.tsx`
e confirme que as ÚNICAS chamadas de leitura são as dos dois `useMemo` do Passo 1. Se
houver uma terceira chamada solta (por exemplo dentro de `montarOpcoes` ou de um
plugin), ela agora lê o valor do render corrente por causa da closure em ref do motor —
o que é correto — mas confirme que ela não está memoizada com `[]` em outro lugar.

**Verifique**: o grep retorna apenas as chamadas esperadas; `cd frontend && npm run test:unit`
→ todos passam, sem regressão (baseline 633 passed).

### Passo 4: cenário de regressão no Playwright

Ver "Plano de teste".

**Verifique**: `cd frontend && npx playwright test operate-trend.spec.ts` → todos
passam, incluindo o cenário novo.

## Plano de teste

**Por que não teste unitário**: os checks de `*.check.ts` rodam em Node puro, sem
bundler e sem DOM/CSS — `motorTrend.ts` importa o CSS do uPlot e não é carregável ali
(está escrito no topo de `frontend/src/features/trend/zoomX.ts:1-6`). A correção é
reatividade de DOM + repintura de canvas, então a prova tem de ser de browser. É a mesma
conclusão que o repo registrou ao verificar o ARCH-01.

**Onde**: acrescente UM cenário em `frontend/e2e/operate-trend.spec.ts`. Modele pelos
cenários já existentes no arquivo (o spec tem 11 cenários; siga o mesmo helper de
login/navegação e a convenção de `data-testid` `operate-*`/`faceplate-*` do repo).

**Nome do cenário: `PW-OP-13`.** Os números até `PW-OP-12` já estão em uso neste arquivo —
`PW-OP-12` é *"a legenda de operação mostra valor e EU na linha"*. Confirme com
`grep -n 'PW-OP-1' frontend/e2e/operate-trend.spec.ts` antes de escrever e use o primeiro
número livre; se `PW-OP-13` também estiver tomado, siga para o próximo.

**O que o cenário prova**:
1. Abre `/operacao/:flowId/:blockId` de um MPC e espera o trend desenhar.
2. Captura uma marca do estado atual de pintura — o caminho mais robusto é ler, via
   `page.evaluate`, uma cor efetivamente aplicada pelo uPlot (por exemplo o
   `stroke`/`fill` computado de um elemento de eixo do uPlot, ou a cor de grade lida do
   contexto), OU contar a quantidade de `<canvas>` criados para provar a recriação.
3. Aciona o `ThemeToggle` (`frontend/src/components/ui/theme-toggle.tsx`).
4. Assere que a instância foi **recriada** (contagem de canvas incrementa uma vez, ou a
   cor lida no passo 2 mudou). Sem o fix, nada muda.

Escolha a asserção mais determinística das duas e comente no spec qual invariante ela
prova. Evite comparar hash de imagem do canvas inteiro: o trend tem dado vivo e isso
seria flaky por construção.

Verificação: `cd frontend && npx playwright test operate-trend.spec.ts` → 12 passed
(11 existentes + 1 novo).

## Critérios de conclusão

Verificáveis por máquina. TODOS têm de valer:

- [ ] `cd frontend && npm run typecheck` sai 0 sem erro
- [ ] `cd frontend && npm run build` sai 0
- [ ] `cd frontend && npm run test:unit` verde, sem regressão contra o baseline de **633**
- [ ] `cd frontend && npx playwright test operate-trend.spec.ts` verde, com 1 cenário novo (`PW-OP-13`)
- [ ] `grep -n "useMemo(() => lerTemaTrend(), \[\])" frontend/src/features/operate/TrendOperacao.tsx`
      não retorna nada
- [ ] `grep -n "useMemo(() => lerCoresPenaOperacao(), \[\])" frontend/src/features/operate/TrendOperacao.tsx`
      não retorna nada
- [ ] `grep -n "const estrutura" frontend/src/features/operate/TrendOperacao.tsx` mostra
      `temaId` dentro do template
- [ ] `git status --porcelain` não lista arquivo fora da lista "Em escopo"
- [ ] Linha de status deste plano atualizada em `docs/reports/advisor/README.md`

## Condições de PARADA

Pare e relate (não improvise) se:

- Os excertos de "Estado atual" não corresponderem ao código vivo (estes dois arquivos
  mudaram em `ecda585`, ontem — se mudaram de novo, pare).
- Acrescentar `temaId` à `estrutura` fizer a instância ser recriada em situações
  inesperadas (por exemplo a cada render): isso indicaria que `useTema()` não é estável
  entre renders, o que contraria o `useSyncExternalStore` de `theme.ts:32`. Nesse caso a
  premissa está errada e o fix precisa de outra forma.
- Você descobrir que `TOKENS_PENA_OPERACAO` **não** tem valores próprios sob
  `[data-theme="dark"]` em `frontend/src/styles/tokens.css`. Se a paleta de pena for
  igual nos dois temas, `coresPena` não precisa da dependência (só `tema` precisa) —
  relate antes de mudar, porque isso muda o Passo 1.
- O cenário de Playwright ficar flaky em duas execuções seguidas.

## Notas de manutenção

- **O que um revisor deve escrutinar**: que `temaId` entrou na `estrutura` (sem isso o
  Passo 1 sozinho não repinta nada, e o bug parece corrigido no código mas não na tela);
  e que a paleta de pena continuou vindo de `TOKENS_PENA_OPERACAO`, não de `tema.penas`.
- **Interação futura**: qualquer campo novo que o trend de operação leia do CSS por
  `getComputedStyle` tem de entrar na mesma dependência `[temaId]`. Se aparecer um
  terceiro leitor de tema neste arquivo, vale extrair um único `useTemaTrend()` que
  devolva `{ temaId, tema, coresPena }` — mas isso é refactor, não este plano.
- **Vizinho conhecido, deliberadamente fora**: a legenda de operação não mostra valor
  nem EU (ARCH-04 / TD-024). É outro achado, com decisão de UX pendente registrada.
