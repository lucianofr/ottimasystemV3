# Roteiro L3 — Testes E2E de browser (Fase F5 — Operação)

**Status:** normativo para o gate da F5 · draft do agente e2e-runner revisado e aceito pelo controlador (revisão 2026-08-06: âncora da predição lida via WS temporário — nunca de `/api/history/mpc`; Ts_mpc via `/api/operate/mpcs` — sem sessão admin paralela; `-m slow` na ordem de gate) · 2026-08-06.
**Fase:** F5 (PRD §8) · tela de operação (faceplates, trend com predição, eventos, faixa anunciadora).
**Quem executa:** o **agente controlador**, segurando a tool nativa `browser` do harness omp. Subagentes NÃO têm acesso a essa tool (bloqueada por design) — nenhum passo deste roteiro pode ser delegado a subagente.
**Quando roda:** plano F5b, Etapa 7, tarefa 7.1 — última camada da rodada de gate completa da fase, depois de L1 e L2 (`docs/plans/F5b-tela-operacao.md` tarefa 7.1 já referencia este arquivo pelo nome).

**Fontes normativas** (precedência ADR > PRD > spec > plano; ADRs sempre vencem em conflito):
- `docs/adr/ADR-003` (hypertable/retenção Timescale, `mpc_samples`), `ADR-009` (watchdog bit alternante), `ADR-010` (modos, herdado), `ADR-011` (hot-swap, herdado), `ADR-015` (papéis admin/operador), `ADR-016` (tela de operação: faceplate, tendência, predição), `ADR-020` (log de eventos sem ACK), `ADR-023` (escopo v1, porta única).
- `docs/PRD.md` v1.3 §5.1 (RF-001/002/003, papéis), §5.11 (RF-701..705, tela de operação), §5.12 (RF-801..803, histórico/eventos), §6 (RNF-05 resiliência, RNF-07 observabilidade), §8-F5 (aceite da fase).
- `docs/specs/F5-operacao.md` — inteira; em especial §3 (semântica da predição), §7 (frontend), §9.2 tabela L3 (B-F5-01..09), §9.3 (precondições, herda F3/F4).
- `docs/plans/F5a-operacao-dados.md` (dados & serviços) e `docs/plans/F5b-tela-operacao.md` (tela de operação, decisão A-12) — em especial as regras globais do F5b item 2 (**convenção de `data-testid`: `operate-*`, `faceplate-*`, `eventos-*`, `home-*`**) e a Etapa 7 (gate final, referencia este roteiro).
- `docs/plans/tests-e2e-f4.md` — modelo estrutural deste roteiro; §2 (armadilhas da tool `browser`) herdado integralmente, regras 1-7.
- `CLAUDE.md` §Comandos (comandos canônicos do stack e precondições do gate; L2 passa a 41 cenários com a F5).
- `DESIGN.md` §Colors/Typography/Layout/Shapes/Do's and Don'ts (mono tabular, sem verde fora de lâmpada, Regra da Plaqueta, Regra do Canal Redundante, Regra do Número Tabular, Regra da Cor Anormal, Regra do Estado Publicado, barra vertical PV/SP/OUT intocável).

## Regra de ferro

**A fase F5 só é considerada pronta quando L1 + L2 (41 cenários — 34 herdados de F1-F4 + 7 novos E2E-F5-01..07) estiverem verdes E este roteiro inteiro estiver verde, na mesma rodada** (plano F5b, Etapa 7, tarefa 7.1). Qualquer vermelho em qualquer camada invalida a rodada inteira: corrige, e a rodada completa roda de novo desde `down -v` — **`down -v` só com autorização explícita do usuário e dump prévio do banco** (spec F5 §9.3); nunca se re-executa só o cenário que falhou.

---

## 1. Precondições de ambiente

Copiadas de `CLAUDE.md` §Comandos e `docs/specs/F5-operacao.md` §9.3 (que herda integralmente o protocolo F3/F4). Válidas para a rodada de gate inteira, não só para este roteiro.

1. **Stack composta com os DOIS arquivos compose**:
   ```bash
   cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d
   ```
   8 serviços (7 sem o override `e2e`); sem ele o opcsim e o Redis de teste não ficam acessíveis do host.
2. **Rebuild do bundle novo do frontend** antes de qualquer passo (o browser precisa do bundle com as rotas `/operacao`, `/operacao/:flowId/:blockId`, `/eventos`, a Home redesenhada como visão geral e a nav em dois grupos — nada disso existe no bundle da F4; entregue pelas Etapas 1-6 do plano F5b):
   ```bash
   cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --no-deps frontend
   ```
3. **Frontend acessível em `http://localhost:8080`** (proxy do nginx do compose).
4. **Credenciais SEMPRE inline de `deploy/.env`** — ler o arquivo, extrair usuário/senha do admin seed (`OTTIMA_ADMIN_USERNAME`/`OTTIMA_ADMIN_PASSWORD`) e digitá-los diretamente no passo de login ou usá-los num comando `curl` pontual. Nunca `export` em shell persistente da sessão.
5. **L2 e Playwright são serializados** — nunca rodam juntos. Este roteiro (L3) roda depois de ambos terminarem, contra o mesmo compose já de pé.
6. **L1 exige flow-runtime recém-subido**: o smoke agora também confere `GET /api/health/workers` com os 3 `up: true` e as políticas de retenção de `mpc_samples` **e** `mpc_samples_1m` em `timescaledb_information.jobs` (spec F5 §9.2-L1). Se a L2 já rodou antes deste roteiro, `docker compose ... restart flow-runtime` antes do L1 — não antes deste roteiro L3.
7. **Estado inicial do roteiro**: projeto ativo existente; um flow com bloco MPC válido e deployável, fechando malha com um bloco TFS (herdado do gate F4 — RNF-09, sem hardware real); conexão OPC **`opcsim-l3`** com tags cadastradas para o `pid` da(s) MV(s) da malha; papel **admin** logado inicialmente (necessário para o item 8 abaixo e para os re-deploys de setup dos cenários B-F5-02/06).
8. **Usuário operador criado antes de qualquer cenário** — nenhum seed nasce com o papel `operator` (só o admin, via `OTTIMA_ADMIN_*`); rota confirmada em `services/api/src/ottima_api/routers/users.py` (`POST /api/users`, exclusiva de admin — `require_admin` no router inteiro) e schema `UserCreate` (`username`, `name`, `password` mín. 8 chars, `role: "admin"|"operator"`). Comando exato, lendo o admin seed de `deploy/.env` (não há UI de usuários na F1 — `frontend/src/features` não tem `usuarios`/`users`; o caminho é API pura):
   ```bash
   ADMIN_USER=$(grep '^OTTIMA_ADMIN_USERNAME=' deploy/.env | cut -d= -f2)
   ADMIN_PASS=$(grep '^OTTIMA_ADMIN_PASSWORD=' deploy/.env | cut -d= -f2)
   ADMIN_TOKEN=$(curl -fsS -X POST http://localhost:8080/api/auth/login \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}" \
     | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
   curl -fsS -X POST http://localhost:8080/api/users \
     -H "Authorization: Bearer ${ADMIN_TOKEN}" -H 'Content-Type: application/json' \
     -d '{"username":"operador_e2e","name":"Operador E2E","password":"OperadorE2E#2026","role":"operator"}'
   ```
   `ADMIN_TOKEN` é reusado nos comandos `curl` de setup dos cenários B-F5-02 e B-F5-06 (tokens têm TTL de `OTTIMA_TOKEN_TTL_HOURS`; regenerar se expirar no meio da rodada).
9. **Diretório de evidências criado antes do primeiro passo**:
   ```bash
   mkdir -p .superpowers/sdd/F5-operacao/evidencias-l3
   ```

---

## 2. Regras de execução com a tool `browser`

Armadilhas confirmadas empiricamente no roteiro L3 da F4 (`docs/plans/tests-e2e-f4.md` §2) — herdadas aqui integralmente como regras obrigatórias, não sugestões. Toda ação de UI deste roteiro segue estas regras sem exceção.

1. **`tab.click`/`tab.fill`/`tab.waitFor*` aceitam APENAS seletores string** (CSS ou texto) — nunca objetos de referência de snapshot. Preferir `[data-testid="..."]`; onde o testid ainda não existe no código (todas as superfícies novas da F5 — plano F5b já escrito, mas as Etapas 1-6 ainda não implementadas —, ver notas "provável" em cada cenário), usar seletor por texto visível ou `role`+nome acessível, com o CSS como plano B documentado no passo. Convenção confirmada em `docs/plans/F5b-tela-operacao.md` (regras globais, item 2): `operate-*`, `faceplate-*`, `eventos-*`, `home-*`.
2. **`wait(ms)` é uma chamada global** da tool — não existe `tab.waitFor(ms)`. Esperas por tempo fixo (ex.: janela de confirmação de 3×Ts_mpc em B-F5-03, limiar de congelamento do watchdog em B-F5-06, polling de 5 s da Home/trend) usam a chamada `wait`; esperas por condição usam `tab.waitFor` com seletor/estado.
3. **`tab.drag(from, to)` recebe `{x, y}` como dois argumentos posicionais**, não um único objeto com dois pares de coordenadas. Nenhum cenário deste roteiro usa arraste (não há canvas nem paleta nas telas de operação/eventos/home) — regra mantida ativa do harness para o caso de a legenda do trend ou o comutador de posição ganharem interação de arraste em iteração futura.
4. **`tab.doubleClick` NÃO EXISTE.** O duplo-clique que abre o modal de configuração de bloco no editor (usado em B-F5-09 para confirmar o modo somente-leitura do operador) é disparado via `tab.evaluate`:
   ```js
   (() => {
     const el = document.querySelector('SELETOR_DO_NO');
     el.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
   })()
   ```
   `bubbles: true` é obrigatório.
5. **`tab.select` exige o `value` do `<option>`, não o texto visível.** Usado nos filtros de `/eventos` (`severity`, `origin` — F5R-24, sempre `<select>`, nunca campo de texto livre) e no seletor de janela do trend (`operate-trend-window`, provável, prefixo `operate-*` confirmado) — o `value` é o identificador técnico (`"warning"`, `"flow:59"`, `"15m"`), nunca o rótulo pt-BR exibido.
6. **Refs de `ariaSnapshot` são reusadas entre snapshots e quebram laços** (ex.: percorrer as N faceplates de variável em B-F5-02/04, ou N linhas da tabela de eventos em B-F5-07). Marcar o elemento-alvo no DOM antes de agir e clicar por seletor CSS estável, não por ref reaproveitada:
   ```js
   document.querySelectorAll('[data-testid="faceplate-var"]')[indice]
     .setAttribute('data-alvo', '1');
   ```
   seguido de `tab.click('[data-alvo="1"]')` (removendo o atributo antes da próxima iteração, ou usando `data-var-id` como seletor estável quando o testid já carrega o id da variável).
7. **Screenshot por passo relevante**: `tab.screenshot()` imediatamente após toda ação que muda o DOM de forma observável. Salvar no diretório de evidências (seção 3) com o nome exato do passo — nunca sobrescrever um screenshot de um passo anterior do mesmo cenário.
8. **[NOVA] Asserções sobre o trend uPlot nunca comparam pixels/canvas** — leem os dados que alimentam o gráfico, não a renderização. Duas vias, nesta ordem de preferência:
   - **Preferida:** `tab.evaluate` chamando o MESMO endpoint que a tela consome, com o token já em `localStorage`:
     ```js
     fetch('/api/history/mpc?flow_id=<id>&block_id=<id>&var_ids=<csv>&start=<iso>&end=<iso>', {
       headers: { Authorization: `Bearer ${localStorage.getItem('ottima.token')}` },
     }).then((r) => r.json())
     ```
     e inspecionar `t`/`v`/`sp`/`auto` do JSON diretamente — independe de detalhe de implementação do wrapper uPlot e sobrevive a refactors (`frontend/src/lib/api.ts` confirma a chave `ottima.token`).
   - **Alternativa**, só quando a instância uPlot estiver exposta pelo componente (a confirmar em `frontend/src/features/operate/TrendOperacao.tsx` — plano F5b tarefa 5.1-5.3, ainda não implementada): ler `u.data` diretamente via `tab.evaluate`.
   Usada em B-F5-05 (âncora `prediction.ts`, degrau `align:-1` das MVs, dessaturação de SP fora de AUTO).

---

## 3. Evidências

Um screenshot por passo relevante (regra 7 acima), salvo em:

```
.superpowers/sdd/F5-operacao/evidencias-l3/B-F5-XX-passoNN.png
```

`XX` = número do cenário com dois dígitos (`01`..`09`); `NN` = número do passo, também com dois dígitos, na ordem da tabela do cenário. Nomeação obrigatória e literal.

---

## 4. Cenários

**Nota geral sobre selectors "prováveis":** o código das superfícies novas da F5 (`/operacao`, `/operacao/:flowId/:blockId`, `/eventos`, Home redesenhada, nav em dois grupos) ainda não existe no branch de trabalho no momento deste draft — só o plano `docs/plans/F5b-tela-operacao.md` (Etapas 1-6). Todo `data-testid` citado abaixo que não conste da lista de testids **confirmados** (login, nav de engenharia, `flow-*`, `tag-*`, `conn-*`, `config-aplicar`, `canvas-*`, `editor-mensagens`, `annunciator`, `current-user`, `active-project` — todos conferidos no código de `frontend/src/features`/`frontend/src/app` nesta sessão) é uma previsão que respeita a convenção de prefixo já **normativa no F5b** (`operate-*`, `faceplate-*`, `eventos-*`, `home-*` — regras globais item 2) e a nomeação de componente já planejada (`OperateSelectorPage.tsx`, `OperatePage.tsx`, `FaceplatePrincipal.tsx`, `FaceplateVariavel.tsx`, `TrendOperacao.tsx`, `EventsPage.tsx`, `HomePage.tsx`/`useWorkersHealth.ts`); deve ser confirmada/ajustada contra o código real quando as Etapas 1-6 do F5b estiverem implementadas. O texto visível em pt-BR e os `role` ARIA são a fonte de verdade quando o testid não bater.

### B-F5-01 — Login operador, navegação ao grupo Operação, seletor e redirect direto

**Objetivo:** confirmar login com papel operador, a nav do shell em dois grupos (Operação · Eventos antes de Conexões · Tags · Flows · Trend), a rota `/operacao` e o redirect direto para `/operacao/:flowId/:blockId` quando há um único MPC no projeto — e que a URL sobrevive a um reload (a "sala de controle" restaura a tela).
**Rastreabilidade:** RF-701 · spec F5 §7.3-1 (rotas novas) · §7.4-1 (seletor + redirect direto) · ADR-016 · plano F5b tarefas 3.1 (nav/rotas) e 4.1 (`OperateSelectorPage.tsx`/`OperatePage.tsx`/`useMpcs.ts` — "esqueleto do B-F5-01").
**Pré-condições:** usuário operador criado (§1 item 8); ambiente com exatamente 1 bloco MPC (herdado do gate F4 — §1 item 7), o que exercita o caminho de redirect direto; o caminho do seletor com múltiplas opções não é exercitado por este ambiente (nota no passo 3).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Login: `tab.fill('[data-testid="login-username"]', "operador_e2e")`, `tab.fill('[data-testid="login-password"]', <senha do §1 item 8>)`, `tab.click('[data-testid="login-submit"]')`. | Redireciona para fora de `/login`; `[data-testid="current-user"]` (confirmado, `AppShell.tsx:41`) mostra "· operador". |
| 2 | `tab.screenshot()` da nav do shell. | Dois grupos visíveis (spec §7.3-1): "Operação · Eventos" antes de "Conexões · Tags · Flows · Trend"; `[data-testid="nav-operacao"]` e `[data-testid="nav-eventos"]` (prováveis, mesmo padrão de `nav-conexoes`/`nav-tags`/`nav-flows`/`nav-trend`, confirmados em `AppShell.tsx:9-14`) presentes; os quatro itens de engenharia continuam visíveis (RBAC é só sobre mutação, não leitura — spec §7.3-2). |
| 3 | `tab.click('[data-testid="nav-operacao"]')`. | Navega para `/operacao`. Com 1 único MPC no projeto, redirect direto para `/operacao/:flowId/:blockId` sem tela intermediária (spec §7.4-1); confirmar via `tab.evaluate` um `fetch('/api/operate/mpcs', {headers:{Authorization:'Bearer '+localStorage.getItem('ottima.token')}})` retornando array de tamanho 1 — é essa cardinalidade que explica o redirect. **Nota:** o caminho do seletor com 2+ opções (`[data-testid="operate-seletor"]`/`"operate-mpc-option"`, prováveis) não é coberto neste ambiente de 1 MPC só; registrado como lacuna de cobertura, não como bug. |
| 4 | `tab.screenshot()` da tela de operação carregada. | URL contém `/operacao/<flowId>/<blockId>`; `[data-testid="faceplate-principal"]` (provável, `FaceplatePrincipal.tsx`, plano F5b tarefa 4.3) visível com a plaqueta `nome · flow` (Regra da Plaqueta). |
| 5 | `tab.evaluate('location.reload()')`; `tab.screenshot()`. | Mesma URL sobrevive ao reload (§7.4-1, "o MPC aberto vive na URL"); faceplate recarrega sem voltar ao seletor. |

**Evidência:** `B-F5-01-passo02.png` a `B-F5-01-passo05.png` (passo 1 não gera screenshot próprio — o redirect do passo 1 já é coberto pela nav do passo 2).

---

### B-F5-02 — Faceplates: barras verticais, mono tabular, lâmpada `building` no deploy recém-feito

**Objetivo:** confirmar a barra vertical com escala/EU/limites em cada faceplate de variável, PV em mono tabular + EU, e a lâmpada de solver capturando `building` como estado de partida do deploy, em qualquer modo.
**Rastreabilidade:** RF-702 · spec F5 §7.4-3/5 · §6.2 (`building` publicado sempre) · §1.3-4 (emenda F4 §4.2/§5.1) · DESIGN §Shapes (barra vertical) + Regra do Número Tabular · plano F5b tarefas 4.3 (`FaceplatePrincipal.tsx`) e 4.4 (`FaceplateVariavel.tsx`).
**Pré-condições:** continuação de B-F5-01 (tela do MPC aberta, sessão operador); um `flow_id` conhecido do flow de teste (extraído da URL do passo 4 de B-F5-01).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Fora da tool `browser` (deploy/stop exigem `require_admin` no servidor — `services/api/src/ottima_api/routers/flows.py:262,272` —, indisponível à sessão operador aberta): `curl -fsS -X POST "http://localhost:8080/api/flows/${FLOW_ID}/stop" -H "Authorization: Bearer ${ADMIN_TOKEN}"` seguido imediatamente de `curl -fsS -X POST "http://localhost:8080/api/flows/${FLOW_ID}/deploy" -H "Authorization: Bearer ${ADMIN_TOKEN}"` (`ADMIN_TOKEN` do §1 item 8). | 202 nos dois; a sessão operador do browser permanece intacta. |
| 2 | Imediatamente após o `deploy` (a janela de `building` é curta numa malha de teste pequena — boot assíncrono, spec §6): `tab.evaluate('location.reload()')`. `tab.screenshot()`. | `[data-testid="faceplate-lampada-solver"]` (provável) mostra o estado `building`; comutadores de modo desabilitados com rótulo do motivo visível (cor + ícone + texto — Regra do Canal Redundante, nunca só cor). |
| 3 | `wait(20000)` (boot + margem); `tab.evaluate('location.reload()')`; `tab.screenshot()`. | Lâmpada de solver sai de `building` para `idle` (LOCAL, estado de partida do deploy) ou `ok` se já tiver sido armado por outro cenário anterior da rodada (§6.2: `building→idle` em LOCAL, `building→ok` em AUTO). |
| 4 | `tab.screenshot()` da fileira de faceplates de variável na base. | Um faceplate por MV/CV/Restrição/DV (RF-702); cada um com barra vertical com escala demarcada a partir de `limits`(MV)/`sp_limits`(CV)/`range`(Restrição) — convenção PV/SP/OUT intocável (DESIGN §Shapes). |
| 5 | `tab.evaluate` lendo o texto de um PV de faceplate (`document.querySelector('[data-testid="faceplate-var"] [data-testid="faceplate-pv"]').textContent`, seletor provável) e a EU ao lado. | Valor em formato mono tabular + EU visível (Regra do Número Tabular) — número sem unidade é defeito. |
| 6 | `tab.screenshot()` dos contadores `overruns` e `last_solve_ms` do faceplate principal. | Ambos em mono tabular (spec §7.4-3). |

**Evidência:** `B-F5-02-passo02.png` a `B-F5-02-passo06.png`.

---

### B-F5-03 — Armar LOCAL→REMOTO(MAN)→AUTO; pendente-até-confirmar

**Objetivo:** confirmar que MAN/AUTO só renderiza em REMOTO (ADR-010), que cada comando entra em estado pendente (fantasma + outline azul) até o `mpc.state` seguinte confirmar, e que a janela de confirmação é 3×Ts_mpc (mín. 5 s).
**Rastreabilidade:** RF-701/704 · spec F5 §7.4-3/4 · ADR-010 · DESIGN "Regra do Estado Publicado" · F5R-18 (janela estritamente maior que `CONFIRM_MISSES_LIMIT=2` ticks do runtime) · plano F5b tarefa 4.2 (redutor `pendencia.ts`) e 4.3 (comutadores de `FaceplatePrincipal.tsx`).
**Pré-condições:** continuação de B-F5-02 (solver fora de `building`); MPC em LOCAL (estado de partida do deploy, herdado do passo 3 de B-F5-02).

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.screenshot()` do comutador de posição inicial. | `[data-testid="faceplate-modo-local-remoto"]` (provável, segmented control — DESIGN §Shapes "Comutador de posição") mostra LOCAL ativo; `[data-testid="faceplate-modo-man-auto"]` (provável) **ausente** do DOM (MAN/AUTO só em REMOTO — ADR-010). |
| 2 | `tab.click` no segmento REMOTO do comutador local-remoto. `tab.screenshot()`. | 1 gesto, sem diálogo (Regra do Estado Publicado); segmento entra em pendente: outline azul (Azul Industrial) + posição comandada em fantasma. |
| 3 | `wait(<3×Ts_mpc em ms, mín. 5000>)` — Ts_mpc calculado **sem sessão admin paralela** (login admin noutra aba sobrescreveria `ottima.token` no localStorage compartilhado do browser e derrubaria a sessão operador): `tab.evaluate` com `fetch('/api/operate/mpcs', {headers: {Authorization: 'Bearer ' + localStorage.getItem('ottima.token')}})` e `Ts_mpc = multiplier × flow_ts_seconds` do item do MPC aberto (payload spec §4.1-1/2). `tab.waitFor('[data-testid="faceplate-modo-local-remoto"]')` (ou seletor de estado confirmado). | Comutador confirma REMOTO: outline/fantasma somem; `[data-testid="faceplate-modo-man-auto"]` (provável) passa a **renderizar** (ADR-010), com MAN como posição inicial (bumpless — armar em REMOTO entra em MAN). |
| 4 | `tab.screenshot()` pós-confirmação REMOTO+MAN. | Ambos comutadores em posição estável, sem pendência. |
| 5 | `tab.click` no segmento AUTO do comutador man-auto. `tab.screenshot()`. | Pendente de novo: outline azul + fantasma no segmento AUTO. |
| 6 | `wait(<mesmo cálculo do passo 3>)`; `tab.waitFor` confirmação. `tab.screenshot()`. | AUTO confirmado; lâmpada de solver evolui para `ok` em regime; entradas de SP das CVs passam a habilitadas (spec §7.4-5, só em AUTO). |

**Evidência:** `B-F5-03-passo01.png` a `B-F5-03-passo06.png`.

---

### B-F5-04 — SP em AUTO e MV em MAN: clamp, materialização e auditoria em `/eventos`

**Objetivo:** confirmar clamp client-side em `sp_limits`/`limits`, materialização no estado publicado, auditoria em `/eventos` (`mpc_sp_written`/`mpc_mv_written`) e entradas desabilitadas fora do modo correspondente.
**Rastreabilidade:** RF-704 · spec F5 §7.4-5 · RF-803/§7.5 (auditoria) · ADR-020 · plano F5b tarefa 4.4 (`FaceplateVariavel.tsx`).
**Pré-condições:** continuação de B-F5-03 (REMOTO+AUTO confirmado); pelo menos 1 CV com `sp_limits` e 1 MV com `limits` na malha de teste.

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | Com REMOTO+AUTO ativo: `tab.evaluate` lê o `sp_limits.max` exibido na escala da barra da CV; `tab.fill` na entrada de SP com um valor **acima** desse limite; confirmar (Enter ou botão de aplicar do faceplate, `[data-testid="faceplate-sp-input"]`/`"faceplate-sp-aplicar"`, prováveis). `tab.screenshot()`. | Clamp client-side reescreve o valor exibido para `sp_limits.max` antes/no submit (espelho leve; servidor é a barreira — §7.4-5), sem round-trip ao servidor com o valor fora de faixa. |
| 2 | `tab.fill` a mesma entrada com um valor válido dentro de `sp_limits`; confirmar. `tab.screenshot()`. | Entra em pendente (fantasma + outline azul, mesmo padrão de B-F5-03). |
| 3 | `wait(<3×Ts_mpc>)`; `tab.waitFor` confirmação. `tab.screenshot()`. | Valor materializado no estado publicado; nenhum fantasma remanescente. |
| 4 | `tab.click('[data-testid="nav-eventos"]')`. | Navega para `/eventos`. |
| 5 | `tab.screenshot()` da linha mais recente, expandindo o payload (`tab.click` no `<details>`). | Evento no topo com `payload.kind == "mpc_sp_written"` (`kind` vive dentro do `payload`, não é coluna — `ottima_core/bus.py:190`, `schemas/events.py`); `origin` referencia o flow/bloco. |
| 6 | Voltar à tela de operação (`tab.click` em `nav-operacao` ou navegação de volta); alternar o comutador man-auto para MAN; `wait` + confirmação (mesmo padrão de B-F5-03). `tab.screenshot()`. | MAN confirmado; entrada de SP da CV agora **desabilitada** com o valor publicado (SP em PV-tracking — F4 decisão A-4, spec §7.4-5), entrada manual da MV agora **habilitada**. |
| 7 | `tab.evaluate` lê `limits.max` da MV na barra; `tab.fill` a entrada manual com valor acima do limite; confirmar. `tab.screenshot()`. | Clamp client-side em `limits` (mesmo padrão do passo 1). |
| 8 | `tab.fill` valor válido dentro de `limits`; confirmar; `wait` + `tab.waitFor` confirmação. `tab.screenshot()`. | Materializado no estado publicado. |
| 9 | `tab.click('[data-testid="nav-eventos"]')`; expandir a linha mais recente. | `payload.kind == "mpc_mv_written"` auditado. |

**Evidência:** `B-F5-04-passo01.png` a `B-F5-04-passo09.png`.

---

### B-F5-05 — Trend: histórico sólido → linha-agora → predição sem degrau na emenda

**Objetivo:** confirmar a assinatura "tinta que ainda não secou" (histórico sólido → linha-agora → predição tracejada no mesmo matiz mais claro, sem degrau na emenda), MVs como degraus fantasma `align:-1`, SP dessaturada onde `auto=false`, janelas 15 min/30 min/2 h/8 h e legenda opt-in de MVs até o teto de 8 penas.
**Rastreabilidade:** RF-703 · spec F5 §3 (semântica da predição) · §7.4-6 (trend) · decisão A-11 (defaults) · F5R-01/16/17/21 · DESIGN "assinatura tinta que ainda não secou" · plano F5b tarefas 5.1 (`trendOperacao.ts`/`useHistoryMpc.ts`), 5.2 (overlay de predição) e 5.3 (`TrendOperacao.tsx`, defaults/legenda — "esqueleto do B-F5-05").
**Pré-condições:** continuação de B-F5-04 (REMOTO+MAN após o passo 6 — alternar de volta para AUTO antes de iniciar este cenário, `wait` + confirmação, para que a predição não esteja vazia — fora de AUTO `prediction.t=[]` e o overlay some, §3.4); o trecho anterior à confirmação do AUTO em B-F5-03 fornece o segmento `auto=false` necessário para o passo 6.

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.screenshot()` do trend central. | `[data-testid="operate-trend"]` (provável) visível; inspeção visual confirma histórico sólido → linha-cursor "agora" → trecho tracejado no mesmo matiz mais claro, desvanecendo ao horizonte (DESIGN §Overview). |
| 2 | `tab.evaluate` com `fetch('/api/history/mpc?...')` (regra 8 do §2) pedindo a janela default (30 min) para o `var_id` de uma CV. | JSON retorna `t`, `v`, `sp`, `auto` alinhados; o histórico é a base do que o trend desenha. |
| 3 | Ler `ts` e `prediction.ts` do quadro vivo. Eles **não** saem de `/api/history/mpc` (predição nunca é persistida — ADR-016): `tab.evaluate` abre um WebSocket temporário autenticado no contexto da página — mesmo esquema `?token=` do provider (`urlDoWs`, `useFlowStatus.ts:69-71`): `new Promise((res) => { const ws = new WebSocket(\`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws?token=${encodeURIComponent(localStorage.getItem("ottima.token"))}\`); ws.onopen = () => ws.send(JSON.stringify({subscribe: {mpc_state: ["<fid>/<bid>"]}})); ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.channel && d.channel.startsWith("mpc.state.")) { ws.close(); res({ts: d.data.ts, pts: d.data.prediction.ts, mpcTs: d.data.ts}); } }; })` — capturar 2 quadros consecutivos se precisar provar regime. | `prediction.ts == ts − Ts_mpc` em regime (§3.5, F5R-01 — a âncora do overlay nunca é o `ts` do quadro; mesma prova do teste de âncora §9.1, aqui via dado vivo + inspeção visual do passo 4). |
| 4 | `tab.screenshot()` com foco na emenda histórico/predição (a linha "agora"). | Ausência visual de degrau na emenda — a predição começa no valor "agora", não um passo adiante nem atrás (F5R-01). |
| 5 | `tab.screenshot()` da(s) MV(s) no trend. | MVs renderizadas como degraus fantasma alinhados à esquerda (`stepped align:-1` — §3.3; `align:+1` é proibido, deslocaria o plano em 1×Ts_mpc). |
| 6 | `tab.evaluate` no `fetch` do passo 2 localizando, no array `auto`, o trecho anterior à confirmação do AUTO (B-F5-03, passo 6) — deve conter `false`. `tab.screenshot()` desse trecho da pena de SP. | Pena de SP dessaturada no trecho `auto=false` (SP em PV-tracking não é SP comandado — §2.2-1, F5R-21); saturada no trecho `auto=true` seguinte. |
| 7 | `tab.select('[data-testid="operate-trend-window"]', "15m")` (provável, mesmo padrão de `value` técnico de `trend-window` da engenharia — regra 5 do §2); repetir com `"8h"`. `tab.screenshot()` de cada. | Janela muda; `tab.evaluate` refazendo o `fetch` confirma `start`/`end` compatíveis com a janela selecionada (15 min · 30 min · 2 h · 8 h — default 30 min, spec §7.4-6). |
| 8 | `tab.screenshot()` da legenda do trend (`[data-testid="operate-trend-legend"]`, provável). | CVs (PV+SP) ligadas por default até o teto de 8 penas, na ordem do config; MVs aparecem desligadas por default (opt-in, decisão A-11). |
| 9 | `tab.click` num item de legenda de MV desligada (`[data-testid="operate-trend-legend-item"][data-var-id="<mv_id>"]`, provável). `tab.screenshot()`. | Pena da MV aparece no trend após o clique. |

**Evidência:** `B-F5-05-passo01.png` a `B-F5-05-passo09.png`.

---

### B-F5-06 — Watchdog congelado: alarme na faixa em qualquer tela; restaurar cessa

**Objetivo:** confirmar que a faixa anunciadora é do shell (aparece em qualquer tela, não só na de operação) ao congelar o watchdog do opcsim, e que a família "par de eventos" (`comm_failure`→`comm_restored`) cessa quando o par com a mesma `origin` chega.
**Rastreabilidade:** RF-705 · spec F5 §7.2 (tabela de cessação, família "par de eventos") · ADR-009 (watchdog bit alternante) · ADR-020 · plano F5b tarefa 2.4 (`AnnunciatorBar.tsx` real — "esqueleto do B-F5-06").
**Pré-condições:** conexão `opcsim-l3` ativa e íntegra (watchdog alternando); testado numa tela de **engenharia**, não na de operação — o banner é do shell (spec §7.1-3, `events` sempre assinado). Nós opcsim confirmados em `tests/opcsim/src/opcsim/server.py`: `ns=2;s=sim.control.freeze_watchdog` (bool, escrevível), `ns=2;s=sim.watchdog.to_system`/`from_system` (leitura). Endpoint: `opc.tcp://127.0.0.1:4840/ottima/opcsim/` (porta do host via `deploy/docker-compose.e2e.yml`, default 4840).

Comando de escrita (fora da tool `browser`; `asyncua` e o pacote `opcsim` são membros do workspace uv — `uv run python` na raiz do repo os alcança):
```bash
uv run python -c "
import asyncio
from asyncua import Client

async def escrever(valor: bool) -> None:
    async with Client(url='opc.tcp://127.0.0.1:4840/ottima/opcsim/') as client:
        await client.get_node('ns=2;s=sim.control.freeze_watchdog').write_value(valor)

asyncio.run(escrever(True))   # True congela (passo 2); False restaura (passo 6)
"
```

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.click('[data-testid="nav-conexoes"]')` (tela de engenharia, não `/operacao`). `tab.screenshot()` de `[data-testid="annunciator"]` (confirmado, `AnnunciatorBar.tsx:6`). | Colapsado: "Sem alarmes ativos" ou equivalente. |
| 2 | Fora da tool `browser`: rodar o comando acima com `valor=True`. | Rung do watchdog para de alternar. |
| 3 | `wait(20000)` (limiar de congelamento fixo de produção: >10 s, plano F2 tarefa 2.1 — não configurável — mais margem de detecção/propagação WS). | — |
| 4 | `tab.waitFor` mudança em `[data-testid="annunciator"]` (ainda em `/engenharia/conexoes`, nenhuma navegação nova). `tab.screenshot()`. | Faixa deixa de estar colapsada: contagem por severidade (`alarm`) + lista expansível com cor + ícone + texto (Regra do Canal Redundante); origem referencia a conexão `opcsim-l3`. |
| 5 | `tab.click` na faixa. `tab.screenshot()`. | Navega para `/eventos` (spec §7.2-4); evento `payload.kind == "comm_failure"` no topo. |
| 6 | Fora da tool `browser`: rodar o comando acima com `valor=False`. | Rung volta a alternar. |
| 7 | `wait(10000)` (nova alternância + `comm_restored`, sessão já `up`). Se a MV da malha sofreu shed durante a falha, `curl` admin (mesmo padrão de B-F5-02, passo 1) para `stop`+`deploy` do flow, restaurando o armado. | `comm_restored` publicado com a mesma `origin` do `comm_failure` (F5R — par de eventos). |
| 8 | `tab.waitFor` `[data-testid="annunciator"]` voltar a colapsado. `tab.screenshot()`. | "Sem alarmes ativos" de novo — cessação da família (spec §7.2 tabela). |

**Evidência:** `B-F5-06-passo01.png`, `B-F5-06-passo04.png`, `B-F5-06-passo05.png`, `B-F5-06-passo08.png` (passos 2/3/6/7 são bash/wait, sem screenshot).

---

### B-F5-07 — `/eventos`: filtros, origem por select, prepend ao vivo, payload expansível

**Objetivo:** confirmar filtros combináveis (severidade, origem, período), que o filtro de origem é sempre um `<select>` (nunca texto livre), o prepend ao vivo com marca de recém-chegado quando sem filtro de período, e o payload expansível em `<details>`.
**Rastreabilidade:** RF-803 · spec F5 §7.5 · F5R-24 (origem por select) · plano F5b tarefa 3.3 (`EventsPage.tsx`/`eventos.ts`).
**Pré-condições:** eventos já existentes no log (herdados de B-F5-04/06: `mpc_sp_written`, `mpc_mv_written`, `comm_failure`, `comm_restored`); sessão operador ativa.

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.click('[data-testid="nav-eventos"]')` (se não já lá). `tab.screenshot()`. | `[data-testid="eventos-tabela"]` (provável) com linhas em ordem `ts` desc; colunas severidade (lâmpada + texto), origem, mensagem. |
| 2 | `tab.select('[data-testid="eventos-filtro-severidade"]', "warning")` (provável — `value` técnico, regra 5 do §2, endpoint confirmado em `routers/events.py:29`: `Literal["info","warning","alarm"]`). `tab.screenshot()`. | Lista filtra: só linhas `severity=warning`. |
| 3 | `tab.screenshot()` do controle de origem antes de interagir. | É um `<select>` (`[data-testid="eventos-filtro-origem"]`, provável) — nunca um campo de texto livre (F5R-24; `routers/events.py:43-44` filtra por igualdade exata). |
| 4 | `tab.select` escolhendo uma origem conhecida por `value` (ex. `"flow:<flow_id>"`). `tab.screenshot()`. | Lista filtra por igualdade exata da `origin`. |
| 5 | `tab.fill` início/fim de período (`[data-testid="eventos-filtro-inicio"]`/`"eventos-filtro-fim"`, prováveis) com uma janela que cubra os eventos herdados. `tab.screenshot()`. | Consulta histórica pura ativa (§7.5-2) — sem prepend a partir daqui. |
| 6 | Limpar o filtro de período (botão ou re-selecionar vazio); repetir o comando de escrita de B-F5-06 (`valor=True` seguido, após alguns segundos, de `valor=False`) para gerar 1 evento novo rapidamente; observar a tabela sem interação adicional. `tab.waitFor` uma nova linha no topo. `tab.screenshot()`. | Evento novo entra no topo via WS, com marca de recém-chegado (`[data-testid="eventos-novo"]` ou classe equivalente, provável) — sem reload. |
| 7 | `tab.click` no `<details>` da linha mais recente. `tab.screenshot()`. | Expande mostrando o `payload` JSON com `kind` (`payload.kind`, não é coluna própria — `schemas/events.py`). |

**Evidência:** `B-F5-07-passo01.png` a `B-F5-07-passo07.png`.

---

### B-F5-08 — Home: lâmpadas dos 3 workers via polling; parar o recorder derruba a lâmpada

**Objetivo:** confirmar que a Home mostra lâmpadas de estado (nunca só cor) para opc-worker/flow-runtime/recorder via `GET /api/health/workers` com polling de 5 s, e que parar um serviço do compose derruba a lâmpada correspondente.
**Rastreabilidade:** RNF-07 · spec F5 §7.3-3 · decisão A-8/A-10 · plano F5b tarefa 3.2 (`HomePage.tsx` + `useWorkersHealth.ts` — "esqueleto do B-F5-08").
**Pré-condições:** sessão operador ativa (Home é leitura, sem RBAC de mutação — spec §7.3-2); os 3 serviços up antes do início. `HomePage.tsx` atual (`frontend/src/app/HomePage.tsx`) só mostra `[data-testid="active-project"]` — a visão geral com lâmpadas é a tarefa 3.2 do F5b, ainda não implementada.

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.click` no item de nav que leva à raiz `/` (logo/plaqueta do header, ou navegação direta). `tab.screenshot()`. | Home carrega; `[data-testid="active-project"]` (confirmado) ainda presente, ou substituído por um componente equivalente na visão geral redesenhada — conferir contra o código real da tarefa 3.2. |
| 2 | `tab.screenshot()` da seção de workers. | `[data-testid="home-workers"]` (provável) com 3 lâmpadas — `[data-testid="home-worker-lamp"][data-worker="opc-worker"\|"flow-runtime"\|"recorder"]` (prováveis) — cada uma quadrado + ícone + rótulo (DESIGN §Shapes "Lâmpada de estado", nunca só cor); todas "up"/rodando (verde mutado só na lâmpada). |
| 3 | `tab.screenshot()` da lista de flows do projeto ativo. | "Último estado" por flow (padrão F3 §6.1); atalho para `/operacao/:flowId/:blockId` no flow com MPC. |
| 4 | Fora da tool `browser`: `docker compose -f docker-compose.yml -f docker-compose.e2e.yml stop recorder` a partir de `deploy/`. | Container do recorder para. |
| 5 | `wait(10000)` (próximo ciclo de polling de 5 s + margem). `tab.waitFor` mudança na lâmpada do recorder (ou `tab.evaluate('location.reload()')` se o polling client-side não bastar). `tab.screenshot()`. | Lâmpada do recorder muda para down/indisponível — mudança de texto/ícone, não só de cor (`GET /api/health/workers` responde `{recorder: {up: false}}`, sempre 200 — spec §4.2-2). |
| 6 | Fora da tool `browser`: `docker compose -f docker-compose.yml -f docker-compose.e2e.yml start recorder` a partir de `deploy/`. | Container volta. |
| 7 | `wait(10000)`; `tab.waitFor`/reload; `tab.screenshot()`. | Lâmpada do recorder volta a up. |

**Evidência:** `B-F5-08-passo01.png`, `B-F5-08-passo02.png`, `B-F5-08-passo03.png`, `B-F5-08-passo05.png`, `B-F5-08-passo07.png`.

---

### B-F5-09 — RBAC: operador opera, mas não vê mutações de engenharia

**Objetivo:** confirmar que o papel operador opera modos/SP/MV (já demonstrado em B-F5-03/04, aqui é conferência rápida) e **não** vê nenhuma superfície de mutação de engenharia em Conexões/Tags/Flows — nem no editor de flow, nem no modal de config de bloco.
**Rastreabilidade:** RF-003 · RF-002 (criação do usuário, §1 item 8) · ADR-015 · spec F5 §7.3-2 · plano F5b tarefa 3.1 ("telas de engenharia intocadas — mutação só admin").
**Pré-condições:** usuário operador (§1 item 8) na sessão ativa desde B-F5-01; usuário admin (seed) disponível para o passo 7. RBAC de mutação **já implementado desde F1-F4** via `useCanMutate()`/`podeMutar` (`frontend/src/features/auth/useAuth.tsx:81-83`) — confirmado em código, não previsão: `ConnectionsPage.tsx:126,134,166,217`, `TagsPage.tsx:46,88,173,223`, `FlowsPage.tsx:241,249,283,341`, `FlowEditorPage.tsx:190,407,435,462-465`, `ModalConfigBloco.tsx:121,213-217,267`, `MpcModal.tsx:96,214-218,339`. O que este cenário confirma é que a F5 não regrediu essa gate ao introduzir a nav em dois grupos.

| # | Ação / estratégia | Assert |
|---|---|---|
| 1 | `tab.screenshot()` da tela de operação ainda aberta (comutadores/entradas do passo final de B-F5-04). | Comutadores de modo e entradas de SP/MV habilitados conforme o modo atual — já demonstrado em B-F5-03/04; aqui só conferência antes de trocar de foco. |
| 2 | `tab.click('[data-testid="nav-conexoes"]')`. `tab.screenshot()`. | `[data-testid="conn-new"]` (confirmado, `ConnectionsPage.tsx:135`) **ausente** do DOM — não `disabled`, `podeMutar` remove o botão inteiro; coluna de Ações ausente na tabela. |
| 3 | `tab.click('[data-testid="nav-tags"]')`. `tab.screenshot()`. | `[data-testid="tag-new"]`/`"tag-edit"`/`"tag-delete"` (confirmados, `TagsPage.tsx:90,251,259`) ausentes. |
| 4 | `tab.click('[data-testid="nav-flows"]')`. `tab.screenshot()`. | `[data-testid="flow-new"]` (confirmado, `FlowsPage.tsx:251`) ausente; coluna de Ações (Deploy/Parar/Excluir) ausente — e não é só ocultação client-side: `POST /api/flows/{id}/deploy`/`/stop` exigem `require_admin` no servidor (`routers/flows.py:262,272`), 403 se forçado via API. |
| 5 | `tab.click('[data-testid="flow-abrir"]')` no flow de teste. `tab.screenshot()`. | `[data-testid="flow-salvar"]` (confirmado, `FlowEditorPage.tsx:408`) ausente; paleta de blocos ausente (`podeMutar && <FlowPalette>`, linha 435); nós do canvas não arrastáveis/conectáveis (`nodesDraggable`/`nodesConnectable=false`, linhas 462-463). |
| 6 | Duplo-clique via workaround (regra 4 do §2) num nó do canvas para abrir o modal de config. `tab.screenshot()`. | Modal abre em **somente leitura**: `fieldset disabled` + aviso "Somente leitura: a edição do flow é do papel admin." (`ModalConfigBloco.tsx:213-217`/`MpcModal.tsx:214-218`); `[data-testid="config-aplicar"]` ausente. |
| 7 | Logout (`tab.click('[data-testid="logout"]')`); login admin (credenciais de `deploy/.env`, §1 item 4). Repetir os passos 2-4 nas mesmas telas. `tab.screenshot()` de cada. | Botões de criar/editar/excluir/deploy/parar agora presentes — prova de que a ausência anterior é RBAC, não bug de renderização. |
| 8 | Logout admin; login operador de volta (mesmas credenciais do passo 1 de B-F5-01) — housekeeping, sem screenshot. | Sessão operador restaurada para o fim da rodada. |

**Evidência:** `B-F5-09-passo01.png` a `B-F5-09-passo06.png`; o passo 7 gera 3 screenshots — `B-F5-09-passo07a.png` (Conexões), `B-F5-09-passo07b.png` (Tags), `B-F5-09-passo07c.png` (Flows), padrão de sufixo herdado de B-F4-07 passo 2 (passo 8 é housekeeping, sem evidência — mesmo padrão de B-F4-04 passo 7).

---

## 5. O que este roteiro NÃO cobre

- **Validações numéricas de convergência** (bumpless, precedência Restrição×CV, overrun de solver em regime) — cobertas pela L2 (`E2E-F5-01..07`, spec §9.2), que fala com a API real e o opcsim; este roteiro só confirma que a UI reflete o estado publicado, não a correção numérica do MPC.
- **Latências do F-1** (boot assíncrono do worker não bloquear `stop`/`deploy` de outro flow; `stop` durante build não deixar processo órfão) — medidas em `pytest` de `flow-runtime` com clock controlado (spec §9.1) e no cenário `E2E-F5-05` do L2; B-F5-02 só observa visualmente a lâmpada `building`, sem medir tempo.
- **Golden `mpcLogic` Python→TS** (§7.6, F-3) — `mpcLogic.golden.check.ts` contra `mpcLogic.golden.json` (plano F5b Etapa 6), parte de `npm run test:unit`; sem superfície de browser.
- **Formas de API** (422/404 de `/api/history/mpc`, `/api/operate/mpcs`, `/api/health/workers`; handler global de enum inválido; RBAC de rota) — cobertas por `pytest` da API (spec §9.1) e por `E2E-F5-02/03/07` do L2; este roteiro só exercita os caminhos felizes e os clamps client-side, nunca chama a API fora da UI (exceto os `curl` de setup, que não são o objeto sob teste).

---

## 6. Ordem de gate

Tabela de execução da rodada de gate completa (plano F5b, Etapa 7, tarefa 7.1). Qualquer vermelho em qualquer linha interrompe a rodada: corrigir, e reiniciar a rodada inteira desde `down -v` (só com autorização explícita + dump prévio, spec F5 §9.3) — nunca pular direto para a camada seguinte com uma pendência aberta.

| Ordem | Camada | Comando / ação | Critério de passagem |
|---|---|---|---|
| 1 | Testes de workspace (pytest + ruff) | `uv run pytest` (workspace, incl. `-m slow` uma vez — plano F5b tarefa 7.1) + `uv run ruff check . && uv run ruff format --check .` | 100% verde, zero warning de lint |
| 2 | Frontend build/unit | `cd frontend && npm run build && npm run test:unit` | build sem erro de tipo; testes puros verdes (`resolverAlarmes`, canal único, clamps, montagem de séries do trend, golden `mpcLogic` — spec §9.1) |
| 3 | L1 — smoke | `OTTIMA_E2E=1 bash deploy/smoke.sh` | smoke completo, incl. `GET /api/health/workers` com os 3 `up: true` e retenção de `mpc_samples`/`mpc_samples_1m` em `timescaledb_information.jobs` |
| 4 | L2 — 41 cenários | `uv run pytest -m e2e tests/e2e -v` | 41/41 verdes (34 herdados de F1-F4 + 7 novos `E2E-F5-01..07`) |
| 5 | Playwright F1 | `cd frontend && npm run e2e` (credenciais `E2E_ADMIN_USERNAME`/`E2E_ADMIN_PASSWORD` inline) | regressão F1 verde; **serializado** com a L2 |
| 6 | **L3 — este roteiro** | Execução manual do controlador com a tool `browser`, cenários B-F5-01 a B-F5-09, screenshot por passo | todos os cenários verdes, evidências completas no diretório da seção 3 |

**Encerramento da fase:** só depois da linha 6 verde na mesma rodada das linhas 1-5, com `.superpowers/sdd/F5-operacao/RELATORIO-GATE-F5.md` documentando a rodada (padrão herdado de F3/F4, plano F5b tarefa 7.2), a fase F5 pode ser dada como pronta para revisão de merge.
