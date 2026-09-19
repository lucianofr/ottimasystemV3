# 019 — Proposta de emendas documentais (para o dono decidir)

> **Este NÃO é um plano de executor.** Todos os itens abaixo alteram documentos normativos
> (`docs/PRD.md`, `docs/adr/`) ou o `CLAUDE.md`, e o item 4 do `CLAUDE.md` exige que contradição ou
> lacuna em documento normativo seja **proposta ao dono**, nunca resolvida em silêncio. O que está
> aqui é o levantamento com evidência e o texto pronto para colar, para o dono aprovar, ajustar ou
> recusar. Nenhum arquivo em `docs/` foi editado por esta auditoria.

- **Levantado em**: commit `37b0caa`, 2026-09-19
- **Natureza**: 4 itens de *drift* — o código andou, o documento não
- **Esforço total se aprovado**: S (é redação; nenhuma linha de código)

Por que agrupado num documento só: são quatro edições pequenas de documentação que precisam da
**mesma decisão** (o dono aceita a emenda?) e da mesma revisão. Quatro planos separados
disputariam espaço no índice com os consertos de código, que é onde o risco real está.

---

## Item 1 — PRD §7.1 não lista o canal `loop.state`, que está em produção

**Severidade**: a mais alta dos quatro, porque induz agente e revisor ao erro.

**Evidência**:
- `docs/PRD.md:253-263` — a tabela §7.1 lista 10 canais (`opc.values.*`, `calc.values`,
  `flow.values`, `flow.exchange`, `opc.writes`, `flow.status.*`, `flow.commands`, `mpc.state.*`,
  `fuzzy.state.*`, `events`). `grep -c 'loop.state' docs/PRD.md` → **0**.
- O canal existe e roda: `packages/ottima-core/src/ottima_core/bus.py:61-62`
  (`channel_loop_state`), publicado a cada varredura por
  `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py`, consumido pela API
  (`services/api/src/ottima_api/ws.py:60-63`, `LOOP_STATE_PATTERN = "loop.state.*"`, "Quinta
  assinatura do hub") e pelo recorder (`services/recorder/src/ottima_recorder/pipeline.py:53`,
  sétimo listener, hypertable própria).

**O que NÃO é o problema — e isto decide como ler o item.** O PRD **não** apodreceu: a disciplina
de registrar canal novo na §7.1 foi seguida por **todos** os outros ADRs que criaram canal, cada um
com sua linha na tabela e seu bloco explicativo em `PRD.md:270-282` — `fuzzy.state` (ADR-030),
`calc.values`, `flow.values` (ADR-041) e `flow.exchange` (ADR-042, com payload emendado pelo
ADR-043). O `loop.state` do ADR-039 é o **único** canal que pulou essa etapa. É um passo de
changelog perdido, não um documento abandonado — e vale enunciar assim, senão o dono confere,
encontra quatro entradas corretas, e desconta a proposta inteira.

Quanto à invariante: o `CLAUDE.md`
exige que "criar/alterar canal exige ADR", e **o ADR existe**.
`docs/adr/ADR-039-block-shell.md:338` define o canal verbatim:
> **Estado vivo** em `loop.state.<flow_id>.<block_id>` (`LoopState` Pydantic em `_WS_MODELS`,
> throttle ~4 Hz), chave `loop_state` no `/ws` — espelho do ADR-030.

E `:339` define a hypertable `loop_samples` + CAgg. A invariante foi **honrada**. Como o ADR vence o
PRD em conflito (`CLAUDE.md` item 1), o código está certo e o **PRD é que está defasado** — exatamente
como aconteceu com `fuzzy.state` via ADR-030.

**Custo de deixar como está**: o PRD §7.1 é o documento que o `CLAUDE.md` aponta como o conjunto
**fechado** de canais. Um agente seguindo o item 4 ("encontrou contradição? PARE") trava diante de
código entregue, ou — pior — "corrige a violação" apagando um canal que sustenta o faceplate de
malha e o histórico `loop_samples` de um bloco que escreve na planta.

**Decisão pedida**: aprovar a linha nova na tabela §7.1.

**Texto proposto** (seguir a forma das linhas vizinhas da tabela):
> `loop.state.<flow_id>.<block_id>` · produtor: flow-runtime · consumidores: api (WS), recorder ·
> payload: `LoopState` · throttle 0,25 s na origem · autorizado pelo ADR-039 §4.10

**Segunda linha da mesma omissão — §7.3.** O mesmo ADR-039 também não chegou à lista de grupos de
API. `docs/PRD.md:305` enumera `/operate` com **`/fuzzy`**, `/history` com `/mpc`, `/ssto/last` e
**`/fuzzy`**, e `/ws` com **`fuzzy.state`** — mas `grep -c loop` nessa linha devolve **0**, embora
`/api/operate/loop`, `/api/history/loop` e a chave `loop_state` do `/ws` estejam todos entregues.
É a mesma falta única, não um item separado: aprovar só a §7.1 deixaria a §7.3 ainda listando o
irmão fuzzy sem o de malha, e o custo descrito acima ("agente trava diante de código entregue")
voltaria a disparar pela outra porta.

**Texto proposto para §7.3**: acrescentar `/loop` ao lado de `/fuzzy` em `/operate`, `/loop` ao
lado de `/fuzzy` em `/history`, e `loop.state` ao lado de `fuzzy.state` em `/ws`.

Sugiro replicar, logo abaixo, o *blockquote* que o PRD já usa em `:272` para o canal do ADR-030 —
mantém a convenção de marcar canal autorizado por ADR posterior ao PRD.

---

## Item 2 — Dois ADRs que governam código entregue continuam `Proposto`

**Evidência** (verificada em `37b0caa`):
- `docs/adr/ADR-036-servidor-mcp-para-agentes.md:3` — `**Status:** Proposto · 2026-08-17`.
  Entregue: `packages/ottima-mcp/src/ottima_mcp/server.py`, ~735 linhas, com ferramentas de
  **escrita** que comandam planta (`flow_deploy`, `mpc_set_mode`, `mpc_write_mv`, …).
- `docs/adr/ADR-039-block-shell.md:3` — `**Status:** Proposto · 2026-08-31`. Entregue:
  `pid_loop`/`fuzzy_loop` em `parse.py`, `validate.py:559`, `frontend/.../graph.ts`, mais um canal,
  duas hypertables, quatro rotas e uma página.
- `grep -l 'Status:\*\* Proposto' docs/adr/*.md` devolve exatamente esses dois.

**Decisão pedida**: promover ambos a `Aceito`, com a data de entrega.

---

## Item 3 — Os três ponteiros de "quais ADRs são normativos" discordam entre si e do disco

**Evidência**:

| Onde | O que diz | Realidade |
|---|---|---|
| `CLAUDE.md:7` | "`docs/adr/ADR-001…040` são NORMATIVOS" | há **43** ADRs |
| `docs/PRD.md:26` | "Documentos-irmãos (normativos): `adr/ADR-001 … ADR-042`" | há **43** |
| `docs/PRD.md:332` | "`adr/ADR-001…026` — decisões de arquitetura (normativas)" | há **43** |

`ls docs/adr/*.md | wc -l` → **43**.

**Custo**: ADR-041, 042 e 043 ficam fora de todos os intervalos citados por `CLAUDE.md:7` — e o
**ADR-043 é o que redefiniu o payload de toda porta** (`Quality`/`Substatus` tri-state). Alguém
resolvendo um conflito sobre `ok ≡ quality is GOOD` pela regra do `CLAUDE.md:7` concluiria que o
ADR-043 não é normativo. Além disso, os dois intervalos dentro do **mesmo** PRD se contradizem.

**Decisão pedida**: trocar os três intervalos numéricos por uma referência que não apodrece.

**Texto proposto**: `todos os arquivos de docs/adr/` (nos três pontos). Intervalo numérico em
documento normativo vira dívida a cada ADR novo; este é o terceiro sintoma da mesma causa.

---

## Item 4 — `CLAUDE.md`, seção "Comandos": falta `npm install` e há quatro afirmações defasadas

O cabeçalho da própria seção pede "manter esta seção atualizada".

**Nota de processo**: `CLAUDE.md` está na **raiz**, não em `docs/`, então não cai na proibição do
item 4 — mas é o documento normativo do projeto e governa o comportamento de todo agente. A
auditoria anterior registrou a mesma ressalva: **confirmar com o dono antes de editar**. Por isso
está aqui, e não como plano de executor.

**4a. Nenhuma linha ensina a instalar as dependências do frontend.**
O bloco começa em `uv sync --all-packages` e vai direto para `cd frontend && npm run build`. Não há
`npm install`/`npm ci` em nenhum ponto do arquivo. Num clone limpo, o primeiro comando de frontend
falha por `node_modules` ausente. (Carry-over #6 da auditoria de 2026-08-16 — **AINDA VALE**.)
**Proposta**: acrescentar `cd frontend && npm ci` como primeira linha do bloco de frontend.

**4b. A navegação descrita não é a implementada.**
O `CLAUDE.md` descreve "Nav do shell em dois grupos: Operação · Fuzzy · Eventos | engenharia" e "Grupo
engenharia com 5 itens". O implementado em `frontend/src/app/AppShell.tsx:13-31` são **três** grupos
— `NAV_OPERACAO` (3 itens), `NAV_ENGENHARIA` (5 itens) e `NAV_ADMIN` (1 item, `Configurações`, só
admin). O comentário do próprio `AppShell.tsx:10` também ainda diz "dois grupos".
**Proposta**: corrigir para três grupos e citar `Configurações` (RF-805, só admin).

**4c. A rota `/operacao/loop` não é mencionada.**
A seção lista as telas da F5b e a de fuzzy, mas não `/operacao/loop` (`router.tsx:50`,
`LoopOperatePage`, ADR-039). **Ligada ao plano 012**, que põe a tela na navegação — se o 012 for
executado, esta linha precisa entrar junto.

**4d. Contagens que envelheceram.**
A seção afirma "43 cenários (5 F1 + 9 F2 + 10 F3 + 10 F4 + 7 F5 + 2 fuzzy)" para a L2 e cita
contagens de teste do frontend. Números absolutos em documento de processo envelhecem a cada
entrega. **Proposta**: ou reconferir e atualizar, ou trocar por "a suíte completa de `tests/e2e`"
sem número — recomendo a segunda, pelo mesmo motivo do Item 3.

---

## Se aprovado

Nenhum destes itens exige código. Um executor pode aplicá-los em **um commit de documentação**
depois do aval do dono, com mensagem no padrão da casa
(`docs: PRD §7.1 registra loop.state; ADRs 036/039 aceitos; ponteiros de ADR sem intervalo`).

Gates aplicáveis: nenhum teste muda; `uv run ruff check .` continua verde porque `docs/` está em
`extend-exclude` (`pyproject.toml:46`). A verificação é leitura.

**Ordem sugerida**, se o dono aprovar em partes: Item 3 (maior risco de induzir erro, menor
esforço) → Item 1 → Item 2 → Item 4.

## Itens de documentação deliberadamente NÃO propostos

- **Reescrever `docs/PRD.md` §5 para descrever os 16 tipos de bloco.** A auditoria constatou que
  cinco tipos entregues não aparecem no PRD. É verdade, mas é redação de escopo grande sobre o
  documento de requisitos — não cabe numa emenda pontual e merece decisão própria do dono sobre
  **se** o PRD deve continuar espelhando cada bloco. **Nota**: a lacuna da §7.3 quanto a
  `/operate/loop`, `/history/loop` e `loop_state` **não** faz parte desta rejeição — ela é uma
  linha só, da mesma omissão do ADR-039, e está no Item 1.
- **Registrar o servidor MCP como capacidade do projeto.** Ele vive em configuração de máquina
  (`.mcp.json` + credencial em env), não é herdado por clone nem por CI; a auditoria anterior já
  decidiu, no plano 009, não registrá-lo no `_tech-debt.md` pelo mesmo motivo.
- **Fechar o TD-026.** O enunciado dele continua literalmente verdadeiro; o plano 012 reduz o custo
  para uma tela, não o elimina.
