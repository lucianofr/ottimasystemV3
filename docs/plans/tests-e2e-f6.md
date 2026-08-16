# Roteiro L3 — Testes E2E de browser (Fase F6 — Portabilidade & hardening)

**Status:** normativo para o gate da F6 · draft do agente e2e-runner revisado e aceito pelo controlador · 2026-08-07.
**Fase:** F6 (PRD §8) — **última fase da v1** · export/import de projeto, certificados, pendência de segredo, EU nas portas de Script/TFS, faceplate de DV com barra, débitos de frontend da F5, RBAC.
**Quem executa:** o **agente controlador**, segurando a tool nativa `browser` do harness omp. Subagentes NÃO têm acesso a essa tool (bloqueada por design) — nenhum passo deste roteiro pode ser delegado a subagente.
**Quando roda:** plano F6c, Etapa 6, tarefa 6.1, **linha 7 da ordem de gate** (§6 abaixo) — depois de L1, L2 (46 cenários), `-m rnf09` (6 cenários) e Playwright F1, todos na mesma rodada.

**Fontes normativas** (precedência ADR > PRD > spec > plano; ADRs sempre vencem em conflito):
- `docs/adr/ADR-009` (watchdog, herdado), `ADR-010` (modos, herdado), `ADR-011` (hot-swap, herdado), `ADR-012` (portabilidade de engenharia), `ADR-016` (predição volátil, herdado), `ADR-018` (escopo restrito do Script), `ADR-020` (log de eventos sem ACK, herdado), `ADR-021` (certificados), `ADR-022` (suíte MPC↔TFS).
- `docs/PRD.md` v1.4 §8-F6 (aceite da fase: export/import limpo entre instalações, re-informando segredos, gestão de certificados, health/heartbeats, suíte MPC↔TFS verde).
- `docs/specs/F6-portabilidade-hardening.md` — inteira; em especial §2 (contrato de portabilidade, `tag_ref`), §3.1/§3.2 (export/import), §4.1/§4.2 (EU nas portas, `range` da DV), §6 inteira (frontend: §6.0 primitivos de arquivo, §6.1 Projetos, §6.2 certificados, §6.3 pendências, §6.4 EU nas portas, §6.5 faceplate de DV, §6.6 os 6 débitos da F5), §9.2 (tabela L3, B-F6-01..13), §9.3 (precondições), Anexo A (decisões A-1..A-16).
- `docs/plans/F6a-portabilidade-dados.md` (backend/schema — export/import, `tag_ref`, `output_eu`, `DvVar.range`, `/api/health`).
- `docs/plans/F6b-superficies.md` (frontend — `/engenharia/projetos`, certificados, pendências, EU nas portas, faceplate de DV, os 6 débitos da F5; regra global item 2 fixa os prefixos de testid da fase: `proj-*`, `import-*`, `cert-*`, `conn-pendencia*`).
- `docs/plans/F6c-suite-e-guia.md` (suíte RNF-09, cenários E2E-F6, ambiente L3 — tarefa 4.1 estende `scripts/setup-l3.py`, tarefa 4.2 é este roteiro).
- `docs/plans/tests-e2e-f4.md` §2 — modelo estrutural e armadilhas da tool `browser`, herdadas integralmente (regras 1-8, ver §2 abaixo).
- `CLAUDE.md` §Comandos (comandos canônicos do stack e precondições do gate).
- `DESIGN.md` (§Colors/Typography/Layout/Shapes + Regra da Plaqueta, Regra do Canal Redundante, Regra do Número Tabular, Regra da Cor Anormal, Regra do Estado Publicado).

## Regra de ferro

**A fase F6 — e a v1 inteira — só é considerada pronta quando L1 + L2 (46 cenários — 41 herdados de F1-F5 + `E2E-F6-01/02/03/05/06`) + `-m rnf09` (6 cenários — `E2E-F4-03/05/06/10` + `E2E-F6-05/06`) + Playwright F1 + este roteiro inteiro estiverem verdes, na mesma rodada** (plano F6c, Etapa 6, tarefa 6.1). Qualquer vermelho em qualquer camada invalida a rodada inteira: corrige, e a rodada completa roda de novo desde `down -v` — **`down -v` só com autorização explícita do usuário e dump prévio do banco** (spec F6 §9.3); **nunca** `docker compose ... prune`; nunca se re-executa só o cenário que falhou.

---

## 1. Precondições de ambiente

Copiadas de `CLAUDE.md` §Comandos e `docs/specs/F6-portabilidade-hardening.md` §9.3 (que herda integralmente o protocolo F3/F4/F5). Válidas para a rodada de gate inteira, não só para este roteiro.

1. **Stack composta com os DOIS arquivos compose**:
   ```bash
   cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d
   ```
   Sem o override `e2e`, o opcsim e o Redis de teste não ficam acessíveis do host.
2. **Rebuild do bundle novo do frontend** antes de qualquer passo (o browser precisa do bundle com `/engenharia/projetos`, a chapa de certificados, a coluna de pendências, `output_eu` no editor e a barra de DV — nada disso existe no bundle da F5; entregue pelo plano F6b):
   ```bash
   cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --no-deps frontend
   ```
3. **Frontend acessível em `http://localhost:8080`** (proxy do nginx do compose).
4. **Credenciais SEMPRE inline de `deploy/.env`** — ler o arquivo, extrair usuário/senha do admin seed (`OTTIMA_ADMIN_USERNAME`/`OTTIMA_ADMIN_PASSWORD`) e digitá-los diretamente no passo de login ou usá-los num comando `curl` pontual. Nunca `export` em shell persistente da sessão.
5. **L2 e Playwright são serializados** — nunca rodam juntos. Este roteiro (L3) roda depois de ambos terminarem, contra o mesmo compose já de pé.
6. **L1 exige flow-runtime recém-subido**: se a L2 já rodou antes deste roteiro, `docker compose -f docker-compose.yml -f docker-compose.e2e.yml restart flow-runtime` antes do L1 — não antes deste roteiro L3 (que quer um flow-runtime já usado, com `L3-flow-operacao` deployável/hot-swappável).
7. **Ambiente L3 por `uv run python scripts/setup-l3.py`** (idempotente — plano F6c tarefa 4.1, estende o script sem alterar o que ele já entregava nas fases F3-F5):
   - **Projeto ativo continua `L3 F5 operacao`** — flow `L3-flow-operacao`, bloco `mpc1` (URL do handoff F5: `/operacao/<flowId>/mpc1`), fechando malha com um bloco TFS (herdado do gate F4, RNF-09 sem hardware real).
   - **Projeto extra inativo `L3 F6 portabilidade`**, criado pela extensão da F6, com três conexões (material das pendências de B-F6-07 e do `tag_ref` de B-F6-05):
     - uma conexão `auth_mode: certificate`, `security_policy: none`;
     - uma conexão segura **sem senha reinformada** (`security_policy: basic256sha256`, `security_mode: sign_and_encrypt`, `auth_mode: user_password`, sem `auth_password`) — **requisito deste roteiro para a tarefa 4.1**: esta conexão precisa apontar para o mesmo endpoint de `opcsim-l3` (`OPCSIM_URL = "opc.tcp://opcsim:4840"`, constante confirmada em `tests/e2e/conftest.py:88`), porque B-F6-04 exercita esta conexão subindo de verdade depois de confiada — o opcsim do compose de teste já serve `basic256sha256` no mesmo container/porta que o modo anônimo (`deploy/docker-compose.e2e.yml:10-14`: "um único container serve aos três modos");
     - duas conexões com **tag homônima** (mesmo nome de tag em conexões diferentes) — material do `tag_ref` como objeto, exercitado em B-F6-05.
   - **Flow `L3-flow-arquivo`** nesse mesmo projeto extra, criado pela mesma extensão (plano F6c tarefa 4.1 item (d)), **parado** (`desired_state: stopped`, nunca deployado — o projeto é inativo e nada nele escreve em planta): um bloco **`opc_read` apontando para uma das tags homônimas** (material determinístico do `tag_ref` objeto em B-F6-05) e um bloco **Script com código conhecido `OUT1 = 0.0`** (material da lista de blocos Script da prévia de import em B-F6-06). Sem esse flow, os dois cenários teriam de improvisar setup pela UI.
   - **Usuário operador `operador_e2e` / `OperadorE2E#2026` já criado pelo script** (diferente do gate F5, aqui não há passo `curl` manual de criação — a tarefa 4.1 do F6c mantém essa entrega).
   - Papel **admin** logado inicialmente (necessário para Projetos, certificados, export/import e para o passo de `curl` de B-F6-04).
8. **Certificado real do servidor opcsim materializado em disco pelo próprio compose**, sem passo manual: `deploy/e2e-certs/opcsim.der` — volume montado em `docker-compose.e2e.yml:15-17` a partir de `--cert-dir /certs-sim` (`tests/opcsim/src/opcsim/server.py:104-123`, `_generate_certificate`; caminho confirmado também em `tests/e2e/conftest.py:91`, `OPCSIM_CERT`). É o arquivo que B-F6-04 sobe via `tab.uploadFile` para confiar no certificado do servidor — **não** confundir com o `.der` do certificado de aplicação (esse é gerado e baixado em B-F6-03, é outro arquivo, outra direção de confiança).
9. **Diretório de evidências criado antes do primeiro passo**:
   ```bash
   mkdir -p .superpowers/sdd/F6-portabilidade/evidencias-l3
   ```

---

## 2. Regras de execução com a tool `browser`

Armadilhas confirmadas empiricamente nos roteiros L3 de F4/F5 (`docs/plans/tests-e2e-f4.md` §2, `docs/plans/tests-e2e-f5.md` §2) — herdadas aqui **integralmente** como regras obrigatórias (1-8), mais as quatro que a F6 exige (9-12). Toda ação de UI deste roteiro segue estas regras sem exceção.

1. **`tab.click`/`tab.fill`/`tab.waitFor*` aceitam APENAS seletores string** (CSS ou texto) — nunca objetos de referência de snapshot. Preferir `[data-testid="..."]`; onde o testid ainda não existe no código (todas as superfícies novas da F6 — planos F6b já escritos, código ainda não implementado no momento deste draft — ver notas "provável" em cada cenário), usar seletor por texto visível ou `role`+nome acessível, com o CSS como plano B documentado no passo. Convenção confirmada nos planos F6b (regras globais, item 2): `proj-*`, `import-*`, `cert-*`, `conn-pendencia*`.
2. **`wait(ms)` é uma chamada global** da tool — não existe `tab.waitFor(ms)`. Esperas por tempo fixo (janela de confirmação 3×Ts_mpc, limiar de congelamento, boot de hot-swap, tique de 5 s do relógio de alarmes) usam a chamada `wait`; esperas por condição usam `tab.waitFor` com seletor/estado.
3. **`tab.drag(from, to)` recebe `{x, y}` como dois argumentos posicionais**, não um único objeto com dois pares de coordenadas. Este roteiro **não usa arraste** — a paleta do editor de flow aceita inserção por clique simples (`FlowPalette.tsx:31-33`, "clique adiciona no centro do canvas"), preferida em todos os cenários que inserem bloco novo (B-F6-09); regra mantida ativa do harness para o caso de alguma legenda ganhar interação de arraste em iteração futura.
4. **`tab.doubleClick` NÃO EXISTE.** O duplo-clique que abre o modal de configuração de bloco (`onNodeDoubleClick` do React Flow, `FlowEditorPage.tsx:459-461`) é disparado via `tab.evaluate`:
   ```js
   (() => {
     const el = document.querySelector('.react-flow__node[data-id="SELETOR_DO_NO"]');
     el.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
   })()
   ```
   `bubbles: true` é obrigatório. `.react-flow__node[data-id="..."]` é o wrapper de nó confirmado da biblioteca `@xyflow/react` (import direto em `FlowEditorPage.tsx:1-9`), não um testid próprio do app.
5. **`tab.select` exige o `value` do `<option>`, não o texto visível.** Usado nos filtros de `/eventos` (`eventos-filtro-severidade`, `eventos-filtro-origem` — confirmados, `EventsPage.tsx:119-146`), no seletor de janela do trend de operação (`operate-trend-window`, confirmado `TrendOperacao.tsx:500`) e em qualquer `<select>` novo do editor (`kind` de variável MPC, `config-n-outputs` do Script — confirmado `ModalConfigBloco.tsx:82`) — o `value` é sempre o identificador técnico, nunca o rótulo pt-BR.
6. **Refs de `ariaSnapshot` são reusadas entre snapshots e quebram laços** (ex.: percorrer as N faceplates de variável, as linhas de pendência da tabela de Conexões, os itens da legenda do trend). Marcar o elemento-alvo no DOM antes de agir e clicar por seletor CSS estável, não por ref reaproveitada — mesmo padrão de F4/F5 §2 regra 6, com `data-var-id`/`data-id` já presentes em vários componentes confirmados (`faceplate-*` tem `data-var-id`, `mpc-var-row-*` tem `data-var-id`, itens de legenda têm `data-var-id`).
7. **Screenshot por passo relevante**: `tab.screenshot()` imediatamente após toda ação que muda o DOM de forma observável. Salvar no diretório de evidências (seção 3) com o nome exato do passo — nunca sobrescrever um screenshot de um passo anterior do mesmo cenário.
8. **Asserções sobre o trend uPlot nunca comparam pixels/canvas** — leem os dados que alimentam o gráfico. Via preferida: `tab.evaluate` chamando `fetch('/api/history/mpc?...')` com o token de `localStorage.getItem('ottima.token')` no header `Authorization`, e inspecionar `t`/`v`/`sp`/`auto` do JSON diretamente.
9. **[NOVA] `tab.press(sel, 'Enter')` NÃO EXISTE.** Confirmar/submeter um campo por Enter (ex.: `faceplate-mv-input-*`/`faceplate-sp-input-*`, que confirmam no `onBlur` mas cujo teclado também dispara `Enter`, `FaceplateVariavel.tsx:256-257`) usa `page.focus(sel)` seguido de `page.keyboard.press('Enter')` — nunca uma chamada `tab.press` inexistente.
10. **[NOVA] `tab.evaluate` NÃO enxerga `document` do escopo externo do `run`.** Todo código passado a `tab.evaluate` precisa ser **autocontido** — nenhuma variável de fora do corpo da função avaliada é capturada; qualquer dado externo (token, id, caminho) entra por interpolação de string no momento de montar o script, nunca por closure.
11. **[NOVA] Upload de arquivo**: `tab.uploadFile` contra o `<input type="file">` oculto que os botões de upload acionam (§6.0-2 da spec: sem `FormData`, corpo binário cru), com o arquivo **materializado em disco antes** por um comando de shell fora da tool `browser`:
    - o certificado do **servidor** (B-F6-04) já está materializado pelo compose em `deploy/e2e-certs/opcsim.der` (§1 item 8) — nenhum passo extra de shell é necessário além do que o compose já fez no boot;
    - o certificado da **aplicação** (se algum passo precisar re-subir o próprio `.der` baixado, o que este roteiro não faz) viria de `GET /api/certificates/app/export`;
    - o **arquivo de projeto** (B-F6-06/08) vem do botão Exportar (baixado pelo próprio `browser`, materializado no diretório de download da sessão) ou de um `curl` de setup quando o teste precisa de uma cópia corrompida — nesse caso o `curl`/edição do JSON roda fora da tool `browser`, e o arquivo resultante entra por `tab.uploadFile` normalmente.
12. **[NOVA] Download**: o app baixa via `fetch` + `Blob` + `URL.createObjectURL` (`baixarArquivo`, spec §6.0-3) — **não** um `<a href>` simples, porque o app autentica por header `Authorization`, que uma navegação direta de âncora não carrega. A **conferência do conteúdo baixado** (tag_ref, ausência de segredos, código de Script na prévia) é feita por `tab.evaluate` chamando a **mesma rota** com o token de `localStorage.getItem('ottima.token')` — nunca pelo sistema de arquivos do host, que não tem acesso garantido ao diretório de downloads do browser controlado pela tool:
    ```js
    fetch('/api/projects/<id>/export', {
      headers: { Authorization: `Bearer ${localStorage.getItem('ottima.token')}` },
    }).then((r) => r.json())
    ```

---

## 3. Evidências

Um screenshot por passo relevante (regra 7 acima), salvo em:

```
.superpowers/sdd/F6-portabilidade/evidencias-l3/B-F6-XX-passoNN.png
```

`XX` = número do cenário com dois dígitos (`01`..`13`); `NN` = número do passo, também com dois dígitos, na ordem da tabela do cenário. Nomeação obrigatória e literal.

---

## 4. Cenários

**Nota sobre selectors "prováveis":** o código das superfícies novas da F6 (`/engenharia/projetos`, chapa de certificados, coluna de pendências, `output_eu` no editor, faceplate de DV com barra) ainda não existe no branch de trabalho no momento deste draft — só os planos `docs/plans/F6a-portabilidade-dados.md`/`F6b-superficies.md`/`F6c-suite-e-guia.md` (escritos, não implementados). Todo `data-testid` citado abaixo que não conste da lista de testids **confirmados nesta sessão** (login, nav, `conn-*`, `tag-*`, `flow-*`, `operate-*`, `faceplate-*`, `eventos-*`, `annunciator*`, `mpc-*`, `config-*`, `paleta-*` — todos lidos do código real de `frontend/src`) é uma previsão que respeita a convenção de prefixo já normativa nos planos F6b (`proj-*`, `import-*`, `cert-*`, `conn-pendencia*`) e deve ser confirmada/ajustada contra o código real antes da execução — o texto pt-BR visível é a fonte de verdade quando o testid não bater.

**Mapa de execução.** A ordem abaixo **não é a ordem numérica dos IDs** (que é a da tabela §9.2-L3 da spec, preservada nos títulos de seção para rastreabilidade) — é a ordem de **execução no browser**, escolhida para que cada cenário deixe o ambiente no estado que o próximo precisa (projeto ativo, certificado de aplicação existente ou não, pendências abertas ou resolvidas), sem nenhuma manobra destrutiva fora do previsto pela spec:

| Ordem de execução | Cenário |
|---|---|
| 1 | B-F6-01 |
| 2 | B-F6-09 |
| 3 | B-F6-10 |
| 4 | B-F6-11 |
| 5 | B-F6-12 |
| 6 | B-F6-02 |
| 7 | B-F6-07 |
| 8 | B-F6-03 |
| 9 | B-F6-04 |
| 10 | B-F6-05 |
| 11 | B-F6-06 |
| 12 | B-F6-08 |
| 13 | B-F6-13 |

Motivo da ordem: B-F6-09..12 exercitam a tela de operação e o editor do flow `L3-flow-operacao`, que só existem enquanto **`L3 F5 operacao`** é o projeto ativo — rodam **antes** de B-F6-02 (Ativar), que troca o projeto ativo para `L3 F6 portabilidade` e não volta atrás. B-F6-07 (pendências) precisa observar o predicado `needs_app_certificate` **ainda aberto** nas duas conexões novas — por isso roda **antes** de B-F6-03 gerar o certificado de aplicação, que fecha esse predicado para a instalação inteira. B-F6-04 depende do certificado de aplicação já existir (§3.2-8: `security_policy != none` também exige `app_cert.exists`, porque o opc-worker usa o certificado da aplicação como material do canal seguro do lado cliente) — por isso roda **depois** de B-F6-03.

---

### B-F6-01 — `/engenharia/projetos`: CRUD, exclusão do ativo recusada

**Objetivo:** confirmar a tabela de projetos (nome/descrição/Ativo/ações), criar/renomear/excluir por admin, e que excluir o projeto ativo é recusado pelo servidor (409) e a recusa aparece na tela.
**Rastreabilidade:** RF-101 · spec F6 §6.1 (decisão A-13) · plano F6b tarefa 2.1 (`ProjectsPage.tsx`/`ProjectForm.tsx`, testid `nav-projetos` e `proj-new`/`proj-edit`/`proj-delete` — confirmados no texto da tarefa 2.1, componente ainda não implementado no branch de trabalho).
**Pré-condições:** login admin (credenciais de `deploy/.env`); ambiente L3 já criado por `setup-l3.py` (dois projetos: `L3 F5 operacao` ativo, `L3 F6 portabilidade` inativo — §1 item 7).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Login: `tab.fill('[data-testid="login-username"]', <usuário admin>)`, `tab.fill('[data-testid="login-password"]', <senha>)`, `tab.click('[data-testid="login-submit"]')`. `tab.click('[data-testid="nav-projetos"]')` (provável, `AppShell.tsx`/`router.tsx` ainda sem a rota `/engenharia/projetos`, plano F6b tarefa 2.1 — "no início" da nav de engenharia). | Redireciona para fora de `/login`; nav mostra "Projetos" como primeiro item do grupo de engenharia; URL `/engenharia/projetos`. |
| 2 | `tab.screenshot()` da tabela. | Duas linhas: `L3 F5 operacao` com lâmpada "Ativo" em **Azul Industrial** (`text-accent`, nunca Verde Rodando — DESIGN §Colors, decisão UX-10) + ícone + rótulo "Ativo" ao lado (nunca só cor); `L3 F6 portabilidade` sem a lâmpada. **Nota sobre o estado "nenhum projeto cadastrado" (spec §6.1-7, UX-09):** não é exercitado por este ambiente — `setup-l3.py` sempre entrega ≥2 projetos como precondição do resto do roteiro (§1 item 7), e excluir ambos para observar o estado vazio destruiria o material dos cenários seguintes. Registrado como lacuna de cobertura, não como bug — coberto por `ProjectsPage.check.ts` (F6b tarefa 2.1) e por leitura de código (o estado vazio renderiza quando `useProjects().data.length === 0`). |
| 3 | `tab.click('[data-testid="proj-new"]')`; preencher nome "L3 F6 CRUD teste" no formulário inline (mesmo padrão de `FlowForm`); submeter. `tab.screenshot()`. | Nova linha aparece na tabela, sem lâmpada "Ativo". |
| 4 | `tab.click('[data-testid="proj-edit"]')` na linha do projeto recém-criado (marcar por `data-alvo` conforme regra 6 do §2, já que há 3 linhas agora); alterar a descrição; submeter. `tab.screenshot()`. | Descrição atualizada refletida na tabela sem reload. |
| 5 | `tab.click('[data-testid="proj-delete"]')` na linha de `L3 F5 operacao` (o **ativo**); confirmar a exclusão. `tab.screenshot()`. | Recusa **409** exibida na tela em pt-BR (mensagem de `projects.py:70-72`, "Não é possível excluir o projeto ativo" ou equivalente); a linha de `L3 F5 operacao` continua na tabela; a lâmpada "Ativo" não some. |
| 6 | `tab.click('[data-testid="proj-delete"]')` na linha do projeto de teste (não-ativo); confirmar. `tab.screenshot()`. | Linha de teste removida da tabela; `L3 F5 operacao` e `L3 F6 portabilidade` continuam intactos — precondição para os cenários seguintes preservada. |

**Evidência:** `B-F6-01-passo02.png` a `B-F6-01-passo06.png` (passo 1 não gera screenshot próprio, mesmo padrão de login em F4/F5).

---

### B-F6-09 — EU nas portas de Script/TFS: declarar no modal, ver unidade no canvas ao vivo

**Objetivo:** confirmar que o modal de TFS e de Script ganham campo de EU por porta de saída (TFS: `y1`/`y2` fixos; Script: `OUT1..OUTn`, acompanhando `n_outputs`), e que a unidade aparece ao lado do valor no canvas ao vivo.
**Rastreabilidade:** RF-511/521 · spec F6 §4.1 (decisão A-10, F6R-09) · §6.4 · plano F6a tarefa 4.1 (backend, `output_eu` em `ScriptConfig`/`TfsConfig`) · plano F6b tarefas 5.1 (`ModalConfigBloco.tsx`, campo controlado `config-n-outputs`) e 5.2 (unidade no canvas, `frontend/src/features/flows/nodes/*`).
**Pré-condições:** login admin ainda ativo (continuação de B-F6-01); projeto ativo `L3 F5 operacao`; flow `L3-flow-operacao` existente com bloco `mpc1` e um bloco TFS fechando a malha (herdado do handoff F4/F5), flow rodando ou parado (hot-swap funciona nos dois casos, ADR-011).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.click('[data-testid="nav-flows"]')`; `tab.click('[data-testid="flow-abrir"]')` na linha de `L3-flow-operacao`. `tab.screenshot()` do canvas. | Editor carrega; `[data-testid="canvas-vivo"]` (confirmado, `FlowEditorPage.tsx:145-151`) visível; nó TFS e nó `mpc1` presentes no canvas. |
| 2 | Duplo-clique via workaround (regra 4 do §2) no nó TFS: `document.querySelector('.react-flow__node[data-id="<id-do-tfs>"]')` → `dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))` (o `<id-do-tfs>` sai de um `tab.evaluate` prévio que lista `document.querySelectorAll('.react-flow__node')` e lê `data-id`/texto da plaqueta para identificar o TFS). | Modal abre: `[data-testid="config-modal"]` (confirmado, `ModalConfigBloco.tsx:204`). |
| 3 | Preencher os dois campos de EU fixos do TFS (`config-output-eu-y1`, `config-output-eu-y2`, prováveis — plano F6b tarefa 5.1: "TFS ⇒ dois campos fixos (y1, y2)") com "°C" e "%", respectivamente. `tab.screenshot()`. | Campos aceitam texto livre; nenhum erro de validação client-side (EU é opcional, §4.1-5). |
| 4 | `tab.click('[data-testid="config-aplicar"]')` (confirmado). `tab.click('[data-testid="flow-salvar"]')` (confirmado, `FlowEditorPage.tsx:408`). `tab.screenshot()` de `[data-testid="editor-mensagens"]` (confirmado, `:416`). | Nenhum erro de validação — o servidor aceita a chave `output_eu` (F6a tarefa 4.1 acrescenta `"output_eu"` a `_CONFIG_KEYS["tfs"]`, sem essa entrada o `422` de chave desconhecida dispararia). |
| 5 | Inserir um bloco Script novo por clique simples na paleta (regra 3 do §2): `tab.click('[data-testid="paleta-script"]')` (confirmado, `FlowPalette.tsx:26`). `tab.screenshot()` do canvas. | Novo nó Script aparece em slot livre da grade (débito m4-b, já fechado na F4), sem sobrepor os nós existentes. |
| 6 | Duplo-clique (mesmo workaround do passo 2) no nó Script novo. `tab.select('[data-testid="config-n-outputs"]', "1")` (confirmado `ModalConfigBloco.tsx:82`, agora controlado por F6b tarefa 5.1 — reduzir/aumentar `n_outputs` deve mostrar/esconder o campo de EU correspondente). `tab.screenshot()`. | Um campo `config-output-eu-OUT1` (provável) aparece, acompanhando `n_outputs = 1`. |
| 7 | Preencher `config-output-eu-OUT1` com "kg/h"; preencher `[data-testid="config-code"]` (confirmado, `ModalConfigBloco.tsx:96`) com `OUT1 = 1.0` (script trivial, sem ligação a nenhuma entrada — não perturba a malha MPC↔TFS). `tab.click('[data-testid="config-aplicar"]')`; `tab.click('[data-testid="flow-salvar"]')`. `tab.screenshot()`. | Salvo sem erro em `editor-mensagens`. |
| 8 | Com o flow rodando (ou aguardar `wait(5000)` + `tab.evaluate('location.reload()')` se precisar de um novo boot), `tab.screenshot()` focando o nó TFS e o nó Script no canvas. | Valor de cada porta de saída aparece em mono tabular (`process-value`) com a EU declarada ao lado, em Texto Secundário menor — mesmo tratamento das portas de OPC-Read/Write (DESIGN §Typography, Regra do Número Tabular). Entradas continuam sem EU própria (herdam da origem pela aresta, §4.1-5 — nenhuma aresta liga ao Script novo, então suas entradas, se houver, ficam sem unidade). |

**Evidência:** `B-F6-09-passo01.png` a `B-F6-09-passo08.png`.

---

### B-F6-10 — Faceplate de DV: com `range` (barra) e sem `range` (valor + EU); aba Variáveis sinaliza a ausência

**Objetivo:** confirmar que a aba Variáveis do modal MPC sinaliza a ausência de `range` na DV, que adicionar `range` faz o faceplate correspondente desenhar a barra vertical com escala (mesma convenção de MV/CV/Restrição), e que uma DV sem `range` continua mostrando só plaqueta + valor mono tabular + EU.
**Rastreabilidade:** RF-702 · spec F6 §4.2 (decisão A-11, RFC-16) · §6.5 · plano F6a tarefa 4.2 (schema `DvVar.range` + projeção em `GET /api/operate/mpcs`) · plano F6b tarefas 5.3 (`TabVariables.tsx`, aba Variáveis) e 5.4 (`FaceplateVariavel.tsx`, `faixaDaEscala`).
**Pré-condições:** continuação de B-F6-09 (editor do `L3-flow-operacao` aberto); bloco `mpc1` já tem ao menos 1 DV existente **sem** `range` (herdada do handoff F4/F5 — `VALOR_DV` é a constante de fixture confirmada em `docs/plans/F6c-suite-e-guia.md`, "Interfaces consumidas").

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Duplo-clique (workaround regra 4 do §2) no nó `mpc1`. `tab.click('[data-testid="mpc-tab-variaveis"]')` (confirmado, `MpcModal.tsx:270`, `TabVariables.tsx:384`). `tab.screenshot()` da lista de DVs. | A DV existente (sem `range`) mostra uma nota discreta de que o faceplate ficará sem barra (RF-702 pede limites; omissão silenciosa é o defeito que RFC-16 fecha) — texto provável, componente `ListaDv` ainda não estendido. |
| 2 | `tab.click('[data-testid="mpc-add-dv"]')` (confirmado, `TabVariables.tsx:358`); no `data-testid="mpc-var-row-<id-da-nova-dv>"` (padrão confirmado, `LinhaVariavel`), preencher nome "DV com faixa" e EU; preencher os dois campos numéricos novos (`<id>-range_low`/`<id>-range_high`, prováveis — mesmo padrão de `CampoNumero` já usado pela Restrição, `TabVariables.tsx:334-335`, `range_low`/`range_high`) com `0` e `100`. `tab.screenshot()`. | Nova linha de DV criada com `range` preenchido; a nota de "sem barra" do passo 1 **não** aparece para esta linha. |
| 3 | `tab.click('[data-testid="config-aplicar"]')` (confirmado); `tab.click('[data-testid="flow-salvar"]')`. `tab.screenshot()` de `editor-mensagens`. | Salvo sem erro — hot-swap aplica a config nova sem parar o flow (ADR-011, mesma prova visual de `B-F4-06`: `canvas-estado` continua "rodando" se já estivesse). |
| 4 | Navegar à tela de operação: `tab.click('[data-testid="nav-operacao"]')` (confirmado, `AppShell.tsx:12`). Com um único MPC no projeto, redireciona direto (spec F5 §7.4-1, comportamento herdado). `tab.screenshot()` da fileira de faceplates de variável. | `[data-testid="faceplate-dv-<id-da-dv-original>"]` (padrão confirmado `faceplate-${tipo}-${definicao.id}`, `FaceplateVariavel.tsx:206`) mostra plaqueta + PV mono tabular + EU, **sem** `[data-testid="faceplate-escala-<id>"]` (a barra, confirmada em `FaceplateVariavel.tsx:99`, ausente para esta DV). |
| 5 | `tab.screenshot()` do faceplate da DV nova (`faceplate-dv-<id-da-nova-dv>`). | `[data-testid="faceplate-escala-<id>"]` presente, com marcadores de PV (`-pv`) desenhados dentro da barra — mesma convenção visual de MV/CV/Restrição (DESIGN §Shapes, "barra vertical de instrumento", convenção intocável). DV continua **somente leitura** nos dois casos: nenhum `faceplate-mv-input-*`/`faceplate-sp-input-*` renderiza para DV (`FaceplateVariavel.tsx:234`, ramo de edição exclui `tipo === "dv"`). |

**Evidência:** `B-F6-10-passo01.png` a `B-F6-10-passo05.png`.

---

### B-F6-11 — Faixa anunciadora: `mpc_arm_failed` cessa sozinho em 60 s; a tela de operação não pisca a cada 5 s

**Objetivo:** confirmar que a família TTL de `mpc_arm_failed` (60 s) cessa sozinha numa tela silenciosa (sem depender de nova mensagem chegando), e que o tique de 5 s que alimenta essa reavaliação **não** re-renderiza a árvore inteira da tela de operação (trend uPlot incluso) — débito 1 de frontend da F5.
**Rastreabilidade:** RF-705 · spec F6 §6.6-1 (F5R, FE-06) · plano F6b tarefa 6.1 (`useRelogioAlarmes.ts`, relógio em estado próprio, fora do `value` do `EstadoContext.Provider`).
**Pré-condições:** continuação de B-F6-10 (hot-swap acabou de rodar no passo 3 — a janela de `building` do solver, transitória, é a oportunidade para provocar `mpc_arm_failed` por comando de armar chegando antes do worker novo ficar pronto, spec §5 "`mpc_arm_failed {worker_not_ready}`").

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Imediatamente após o passo 3 de B-F6-10 (sem `wait` — a janela de `building` é curta): `tab.click` no segmento REMOTO do comutador `faceplate-modo-local-remoto` (confirmado, `FaceplatePrincipal.tsx:242`). `tab.screenshot()`. | Se o solver ainda estiver em `building`: comando rejeitado/pendência não confirma; evento `mpc_arm_failed` publicado. **Se a janela já tiver fechado** (build terminou antes do clique): repetir o passo 3 de B-F6-10 com um novo valor de `range` (reabre a janela de `building`) e tentar de novo — documentado como dependência de timing, não como falha do roteiro. |
| 2 | `tab.screenshot()` de `[data-testid="annunciator"]` (confirmado, `AnnunciatorBar.tsx:75/95`). | Faixa deixa de estar colapsada (sai de "Sem alarmes ativos"); contagem por severidade + `[data-testid="annunciator-resumo"]` visível (cor + ícone + texto — Regra do Canal Redundante). |
| 3 | `tab.click('[data-testid="annunciator-resumo"]')`. `tab.screenshot()`. | Navega para `/eventos`; evento no topo com `payload.kind == "mpc_arm_failed"`. |
| 4 | Voltar à tela de operação (`tab.click('[data-testid="nav-operacao"]')`). `tab.evaluate` marcando o elemento do gráfico uPlot com um atributo próprio, autocontido (regra 10 do §2): `(() => { const el = document.querySelector('[data-testid="operate-trend-chart"] canvas') ?? document.querySelector('[data-testid="operate-trend-chart"]'); el.setAttribute('data-marca-fixa', '1'); return true; })()`. | Marcação aplicada sem erro. |
| 5 | `wait(6000)` (> tique de 5 s, F6b tarefa 6.1). `tab.evaluate` conferindo, autocontido: `(() => { const el = document.querySelector('[data-testid="operate-trend-chart"] [data-marca-fixa="1"]'); return el !== null; })()`. `tab.screenshot()`. | `true` — o elemento marcado sobrevive ao tique: se o tique bumpasse o `value` do `EstadoContext.Provider` (`CanalAoVivo.tsx:701`), `TrendOperacao` (consumidor do canal) desmontaria/remontaria o container do uPlot e a marca se perderia (débito F5 §6.6-1, fechado pela tarefa 6.1 do F6b). Prova por DOM, não por inspeção de estado React interno. |
| 6 | `wait(55000)` (completa os 60 s da janela TTL desde o `mpc_arm_failed` do passo 1, sem nenhuma mensagem nova chegando). `tab.waitFor` `[data-testid="annunciator"]` voltar a colapsado. `tab.screenshot()`. | "Sem alarmes ativos" de novo — cessação **sozinha**, sem depender de outra mensagem publicada (era exatamente o débito: a condição TTL só reavaliava quando chegava mensagem nova). |

**Evidência:** `B-F6-11-passo01.png`, `B-F6-11-passo02.png`, `B-F6-11-passo03.png`, `B-F6-11-passo05.png`, `B-F6-11-passo06.png` (passo 4 é só marcação, sem mudança visual observável — sem screenshot próprio).

---

### B-F6-12 — Trend com 8 penas: cores distinguíveis; `overruns` com unidade

**Objetivo:** confirmar que a paleta do trend de operação suporta 8 penas simultâneas sem colidir com as cores de severidade nem com o Azul Único de interação, e que o contador `overruns` do faceplate principal ganha rótulo de unidade explícito.
**Rastreabilidade:** RF-702/704 · spec F6 §6.6-5/6 (débitos 5 e 6 de frontend da F5) · plano F6b tarefa 6.5 (`tokens.css`, `--color-pen-7`/`--color-pen-8`) e 6.6 (`FaceplatePrincipal.tsx`).
**Pré-condições:** continuação de B-F6-11 (tela de operação de `mpc1` ainda aberta); teto `TETO_PENAS_OPERACAO = 8` (confirmado, `trendOperacao.ts:162`).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.screenshot()` de `[data-testid="operate-trend-legend"]` (confirmado, `TrendOperacao.tsx:535`). | Lista de penas visível, cada item com `data-testid="operate-trend-legend-item"` e `data-var-id` (confirmados, `:542-543`); contar quantas já vêm ligadas por default (decisão A-11, teto de 6 anterior + 2 novas). |
| 2 | Para cada item de legenda ainda **desligado** (checkbox desmarcado), até completar 8 ligadas ou esgotar a lista: `document.querySelectorAll('[data-testid="operate-trend-legend-item"]')[<indice>].setAttribute('data-alvo','1')` (regra 6 do §2) seguido de `tab.click('[data-alvo="1"] input[type="checkbox"]')`, removendo o atributo entre iterações. Se os defaults já somarem 8, pular este passo (nota no cenário, não é falha). | Cada clique liga uma pena nova, sem exceder o teto — ao atingir 8, `[data-testid="operate-trend-legend-teto"]` (confirmado, `:564`) aparece nos itens restantes desligados, com o aviso "Máximo de 8 penas por gráfico". |
| 3 | `tab.screenshot()` do gráfico (`[data-testid="operate-trend-chart"]`, confirmado) com as 8 penas ligadas. | 8 traços com cores distintas entre si (paleta estendida a `--color-pen-7`/`--color-pen-8`), nenhuma colidindo visualmente com Vermelho Alarme/Âmbar Advertência/Verde Rodando (DESIGN §Colors, Regra da Cor Anormal) nem com o Azul Industrial de interação (regra do Azul Único — nenhuma pena, nem a de SP, desenha nesse azul). |
| 4 | `tab.screenshot()` da linha de contadores do faceplate principal (`[data-testid="faceplate-overruns"]`, confirmado `FaceplatePrincipal.tsx:272`). | Valor em mono tabular acompanhado de um rótulo de unidade explícito (ex. "contagem", texto provável — F6b tarefa 6.6, hoje o elemento mostra só o número, `FaceplatePrincipal.tsx:269-275`) — DESIGN §Typography, "número sem unidade de engenharia é defeito". `[data-testid="faceplate-last-solve-ms"]` (confirmado, `:278`) continua com "ms" ao lado, inalterado. |

**Evidência:** `B-F6-12-passo01.png` a `B-F6-12-passo04.png`.

---

### B-F6-02 — Ativar: confirmação nomeia o projeto e o nº de flows a parar; invalidação de cache sem reload

**Objetivo:** confirmar que Ativar troca o projeto ativo, que a confirmação nomeia o projeto atual e o número de flows que vão parar (verbo no botão, "Ativar e parar N flows"), que os flows do projeto anterior param, que um evento aparece em `/eventos`, e que as telas de engenharia refletem o novo projeto **sem reload** (prova da invalidação de cache).
**Rastreabilidade:** RF-101 · spec F6 §6.1-4 (UX-07) · §6.1-8 (F6R-11, tabela de invalidação) · plano F6b tarefa 2.2 (`ConfirmarAtivacao.tsx`).
**Pré-condições:** continuação de B-F6-12 (todos os cenários de operação em `L3 F5 operacao` já exercitados — este é o último uso da tela de operação deste roteiro antes da troca); `L3-flow-operacao` rodando (deployado durante os cenários anteriores).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.click('[data-testid="nav-projetos"]')`. `tab.click('[data-testid="proj-ativar"]')` (provável) na linha de `L3 F6 portabilidade`. `tab.screenshot()` do diálogo de confirmação. | Diálogo **nomeia** "L3 F5 operacao" (o projeto **atual**, não o alvo) e a contagem de flows a parar (1 — `L3-flow-operacao`); botão com o verbo, "Ativar e parar 1 flow" (singular; degradaria para "Ativar" sem contagem só com zero flows, UX-07) — nunca um "OK" genérico. |
| 2 | `tab.click` no botão de confirmação do diálogo. `tab.screenshot()`. | Projeto ativo passa a `L3 F6 portabilidade`; lâmpada "Ativo" migra de linha na tabela sem reload de página. |
| 3 | Sem navegar: `tab.click('[data-testid="nav-flows"]')`. `tab.screenshot()`. | A tabela de Flows já mostra o recorte de `L3 F6 portabilidade` (vazio ou com o que o F6c criar ali) — **não** mais `L3-flow-operacao` — prova de que `["flows"]` foi invalidada pela ação Ativar (tabela §6.1-8), sem precisar de reload manual. |
| 4 | `tab.click('[data-testid="nav-conexoes"]')`. `tab.screenshot()`. | Tabela de Conexões mostra as três conexões novas de `L3 F6 portabilidade` (§1 item 7) — prova de `["connections"]` invalidada. |
| 5 | `tab.click('[data-testid="nav-eventos"]')`. `tab.screenshot()` da linha mais recente, expandindo o `<details>`. | Evento no topo referenciando a ativação do projeto (kind confirmável por `payload.kind` — evento de ativação já existe desde a F1, este cenário confirma que a ativação pela UI nova continua auditada). |
| 6 | `tab.click('[data-testid="nav-operacao"]')`. `tab.screenshot()`. | Sem MPC no projeto `L3 F6 portabilidade`: `[data-testid="operate-selector-empty"]` (confirmado, `OperateSelectorPage.tsx:47`) mostra "Nenhum bloco MPC configurado no projeto ativo" — prova de `["operate","mpcs"]` invalidada (a tela não continua mostrando `mpc1` do projeto anterior). |

**Evidência:** `B-F6-02-passo01.png` a `B-F6-02-passo06.png`.

---

### B-F6-07 — Pendências em Conexões: ícone + rótulo sem cor de severidade; as três pendências; resolver

**Objetivo:** confirmar a coluna "Pendências" na tabela de Conexões (ícone + rótulo em Texto Secundário, sem cor de severidade), os três predicados presentes nas conexões de `L3 F6 portabilidade`, e a resolução da pendência de senha via o formulário de edição existente.
**Rastreabilidade:** RF-202 (aceite "re-informando segredos") · spec F6 §6.3 (decisão A-4, UX-01) · §3.2-8 (os três predicados) · plano F6b tarefas 1.4 (`pendencias.ts`) e 4.1 (coluna `ConnectionsPage.tsx`).
**Pré-condições:** continuação de B-F6-02 (`L3 F6 portabilidade` já é o projeto ativo); certificado de aplicação **ainda não existe** nesta instalação (B-F6-03, que gera o certificado, roda depois deste cenário — de propósito, para o predicado `needs_app_certificate` ficar observável aqui).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.click('[data-testid="nav-conexoes"]')` (se não já lá). `tab.screenshot()` da tabela. | Coluna **Pendências** (`conn-pendencias`, provável — prefixo `conn-pendencia*` normativo, plano F6b regras globais item 2) antes de "Último estado"; célula com ícone + rótulo em Texto Secundário (`text-fg-muted`), **sem** âmbar/vermelho (UX-01: pendência é estado de configuração, não severidade de processo — a Regra da Cor Anormal fica reservada à coluna "Último estado"). |
| 2 | `tab.screenshot()` focando a linha da conexão `auth_mode: certificate`. | Pendência **"certificado da aplicação"** presente (predicado `needs_app_certificate` — `security_policy != none \|\| auth_mode == certificate`, sem `security_policy` aqui mas com `auth_mode == certificate`, §3.2-8 terceira fórmula) — `title` do elemento com o efeito exato (ex. "a conexão falhará em `cert_missing` até gerar o certificado de aplicação da instalação", texto provável de `EFEITO_PENDENCIA`). |
| 3 | `tab.screenshot()` focando a linha da conexão segura sem senha reinformada. | **Duas** pendências na mesma célula: "senha" (`needs_password`) e "certificado do servidor" (`needs_server_certificate`) — e também "certificado da aplicação" (`security_policy != none`), então esta linha mostra as **três** ao mesmo tempo. |
| 4 | `tab.click('[data-testid="conn-edit"]')` nesta linha (confirmado, `ConnectionsPage.tsx:245`); preencher o campo de senha do `ConnectionForm` com um valor qualquer; salvar. `tab.screenshot()`. | Formulário aceita; ao fechar, a célula de Pendências desta linha perde o item "senha" — as outras duas continuam (servidor e aplicação ainda não resolvidos neste cenário; ficam para B-F6-04 e B-F6-03, que rodam a seguir). |

**Evidência:** `B-F6-07-passo01.png` a `B-F6-07-passo04.png`.

---

### B-F6-03 — Chapa do certificado de aplicação: escopo de instalação; mono tabular; baixar `.der`; Regerar lista conexões afetadas

**Objetivo:** confirmar a chapa "Certificado da aplicação" no topo de Conexões (visível só a admin, rótulo de escopo de instalação explícito, metadados em mono tabular), o fluxo Gerar → Baixar → Regerar, e que Regerar lista as conexões afetadas e exibe o aviso de re-trust do backend verbatim.
**Rastreabilidade:** RF-202 · spec F6 §6.2 (decisão A-7, UX-02/03/04, SEC-06) · plano F6b tarefa 3.1 (`ChapaCertificadoApp.tsx`, `useAppCertificate.ts`, `certificados.ts`).
**Pré-condições:** continuação de B-F6-07 (ainda em `/engenharia/conexoes`, admin); certificado de aplicação **ainda não existe** (confirmado pela pendência observada em B-F6-07).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.screenshot()` do topo da página, antes de qualquer interação com a chapa. | Chapa "Certificado da aplicação" (`cert-app-chapa`, provável) separada da tabela por um degrau tonal (não só posição); rótulo explícito de escopo — "vale para todas as conexões de todos os projetos desta instalação" (texto provável, UX-04/SEC-06); estado **ausente**: texto explícito + botão `cert-app-gerar` (provável). |
| 2 | `tab.click('[data-testid="cert-app-gerar"]')`. `tab.screenshot()`. | Certificado gerado; metadados aparecem em **mono tabular** (`process-value`): `fingerprint_sha256`, `not_before`/`not_after`, `application_uri` (`urn:ottima:opc-worker` — identificador técnico, mesmo tratamento de `node_id`, nunca plaqueta — UX-02). Botões `cert-app-baixar`/`cert-app-regerar` (prováveis) aparecem. |
| 3 | `tab.click('[data-testid="conn-pendencias"]')`-equivalente: sem navegar, `tab.screenshot()` da tabela de Conexões abaixo da chapa. | As duas conexões que mostravam "certificado da aplicação" pendente em B-F6-07 **perdem** esse item da célula — prova de que gerar o certificado resolve o predicado `needs_app_certificate` para a instalação inteira (§3.2-8), sem precisar reeditar cada conexão. |
| 4 | `tab.click('[data-testid="cert-app-baixar"]')` (chama `baixarArquivo('/api/certificates/app/export', 'ottima.der')`, regra 12 do §2). | Download disparado; conferência de conteúdo não é necessária aqui (o `.der` de aplicação não é reutilizado por este roteiro — B-F6-04 usa o `.der` do **servidor**, já materializado em disco, §1 item 8). |
| 5 | `tab.click('[data-testid="cert-app-regerar"]')`. `tab.screenshot()` do diálogo de confirmação. | Diálogo **lista as conexões afetadas** — as que têm `security_policy != "none"` ou `auth_mode == "certificate"` (computável no cliente com a lista já carregada, SEC-06) — ou seja, no mínimo as duas conexões novas de `L3 F6 portabilidade`. |
| 6 | Confirmar a regeração. `tab.screenshot()`. | O `warning` de re-trust do backend (`certificates.py:28-31,52`) aparece **verbatim** na tela — texto do servidor, não reescrito pelo cliente. Novo `fingerprint_sha256` diferente do exibido no passo 2. |

**Evidência:** `B-F6-03-passo01.png` a `B-F6-03-passo06.png`.

---

### B-F6-04 — Confiar no certificado do servidor (upload), conferir fingerprint; conexão sobe; deixar de confiar

**Objetivo:** confirmar o upload de um `.der` do servidor via `<input type="file">` oculto, a exibição do `fingerprint_sha256` devolvido para conferência, que a conexão efetivamente sobe depois de confiada, e que "Deixar de confiar" reverte (idempotente).
**Rastreabilidade:** RF-202 · ADR-021 · spec F6 §6.2-2/3 · plano F6b tarefa 3.2 (`useServerCertificate.ts`).
**Pré-condições:** continuação de B-F6-03 (certificado de aplicação já existe — necessário: `needs_app_certificate` precisa estar `false` para a conexão segura poder subir de verdade, §3.2-8, "requisito deste roteiro" no §1 item 7); senha já reinformada nesta conexão em B-F6-07 passo 4; `deploy/e2e-certs/opcsim.der` disponível em disco (§1 item 8) — o certificado **real** do opcsim, servindo `basic256sha256` no mesmo endpoint de `opcsim-l3` (§1 item 7, requisito de endpoint).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.screenshot()` da linha da conexão segura antes de confiar. | Coluna "Último estado" mostra falha de comunicação (`cert_missing` ou equivalente — servidor ainda não confiado); Pendências mostra só "certificado do servidor" restante (senha já resolvida em B-F6-07, app já existe desde B-F6-03). |
| 2 | `tab.click('[data-testid="cert-servidor-confiar"]')` (provável) na linha; `tab.uploadFile('[data-testid="cert-servidor-upload-input"]', 'deploy/e2e-certs/opcsim.der')` (regra 11 do §2, arquivo já materializado pelo compose, §1 item 8). `tab.screenshot()`. | Upload aceito; `fingerprint_sha256` devolvido pela API (`connections.py:292-298`) exibido em mono tabular na linha, para conferência contra o servidor. |
| 3 | `wait(15000)` (a próxima tentativa de sessão do `opc-worker` para esta conexão — mesma margem de boot usada em `B-F5-02`). `tab.evaluate('location.reload()')`. `tab.screenshot()` da coluna "Último estado". | Conexão **sobe**: estado deixa de ser falha de certificado — a sessão OPC-UA se estabelece de verdade contra o opcsim (endpoint real, `security_policy: basic256sha256`, §1 item 7). Pendências desta linha ficam vazias (as três resolvidas: senha em B-F6-07, aplicação em B-F6-03, servidor aqui). |
| 4 | `tab.click('[data-testid="cert-servidor-descartar"]')` (provável, `DELETE`, idempotente). `tab.screenshot()`. | Trust removido; Pendências volta a mostrar "certificado do servidor"; `wait(15000)` + reload confirmaria a conexão cair de novo (não necessário reexecutar o reload — a queda é responsabilidade do `opc-worker`, já provada indiretamente pelo passo 3 no sentido inverso). |

**Evidência:** `B-F6-04-passo01.png` a `B-F6-04-passo04.png`.

---

### B-F6-05 — Exportar: arquivo baixa com o slug; `tag_ref` objeto; ausência de segredos

**Objetivo:** confirmar que Exportar baixa um arquivo com o nome derivado do slug do projeto (via `Content-Disposition`), e que o conteúdo tem `tag_ref` como objeto `{connection, tag}` nos seis lugares aplicáveis, sem nenhum campo de segredo.
**Rastreabilidade:** RF-102 · spec F6 §2.1/§2.2/§2.3 · §3.1 · §6.0-3 · §6.1-5 · plano F6a tarefas 1.1-1.3/2.2 (backend) · plano F6b tarefa 2.3 (`ProjectsPage.tsx`, ação "Exportar").
**Pré-condições:** continuação de B-F6-04; projeto `L3 F6 portabilidade` (ativo) com as três conexões (uma delas agora com trust removido pelo passo 4 de B-F6-04 — estado irrelevante para export, que nunca inclui `server_cert_file`), as duas conexões com **tag homônima** e o flow **`L3-flow-arquivo`** (`opc_read` sobre uma das tags homônimas + bloco Script `OUT1 = 0.0`), tudo entregue por `setup-l3.py` (§1 item 7). **Nenhum setup pela UI é necessário neste cenário** — o material de `tag_ref` e de código Script já existe no ambiente.

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.click('[data-testid="nav-flows"]')`. `tab.screenshot()` da tabela de Flows do projeto ativo. | `L3-flow-arquivo` presente e **parado** (coluna "Desejado" = parado; nunca deployado, §1 item 7) — confirmação de que o material do export existe antes de exportar. |
| 2 | `tab.click('[data-testid="nav-projetos"]')`. `tab.click('[data-testid="proj-exportar"]')` (provável, plano F6b tarefa 2.3) na linha de `L3 F6 portabilidade`. | `baixarArquivo('/api/projects/{id}/export', '<slug>.ottima.json')` disparado (regra 12 do §2) — download efetivo, nome derivado do `Content-Disposition` do servidor. |
| 3 | Conferência de conteúdo por `tab.evaluate` (regra 12 do §2, autocontido — regra 10): `fetch('/api/projects/<id-de-L3-F6-portabilidade>/export', { headers: { Authorization: 'Bearer ' + localStorage.getItem('ottima.token') } }).then((r) => r.json())`. `tab.screenshot()` de uma inspeção do objeto no console (ou captura do retorno pela tool, se exposto). | `schema_version: 1`; `connections[]` **sem** `auth_password_enc` nem `server_cert_file`; nenhum campo `id`/`project_id`/`connection_id`/`is_active`/`created_at`/`updated_at` em nenhum nível; `tags[]` das duas conexões com tag homônima mostra o **mesmo** `name` de tag sob `connection` diferente, sem colisão de dado. |
| 4 | No JSON do passo 3, localizar o nó `opc_read` do flow `L3-flow-arquivo` dentro de `flows[].graph.nodes[]`. | O nó tem `data.tag_ref` no formato **objeto** `{"connection": "<nome da conexão>", "tag": "<nome da tag>"}` — e **não** `data.tag_id`. Varredura recursiva do JSON inteiro não acha nenhuma ocorrência das chaves cruas `tag_id`/`write_tag_id`/`mode_cmd_tag_id`/`mode_read_tag_id`/`readback_tag_id` (§2.2 da spec, os seis lugares). Como as duas conexões têm tag de **mesmo nome**, o par `{connection, tag}` é o que desambigua — a forma string `"conexao/tag"` seria ambígua aqui, que é exatamente a razão de A-2. |

**Evidência:** `B-F6-05-passo01.png` a `B-F6-05-passo04.png`.

---

### B-F6-06 — Importar: prévia com contagens, nome editável e blocos Script com código; confirmação explícita; resumo de pendências

**Objetivo:** confirmar o fluxo de import em três passos: prévia com contagem de conexões/tags/flows e nome editável, lista dos blocos Script com o código visível exigindo confirmação explícita antes de enviar, e o resumo final com `pending_secrets`.
**Rastreabilidade:** RF-103 · spec F6 §3.2 · §6.1-6 (decisão A-6, F6R-03) · plano F6a tarefa 2.3 (backend) · plano F6b tarefa 2.4 (`ImportarProjeto.tsx`, `importar.ts`).
**Pré-condições:** continuação de B-F6-05; arquivo `.ottima.json` de `L3 F6 portabilidade` já baixado (contém o flow `L3-flow-arquivo`, com o `opc_read` traduzido para `tag_ref` e o bloco Script `OUT1 = 0.0` — §1 item 7).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.click('[data-testid="import-arquivo"]')` (provável, prefixo `import-*` normativo, plano F6b regras globais item 2); `tab.uploadFile('[data-testid="import-arquivo-input"]', <caminho do arquivo baixado em B-F6-05>)` (regra 11 do §2). `tab.screenshot()`. | Leitura e `JSON.parse` no cliente sem erro (§6.0-2); avança para a prévia sem requisição ao servidor ainda. |
| 2 | `tab.screenshot()` da prévia (`import-previa`, provável). | Contagem de **conexões (4** — as duas homônimas, a `certificate` e a segura**)**, de tags e de **flows (1** — `L3-flow-arquivo`**)** visível e conferindo com o arquivo; campo `import-nome` (provável) pré-preenchido com o nome do projeto exportado, **editável**. |
| 3 | `tab.screenshot()` da lista de blocos Script (`import-scripts`, provável). | O bloco Script de `L3-flow-arquivo` aparece com o `code` **verbatim** em `<pre>` rolável (`OUT1 = 0.0`, semeado por `setup-l3.py`) — o admin nunca importa às cegas (ADR-018/012). |
| 4 | `tab.click('[data-testid="import-enviar"]')` (provável) **sem** marcar a confirmação de execução do Script. | Botão desabilitado / envio bloqueado — a confirmação explícita é obrigatória (§6.1-6). |
| 5 | `tab.click('[data-testid="import-confirmar-script"]')` (checkbox, provável); alterar `import-nome` para "L3 F6 portabilidade (importado)" — o nome original já existe nesta instalação e colidiria em 409, que é exatamente o que A-6 resolve com o campo editável; `tab.click('[data-testid="import-enviar"]')`. `tab.screenshot()`. | Envio disparado; `201` do servidor. |
| 6 | `tab.screenshot()` do resumo de sucesso (`import-resumo`, provável). | Projeto novo criado **inativo** (RF-103); `pending_secrets` agrupado por tipo (`pendenciasDoResumo`, plano F6b tarefa 1.4) — a conexão `auth_mode: certificate` do arquivo original volta a pedir certificado de aplicação **só se** este for outro ambiente sem cert — como o cert já existe nesta instalação (B-F6-03), este predicado sai `false`; senha e certificado de servidor voltam a pedir (nunca atravessam a fronteira, §2.3); link para `/engenharia/conexoes`. |

**Evidência:** `B-F6-06-passo01.png` a `B-F6-06-passo06.png`.

---

### B-F6-08 — Import recusado: lista de problemas um por linha; `;` sobrevive íntegro; nada criado

**Objetivo:** confirmar que uma recusa de import com múltiplos problemas aparece como lista, um problema por linha, nunca truncada, e que um valor contendo `;` sobrevive íntegro (a partição do `detail` agregado usa ` | `, nunca `;`) — e que nenhum registro é criado no banco.
**Rastreabilidade:** RF-103 · spec F6 §3.2-5 (UX-06) · §6.1-6 · plano F6a tarefa 2.1 (`formatar_problemas`) · plano F6b tarefa 2.4 (`importar.ts`, partição do `detail`).
**Pré-condições:** cópia do arquivo exportado em B-F6-05, corrompida **fora da tool `browser`** (edição de texto do JSON, sem subir/derrubar stack): (a) um `tags[].name` trocado para o literal `"ns=2;s=TT101"` (nome de tag é texto livre, spec §2.2-2 confirma que pode conter qualquer caractere, incluindo `;` — vetor de teste deliberado para exercitar a sobrevivência do `;`, já que o texto exato de qual campo do servidor cita esse valor é implementação da tarefa 2.3 do F6a, ainda não escrita no momento deste draft); (b) o `tag_ref` correspondente alterado para apontar a um nome de tag que **não existe** no arquivo (órfão) — dois problemas distintos no mesmo arquivo, o segundo citando o valor do item (a) na mensagem de erro.

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Contagem de projetos/conexões/tags/flows via `tab.evaluate` autocontido chamando `GET /api/projects`, `/api/connections?project_id=...` etc com o token de `localStorage`, **antes** da tentativa de import (baseline). | Contagens anotadas para comparação no passo 3. |
| 2 | `tab.click('[data-testid="import-arquivo"]')`; `tab.uploadFile('[data-testid="import-arquivo-input"]', <caminho do arquivo corrompido>)`. Avançar a prévia (contagens ainda aparecem — a prévia é só leitura do JSON no cliente, não valida contra o servidor); se houver bloco Script, marcar a confirmação; `tab.click('[data-testid="import-enviar"]')`. `tab.screenshot()`. | Servidor recusa com **422**. |
| 3 | `tab.screenshot()` da lista de problemas (`import-erro`, provável). | Lista renderizada **um problema por linha**, nunca truncada; a linha referente ao item (b) contém o valor `ns=2;s=TT101` **íntegro** — prova de que a partição do `detail` agregado usa ` \| ` como separador e não quebra no `;` interno do valor (§3.2-5, UX-06). |
| 4 | Repetir a contagem do passo 1 pelo mesmo mecanismo. | Contagens **idênticas** às do baseline — nada foi criado, mesmo com dois problemas detectados (a varredura completa das 4 camadas custa o mesmo que parar no primeiro, e a transação é única). |

**Evidência:** `B-F6-08-passo02.png` a `B-F6-08-passo03.png` (passos 1 e 4 são conferência por `tab.evaluate`, sem mudança visual de tela — sem screenshot próprio, mesmo padrão de F5 para passos de leitura de API).

---

### B-F6-13 — RBAC: operador não vê Projetos, nem a chapa de certificados, nem export/import

**Objetivo:** confirmar que o papel operador não vê nenhuma superfície de mutação da F6: item de nav "Projetos", chapa de certificado da aplicação, ações de trust por conexão, e as ações Exportar/Importar/Ativar da página de Projetos (se acessada por URL direta).
**Rastreabilidade:** RF-003 · ADR-015 · spec F6 §6.1/§6.2 (RBAC herdado — nenhuma rota nova muda o modelo de papéis) · plano F6b tarefas 2.1 ("Browser (operador): `proj-new`/`proj-edit`/`proj-delete` ausentes"), 3.1 ("a chapa **não aparece**").
**Pré-condições:** usuário operador (`operador_e2e`/`OperadorE2E#2026`, já criado por `setup-l3.py`, §1 item 7); usuário admin (seed) disponível para o passo de comparação. RBAC de mutação já implementado desde F1-F4 via `useCanMutate()` (`useAuth.tsx:81-83`) — este cenário confirma que a F6 não regrediu essa gate ao introduzir as superfícies novas.

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Logout (`tab.click('[data-testid="logout"]')`, confirmado `AppShell.tsx:68`); login operador: `tab.fill('[data-testid="login-username"]', "operador_e2e")`, `tab.fill('[data-testid="login-password"]', "OperadorE2E#2026")`, `tab.click('[data-testid="login-submit"]')`. `tab.screenshot()` da nav do shell. | `[data-testid="current-user"]` mostra "· operador" (confirmado, `AppShell.tsx:63`); `[data-testid="nav-projetos"]` **presente** — Projetos é superfície de **leitura** (a tabela lista projetos, como Conexões lista conexões), e RBAC é só sobre mutação (spec §7.3-2 herdada da F5); o que tem de sumir são as ações, conferidas no passo 2. *(Corrigido na execução do gate: o draft previa o item de nav ausente, o que contradizia a própria premissa citada e o plano F6b tarefa 2.1, que só exige `proj-new`/`proj-edit`/`proj-delete` ausentes.)* |
| 2 | Navegação direta por URL: `tab.evaluate("location.assign('/engenharia/projetos')")`. `tab.screenshot()`. | Se a rota existir mas a nav estiver oculta, a página ainda carrega em modo leitura: `proj-new`/`proj-edit`/`proj-delete`/`proj-ativar`/`proj-exportar` **ausentes** do DOM — não `disabled`, removidos (mesmo padrão de `conn-new` ausente para operador, `ConnectionsPage.tsx`). |
| 3 | `tab.click('[data-testid="nav-conexoes"]')`. `tab.screenshot()`. | Chapa "Certificado da aplicação" **não aparece** (plano F6b tarefa 3.1); coluna "Pendências" continua visível (é leitura, não mutação); `conn-new` (confirmado ausente desde F5), `cert-servidor-confiar`/`cert-servidor-descartar` (prováveis) **ausentes** por linha. |
| 4 | Logout operador; login admin (credenciais de `deploy/.env`, §1 item 4). Repetir os passos 2-3. `tab.screenshot()` de cada. | `nav-projetos` presente; `/engenharia/projetos` com `proj-new`/`proj-ativar`/`proj-exportar` presentes; chapa de certificado presente em Conexões — prova de que a ausência anterior é RBAC, não bug de renderização. |
| 5 | Logout admin; login operador de volta (mesmas credenciais do passo 1) — housekeeping, sem screenshot. | Sessão operador restaurada; ambiente pronto para uma eventual repetição da rodada de gate. |

**Evidência:** `B-F6-13-passo01.png` a `B-F6-13-passo04.png` (passo 4 gera 2 screenshots — `B-F6-13-passo04a.png` Projetos, `B-F6-13-passo04b.png` Conexões, padrão de sufixo herdado de `B-F4-07`/`B-F5-09`; passo 5 é housekeeping, sem evidência).

---

## 5. O que este roteiro NÃO cobre

- **Formas de API agregadas** (413 de corpo > 4 MiB, 409 de nome colidindo, os demais casos de 422 além do exercitado em B-F6-08, RBAC de rota em 403 puro) — cobertas por `pytest` da API (spec F6 §9.1) e por `E2E-F6-01/02/03` do L2; este roteiro exercita a UI com um único caso ilustrativo de recusa múltipla, não a matriz completa de recusas.
- **Dinâmica numérica do MPC sob a malha TFS** (overrun com orçamento estreitado, hot-swap com irmão de controle) — coberta exclusivamente por `E2E-F6-05`/`E2E-F6-06` sob `-m rnf09` (spec F6 §7), que fala com a API e o opcsim reais sob clock controlado; este roteiro só confirma que a UI reflete o estado publicado (B-F6-11 usa hot-swap para provocar `mpc_arm_failed`, mas não mede orçamento nem contador de overrun em regime).
- **`/api/health` degradado** (Redis/Postgres fora) — fora da fase inteira por decisão A-1 (a suíte E2E proíbe `down`/`prune`, `tests/e2e/conftest.py:4-6`); a prova é unitária (F6a tarefa 3.2, spec §9.1). Nenhum cenário deste roteiro tenta derrubar um serviço para observar `status: "degraded"`.
- **Round-trip destrutivo de projeto** (export → `DELETE` → import → re-informar segredos → deploy) — é o aceite da fase (PRD §8-F6), provado por `E2E-F6-02` no L2 (decisão A-9, ids de destino necessariamente maiores após `DELETE`); este roteiro exercita export e import como ações de UI **separadas**, sem excluir nenhum projeto real do ambiente L3 (que precisa sobreviver para as rodadas de gate seguintes).
- **Guia de implantação** (`docs/IMPLANTACAO.md`, plano F6c tarefa 5.1) — documento de leitura, sem superfície de browser.
- **Golden `mpcLogic` Python→TS e demais testes puros** (predicados de pendência, partição do `detail`, primitivos de arquivo, tique de TTL sem re-render) — cobertos por `npm run test:unit` (spec §9.1); este roteiro confirma o comportamento observável na tela, não a implementação interna.

---

## 6. Ordem de gate

Tabela de execução da rodada de gate completa (plano F6c, Etapa 6, tarefa 6.1). Qualquer vermelho em qualquer linha interrompe a rodada: corrigir, e reiniciar a rodada inteira desde `down -v` (só com autorização explícita + dump prévio, spec F6 §9.3) — nunca pular direto para a camada seguinte com uma pendência aberta; nunca `prune`.

| Ordem | Camada | Comando / ação | Critério de passagem |
|---|---|---|---|
| 1 | Testes de workspace (pytest + ruff) | `uv run pytest` (workspace, incl. `-m slow` uma vez) + `uv run ruff check . && uv run ruff format --check .` | 100% verde, zero warning de lint |
| 2 | Frontend build/unit | `cd frontend && npm run build && npm run test:unit` | build sem erro de tipo; checks puros verdes (predicados de pendência, partição do `detail`, primitivos de arquivo, `output_eu`, faceplate de DV, paleta de 8 penas, chaves invalidadas, tique de TTL sem re-render) |
| 3 | L1 — smoke | `OTTIMA_E2E=1 bash deploy/smoke.sh` (flow-runtime recém-subido — §1 item 6) | smoke completo, incl. `/api/health` com `redis_ok`/`db_ok` e `status: "ok"` |
| 4 | L2 — 46 cenários | `E2E_ADMIN_USERNAME=… E2E_ADMIN_PASSWORD=… uv run pytest -m e2e tests/e2e -v` (credenciais inline de `deploy/.env`) | 46/46 verdes (41 herdados de F1-F5 + `E2E-F6-01/02/03/05/06`) |
| 5 | Suíte RNF-09 | `uv run pytest -m rnf09 -v` | 6/6 verdes (`E2E-F4-03/05/06/10` + `E2E-F6-05/06`) |
| 6 | Playwright F1 | `cd frontend && npm run e2e` (credenciais `E2E_ADMIN_USERNAME`/`E2E_ADMIN_PASSWORD` inline) | regressão F1 verde; **serializado** com a L2 |
| 7 | **L3 — este roteiro** | Execução manual do controlador com a tool `browser`, cenários B-F6-01 a B-F6-13 (ordem de execução do §4), screenshot por passo | todos os cenários verdes, evidências completas no diretório da seção 3 |

**Encerramento da fase — e da v1:** só depois da linha 7 verde na mesma rodada das linhas 1-6, com `.superpowers/sdd/F6-portabilidade/RELATORIO-GATE-F6.md` documentando a rodada (padrão herdado de F3/F4/F5, plano F6c tarefa 6.2), a fase F6 pode ser dada como pronta para revisão de merge — e, com aceite explícito do usuário, para o merge `--no-ff` da branch `f6-portabilidade` na `main`, fechando a v1.
