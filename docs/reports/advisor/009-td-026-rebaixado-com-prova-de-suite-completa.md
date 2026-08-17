# Plan 009: TD-026 rebaixado a Low com prova de suíte completa, runbook e o custo escrito — NÃO fechado

> **Instruções ao executor**: siga este plano passo a passo. Rode TODO comando de verificação e
> confirme o resultado antes de passar ao próximo. Se qualquer condição da seção "Condições de
> PARADA" ocorrer, pare e relate — não improvise.
>
> **Checagem de drift (rode primeiro)**:
> `git diff --stat bc4e882..HEAD -- docs/reports/_tech-debt.md`
> Divergência com o excerto de "Estado atual" é condição de PARADA.

## Status

- **Prioridade**: P2
- **Esforço**: S
- **Risco**: LOW
- **Depende de**: 007 (o conserto) e 008 (que abriu o TD-026)
- **Categoria**: docs / registro de dívida
- **Planejado em**: commit `bc4e882`, 2026-08-16

## Por que isso importa

O `TD-026` foi aberto hoje pelo plano 008 como **High**. Uma versão anterior deste plano queria
FECHÁ-LO, e estava errada — o título do item é *"regressão de comportamento da tela de operação
só é detectada rodando o Playwright à mão contra um stack reconstruído"*, e isso **continua
literalmente verdadeiro**. Marcar como resolvido um item cujo enunciado segue valendo é
falsificar o registro; quem ler em seis meses vai acreditar que existe detecção automática que
não existe.

O que realmente mudou hoje, e precisa estar escrito:

1. **O defeito que motivou o item foi consertado e a suíte INTEIRA está verde nesta `main`**:
   `npm run e2e` → **64 passed, 2,4 min, zero failed, zero flaky**, contra stack reconstruída de
   `bc4e882` (frontend, api e flow-runtime rebuildados; 9 serviços `healthy`; flow redeployado
   por `scripts/setup-l3.py`). Não são 12 cenários de um arquivo: são os 64 da suíte, incluindo
   `PW-OP-11` (7,4 s) e `PW-OP-13` (1,0 s).
2. **A margem da causa específica foi MEDIDA, não estimada**: a instância do uPlot mora no
   **hook de índice 41** da fibra de `TrendOperacao`. O teto antigo (`i < 40`) errava por **um**;
   o novo (`200`) deixa ~159 hooks de folga. A recorrência daquela causa é quantificadamente
   improvável.
3. **O que NÃO mudou**: nada força a checagem. Continua sendo decisão deliberada da
   [ADR-035](../../adr/ADR-035-mecanizacao-dos-gates.md) manter fora do CI a stack de 9 serviços,
   o `opcsim` e as credenciais de `deploy/.env`.

Portanto o item **fica aberto**, rebaixado de **High** para **Low (Track for Later)** — a faixa
que as Priority Guidelines do próprio arquivo reservam para o que é gerenciável e revisto em
cadência trimestral. Um custo aceito e visível é melhor registro do que uma dívida fechada por
conveniência.

**Fora deste plano, de propósito**: existe uma segunda via de execução via servidor MCP do
Playwright, mas ela vive em `~/.omp/agent/mcp.json`, no home de um operador, **fora do
repositório**. Nenhum colega, nenhuma máquina nova e nenhum CI herda isso. Registrar essa
ferramenta como capacidade do projeto no registro de dívida seria enganoso, então ela **não entra
no `_tech-debt.md`** — fica apenas no registro do advisor, que é onde descreve o ambiente de quem
auditou.

## Estado atual

`docs/reports/_tech-debt.md`, na seção `## High (Causes Frequent Issues)`:

```markdown
- [ ] **TD-026**: Regressão de comportamento da tela de operação só é detectada rodando o Playwright à mão contra um stack reconstruído
  - **Evidência de 2026-08-16**: `PW-OP-11` (zoom em X sobrevive à troca do eixo Y) ficou vermelho ao mesclar o fix de tema em `TrendOperacao.tsx` — o helper do cenário varre a lista de hooks da fibra do React com teto fixo, e um hook novo (`useTema`) pôs o ref do uPlot fora do alcance. Passou por `ruff`, `test:unit` 633, `typecheck` e `build` **todos verdes**. Só apareceu quando alguém reconstruiu o container e rodou `operate-trend.spec.ts`.
  - **Por que continua aberto e não é esquecimento**: a ADR-035 decidiu que a stack de 9 serviços, o `opcsim` e as credenciais de `deploy/.env` ficam fora do CI. O item registra o **custo** da decisão, para ele ser revisto de olho aberto — não a contradiz.
  - **Mitigação em uso hoje**: rodar `cd frontend && npm run e2e` (ou o spec afetado) contra o stack reconstruído a partir da `main` antes de considerar mesclada qualquer mudança em `frontend/src/features/operate/` ou `frontend/src/features/trend/`.
```

Leia as **Priority Guidelines** no topo do arquivo e a seção `## Low (Track for Later)` antes de
mover: use a forma que já está lá, sem inventar seção nem cabeçalho novo.

## Convenções do repositório que se aplicam aqui

- Registro em **pt-BR**, sem emoji. Datas `YYYY-MM-DD`.
- O item continua `- [ ]` (aberto). **Não** use `- [x]`, **não** acrescente `**Resolved:**`.
- Se a seção `## High (Causes Frequent Issues)` ficar sem item aberto, restaure a linha
  `_Nenhum item aberto._` que o plano 008 havia substituído.

## Comandos que você vai precisar

| Objetivo | Comando | Esperado |
|---|---|---|
| Continua aberto | `grep -c '^- \[ \] \*\*TD-026' docs/reports/_tech-debt.md` | `1` |
| Não foi fechado | `grep -c '^- \[x\] \*\*TD-026' docs/reports/_tech-debt.md` | `0` |
| TD-023 intacto | `grep -c '^- \[x\] \*\*TD-023' docs/reports/_tech-debt.md` | `1` |
| Está em Low | `awk '/^## Low/,/^## /' docs/reports/_tech-debt.md \| grep -c 'TD-026'` | `1` |
| Nada de código | `git diff --stat HEAD~1 -- frontend packages services` | vazio |

Não rode `docker compose`, Playwright, `uv run pytest` nem `npm`. Este plano é só registro.

## Escopo

**Em escopo**: `docs/reports/_tech-debt.md` — apenas o item `TD-026` e as duas linhas de seção
que a movimentação afeta.

**Fora de escopo** (NÃO toque): qualquer outro item, em especial `TD-023`; `docs/adr/*`;
`.github/workflows/gates.yml`; qualquer arquivo de código; e **não** mencione o servidor MCP
neste arquivo.

## Fluxo de git

Commite na branch da sua worktree; sem push, sem PR. Sugestão:
`docs(debt): TD-026 rebaixado a Low com prova de suite completa e runbook`

## Passos

### Passo 1: mover o item para Low, preservando a evidência

Mova o item `TD-026` inteiro da seção `## High (Causes Frequent Issues)` para
`## Low (Track for Later)`, mantendo `- [ ]` e **preservando integralmente** o parágrafo
`**Evidência de 2026-08-16**` (é o registro do incidente; não resuma, não reescreva).

Ajuste o bullet de prioridade se o formato da seção Low pedir, seguindo os itens vizinhos.

### Passo 2: acrescentar os três bullets novos

Depois do parágrafo de evidência, acrescente:

- `- **Rebaixado para Low em 2026-08-16, com prova:**` — `npm run e2e` completo contra stack
  reconstruída de `bc4e882` (frontend, api e flow-runtime rebuildados, 9 serviços `healthy`,
  flow redeployado por `scripts/setup-l3.py`): **64 passed, 2,4 min, zero failed, zero flaky**,
  incluindo `PW-OP-11` (7,4 s) e `PW-OP-13` (1,0 s). O código está são nesta `main`; o que
  permanece é a ausência de gatilho automático.
- `- **Margem medida da causa específica:**` — a instância do uPlot está no hook de índice **41**
  da fibra de `TrendOperacao`, medido na planta viva. O teto antigo da varredura (`i < 40`)
  errava por um; o atual (`200`) deixa ~159 hooks de folga. Recorrência daquela causa é
  quantificadamente improvável.
- `- **Runbook (o gatilho é de processo, não de máquina):**` — antes de considerar mesclada
  qualquer mudança em `frontend/src/features/operate/`, `frontend/src/features/trend/` ou nos
  contratos que elas consomem, rode nesta ordem:
  1. `cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --no-deps frontend api flow-runtime`
  2. `uv run python scripts/setup-l3.py` (o restart do flow-runtime deixa o flow parado)
  3. `cd frontend && npm run e2e` com as credenciais inline (`CLAUDE.md:168-170`)
  Rodar a suíte contra um container antigo dá **verde falso** — o bundle testado é o do container,
  não o da árvore.

**Não** acrescente nenhum bullet dizendo ou insinuando que existe detecção automática.

### Passo 3: a seção que ele deixa

Se `## High (Causes Frequent Issues)` ficou sem item aberto, restaure `_Nenhum item aberto._`.

**Verifique**: os 5 comandos da tabela, com os valores esperados.

## Plano de teste

Sem teste: a mudança é de registro. A verificação são os greps do Passo 3 mais
`git diff --stat HEAD~1 -- frontend packages services` vazio.

## Critérios de conclusão

- [ ] `grep -c '^- \[ \] \*\*TD-026' docs/reports/_tech-debt.md` → `1`
- [ ] `grep -c '^- \[x\] \*\*TD-026' docs/reports/_tech-debt.md` → `0`
- [ ] `grep -c '^- \[x\] \*\*TD-023' docs/reports/_tech-debt.md` → `1`
- [ ] `awk '/^## Low/,/^## /' docs/reports/_tech-debt.md | grep -c 'TD-026'` → `1`
- [ ] `grep -c 'mcp\|MCP' docs/reports/_tech-debt.md` → **0** (o servidor MCP não entra aqui)
- [ ] O parágrafo `**Evidência de 2026-08-16**` continua íntegro
- [ ] `git diff --name-only HEAD~1` lista **só** `docs/reports/_tech-debt.md`
- [ ] `git diff --stat HEAD~1 -- frontend packages services` → vazio
- [ ] Um commit na sua branch, mensagem pt-BR

## Condições de PARADA

- O `TD-026` não estar no arquivo, ou já estar fechado/movido: relate, não escreva de novo.
- O arquivo não ter seção `## Low (Track for Later)`: relate os cabeçalhos que existem, não crie
  seção nova.
- Você concluir que o item deveria ser FECHADO: não feche. Relate o argumento e pare — a decisão
  de fechar exige rever a ADR-035, que está fora deste plano.

## Notas de manutenção

- **O que fecharia o item de verdade**: uma ADR nova que supere a 035 e ponha a stack no CI
  (`workflow_dispatch` ou nightly, com `docker compose` e segredos de repositório). Enquanto isso
  não existir, o item é custo aceito e visível, não dívida esquecida.
- Se `TrendOperacao` passar de ~190 hooks, a varredura de fibra volta a ser frágil; a saída
  durável está na nota de manutenção do plano 007 (o componente expor a janela aplicada num
  `data-*`).
