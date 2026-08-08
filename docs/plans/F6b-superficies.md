# Plano F6b — Superfícies (Projetos, certificados, pendências, EU, DV)

> **Para executores agênticos:** execução tarefa a tarefa com subagente por tarefa + revisão independente (padrão F3/F4/F5, skill subagent-driven-development; ledger em `.superpowers/sdd/F6b-superficies/progress.md`). Checkboxes das tabelas rastreiam conclusão. **Pré-requisito: plano F6a concluído** (Etapa 6 do F6a verde) — este plano consome os contratos, rotas e tipos gerados de lá. **Toda tarefa que entrega UI termina com validação browser feita pelo controlador** (tool nativa `browser`, screenshot por passo — a tool é bloqueada a subagentes; o subagente implementa, o controlador valida na revisão).

**Fase:** F6 (PRD §8) — **última fase da v1** · plano 2 de 3 (decisão A-1; mapa §12 da spec) · 2026-08-07
**Executa:** `docs/specs/F6-portabilidade-hardening.md` §6 inteira (inclui §6.0), §4.1 (frontend), §4.2 (faceplate) e a fatia frontend de §9.1 — backend e schema são do F6a; a suíte RNF-09, os cenários E2E-F6 e o guia são do F6c
**Fontes normativas:** `docs/PRD.md` v1.4 · `docs/adr/ADR-001…024` (prevalecem) · `docs/GLOSSARY.md` (com as duas entradas novas da Etapa 0 do F6a) · `PRODUCT.md`/`DESIGN.md` (**autoridade visual**) · specs F1-F5 · spec F6
**Objetivo:** RF-101 ganha superfície (`/engenharia/projetos` com CRUD, ativar, exportar e importar), RF-202 ganha UI (certificado de aplicação + trust por conexão), a pendência de segredo fica visível antes de a conexão falhar, EU aparece nas portas de Script/TFS, a DV ganha barra, e os 6 débitos de frontend da F5 fecham. Sem isto o aceite da fase é inatingível pela UI (spec §1-3).
**Stack:** nenhuma dependência frontend nova. React/react-router/@tanstack/react-query/uPlot já presentes; `components/ui/{button,card,input,label,select}` é todo o design system que existe (não há Modal/Table/Lâmpada compartilhados — o que se reusa é o *padrão*, copiado com adaptação, §6.1-9).

## Regras globais

Idênticas ao plano F6a (governança, worktree `ottimaSystemV3-f6`/branch `f6-portabilidade`, ciclo verde por etapa, TDD com prova RED em lógica pura, **caminho absoluto em toda edição de subagente**, credenciais inline, lacuna ⇒ perguntar), mais:

1. **Validação browser por tarefa de UI** contra o stack composto (`cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --no-deps frontend`), em `http://localhost:8080`; screenshot por passo. O roteiro completo B-F6 (`docs/plans/tests-e2e-f6.md`) roda só no gate da fase (plano F6c) — a validação por tarefa é o esqueleto do cenário correspondente, não o roteiro inteiro.
2. **`data-testid` novos são estáveis e semânticos**, criados junto com o componente — o roteiro L3 depende deles. Prefixos desta fase: **`proj-*`** (página de Projetos), **`import-*`** (fluxo de import), **`cert-*`** (certificados), **`conn-pendencia*`** (coluna de pendências); os existentes (`conn-*`, `tag-*`, `flow-*`, `operate-*`, `faceplate-*`, `eventos-*`, `home-*`, `nav-*`, `config-*`, `mpc-*`) seguem intocados.
3. **Vocabulário de tela é o do GLOSSARY**: a UI diz **"arquivo de projeto"**; a palavra **"bundle" é proibida em qualquer string pt-BR** (§1.3-8). Sem emojis.
4. **Autoridade visual é `DESIGN.md`**: campo grafite, chapas (`Card`), linhas 1px (`border-hairline`), plaqueta (classe utilitária `plaqueta`) em rótulo de tag/equipamento, mono tabular (`process-value`) em todo valor e identificador técnico, cor reservada a estado e ao Azul Único (`text-accent`/`border-accent`), severidade **sempre** com canal redundante (cor + ícone + texto).
5. **Testes puros em arquivos `*.check.ts` colocalizados** (`npm run test:unit` ⇒ `playwright test -c playwright.unit.config.ts`), padrão do repo (17 arquivos hoje).
6. **DoD do plano:** §Aderência ao final; o aceite da FASE fecha no F6c.

## Interfaces consumidas (produzidas no F6a — não redefinir)

`frontend/src/lib/api-types.ts` e `contracts.gen.ts` regenerados (F6a tarefa 6.1), com `ProjectImportIn`/`ProjectImportOut`/`PendingSecretOut` e `DvOut.range` · `GET /api/projects/{id}/export` (attachment, `Content-Disposition`) · `POST /api/projects/import` (201 `ProjectImportOut`; 413 teto de 4 MiB; 409 nome em uso; 422 `detail` string única agregada com separador **` | `**) · `GET /api/health` com `redis_ok`/`db_ok` · `output_eu` aceito em `data` de `script`/`tfs` · `DvVar.range` opcional projetado em `GET /api/operate/mpcs`.

Já existentes e consumidos sem alteração de contrato: `GET /api/certificates/app`, `POST /api/certificates/app/generate`, `GET /api/certificates/app/export`, `POST`/`DELETE /api/connections/{id}/server-certificate` (entregues na F2, **sem nenhum consumidor React até hoje**), `GET`/`POST`/`PATCH`/`DELETE /api/projects` e `POST /api/projects/{id}/activate` (entregues na F1, idem).

## Interfaces internas deste plano (contratos entre tarefas — decididos antes do dispatch, assinaturas exatas)

```ts
// frontend/src/lib/api.ts (tarefa 1.1) — helper existente, duas mudanças
export async function apiResposta(path: string, init?: RequestInit): Promise<Response>;
// ^ auth + interceptor 401 + ApiError, devolvendo a Response crua (para blob/headers)
export async function api<T>(path: string, init?: RequestInit): Promise<T>;  // agora usa apiResposta
// Content-Type: JSON só quando o chamador NÃO definiu o header (hoje `api.ts:48` sobrescreve sempre)

// frontend/src/lib/arquivos.ts (tarefa 1.2) — os dois primitivos de §6.0-2/3
export function nomeDoContentDisposition(header: string | null): string | null;  // puro
export async function baixarArquivo(path: string, nomePadrao: string): Promise<void>;
export async function enviarBinario<T>(path: string, arquivo: File, tipo: string): Promise<T>;
export async function lerJsonDeArquivo(arquivo: File): Promise<unknown>;  // File.text() + JSON.parse

// frontend/src/features/projects/useProjects.ts (tarefa 1.3)
export const CHAVE_PROJETOS = ["projects"] as const;
export function useProjects(): UseQueryResult<ProjectOut[]>;
export function useActiveProject(): UseQueryResult<ProjectOut | null>;   // MOVIDO de useConnections.ts
export function useCreateProject(); export function useUpdateProject(); export function useDeleteProject();
export function useActivateProject();   // invalida projects+connections+tags+flows+operate.mpcs
export function useImportProject();     // idem; devolve ProjectImportOut

// frontend/src/features/connections/pendencias.ts (tarefa 1.4) — os 3 predicados, um lugar de verdade
export type Pendencia = "senha" | "certificado_servidor" | "certificado_aplicacao";
export function pendenciasDaConexao(
  conexao: Pick<ConnectionOut, "auth_mode" | "has_password" | "security_policy" | "server_cert_file">,
  appCertExiste: boolean | null,   // null = não avaliável (operador não lê /certificates/app)
): Pendencia[];
export function pendenciasDoResumo(p: PendingSecretOut): Pendencia[];
export const ROTULO_PENDENCIA: Record<Pendencia, string>;
export const EFEITO_PENDENCIA: Record<Pendencia, string>;   // texto do `title`, efeito exato

// frontend/src/features/certificates/useAppCertificate.ts (tarefa 3.1)
export const CHAVE_CERT_APP = ["certificates", "app"] as const;
export function useAppCertificate(habilitado: boolean): UseQueryResult<AppCertificateOut>;
export function useGenerateAppCertificate();   // { force: boolean } -> AppCertificateGenerateOut

// frontend/src/features/connections/useServerCertificate.ts (tarefa 3.2)
export function useTrustServerCertificate();   // { id, arquivo: File } -> ServerCertificateOut
export function useClearServerCertificate();   // id -> void

// frontend/src/features/flows/graph.ts (tarefa 5.1) — DadosScript/DadosTfs ganham o campo plano
export type DadosScript = DadosBase & { n_inputs: number; n_outputs: number; code: string;
  output_eu: Record<string, string> };
export type DadosTfs = DadosBase & { matrix: MatrizTfs; output_eu: Record<string, string> };
export type VariavelDv = { id: string; name: string; eu: string; range: FaixaMpc | null };
```

**Decisão de RBAC registrada (ponto de atenção, `[NOVA — implementação]`):** `GET /api/certificates/app` é `require_admin` (`certificates.py:25`, router inteiro). O terceiro predicado (`certificado_aplicacao`) depende de `exists` dessa rota, então **para o papel operador ele não é avaliável**: `useAppCertificate(habilitado)` só dispara com `useCanMutate()` verdadeiro e a coluna de pendências recebe `appCertExiste = null`, exibindo apenas os dois predicados computáveis. Nenhum RBAC de rota é alterado por este plano.

---

## Etapa 1 — Fundação: helper, primitivos de arquivo e módulos compartilhados (spec §6.0; F6R-10/11)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 1.1 | **`api()` deixa de sobrescrever `Content-Type` e passa a expor a `Response`** (§6.0-1): `api.ts:48` (`if (init?.body) headers.set("Content-Type", "application/json")`) vira `if (init?.body && !headers.has("Content-Type"))` — upload binário precisa mandar o seu; e o corpo do helper (auth, interceptor 401 de `api.ts:52-57`, `ApiError` de `:58-62`) é extraído para `apiResposta`, com `api<T>` reimplementada em cima dela preservando o tratamento de corpo vazio (`api.ts:63-66`, 204/202). Nenhum chamador existente muda de comportamento | `frontend/src/lib/api.ts` · `frontend/src/lib/api.check.ts` (novo) | RED: `api` com body e sem header ⇒ `Content-Type: application/json`; com header explícito ⇒ preservado; 401 fora de `/auth/login` ⇒ limpa token e redireciona; 204 ⇒ `undefined`; `apiResposta` devolve `Response` com headers legíveis. `npm run build` + `test:unit` verdes | §6.0-1 · F6R-10 |
| 1.2 | **Primitivos de arquivo** (§6.0-2/3): `nomeDoContentDisposition` (puro; extrai `filename="…"`, tolera aspas ausentes e header nulo); `baixarArquivo` — `apiResposta` ⇒ `res.blob()` ⇒ `URL.createObjectURL` ⇒ `<a download>` clicado ⇒ **`revokeObjectURL` e remoção do nó no `finally`**, com o nome vindo do `Content-Disposition` e fallback local (o app manda JWT em header, então `<a href>` simples não autentica); `enviarBinario` — `File.arrayBuffer()` ⇒ `Blob` no corpo com `Content-Type` explícito, **sem `FormData`** (o endpoint de trust lê corpo bruto, `connections.py:106-126`, não multipart); `lerJsonDeArquivo` — `File.text()` + `JSON.parse` com erro pt-BR **antes de qualquer requisição** | `frontend/src/lib/arquivos.ts` (novo) · `frontend/src/lib/arquivos.check.ts` (novo) | RED: `nomeDoContentDisposition('attachment; filename="planta-c-101.ottima.json"')` ⇒ o nome; sem header ⇒ `null`; header sem `filename` ⇒ `null`; `lerJsonDeArquivo` com texto inválido ⇒ rejeita com mensagem pt-BR (nunca `SyntaxError` cru); `enviarBinario` monta `Blob` com o tipo informado | §6.0-2/3 |
| 1.3 | **Módulo de projetos com CRUD e invalidação** (§6.1-8; F6R-11): `features/projects/useProjects.ts` com `CHAVE_PROJETOS` exportada e todos os hooks da seção §Interfaces. **`useActiveProject` é MOVIDO** de `features/connections/useConnections.ts:14-20` para cá (a `queryKey ["projects"]` hoje é literal não exportada); os **7** importadores (`app/CanalAoVivo.tsx`, `app/HomePage.tsx`, `features/connections/ConnectionsPage.tsx`, `features/tags/TagsPage.tsx`, `features/trend/TrendPage.tsx`, `features/flows/FlowsPage.tsx`, `features/events/EventsPage.tsx`) passam a importar do módulo novo — **`lsp` `references`/`rename_file`, nunca busca textual**, e nenhum re-export de compatibilidade fica para trás. Tabela de invalidação **verbatim de §6.1-8**: criar/renomear/excluir ⇒ `["projects"]`; **ativar** e **importar** ⇒ `["projects"]`, `["connections"]`, `["tags"]`, `["flows"]`, `["operate","mpcs"]` (prefixos — as chaves reais são `[...CHAVE, projectId]`, `useConnections.ts:24`, `useFlows.ts:29`, `useTags.ts:43`) | `frontend/src/features/projects/useProjects.ts` (novo) · `frontend/src/features/connections/useConnections.ts` · os 7 importadores · `frontend/src/features/projects/useProjects.check.ts` (novo) | RED: a lista de chaves invalidada por cada mutação bate com a tabela §6.1-8 (função pura `chavesInvalidadasPor(acao)` conferida no check); `grep -rn "useActiveProject" src` ⇒ só o módulo novo e os 7 importadores; `npm run build` verde | RF-101 · F6R-11 |
| 1.4 | **Predicados de pendência** (§6.3-1; A-4; F6R-14): `pendenciasDaConexao` com as **três** fórmulas verbatim de §3.2-8 — `senha ⇔ auth_mode === "user_password" && !has_password`; `certificado_servidor ⇔ security_policy !== "none" && !server_cert_file`; `certificado_aplicacao ⇔ (security_policy !== "none" || auth_mode === "certificate") && appCertExiste === false` (com `null` ⇒ predicado não avaliado, ver a decisão de RBAC acima). `pendenciasDoResumo` mapeia os 3 booleanos de `PendingSecretOut` no mesmo vocabulário, para o resumo do import (tarefa 2.4) reusar rótulos. `EFEITO_PENDENCIA` traz o efeito exato em pt-BR: "a conexão falhará em `cert_missing` até confiar no certificado do servidor" / "…até gerar o certificado de aplicação da instalação" / "a conexão falhará na autenticação até a senha ser reinformada" | `frontend/src/features/connections/pendencias.ts` (novo) · `frontend/src/features/connections/pendencias.check.ts` (novo) | RED: **tabela-verdade completa** — `auth_mode` (3) × `has_password` (2) × `security_policy` (2) × `server_cert_file` (2) × `appCertExiste` (3, incluindo `null`) = 72 casos conferidos contra as 3 fórmulas; caso crítico do F6R-14: `auth_mode: "certificate"` + `security_policy: "none"` + `appCertExiste: false` ⇒ **exatamente** `["certificado_aplicacao"]`; `appCertExiste: null` ⇒ nunca inclui `certificado_aplicacao` | A-4 · F6R-14 |

**Conclusão:** `npm run build` + `npm run test:unit` verdes. Nenhuma tela mudou ainda.

---

## Etapa 2 — Página `/engenharia/projetos` (spec §6.1; decisão A-13; RF-101/102/103)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 2.1 | **Rota, nav e tabela com CRUD**: rota `/engenharia/projetos` em `router.tsx` (o array de rotas hoje vai de `/engenharia/conexoes` a `/engenharia/trend`, `router.tsx:33-37`) e item novo **no início** de `NAV_ENGENHARIA` (`AppShell.tsx:16-21`), ficando `Projetos · Conexões · Tags · Flows · Trend`, testid `nav-projetos`. Tabela em chapa no padrão copiado de `ConnectionsPage.tsx:157-172` (`<Card className="overflow-hidden">` + `<table>` cru + `<th className="plaqueta …">`): colunas **Nome · Descrição · Ativo · Ações**. A lâmpada de "Ativo" usa o **Azul Industrial** (`text-accent`), **nunca** o Verde Rodando — DESIGN §Colors reserva o verde a "rodando/vivo" e projeto ativo não é execução (UX-10) —, com **ícone + rótulo "Ativo" ao lado, nunca só cor**. Mutações só com `useCanMutate()` (`useAuth.tsx:81-83`): criar e editar por formulário inline em `<Card>` (padrão `FlowForm`, `FlowsPage.tsx:38-113` — o repo não usa `<dialog>` fora do canvas), excluir com confirmação inline (padrão `conn-delete-confirm`/`conn-delete-cancel`); excluir o projeto ativo devolve 409 do servidor (`projects.py:70-72`) e a mensagem aparece na tela. **Estado vazio próprio para zero projetos** (dia 1 de uma instalação, UX-09): chapa "Nenhum projeto cadastrado" com **os dois caminhos lado a lado** — criar e importar | `frontend/src/features/projects/ProjectsPage.tsx` (novo) · `frontend/src/features/projects/ProjectForm.tsx` (novo) · `frontend/src/app/router.tsx` · `frontend/src/app/AppShell.tsx` | Browser (admin): nav mostra Projetos primeiro no grupo de engenharia; criar, renomear, editar descrição e excluir funcionam; excluir o ativo mostra a recusa; base sem projeto mostra o estado vazio com os dois caminhos. Browser (operador): `proj-new`/`proj-edit`/`proj-delete` **ausentes do DOM**. Screenshots dos 4 estados | RF-101 · A-13 · UX-09/10 |
| 2.2 | **Ativar** (§6.1-4): ação de maior consequência da tela — encerra a execução de todos os flows do projeto atual, o que numa planta é efeito físico. Diálogo de confirmação que **nomeia o projeto atual** e **lista quantos flows serão parados** (contagem de `useFlows(projetoAtivo.id)`), com o verbo no botão — **"Ativar e parar N flows"**, nunca um "OK" genérico (UX-07); com zero flows, o texto degrada para "Ativar" sem a contagem. **Não** usa o pendente-até-confirmar da operação (F5 §7.4-4): aquele padrão é para comando de malha com estado publicado; aqui a confirmação é do banco e é síncrona. Ao concluir, invalida as 5 chaves de §6.1-8 (tarefa 1.3) | `frontend/src/features/projects/ProjectsPage.tsx` · `frontend/src/features/projects/ConfirmarAtivacao.tsx` (novo) | Browser: com 2 projetos e flows rodando no ativo, o diálogo nomeia o projeto atual e a contagem; confirmar troca o ativo, para os flows e **as telas de Conexões/Tags/Flows refletem o novo projeto sem reload** (prova da invalidação); evento correspondente aparece em `/eventos`. Screenshots antes/depois | RF-101 · UX-07 · F6R-11 |
| 2.3 | **Exportar por linha** (§6.1-5): ação "Exportar" chama `baixarArquivo('/api/projects/{id}/export', '<slug>.ottima.json')` (tarefa 1.2). Só admin. Falha (422 de referência irresolvível, 403) é renderizada como erro pt-BR na tela, não como download vazio | `frontend/src/features/projects/ProjectsPage.tsx` | Browser: clicar Exportar baixa o arquivo com o nome do `Content-Disposition`; abrir o arquivo mostra `tag_ref` objeto e nenhum campo de segredo. Screenshot da linha e do arquivo aberto | RF-102 · §6.0-3 |
| 2.4 | **Importar em três passos** (§6.1-6; A-6; F6R-03): ação no cabeçalho da página. **(1)** escolher arquivo ⇒ `lerJsonDeArquivo` (erro de parse tratado no cliente, sem requisição). **(2) Prévia antes de criar**: contagem de conexões/tags/flows, **nome do projeto em campo editável pré-preenchido** com `bundle.project.name` (A-6), e — quando o arquivo contiver blocos `script` — **a lista deles com o código visível** (`<pre>` com o `code` verbatim, rolável) e uma **confirmação explícita, obrigatória, de que executarão no servidor**; sem marcar, o botão de enviar fica desabilitado. O admin nunca importa às cegas: o arquivo atravessa organizações (ADR-012) e o código importado deixa de ter autor confiável, que é a premissa do ADR-018. **(3)** enviar ⇒ sucesso mostra resumo com `pending_secrets` **agrupado por tipo** (rótulos de `pendenciasDoResumo`, tarefa 1.4) e link para `/engenharia/conexoes`; recusa parte o `detail` por **` | `** e renderiza **uma linha por problema, nunca truncado** (o `node_id` com `;` precisa sair legível — UX-06); 413 e 409 têm mensagem própria | `frontend/src/features/projects/ImportarProjeto.tsx` (novo) · `frontend/src/features/projects/importar.ts` (novo — puro: partição do `detail`, contagens, extração dos blocos Script) · `frontend/src/features/projects/importar.check.ts` (novo) | RED: partição de `"Import recusado (2 problemas) | tags[7]: … ns=2;s=TT101 … | connections[0]: …"` ⇒ 2 linhas com o `node_id` íntegro; contagem e extração de blocos `script` de um grafo de exemplo; arquivo sem Script ⇒ nenhuma confirmação exigida. Browser: prévia com contagens e código; sem marcar a confirmação o envio fica bloqueado; sucesso mostra as 3 pendências; recusa lista os problemas um por linha. Screenshots dos 3 passos + recusa | RF-103 · A-6 · A-15 · UX-05/06 |
| 2.5 | **Ponteiros para a tela nova** (§1-3, §6.1-7; FACT-01): as **três** telas que hoje dizem "Nenhum projeto ativo: ative um projeto para…" apontando para uma tela inexistente ganham link para `/engenharia/projetos` — `ConnectionsPage.tsx:174-180`, `FlowsPage.tsx:291-297` (linha de tabela) e `TagsPage.tsx:49-58` (early-return com `tag-no-project`). O **seletor de operação** ganha **condição nova**: hoje `OperateSelectorPage.tsx:46-49` diz "Nenhum bloco MPC configurado no projeto ativo" **nos dois casos**; passa a consultar `useActiveProject()` e, sem projeto ativo, exibe "Nenhum projeto ativo: ative um projeto para operar" com o mesmo link — a frase de ausência de MPC fica reservada ao caso em que há projeto ativo | `frontend/src/features/connections/ConnectionsPage.tsx` · `frontend/src/features/flows/FlowsPage.tsx` · `frontend/src/features/tags/TagsPage.tsx` · `frontend/src/features/operate/OperateSelectorPage.tsx` | Browser: com o projeto ativo desativado por troca, as 3 telas mostram o link e ele navega; `/operacao` distingue as duas mensagens (com projeto ativo sem MPC × sem projeto ativo). Screenshot de cada | §6.1-7 · FACT-01 |

**Conclusão:** `npm run build` + `test:unit` verdes; browser 2.1-2.5 com evidências.

---

## Etapa 3 — Certificados (spec §6.2; decisão A-7; RF-202, ADR-021)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 3.1 | **Chapa "Certificado da aplicação"** no topo de `/engenharia/conexoes`, **visível só para admin** (`useCanMutate`), consumindo `GET /api/certificates/app` (`AppCertificateOut`, `schemas/certificates.py:7-13`). **Mitigação de escopo (UX-04, SEC-06):** a página é recortada pelo projeto ativo (`ConnectionsPage.tsx:92-94`) mas o certificado é **da instalação** — o rótulo diz isso literalmente ("vale para todas as conexões de todos os projetos desta instalação") e a chapa é separada da tabela por um **degrau tonal**, não só por posição. `fingerprint_sha256`, `not_before`/`not_after` e `application_uri` em **mono tabular** (`process-value`) — `application_uri` (`urn:ottima:opc-worker`) é identificador técnico, mesmo tratamento que DESIGN dá a `node_id`; **plaqueta é para rótulo de equipamento/variável, não para identificador** (UX-02). Ausente ⇒ estado explícito + botão **Gerar**; presente ⇒ **Baixar .der** (`baixarArquivo('/api/certificates/app/export', 'ottima.der')`) e **Regerar**. **Regerar** manda `force: true`, exige confirmação e **lista as conexões afetadas** antes de executar — as que têm `security_policy !== "none"` **ou** `auth_mode === "certificate"`, computável no cliente com a lista já carregada (SEC-06); ao voltar, exibe o `warning` de re-trust do backend **verbatim** (`certificates.py:28-31`). 500 com `_MSG_ILEGIVEL` (`certificates.py:33-36`) é estado de erro com **cor + ícone + texto** (Regra do Canal Redundante), não texto solto (UX-03) | `frontend/src/features/certificates/ChapaCertificadoApp.tsx` (novo) · `frontend/src/features/certificates/useAppCertificate.ts` (novo) · `frontend/src/features/certificates/certificados.ts` (novo — puro: `conexoesAfetadasPorRegeracao`) · `frontend/src/features/certificates/certificados.check.ts` (novo) · `frontend/src/features/connections/ConnectionsPage.tsx` | RED: `conexoesAfetadasPorRegeracao` inclui `security_policy != none`, inclui `auth_mode == certificate` com policy `none`, exclui anônima sem segurança. Browser (admin): sem certificado ⇒ estado + Gerar; após gerar ⇒ metadados em mono, Baixar e Regerar; Regerar lista as conexões e mostra o aviso de re-trust. Browser (operador): a chapa **não aparece**. Screenshots | RF-202 · A-7 · UX-02/03/04 · SEC-06 |
| 3.2 | **Trust do certificado do servidor por linha** (§6.2-2/3): ações "Confiar certificado" (upload via `enviarBinario` com `Content-Type` de certificado — o endpoint lê corpo bruto, `connections.py:250-298`) e "Deixar de confiar" (`DELETE`, idempotente, `connections.py:301-308`). O `fingerprint_sha256` devolvido (`connections.py:292-298`) é exibido em mono tabular **para conferência contra o servidor**. Teto de **64 KiB espelhado no cliente** (`connections.py:42`, `MAX_SERVER_CERT_BYTES`) com mensagem pt-BR antes de enviar — o servidor continua sendo a barreira (413) | `frontend/src/features/connections/useServerCertificate.ts` (novo) · `frontend/src/features/connections/ConnectionsPage.tsx` | Browser (admin): confiar num `.der` do opcsim ⇒ fingerprint exibido, coluna de pendência do certificado do servidor apaga, conexão sobe; deixar de confiar ⇒ volta a pendência; arquivo > 64 KiB ⇒ recusado no cliente. Screenshots | RF-202 · ADR-021 |

**Conclusão:** `npm run build` + `test:unit` verdes; browser 3.1-3.2 com evidências.

---

## Etapa 4 — Pendência de segredo na tabela de Conexões (spec §6.3; decisão A-4)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 4.1 | **Coluna "Pendências"** em `ConnectionsPage` (`COLUNAS`, `ConnectionsPage.tsx:33-41`, ganha a entrada antes de "Último estado"), alimentada por `pendenciasDaConexao` (tarefa 1.4). **Ícone + rótulo em Texto Secundário (`text-fg-muted`), SEM cor de severidade** (UX-01): âmbar é reservado a advertência de processo (DESIGN §Severity) e pendência é estado de **configuração** — no cenário de aceite toda conexão importada acenderia ao mesmo tempo, transformando a Regra da Cor Anormal em ruído permanente. A falha real, quando a conexão tentar subir, já aparece em âmbar/vermelho na coluna "Último estado" (`conn-last-state`), que é o canal correto. `title` por pendência com o **efeito exato** (`EFEITO_PENDENCIA`); sem pendência, célula neutra. Resolver é o que já existe: modal de conexão para a senha, ação de trust (tarefa 3.2) para o certificado do servidor, chapa (tarefa 3.1) para o certificado de aplicação. **Efeito colateral pretendido:** conserta um buraco anterior à F6 — conexão criada à mão sem certificado hoje fica muda até o worker falhar | `frontend/src/features/connections/ConnectionsPage.tsx` | Browser: projeto recém-importado ⇒ as três pendências visíveis, **nenhuma em cor de severidade**; `title` mostra o efeito; resolver cada uma faz a respectiva sumir sem reload; conexão anônima sem segurança ⇒ célula neutra. Screenshots antes/depois de resolver | A-4 · UX-01 |

**Conclusão:** `npm run build` + `test:unit` verdes; browser 4.1 com evidências.

---

## Etapa 5 — EU nas portas e faceplate de DV (spec §4.1 frontend, §4.2, §6.4/§6.5)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 5.1 | **`output_eu` no editor** (§4.1-2/4; F6R-09; FE-02): `DadosScript` (`graph.ts:54`) e `DadosTfs` (`graph.ts:68`) ganham `output_eu: Record<string, string>` — o `data` do nó React Flow é **plano**, não há objeto `config` aninhado, e sem o campo aqui o dado não persiste (`paraGraphJson`, `graph.ts:529-545`, emite `data` verbatim) e o servidor recusa chave desconhecida com 422 (`parse.py:251-255`). `lerNo`/`deGraphJson` (`graph.ts:603-690`) leem o campo com default `{}` — flow salvo antes da F6 continua abrindo. No `ModalConfigBloco`, um campo de unidade **por porta de saída** (opcional, `Label` com a classe `plaqueta` como rótulo): TFS ⇒ dois campos fixos (`y1`, `y2`); Script ⇒ N campos conforme `n_outputs`, o que exige tornar **apenas** o select `config-n-outputs` (`ModalConfigBloco.tsx:80-82`) **controlado** — o modal é hoje deliberadamente não-controlado, lendo tudo por `FormData` no submit (`ModalConfigBloco.tsx:151-198`); a leitura dos campos de EU segue por `FormData`, só a contagem de campos vira estado. Reduzir `n_outputs` **descarta** as EUs das portas que deixaram de existir (o servidor recusaria `OUT3` com `n_outputs: 2`) | `frontend/src/features/flows/graph.ts` · `frontend/src/features/flows/config/ModalConfigBloco.tsx` · `frontend/src/features/flows/config/CamposTfs.tsx` · `frontend/src/features/flows/graph.check.ts` | RED: round-trip `paraGraphJson`/`deGraphJson` preserva `output_eu`; nó antigo sem a chave ⇒ `{}`; reduzir `n_outputs` de 3 para 2 poda `OUT3`. Browser: declarar `t/h` em OUT1 de um Script e `C` em y1 do TFS, aplicar, salvar, reabrir ⇒ valores preservados; servidor aceita (sem 422). Screenshots | RF-511/521 · A-10 · FE-02 |
| 5.2 | **Unidade no canvas ao vivo** (§6.4): o nó exibe a EU ao lado do valor da porta de saída, no mesmo tratamento que os nós de OPC dão à EU da tag — número em mono tabular (`process-value`), unidade em Texto Secundário menor. Portas de **entrada** não declaram EU: herdam da porta de origem pela aresta, resolvido no cliente com o mapa de arestas do próprio grafo; saída sem declaração fica sem unidade (como `Tag.eu` já admite, default `''`). **Sem propagação automática** através do bloco Script (§4.1-6: o Script existe em boa parte para converter grandeza, e unidade **errada** num console de operação é pior que unidade ausente) | `frontend/src/features/flows/nodes/*` (nó de Script e de TFS) · `frontend/src/features/flows/graph.ts` (função pura `euDaPortaDeEntrada(edges, output_eu_por_no, no, handle)`) · `frontend/src/features/flows/graph.check.ts` | RED: entrada ligada a `OUT1` com EU `t/h` ⇒ herda `t/h`; entrada solta ⇒ vazio; saída de Script atravessada **não** propaga para a saída do Script. Browser: flow rodando mostra valor + unidade nas portas declaradas. Screenshot | §6.4 · §4.1-5/6 |
| 5.3 | **`range` da DV na aba Variáveis** (§4.2-5; RFC-16): `VariavelDv` (`graph.ts:119`) ganha `range: FaixaMpc | null` (o mesmo tipo `{low, high}` já usado por Restrição), `ListaDv` (`TabVariables.tsx:344-376`) ganha os dois campos numéricos ao lado de Nome/EU (hoje só `CampoNomeEu`), e `variavelDvDoFormulario` (`mpcLogic.ts:54-61`) passa a lê-los — vazio nos dois ⇒ `null`; preenchido só um ⇒ erro de validação pt-BR no modal (o `Range` do servidor é `extra="forbid"` com os dois campos obrigatórios). A aba **sinaliza a ausência**: DV sem `range` recebe nota discreta de que o faceplate ficará sem barra — RF-702 pede limites e omissão silenciosa vira defeito invisível | `frontend/src/features/flows/graph.ts` · `frontend/src/features/flows/mpc/TabVariables.tsx` · `frontend/src/features/flows/mpc/mpcLogic.ts` · `frontend/src/features/flows/mpc/mpcLogic.check.ts` | RED: `variavelDvDoFormulario` com os dois campos ⇒ `range` montado; ambos vazios ⇒ `null`; só `low` ⇒ erro. Browser: criar DV com faixa, salvar, reabrir ⇒ preservada; DV sem faixa mostra a nota. Screenshots | RF-702 · A-11 · RFC-16 |
| 5.4 | **Faceplate de DV com barra** (§6.5): `faixaDaEscala` (`FaceplateVariavel.tsx:62-70`, hoje `return null` para DV) passa a devolver a faixa quando `definicao.range` vier preenchido de `GET /api/operate/mpcs` (F6a tarefa 4.2), fazendo a `BarraVertical` (`FaceplateVariavel.tsx:83-121`) renderizar com escala demarcada, **como MV/CV/Restrição** (DESIGN §Shapes, convenção intocável). Sem `range`: plaqueta + valor mono tabular + EU, sem barra — comportamento atual preservado. **Somente leitura nos dois casos** (RF-702): a DV continua fora do ramo de edição (`FaceplateVariavel.tsx:156-161,234`) | `frontend/src/features/operate/FaceplateVariavel.tsx` · `frontend/src/features/operate/faceplateVariavel.check.ts` (novo) | RED: `faixaDaEscala` de DV com `range` ⇒ `{min, max}`; sem `range` ⇒ `null`; DV nunca é editável em modo algum. Browser: faceplate de DV com faixa mostra barra; sem faixa mostra só valor + EU. Screenshots dos dois | RF-702 · A-11 |

**Conclusão:** `npm run build` + `test:unit` verdes; browser 5.1-5.4 com evidências.

---

## Etapa 6 — Débitos de frontend da F5 (spec §6.6, os seis)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 6.1 | **Tique de TTL sem re-render global** (§6.6-1): a família TTL (`mpc_arm_failed`, 60 s) só reavalia quando chega mensagem, então a condição fica acesa numa tela silenciosa. Tique de **5 s** alimentando `resolverAlarmes` — a assinatura **não muda**, ela já recebe `agora: Date` (`alarmes.ts:233-238`) e `alarmes.ts` continua pura. **O tique não pode bumpar o contexto único**: `EstadoContext.Provider value={estado}` (`CanalAoVivo.tsx:701`) re-renderiza **todo** consumidor de `useCanalAoVivo()` a cada troca de valor, incluindo a tela de operação com trend uPlot. O relógio vive em **estado próprio**, num hook consumido só por quem deriva alarmes (`AnnunciatorBar`), nunca no `value` do provider **[NOVA — implementação]** (forma) | `frontend/src/app/CanalAoVivo.tsx` · `frontend/src/app/AnnunciatorBar.tsx` · `frontend/src/app/useRelogioAlarmes.ts` (novo) · `frontend/src/app/canalAoVivo.check.ts` | RED: com relógio avançado 61 s e **zero mensagens novas**, a condição TTL cessa; o `value` de `EstadoContext` é o **mesmo objeto** antes e depois do tique (prova de que nada re-renderizou). Browser: B-F6-11 esqueleto — faixa cessa sozinha em 60 s e a tela de operação não pisca a cada 5 s | §6.6-1 · FE-06 |
| 6.2 | **Import circular desfeito** (§6.6-2): é **exatamente um** ciclo de runtime (imports type-only não contam) — `CanalAoVivo.tsx:14-25` importa `atrasoReconexao`, `deveReconectar`, `ehEstado`, `lerPorts`, `mesclarPorts`, `objeto`, `urlDoWs` (+ tipos) de `features/flows/useFlowStatus.ts`, e `useFlowStatus.ts:3` importa `useAssinatura`, `useCanalAoVivo` e o tipo `EstadoDoCanal` de volta. **Os sete símbolos de valor mudam de casa** para `features/flows/canalPrimitivos.ts`, com os dois arquivos passando a importar de lá; nenhum re-export de compatibilidade fica para trás (`lsp` `references` para achar todos os consumidores — `useFlowStatus.check.ts` inclusive) | `frontend/src/features/flows/canalPrimitivos.ts` (novo) · `frontend/src/app/CanalAoVivo.tsx` · `frontend/src/features/flows/useFlowStatus.ts` · checks afetados | `npm run build` verde; `grep` confirma que `CanalAoVivo.tsx` não importa mais de `useFlowStatus.ts` e vice-versa (só o tipo `EstadoDoCanal`, se `import type`); `test:unit` verde sem reescrever asserções de comportamento | §6.6-2 · FE-07 |
| 6.3 | **`AcaoPendencia.state` deixa de forçar double-cast** (§6.6-3): o ramo `estadoPublicado` (`pendencia.ts:24-27`) tipa `state: MpcState` e obriga `FaceplateVariavel.tsx:148` a construir `{ vars: { … } } as unknown as MpcState`. Passa a `unknown` — verificado seguro e completo: `reduzirPendencia` só usa `state` via leitura por caminho, e o double-cast some sem quebrar outro consumidor | `frontend/src/features/operate/pendencia.ts` · `frontend/src/features/operate/FaceplateVariavel.tsx` · `frontend/src/features/operate/pendencia.check.ts` | `grep "as unknown as MpcState" src` ⇒ nada; `npm run build` + `test:unit` verdes com os checks de `pendencia` intactos | §6.6-3 |
| 6.4 | **`EventsPage` reusa `useMpcs`** (§6.6-4): `EventsPage.tsx:69-72` refaz na mão o `useQuery` com `queryKey: ["operate","mpcs"]` e a mesma `queryFn` já definidas em `useMpcs.ts:10,22-27`; passa a chamar `useMpcs()`, importando `MpcNodeOut` de lá (hoje vem de `./eventos`) | `frontend/src/features/events/EventsPage.tsx` | `grep '\["operate", "mpcs"\]' src` ⇒ só `useMpcs.ts`; Browser: filtro de origem de `/eventos` continua populado igual. Screenshot | §6.6-4 |
| 6.5 | **Paleta estendida a 8 penas** (§6.6-5): o trend de operação tem teto de 8 (`trendOperacao.ts:162`, `TETO_PENAS_OPERACAO`) mas a paleta tem 6 cores (`styles/tokens.css:19-24`, `--color-pen-1..6`), então a 7ª e a 8ª pena colidem. Duas cores novas dessaturadas (`--color-pen-7`, `--color-pen-8`), **sem colidir com severidade nem com o Azul Único** (DESIGN §Colors) — mesma família `oklch(~0.78 ~0.09 …)` das existentes, matizes escolhidos longe do verde/âmbar/vermelho de severidade e do azul de acento. O teto de 6 do trend de **engenharia** (`features/trend/trendTheme.ts`, `LIMITE_PENAS`) **não muda**: é outro caso de uso | `frontend/src/styles/tokens.css` · `frontend/src/features/operate/trendOperacao.ts` · `frontend/src/features/operate/trendOperacao.check.ts` | RED: a lista de cores do trend de operação tem 8 entradas distintas e nenhuma igual às de severidade nem ao acento. Browser: trend com 8 penas ligadas ⇒ cores distinguíveis. Screenshot | §6.6-5 |
| 6.6 | **`overruns` com unidade** (§6.6-6): `FaceplatePrincipal.tsx:269-275` exibe o contador em mono tabular sem rótulo de unidade — DESIGN §Typography: número sem EU é defeito. Ganha rótulo de unidade explícito ("contagem"), no mesmo tratamento visual das EUs dos faceplates de variável | `frontend/src/features/operate/FaceplatePrincipal.tsx` | Browser: faceplate principal mostra `overruns` com a unidade ao lado; `last_solve_ms` continua com "ms". Screenshot | §6.6-6 · DESIGN §Typography |

**Conclusão:** `npm run build` + `test:unit` verdes; browser 6.1/6.4/6.5/6.6 com evidências.

---

## Etapa 7 — Fechamento do plano F6b

| # | Tarefa | Verificar | Governança |
|---|---|---|---|
| 7.1 | **Bateria de frontend completa + varredura de conjunto**: `cd frontend && npm run build && npm run test:unit`; leitura de conjunto das telas novas contra `DESIGN.md` (mono tabular em todo valor e identificador; plaqueta só em rótulo; cor só em estado; severidade sempre com canal redundante; zero emoji; zero ocorrência da palavra "bundle" em string pt-BR — `grep -rin "bundle" src` só pode achar identificador de código) | build e testes verdes; varredura sem achado aberto | DESIGN.md · §1.3-8 |
| 7.2 | **Encerramento parcial**: CLAUDE.md §Comandos com a rota `/engenharia/projetos` e a nav de 5 itens de engenharia; ledger `.superpowers/sdd/F6b-superficies/progress.md` completo com as provas RED e os screenshots por tarefa | seção reflete a UI real; ledger completo | CLAUDE.md §Workflow |

---

## Aderência (DoD do plano F6b)

| Critério | Tarefas |
|---|---|
| §6.0: helper `api()` corrigido, dois primitivos de arquivo, download autenticado | 1.1, 1.2 |
| RF-101 com superfície: CRUD, ativar com peso, estado vazio de dia 1 | 2.1, 2.2 |
| RF-102/103 pela UI: exportar por linha, importar em 3 passos com consentimento de Script e recusa legível | 2.3, 2.4 |
| Invalidação de cache por ação (a tabela §6.1-8 inteira) | 1.3, 2.2, 2.4 |
| As 3 telas + o seletor de operação deixam de apontar para tela inexistente | 2.5 |
| RF-202 com UI: chapa da instalação com escopo explícito, re-trust listado, trust por conexão | 3.1, 3.2 |
| Pendência de segredo visível, sem cor de severidade, com efeito no `title` | 1.4, 4.1 |
| EU nas portas (editor + canvas) e DV com barra | 5.1, 5.2, 5.3, 5.4 |
| Os 6 débitos de frontend da F5 | 6.1-6.6 |
| Zero regressão de build/unit e conformidade DESIGN | 7.1 |

O aceite da FASE (PRD §8-F6) fecha no plano F6c, com o gate completo e o roteiro L3 de `docs/plans/tests-e2e-f6.md`.

## Rastreabilidade (RF/decisão por tarefa)

| Norma | Tarefas |
|---|---|
| RF-101 (projetos) | 2.1, 2.2 |
| RF-102 (export) | 2.3 |
| RF-103 (import, projeto inativo) | 2.4 |
| RF-202 (certificados) | 3.1, 3.2 |
| RF-511/521 (EU nas portas) | 5.1, 5.2 |
| RF-702 (faceplates com EU e limites) | 5.3, 5.4, 6.6 |
| RF-705 (faixa anunciadora) | 6.1 |
| RF-803 (eventos) | 6.4 |
| ADR-012 (portabilidade) · ADR-018 (Script) · ADR-021 (certificados) | 2.3-2.4 · 2.4 · 3.1-3.2 |
| Decisões A-4/A-6/A-7/A-10/A-11/A-13/A-15 | 1.4+4.1 / 2.4 / 3.1 / 5.1-5.2 / 5.3-5.4 / 2.1-2.5 / 2.4 |
| F6R-03/09/10/11/14 | 2.4 / 5.1 / 1.1-1.2 / 1.3 / 1.4 |
| UX-01..10 · FE-02/06/07/08 · SEC-06 | 4.1, 3.1, 2.1, 2.2, 2.4, 2.5 · 5.1, 6.1, 6.2, 2.1 · 3.1 |
