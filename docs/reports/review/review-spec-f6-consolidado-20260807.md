# Revisão da spec F6 — consolidado

**Spec:** `docs/specs/F6-portabilidade-hardening.md` @ `da25cd6`
**Data:** 2026-08-07 · **Revisores:** 7 agentes em paralelo, um por facet
**Veredito consolidado:** **REQUEST CHANGES**
**Achados brutos:** 74 (15 Critical, 37 Important, 22 Minor) · **após deduplicação:** 68 (13 Critical, 34 Important, 21 Minor)

| Facet | Agente | Veredito | C / I / m | Relatório |
|---|---|---|---|---|
| Coerência normativa, escopo, aceite | `rfc` | REQUEST CHANGES | 4 / 6 / 6 | `review-spec-f6-normativa-20260807.md` |
| Verificação factual de 75 âncoras | `scout` | REQUEST CHANGES | 1 / 4 / 8 | `review-spec-f6-fatos-20260807.md` |
| Contratos de API, validação, transação | `fastapi-reviewer` | REQUEST CHANGES | 3 / 4 / 3 | `review-spec-f6-api-20260807.md` |
| Implementabilidade no frontend | `react-reviewer` | REQUEST CHANGES | 4 / 3 / 1 | `review-spec-f6-frontend-20260807.md` |
| Conformidade DESIGN/PRODUCT e IA | `ux-designer` | APPROVE WITH CHANGES | 0 / 10 / 2 | `review-spec-f6-ux-20260807.md` |
| O plano de testes prova o que promete | `pr-test-analyzer` | REQUEST CHANGES | 3 / 4 / 2 | `review-spec-f6-testes-20260807.md` |
| Superfície de segurança | `security-reviewer` | APPROVE WITH CHANGES | 0 / 6 / 0 | `review-spec-f6-seguranca-20260807.md` |

---

## Bloco 1 — Exige decisão do dono do produto (CLAUDE.md item 4)

Quatro achados não podem ser resolvidos por reescrita da spec: tocam decisão aprovada do Anexo A, contrato do PRD ou premissa de ADR.

### F6R-01 — A decisão A-8 está tecnicamente bloqueada [Critical]
**Origem:** TST-02, TST-03 · **Seção:** §7.2, §7.4 · **Ameaça:** aceite "suíte MPC↔TFS verde"

A-8 mandou reescrever `E2E-F4-06` (overrun) e `E2E-F4-10` (hot-swap) para `grafo_mpc_tfs`. Ambas as reescritas são inviáveis como especificadas:

- **Overrun:** `grafo_mpc_tfs` não aceita config externo — é hardcoded para `_config_mpc_malha` (2 MVs / 1 CV), e o bloco TFS é travado em exatamente 2×2 por regra de parse (`parse.py:326-327`). O config pesado que garante o overrun tem 6 CVs (`test_f4_failure.py:44-45`) e **não cabe** na malha TFS.
- **Hot-swap:** o cenário atual prova "hot-swap troca só quem mudou" usando DOIS blocos MPC — `mpc2` é o irmão de controle (`test_f4_ws.py:4-6,156-158,301-310`). `grafo_mpc_tfs` produz um único nó `mpc`; a reescrita **destrói a prova**, não a fortalece.

**Opções:** (a) generalizar `grafo_mpc_tfs` para aceitar config e nº de blocos, e relaxar o teto 2×2 do TFS — mexe em regra de parse validada, custo alto; (b) cobrir overrun/hot-swap por malha TFS num MPC pequeno e manter o config pesado num cenário separado sem TFS, aceitando que "malha fechada" vale para a dinâmica, não para o estresse do solver; (c) reverter A-8 para o veredito "consolidar sem reescrever" que foi descartado no brainstorm.

### F6R-02 — §3.1-3 amplia RF-102 sem emenda, e o aceite depende da ampliação [Critical]
**Origem:** RFC-03 · **Seção:** §3.1-3, §9.2 (E2E-F6-02)

RF-102 (`PRD.md:82`) diz "Export do **projeto ativo**". A spec exporta qualquer projeto por id, sem `[NOVA]` e sem linha em §1.3. Pela precedência declarada, o PRD vence. E o aceite **depende** da ampliação: E2E-F6-02 faz `DELETE` do projeto exportado, o backend recusa excluir o ativo (`projects.py:70-72`) e não existe endpoint de desativar. Sob a letra do RF-102, o único cenário que prova o aceite é inexecutável.

**Decisão necessária:** emendar RF-102 (export de qualquer projeto) ou redesenhar E2E-F6-02.

### F6R-03 — Import quebra a premissa de confiança do ADR-018 [Critical → reclassificado de SEC-01 Important]
**Origem:** SEC-01, SEC-03 · **Seção:** §3.2 camada 4, ADR-018

ADR-018 aceita `exec()` sem sandbox pesado porque autor do script = implantador do script. O import de bundle externo quebra essa premissa: nenhuma das 4 camadas inspeciona `graph_json.code`. Agravantes verificados: `script_pool.py` injeta `numpy`/`math` como módulos completos (só builtins fechados, sem defesa contra fuga por `__class__/__subclasses__`), e `docker-compose.yml` usa `env_file:[.env]` no `flow-runtime`, expondo `OTTIMA_SECRET_KEY`/`OTTIMA_FERNET_KEY` ao processo que roda o script importado.

**Decisão necessária:** aceitar e documentar no guia (§8) como risco conhecido de operação; exigir revisão explícita do código Script na tela de import; ou ADR novo sobre confiança de bundle.

### F6R-04 — A exclusão do campo `service` dos logs se apoia em premissa falsa [Important]
**Origem:** FACT-11, RFC-12 · **Seção:** §1.2

A §1.2 justifica deixar `service` fora da v1 dizendo que o JSON de `logging.py` "já cumpre" RNF-07 ("logs estruturados **por serviço**"). Falso: `JsonFormatter.format()` emite `{ts, level, logger, message}` — sem chave `service`; `record.name` é o caminho do logger Python. A distinção por serviço hoje só existe no prefixo de container do `docker compose logs`.

**Decisão necessária:** RNF-07 está descoberto neste eixo. Manter fora (com justificativa honesta) ou trazer para a fase (é ~3 linhas em `logging.py`).

---

## Bloco 2 — Critical resolvíveis por reescrita da spec

### F6R-05 — A camada 2 reprova o próprio bundle normativo da spec [Critical]
**Origem:** RFC-01, API-01, API-02, SEC-02 · **Seção:** §2.1-1, §2.1-2, §3.2-4

Cluster de quatro defeitos no reuso de `ConnectionCreate`:
1. `_coerencia` (`schemas/connections.py:37-38`) levanta 422 quando `auth_mode == "user_password"` sem `auth_password`. O bundle nunca carrega senha (§2.3) — e o exemplo normativo de §2.1-2 é exatamente esse caso. **O bundle da própria spec não é importável pela regra da própria spec.**
2. `ConnectionCreate.project_id`, `TagCreate.connection_id`, `FlowCreate.project_id` são obrigatórios e ausentes do bundle: reuso literal é impossível.
3. Sentido inverso: `_ConnectionFields` **não tem `extra="forbid"`**, e aceita `auth_password` e `server_cert_file`. Um bundle com senha em claro seria consumido em silêncio.
4. `server_cert_file` vazado cria pinning pendurado que o predicado de pendência de §6.3 **não acusa** — esconde conexão quebrada.

**Correção:** schemas de bundle próprios (`extra="forbid"`, sem ids, sem segredos) reusando as checagens extraídas, com a regra do par trocada por "`user_password` exige `auth_username`". Contraprova de que o estado sem senha é legítimo: o PATCH só valida policy×mode e watchdog (`routers/connections.py:210-215`).

### F6R-06 — §5.2-2 omite `detach_hosts`; risco de escrita indevida em planta [Critical]
**Origem:** FACT-03 · **Seção:** §5.2-2

A spec atribui a `stop_host_background` (`supervisor_mpc.py:359`) a ação de "remove o host do mapa". Falso: quem remove é `detach_hosts` (`supervisor_mpc.py:347`); o docstring de `stop_host_background` diz que o host já saiu do mapa antes da task nascer. Implementado ao pé da letra, o host morto fica alcançável em `runtime.hosts` por até `_BOOT_TIMEOUT_S=30 s`, permitindo comando concorrente sobre worker em morte — viola a invariante "nunca dois workers escrevendo na mesma malha" que a própria §5.2-2 declara normativa.

**Correção:** três passos — `revert_armed_mpc` → `detach_hosts` (síncrono, sob o lock) → `stop_host_background`. Padrão já usado em `supervisor.py:352-353`.

### F6R-07 — E2E-F6-04 é inexecutável e contradiz a §1.2 da própria spec [Critical]
**Origem:** RFC-02 · **Seção:** §9.2, §1.2, §11

§1.2 põe fora da v1 o cenário que derruba `redis`/`timescaledb`; §9.2 lista E2E-F6-04 fazendo exatamente isso; `tests/e2e/conftest.py:4-6` proíbe `down`. A prova equivalente já existe em §9.1 (unit).
**Correção:** remover E2E-F6-04 e trocar a evidência da linha RNF-07 em §11 por §9.1.

### F6R-08 — Mudança de payload de `mpc_overrun` quebra teste existente [Critical]
**Origem:** TST-08 · **Seção:** §5.1 vs §9.2 "regressão"

§5.1 muda `payload={}` para `{"overruns": n}`. Isso quebra com certeza mecânica a asserção em `tests/e2e/test_f4_failure.py:226`. A spec promete "41 cenários F1-F5 verdes na mesma rodada" sem referência cruzada — regressão garantida entre duas tarefas da mesma fase.
**Correção:** §5.1 passa a citar o teste a atualizar; a linha de regressão de §9.2 vira "41 verdes, com `test_f4_failure.py:226` atualizado por §5.1".

### F6R-09 — `output_eu` não tem onde morar no modelo do frontend [Critical]
**Origem:** FE-01 · **Seção:** §4.1-2

A spec diz "no `config` de script/tfs", mas o modelo de nó do frontend (`graph.ts`, `DadosScript`/`DadosTfs`) é plano, sem objeto `config` aninhado, e o backend recusa chave desconhecida em `data` com 422 (`parse.py:19-25,252-255`). Seguido ao pé da letra, a tarefa não compila nem persiste.
**Correção:** §4.1 precisa dizer onde o campo mora nos DOIS lados (config Pydantic no backend, `Dados*` no frontend) e que `_CONFIG_KEYS` ganha a chave.

### F6R-10 — Helper `api()` não suporta download autenticado nem upload binário [Critical]
**Origem:** FE-03, FE-04 · **Seção:** §6.1-5, §6.1-6, §6.2-3

`api.ts:49` sobrescreve `Content-Type` para JSON sempre que há body, e o helper nunca expõe `res.blob()` nem headers de resposta. Com JWT em header, `<a href>` simples não autentica. Nenhum dos três fluxos novos (baixar bundle, baixar `.der`, subir `.der`) funciona sem alterar o helper — a spec não menciona essa alteração. Ainda: o import lê arquivo como **texto + JSON.parse**, não bytes brutos, então o primitivo de §6.2-3 não serve aos dois casos sem bifurcação.
**Correção:** §6.2-3 passa a especificar a mudança em `api.ts` e dois primitivos distintos (binário e texto).

### F6R-11 — Nenhuma invalidação de `queryKey` especificada [Critical]
**Origem:** FE-05 · **Seção:** §6.1

Import cria projeto + conexões + tags + flows; Ativar troca o projeto ativo. `useActiveProject` usa `["projects"]` sem chave exportada nem invalidação. Sem especificar, reintroduz o bug das telas presas que a §1-3 cita como motivação da fase.
**Correção:** §6.1 lista as chaves a invalidar em cada ação.

### F6R-12 — `desired_state` fora de todo schema `Create` vira 500 [Critical]
**Origem:** API-03 · **Seção:** §2.1-4, §3.2-4

`Flow.desired_state` é exportado verbatim mas não existe em `FlowCreate`/`FlowUpdate` (`schemas/flows.py:17-20`); só o CHECK `ck_flows_desired_state` protege. Valor malformado escapa das 4 camadas e vira `IntegrityError` não tratado no `flush()` — 500, não o 422 agregado.
**Correção:** o schema de bundle do flow declara `desired_state: Literal["running","stopped"]`.

### F6R-13 — §3.3 define o formato do `/health` mas não o mecanismo [Critical]
**Origem:** API-04 · **Seção:** §3.3

Os outros três serviços rodam `_heartbeat_loop` em background e o handler só faz `getattr` — zero I/O por request. A spec só define o JSON. Checagem síncrona sem timeout numa rota pública que é o healthcheck do compose é risco real.
**Correção:** §3.3 passa a exigir o mesmo mecanismo de heartbeat em background.

### F6R-14 — Modelo de pendências cego ao certificado de aplicação [Critical]
**Origem:** RFC-04 · **Seção:** §3.2-7, §6.3-1

`auth_mode: certificate` reusa o par do certificado de aplicação (`opc-worker/security.py:167-176`), que na instalação nova não existe. Conexão importada com `auth_mode: certificate` e `security_policy: none` gera `pending_secrets` vazio e coluna neutra — falha em `cert_missing` sem aviso. Torna falso o `title` prescrito em §6.3-2.
**Correção:** terceira pendência `needs_app_certificate ⇔ (security_policy != none || auth_mode == certificate) && !appCert.exists`, com dado já disponível em `AppCertificateOut.exists`; conexão `certificate` entra no projeto de E2E-F6-01/02.

---

## Bloco 3 — Important (34)

**Normativa:** RFC-05 emenda §7.2 incompleta (`ts`→`ts_seconds`, `"R"`→`"r"`, `auth_mode`/`auth_username`, cabeçalho do PRD ainda diz "F1 e F2 concluídas") · RFC-06 `opc.values` vira "nunca" sem emendar `PRD.md:172,192` · RFC-07 a emenda §1.3-6 descreve trecho que a F5 §8 não contém (nunca diz "quatro", nunca cita `_teardown`) · RFC-08 duas linhas de §11 citam evidência que não prova o critério · RFC-09 os 3 planos não têm mapa de seções (§4, §5, §6.6 sem dono) · RFC-10 §7.4 exige recalibração sem critério de saída nem contingência.

**Fatos:** FACT-01 são três telas, não quatro (`OperateSelectorPage:48` diz outra coisa e exige lógica nova) · FACT-02 `flows.py:55` é "Flow não encontrado", constante errada · FACT-10 `flow-runtime` soma `runtime_up`, não só `redis_ok and db_ok`.

**API:** API-02 ids de pai obrigatórios sem mecanismo de placeholder · API-05 `TagConfig`/`PidBinding` são `extra=forbid` com `tag_id: int`, não aceitam `tag_ref`; §2.2-5 e §3.2-4 se contradizem na ordem · API-06 teto de 4 MiB não aplicável a body Pydantic tipado · API-07 `pending_secrets` (§3.2-7) e pendência (§6.3-1) são fórmulas diferentes.

**Frontend:** FE-02 campo de EU por porta exige `n_outputs` controlado, e `ModalConfigBloco` é deliberadamente não-controlado · FE-06 tique de 5 s no contexto único re-renderiza a tela de operação inteira (uPlot incluso) · FE-08 "reusa byte a byte" superestima: não há componente de tabela compartilhado, e Ativar/Exportar/Importar não têm análogo.

**UX:** UX-01 âmbar de pendência colide com a Regra da Cor Anormal justo no cenário de aceite (toda conexão importada acende) · UX-02 `application_uri` como plaqueta contradiz o tratamento mono de `node_id` · UX-03 certificado ilegível e aviso de re-trust sem canal redundante · UX-04 certificado de instalação em página de projeto sem mitigação de escopo · UX-05 import sem prévia antes de criar · UX-06 **`node_id` contém `;` legitimamente — o separador do 422 agregado é ambíguo** · UX-07 "Ativar" com peso de UI igual a ações muito menores · UX-08 "bundle" fora do GLOSSARY vazando para a API · UX-09 estado "zero projetos" não especificado · UX-10 cor da lâmpada "Ativo" não especificada (verde violaria a reserva de Verde Rodando).

**Testes:** TST-01 nenhum cenário testa duas conexões com tag homônima — o caso que motivou `tag_ref` ser objeto · TST-04 nome duplicado dentro do próprio bundle nunca testado · TST-05 falta import com `pid` parcialmente preenchido (chave `_ref` ausente) · TST-06 mecanismo do teste de completude dos 6 campos não especificado (proposta: `TAG_REF_FIELDS` × `_CONFIG_KEYS` + `PidBinding.model_fields`).

**Segurança:** SEC-02 `server_cert_file` excluído por motivo fora do vocabulário de §2.1-1 · SEC-04 import sem teto de contagem; camada 4 síncrona bloqueia o único worker uvicorn que também serve `/ws` — a IHM de operação congela durante o import · SEC-05 export não audita, apesar de §3.1-1 justificar o RBAC pela sensibilidade da topologia · SEC-06 regenerar certificado pode quebrar conexões de projetos não visíveis, sem lista de impactados.

---

## Bloco 4 — Minor (21)

**Âncoras a corrigir (FACT-04..09, 12, 13):** `projects.py:77-112` · `opc-worker/main.py:108-128` · `docker-compose.yml:46-51` · `models/tag.py:30` (eu) · `models/tag.py:34` (UniqueConstraint) · `.env.example:18,22` · `conftest.py:4-6` · "constante única" de `projects.py` é literal duplicado, não símbolo.

**Normativa (RFC-11..16):** três âncoras erradas (já cobertas acima) · RFC-13 §3.2-7 ≠ §6.3-1 · RFC-14 GLOSSARY não emendado para "bundle"/"pendência" · RFC-15 `/api/health` público amplia corpo não autenticado sem registrar a exceção a RF-003 · RFC-16 RF-702 segue descoberto para DV sem `range`, sem sinalização na aba Variáveis.

**API (API-08..10):** `KIND_PROJECT_IMPORTED` não registrado em `bus.py` · dois formatos concorrentes de agregação de erro · `GET /export` com `Response` cru gera tipo OpenAPI enganoso (não quebra o `generate:api`, confirmado).

**Frontend/UX/Testes:** FE-07 ciclo de import é exatamente um, correção não nomeia módulo destino · UX-11/12 · TST-07 comando do marcador `rnf09` não registrado (`-m rnf09` sobrescreve `addopts`, verificado) · TST-09 idempotência de E2E-F6-02/03 depende de convenção `RUN_ID` não citada.

---

## Verificações positivas relevantes (não re-revisar)

- **Falso-verde do E2E-F6-02: DESCARTADO com cadeia de evidência completa** (TST). `Identity(always=True)` nos três models, CASCADE real, sequences Postgres não revertem por DELETE, nenhum `RESTART IDENTITY` em `tests/e2e`, banco persistente por volume nomeado, e a camada 4 resolve `tag_id` contra o mapa do próprio projeto. A decisão A-9 está certa — a spec só não cita nenhuma dessas evidências.
- Os seis campos de `tag_ref` são exatamente seis: varredura completa não achou sétimo (FACT).
- A tabela dos três caminhos de §5.2-1 é 100% exata em todas as âncoras (FACT); o defeito da seção é conceitual, não de anchor.
- `flush()` com `BigInteger Identity` funciona (SQLAlchemy 2.0 async + asyncpg, RETURNING); `project_tags()` vê linhas flushed-não-commitadas (API).
- `AcaoPendencia.state → unknown` é seguro e completo; `resolverAlarmes` já recebe `agora` (FE).
- `_to_out` já usa projeção manual campo-a-campo — precedente forte para o bundle (SEC).
- Export por id com `require_admin` não é IDOR; `/api/health` público não é achado sob o modelo de ameaça do ADR-023 (SEC).
- §2.1-4 (`desired_state` verbatim) não cria caminho de escrita em planta: `_pass` nunca inicia flow, `on_project_activated` só para (RFC).
- Bootstrap de segredos do `.env` fora da v1 **não** é pré-requisito do aceite — os segredos do aceite são os da conexão OPC (RFC).
