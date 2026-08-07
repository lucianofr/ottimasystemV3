# Spec F6 — Portabilidade & hardening (export/import, certificados, suíte RNF-09)

**Fase:** F6 (PRD §8) — **última fase da v1** · **Status:** aprovado em blocos em sessão de brainstorm (2026-08-07); revisado por 7 agentes em paralelo no mesmo dia — achados `F6R-01..14` e os 54 de Bloco 3/4 aplicados (Anexo B)
**Fontes normativas:** `docs/PRD.md` v1.3→v1.4 (RF/RNF, contratos §7, fases §8, riscos §9) · `docs/adr/ADR-001…024` (prevalecem em conflito) · `docs/GLOSSARY.md` · `PRODUCT.md`/`DESIGN.md` (frontend) · specs F1/F2/F3/F4/F5 (vinculantes) · revisão consolidada `.claude/reports/review/review-spec-f6-consolidado-20260807.md`
**Execução:** 1 spec (esta) + 3 planos — F6a (portabilidade & dados), F6b (superfícies), F6c (suíte RNF-09 & guia), decisão A-1. Mapa de seções por plano em §12.

Convenções herdadas: itens **[NOVA — implementação]** são decisões de implementação desta spec, sem lastro literal em RF/ADR; o Anexo A registra as decisões do brainstorm; testes citam itens numerados (ex.: §3.2-4).

---

## 1. Escopo da F6

**Entrega (PRD §8-F6):** export/import JSON, gestão de certificados, health/heartbeats, testes RNF-09.
**Aceite (PRD §8-F6):** projeto exportado importa limpo em instalação nova (re-informando segredos); suíte MPC↔TFS verde.

Três fatos de levantamento moldam a fase e precisam ficar escritos, porque contrariam a leitura ingênua do PRD §8:

1. **Certificados é fase de frontend, não de backend.** RF-202 foi entregue inteiro na F2 — `POST /api/certificates/app/generate`, `GET /api/certificates/app`, `GET /api/certificates/app/export` (`routers/certificates.py:39-80`) e o trust por conexão `POST`/`DELETE /api/connections/{id}/server-certificate` (`routers/connections.py:250-323`), com a lógica X.509 em `ottima_core/certs.py`. A spec F2 §1.2 já registrava "UI fica na F6". Nenhum componente React consome esses quatro endpoints hoje.
2. **`overrun` e `hot-swap` não passam pela TFS em nenhum nível de teste.** É decisão documentada da F4b (`tests/e2e/test_f4_failure.py:1-7`, `tests/e2e/test_f4_ws.py:1-6`): os dois cenários de aceite usam `opc_read` dummy (`NODE_SINE`), não `grafo_mpc_tfs`.
3. **RF-101 não tem superfície.** `POST /api/projects`, `PATCH`, `DELETE` e `POST /{id}/activate` existem desde a F1 e nenhum componente os chama — o frontend só faz `GET /api/projects` para descobrir o ativo (`features/connections/useConnections.ts:14-20`). **Três** telas exibem "Nenhum projeto ativo: ative um projeto para…" apontando para uma tela inexistente (`ConnectionsPage.tsx:177`, `FlowsPage.tsx:294`, `TagsPage.tsx:54`). O seletor de operação **não** exibe essa mensagem: `OperateSelectorPage.tsx:48` diz "Nenhum bloco MPC configurado no projeto ativo", texto que aparece igual com projeto ativo sem MPC — distinguir os dois casos ali é lógica nova (§6.1-7). Sem a tela de Projetos o aceite é inatingível pela UI: o import cria projeto **inativo** (RF-103) e ninguém consegue ativá-lo.

### 1.1 Dentro da F6

| Item | Governança |
|---|---|
| Bundle de projeto (`tag_ref`, sem segredos) + emenda PRD §7.2 → v1.4 | RF-102 · ADR-012 · decisão A-2 · §2 |
| `GET /api/projects/{id}/export` + emenda a RF-102 (qualquer projeto, não só o ativo) | RF-102 · decisão A-14 · §3.1 |
| `POST /api/projects/import` (4 camadas de validação, transação única) | RF-103 · decisões A-5/A-6 · §3.2 |
| `GET /api/health` da api reflete `redis_ok`/`db_ok` por heartbeat de fundo | RNF-07 · §3.3 |
| Campo `service` no log estruturado dos 4 serviços | RNF-07 (descoberto, F6R-04) · decisão A-16 · §3.4-1 |
| `env_file` do `flow-runtime` restrito: segredos fora do processo que executa Script | RNF-04 · decisão A-15 · §3.4-2 |
| Página `/engenharia/projetos` (CRUD + ativar + export + import) | **RF-101 sem UI desde a F1** · decisão A-13 · §6.1 |
| UI do certificado de aplicação + trust por conexão + primitivos de arquivo | RF-202 · ADR-021 · decisão A-7 · §6.2 |
| Pendência de segredo derivável (3 predicados) na página de Conexões | aceite F6 ("re-informando segredos") · decisão A-4 · §6.3 |
| EU por porta de saída de Script/TFS (`output_eu`) | DESIGN §Typography · decisão A-10 · §4.1 |
| `range` opcional na `DvVar` + barra vertical no faceplate de DV | RF-702 · DESIGN §Shapes · decisão A-11 · §4.2 |
| Suíte RNF-09: os 4 itens com prova pela TFS **e** prova de estresse preservada, sob marcador `rnf09` | RNF-09 · ADR-022 · decisão A-8 (revista) · §7 |
| `docs/IMPLANTACAO.md` — guia de implantação e comissionamento | PRD §9-5 · decisão A-12 · §8 |
| Débitos de runtime da F5: payload de `mpc_overrun`; `shutdown_mpc` fora do lock | spec F5 §8 · decisão A-1 · §5 |
| Débitos de frontend da F5: tique de TTL, import circular, `AcaoPendencia.state`, `queryKey` duplicada, paleta de 8 penas, `overruns` com EU | spec F5 (ledgers) · decisão A-1 · §6.6 |

### 1.2 Fora da F6 — com destino registrado

| Item | Destino | Governança |
|---|---|---|
| `opc.values.<conn_id>` no `/ws` | **nunca** — sem consumidor real (`ws.py:120-127`, `canalAoVivo.check.ts:167`); o trend de engenharia segue polling. Exige emenda ao PRD §7.1 e §7.3, que ainda listam `api(WS)` como consumidor (§1.3-7) | decisão A-1; encerra o registro aberto em F2 §1.2, F3 §1.2 e F5 §1.2 |
| Backup/restauração do Postgres (mecanismo) | fora da v1 — sem RF/ADR; o guia documenta `pg_dump`/`pg_restore` como procedimento manual, sem prometer automação | decisão A-1 · §8-6 |
| Correlação de log (`request_id`/`trace_id`) entre serviços | fora da v1 — RNF-07 pede "logs estruturados por serviço", que §3.4-1 passa a cumprir; correlação é eixo distinto e sem RF | decisão A-16 |
| Limites de recurso (`mem_limit`/`cpus`) e teto de tentativas de restart no compose | fora da v1 — sem RF; `unless-stopped` + healthchecks + `depends_on: service_healthy` cobrem RNF-06 | decisão A-1 |
| Bootstrap que gera os segredos do `.env` automaticamente | fora da v1 — passo manual documentado no guia (§8-1). **Não é pré-requisito do aceite:** os segredos que o aceite manda re-informar são os da conexão OPC, não os do `.env` | decisão A-1 |
| Cenário E2E que derruba `redis`/`timescaledb` como container real | fora da v1 — a resiliência está provada em unit/integração nos 4 serviços (§9.1) e a suíte tem proibição explícita de `down`/`prune` (`tests/e2e/conftest.py:4-6`) | decisão A-1 |
| Sandbox forte do bloco Script (isolamento de processo, seccomp) | fora da v1 — ADR-018 fixou o escopo restrito (`math`/`numpy`). A F6 fecha o pior impacto (§3.4-2) e trata a proveniência por consentimento explícito (§6.1-6) e documentação (§8-5); o resíduo fica em TD-001 | decisão A-15 |
| Teto de contagem no import (nº de flows/conexões/tags) e execução da validação fora do worker | fora da v1 — o teto de 4 MiB (§3.2-1) limita o pior caso; o congelamento do `/ws` durante um import grande fica em TD-002 | decisão A-1 |
| ACK de alarmes | fora da v1 | ADR-020 |
| Protocolo `Commandable`/`Healthy` | revisitar no 2º bloco comandável | spec F5 §1.2 |
| Persistir predição/custo/status do MPC | nunca | ADR-016 |
| `mpc_state_dimension` conservador | fica como está | spec F4 §2.2-7 |
| Migração de `schema_version` antigo no import | não existe versão anterior a 1; quando existir, é ADR | §3.2-2 |
| Nível in-process MPC↔TFS + `FakeClock` canônico no `tests/testkit/` | não-objetivo consciente: o valor seria velocidade de regressão, e o aceite pede prova | §7-6 |

### 1.3 Emendas a documentos anteriores (consolidação)

O PRD tem regra explícita de correção (`PRD.md` §nota inicial); specs anteriores recebem **nota de remissão** a esta spec no trecho alterado. Aplicação: **Etapa 0 do plano F6a**, antes de qualquer código.

| # | Documento · trecho | O que muda |
|---|---|---|
| 1 | PRD §7.2 (JSON de projeto) + changelog v1.4 + cabeçalho §Status (`PRD.md:4`, ainda diz "F1 e F2 concluídas") | O exemplo passa a espelhar os schemas reais: `ts` → `ts_seconds`, `"dir": "R"` → `"direction": "r"`, campos `security_*`/`watchdog_*` planos no lugar de `security:{}`/`watchdog:{}`, `data_type`/`description` nas tags, `auth_mode`/`auth_username` nas conexões; ganha `exported_at`, `desired_state` e a referência `tag_ref` dentro do `graph` (§2) |
| 2 | **PRD RF-102** (`PRD.md:82`, "Export do projeto **ativo**") | Passa a "Export de **um projeto** (por id)". Motivo: arquivar a engenharia antes de ativar outra é caso legítimo, o RBAC admin já protege, e sem isso o único cenário que prova o aceite é inexecutável — o backend recusa excluir o projeto ativo (`projects.py:70-72`) e não existe endpoint de desativar (decisão A-14, F6R-02) |
| 3 | Spec F2 §1.2 ("UI de gestão de certificados \| F6") | Cumprida por §6.2 |
| 4 | Spec F4 §1.2 / F5 §1.2 ("suíte completa RNF-09 \| F6") | Cumprida por §7 |
| 5 | Spec F5 §1.2 ("EU nas portas de Script/TFS \| F6") | Cumprida por §4.1 |
| 6 | Spec F5 §8, última linha (`shutdown_mpc` síncrono sob o lock em `_force_stop`, `_pass`/`_reconcile_flow` e `_handback_failed_mpc`) | Fecha em §5.2. Correção do registro: a F5 §8 enumera **três** contextos e nunca cita `_teardown`; o inventário desta spec confirma os três e acrescenta o quarto chamador real que o ledger da F5 não registrou — `_deploy` sobre `old_runtime` (`supervisor.py:338`) |
| 7 | PRD §7.1 (linha `opc.values.<conn_id>`, coluna Consumidores) e §7.3 (`/ws` descrito como "(valores, …)") | `api(WS)` deixa de ser consumidor de `opc.values`; o `/ws` entrega `flow.status`, `mpc.state` e `events`. Formaliza o "nunca" de §1.2 — é a última fase da v1 e o registro não pode ficar aberto (F6R/RFC-06) |
| 8 | `docs/GLOSSARY.md` | Entradas novas: **arquivo de projeto** (o JSON de export/import; "bundle" é termo interno de código, **proibido na UI**) e **pendência** (condição de configuração que impede a conexão de subir, derivada, sem estado persistido) |

---

## 2. Contrato de portabilidade

### 2.1 Schemas de bundle próprios (decisão A-2; emenda PRD §7.2 → v1.4; F6R-05)

1. **O bundle NÃO reusa os schemas `Create`.** A versão anterior desta spec mandava reusar `ConnectionCreate` como camada 2 de validação; a revisão provou que isso é impossível e perigoso nas duas direções:
   - `ConnectionCreate._coerencia` (`schemas/connections.py:37-38`) levanta 422 quando `auth_mode == "user_password"` sem `auth_password` — e o bundle nunca carrega senha (§2.3). O exemplo normativo do item 2 é exatamente esse caso: **o bundle seria recusado pela própria regra**.
   - `ConnectionCreate.project_id` (`:27`), `TagCreate.connection_id` e `FlowCreate.project_id` são obrigatórios e ausentes do bundle.
   - Sentido inverso: `_ConnectionFields` (`:13`) **não** declara `extra="forbid"` e aceita `auth_password` (`:28`) e `server_cert_file` (`:20`). Um bundle com senha em claro seria consumido em silêncio; um com `server_cert_file` criaria pinning pendurado que o predicado de pendência de §6.3 **não** acusa.
2. Em vez disso, módulo novo de schemas de bundle, todos com **`extra="forbid"`**, sem ids e sem segredos. As regras de coerência que continuam valendo são **extraídas para funções puras** e chamadas dos dois lados (`ConnectionCreate` e bundle), sem terceira cópia:

   | Regra | Vale no bundle? |
   |---|---|
   | `security_policy == "none"` ⇔ `security_mode == "none"` | sim |
   | watchdog exige os dois `node_id` ou nenhum | sim |
   | `user_password` exige usuário **e senha** | **não** — vira "`user_password` exige `auth_username`". Contraprova de que o estado sem senha é legítimo no sistema: o PATCH de conexão só valida policy×mode e watchdog (`routers/connections.py:210-215`) |

3. `desired_state` do Flow é declarado no schema de bundle como `Literal["running", "stopped"]` **[NOVA — implementação]**. Sem isso o valor não é validado por camada nenhuma (não existe em `FlowCreate`/`FlowUpdate`, `schemas/flows.py:17-20`), só pelo CHECK `ck_flows_desired_state` (`models/flow.py:40`) — e um valor malformado escaparia como `IntegrityError` no `flush()`, virando 500 em vez do 422 agregado (F6R-12).

4. Forma normativa:

```json
{
  "schema_version": 1,
  "exported_at": "2026-08-07T21:40:00Z",
  "project": {"name": "Planta C-101", "description": "Coluna debutanizadora"},
  "connections": [{
    "name": "gateway-1",
    "endpoint": "opc.tcp://10.0.0.5:4840",
    "security_policy": "basic256sha256",
    "security_mode": "sign_and_encrypt",
    "auth_mode": "user_password",
    "auth_username": "ottima",
    "watchdog_read_node_id": "ns=2;s=WD_R",
    "watchdog_write_node_id": "ns=2;s=WD_W",
    "watchdog_period_ms": 1500
  }],
  "tags": [{
    "connection": "gateway-1",
    "name": "TT-101",
    "node_id": "ns=2;s=TT101",
    "direction": "r",
    "data_type": "float",
    "eu": "C",
    "description": "Temperatura de topo"
  }],
  "flows": [{
    "name": "Coluna C-101",
    "ts_seconds": 1.0,
    "desired_state": "stopped",
    "graph": {"nodes": [], "edges": []}
  }]
}
```

5. `exported_at` (UTC, ISO-8601) é metadado de arquivo: nenhum consumidor de código o lê e o import o ignora. Existe porque o arquivo circula entre plantas e reaparece meses depois **[NOVA — implementação]**.
6. `desired_state` é exportado verbatim: é intenção de engenharia persistida (RF-306) e o import não auto-aplica nada, como o boot (RF-104). Verificado que isso não cria caminho de escrita em planta: `_pass` nunca inicia flow (`supervisor.py:507-516`) e `on_project_activated` só para (`:491-496`).
7. `Tag.name` é único por **conexão** (`models/tag.py:34`), não por projeto; `Connection.name` e `Flow.name` são únicos por projeto. O bundle herda essas garantias por construção e o import as reafirma como camada 3 (§3.2-4).

### 2.2 Referência de tag dentro do grafo (`tag_ref`)

1. `graph_json` guarda `Tag.id` inteiro em **seis campos**, e `Tag.id` é `BigInteger Identity` — a instalação de destino recria as tags com ids novos. Sem tradução, todo flow importado aponta para tag inexistente e o aceite falha:

| Bloco | Campo no banco | Campo no bundle | Âncora |
|---|---|---|---|
| `opc_read`, `opc_write` | `config.tag_id` | `config.tag_ref` | `flowgraph/parse.py:46-51`; `_CONFIG_KEYS` em `:19-25` |
| `mpc`, por MV em `config.variables.mvs[i].pid` | `write_tag_id` | `write_tag_ref` | `flowgraph/mpc_config.py:58-68` |
| idem | `mode_cmd_tag_id` | `mode_cmd_tag_ref` | idem |
| idem | `mode_read_tag_id` (opcional) | `mode_read_tag_ref` (opcional) | idem |
| idem | `readback_tag_id` | `readback_tag_ref` | idem |

2. `tag_ref` é **objeto**: `{"connection": "gateway-1", "tag": "TT-101"}`. Nome de conexão e de tag são texto livre e podem conter `/`; a forma `"conexao/tag"` exigiria regra de escape nova sobre dados existentes, e a ambiguidade só apareceria na planta de um cliente.
3. A tradução é **explícita por campo**, nunca varredura heurística: a lista dos seis campos vive num lugar só (`TAG_REF_FIELDS`), e um bloco futuro que ganhe referência de tag precisa entrar nela. O teste de §9.1 guarda a lista por introspecção (§9.1, mecanismo em TST-06).
4. **`TagConfig` e `PidBinding` são `extra="forbid"` com `tag_id: int`** — eles nunca veem `tag_ref`. O grafo do bundle é uma forma **distinta** do `graph_json` do banco, não um superset: a tradução acontece **antes** de qualquer `parse_graph`, nos dois sentidos.
5. **Ordem normativa** (resolve a ambiguidade apontada em API-05):
   - **Export:** carrega o mapa `{tag_id → (connection_name, tag_name)}` do projeto → reescreve os seis campos no JSON → serializa. Referência que não resolve **aborta com 422**, nunca exporta bundle quebrado.
   - **Import:** camada 3 valida em memória, **antes de qualquer insert**, que todo `tag_ref` casa com alguma `(connection, tag)` do próprio bundle e que não há nome duplicado dentro do bundle — assim `IntegrityError` de unicidade nunca escapa como 500. Só depois: insere projeto/conexões/tags, `flush()` para obter os ids, monta o mapa `{(connection, tag) → novo_id}`, reescreve o grafo, e aí roda `parse_graph` + `validate_graph` (camada 4).

### 2.3 O que não atravessa a fronteira

| Campo | Motivo |
|---|---|
| `auth_password_enc` | **segredo** (ADR-012/021); re-informado no destino (§6.3) |
| `server_cert_file` e o `.der` confiado | **ambiente-específico** — terceiro motivo, distinto de "segredo" e de "id" (decisão A-3). Material público, mas no caso de uso principal do ADR-012 (levar engenharia para outra planta) o endpoint muda e o certificado antigo é pior que ausente: instala pinning errado, que falha em `cert_mismatch` (`opc-worker/security.py:115-125`), diagnóstico mais confuso que `cert_missing`. O `extra="forbid"` de §2.1-2 garante que ele não entre por descuido |
| `id`, `project_id`, `connection_id` | **ids internos**; substituídos por nome lógico (§2.2) |
| `is_active` | RF-103: import cria projeto **inativo**, sempre; o campo nem sai no bundle |
| `created_at`, `updated_at` | metadado da instalação de origem |
| `User` | global à instalação, não é filho de Project (PRD §4) |
| `samples`, `events`, `mpc_samples` | RF-102: "sem dados históricos" |

**Nota de proveniência (F6R-03):** `graph_json` carrega o campo `code` do bloco Python-Script verbatim — é o único texto livre arbitrário do grafo, e ele **executa no servidor** quando o flow é deployado. O bundle é feito para atravessar organizações (ADR-012), então o código importado deixa de ter autor confiável, que é a premissa do ADR-018. Tratamento: consentimento explícito na tela de import (§6.1-6), redução de impacto no compose (§3.4-2) e seção própria no guia (§8-5). O resíduo está em TD-001.

---

## 3. API nova e correções

### 3.1 `GET /api/projects/{id}/export` (RF-102 emendado; router `projects`; `require_admin`)

1. `require_admin` — PRD §2 põe "Export/import de projeto" na linha exclusiva de admin. Mesmo sem segredos, o bundle revela a topologia OPC completa da planta.
2. Resposta `application/json` com `Content-Disposition: attachment; filename="<slug>.ottima.json"` — mesmo padrão de `routers/certificates.py:76-80`. O slug reduz o nome do projeto a `[a-z0-9-]`; nome que reduz a vazio cai em `projeto` **[NOVA — implementação]**.
3. Exporta **qualquer** projeto por id, não só o ativo — **isto amplia RF-102 e por isso vai emendado em §1.3-2**, não assumido. 404 pt-BR "Projeto não encontrado", literal já usado em `projects.py:21` (não confundir com `MSG_FLOW_NAO_ENCONTRADO` de `messages.py:3`, que é de outra entidade); a Etapa 0 extrai `MSG_PROJETO_NAO_ENCONTRADO` para `messages.py`, hoje duplicado em `projects.py:21` e `flows.py:134`.
4. **Audita.** Evento `project_exported` (severity `info`, origin `user:<id>`, payload `{project_id, name}`) **[NOVA — implementação]**. A própria justificativa do RBAC no item 1 é a sensibilidade da topologia; toda outra ação sensível do sistema deixa rastro (`connections.py:240-247` é o padrão) e o import audita — export sem evento seria a única exfiltração silenciosa possível (SEC-05).
5. Sem paginação e sem filtro: teto de ~10 flows, ≤5 conexões e ~100 tags (RNF-01); nenhum router do sistema pagina (padrão F1 §6.1).

### 3.2 `POST /api/projects/import` (RF-103; router `projects`; `require_admin`)

1. Corpo `{"name": "...", "bundle": {…}}`, `name` opcional sobrescrevendo `bundle.project.name` (decisão A-6). **Teto de 4 MiB aplicado por middleware/dependência que lê o corpo como stream antes da amarração Pydantic** — o precedente de `_ler_certificado` só funciona porque usa bytes crus, e um `body:` tipado já materializou o payload quando se consegue medi-lo (API-06). Excedente ⇒ **413** com mensagem pt-BR **[NOVA — implementação]**.
2. `schema_version` diferente de `1` ⇒ 422 imediato, sem tentativa de migração.
3. **Transação única** — tudo-ou-nada, mesmo padrão de `activate_project` (`projects.py:77-112`).
4. Validação em quatro camadas, ordem determinística, **toda antes do commit** (detalhe da ordem em §2.2-5):

   | # | Camada | O que reprova |
   |---|---|---|
   | 1 | `schema_version` | valor ≠ 1 |
   | 2 | Forma (schemas de bundle, `extra="forbid"`, §2.1-2) | tipo errado, campo faltando, campo proibido (senha, cert, id), enum inválido, `ts_seconds` fora da lista, `desired_state` inválido, coerência de conexão |
   | 3 | Referências internas, **em memória** | tag apontando para conexão ausente; `tag_ref` que não casa; nome duplicado dentro do bundle (projeto/conexão/tag/flow) |
   | 4 | Grafo | `parse_graph` + `validate_graph` por flow, com o mapa de tags materializado pelo `flush()` |

5. **Recusa: 422 com `detail` string única pt-BR agregando até 10 problemas.** Separador **` | `**, nunca `;` — `node_id` de OPC-UA contém `;` legitimamente (`ns=2;s=TT101`) e o ponto-e-vírgula tornaria a mensagem ambígua para quem lê e impossível de partir para quem renderiza (UX-06). Formato:

   `"Import recusado (3 problemas) | flows[2].graph: nó 'mpc_x7k2' refere tag inexistente (conexão 'gateway-1', tag 'TT-999') | tags[7]: conexão 'gateway-2' não existe no arquivo | connections[0]: SecurityPolicy None exige modo None"`, com sufixo `" | e mais N"` acima de 10.

   O contrato universal de erro da API (string única, `app.py:60-67`) fica intacto. A varredura completa custa o mesmo que parar no primeiro problema. A apresentação disso na tela é §6.1-6.
6. Nome de projeto já existente ⇒ **409**, mesma mensagem de `create_project` (`projects.py:39`, hoje literal duplicado em `:62` — a Etapa 0 extrai a constante). É a única reprovação de **conteúdo** fora do 422; o 413 do item 1 é de transporte e nem chega às camadas.
7. Sucesso ⇒ **201** com `ProjectImportOut`:

```json
{"project": { /* ProjectOut, is_active sempre false */ },
 "pending_secrets": [
   {"connection_name": "gateway-1",
    "needs_password": true,
    "needs_server_certificate": true,
    "needs_app_certificate": false}
 ]}
```

8. **Os três predicados são UM só lugar de verdade**, compartilhado com §6.3-1 — a versão anterior desta spec usava fórmulas diferentes nos dois pontos, o que faria a pendência nunca sumir da tela (API-07):

   - `needs_password ⇔ auth_mode == "user_password" && !has_password`
   - `needs_server_certificate ⇔ security_policy != "none" && !server_cert_file`
   - `needs_app_certificate ⇔ (security_policy != "none" || auth_mode == "certificate") && !appCert.exists`

   O terceiro fecha um buraco real (F6R-14): `auth_mode: certificate` reusa o par do certificado de aplicação (`opc-worker/security.py:167-176`), que na instalação nova não existe. Sem ele, uma conexão importada com `auth_mode: certificate` e `security_policy: none` teria pendência vazia e falharia em `cert_missing` sem aviso nenhum. O dado vem de `AppCertificateOut.exists` (`schemas/certificates.py:8-14`).
9. Emite `project_imported` (severity `info`, origin `user:<id>`, payload com contagens). O kind novo entra em `ottima_core/bus.py` junto dos demais (API-08), como `project_exported` de §3.1-4.

### 3.3 `GET /api/health` da api reflete as dependências (RNF-07)

1. Hoje a rota devolve `{"status": "ok", …}` fixo (`routers/health.py:17-19`), sem consultar Redis nem Postgres. Os outros três derivam do estado real: `opc-worker` e `recorder` de `redis_ok and db_ok` (`opc-worker/main.py:108-128`, `recorder/main.py:67-86`); **`flow-runtime` soma uma terceira condição**, `runtime_up` (`flow-runtime/main.py:145`).
2. **O mecanismo é normativo, não só o formato.** Os três workers rodam um `_heartbeat_loop` de fundo e o handler apenas lê o estado (zero I/O por request). A api adota **o mesmo mecanismo** — checagem periódica em background, handler sem I/O. Uma checagem síncrona sem timeout numa rota que é o healthcheck do compose seria vetor de lentidão auto-infligido (F6R-13).
3. Corpo: `{"status": "ok"|"degraded", "service": "api", "version": …, "redis_ok": bool, "db_ok": bool}`, **sempre 200**.
4. A rota segue **pública** — é o healthcheck do compose (`docker-compose.yml:46-51`) e o passo E2E-01a do smoke. Isso é exceção a RF-003 herdada da F1 (`routers/health.py:1`) e fica **registrada aqui** ao ampliar o corpo não autenticado: `redis_ok`/`db_ok` não revelam nada além do que a disponibilidade da própria rota já revela na rede interna (ADR-023) **[NOVA — implementação]**.

### 3.4 Hardening com lastro

1. **Campo `service` no log estruturado (RNF-07; decisão A-16).** `JsonFormatter` emite hoje `{ts, level, logger, message}` (`ottima_core/logging.py:12-21`); `record.name` é o caminho do logger Python, não o serviço. A distinção por serviço só existe no prefixo de container do `docker compose logs` — ou seja, **RNF-07 ("logs estruturados por serviço") está descoberto**, ao contrário do que a versão anterior desta spec afirmava. `setup_logging(level, service: str)` passa a gravar o nome no formatter, e cada um dos 4 serviços informa o seu no boot (`api/app.py:91`, `api/seed.py:44`, `opc-worker/main.py:64`, `flow-runtime/main.py:75`, `recorder/main.py:44`).
2. **`env_file` do `flow-runtime` restrito (RNF-04; decisão A-15).** O serviço recebe hoje o `.env` inteiro, então `OTTIMA_SECRET_KEY` e `OTTIMA_FERNET_KEY` ficam no ambiente do processo que executa código do bloco Script — código que, a partir desta fase, pode vir de um bundle externo (§2.3, nota). `env_file` é trocado por lista explícita das variáveis que o `flow-runtime` realmente usa. É mudança de compose, não de arquitetura, e remove o pior impacto de TD-001; o sandbox do Script em si não muda (ADR-018).

---

## 4. Schema

### 4.1 EU por porta de saída de Script e TFS (decisão A-10; RF-511/521, DESIGN §Typography)

1. DESIGN §Typography: "número sem unidade de engenharia é defeito". Tags têm `eu` (`models/tag.py:30`) e as variáveis do MPC têm `eu`, então OPC-Read/Write e faceplates cumprem. Script e TFS não têm onde declarar, e o canvas ao vivo mostra número pelado.
2. **O campo precisa nascer nos dois lados, e a spec anterior só dizia um** (F6R-09):
   - **Backend:** `output_eu: dict[str, str] = {}` em `ScriptConfig` e `TfsConfig` (`flowgraph/parse.py`), com a chave nova em `_CONFIG_KEYS` (`:19-25`).
   - **Frontend:** campo correspondente em `DadosScript`/`DadosTfs` (`features/flows/graph.ts`), que é **plano** — não há objeto `config` aninhado no nó do React Flow. Sem isso o dado não persiste, e o servidor recusa chave desconhecida em `data` com 422 (`parse.py:252-255`).
3. Handles de saída válidos, verbatim de `flowgraph/validate.py:99-111`: `script` ⇒ `OUT1..OUT{n_outputs}`; `tfs` ⇒ `y1`, `y2`. Chave fora do conjunto é erro de parse (`extra="forbid"` confirmado em `ScriptConfig`/`TfsConfig`). Para `script` a validação depende de `n_outputs` no mesmo modelo ⇒ `model_validator`.
4. **`ModalConfigBloco` é hoje deliberadamente não-controlado** (lê valores no submit via `FormData`). Renderizar N campos de EU conforme `n_outputs` exige tornar **apenas** esse select controlado, com `onChange` que ajusta a lista de campos — mudança localizada, registrada aqui para não virar descoberta na execução (FE-02).
5. Portas de **entrada** não declaram EU: herdam da porta de origem pela aresta, resolvido no cliente. Saída sem declaração fica sem unidade, como `Tag.eu` já admite (default `''`). Nada é obrigatório: flow existente continua válido byte a byte.
6. Sem propagação automática: o Script existe em boa parte para converter grandeza, e unidade **errada** num console de operação é pior que unidade ausente.
7. Regenera `contracts.gen.ts` (`ottima_core/contracts_export.py`).

### 4.2 `range` opcional na `DvVar` (decisão A-11; RF-702, DESIGN §Shapes)

1. `DvVar` tem só `id`/`name`/`eu` (`flowgraph/mpc_config.py:128-135`). RF-702 lista os faceplates "com EU e **limites**" e DESIGN §Shapes chama a barra vertical de convenção intocável; a F5 entregou DV sem barra por falta de schema.
2. Campo `range: Range | None = None` — **o mesmo tipo `Range` `{low, high}` de `ConstraintVar`** (`mpc_config.py:39-46`). JSONB, sem migration, opcional.
3. Projetado por `GET /api/operate/mpcs` no bloco `dvs` (spec F5 §4.1-1).
4. Com faixa, o faceplate desenha barra vertical com escala como MV/CV/Restrição; sem faixa, plaqueta + valor mono tabular + EU, sem barra (§6.5).
5. Editável na aba **Variáveis** do modal do MPC (RF-607). A aba **sinaliza** a ausência: DV sem `range` recebe nota discreta de que o faceplate ficará sem barra — RF-702 pede limites, e omissão silenciosa vira defeito invisível (RFC-16).

---

## 5. Runtime — débitos herdados da F5

### 5.1 Payload de `mpc_overrun`

`blocks/mpc.py:453-463` publica `payload={}`. Passa a publicar `{"overruns": <contador>}`, tornando a família "contador publicado" simétrica a `flow_overrun` (spec F5 §7.2-1).

**Regressão declarada:** `tests/e2e/test_f4_failure.py:226` assere `evento["payload"] == {"kind": KIND_MPC_OVERRUN}` por **igualdade exata**. A mudança quebra esse teste com certeza mecânica; a tarefa que altera o payload atualiza a asserção no mesmo commit (F6R-08). A linha de regressão de §9.2 lê-se com essa exceção.

### 5.2 `shutdown_mpc` fora do lock global (spec F5 §8)

1. **Inventário.** O lock é `Supervisor._lock` (`supervisor.py:172`), tomado em quatro lugares: comandos (`:259`), `on_comm_failure` (`:477`), `on_project_activated` (`:494`) e `_pass` (`:517`). O `shutdown_mpc` **síncrono** (`supervisor_mpc.py:417`) sobrevive em **três** caminhos sob o lock:

   | # | Chamador | Âncora | Sob qual tomada do lock |
   |---|---|---|---|
   | 1 | `_deploy`, sobre o `old_runtime` do redeploy | `supervisor.py:338` | `:259` (comando) |
   | 2 | `_handback_failed_mpc`, na varredura de watermark | `supervisor.py:548` | `:517` (`_pass`) |
   | 3 | `_force_stop` | `supervisor.py:597` | `:494` (`on_project_activated`) e `:517`→`:558`/`:563` (`_reconcile_flow`) |

   `_teardown` (`supervisor.py:643`) **não** roda sob o lock — é chamado por `Supervisor.stop()` (`:219-222`) — e é o único lugar onde esperar o desmonte é correto: `:644-649` já aguarda `runtime.mpc_stop_tasks` de propósito (invariante da spec F5 §6.5). **Fica como está.**

2. **A substituição tem TRÊS passos, não dois** (F6R-06). A versão anterior desta spec creditava a `stop_host_background` a remoção do host do mapa; é falso — quem esvazia `runtime.hosts` é `detach_hosts` (`supervisor_mpc.py:347`), e o docstring de `stop_host_background` (`:359`) documenta que o host "já saiu do mapa … ANTES desta task nascer". Sequência normativa, idêntica à que `_stop` já usa (`supervisor.py:352-353`):

   1. `revert_armed_mpc` (`supervisor_mpc.py:395`) — devolve `mode_cmd=auto` de todo bloco armado; **não espera processo nenhum**. Sob o lock.
   2. `detach_hosts` (`supervisor_mpc.py:347`) — esvazia `runtime.hosts` e devolve o que havia. **Síncrono, sob o lock.**
   3. `stop_host_background` (`supervisor_mpc.py:359`) — destaca o kill/join como task de fundo.

   Omitir o passo 2 deixaria o host morto alcançável em `runtime.hosts` por até `_BOOT_TIMEOUT_S = 30 s`, permitindo comando concorrente sobre um worker em processo de morte — violação direta da invariante "nunca dois workers escrevendo na mesma malha", com risco de escrita indevida em planta.

3. **Posse das tasks destacadas.** No caminho 1 o `_FlowRuntime` antigo é substituído no mapa; uma task pendurada em `old_runtime.mpc_stop_tasks` ficaria órfã e o `_teardown` do serviço voltaria a poder abandonar um kill em voo. As tasks destacadas precisam de dono que sobreviva à troca de `_FlowRuntime` — conjunto no `Supervisor` ou transferência para o runtime novo **[NOVA — implementação]** (forma). Sem isso a correção reintroduz o defeito que a F5 §6.5 fechou.
4. Invariantes preservadas byte a byte: idempotência (`revert_armed_mpc` guarda por `block.local_remote`, `MpcHost.stop()` idempotente), `mpc_arm_failed {worker_not_ready}` nos dois eixos, shed/hot-swap/watchdog de armar intocados, nenhum worker órfão após stop durante build.
5. Prova: latências medidas com clock controlado (§9.1) — comando de outro flow não espera `_BOOT_TIMEOUT_S` em nenhum dos três caminhos.

---

## 6. Frontend

Autoridade visual: `PRODUCT.md`/`DESIGN.md`. Tudo pt-BR com o vocabulário do `GLOSSARY.md` (incluindo as entradas novas de §1.3-8), sem emojis. Campo grafite, chapas, linhas 1px, cantos 2-4px, plaquetas em rótulo de tag/equipamento, mono tabular em todo valor, cor reservada a estado e ao azul único, severidade sempre com canal redundante.

### 6.0 Primitivos de arquivo e mudança no helper `api()` (F6R-10)

1. `frontend/src/lib/api.ts:48` sobrescreve `Content-Type` para JSON sempre que há body, e o helper nunca expõe `res.blob()` nem headers de resposta. Nenhum dos fluxos novos funciona sem alterá-lo — a versão anterior desta spec não mencionava isso. A mudança é parte da fase.
2. **Dois primitivos distintos**, porque os casos não são o mesmo:
   - **Upload binário** (certificado): `<input type="file">` oculto acionado por botão do design system → `File.arrayBuffer()` → `Blob` no corpo, com `Content-Type` explícito (`application/octet-stream`/`application/x-pem-file`/`application/pkix-cert`). **Sem `FormData`** — o endpoint não é multipart (`connections.py:259-263`).
   - **Leitura de texto** (arquivo de projeto): `File.text()` → `JSON.parse` no cliente → corpo JSON normal. Erro de parse é tratado no cliente com mensagem pt-BR, antes de qualquer requisição.
3. **Download autenticado:** o app envia JWT em header, então `<a href>` simples não autentica. Os dois downloads (arquivo de projeto e `.der`) usam `fetch` com header → `res.blob()` → object URL → `<a download>` revogado depois. O nome vem do `Content-Disposition` quando presente, com fallback local.

### 6.1 Página `/engenharia/projetos` (decisão A-13; RF-101/102/103)

1. Rota nova em `app/router.tsx`, item novo no grupo de engenharia do nav (`Projetos · Conexões · Tags · Flows · Trend`).
2. Tabela (chapa): nome, descrição, **Ativo**, ações. A lâmpada de "Ativo" usa o **Azul Industrial** — DESIGN §Colors reserva o Verde Rodando exclusivamente para "rodando/vivo", e projeto ativo não é execução; o azul é a cor de seleção/item ativo do sistema (UX-10). Ícone + rótulo "Ativo" ao lado, nunca só cor.
3. Mutações só para admin (`useCanMutate`): criar, renomear/editar descrição, excluir (confirmação; o backend recusa excluir o ativo com 409, `projects.py:67-74`).
4. **Ativar** é a ação de maior consequência da tela — encerra a execução de todos os flows do projeto atual, o que numa planta é efeito físico. Tratamento: diálogo de confirmação que **nomeia o projeto atual e lista quantos flows serão parados**, com o verbo no botão ("Ativar e parar N flows"), não um "OK" genérico (UX-07). Não usa o pendente-até-confirmar da operação (F5 §7.4-4): aquele padrão é para comando de malha com estado publicado; aqui a confirmação é do banco e é síncrona.
5. **Exportar** por linha: `GET /api/projects/{id}/export` pelo primitivo de download de §6.0-3.
6. **Importar** no cabeçalho, em três passos **[NOVA — implementação]** (UX-05, F6R-03):
   1. Escolher arquivo → leitura e `JSON.parse` no cliente (§6.0-2).
   2. **Prévia antes de criar**: contagem de conexões/tags/flows, nome do projeto (campo editável, pré-preenchido, A-6) e — quando o arquivo contiver blocos Script — a lista deles com o código visível e uma confirmação explícita de que executarão no servidor. O admin nunca importa às cegas, e a proveniência do código fica com quem conhece a origem do arquivo.
   3. Enviar. Sucesso ⇒ resumo com `pending_secrets` agrupado por tipo e link para `/engenharia/conexoes`. Recusa ⇒ o `detail` agregado é **partido por ` | `** (§3.2-5) e renderizado como lista, um problema por linha; nunca truncado.
7. Estados vazios: **zero projetos cadastrados** (dia 1 de uma instalação) tem tratamento próprio — chapa com "Nenhum projeto cadastrado" e os dois caminhos possíveis lado a lado, criar ou importar (UX-09). As três telas de §1-3 ganham link para cá. O seletor de operação (`OperateSelectorPage.tsx:46-49`) precisa de **condição nova** para distinguir "sem projeto ativo" de "projeto ativo sem MPC" — hoje exibe a mesma frase nos dois casos (FACT-01).
8. **Invalidação de cache (F6R-11).** Sem isto, Ativar e Importar reintroduzem exatamente o bug de telas presas que motiva a fase. `useActiveProject` usa `["projects"]` (`useConnections.ts:16`), hoje sem chave exportada. A chave é extraída para constante e cada ação invalida o que tocou:

   | Ação | Invalida |
   |---|---|
   | Criar / renomear / excluir projeto | `["projects"]` |
   | **Ativar** | `["projects"]`, `["connections"]`, `["tags"]`, `["flows"]`, `["operate","mpcs"]` — troca o recorte de projeto ativo de todas as telas |
   | **Importar** | as mesmas de Ativar (o projeto nasce inativo, mas a lista muda e o usuário costuma ativar em seguida) |

9. **Reuso honesto (FE-08):** não existe componente de tabela compartilhado entre `ConnectionsPage` e `FlowsPage` — o que se reusa é o *padrão* (estrutura de chapa, `useCanMutate`, modal de formulário, confirmação de exclusão), copiado com adaptação. Ativar, Exportar e Importar não têm análogo em nenhuma das duas e nascem aqui.

### 6.2 Certificados (decisão A-7; RF-202, ADR-021)

1. **Chapa "Certificado da aplicação"** no topo de `/engenharia/conexoes`, visível só para admin. Consome `GET /api/certificates/app` (`schemas/certificates.py:8-14`).
   - **Mitigação de escopo (UX-04, SEC-06):** a chapa fica numa página recortada pelo projeto ativo (`ConnectionsPage.tsx:92-94`), mas o certificado é **da instalação**. O rótulo diz isso literalmente ("vale para todas as conexões de todos os projetos desta instalação") e a chapa é visualmente destacada da tabela por um degrau tonal, não apenas por posição.
   - `fingerprint_sha256`, `not_before`/`not_after` e `application_uri` em **mono tabular** — `application_uri` (`urn:ottima:opc-worker`) é identificador técnico, mesmo tratamento que DESIGN já dá a `node_id`; plaqueta é para rótulo de equipamento/variável, não para identificador (UX-02).
   - Ausente ⇒ estado explícito + botão **Gerar**. Presente ⇒ **Baixar .der** e **Regerar**.
   - **Regerar** manda `force: true`, exige confirmação e **lista as conexões afetadas** antes de executar — as que têm `security_policy != "none"` ou `auth_mode == "certificate"`, computável no cliente com o que a lista de conexões já traz (SEC-06). Ao voltar, exibe o `warning` de re-trust do backend verbatim (`certificates.py:28-31,52`).
   - `GET /app` respondendo 500 com `_MSG_ILEGIVEL` (`certificates.py:33-36`) é estado de erro renderizado com **cor + ícone + texto** (Regra do Canal Redundante), não texto solto (UX-03).
2. **Trust do certificado do servidor** por linha da tabela: "Confiar certificado" (upload, §6.0-2) e "Deixar de confiar" (`DELETE`, idempotente). O `fingerprint_sha256` devolvido (`connections.py:292-298`) é exibido para conferência contra o servidor.
3. Teto de 64 KiB espelhado no cliente (`connections.py:42`) com mensagem pt-BR antes de enviar; o servidor continua sendo a barreira.

### 6.3 Pendência de segredo derivável (decisão A-4)

1. Os **três** predicados de §3.2-8 são os mesmos aqui — uma função só, um lugar de verdade. Dados: `has_password`, `server_cert_file` (`schemas/connections.py:20,65`) e `AppCertificateOut.exists`. **Nenhum campo novo, nenhuma migration.**
2. Coluna **Pendências** na tabela de Conexões: **ícone + rótulo em Texto Secundário, sem cor de severidade** (UX-01). Âmbar é reservado a advertência de processo (DESIGN §Severity), e pendência é estado de **configuração**; no cenário de aceite toda conexão importada acenderia ao mesmo tempo, transformando a Regra da Cor Anormal em ruído permanente. A falha real, quando a conexão tentar subir, já aparece em âmbar/vermelho na coluna "Último estado", que é o canal correto.
3. `title` por pendência com o efeito exato ("a conexão falhará em `cert_missing` até confiar no certificado do servidor" / "…até gerar o certificado de aplicação da instalação"). Sem pendência, célula neutra.
4. Resolver é o que já existe: modal de conexão para a senha, ação de trust para o certificado do servidor, chapa de §6.2 para o certificado de aplicação.
5. Efeito colateral pretendido: conserta um buraco anterior à F6 — conexão criada à mão sem certificado hoje fica muda até o worker falhar.

### 6.4 EU nas portas no editor (§4.1)

Modal de Script e TFS ganha um campo de unidade por porta de saída (opcional, plaqueta como rótulo), com o select de `n_outputs` controlado (§4.1-4). O canvas ao vivo exibe a unidade ao lado do valor da porta, no mesmo tratamento que os nós de OPC dão à EU da tag — mono tabular para o número, Texto Secundário menor para a unidade.

### 6.5 Faceplate de DV com barra (§4.2)

Com `range`, barra vertical com escala demarcada como MV/CV/Restrição. Sem `range`, plaqueta + valor mono tabular + EU. Somente leitura nos dois casos (RF-702).

### 6.6 Débitos de frontend da F5

| # | Débito | Correção |
|---|---|---|
| 1 | Família TTL (`mpc_arm_failed`, 60 s) só reavalia quando chega mensagem — a condição fica acesa numa tela silenciosa | Tique de 5 s no `CanalAoVivoProvider`. `resolverAlarmes` **já recebe `agora: Date`** (verificado), então a assinatura não muda e `alarmes.ts` continua pura. **O tique não pode bumpar o contexto único**: isso re-renderizaria toda página que usa `useCanalAoVivo`, incluindo a operação com trend uPlot, a cada 5 s mesmo sem mensagem. O relógio vive em estado próprio, consumido só por quem deriva alarmes **[NOVA — implementação]** (forma) |
| 2 | Import circular `app/CanalAoVivo.tsx` ↔ `features/flows/useFlowStatus.ts` | É **exatamente um** ciclo de runtime (imports type-only não contam). Os primitivos compartilhados vão para `features/flows/canalPrimitivos.ts`; o plano nomeia os símbolos a mover |
| 3 | `AcaoPendencia.state` tipado como `MpcState`, forçando double-cast | Passa a `unknown`. Verificado seguro e completo: `reduzirPendencia` só usa `state` via `lerCaminho(unknown)`, e o double-cast de `FaceplateVariavel.tsx:148` some sem quebrar outro consumidor |
| 4 | `EventsPage` com `queryKey ["operate","mpcs"]` duplicada | Reusa o hook `useMpcs` |
| 5 | Paleta de 6 cores para teto de 8 penas | Estendida a 8, dessaturada, sem colidir com severidade nem com o Azul Único |
| 6 | `overruns` sem EU no faceplate principal | Rótulo de unidade explícito (contagem) |

---

## 7. Suíte RNF-09 (decisão A-8, revista)

1. **Marcador `rnf09`** novo em `pyproject.toml:29-32`. Comando de execução registrado: `uv run pytest -m rnf09` — o `-m` da linha de comando sobrescreve o `addopts` que exclui `e2e` (verificado empiricamente).
2. **A forma original de A-8 era inviável e foi corrigida** (F6R-01):
   - `grafo_mpc_tfs` (`tests/e2e/conftest.py:612-681`) é hardcoded para `_config_mpc_malha` (2 MVs / 1 CV) e o bloco TFS é travado em exatamente 2×2 por regra de parse (`parse.py:326-327`). O config pesado que garante o overrun é **4 MVs × 6 linhas** (`_N_MV_PESADO`/`_N_ROWS_PESADO`, `test_f4_failure.py:65-66`) e **não cabe** na malha.
   - O cenário de hot-swap prova "troca só quem mudou" com **dois** blocos MPC, sendo `mpc2` o irmão de controle (`test_f4_ws.py:4-6,156-158,301-310`). `grafo_mpc_tfs` produz um único nó `mpc`: reescrever destruiria a prova.
3. **Solução: cada item ganha prova de dinâmica pela TFS, sem perder a prova que já existe.** Nenhum cenário atual é reescrito; dois nascem.

   | Item RNF-09 | Prova pela malha TFS | Prova preservada |
   |---|---|---|
   | Bumpless | `E2E-F4-03` (`test_f4_mpc.py:309`) — já usa `grafo_mpc_tfs` | — |
   | Precedência de restrição | `E2E-F4-05` (`test_f4_mpc.py:398`) — já usa `grafo_mpc_tfs` | — |
   | Overrun | **`E2E-F6-05` (novo)** — MPC pequeno de `grafo_mpc_tfs`, orçamento estreitado por `Ts_mpc` mínimo (multiplicador 1 com `Ts = 0,5 s`) e `Np` elevado via TSS: prova que **a MV congela enquanto a planta continua evoluindo**, que é a dinâmica que o `NODE_SINE` não mostra | `E2E-F4-06` (`test_f4_failure.py:159`) intacto — estresse do solver (dim>150, Np=120) e prova do contador/alarme |
   | Hot-swap | **`E2E-F6-06` (novo)** — troca de config do MPC com a planta TFS viva, provando que o estado da planta e o dos blocos não alterados sobrevivem | `E2E-F4-10` (`test_f4_ws.py:210`) intacto — irmão de controle, prova "só quem mudou" |

4. Os quatro itens ficam sob `rnf09`: `E2E-F4-03`, `E2E-F4-05`, `E2E-F4-06`, `E2E-F4-10`, `E2E-F6-05`, `E2E-F6-06`. Os ids dos cenários de aceite da F4 são **preservados** — renumerá-los quebraria a rastreabilidade das fases anteriores.
5. **Critério de calibração e contingência (RFC-10).** O critério do `E2E-F6-05` é o comportamento do RF-624 (MV inalterada entre execuções, `mpc_overrun` emitido, contador somando, sem acumular fila), **nunca** um número inventado para o teste passar. Se o overrun não for reproduzível de forma determinística na malha pequena — o solve lento arrasta o próprio flow, o que muda o regime —, a contingência é: `E2E-F6-05` reduz o escopo para a asserção de dinâmica (MV constante enquanto a planta evolui, medida ao longo de N varreduras) e a prova de orçamento/contador permanece integralmente em `E2E-F4-06`. O que **não** é aceitável é afrouxar a asserção do `E2E-F4-06`.
6. Não entra nesta fase o nível in-process ligando `mpc_node`+`tfs_node` via `harness_factory`, nem a promoção do `FakeClock` para `tests/testkit/` (hoje duas implementações homônimas e incompatíveis, `test_scheduler.py:35-84` e `test_mpc_block.py:156-165`). Registrado como não-objetivo: o valor seria velocidade de regressão, e o aceite pede prova.

---

## 8. Guia de implantação e comissionamento (decisão A-12; PRD §9-5)

`docs/IMPLANTACAO.md`. Público: o engenheiro de APC que implanta o OttimaSystem numa planta de cliente. Cada passo ancorado no RF/ADR que o governa.

1. **Instalação e primeiro boot** — pré-requisitos de host, `deploy/.env` a partir do `.env.example`, geração manual de `OTTIMA_SECRET_KEY` e `OTTIMA_FERNET_KEY` (`deploy/.env.example:18,22`), `docker compose up -d --build`, 7 serviços, admin do seed, verificação por `/api/health` e pela Home. Registra que a geração dos segredos é manual **por decisão** (§1.2).
2. **Identidade e confiança** — gerar o certificado de aplicação, exportar o `.der` para a trust list do servidor OPC, confiar no certificado do servidor pela UI, o que cada modo de segurança exige, e a exigência de o `applicationUri` casar com `urn:ottima:opc-worker` (`ottima_core/certs.py:34`).
3. **Pré-requisitos do PID por malha** — o coração do §9-5. Por modo-alvo: **RCAS/CAS** exigem SP-tracking; **ROUT** exige OUT-tracking. Tags obrigatórias por MV (escrita, comando de modo, readback) e a opcional (leitura de modo), os valores de `mode_values`, e a consequência de cada uma faltar. Explicita o que o sistema **não** faz: em LOCAL não escreve MV, no boot não reassume malha, em falha de comunicação cessa escrita e para o flow.
4. **Comissionamento passo a passo até AUTO** — projeto, conexão, tags, flow, blocos, `exec_order`, TSS e horizontes, deploy, LOCAL (tracking observado), REMOTO, MAN, AUTO. Checklist por etapa, com o que olhar na tela de operação e em `/eventos`.
5. **Transporte de engenharia entre plantas** — export/import, o que o arquivo não carrega e por quê (§2.3), o procedimento de re-informar segredos, e uma seção sobre **proveniência**: um arquivo de projeto de origem desconhecida traz código Python que executará no servidor; conferir os blocos Script na prévia do import antes de confirmar (§2.3 nota, §6.1-6).
6. **Operação contínua e limites conhecidos** — retenção de 1 mês (ADR-003), backup do Postgres como procedimento manual (`pg_dump` do volume `pgdata`), não-objetivos da v1 (PRD §1).

---

## 9. Testes e gate E2E

### 9.1 Unit/integração (padrões F1 §9 · F2 §11.1 · F3 §7.1 · F4 §9.1 · F5 §9.1)

- **ottima-core:** round-trip puro (projeto → bundle → projeto, com ids diferentes) · tradução dos **seis** campos nos dois sentidos · **teste de completude da lista**: `TAG_REF_FIELDS` conferida por introspecção contra `_CONFIG_KEYS` (`parse.py:19-25`) e contra `PidBinding.model_fields`, pela convenção de nome `*_tag_id` — um bloco novo com referência de tag esquecida vira vermelho (§2.2-3) · schemas de bundle recusam campo proibido (`auth_password`, `server_cert_file`, qualquer id) por `extra="forbid"` · `desired_state` inválido reprovado na camada 2, nunca no `flush()` · `output_eu`: chave fora dos handles reprovada, `OUT{n}` além de `n_outputs` reprovada, config antigo válido · `DvVar.range` opcional, `Range` reusado, config antigo válido.
- **api:** `/projects/{id}/export` (sem segredos, sem ids, `tag_ref` objeto, `Content-Disposition`, 404 com a mensagem de projeto, evento `project_exported`, RBAC) · export com referência irresolvível ⇒ 422 · `/projects/import` (as 4 camadas na ordem de §2.2-5, `detail` agregado com separador ` | ` e teto de 10, 409 de nome, 413 de teto por stream, `schema_version` ≠ 1, `is_active` **sempre false**, os 3 predicados de `pending_secrets` incluindo `needs_app_certificate`, evento `project_imported`, RBAC) · **duas conexões com tag homônima**: o grafo importado aponta para a tag da conexão certa — é o caso que motivou `tag_ref` ser objeto (TST-01) · **nome duplicado dentro do próprio bundle** reprovado na camada 3, sem `IntegrityError` (TST-04) · **`pid` de MPC com chave `_ref` ausente** (não só irresolvível) reprovado sem 500 (TST-05) · **nada gravado quando qualquer camada reprova** · `/api/health` com Redis fora ⇒ `degraded` e 200, handler sem I/O (heartbeat de fundo).
- **flow-runtime (clock controlado):** payload de `mpc_overrun` com `overruns` · §5.2 — nos **três** caminhos, comando de outro flow não espera o build (latência medida) · **`runtime.hosts` vazio imediatamente após o passo 2**, antes de a task de fundo terminar — é o teste que guarda o F6R-06 · nenhum worker órfão · **`_teardown` continua esperando** as tasks destacadas, inclusive as dos caminhos novos (§5.2-3).
- **logging:** `setup_logging(level, service)` grava `service` no JSON; os 4 serviços informam o seu (§3.4-1).
- **frontend `test:unit`:** os 3 predicados de pendência (todas as combinações de `auth_mode` × `has_password` × `security_policy` × `server_cert_file` × `appCert.exists`) · tique de TTL sem bumpar o contexto compartilhado · partição do `detail` agregado por ` | ` preservando `node_id` com `;` · leitura e `JSON.parse` do arquivo com erro tratado · `output_eu` na montagem dos nós · faceplate de DV com e sem `range` · paleta de 8 penas sem colisão · chaves invalidadas por ação (§6.1-8).

### 9.2 Gate E2E — 3 camadas

**L1** — `deploy/smoke.sh`: inalterado + `GET /api/health` expondo `redis_ok`/`db_ok` com `status: ok`.

**L2** — cenários novos:

| Cenário | Prova |
|---|---|
| E2E-F6-01 | Export: sem `auth_password_enc`, sem `server_cert_file`, sem ids nem timestamps; `tag_ref` objeto nos 6 campos; `schema_version: 1`; `Content-Disposition`; evento `project_exported`; RBAC (operador ⇒ 403). O projeto inclui uma conexão `auth_mode: certificate` |
| E2E-F6-02 | **ACEITE PRD §8-F6:** round-trip destrutivo — cria projeto completo (conexão segura + conexão `certificate` + duas conexões com tag homônima + flow MPC↔TFS) ⇒ exporta ⇒ `DELETE` do projeto ⇒ importa ⇒ `pending_secrets` lista as três pendências ⇒ re-informa senha, re-confia o certificado do servidor ⇒ ativa ⇒ deploya ⇒ flow roda e o MPC publica estado. Os ids das tags novas são necessariamente maiores que os exportados (`Identity` não reaproveita valor após `DELETE`) |
| E2E-F6-03 | Recusas: `schema_version: 2`; `tag_ref` órfã; `exec_order` não contíguo; nome duplicado no bundle; nome de projeto colidindo ⇒ 409; corpo > 4 MiB ⇒ 413; operador ⇒ 403. **Banco inalterado após cada recusa** |
| E2E-F6-05 | **RNF-09 overrun pela malha TFS** (§7-3) |
| E2E-F6-06 | **RNF-09 hot-swap pela malha TFS** (§7-3) |

O cenário de `/api/health` degradado **não** existe na L2: derrubar `redis`/`timescaledb` está fora da fase (§1.2) e a suíte proíbe `down` (`tests/e2e/conftest.py:4-6`). A prova é unitária (§9.1) — a versão anterior desta spec listava um E2E-F6-04 que contradizia a própria §1.2 (F6R-07).

Idempotência: E2E-F6-02 e E2E-F6-03 seguem a convenção `RUN_ID` + sentinela de teardown já usada pela suíte (`tests/e2e/conftest.py:46-52`), para serem re-executáveis na mesma stack.

**Suíte RNF-09** (`-m rnf09`): `E2E-F4-03`, `E2E-F4-05`, `E2E-F4-06`, `E2E-F4-10`, `E2E-F6-05`, `E2E-F6-06`.

**Regressão:** os 41 cenários L2 F1-F5 verdes na mesma rodada, com `tests/e2e/test_f4_failure.py:226` atualizado pela tarefa de §5.1 (F6R-08). Playwright F1 serializado após a L2.

**L3** — roteiro `docs/plans/tests-e2e-f6.md`, **executado pelo controlador**:

| ID | Passo |
|---|---|
| B-F6-01 | `/engenharia/projetos`: estado "nenhum projeto cadastrado"; criar, renomear, excluir; excluir o ativo é recusado |
| B-F6-02 | Ativar: confirmação nomeia o projeto atual e o nº de flows a parar; flows param; evento em `/eventos`; as telas de engenharia refletem o novo projeto sem reload (invalidação) |
| B-F6-03 | Chapa do certificado de aplicação: rótulo de escopo de instalação; metadados em mono; baixar `.der`; regerar lista as conexões afetadas e exibe o aviso de re-trust |
| B-F6-04 | Confiar no certificado do servidor (upload), conferir fingerprint; conexão sobe; deixar de confiar |
| B-F6-05 | Exportar: arquivo baixa com o slug; abrir e conferir `tag_ref` e ausência de segredos |
| B-F6-06 | Importar: prévia com contagens, nome editável e **lista dos blocos Script com o código**, exigindo confirmação; resumo de pendências |
| B-F6-07 | Pendências em Conexões: ícone + rótulo sem cor de severidade; as três pendências; resolver cada uma |
| B-F6-08 | Import recusado: lista de problemas, um por linha, com `node_id` contendo `;` legível; nada foi criado |
| B-F6-09 | EU nas portas de Script/TFS: declarar no modal (campos acompanham `n_outputs`), ver unidade no canvas ao vivo |
| B-F6-10 | Faceplate de DV com `range` (barra) e sem `range` (valor + EU); aba Variáveis sinaliza a ausência |
| B-F6-11 | Faixa anunciadora: `mpc_arm_failed` cessa sozinho em 60 s numa tela parada; a tela de operação não pisca a cada 5 s |
| B-F6-12 | Trend com 8 penas: cores distinguíveis, sem colidir com severidade nem com o azul; `overruns` com unidade |
| B-F6-13 | RBAC: operador não vê Projetos, nem a chapa de certificados, nem export/import |

### 9.3 Precondições de ambiente

Herdam o protocolo F3/F4/F5 (CLAUDE.md §Comandos): L2 e Playwright serializados; credenciais sempre inline; `down -v` só com autorização explícita + dump prévio; sempre os dois arquivos compose; nunca `prune`.

---

## 10. Débitos herdados — veredito

| # | Débito | Veredito F6 | Onde |
|---|---|---|---|
| — | UI de gestão de certificados (F2 §1.2) | **Fecha na F6** | §6.2 |
| — | Suíte completa RNF-09 (F4 §1.2, F5 §1.2) | **Fecha na F6** (4 itens com prova pela TFS, provas de estresse preservadas) | §7 |
| — | EU nas portas de Script/TFS (F5 §1.2) | **Fecha na F6** | §4.1 |
| — | `shutdown_mpc` síncrono sob o lock (F5 §8) | **Fecha na F6** nos 3 caminhos reais, em 3 passos; `_teardown` fica | §5.2 |
| — | Payload vazio de `mpc_overrun` | **Fecha na F6** (com a regressão declarada) | §5.1 |
| — | Débitos de frontend da F5 (6) | **Fecham na F6** | §6.6 |
| — | DV sem escala | **Fecha na F6** | §4.2 |
| — | RF-101 sem superfície (desde a F1) | **Fecha na F6** | §6.1 |
| — | RNF-07 sem campo `service` no log | **Fecha na F6** (estava descoberto, não cumprido) | §3.4-1 |
| — | Segredos do `.env` no processo que executa Script | **Fecha o pior impacto na F6**; resíduo em TD-001 | §3.4-2 |
| — | `opc.values.<conn_id>` no `/ws` | **Nunca** — com emenda ao PRD §7.1/§7.3 | §1.2 · §1.3-7 |
| — | Sandbox forte do Script; teto de contagem no import | Fora da v1 — TD-001, TD-002 | §1.2 |
| — | `mpc_state_dimension` conservador · Protocolo `Commandable`/`Healthy` | Ficam | §1.2 |
| — | Nível in-process MPC↔TFS + `FakeClock` canônico | Não-objetivo consciente | §7-6 |

---

## 11. Aderência ao aceite F6 (PRD §8)

| Critério | Evidência na spec |
|---|---|
| Export em JSON com `schema_version`, sem histórico e sem segredos (RF-102 emendado) | §2.1 · §2.3 · §3.1 · §1.3-2 · E2E-F6-01 · B-F6-05 |
| Import com validação, criando projeto **inativo** (RF-103) | §3.2 (4 camadas, transação única) · **§9.1 api: `is_active` sempre false** · E2E-F6-03 · B-F6-06/08 |
| **Projeto exportado importa limpo em instalação nova** | §2.2 (tradução de `tag_ref`; sem ela o aceite falha) · **E2E-F6-02** (o `DELETE` garante ids de destino maiores) · §6.1 e B-F6-01/02/06, sem os quais o aceite é inatingível pela UI (§1-3) |
| **Re-informando segredos** | §2.3 · §3.2-8 (3 predicados) · §6.3 · E2E-F6-02 · B-F6-07 |
| Gestão de certificados (RF-202) | §6.2 (backend F2 + UI + primitivos de arquivo) · B-F6-03/04 |
| Health/heartbeats (RNF-07) | §3.3 (formato **e** mecanismo) · §3.4-1 (campo `service`) · §9.1 · L1 |
| **Suíte MPC↔TFS verde** (RNF-09) | §7 (4 itens com prova pela TFS + provas de estresse preservadas, marcador `rnf09`, critério e contingência de calibração) |
| Guia de integração (PRD §9-5) | §8 |

---

## 12. Mapa de seções por plano (RFC-09)

| Plano | Seções | Fronteira |
|---|---|---|
| `F6a-portabilidade-dados.md` | Etapa 0 (§1.3, todas as 8 emendas + extração das constantes de mensagem) · §2 · §3 · §4.1 (backend) · §4.2 (schema + projeção) · §5 | Entrega `openapi.json` e `contracts.gen.ts` regenerados — é o que o F6b consome |
| `F6b-superficies.md` | §6 inteira (inclui §6.0, a mudança em `api.ts`) · §4.1 (frontend) · §4.2 (faceplate) | Depende dos contratos do F6a |
| `F6c-suite-e-guia.md` | §7 · §9.2 (E2E-F6-01/02/03/05/06) · roteiro L3 · §8 | Depende de F6a (export/import, §5.1 para o contador de `overruns` do critério de §7) e de F6b (as telas que o L3 exercita) |

---

## Anexo A — Decisões do brainstorm (2026-08-07)

| # | Lacuna | Decisão aprovada |
|---|---|---|
| A-1 | Perímetro da última fase | **PRD §8 + guia (§9-5) + os 6 follow-ups da F5 + EU nas portas.** `opc.values` vira **nunca**; backup/restore, correlação de log, limites de recurso e bootstrap de segredos ficam fora (§1.2) |
| A-2 | `graph_json` guarda `tag_id` em 6 campos e `Tag.id` é `Identity` | **Reescrita na fronteira:** `tag_ref` **objeto** `{connection, tag}`, traduzido por lista explícita nos dois sentidos. Emenda PRD §7.2 → v1.4 |
| A-3 | O `.der` do servidor confiado no bundle | **Fora**, re-confiar no destino: em outra planta o pinning antigo é pior que ausente |
| A-4 | Nada sinaliza a pendência de segredo | **Pendência derivável**, sem campo novo, na página de Conexões; o import devolve `pending_secrets` |
| A-5 | Bundle com N problemas × contrato de string única | **Valida as 4 camadas, aborta e devolve 422 agregando até 10 problemas** numa string, separador ` | ` |
| A-6 | `Project.name` é UNIQUE global | **Nome editável no import**; colidindo ⇒ 409 |
| A-7 | O certificado de aplicação não tem casa | **Chapa no topo da página de Conexões**, só admin, com rótulo de escopo de instalação. Upload por corpo bruto |
| A-8 | RNF-09 com overrun e hot-swap fora da TFS | **Revista após a revisão (F6R-01):** cada item ganha prova de dinâmica pela malha TFS em cenário novo (`E2E-F6-05`/`E2E-F6-06`) e **mantém** a prova existente (`E2E-F4-06`/`E2E-F4-10`), porque `grafo_mpc_tfs` é hardcoded, o TFS é travado em 2×2 e o hot-swap depende do irmão de controle. Marcador `rnf09` sobre os seis |
| A-9 | Provar "instalação nova" sem violar a proibição de `up`/`down` | **Round-trip destrutivo do projeto**: os ids de destino são necessariamente maiores porque `Identity` não reaproveita valor após `DELETE` |
| A-10 | Portas de Script/TFS sem unidade | **`output_eu` por handle de saída**, nos dois lados do stack, sem propagação automática |
| A-11 | `DvVar` sem faixa | **`range: Range \| None`**, reusando o tipo de `ConstraintVar` |
| A-12 | PRD §9-5 manda produzir o guia | **`docs/IMPLANTACAO.md` único** |
| A-13 | RF-101 sem UI e export/import sem casa | **Página `/engenharia/projetos` completa** |
| A-14 | RF-102 diz "projeto ativo", mas o aceite exige exportar um projeto que será apagado | **Emendar RF-102** para "export de um projeto (por id)" (§1.3-2) |
| A-15 | O import quebra a premissa de confiança do ADR-018 | **Fechar o vazamento agora**: `env_file` do `flow-runtime` restrito (§3.4-2), mais consentimento explícito na prévia do import (§6.1-6) e seção de proveniência no guia (§8-5). Sandbox forte fica fora da v1 (TD-001) |
| A-16 | RNF-07 "logs estruturados por serviço" está descoberto | **Trazer o campo `service` para a F6** (§3.4-1); correlação entre serviços continua fora |

## Anexo B — Revisão aplicada (2026-08-07)

Sete agentes em paralelo, um por facet. Consolidado em `.claude/reports/review/review-spec-f6-consolidado-20260807.md`; relatórios por facet no mesmo diretório. **74 achados brutos (15 Critical), 68 após deduplicação — todos aplicados nesta versão.**

| Facet | Agente | Veredito | C/I/m |
|---|---|---|---|
| Coerência normativa, escopo, aceite | `rfc` | REQUEST CHANGES | 4/6/6 |
| Verificação factual (75 âncoras, sem amostragem) | `scout` | REQUEST CHANGES | 1/4/8 |
| Contratos de API, validação, transação | `fastapi-reviewer` | REQUEST CHANGES | 3/4/3 |
| Implementabilidade no frontend | `react-reviewer` | REQUEST CHANGES | 4/3/1 |
| Conformidade DESIGN/PRODUCT | `ux-designer` | APPROVE WITH CHANGES | 0/10/2 |
| O plano de testes prova o que promete | `pr-test-analyzer` | REQUEST CHANGES | 3/4/2 |
| Superfície de segurança | `security-reviewer` | APPROVE WITH CHANGES | 0/6/0 |

| Achado | Aplicação |
|---|---|
| F6R-01 (A-8 inviável) | §7-2/3/5 · A-8 revista · E2E-F6-05/06 |
| F6R-02 (RF-102 sem emenda) | §1.3-2 · §3.1-3 · A-14 |
| F6R-03 (premissa do ADR-018) | §2.3 nota · §3.4-2 · §6.1-6 · §8-5 · A-15 · TD-001 |
| F6R-04 (RNF-07 descoberto) | §3.4-1 · §1.2 (linha corrigida) · A-16 |
| F6R-05 (bundle não importável pela própria regra) | §2.1-1/2/3 — schemas próprios com `extra="forbid"` |
| F6R-06 (`detach_hosts` omitido) | §5.2-2 — três passos · teste de `runtime.hosts` vazio em §9.1 |
| F6R-07 (E2E-F6-04 contraditório) | removido de §9.2; prova unitária em §9.1 |
| F6R-08 (regressão de `mpc_overrun`) | §5.1 · §9.2 regressão |
| F6R-09 (`output_eu` sem casa) | §4.1-2 — os dois lados |
| F6R-10 (helper `api()`) | §6.0 — seção nova, dois primitivos + download autenticado |
| F6R-11 (invalidação de cache) | §6.1-8 — tabela por ação |
| F6R-12 (`desired_state` ⇒ 500) | §2.1-3 |
| F6R-13 (`/health` sem mecanismo) | §3.3-2 |
| F6R-14 (pendência cega ao cert de aplicação) | §3.2-8 (3º predicado) · §6.3-1 |
| RFC-05..10 | §1.3-1 (lista completa) · §1.3-7 · §1.3-6 (registro corrigido) · §11 (evidências trocadas) · §12 (mapa de planos) · §7-5 (critério e contingência) |
| FACT-01/02/10, 04..09, 12, 13 | §1-3 (três telas) · §6.1-7 · §3.1-3 (`projects.py:21`) · §3.3-1 (`runtime_up`) · âncoras corrigidas em todo o documento |
| API-02/05/06/07, 08..10 | §2.1-2 · §2.2-4/5 (ordem) · §3.2-1 (stream) · §3.2-8 (predicado único) · §3.2-9 (kinds em `bus.py`) |
| FE-02/06/07/08 | §4.1-4 · §6.6-1 (sem re-render global) · §6.6-2 (módulo nomeado) · §6.1-9 (reuso honesto) |
| UX-01..10 | §6.3-2 (sem âmbar) · §6.2-1 (mono, escopo, canal redundante) · §6.1-4/6/7 (peso de Ativar, prévia, estado vazio) · §3.2-5 (separador ` \| `) · §6.1-2 (azul no "Ativo") · §1.3-8 (GLOSSARY) |
| TST-01/04/05/06/07/09 | §9.1 (tag homônima, nome duplicado, `pid` parcial, introspecção) · §7-1 (comando) · §9.2 (`RUN_ID`) |
| SEC-02/04/05/06 | §2.3 (terceiro motivo) · §1.2 + TD-002 · §3.1-4 (auditoria de export) · §6.2-1 (conexões afetadas) |

**Verificação positiva de maior peso:** o risco de falso-verde do `E2E-F6-02` foi **descartado com cadeia de evidência completa** — `Identity(always=True)` nos três models, CASCADE real no banco, sequences Postgres não revertem por `DELETE`, nenhum `RESTART IDENTITY` em `tests/e2e`, banco persistente por volume nomeado, e a camada 4 resolve `tag_id` contra o mapa do próprio projeto. A decisão A-9 está correta.
