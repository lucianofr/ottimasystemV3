# Plan 007: A varredura de fibra do `PW-OP-11` para de quebrar quando `TrendOperacao` ganha um hook

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado esperado antes de passar ao próximo. Se qualquer condição da seção
> "Condições de PARADA" ocorrer, pare e relate — não improvise.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat df9c5c0..HEAD -- frontend/e2e/operate-trend.spec.ts`
> Se o arquivo mudou desde que este plano foi escrito, compare o excerto de "Estado atual" com
> o código vivo antes de prosseguir; divergência é condição de PARADA.

## Status

- **Prioridade**: P1
- **Esforço**: S
- **Risco**: LOW
- **Depende de**: nenhum (conserta uma regressão já mesclada na `main`)
- **Categoria**: bug (teste)
- **Planejado em**: commit `df9c5c0`, 2026-08-16

## Por que isso importa

`PW-OP-11` está **vermelho na `main`** agora, e é regressão do plano 002 (mesclado em
`df9c5c0`). Atribuição feita por medição, não por leitura:

| Bundle servido | `PW-OP-11` |
|---|---|
| `5c6d231` (antes do plano 002), servido em `:8081` | **passa** (7,4 s) |
| `df9c5c0` (com o plano 002), servido em `:8080` | **falha 3x**, com retry |

Erro, na PRIMEIRA chamada do helper (linha 461, antes de qualquer interação):

```
Error: page.evaluate: Error: instância do uPlot não encontrada na fibra do React
    at janelaAplicadaS (frontend/e2e/operate-trend.spec.ts:420:12)
    at frontend/e2e/operate-trend.spec.ts:461:31
```

**Causa raiz.** O plano 002 corrigiu um defeito real: o trend de operação congelava as cores do
tema porque `lerTemaTrend()`/`lerCoresPenaOperacao()` estavam em `useMemo(..., [])`. A correção
acrescentou `const temaId = useTema()` em `TrendOperacao.tsx`, ANTES da chamada de
`useMotorTrend`. `useTema` é `useSyncExternalStore`, que ocupa mais de um nó na lista de hooks
da fibra.

O helper de `PW-OP-11` procura a instância do uPlot varrendo a lista de hooks de cada fibra com
teto fixo de 40 (`i < 40`, linha 449). A lista de `TrendOperacao` já era longa — 23 chamadas
diretas de hook antes do `useMotorTrend`, várias delas hooks customizados que expandem em
vários nós — e passou de 40 com a adição. O ref do uPlot continua lá; o teto é que para de
alcançá-lo.

**O defeito é o teto arbitrário, não o hook novo.** Reatividade de tema exige um hook; a
correção do 002 está certa e não será desfeita. Um teste que quebra porque o componente
ganhou um hook — sem que nada do comportamento sob teste mude — é frágil por construção, e vai
quebrar de novo no próximo hook.

## Estado atual

`frontend/e2e/operate-trend.spec.ts`, dentro do helper `janelaAplicadaS` do `PW-OP-11`:

```ts
        let no: Element | null = document.querySelector(
          '[data-testid="operate-trend-chart"] .u-wrap',
        );
        let fibra: unknown = null;
        while (no !== null && fibra === null) {
          const chave = Object.keys(no).find((nome) => nome.startsWith("__reactFiber$"));
          if (chave === undefined) no = no.parentElement;
          else fibra = (no as unknown as Record<string, unknown>)[chave];
        }

        for (let f = fibra, nivel = 0; f !== null && nivel < 40; f = campo(f, "return"), nivel++) {
          for (
            let gancho = campo(f, "memoizedState"), i = 0;
            gancho !== null && i < 40;
            gancho = campo(gancho, "next"), i++
          ) {
            const janela = janelaDoGrafico(campo(campo(gancho, "memoizedState"), "current"));
            if (janela !== null) return janela;
          }
        }
        throw new Error("instância do uPlot não encontrada na fibra do React");
```

O comentário logo acima (linhas 415-418) explica por que a leitura é pela fibra: o eixo é
desenhado no canvas, sem superfície no DOM, e o aviso na tela sai do estado do React — então
ler o aviso não provaria nada sobre o eixo. Esse raciocínio continua válido e **não muda**.

## Convenções do repositório que se aplicam aqui

- Comentários e nomes de teste em **pt-BR**; identificadores em inglês. **Sem emoji**.
- `frontend/e2e/*.spec.ts` roda com `fullyParallel: false, workers: 1`
  (`playwright.config.ts:5-6`) — "backend compartilhado com estado real".
- O padrão de nome de cenário é `PW-OP-NN`. Este plano **não** cria cenário novo.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Typecheck (cobre `e2e/`) | `cd frontend && npm run typecheck` | exit 0 |
| Checks unitários | `cd frontend && npm run test:unit` | 633 passed |
| **O RED/GREEN deste plano** | ver Passo 1 e Passo 3 | falha antes, passa depois |

**O stack do dono está no ar em `:8080` servindo o bundle da `main` @ `df9c5c0`** — que é
exatamente o bundle sob teste aqui. Neste plano, apontar o Playwright para `:8080` é **correto**:
a mudança é só no arquivo de spec, lido do seu sistema de arquivos, e o bundle que tem de ser
exercitado é o da `main`. Não reconstrua container, não rode `docker compose`, não rode a L2
(`uv run pytest -m e2e`) — `CLAUDE.md:165-167` proíbe rodar a L2 junto com o Playwright.

Credenciais: passe **inline**, nunca por export global, exatamente nesta forma
(`CLAUDE.md:168-170`) — ela lê de `deploy/.env` sem imprimir valor:

```bash
cd frontend && env \
  E2E_ADMIN_USERNAME=$(grep -m1 '^OTTIMA_ADMIN_USERNAME=' ../deploy/.env|cut -d= -f2-) \
  E2E_ADMIN_PASSWORD=$(grep -m1 '^OTTIMA_ADMIN_PASSWORD=' ../deploy/.env|cut -d= -f2-) \
  npx playwright test operate-trend.spec.ts --reporter=list
```

Nunca escreva o valor de uma credencial em arquivo, log, mensagem de commit ou relato.

## Escopo

**Em escopo** (um arquivo, um helper):
- `frontend/e2e/operate-trend.spec.ts` — apenas o helper `janelaAplicadaS` do `PW-OP-11`.

**Fora de escopo** (NÃO toque):
- `frontend/src/features/operate/TrendOperacao.tsx` — **não desfaça o `useTema()` nem tire
  `temaId` da chave `estrutura`**. Aquilo é o fix do plano 002, está certo, e é o que faz o
  `PW-OP-13` passar. Se você "consertar" o teste removendo o hook, quebra o comportamento.
- Qualquer outro cenário do spec, incluindo `PW-OP-12` e `PW-OP-13`.
- `playwright.config.ts`. Em especial: **não** aumente `retries` para mascarar a falha.

## Fluxo de git

Commite na branch da sua worktree; sem push, sem PR. Conventional Commits em pt-BR. Sugestão:
`test(frontend): varredura de fibra do PW-OP-11 não depende de teto fixo de hooks`

## Passos

### Passo 1: o RED

```bash
cd frontend && env \
  E2E_ADMIN_USERNAME=$(grep -m1 '^OTTIMA_ADMIN_USERNAME=' ../deploy/.env|cut -d= -f2-) \
  E2E_ADMIN_PASSWORD=$(grep -m1 '^OTTIMA_ADMIN_PASSWORD=' ../deploy/.env|cut -d= -f2-) \
  npx playwright test operate-trend.spec.ts -g "PW-OP-11" --reporter=list
```

**Verifique**: falha com `instância do uPlot não encontrada na fibra do React`. Se ela
**passar** aqui, o defeito não se reproduz no seu ambiente: **pare e relate**, não edite nada.

### Passo 2: tirar o teto de perto do número de hooks

No helper `janelaAplicadaS`, troque os dois tetos de `40` por um limite que exista só como
guarda contra cadeia malformada, não como palpite sobre quantos hooks o componente tem — use
`200` nos dois laços (níveis de fibra e nós de hook).

Troque também o comentário de dentro do laço para registrar por que o limite existe e o que ele
**não** é: `TrendOperacao` tem dezenas de hooks e ganha mais a cada feature; um teto perto do
número real transforma "adicionar um hook" em teste vermelho, o que já aconteceu uma vez
(`useTema`, plano 002). O limite é anti-loop-infinito, não um orçamento de hooks.

Não mude mais nada do helper: a navegação campo a campo, as guardas, `janelaDoGrafico` e a
mensagem de erro final continuam como estão.

**Verifique**: `cd frontend && npm run typecheck` → exit 0.

### Passo 3: o GREEN, e o arquivo inteiro

```bash
cd frontend && env \
  E2E_ADMIN_USERNAME=$(grep -m1 '^OTTIMA_ADMIN_USERNAME=' ../deploy/.env|cut -d= -f2-) \
  E2E_ADMIN_PASSWORD=$(grep -m1 '^OTTIMA_ADMIN_PASSWORD=' ../deploy/.env|cut -d= -f2-) \
  npx playwright test operate-trend.spec.ts --reporter=list
```

**Verifique**: **12 passed**, sem `failed` e sem `flaky` — os 11 que já passavam mais o
`PW-OP-11`. Reporte a linha de resumo exata.

## Plano de teste

Nenhum teste novo: este plano conserta um teste existente, e a prova é ele mesmo passando
(Passo 1 vermelho, Passo 3 verde) sem que uma linha de produção mude. Que a asserção continua
valendo se vê no diff: `janelaAplicadaS` segue lendo `scales.x.min/max` da instância real do
uPlot, então `PW-OP-11` continua provando exatamente o que provava — que o zoom em X é
realmente aplicado ao eixo, e não apenas ao estado do React.

## Critérios de conclusão

- [ ] Passo 1 executado e vermelho registrado, ANTES da edição
- [ ] `cd frontend && npm run typecheck` sai 0
- [ ] `cd frontend && npm run test:unit` → 633 passed
- [ ] Playwright do arquivo inteiro → **12 passed**, zero failed, zero flaky
- [ ] `git diff --name-only HEAD~1` lista **só** `frontend/e2e/operate-trend.spec.ts`
- [ ] `git diff HEAD~1 -- frontend/src` → vazio (nenhuma linha de produção tocada)
- [ ] `grep -c 'nivel < 40\|i < 40' frontend/e2e/operate-trend.spec.ts` → 0
- [ ] Nenhuma credencial em nenhum arquivo, log ou mensagem de commit

## Condições de PARADA

- Passo 1 passar em vez de falhar.
- Depois do Passo 2 o teste continuar vermelho com a MESMA mensagem: então o ref do uPlot não
  está na lista de hooks alcançada por essa varredura, e o problema não é o teto — relate o que
  observou, sem partir para reescrever o helper por conta própria.
- Aparecer falha em qualquer outro cenário (`PW-OP-01..10`, `12`, `13`): não é deste plano.
  Relate, não conserte de passagem.
- Você concluir que a saída é desfazer o `useTema()`/`temaId` em `TrendOperacao.tsx`. Isso é
  proibido por este plano e derruba o `PW-OP-13`.

## Notas de manutenção

- **O que um revisor deve escrutinar**: que `git diff HEAD~1 -- frontend/src` está vazio, e que
  a asserção de `janelaAplicadaS` não foi enfraquecida (continua lendo `scales.x` da instância).
- Esta é a segunda vez que um teste de browser depende de detalhe interno do React
  (`__reactFiber$`, `memoizedState`). Funciona e o comentário do spec justifica bem por que não
  há alternativa pelo DOM — mas é acoplamento a versão do React, e uma atualização de major
  pode quebrá-lo de novo. Se isso acontecer, a saída mais durável é o componente expor a janela
  aplicada num `data-*` só para teste, e o spec ler o DOM.
- Nenhum gate pega este vermelho: `.github/workflows/gates.yml` (ADR-035) não roda Playwright,
  por decisão registrada — a pendência está no TD-023.
