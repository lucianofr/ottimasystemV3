# Spec F6 — Portabilidade & hardening (export/import, certificados, suíte RNF-09)

**Fase:** F6 (PRD §8) — **última fase da v1** · **Status:** aprovado em blocos em sessão de brainstorm (2026-08-07)
**Fontes normativas:** `docs/PRD.md` v1.3→v1.4 (RF/RNF, contratos §7, fases §8, riscos §9) · `docs/adr/ADR-001…024` (prevalecem em conflito) · `docs/GLOSSARY.md` · `PRODUCT.md`/`DESIGN.md` (frontend) · specs F1/F2/F3/F4/F5 (vinculantes)
**Execução:** 1 spec (esta) + 3 planos — F6a (portabilidade & dados), F6b (superfícies), F6c (suíte RNF-09 & guia), decisão A-1.

Convenções herdadas: itens **[NOVA — implementação]** são decisões de implementação desta spec, sem lastro literal em RF/ADR; o Anexo A registra as decisões do brainstorm; testes citam itens numerados (ex.: §3.2-4).

---

## 1. Escopo da F6

**Entrega (PRD §8-F6):** export/import JSON, gestão de certificados, health/heartbeats, testes RNF-09.
**Aceite (PRD §8-F6):** projeto exportado importa limpo em instalação nova (re-informando segredos); suíte MPC↔TFS verde.

Três fatos de levantamento moldam a fase e precisam ficar escritos, porque contrariam a leitura ingênua do PRD §8:

1. **Certificados é fase de frontend, não de backend.** RF-202 foi entregue inteiro na F2 — `POST /api/certificates/app/generate`, `GET /api/certificates/app`, `GET /api/certificates/app/export` (`routers/certificates.py:39-80`) e o trust por conexão `POST`/`DELETE /api/connections/{id}/server-certificate` (`routers/connections.py:250-323`), com a lógica X.509 em `ottima_core/certs.py`. A spec F2 §1.2 já registrava "UI fica na F6". Nenhum componente React consome esses quatro endpoints hoje; eles só existem em `frontend/src/lib/api-types.ts`.
2. **`overrun` e `hot-swap` não passam pela TFS em nenhum nível de teste.** É decisão documentada da F4b (`tests/e2e/test_f4_failure.py:1-7`, `tests/e2e/test_f4_ws.py:1-6`): os dois cenários de aceite usam `opc_read` dummy (`NODE_SINE`), não `grafo_mpc_tfs`. Ao pé da letra do RNF-09 ("malha fechada MPC↔TFS … cobrindo bumpless, precedência de restrição, overrun e hot-swap"), metade do requisito está descoberta.
3. **RF-101 não tem superfície.** `POST /api/projects`, `PATCH`, `DELETE` e `POST /{id}/activate` existem desde a F1 e nenhum componente os chama — o frontend só faz `GET /api/projects` para descobrir o ativo (`features/connections/useConnections.ts:14-20`). Quatro telas exibem "Nenhum projeto ativo: ative um projeto para…" apontando para uma tela inexistente (`ConnectionsPage.tsx:177`, `FlowsPage.tsx:294`, `TagsPage.tsx:54`, `OperateSelectorPage.tsx:48`). Sem essa tela o próprio aceite da F6 é inatingível pela UI: o import cria projeto **inativo** (RF-103) e ninguém consegue ativá-lo.

### 1.1 Dentro da F6

| Item | Governança |
|---|---|
| Bundle de projeto (`tag_ref`, sem segredos) + emenda PRD §7.2 → v1.4 | RF-102 · ADR-012 · decisão A-2 · §2 |
| `GET /api/projects/{id}/export` | RF-102 · §3.1 |
| `POST /api/projects/import` (4 camadas de validação, transação única) | RF-103 · decisões A-5/A-6 · §3.2 |
| `GET /api/health` da api passa a refletir `redis_ok`/`db_ok` | RNF-07 ("health/heartbeats" é entrega literal da F6) · §3.3 |
| Página `/engenharia/projetos` (CRUD + ativar + export + import) | **RF-101 sem UI desde a F1** · decisão A-13 · §6.1 |
| UI do certificado de aplicação + trust por conexão + primitivo de upload | RF-202 · ADR-021 · decisão A-7 · §6.2 |
| Pendência de segredo derivável na página de Conexões | aceite F6 ("re-informando segredos") · decisão A-4 · §6.3 |
| EU por porta de saída de Script/TFS (`output_eu`) | DESIGN §Typography (Regra do Número Tabular) · decisão A-10 · §4.1 |
| `range` opcional na `DvVar` + barra vertical no faceplate de DV | RF-702 · DESIGN §Shapes · decisão A-11 · §4.2 |
| Suíte RNF-09: os 4 itens pela TFS, sob marcador `rnf09` | RNF-09 · ADR-022 · decisão A-8 · §7 |
| `docs/IMPLANTACAO.md` — guia de implantação e comissionamento | PRD §9-5 ("guia de integração, F6") · decisão A-12 · §8 |
| Débitos de runtime da F5: payload de `mpc_overrun`; `shutdown_mpc` fora do lock | spec F5 §8 · decisão A-1 · §5 |
| Débitos de frontend da F5: tique de TTL, import circular, `AcaoPendencia.state`, `queryKey` duplicada, paleta de 8 penas, `overruns` com EU | spec F5 (ledgers de execução) · decisão A-1 · §6.6 |

### 1.2 Fora da F6 — com destino registrado

| Item | Destino | Governança |
|---|---|---|
| `opc.values.<conn_id>` no `/ws` | **nunca** — sem consumidor real; o trend de engenharia segue polling | decisão A-1; encerra o registro aberto em F2 §1.2, F3 §1.2 e F5 §1.2 (§1.3-4) |
| Backup/restauração do Postgres (mecanismo) | fora da v1 — sem RF/ADR; o guia documenta `pg_dump`/`pg_restore` como procedimento manual, sem prometer automação | decisão A-1 · §8 |
| Campo `service` e correlação (`request_id`) nos logs | fora da v1 — RNF-07 pede "logs estruturados por serviço" e o JSON de `ottima_core/logging.py:9-22` já cumpre | decisão A-1 |
| Limites de recurso (`mem_limit`/`cpus`) e teto de tentativas de restart no compose | fora da v1 — sem RF; `unless-stopped` + healthchecks + `depends_on: service_healthy` cobrem RNF-06 | decisão A-1 |
| Bootstrap que gera os segredos do `.env` automaticamente | fora da v1 — passo manual documentado no guia (§8) | decisão A-1 |
| Cenário E2E que derruba `redis`/`timescaledb` como container real | fora da v1 — a resiliência está provada em unit/integração nos 4 serviços; a suíte E2E tem proibição explícita de `up`/`down` (`tests/e2e/conftest.py:14-16`) | decisão A-1 |
| ACK de alarmes | fora da v1 | ADR-020 |
| Protocolo `Commandable`/`Healthy` (5 `isinstance` em `supervisor_mpc.py`) | revisitar no 2º bloco comandável | spec F5 §1.2 |
| Persistir predição/custo/status do MPC | nunca | ADR-016 |
| `mpc_state_dimension` conservador | fica como está | spec F4 §2.2-7 · F5 §1.2 |
| Migração de `schema_version` antigo no import | não existe versão anterior a 1; quando existir, é ADR | §3.2-2 |

### 1.3 Emendas a documentos anteriores (consolidação)

O PRD tem regra explícita de correção (`PRD.md` §nota inicial); specs anteriores recebem **nota de remissão** a esta spec no trecho alterado. Aplicação: **Etapa 0 do plano F6a**, antes de qualquer código — mesmo rito da Etapa 0 da F5a.

| # | Documento · trecho | O que muda |
|---|---|---|
| 1 | PRD §7.2 (JSON de projeto) + changelog v1.4 | O exemplo passa a espelhar os schemas `Create` (campos planos `security_*`/`watchdog_*`, `direction`/`data_type`/`description` no lugar de `dir`), ganha `exported_at`, `desired_state` e a referência `tag_ref` dentro do `graph` (§2) |
| 2 | Spec F2 §1.2 ("UI de gestão de certificados \| F6") | Cumprida por §6.2 |
| 3 | Spec F4 §1.2 / F5 §1.2 ("suíte completa RNF-09 \| F6") | Cumprida por §7 |
| 4 | Spec F2 §1.2 / F3 §1.2 / F5 §1.2 (`opc.values` no `/ws`) | Reapontado para **nunca** (§1.2) — o registro deixa de ficar aberto |
| 5 | Spec F5 §1.2 ("EU nas portas de Script/TFS \| F6") | Cumprida por §4.1 |
| 6 | Spec F5 §8, última linha (`shutdown_mpc` síncrono sob o lock) | Fecha em §5.2, com a correção do inventário: são **3** caminhos, não 4 — `_teardown` não roda sob o lock e é o único onde esperar é correto |

---

## 2. Contrato de portabilidade

### 2.1 O bundle espelha os schemas `Create` (decisão A-2; emenda PRD §7.2 → v1.4)

1. O JSON de projeto **não inventa vocabulário**: cada entidade do bundle é o schema `Create` correspondente menos os segredos e menos os ids. A consequência é operacional, não estética — o import reusa `ConnectionCreate._coerencia` (`schemas/connections.py:30-41`: policy×mode coerentes, watchdog em par, usuário/senha juntos) como **camada 2 de validação**, de graça, sem uma segunda cópia das mesmas regras.

2. Forma normativa:

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

3. `exported_at` (UTC, ISO-8601) é metadado de arquivo, não de entidade: nenhum consumidor de código o lê, e o import o ignora. Existe porque o bundle é artefato físico que circula entre plantas e reaparece meses depois **[NOVA — implementação]**.
4. `desired_state` do Flow **é exportado verbatim**: é intenção de engenharia persistida (RF-306), e o import não auto-aplica nada — exatamente como o boot (RF-104). Um flow importado com `desired_state = "running"` nasce parado e aparece como "Rodando (desejado)" na lista, que é a mesma semântica de depois de um restart.
5. `Tag.name` é único por **conexão**, não por projeto (`models/tag.py:33`); `Connection.name` e `Flow.name` são únicos por projeto. O bundle herda essas garantias por construção (veio de um projeto válido) e o import as reafirma como camada 3 (§3.2-4).

### 2.2 Referência de tag dentro do grafo (`tag_ref`)

1. `graph_json` guarda `Tag.id` inteiro em **seis campos**, e `Tag.id` é `BigInteger Identity` — a instalação de destino recria as tags com ids novos. Sem tradução, todo flow importado aponta para tag inexistente e o aceite da fase falha:

| Bloco | Campo no banco | Campo no bundle | Âncora |
|---|---|---|---|
| `opc_read`, `opc_write` | `config.tag_id` | `config.tag_ref` | `flowgraph/parse.py:46-51`; `_CONFIG_KEYS` em `:19-25` |
| `mpc`, por MV em `config.variables.mvs[i].pid` | `write_tag_id` | `write_tag_ref` | `flowgraph/mpc_config.py:58-68` |
| idem | `mode_cmd_tag_id` | `mode_cmd_tag_ref` | idem |
| idem | `mode_read_tag_id` (opcional) | `mode_read_tag_ref` (opcional) | idem |
| idem | `readback_tag_id` | `readback_tag_ref` | idem |

2. `tag_ref` é **objeto**, não string: `{"connection": "gateway-1", "tag": "TT-101"}`. Nome de conexão e de tag são texto livre e podem conter `/`; a forma `"conexao/tag"` exigiria uma regra de escape nova sobre dados que já existem em produção, e a ambiguidade só apareceria na planta de um cliente. Mesmo tamanho de código, correto na borda.
3. A tradução é **explícita por campo**, nunca varredura heurística de "qualquer chave terminada em `_tag_id`": a lista dos seis campos vive num lugar só, e um bloco futuro que ganhe referência de tag precisa entrar nela. O teste de §9.1 guarda essa lista contra `_CONFIG_KEYS` e `PidBinding`, para que o esquecimento vire vermelho e não bug de campo.
4. Sentido export: `tag_id` → busca no mapa `{id: (connection_name, tag_name)}` do projeto → `tag_ref`. Referência que não resolve (tag de outro projeto num grafo salvo antes de alguma validação) **aborta o export com 422**, nunca exporta bundle quebrado.
5. Sentido import: `tag_ref` → busca no mapa `{(connection_name, tag_name): novo_id}` construído após o `flush()` das tags na mesma transação → `tag_id`. Referência órfã é erro de camada 3 (§3.2-4).

### 2.3 O que não atravessa a fronteira

| Campo | Motivo |
|---|---|
| `auth_password_enc` | segredo (ADR-012/021); re-informado no destino (§6.3) |
| `server_cert_file` e o `.der` confiado | decisão A-3: material público, mas **ambiente-específico**. No caso de uso principal do ADR-012 — levar engenharia para outra planta — o endpoint muda e o certificado do servidor antigo é pior que ausente: instala um pinning errado, que falha em `cert_mismatch` (`opc-worker/security.py:115-125`), diagnóstico mais confuso que o `cert_missing` de quem não confia em ninguém |
| `id`, `project_id`, `connection_id` | ids internos; substituídos por nome lógico (§2.2) |
| `is_active` | RF-103: import cria projeto **inativo**, sempre; o campo nem sai no bundle |
| `created_at`, `updated_at` | metadado da instalação de origem |
| `User` | global à instalação, não é filho de Project (PRD §4); gestão de usuários é RF-002 |
| `samples`, `events`, `mpc_samples` | RF-102: "sem dados históricos" |

---

## 3. API nova e correções

### 3.1 `GET /api/projects/{id}/export` (RF-102; router `projects`; `require_admin`)

1. `require_admin` — PRD §2 põe "Export/import de projeto" na linha exclusiva de admin. Mesmo sem segredos, o bundle revela a topologia OPC completa da planta.
2. Resposta `application/json` com `Content-Disposition: attachment; filename="<slug-do-nome>.ottima.json"` — mesmo padrão do export de certificado (`routers/certificates.py:76-80`). O slug reduz o nome do projeto a `[a-z0-9-]`; nome que reduz a vazio cai em `projeto` **[NOVA — implementação]**.
3. Exporta **qualquer** projeto por id, não só o ativo (o caso "arquivar a engenharia antes de ativar outra" é real). 404 pt-BR para projeto inexistente, constante única com `flows.py:55`.
4. Sem paginação e sem filtro: o teto de dimensionamento é ~10 flows, ≤5 conexões e ~100 tags (RNF-01), e nenhum router do sistema pagina (padrão F1 §6.1).

### 3.2 `POST /api/projects/import` (RF-103; router `projects`; `require_admin`)

1. Corpo `{"name": "...", "bundle": {…}}`, onde `name` é **opcional** e sobrescreve `bundle.project.name` (decisão A-6). Teto de **4 MiB** no corpo, recusado com 413 e mensagem pt-BR **[NOVA — implementação]** — o teto de 64 KiB do certificado (`connections.py:42`) é pequeno para 10 flows com config de MPC, e um limite explícito é melhor que o do servidor web.
2. `schema_version` diferente de `1` ⇒ 422 imediato, sem tentativa de migração: não existe versão anterior. Quando existir, a política de compatibilidade é decisão de ADR, não de código.
3. **Transação única** — tudo-ou-nada, mesmo padrão de `activate_project` (`projects.py:77-108`). Nada é gravado antes de as quatro camadas passarem.
4. Validação em quatro camadas, em ordem determinística, **toda ela antes do commit**:

   | # | Camada | O que reprova |
   |---|---|---|
   | 1 | `schema_version` | valor ≠ 1 |
   | 2 | Forma (Pydantic, schemas `Create` reusados) | tipo errado, campo faltando, enum inválido, `ts_seconds` fora da lista, `_coerencia` de conexão |
   | 3 | Referências internas | tag apontando para conexão ausente do bundle; `tag_ref` que não casa com nenhuma tag do bundle; nome duplicado dentro do próprio bundle |
   | 4 | Grafo | `flowgraph/parse.py` + `flowgraph/validate.py` por flow, com o mapa de tags já materializado pelo `flush()` — o mesmo validador que o editor e o deploy usam, sem segunda implementação |

5. **Recusa: 422 com `detail` string única pt-BR agregando até 10 problemas**, no formato `"Import recusado (3 problemas): flows[2].graph: nó 'mpc_x7k2' refere tag inexistente (conexão 'gateway-1', tag 'TT-999'); tags[7]: conexão 'gateway-2' não existe no arquivo; connections[0]: SecurityPolicy None exige modo None"`. Acima de 10, sufixo `"; e mais N"`. O contrato universal de erro da API (string única, `app.py:60-67`) fica intacto — nenhuma rota ganha corpo de erro estruturado. A varredura completa custa o mesmo que parar no primeiro problema, porque o laço sobre os flows acontece de qualquer jeito. A mensagem nunca renderiza `tag_ref` como `"conexão/tag"`: a forma é objeto (§2.2-2) e um texto com barra convidaria a reintroduzi-la.
6. Nome de projeto já existente ⇒ **409** com a mensagem de `create_project` (`projects.py:38-41`), constante única. É a única reprovação de **conteúdo** fora do 422 — colisão de unicidade tem convenção própria no sistema; o 413 do item 1 é de transporte e nem chega às camadas.
7. Sucesso ⇒ **201** com `ProjectImportOut`:

```json
{"project": { /* ProjectOut, is_active sempre false */ },
 "pending_secrets": [
   {"connection_name": "gateway-1", "needs_password": true, "needs_server_certificate": true}
 ]}
```

   `pending_secrets` é **derivado**, não persistido: `needs_password := auth_mode == "user_password"`, `needs_server_certificate := security_policy != "none"`. É o mesmo predicado que a página de Conexões avalia continuamente (§6.3) — a mesma verdade, calculada no mesmo lugar conceitual, exposta aqui só para o resumo do import poder dizer o que falta sem uma segunda consulta.
8. O import **não publica** `project_activated` (não ativa nada) e emite um evento de auditoria `project_imported` (severity `info`, origin `user:<id>`, payload com contagens de conexões/tags/flows) **[NOVA — implementação]** — toda mutação de engenharia já audita (`connections.py:240-247` é o padrão), e um projeto inteiro aparecendo do nada sem rastro seria a única exceção.

### 3.3 `GET /api/health` da api reflete as dependências (RNF-07)

1. Hoje a rota devolve `{"status": "ok", …}` fixo (`routers/health.py:17-19`), sem consultar Redis nem Postgres — os outros três serviços derivam `status` de `redis_ok and db_ok` (`opc-worker/main.py:108-135`, `flow-runtime/main.py:129-160`, `recorder/main.py:67-86`). O agregador da F5 herda a mentira: um api com Postgres fora responde `ok`.
2. Passa a devolver `{"status": "ok"|"degraded", "service": "api", "version": …, "redis_ok": bool, "db_ok": bool}`, **sempre 200** — mesmo contrato dos outros três (degradação vai no corpo, healthcheck do compose não derruba o container por dependência externa).
3. A rota segue pública (sem autenticação): é o healthcheck do compose (`docker-compose.yml:43-48`) e o passo E2E-01a do smoke.

---

## 4. Schema

### 4.1 EU por porta de saída de Script e TFS (decisão A-10; RF-511/521, DESIGN §Typography)

1. DESIGN §Typography, Regra do Número Tabular: "número sem unidade de engenharia é defeito". Tags têm `eu` (`models/tag.py:29`) e as variáveis do MPC têm `eu` (`mpc_config.py`), então OPC-Read/Write e faceplates cumprem. Script e TFS não têm onde declarar, e o canvas ao vivo (RF-305/404) mostra número pelado.
2. Campo novo `output_eu: dict[str, str] = {}` no `config` de `script` e de `tfs`, no `graph_json` (JSONB — **sem migration**). Chave = nome do handle de saída; valor = unidade.
3. Handles de saída válidos, verbatim de `flowgraph/validate.py:99-111`: `script` ⇒ `OUT1..OUT{n_outputs}`; `tfs` ⇒ `y1`, `y2`. Chave fora desse conjunto é erro de parse (os configs são `extra="forbid"`; a chave entra em `_CONFIG_KEYS`, `parse.py:19-25`). Para `script` a validação depende de `n_outputs` no mesmo modelo ⇒ `model_validator`.
4. **Portas de entrada não declaram EU** — herdam da porta de origem pela aresta, resolvido no cliente. Saída sem declaração fica sem unidade, como `Tag.eu` já admite (default `''`). Nada é obrigatório: um flow existente continua válido byte a byte.
5. Sem propagação automática: o Script existe em boa parte para converter grandeza, e um rótulo de unidade **errado** num console de operação é pior que unidade ausente.
6. Regenera `contracts.gen.ts` (`ottima_core/contracts_export.py`).

### 4.2 `range` opcional na `DvVar` (decisão A-11; RF-702, DESIGN §Shapes)

1. `DvVar` tem só `id`/`name`/`eu` (`flowgraph/mpc_config.py:128-135`) — sem faixa. RF-702 lista os faceplates de variável "com EU e **limites**" e DESIGN §Shapes chama a barra vertical de convenção intocável; a F5 entregou DV sem barra por falta de schema.
2. Campo `range: Range | None = None` — **o mesmo tipo `Range` `{low, high}` já usado por `ConstraintVar`** (`mpc_config.py:39-46`), não um tipo novo. JSONB, sem migration, opcional: nenhum config existente quebra.
3. Projetado por `GET /api/operate/mpcs` no bloco `dvs` (spec F5 §4.1-1), junto de `id`/`name`/`eu`.
4. Com faixa, o faceplate de DV desenha barra vertical com escala demarcada como MV/CV/Restrição; sem faixa, plaqueta + valor mono tabular + EU, sem barra (§6.5).
5. Editável na aba **Variáveis** do modal do MPC (RF-607), ao lado dos campos de DV existentes.

---

## 5. Runtime — débitos herdados da F5

### 5.1 Payload de `mpc_overrun`

`blocks/mpc.py:453-463` publica `payload={}`. Passa a publicar `{"overruns": <contador>}`, tornando a família "contador publicado" simétrica a `flow_overrun` (spec F5 §7.2-1) e dando ao evento o mesmo dado que a faixa anunciadora já lê do estado publicado. Nenhuma outra mudança de kind, severidade ou dedupe.

### 5.2 `shutdown_mpc` fora do lock global (spec F5 §8, última linha)

1. **Correção do inventário herdado.** O lock é `Supervisor._lock` (`supervisor.py:172`), tomado em quatro lugares: comandos (`:259`), `on_comm_failure` (`:477`), `on_project_activated` (`:494`) e `_pass` (`:517`). O `shutdown_mpc` **síncrono** (`supervisor_mpc.py:417`) sobrevive em **três** caminhos sob o lock, não quatro:

   | # | Chamador | Âncora | Sob qual tomada do lock |
   |---|---|---|---|
   | 1 | `_deploy`, sobre o `old_runtime` do redeploy | `supervisor.py:338` | `:259` (comando) |
   | 2 | `_handback_failed_mpc`, na varredura de watermark | `supervisor.py:548` | `:517` (`_pass`) |
   | 3 | `_force_stop` | `supervisor.py:597` | `:494` (`on_project_activated`) e `:517`→`:558`/`:563` (`_reconcile_flow`) |

   `_teardown` (`supervisor.py:643`) **não** roda sob o lock — é chamado por `Supervisor.stop()` (`:219-222`) — e é o único lugar onde esperar o desmonte é o comportamento correto: `:644-649` já aguarda `runtime.mpc_stop_tasks` de propósito, para o desligamento do serviço nunca abandonar um kill em voo (invariante da spec F5 §6.5). **Fica como está.**

2. Nos três caminhos, `shutdown_mpc` (`supervisor_mpc.py:417`) é substituído pelo par que a F5 já extraiu: `revert_armed_mpc` (`supervisor_mpc.py:395`, devolve `mode_cmd=auto` de todo bloco armado e **não espera processo nenhum**) executado sob o lock, seguido de `stop_host_background` (`supervisor_mpc.py:359`, remove o host do mapa e destaca o desmonte). A ordem é normativa: a devolução do PID acontece antes de soltar o host, então em nenhum instante existem dois workers podendo escrever na mesma malha.
3. **Restrição normativa sobre a posse das tasks destacadas:** no caminho 1 o `_FlowRuntime` antigo é substituído no mapa, então uma task destacada pendurada em `old_runtime.mpc_stop_tasks` ficaria órfã e o `_teardown` do serviço voltaria a poder abandonar um kill em voo. As tasks destacadas desses caminhos precisam de dono que sobreviva à troca de `_FlowRuntime` — conjunto no `Supervisor` ou transferência para o runtime novo **[NOVA — implementação]** (forma). Sem isso a correção reintroduz o defeito que a F5 §6.5 fechou.
4. Invariantes preservadas byte a byte: idempotência (`revert_armed_mpc` guarda por `block.local_remote`, `MpcHost.stop()` idempotente), `mpc_arm_failed {worker_not_ready}` nos dois eixos, shed/hot-swap/watchdog de armar intocados, nenhum worker órfão após stop durante build.
5. Prova: latências medidas com clock controlado (§9.1) — comando de outro flow não espera `_BOOT_TIMEOUT_S = 30 s` em nenhum dos três caminhos.

---

## 6. Frontend

Autoridade visual: `PRODUCT.md`/`DESIGN.md`. Tudo pt-BR com o vocabulário do `GLOSSARY.md`, sem emojis. Campo grafite, chapas, linhas 1px, cantos 2-4px, plaquetas em rótulo de tag/equipamento, mono tabular em todo valor, cor reservada a estado e ao azul único de interação, severidade sempre com canal redundante (cor + ícone + texto).

### 6.1 Página `/engenharia/projetos` (decisão A-13; RF-101/102/103)

1. Rota nova em `app/router.tsx`, item novo no grupo de engenharia do nav (`Projetos · Conexões · Tags · Flows · Trend`) — o grupo Operação da F5 não muda.
2. Tabela (chapa, padrão byte a byte de `ConnectionsPage`/`FlowsPage`): nome, descrição, **Ativo** como lâmpada de estado (quadrado + ícone + rótulo, nunca só cor), ações.
3. Mutações só para admin (`useCanMutate`, padrão existente): criar, renomear/editar descrição, excluir (confirmação; o backend já recusa excluir o ativo com 409 — `projects.py:67-75`).
4. **Ativar** exige confirmação explícita com o efeito escrito: "Ativar 'X' encerra a execução de todos os flows do projeto atual" (RF-101, ADR-017). É a única ação da tela com consequência de processo.
5. **Exportar** por linha: dispara `GET /api/projects/{id}/export` e salva o arquivo pelo `Content-Disposition`.
6. **Importar** no cabeçalho: seleção de arquivo (primitivo de §6.2-3), campo **Nome do projeto** pré-preenchido com `bundle.project.name` e editável (A-6), e ao concluir um resumo com `pending_secrets` — contagem por tipo e link para `/engenharia/conexoes`. Recusa exibe o `detail` agregado (§3.2-5) inteiro, sem truncar.
7. Sem projeto ativo, as quatro telas que hoje dizem "ative um projeto" ganham link para cá.

### 6.2 Certificados (decisão A-7; RF-202, ADR-021)

1. **Chapa "Certificado da aplicação (instalação)"** no topo de `/engenharia/conexoes`, acima da tabela, visível só para admin. Consome `GET /api/certificates/app` (`AppCertificateOut`: `exists`, `subject`, `fingerprint_sha256`, `not_before`, `not_after`, `application_uri` — `schemas/certificates.py:8-14`). Fingerprint e datas em mono tabular; `application_uri` como plaqueta.
   - Ausente ⇒ estado explícito ("não gerado") + botão **Gerar**.
   - Presente ⇒ botões **Baixar .der** (`GET /app/export`) e **Regerar**. Regerar manda `force: true`, exige confirmação e, ao voltar, exibe o `warning` de re-trust que o backend já devolve (`certificates.py:28-31,52`) — **verbatim**, sem reescrever.
   - `GET /app` respondendo 500 com o texto de `_MSG_ILEGIVEL` (`certificates.py:33-36`) é estado de erro renderizado, não tela quebrada.
2. **Trust do certificado do servidor** por linha da tabela de Conexões: ação "Confiar certificado" (upload) e "Deixar de confiar" (`DELETE`, idempotente). O `ServerCertificateOut` devolve `fingerprint_sha256` do que foi de fato gravado (`connections.py:292-298`) — exibido para conferência contra o servidor.
3. **Primitivo de upload de arquivo — o primeiro do frontend.** Não existe hoje nenhum `type="file"`, `accept=` ou `multipart` em todo o `frontend/`. O endpoint aceita **corpo bruto** (`application/octet-stream`, `application/x-pem-file`, `application/pkix-cert`), não multipart (`connections.py:259-263`). Padrão fixado aqui e reusado pelo import (§6.1-6): `<input type="file">` oculto acionado por botão do design system → `File.arrayBuffer()` → `Blob` no corpo da requisição. **Sem `FormData`** — o único uso de `FormData` no repo é leitura de campos de formulário, e um upload de campo único não justifica parsing de formulário no servidor.
4. Teto de 64 KiB espelhado no cliente (`MAX_SERVER_CERT_BYTES`, `connections.py:42`) com mensagem pt-BR própria antes de enviar; o servidor continua sendo a barreira.

### 6.3 Pendência de segredo derivável (decisão A-4)

1. `ConnectionOut` já expõe `has_password: bool` e `server_cert_file: str | null` (`schemas/connections.py:20,65`) — a pendência é 100% derivável, **nenhum campo novo, nenhuma migration**:
   - falta senha ⇔ `auth_mode == "user_password" && !has_password`
   - falta certificado confiado ⇔ `security_policy != "none" && !server_cert_file`
2. Coluna **Pendências** na tabela de Conexões: lâmpada âmbar + ícone + rótulo curto (Regra do Canal Redundante), `title` com o efeito ("a conexão falhará em `cert_missing` até confiar no certificado do servidor"). Sem pendência, célula neutra — a Regra da Cor Anormal manda a tela em operação normal ficar sem cor saturada.
3. Resolver é o formulário/ação que já existe: modal de conexão para a senha, ação de trust para o certificado.
4. Efeito colateral pretendido: isso conserta um buraco anterior à F6 — uma conexão criada à mão sem certificado hoje fica muda até o worker falhar.

### 6.4 EU nas portas no editor (§4.1)

1. Modal de config do Script e do TFS ganha um campo de unidade por porta de saída (`OUT1..OUTn`; `y1`/`y2`), opcional, plaqueta como rótulo.
2. O canvas ao vivo exibe a unidade ao lado do valor da porta, no mesmo tratamento que os nós de OPC já dão à EU da tag (`features/flows/nodes/`) — mono tabular para o número, Texto Secundário menor para a unidade.

### 6.5 Faceplate de DV com barra (§4.2)

Com `range`, o faceplate de DV passa a ter barra vertical com escala demarcada, igual a MV/CV/Restrição (DESIGN §Shapes, convenção intocável). Sem `range`, permanece como a F5 entregou: plaqueta + valor mono tabular + EU. Somente leitura nos dois casos (RF-702).

### 6.6 Débitos de frontend da F5

| # | Débito | Correção |
|---|---|---|
| 1 | Família TTL (`mpc_arm_failed`, 60 s) só reavalia quando chega mensagem no canal — a condição pode ficar acesa indefinidamente numa tela silenciosa | Tique de 5 s no `CanalAoVivoProvider` reavaliando `resolverAlarmes`. `alarmes.ts` continua **pura** e sem parâmetro de período (spec F5 §7.2-3): quem tem relógio é o provider |
| 2 | Import circular `app/CanalAoVivo.tsx` ↔ `features/flows/useFlowStatus.ts` | Primitivos compartilhados extraídos para módulo neutro; verificado seguro hoje, mas é armadilha para o próximo editor |
| 3 | `AcaoPendencia.state` tipado como `MpcState`, forçando double-cast em `FaceplateVariavel` | Passa a `unknown`; o consumidor estreita |
| 4 | `EventsPage` usa `queryKey ["operate","mpcs"]` duplicada | Reusa o hook `useMpcs` (spec F5 §7.4-1), chave única |
| 5 | Paleta de 6 cores de pena para um teto de 8 penas no trend (spec F5 §7.4-6) | Paleta estendida a 8, dessaturada e distinguível, sem colidir com severidade nem com o Azul Único (DESIGN §Colors) |
| 6 | Contador `overruns` exibido sem EU no faceplate principal | Rótulo de unidade explícito (contagem), Regra do Número Tabular |

---

## 7. Suíte RNF-09 (decisão A-8)

1. **Marcador `rnf09`** novo em `pyproject.toml:29-32`, ao lado de `e2e` e `slow`; `addopts` continua excluindo `e2e`, então a suíte roda por seleção explícita. Os cenários RNF-09 são também `e2e` (dependem do compose): o marcador é recorte, não categoria nova de ambiente.
2. Os quatro itens do RNF-09, todos fechando a malha por `grafo_mpc_tfs` (`tests/e2e/conftest.py:612-683` — o único construtor que liga `opc_read(readback) → tfs(planta) → mpc`):

   | Item RNF-09 | Cenário | Mudança nesta fase |
   |---|---|---|
   | Bumpless | `E2E-F4-03` (`test_f4_mpc.py:309`) | só ganha o marcador — já usa `grafo_mpc_tfs` |
   | Precedência de restrição | `E2E-F4-05` (`test_f4_mpc.py:398`) | só ganha o marcador — já usa `grafo_mpc_tfs` |
   | Overrun | `E2E-F4-06` (`test_f4_failure.py:159`) | **reescrito**: `_grafo_overrun` (dummy `NODE_SINE`) → `grafo_mpc_tfs` com o mesmo config pesado |
   | Hot-swap | `E2E-F4-10` (`test_f4_ws.py:210`) | **reescrito**: `_grafo_hot_swap` (dummy) → `grafo_mpc_tfs` |

3. **Os ids são preservados.** `E2E-F4-06` e `E2E-F4-10` são aceite do PRD §8-F4; renumerá-los quebraria a rastreabilidade das fases anteriores. O que muda é a força da prova, não a identidade do cenário.
4. **A reescrita muda a dinâmica e a spec fixa o que se espera disso:** com a TFS na malha, a planta continua evoluindo enquanto a MV congela. No overrun, isso é a prova mais forte — a MV mantida passa a ser observável contra um processo que se move, e não contra uma senoide indiferente. Consequência prática: as tolerâncias e os timeouts foram calibrados para os grafos dummy (o docstring de `test_f4_failure.py:166` registra "solve consistente em ~13-17 s, ~40-50× o orçamento") e **precisam ser recalibrados**; o critério permanece o do RF-624 (MV inalterada + `mpc_overrun` + contador somando + nunca acumular fila), nunca um valor numérico novo inventado para fazer o teste passar.
5. **Não** entra nesta fase um nível de integração in-process ligando `mpc_node`+`tfs_node` via `harness_factory`, nem a promoção do `FakeClock` para `tests/testkit/` (hoje há duas implementações homônimas e incompatíveis, `test_scheduler.py:35-84` e `test_mpc_block.py:156-165`). Registrado como não-objetivo consciente: o valor seria velocidade de regressão, e o aceite pede prova, que o nível E2E dá.

---

## 8. Guia de implantação e comissionamento (decisão A-12; PRD §9-5)

`docs/IMPLANTACAO.md` — único entregável documental que o PRD manda produzir nesta fase ("documentar pré-requisitos de comissionamento por malha (guia de integração, F6)"). Público: o engenheiro de APC que implanta o OttimaSystem numa planta de cliente. Cada passo ancorado no RF/ADR que o governa.

1. **Instalação e primeiro boot** — pré-requisitos de host, `deploy/.env` a partir do `.env.example`, geração manual de `OTTIMA_SECRET_KEY` e `OTTIMA_FERNET_KEY` (`deploy/.env.example:18,21`), `docker compose up -d --build`, 7 serviços, admin do seed, verificação por `/api/health` e pela Home. Registra que a geração dos segredos é manual **por decisão** (§1.2), não por esquecimento.
2. **Identidade e confiança** — gerar o certificado de aplicação, exportar o `.der` para a trust list do servidor OPC, confiar no certificado do servidor pela UI, e o que cada modo de segurança exige (`none` / `Basic256Sha256 Sign` / `SignAndEncrypt`), incluindo a exigência de o `applicationUri` do certificado casar com `urn:ottima:opc-worker` (`ottima_core/certs.py:34`).
3. **Pré-requisitos do PID por malha** — o coração do §9-5. Por modo-alvo: **RCAS/CAS** exigem SP-tracking no PID; **ROUT** exige OUT-tracking. Tags obrigatórias por MV (escrita, comando de modo, readback) e a opcional (leitura de modo), os valores de `mode_values` (`auto` que devolve, `target` que assume), e a consequência de cada uma faltar. Explicita o que o OttimaSystem **não** faz: em LOCAL não escreve MV, no boot não reassume malha, em falha de comunicação cessa escrita e para o flow.
4. **Comissionamento passo a passo até AUTO** — projeto, conexão, tags, flow, blocos, `exec_order`, TSS e horizontes, deploy, LOCAL (tracking observado), REMOTO (assume, watchdog vivo), MAN, AUTO. Checklist de verificação por etapa, com o que olhar na tela de operação e em `/eventos`.
5. **Transporte de engenharia entre plantas** — export/import, o que o bundle não carrega e por quê (§2.3), e o procedimento de re-informar segredos no destino.
6. **Operação contínua e limites conhecidos** — retenção de 1 mês (ADR-003), backup do Postgres como procedimento manual (`pg_dump` do volume `pgdata`), não-objetivos da v1 (PRD §1) para o cliente não esperar o que não existe.

---

## 9. Testes e gate E2E

### 9.1 Unit/integração (padrões F1 §9 · F2 §11.1 · F3 §7.1 · F4 §9.1 · F5 §9.1)

- **ottima-core:** bundle round-trip puro (projeto → bundle → projeto, com ids diferentes) · tradução dos **seis** campos de `tag_ref` nos dois sentidos · **teste de completude da lista de campos**: a lista de tradução conferida contra `_CONFIG_KEYS` (`parse.py:19-25`) e contra os campos de `PidBinding` (`mpc_config.py:58-68`), para que um bloco novo com referência de tag esquecido vire vermelho (§2.2-3) · `output_eu`: chave fora dos handles de saída reprovada, `OUT{n}` além de `n_outputs` reprovada, config antigo sem o campo continua válido · `DvVar.range` opcional, `Range` reusado, config antigo válido.
- **api:** `/projects/{id}/export` (sem segredos, sem ids, `tag_ref` no lugar de `tag_id`, `Content-Disposition`, 404, RBAC admin) · export com `tag_ref` irresolvível ⇒ 422 (§2.2-4) · `/projects/import` (as 4 camadas, `detail` agregado com teto de 10 e sufixo, 409 de nome, 413 de teto, `schema_version` ≠ 1, `is_active` sempre false, `pending_secrets` derivado, evento `project_imported`, RBAC admin) · **nada gravado quando a camada 4 reprova** (transação) · `/api/health` com Redis fora ⇒ `degraded` e 200, com tudo de pé ⇒ `ok`.
- **flow-runtime (clock controlado):** payload de `mpc_overrun` com `overruns` · §5.2 — nos **três** caminhos, comando de outro flow não espera o build (latência medida): redeploy com host pesado, `_pass`/`_handback_failed_mpc` e `_force_stop` por `on_project_activated` · nenhum worker órfão após qualquer um deles (`stats()["alive"]` falso, processo juntado) · **`_teardown` continua esperando** as tasks destacadas, inclusive as dos caminhos novos (§5.2-3) — é a invariante da F5 §6.5 e o teste é o que impede a correção de reintroduzir o defeito.
- **frontend `test:unit`:** predicado de pendência de segredo (4 combinações de `auth_mode`×`has_password` e `security_policy`×`server_cert_file`) · tique de TTL (condição de 60 s cessa sem mensagem nova; `alarmes.ts` segue pura) · redutor/leitura do bundle na tela de import (nome pré-preenchido e editável, resumo de pendências, `detail` agregado renderizado inteiro) · `output_eu` na montagem dos nós do canvas · faceplate de DV com e sem `range` · paleta de 8 penas sem colisão com severidade nem com o azul de interação.

### 9.2 Gate E2E — 3 camadas (protocolo F2 §11.2 · F3 §7.2 · F4 §9.2 · F5 §9.2)

**L1** — `deploy/smoke.sh`: inalterado + `GET /api/health` expondo `redis_ok`/`db_ok` com `status: ok`.

**L2** — `tests/e2e`, cenários novos:

| Cenário | Prova |
|---|---|
| E2E-F6-01 | Export do projeto: bundle sem `auth_password_enc`, sem `server_cert_file`, sem ids nem timestamps; `tag_ref` objeto nos 6 campos; `schema_version: 1`; `Content-Disposition`; RBAC (operador ⇒ 403) |
| E2E-F6-02 | **ACEITE PRD §8-F6:** round-trip destrutivo — cria projeto completo (conexão segura + tags + flow MPC↔TFS) ⇒ exporta ⇒ `DELETE` do projeto (CASCADE) ⇒ importa ⇒ `pending_secrets` lista as duas pendências ⇒ re-informa senha e re-confia o certificado ⇒ ativa ⇒ deploya ⇒ flow roda e o MPC publica estado. Os ids das tags novas **são diferentes** dos exportados: se a tradução de `tag_ref` falhar, o grafo importado não valida e o cenário fica vermelho |
| E2E-F6-03 | Recusas do import: `schema_version: 2` ⇒ 422; `tag_ref` órfã ⇒ 422 com o `detail` agregado citando o flow; grafo com `exec_order` não contíguo ⇒ 422; nome duplicado ⇒ 409; corpo > 4 MiB ⇒ 413; operador ⇒ 403. **Banco inalterado após cada recusa** |
| E2E-F6-04 | `GET /api/health` da api degradando: com dependência fora responde 200 com `status: degraded` |

**Suíte RNF-09** (marcador `rnf09`, §7): `E2E-F4-03`, `E2E-F4-05`, `E2E-F4-06` (reescrito pela TFS), `E2E-F4-10` (reescrito pela TFS).

**Regressão:** os 41 cenários L2 F1-F5 verdes na mesma rodada; Playwright F1 serializado após a L2.

**L3** — roteiro browser `docs/plans/tests-e2e-f6.md` (**executado pelo controlador** — a tool `browser` é bloqueada a subagentes; herda a seção de armadilhas dos roteiros F4/F5):

| ID | Passo |
|---|---|
| B-F6-01 | `/engenharia/projetos`: criar, renomear, excluir; excluir o ativo é recusado com mensagem |
| B-F6-02 | Ativar outro projeto: confirmação com o efeito escrito; flows do anterior param; evento em `/eventos` |
| B-F6-03 | Chapa do certificado de aplicação: gerar, ver `subject`/`fingerprint`/validade/`application_uri`, baixar `.der`; regerar com confirmação exibe o aviso de re-trust |
| B-F6-04 | Confiar no certificado do servidor por conexão (upload do `.der`), conferir fingerprint; conexão sobe; deixar de confiar |
| B-F6-05 | Exportar projeto: arquivo baixa com o nome do slug; abrir e conferir `tag_ref` e ausência de segredos |
| B-F6-06 | Importar: nome pré-preenchido e editável, resumo de pendências, navegação para Conexões |
| B-F6-07 | Pendências em Conexões: lâmpada âmbar + ícone + rótulo; resolver senha e certificado; pendência some |
| B-F6-08 | Import recusado: `detail` agregado em pt-BR exibido inteiro; nada foi criado |
| B-F6-09 | EU nas portas de Script/TFS: declarar no modal, ver unidade ao lado do valor no canvas ao vivo |
| B-F6-10 | Faceplate de DV com `range`: barra vertical com escala; sem `range`: valor + EU sem barra |
| B-F6-11 | Faixa anunciadora: `mpc_arm_failed` cessa sozinho em 60 s numa tela parada (tique do provider) |
| B-F6-12 | Trend com 8 penas ligadas: cores distinguíveis, nenhuma colidindo com severidade ou com o azul de interação; `overruns` com unidade no faceplate principal |
| B-F6-13 | RBAC: operador não vê a chapa de certificados, não vê Projetos e não tem export/import |

### 9.3 Precondições de ambiente

Herdam o protocolo F3/F4/F5 (CLAUDE.md §Comandos): L2 e Playwright serializados; credenciais sempre inline; `down -v` só com autorização explícita + dump prévio; sempre os dois arquivos compose; nunca `prune`.

---

## 10. Débitos herdados — veredito

| # | Débito | Veredito F6 | Onde |
|---|---|---|---|
| — | UI de gestão de certificados (F2 §1.2) | **Fecha na F6** | §6.2 |
| — | Suíte completa RNF-09 (F4 §1.2, F5 §1.2) | **Fecha na F6** (os 4 itens pela TFS, marcador próprio) | §7 |
| — | EU nas portas de Script/TFS (F5 §1.2) | **Fecha na F6** | §4.1 |
| — | `shutdown_mpc` síncrono sob o lock (F5 §8) | **Fecha na F6** nos 3 caminhos reais; `_teardown` fica (esperar ali é correto) | §5.2 |
| — | Payload vazio de `mpc_overrun` | **Fecha na F6** | §5.1 |
| — | Tique de TTL, import circular, `AcaoPendencia.state`, `queryKey` duplicada, paleta de 6 penas, `overruns` sem EU | **Fecham na F6** | §6.6 |
| — | DV sem escala (backend não expunha faixa) | **Fecha na F6** (`DvVar.range`) | §4.2 |
| — | RF-101 sem superfície (desde a F1) | **Fecha na F6** | §6.1 |
| — | `opc.values.<conn_id>` no `/ws` | **Nunca** — encerra o registro aberto desde a F2 | §1.2 · §1.3-4 |
| — | `mpc_state_dimension` conservador | Fica (letra da spec F4 §2.2-7) | §1.2 |
| — | Protocolo `Commandable`/`Healthy` | Fica (2º bloco comandável) | §1.2 |
| — | Nível in-process MPC↔TFS + `FakeClock` canônico no testkit | Não-objetivo consciente da F6 | §7.5 |

---

## 11. Aderência ao aceite F6 (PRD §8)

| Critério | Evidência na spec |
|---|---|
| Export do projeto em JSON com `schema_version`, sem histórico e sem segredos (RF-102) | §2.1 · §2.3 · §3.1 · E2E-F6-01 · B-F6-05 |
| Import com validação de schema, criando projeto inativo (RF-103) | §3.2 (4 camadas, transação única) · E2E-F6-03 · B-F6-06/08 |
| **Projeto exportado importa limpo em instalação nova** | §2.2 (tradução de `tag_ref` — sem ela o aceite falha) · **E2E-F6-02**, cujo `DELETE` do projeto garante ids de destino diferentes dos de origem |
| **Re-informando segredos** | §2.3 · §3.2-7 (`pending_secrets`) · §6.3 (pendência derivável) · E2E-F6-02 · B-F6-07 |
| Gestão de certificados (RF-202) | §6.2 (backend F2 + UI nova + primitivo de upload) · B-F6-03/04 |
| Health/heartbeats (RNF-07) | §3.3 (`/api/health` deixa de mentir) · agregador e lâmpadas da F5 em regressão · L1 · E2E-F6-04 |
| **Suíte MPC↔TFS verde** (RNF-09) | §7 (os 4 itens pela TFS, marcador `rnf09`, overrun e hot-swap reescritos) |
| Guia de integração (PRD §9-5) | §8 |

---

## Anexo A — Decisões do brainstorm (2026-08-07)

| # | Lacuna | Decisão aprovada |
|---|---|---|
| A-1 | Perímetro da última fase: PRD §8 nomeia 4 entregas, mas há diferidos com destino "F6", 6 follow-ups da F5 e itens de hardening sem RF | **PRD §8 + guia (§9-5) + os 6 follow-ups da F5 + EU nas portas de Script/TFS.** `opc.values` no `/ws` vira **nunca**; backup/restore, correlação de log, limites de recurso e bootstrap de segredos ficam fora da v1 (§1.2) |
| A-2 | `graph_json` guarda `tag_id` inteiro em 6 campos e `Tag.id` é `Identity` — sem tradução, todo projeto importado nasce com grafo quebrado. O PRD §7.2 exporta tags por nome mas não diz nada sobre o grafo | **Reescrita na fronteira:** `tag_ref` no lugar de `tag_id` nos 6 campos, traduzido nos dois sentidos por lista explícita. Refinado para **objeto** `{connection, tag}` em vez de string `"conexao/tag"`: nomes são texto livre e podem conter `/` — a string exigiria regra de escape nova sobre dados existentes. Emenda PRD §7.2 → v1.4 |
| A-3 | O `.der` do servidor confiado não é segredo, mas é ambiente-específico; ADR-012 só proíbe segredos e histórico | **Fora do bundle**, re-confiar no destino. Levar o certificado do servidor antigo para outra planta instala um pinning errado (`cert_mismatch`), pior que ausente (`cert_missing`) |
| A-4 | O aceite exige "re-informando segredos" mas nada sinaliza a pendência | **Pendência derivável** de `has_password`/`server_cert_file` (nenhum campo novo), visível na página de Conexões com lâmpada + ícone + rótulo; o import devolve `pending_secrets` no resumo. Conserta de lambuja um buraco anterior à F6 |
| A-5 | Um bundle pode ter N problemas simultâneos e toda a API responde erro como string única | **Valida as 4 camadas até o fim, aborta a transação e devolve 422 com `detail` string única agregando até 10 problemas.** Contrato de erro da API intacto; a varredura completa custa o mesmo que parar no primeiro |
| A-6 | `Project.name` é UNIQUE global e o caso de uso mais provável é reimportar o mesmo projeto | **Nome editável no import** (campo opcional que sobrescreve o do bundle); ainda colidindo ⇒ **409**, mesma mensagem de `create_project`. Sem sufixo automático: num sistema de 1 projeto ativo, "Planta X (2)" é convite a ativar o errado |
| A-7 | O certificado de aplicação é de INSTALAÇÃO e não tem casa na navegação | **Chapa "Certificado da aplicação (instalação)" no topo da página de Conexões**, só para admin. Sem rota nova: comissionar uma conexão segura exige os dois certificados na mesma sessão. Upload por `<input type="file">` oculto → `Blob` em corpo bruto (o endpoint não é multipart) — primeiro padrão de upload do frontend |
| A-8 | RNF-09 pede malha fechada MPC↔TFS nos 4 itens; overrun e hot-swap usam grafo dummy por decisão documentada da F4b | **Suíte nomeada no nível E2E:** overrun e hot-swap reescritos para `grafo_mpc_tfs` (ids preservados), os 4 sob marcador `rnf09`. Nível in-process e `FakeClock` canônico ficam fora, registrados como não-objetivo |
| A-9 | Como provar "importa limpo em instalação nova" sem violar a proibição de `up`/`down` na suíte | **Round-trip destrutivo do projeto, não do banco:** export ⇒ `DELETE` do projeto ⇒ import ⇒ re-informa segredos ⇒ ativa ⇒ deploya ⇒ roda. A sequence do `Identity` já avançou, então os ids de destino são necessariamente diferentes — é exatamente o modo de falha que importa |
| A-10 | Portas de saída de Script/TFS não têm onde declarar unidade; DESIGN manda todo valor ter EU | **`output_eu: dict[str, str]` por bloco**, chave = handle de saída (`OUT1..OUTn`, `y1`/`y2`), opcional, sem migration. Sem propagação automática pela aresta: o Script converte grandeza, e unidade errada é pior que ausente |
| A-11 | `DvVar` não tem faixa, então o faceplate de DV ficou sem barra — contra RF-702 e DESIGN §Shapes | **`range: Range \| None` opcional na `DvVar`**, reusando o tipo de `ConstraintVar`; projetado por `/api/operate/mpcs`, editável na aba Variáveis. Sem faixa, faceplate sem barra |
| A-12 | PRD §9-5 manda produzir "guia de integração" na F6 e não existe nenhum documento de implantação | **`docs/IMPLANTACAO.md` único**, cobrindo instalação → certificados → **pré-requisitos do PID por malha** → comissionamento até AUTO → transporte por export/import → limites conhecidos |
| A-13 | RF-101 tem backend desde a F1 e nenhuma UI; export/import não teria onde morar e o projeto importado (inativo) seria inativável pela UI | **Página `/engenharia/projetos` completa:** CRUD + ativar (com confirmação do efeito) + exportar por linha + importar no cabeçalho. Reusa byte a byte os padrões de `ConnectionsPage`/`FlowsPage` |
