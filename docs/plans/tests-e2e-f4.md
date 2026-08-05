# Roteiro L3 — Testes E2E de browser (Fase F4 — Bloco MPC)

**Status:** normativo para o gate da F4 · draft do agente e2e-runner revisado e aceito pelo controlador · 2026-08-04.
**Fase:** F4 (PRD §8) · bloco MPC (config, montagem, runtime e modos).
**Quem executa:** o **agente controlador**, segurando a tool nativa `browser` do harness omp. Subagentes NÃO têm acesso a essa tool (bloqueada por design) — nenhum passo deste roteiro pode ser delegado a subagente.
**Quando roda:** plano F4b, Etapa 5, tarefa 5.1 — última camada da rodada de gate completa da fase, depois de L1 e L2.

**Fontes normativas** (precedência ADR > PRD > spec > plano; ADRs sempre vencem em conflito):
- `docs/adr/ADR-004` (loops vivos, sem bloquear event loop), `ADR-008` (modal em abas), `ADR-010` (modos), `ADR-011` (hot-swap sem versionamento), `ADR-013` (SOPDT/TSS/integrador), `ADR-019` (precedência CV×Restrição).
- `docs/PRD.md` v1.2 §7 (contratos), §8-F4 (aceite da fase).
- `docs/specs/F4-mpc.md` — inteira; em especial §2 (config/validação), §7 (frontend), §8 tabela m4 (débitos de UI), §9.2 (gate, L3 B-F4-01..06), §9.3 (precondições).
- `docs/plans/F4a-mpc-config-montagem.md` Etapa 0 tarefa 0.7 e Etapa 4 (tarefas 4.1/4.2/4.3).
- `docs/plans/F4b-mpc-runtime-modos.md` Etapa 4 (L2, para as fronteiras L2×L3) e Etapa 5 (gate).
- `docs/specs/F3-motor-canvas.md` §7.2 (modelo de estilo dos cenários B-F3, protocolo de gate herdado).
- `CLAUDE.md` §Comandos (comandos canônicos do stack e precondições do gate).
- `DESIGN.md` §Do's and Don'ts (asserts visuais objetivos: mono tabular, sem verde fora de lâmpada, Regra da Plaqueta, Regra do Canal Redundante).

## Regra de ferro

**A fase F4 só é considerada pronta quando L1 + L2 (34 cenários — 5 F1 + 9 F2 + 10 F3 + 10 F4) estiverem verdes E este roteiro inteiro estiver verde, na mesma rodada** (plano F4b, Etapa 5, tarefa 5.1). Qualquer vermelho em qualquer camada invalida a rodada inteira: corrige, e a rodada completa (desde `down -v`) roda de novo — não se re-executa só o cenário que falhou.

---

## 1. Precondições de ambiente

Copiadas de `CLAUDE.md` §Comandos e `docs/specs/F4-mpc.md` §9.3 (que herda integralmente o protocolo da F3). Válidas para a rodada de gate inteira, não só para este roteiro.

1. **Stack composta com os DOIS arquivos compose** — sem o override `e2e`, o opcsim e o Redis de teste não ficam acessíveis do host:
   ```bash
   cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d
   ```
   8 serviços (7 sem o override).
2. **Rebuild do bundle novo do frontend** antes de qualquer passo deste roteiro (o browser precisa do bundle com o bloco MPC, o modal de 7 abas e os minors m4 — nada disso existe no bundle da F3):
   ```bash
   cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --no-deps frontend
   ```
   `--no-deps` é obrigatório: `--build frontend` sem essa flag arrasta o `api` junto.
3. **Frontend acessível em `http://localhost:8080`** (proxy do nginx do compose; não confundir com `127.0.0.1:5173` do `npm run dev`, que não faz parte do gate).
4. **Credenciais SEMPRE inline de `deploy/.env`** — ler o arquivo, extrair usuário/senha do admin seed e digitá-los diretamente no passo de login. Nunca `export` em shell persistente da sessão (o mesmo cuidado do `E2E_ADMIN_USERNAME`/`E2E_ADMIN_PASSWORD` do L2/Playwright — evita vazar `OTTIMA_DATABASE_URL` e quebrar os testcontainers da suíte unitária).
5. **L2 e Playwright são serializados** — nunca rodam juntos (o `E2E-16` publica `project_activated` duas vezes e derruba `E2E-F3-03/04/08`). Este roteiro (L3) roda depois de ambos terminarem, contra o mesmo compose já de pé.
6. **L1 exige flow-runtime recém-subido**: o smoke assere `flows={}` no boot. Se a L2 já rodou antes deste roteiro (deploys de flow ficam no mapa como `stopped`), rodar `docker compose ... restart flow-runtime` antes do L1 — não antes deste roteiro L3 (que quer justamente um flow-runtime já usado, com o flow MPC de teste passível de deploy).
7. **Estado inicial do roteiro**: projeto ativo existente (herdado do setup F1/F2/F3), pelo menos uma conexão OPC (`opcsim`) com tags cadastradas para simular o `pid` de uma MV (tags de escrita/leitura de modo/readback), papel **admin** logado. Cada cenário declara suas pré-condições específicas de estado de banco/flow/login/papel.
8. **Diretório de evidências criado antes do primeiro passo**:
   ```bash
   mkdir -p .superpowers/sdd/F4-mpc/evidencias-l3
   ```

---

## 2. Regras de execução com a tool `browser`

Armadilhas confirmadas empiricamente no roteiro L3 da F3 — tratadas aqui como regras obrigatórias, não sugestões. Toda ação de UI deste roteiro segue estas regras sem exceção.

1. **`tab.click`/`tab.fill`/`tab.waitFor*` aceitam APENAS seletores string** (CSS ou texto) — nunca objetos de referência de snapshot. Preferir `[data-testid="..."]`; onde o testid ainda não existe (superfícies novas da F4, ver notas "provável" em cada cenário), usar seletor por texto visível ou `role`+nome acessível, com o CSS como plano B documentado no passo.
2. **`wait(ms)` é uma chamada global** da tool — não existe `tab.waitFor(ms)`. Esperas por tempo fixo usam a chamada `wait`; esperas por condição usam `tab.waitFor` com seletor/estado (visível, oculto, texto).
3. **`tab.drag(from, to)` recebe `{x, y}` como dois argumentos posicionais** (origem e destino), não um único objeto com dois pares de coordenadas. Usado no arraste da paleta para o canvas (B-F4-01) e para reposicionar nós ao checar a grade de slot livre (B-F4-05).
4. **`tab.doubleClick` NÃO EXISTE.** O duplo-clique que abre o modal de configuração de bloco (`onNodeDoubleClick` do React Flow, escuta nativa de `dblclick`) é disparado via `tab.evaluate`:
   ```js
   (() => {
     const el = document.querySelector('SELETOR_DO_NO');
     el.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
   })()
   ```
   `bubbles: true` é obrigatório — o React Flow delega o listener na raiz do painel, não no nó individual. Todo cenário que abre o modal MPC (B-F4-02 em diante) usa este workaround, nunca uma tentativa de duplo-clique via `tab.click` repetido (que dispara dois `click` separados, não um `dblclick`, e não abre o modal).
5. **`tab.select` exige o `value` do `<option>`, não o texto visível.** Confirmado no código existente (`CamposTfs.tsx`): `<option value="sopdt">SOPDT</option>` — o texto e o value coincidem em minúsculas mas são campos distintos; para os selects novos do modal MPC (kind de CV/Restrição, `target_mode`, `mode_values`, tags do `pid`) o `value` é sempre o identificador em minúsculas/snake_case do schema (`selfreg`/`integrating`, `rcas`/`cas`/`rout`, id numérico da tag como string) — nunca o rótulo pt-BR exibido.
6. **Refs de `ariaSnapshot` são reusadas entre snapshots e quebram laços** (ex.: adicionar 3 variáveis em sequência, preencher célula por célula da matriz). Para qualquer laço, marcar o elemento-alvo no DOM antes de agir e clicar por seletor CSS estável, não por ref reaproveitada:
   ```js
   document.querySelectorAll('[data-testid^="mpc-var-row-"]')[indice]
     .setAttribute('data-alvo', '1');
   ```
   seguido de `tab.click('[data-alvo="1"]')` (e remoção do atributo antes da próxima iteração, ou seletor mais específico por índice/id estável quando o testid já carrega o id da variável).
7. **Screenshot por passo relevante**: `tab.screenshot()` imediatamente após toda ação que muda o DOM de forma observável (clique que abre modal, preenchimento que dispara validação ao vivo, salvar, erro 422). Salvar e copiar para o diretório de evidências (seção 3) com o nome exato do passo — nunca sobrescrever um screenshot de um passo anterior do mesmo cenário.

---

## 3. Evidências

Um screenshot por passo relevante (toda ação listada na regra 7 acima), salvo em:

```
.superpowers/sdd/F4-mpc/evidencias-l3/B-F4-XX-passoNN.png
```

`XX` = número do cenário com dois dígitos (`01`..`07`); `NN` = número do passo dentro do cenário, também com dois dígitos, na ordem em que aparece na tabela de passos do cenário (`passo01`, `passo02`, ...). Nomeação obrigatória e literal — não usar descrições livres no nome do arquivo (a rastreabilidade cenário→passo→evidência depende do padrão fixo).

---

## 4. Cenários

### B-F4-01 — Paleta com MPC habilitado e nó sem portas antes de configurar

**Objetivo:** confirmar que o bloco MPC saiu do estado desabilitado da F3 e que o nó recém-criado no canvas não tem portas (config vazio) até ser configurado.
**Rastreabilidade:** RF-301 · spec F4 §7.1 · plano F4a tarefa 4.1.
**Pré-condições:** login admin; projeto ativo; flow existente com `Ts` qualquer, sem blocos MPC ainda, aberto no editor (`/engenharia/flows/:flowId`) em estado parado (não precisa estar rodando).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Login: `tab.fill('[data-testid="login-username"]', <usuário de deploy/.env>)`, `tab.fill('[data-testid="login-password"]', <senha>)`, `tab.click('[data-testid="login-submit"]')`. | Redireciona para fora de `/login`. |
| 2 | Navegar para o flow: `tab.click('[data-testid="flow-abrir"]')` na linha do flow de teste em `/engenharia/flows`. | Editor carrega; `[data-testid="canvas-vivo"]` visível. |
| 3 | `tab.screenshot()` do bloco MPC na paleta antes de qualquer interação. | Elemento `[data-testid="paleta-mpc"]` presente, **sem** `aria-disabled="true"`, **sem** o badge de texto "F4" e **sem** o texto "Disponível na próxima fase" (ambos ausentes — busca por `tab.waitFor` com seletor de texto deve **falhar**, confirmando ausência). Bloco arrastável (atributo `draggable="true"`). |
| 4 | Arrastar o bloco ao canvas: `tab.drag('[data-testid="paleta-mpc"]', {x, y})` com destino em área livre do canvas (coordenadas obtidas do bounding box do `<canvas>`/painel do React Flow via `tab.evaluate`, não chutadas). | Novo nó aparece no canvas com a chapa/plaqueta padrão do bloco MPC (DESIGN.md §Shapes: chapa, bisel 2-4px). |
| 5 | `tab.screenshot()` do nó recém-criado. | Nó exibe rótulo/plaqueta do tipo MPC e badge de `exec_order`; **nenhuma porta de entrada nem de saída** desenhada (`div` de portas do `BlocoChapa` ausente ou vazio) — o config ainda não tem `variables`. |

**Evidência:** `B-F4-01-passo03.png`, `B-F4-01-passo04.png`, `B-F4-01-passo05.png`.

---

### B-F4-02 — Modal 7 abas, criação de variáveis e matriz de modelos

**Objetivo:** confirmar que o duplo-clique abre o modal com as 7 abas nomeadas conforme RF-607 verbatim, que a aba Variáveis cria 1 MV + 1 CV + 1 DV (com `pid` opcional vazio na MV) e que a matriz em Modelos nasce com os pares corretos e os parâmetros SOPDT conforme o `kind` da linha.
**Rastreabilidade:** RF-601/602/604/607 · spec F4 §2.1 (esqueleto de config), §7.3 · plano F4a tarefa 4.2.
**Pré-condições:** continuação de B-F4-01 (nó MPC no canvas, ainda sem config) — ou, isoladamente, um flow com um nó MPC recém-arrastado.

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Duplo-clique via workaround (regra 4, seção 2) no nó MPC: `el = document.querySelector('[data-testid^="rf__node-"][data-id="<id-do-no>"]')` (ou seletor equivalente do wrapper de nó do React Flow) → `dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))`. | Modal abre: `[data-testid="config-modal"]` (ou `[data-testid="mpc-modal"]` se o componente novo usar testid próprio — checar os dois antes de falhar o passo) visível como `<dialog>` aberto. |
| 2 | `tab.screenshot()` da aba inicial (Geral). | As 7 abas aparecem, nesta ordem e com estes textos exatos (RF-607 verbatim): **Geral · Variáveis · Modelos · Horizontes · Restrições & Limites · Pesos · Resumo**. Seletor provável: `[role="tab"]` dentro do modal, texto exato por `tab.waitFor` com seletor de texto por aba. |
| 3 | Clicar na aba Variáveis: `tab.click('[role="tab"]:has-text("Variáveis")')` (fallback: seletor por `data-testid="mpc-tab-variables"`, provável). | Aba Variáveis ativa; 4 listas visíveis (MVs, CVs, Restrições, DVs), cada uma com botão de adicionar (provável `data-testid="mpc-add-mv"`, `mpc-add-cv"`, `mpc-add-constraint`, `mpc-add-dv"`). |
| 4 | Adicionar 1 MV: `tab.click('[data-testid="mpc-add-mv"]')`; preencher nome (`tab.fill` no campo de nome da linha recém-criada, marcada por `data-alvo` conforme regra 6) e EU; deixar a seção `pid` **fechada/vazia** (não preencher tags, `target_mode` nem `mode_values`). | Linha da MV aparece na lista com id gerado no padrão `mv_<sufixo>` (visível em texto ou atributo `title`/`data-var-id`, verificável via `tab.evaluate`); nenhum erro de validação client-side por `pid` ausente (opcional por MV — decisão A-8). |
| 5 | Adicionar 1 CV: `tab.click('[data-testid="mpc-add-cv"]')`; preencher nome, EU e `kind` = Autorregulável via `tab.select` com **value** `selfreg` (regra 5, seção 2) — não o texto "Autorregulável". | Linha da CV aparece com id `cv_<sufixo>`; `kind` gravado como `selfreg`. |
| 6 | Adicionar 1 DV: `tab.click('[data-testid="mpc-add-dv"]')`; preencher nome e EU. | Linha da DV aparece com id `dv_<sufixo>`. |
| 7 | `tab.screenshot()` da aba Variáveis com as 3 linhas. | 1 MV + 1 CV + 1 DV listadas; nenhuma linha de Restrição (não pedida neste cenário). |
| 8 | Clicar na aba Modelos: `tab.click('[role="tab"]:has-text("Modelos")')`. | Matriz aparece: 1 linha (a CV criada) × 2 colunas (a MV e a DV criadas) — Restrições entrariam como linhas adicionais, DVs como colunas adicionais, mas aqui há só 1 de cada categoria com par possível. |
| 9 | `tab.screenshot()` da matriz. | Cada célula da linha da CV mostra campos de parâmetro **SOPDT** (`K`, `tau1`, `tau2`, `theta`) — não IOPDT — porque o `kind` da linha (a CV) é `selfreg` (spec §2.1-2: o `kind` da linha define a forma dos `params` de toda a linha, não é escolha por célula como no TFS). |

**Evidência:** `B-F4-02-passo01.png` a `B-F4-02-passo09.png`.

**Nota sobre selectors "prováveis":** o modal MPC ainda não existe no branch de trabalho no momento deste draft (F4a Etapa 4 ainda não implementada) — todo `data-testid` citado acima que não seja `config-modal`/`config-aplicar`/`config-cancelar`/`config-label` (confirmados em `ModalConfigBloco.tsx` para os blocos existentes) é uma previsão alinhada à convenção de nomenclatura já em uso no repositório (`tfs-enabled-JK`, `tfs-kind-JK`, `flow-*`, `tag-*`) e deve ser confirmado/ajustado contra o código real de `frontend/src/features/flows/mpc/*.tsx` antes da execução — o texto visível das abas (RF-607 verbatim) e os rótulos pt-BR são a fonte de verdade quando o testid não bater.

---

### B-F4-03 — Horizontes ao vivo e Resumo bloqueando/liberando o salvar

**Objetivo:** confirmar que a aba Horizontes deriva `Ts_mpc`/`Np`/`Nc` ao vivo (read-only) a partir do TSS digitado, que um `Np` grande produz o warning não-bloqueante, e que a aba Resumo bloqueia o salvar com matriz incompleta e libera quando ela é completada.
**Rastreabilidade:** RF-603/605/607/608 · spec F4 §2.2-5 (fórmulas de horizonte), §2.2-7 (warnings) · plano F4a tarefa 4.3.
**Pré-condições:** continuação de B-F4-02 (modal aberto, MV+CV+DV criadas, matriz com 1 linha visível). O par CV×MV da matriz **não** está habilitado ainda (matriz "vazia" no sentido do §2.2-3: linha sem par habilitado com coluna MV).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Clicar na aba Horizontes: `tab.click('[role="tab"]:has-text("Horizontes")')`. | Campo de TSS por linha (a CV) visível; campos `Ts_mpc`/`Np`/`Nc` **read-only** (atributo `readonly`/`disabled` confirmado via `tab.evaluate`). |
| 2 | Preencher TSS da CV com um valor pequeno (ex.: `60`, aceitando ponto): `tab.fill(seletor_tss_cv, "60")`. | `Ts_mpc`/`Np`/`Nc` mudam ao vivo sem precisar de salvar/reload (valor lido via `tab.evaluate` antes/depois do fill confirma a mudança); nenhum warning de `Np>60` para este valor. |
| 3 | `tab.screenshot()` do estado com TSS pequeno. | Valores derivados visíveis e coerentes com a fórmula (`Ts_mpc = multiplier × Ts_flow`; `Np = ceil(TSS/Ts_mpc)`). |
| 4 | Trocar o TSS para um valor grande o bastante para estourar `Np>60` (calcular a partir do `Ts_mpc` exibido no passo 2 — ex.: TSS tal que `Np` fique entre 61 e 120, ainda válido mas com warning). `tab.fill(seletor_tss_cv, <valor calculado>)`. | Warning não-bloqueante aparece na tela (texto visível, não um alerta de erro que impeça digitação) — "Np > 60" ou equivalente pt-BR referenciando a carga de RNF-02; o campo continua editável. |
| 5 | `tab.screenshot()` do warning ao vivo. | Warning visível; `Np` exibido entre 61 e 120. |
| 6 | Clicar na aba Resumo: `tab.click('[role="tab"]:has-text("Resumo")')`. | Lista de erros de validação visível: matriz sem par habilitado com coluna MV (§2.2-3) listada como erro bloqueante — texto pt-BR explícito, não um código. |
| 7 | Tentar salvar com o erro presente: `tab.click('[data-testid="config-aplicar"]')` (ou o botão de submit equivalente do modal MPC). | Salvar **bloqueado**: modal não fecha, ou fecha mas o `PUT` não é disparado / é rejeitado antes de chegar ao servidor — o erro listado no Resumo continua visível; nenhum `[data-testid="flow-salvar"]` bem-sucedido. |
| 8 | `tab.screenshot()` do bloqueio. | Erro(s) do Resumo visível(is) simultaneamente à tentativa de salvar. |
| 9 | Voltar à aba Modelos, habilitar o par CV×MV (`tab.click` no checkbox/toggle "habilitado" da célula, seletor provável `[data-testid="mpc-cell-enabled-<cv_id>-<mv_id>"]`) e preencher os 4 parâmetros SOPDT com valores válidos (`K≠0`, `tau1>0`, `tau2≥0`, `theta≥0`) via `tab.fill`, aceitando ponto. | Célula marcada habilitada; campos preenchidos sem erro de formato. |
| 10 | Voltar à aba Resumo. | Erro de matriz incompleta **desaparece** da lista. |
| 11 | Tentar salvar de novo: `tab.click('[data-testid="config-aplicar"]')` (ou submit equivalente), depois `tab.click('[data-testid="flow-salvar"]')` no editor. | Salvar **liberado**: sem erro bloqueante; requisição `PUT /api/flows/{id}` sai (confirmável por resposta na aba de rede da tool `browser`, se disponível, ou pela transição visual do editor — mensagem de sucesso/ausência de `[data-testid="editor-mensagens"]` com erro). |
| 12 | `tab.screenshot()` do salvar liberado. | Nenhum erro em `[data-testid="editor-mensagens"]`. |

**Evidência:** `B-F4-03-passo01.png` a `B-F4-03-passo12.png`.

---

### B-F4-04 — Portas dinâmicas após salvar e 422 do servidor exibido em pt-BR

**Objetivo:** confirmar que salvar re-renderiza o nó com portas dinâmicas (entradas CV/Restrição/DV à esquerda, saídas MV à direita, rótulo `nome (EU)`) e que uma reprovação 422 do servidor aparece como string única em pt-BR.
**Rastreabilidade:** RF-301/302 · spec F4 §2.1-5 (portas), §2.2 (validação 422), §7.2 · plano F4a tarefas 4.1/4.3.
**Pré-condições:** continuação de B-F4-03 (flow com o bloco MPC salvo com sucesso — 1 MV, 1 CV, 1 DV, 1 par habilitado). Existe pelo menos uma tag do projeto ativo que **não** está vinculada ao `pid` desta MV (será removida para provocar o 422 — ver passo 4).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Fechar o modal (se ainda aberto) e observar o nó no canvas. `tab.screenshot()`. | Nó re-renderiza com portas: **entradas à esquerda** = CV + DV (2 portas, ids `cv_<sufixo>` e `dv_<sufixo>`), **saída à direita** = MV (1 porta, id `mv_<sufixo>`) — nenhuma porta de Restrição (não criada neste roteiro). |
| 2 | Verificar rótulo das portas via `tab.evaluate` lendo o texto dos `<span>` de plaqueta de cada `LinhaPorta`. | Rótulo no formato **`nome (EU)`** — ex. "Vazão de carga (m3/h)" — não apenas o id técnico (diferente do rótulo simples usado por Script/TFS, que é o próprio id do handle). |
| 3 | `tab.screenshot()` do nó com portas rotuladas. | Confirma visualmente handles à esquerda (entradas) e à direita (saídas), bisel 2-4px (DESIGN.md §Shapes), rótulos em Regra da Plaqueta (caps/Narrow). |
| 4 | Provocar 422 do servidor **só com UI**: navegar para `/engenharia/tags`, localizar a tag associada ao `pid` de outra MV do config se houver, ou — caminho mais simples e sempre disponível — reeditar o config do MV para adicionar um `pid` completo referenciando uma tag existente, salvar com sucesso, depois ir a `/engenharia/tags` e excluir essa tag (`tab.click('[data-testid="tag-delete"]')` na linha, `tab.click('[data-testid="tag-delete-confirm"]')`). Se a exclusão da tag for bloqueada pelo backend (proteção referencial ainda não confirmada nesta fase), usar o caminho alternativo: editar a mesma tag (`tab.click('[data-testid="tag-edit"]')`) e trocar sua **direção** (`tab.select('[data-testid="tag-direction"]', <value oposto>)`) para quebrar a integridade `write`/`mode_cmd` = W exigida pelo `pid` (spec §2.2-6), e salvar a tag. | Tag excluída (ou direção trocada) com sucesso na tela de Tags. |
| 5 | Voltar ao editor do flow, abrir o modal MPC de novo (workaround dblclick), reabrir a aba Variáveis para confirmar visualmente a referência quebrada (opcional, mas útil para o screenshot de evidência), fechar sem alterar nada além do necessário, e tentar salvar o flow: `tab.click('[data-testid="flow-salvar"]')`. | Requisição de save é rejeitada pelo servidor (422). |
| 6 | `tab.screenshot()` da mensagem de erro. | `[data-testid="editor-mensagens"]` (ou equivalente) exibe **uma única string em pt-BR** (padrão `api.ts` da F3 — nunca um objeto JSON cru, nunca múltiplas mensagens concatenadas sem tratamento) descrevendo o problema de integridade da tag do `pid`. |
| 7 | Reverter o estado da tag (recriar ou devolver a direção original) para não deixar o ambiente de teste sujo para os cenários seguintes e para a L2. `tab.click`/`tab.fill` conforme necessário na tela de Tags. | Tag restaurada; um novo salvar do flow (repetir passo 5) volta a funcionar sem 422. |

**Evidência:** `B-F4-04-passo01.png` a `B-F4-04-passo06.png` (o passo 7 de limpeza não precisa de evidência — não é parte do cenário sob teste, é housekeeping do ambiente).

---

### B-F4-05 — Minors m4: vírgula/ponto, "Aplicar" fecha, booleano de Script, EU nas portas com fonte, grade sem sobreposição

**Objetivo:** confirmar o fechamento dos itens do débito m4 (spec F4 §8) nas superfícies afetadas. **Emenda de 2026-08-05:** o item "EU nas portas" fica restrito às portas que têm fonte de EU (Leitura/Escrita OPC pela tag; MPC pelo config); Script/TFS ficam diferidos para F5/F6 por decisão do usuário (nenhuma fonte de EU existe hoje nesses blocos e criá-la exigiria schema novo fora de qualquer spec F1-F4 — apurado na tarefa 4.1).
**Rastreabilidade:** spec F4 §8 tabela, linha `m4` · plano F4a tarefa 0.7 (m1 + m4 de vírgula/ponto, booleano, grade, Aplicar) e tarefa 4.1 (EU nas portas com fonte, mesma leva das portas dinâmicas do MPC).
**Pré-condições:** flow com pelo menos 1 nó MPC configurado (reusa o estado de B-F4-04), 1 nó TFS e 1 nó Script já existentes no mesmo flow ou em flow auxiliar — se o flow de teste dos cenários anteriores não tiver TFS/Script, criar um flow auxiliar mínimo só para este cenário (mais barato que forçar os 5 blocos no mesmo flow).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Abrir o modal de um campo numérico do MPC (ex.: `du_max` na aba Restrições & Limites, ou um parâmetro SOPDT na aba Modelos) e digitar um valor com **vírgula**: `tab.fill(seletor_campo, "5,5")`. | Campo aceita a vírgula sem erro de formato (parse client-side interpreta `,` como separador decimal). |
| 2 | Limpar e digitar o mesmo campo com **ponto**: `tab.fill(seletor_campo, "5.5")`. | Campo aceita igualmente; ambos os formatos resultam no mesmo valor interno (verificável lendo o valor pós-parse, se exposto, ou pela ausência de erro em ambos os casos). |
| 3 | Repetir passos 1-2 em um campo numérico do modal TFS (`CamposTfs.tsx`, ex. parâmetro `K` de uma célula habilitada). | Mesmo comportamento — vírgula e ponto aceitos (débito m4 cobre TFS, não só MPC). |
| 4 | Clicar em "Aplicar" do modal MPC (ou TFS) sem fechar manualmente: `tab.click('[data-testid="config-aplicar"]')` (ou testid equivalente do modal MPC). | Modal fecha sozinho via `close()` explícito — `tab.waitFor` com estado "oculto" do `<dialog>` confirma; não é preciso um segundo clique em "Cancelar"/"Fechar" para o modal sumir. |
| 5 | Abrir o modal de um nó Script existente com pelo menos 1 saída booleana configurada (`OUTx` alimentando uma porta ligada a entrada booleana, ou inspecionar o valor ao vivo da porta com o flow rodando). `tab.screenshot()` do valor exibido na porta do nó Script no canvas. | Valor booleano exibido como **booleano** (ex. "true"/"false" — **nunca** "1"/"0", "1.0"/"0.0" nem outro número cru: exibir número era exatamente o bug m4; Regra do Canal Redundante). |
| 6 | `tab.screenshot()` de um nó com tag (Leitura/Escrita OPC) e do nó MPC no canvas, focando as portas. | Porta com **fonte de EU** exibe a EU ao lado do valor (Regra do Número Tabular): Leitura/Escrita OPC usam a EU da tag; o nó MPC rotula cada porta como `nome (EU)` a partir do config. **Script e TFS ficam fora deste assert** — emenda de 2026-08-05: apurou-se na tarefa 4.1 que esses blocos não têm fonte de EU alguma (nem no config, nem no `PortValue` do barramento) e criá-la exigiria campo novo de schema não especificado em nenhuma spec F1-F4; por decisão do usuário o item "EU nas portas de Script/TFS" do débito m4 fica **diferido para F5/F6** e o roteiro não o cobre. |
| 7 | Arrastar um novo bloco qualquer (ex. `opc_read`) da paleta para o canvas já com nós existentes ocupando posições no topo-esquerda por inserção anterior: `tab.drag('[data-testid="paleta-opc_read"]', {x, y})` sem especificar posição manual (usar o fluxo padrão de clique simples de inserção, se a paleta oferecer inserção por clique além de arraste). | Novo nó aparece em um **slot livre da grade** (posição calculada, não sobreposto a nenhum nó existente) — a inserção não usa mais `nodes.length` como índice de posição (débito m4). Verificável via `tab.evaluate` comparando o bounding box do novo nó contra os já existentes (sem interseção). |
| 8 | `tab.screenshot()` do canvas com o novo nó em posição livre. | Confirma visualmente ausência de sobreposição. |

**Evidência:** `B-F4-05-passo01.png` a `B-F4-05-passo08.png`.

---

### B-F4-06 — Hot-swap: editar config do MPC com flow rodando não para o flow

**Objetivo:** confirmar que editar e salvar a config de um bloco MPC com o flow em execução preserva a execução (canvas continua vivo, lâmpada/valores atualizando), sem parada visível.
**Rastreabilidade:** ADR-011 · decisão A-11 (spec F4 Anexo A) · RF-304 · spec F4 §4.7 (hot-swap ⇒ shed a LOCAL, asserção de shed em si é L2).
**Pré-condições:** flow com bloco MPC configurado e válido (reusa B-F4-04) **e** um bloco TFS fechando a malha da MV/CV — se o flow de teste ainda não tiver o TFS, montá-lo agora (mesmo padrão de malha fechada dos cenários E2E-F4 do L2, mas aqui é só para observar o canvas vivo, não para validar convergência numérica). Deploy feito **antes** deste cenário, via UI: `/engenharia/flows`, `tab.click('[data-testid="flow-deploy"]')` na linha do flow, aguardar `[data-testid="flow-desired"]` confirmar "Rodando" (ou rótulo equivalente do estado publicado).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Abrir o editor do flow rodando: `tab.click('[data-testid="flow-abrir"]')`. `tab.screenshot()` do cabeçalho do canvas. | `[data-testid="canvas-estado"]` mostra lâmpada de estado "rodando" (verde mutado, exclusivamente na lâmpada — DESIGN.md, nunca verde em área grande); `[data-testid="canvas-vivo"]` mostra contagem de varredura crescendo. |
| 2 | Abrir o modal do bloco MPC (workaround dblclick, regra 4) com o flow ainda rodando. | Modal abre normalmente — não há bloqueio de edição por flow rodando (editar rodando é o caminho feliz, ADR-011). |
| 3 | Editar um peso na aba Pesos (`w` da CV): `tab.fill(seletor_peso_cv, <novo_valor>)` — valor diferente do atual, ainda válido (`weight>0`). `tab.screenshot()`. | Campo aceita o novo valor sem erro. |
| 4 | Salvar: `tab.click('[data-testid="config-aplicar"]')` seguido de `tab.click('[data-testid="flow-salvar"]')`. | Save bem-sucedido (sem erro em `[data-testid="editor-mensagens"]`). |
| 5 | Aguardar 1-2 ciclos de `Ts_mpc` (usar a chamada global `wait(ms)` com um valor calculado a partir do `Ts_mpc` exibido na aba Horizontes antes de fechar o modal, ou um valor fixo conservador se o `Ts_mpc` não estiver mais visível). `tab.screenshot()` do cabeçalho do canvas. | `[data-testid="canvas-estado"]` **continua** mostrando "rodando" — sem transição visível para parado/falha; `[data-testid="canvas-vivo"]` continua incrementando a contagem de varredura (o flow nunca parou). |
| 6 | `tab.screenshot()` dos valores das portas do bloco MPC e do TFS no canvas, antes e depois do save (comparação visual entre o screenshot do passo 1 e este). | Valores de porta seguem atualizando (não congelados) — a malha continua viva, coerente com "worker novo + shed a LOCAL" (o bloco não some do canvas, só troca de modo internamente; a asserção **numérica** do shed em si, e a confirmação de que o modo caiu para LOCAL, é do cenário `E2E-F4-10` do L2 — este roteiro L3 só confirma que a UI não trava nem indica parada). |

**Evidência:** `B-F4-06-passo01.png` a `B-F4-06-passo06.png`.

**Nota explícita:** este cenário **não** assere a transição de modo REMOTO→LOCAL em si (não há superfície de UI para modos até a F5 — spec F4 §7.5, "sem superfície de operação"). O shed determinístico por hot-swap é responsabilidade do `E2E-F4-10` (L2), que lê o payload `mpc.state` via WS. Aqui o critério é puramente visual: o canvas não trava, não mostra estado de falha, e os valores seguem vivos.

---

### B-F4-07 — Reabrir o modal de um bloco MPC salvo: hidratação completa (extra)

**Objetivo:** confirmar que reabrir o modal de um bloco MPC já salvo carrega corretamente todas as 7 abas com os dados persistidos — variáveis, matriz, horizontes derivados, limites, pesos e o `pid` da MV, quando presente. Lacuna real identificada pela leitura da spec/planos: nenhum dos 6 cenários mínimos reabre um bloco já salvo para conferir a hidratação; sem esse cenário, um bug de hidratação (comum em modais com estado derivado de `graph_json`) passaria despercebido até a operação manual do usuário.
**Rastreabilidade:** RF-607 · spec F4 §7.3 (modal 7 abas) · ADR-011 (editar rodando/salvo é o caminho normal, não um caso especial).
**Pré-condições:** bloco MPC salvo com sucesso e com um `pid` completo configurado em pelo menos uma MV (reusa o estado alcançado no meio de B-F4-04, antes da remoção da tag — ou reconfigura um `pid` válido especificamente para este cenário, já que B-F4-04 deixa a tag revertida ao final).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Fechar o modal (se aberto) e recarregar a página do editor (`tab.evaluate('location.reload()')` ou navegação equivalente) para garantir que o estado vem do `graph_json` persistido, não de estado React em memória. | Editor recarrega; nó MPC aparece com as mesmas portas de antes (B-F4-04 passo 1-3). |
| 2 | Reabrir o modal (workaround dblclick). Navegar pelas 7 abas em sequência, com `tab.screenshot()` em cada uma: Geral, Variáveis, Modelos, Horizontes, Restrições & Limites, Pesos, Resumo. | Cada aba mostra os valores salvos: nome/multiplicador (Geral); MV+CV+DV com os nomes/EUs digitados em B-F4-02, `pid` da MV com os selects de tag/`target_mode`/`mode_values` preenchidos (Variáveis); par habilitado com os 4 parâmetros SOPDT de B-F4-03 (Modelos); TSS e `Ts_mpc`/`Np`/`Nc` coerentes com o último valor salvo (Horizontes); `du_max`/faixas conforme editado em B-F4-05, se aplicável (Restrições & Limites); peso editado em B-F4-06 (Pesos); Resumo sem erros bloqueantes (Resumo). |
| 3 | Fechar sem alterar nada (`tab.click('[data-testid="config-cancelar"]')` ou testid equivalente). | Modal fecha; nenhuma requisição de save disparada (edição de leitura, sem `PUT`). |

**Evidência:** `B-F4-07-passo01.png` a `B-F4-07-passo03.png` (o passo 2 gera 7 screenshots, um por aba — nomear `B-F4-07-passo02a.png` a `B-F4-07-passo02g.png`, na ordem Geral→Resumo, mantendo o prefixo do passo).

---

## 5. O que este roteiro NÃO cobre

- **Modos LOCAL/REMOTO/MAN/AUTO, bumpless, overrun, shed automático, precedência Restrição×CV** — cobertos exclusivamente pelo L2 (`E2E-F4-01` a `E2E-F4-10`, spec F4 §9.2), porque **não existe superfície de UI para operar modos até a F5** (spec F4 §7.5: "sem superfície de operação — modos/SP/MV não aparecem no editor"). Nenhuma tentativa deste roteiro de simular clique em um comutador de modo é válida — esse controle não existe no editor da F4.
- **Malha real com PLC** — fora de escopo de qualquer camada do gate desta fase; toda malha fechada usa o opcsim (simulador OPC-UA in-process), nunca hardware real.
- **Carga/desempenho do solver** (RNF-02, teste `slow` do plano F4a tarefa 2.4) — é teste de mesa pura (pytest), não tem superfície de browser.
- **REST `/api/operate`** — sem UI cliente na F4 (decisão A-2); testado só via L2 (`E2E-F4-08`) e pytest de API.

---

## 6. Ordem de gate

Tabela de execução da rodada de gate completa (plano F4b, Etapa 5, tarefa 5.1). Qualquer vermelho em qualquer linha interrompe a rodada: corrigir, e reiniciar a rodada inteira desde `down -v` — nunca pular direto para a camada seguinte com uma pendência aberta.

| Ordem | Camada | Comando / ação | Critério de passagem |
|---|---|---|---|
| 1 | Testes de workspace (pytest + ruff) | `uv run pytest` (workspace, incl. `-m slow` uma vez) + `uv run ruff check . && uv run ruff format --check .` | 100% verde, zero warning de lint |
| 2 | Frontend build/unit | `cd frontend && npm run build && npm run test:unit` | build sem erro de tipo; testes puros verdes |
| 3 | L1 — smoke | `OTTIMA_E2E=1 bash deploy/smoke.sh` (flow-runtime recém-subido, `flows={}`) | smoke completo, incl. campos novos do `/health` (§4.10 da spec) |
| 4 | L2 — 34 cenários | `uv run pytest -m e2e tests/e2e -v` | 34/34 verdes (5 F1 + 9 F2 + 10 F3 + 10 F4) |
| 5 | Playwright F1 | `cd frontend && npm run e2e` (credenciais `E2E_ADMIN_USERNAME`/`E2E_ADMIN_PASSWORD` inline) | regressão F1 verde; **serializado** com a L2 (nunca simultâneo) |
| 6 | **L3 — este roteiro** | Execução manual do controlador com a tool `browser`, cenários B-F4-01 a B-F4-07, screenshot por passo | todos os cenários verdes, evidências completas no diretório da seção 3 |

**Encerramento da fase:** só depois da linha 6 verde na mesma rodada das linhas 1-5, com `.superpowers/sdd/F4-mpc/RELATORIO-GATE-F4.md` documentando a rodada (padrão herdado da F3), a fase F4 pode ser dada como pronta para revisão de merge (plano F4b, tarefa 5.2).
