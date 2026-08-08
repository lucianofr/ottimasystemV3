# Plano F6a — Portabilidade & dados

> **Para executores agênticos:** execução tarefa a tarefa com subagente por tarefa + revisão independente (padrão F3/F4/F5, skill subagent-driven-development; ledger em `.superpowers/sdd/F6a-portabilidade-dados/progress.md`). Checkboxes das tabelas rastreiam conclusão. Cada tarefa cita a seção da spec, a decisão A-n e o achado F6R-n que implementa.

**Fase:** F6 (PRD §8) — **última fase da v1** · plano 1 de 3 (decisão A-1; mapa §12 da spec) · 2026-08-07
**Executa:** `docs/specs/F6-portabilidade-hardening.md` §1.3 (Etapa 0), §2, §3, §4.1 (backend), §4.2 (schema + projeção), §5 e a fatia backend de §9.1 — as superfícies (§6, §4.1 frontend, §4.2 faceplate) são do F6b; a suíte RNF-09, os cenários E2E-F6 e o guia são do F6c
**Fontes normativas:** `docs/PRD.md` v1.3→v1.4 · `docs/adr/ADR-001…024` (prevalecem em conflito) · `docs/GLOSSARY.md` · specs F1/F2/F3/F4/F5 (com as notas de remissão da Etapa 0) · spec F6
**Objetivo:** arquivo de projeto (bundle) exportável e importável ponta a ponta — `tag_ref` traduzida nos dois sentidos, 4 camadas de validação em transação única, `pending_secrets` com os 3 predicados; `/api/health` refletindo Redis/Postgres por heartbeat de fundo; `service` no log dos 4 serviços; `env_file` do flow-runtime restrito; `output_eu` e `DvVar.range` no schema; os 2 débitos de runtime da F5 fechados. Entrega `frontend/openapi.json` e `frontend/src/lib/contracts.gen.ts` regenerados — é o que o F6b consome.
**Stack:** NENHUMA dependência nova (`json`/`re`/`datetime` da stdlib; Pydantic v2 e SQLAlchemy já presentes).

## Regras globais (valem para todas as tarefas)

1. **Governança:** ADR > PRD > spec > plano. Worktree único da fase `ottimaSystemV3-f6`, branch `f6-portabilidade` (os três planos na mesma branch); Conventional Commits pt-BR; identificadores em inglês no backend, strings pt-BR, sem emojis; teto 800 linhas/arquivo (típico 200-400).
2. **Ciclo de conclusão de etapa:** bateria da etapa **toda verde** (`uv run pytest` + `uv run ruff check . && uv run ruff format --check .`). Vermelho ⇒ corrigir ⇒ re-executar ⇒ repetir até verde.
3. **TDD estrito com prova RED** registrada no ledger em toda lógica nova (CLAUDE.md §Testes): teste vermelho antes da implementação, verde depois, refactor com suíte verde.
4. **Caminho absoluto em toda edição de subagente** (armadilha nº1 dos ledgers F3/F5: `edit`/`write` resolvem caminho relativo contra o cwd do processo, não contra o worktree). Confirmar cada gravação por `grep` no arquivo antes de commitar, e `git status` no worktree antes de todo commit.
5. **Lacuna real de spec/schema ⇒ PARAR e perguntar** (CLAUDE.md item 4); nunca inventar contrato.
6. **Credenciais/env sempre inline de `deploy/.env`** — nunca `export` persistente (`OTTIMA_DATABASE_URL` exportada quebra os testcontainers da suíte unitária).
7. **Nenhuma tarefa deste plano toca `frontend/src`** além dos dois arquivos gerados da tarefa 6.1 — superfície é F6b.
8. **DoD do plano:** §Aderência ao final; o aceite da FASE fecha só no F6c (gate + roteiro `docs/plans/tests-e2e-f6.md`).

## Contratos verbatim (spec F6 §2.1-4 — forma normativa do arquivo de projeto)

```json
{"schema_version": 1, "exported_at": "2026-08-07T21:40:00Z",
 "project": {"name": "Planta C-101", "description": "Coluna debutanizadora"},
 "connections": [{"name": "gateway-1", "endpoint": "opc.tcp://10.0.0.5:4840",
   "security_policy": "basic256sha256", "security_mode": "sign_and_encrypt",
   "auth_mode": "user_password", "auth_username": "ottima",
   "watchdog_read_node_id": "ns=2;s=WD_R", "watchdog_write_node_id": "ns=2;s=WD_W",
   "watchdog_period_ms": 1500}],
 "tags": [{"connection": "gateway-1", "name": "TT-101", "node_id": "ns=2;s=TT101",
   "direction": "r", "data_type": "float", "eu": "C", "description": "Temperatura de topo"}],
 "flows": [{"name": "Coluna C-101", "ts_seconds": 1.0, "desired_state": "stopped",
   "graph": {"nodes": [], "edges": []}}]}
```

Fora da fronteira (§2.3, **nenhum destes campos existe em schema de bundle**): `auth_password_enc`, `server_cert_file`, `id`/`project_id`/`connection_id`, `is_active`, `created_at`/`updated_at`, `User`, `samples`/`events`/`mpc_samples`.

Referência de tag (§2.2-2): **objeto** `{"connection": "gateway-1", "tag": "TT-101"}` — nunca a string `"conexao/tag"` (nomes são texto livre e podem conter `/`).

Separador do 422 agregado (§3.2-5): **` | `**, nunca `;` — `node_id` de OPC-UA contém `;` legitimamente (`ns=2;s=TT101`).

## Interfaces produzidas (consumidas pelo F6b/F6c e entre tarefas — assinaturas exatas)

```python
# ottima_core.portability.schemas (tarefa 1.1) — todos com model_config = ConfigDict(extra="forbid")
SCHEMA_VERSION: Final[int] = 1
class BundleTagRef(BaseModel):     connection: str; tag: str
class BundleProject(BaseModel):    name: str; description: str = ""
class BundleConnection(BaseModel): name: str; endpoint: str; security_policy: SecurityPolicy = "none"
    security_mode: SecurityMode = "none"; auth_mode: AuthMode = "anonymous"
    auth_username: str | None = None; watchdog_read_node_id: str | None = None
    watchdog_write_node_id: str | None = None; watchdog_period_ms: int = 1500
class BundleTag(BaseModel):        connection: str; name: str; node_id: str; direction: Direction
    data_type: DataType; eu: str = ""; description: str = ""
class BundleFlow(BaseModel):       name: str; ts_seconds: TsSeconds
    desired_state: DesiredState = "stopped"; graph: dict
class ProjectBundle(BaseModel):    schema_version: Literal[1]; exported_at: datetime
    project: BundleProject; connections: list[BundleConnection]; tags: list[BundleTag]
    flows: list[BundleFlow]

# ottima_core.portability.tag_ref (tarefa 1.2)
@dataclass(frozen=True, slots=True)
class CampoTagRef: id_key: str; ref_key: str; obrigatorio: bool
CAMPOS_NO_DATA: tuple[CampoTagRef, ...]   # ("tag_id", "tag_ref", True) — vale opc_read E opc_write
CAMPOS_NO_PID: tuple[CampoTagRef, ...]    # write/mode_cmd/mode_read(opcional)/readback
TAG_REF_FIELDS = CAMPOS_NO_DATA + CAMPOS_NO_PID   # 5 nomes cobrindo os 6 lugares de §2.2-1
class ReferenciaTagInvalida(ValueError): problemas: list[str]
def grafo_para_bundle(graph: dict, ref_por_id: Mapping[int, tuple[str, str]]) -> dict
def grafo_para_banco(graph: dict, id_por_ref: Mapping[tuple[str, str], int]) -> dict
def problemas_de_tag_ref(graph: dict, *, onde: str, refs: Container[tuple[str, str]]) -> list[str]

# ottima_core.portability.bundle (tarefa 1.3)
def montar_bundle(*, project: Project, connections: Sequence[Connection], tags: Sequence[Tag],
                  flows: Sequence[Flow], exported_at: datetime) -> ProjectBundle
def problemas_de_coerencia_interna(bundle: ProjectBundle) -> list[str]     # camada 3
def ref_por_id(connections: Sequence[Connection], tags: Sequence[Tag]) -> dict[int, tuple[str, str]]

# ottima_core.portability.pendencias (tarefa 2.1) — os 3 predicados, um lugar de verdade (§3.2-8)
def pendencias_da_conexao(*, connection_name: str, auth_mode: str, has_password: bool,
                          security_policy: str, server_cert_file: str | None,
                          app_cert_exists: bool) -> PendingSecretOut

# ottima_core.schemas.projects (tarefa 2.1)
class PendingSecretOut(BaseModel): connection_name: str; needs_password: bool
    needs_server_certificate: bool; needs_app_certificate: bool
class ProjectImportIn(BaseModel):  name: str | None = None; bundle: dict
class ProjectImportOut(BaseModel): project: ProjectOut; pending_secrets: list[PendingSecretOut]

# ottima_core.schemas.connections (tarefa 1.1) — regras de coerência extraídas, puras
def erro_policy_mode(security_policy: str, security_mode: str) -> str | None
def erro_watchdog(read_node_id: str | None, write_node_id: str | None) -> str | None
def erro_auth_username(auth_mode: str, auth_username: str | None) -> str | None

# ottima_core.bus (tarefas 2.2 e 2.3)
KIND_PROJECT_EXPORTED = "project_exported"   # severity "info"
KIND_PROJECT_IMPORTED = "project_imported"   # severity "info"

# ottima_api.validacao (tarefas 0.5 e 2.1)
def traduzir_erro_de_validacao(erro: dict[str, Any]) -> str          # movida de app.py:42
def problemas_de_validacao(exc: ValidationError, *, prefixo: str = "") -> list[str]
def formatar_problemas(problemas: Sequence[str], *, cabecalho: str) -> str
# ^ "<cabecalho> (N problemas) | p1 | p2 | … | e mais N" — cabecalho "Import recusado" (§3.2-5)
#   ou "Export recusado" (§2.2-5); o texto do import é normativo, o do export não

# REST novo (OpenAPI regenerado na tarefa 6.1 — o F6b consome via npm run generate:api)
GET  /api/projects/{project_id}/export   # §3.1; require_admin; Content-Disposition attachment
POST /api/projects/import                # §3.2; require_admin; 201 ProjectImportOut
GET  /api/health                         # §3.3; público; + redis_ok/db_ok, sempre 200

# ottima_core.logging (tarefa 3.1)
def setup_logging(level: str = "INFO", service: str = "unknown") -> None   # grava "service" no JSON
```

---

## Etapa 0 — Emendas documentais e constantes (spec §1.3; antes de qualquer código de feature)

| # | Tarefa | Arquivos | Verificar | Gov. |
|---|---|---|---|---|
| 0.1 | **Emenda PRD → v1.4** (§1.3-1/2/7, três emendas no mesmo documento, um commit): (a) §7.2 (JSON de projeto) reescrito espelhando os schemas reais — `ts` → `ts_seconds`, `"dir": "R"` → `"direction": "r"`, `security_*`/`watchdog_*` planos no lugar de `security:{}`/`watchdog:{}`, `data_type`/`description` nas tags, `auth_mode`/`auth_username` nas conexões, mais `exported_at`, `desired_state` e o `tag_ref` objeto dentro do `graph` (usar o bloco §Contratos verbatim acima, byte a byte); (b) **RF-102** (`PRD.md:82`) passa de "Export do projeto **ativo**" para "Export de **um projeto** (por id)" com a justificativa de A-14; (c) §7.1 linha `opc.values.<conn_id>` perde `api(WS)` da coluna Consumidores e §7.3 deixa de descrever o `/ws` como "(valores, …)" — passa a `flow.status`, `mpc.state`, `events`; (d) changelog v1.4 datado e cabeçalho §Status (`PRD.md:4`, hoje "F1 e F2 concluídas") atualizado para F1-F5 concluídas | `docs/PRD.md` | grep `v1.4`, `ts_seconds`, `tag_ref`, `exported_at` no PRD; RF-102 sem a palavra "ativo"; linha `opc.values` sem `api(WS)`; nenhuma outra linha de §7.1 alterada | A-14 · F6R-02 · RFC-05/06 |
| 0.2 | **Notas de remissão nas specs anteriores** (§1.3-3/4/5/6; specs não são reescritas — recebem nota no trecho alterado apontando a spec F6): F2 §1.2 "UI de gestão de certificados \| F6" ⇒ cumprida por F6 §6.2; F4 §1.2 e F5 §1.2 "suíte completa RNF-09 \| F6" ⇒ cumprida por F6 §7; F5 §1.2 "EU nas portas de Script/TFS \| F6" ⇒ cumprida por F6 §4.1; F5 §8 última linha (`shutdown_mpc` sob o lock) ⇒ fecha em F6 §5.2, **com a correção de registro**: são três contextos reais e o quarto chamador que o ledger da F5 não registrou é `_deploy` sobre `old_runtime` (`supervisor.py:338`) | `docs/specs/F2-aquisicao.md` · `docs/specs/F4-mpc.md` · `docs/specs/F5-operacao.md` | grep "spec F6" acha as 5 notas nos trechos certos; diff não altera nenhuma frase normativa fora das notas | §1.3 |
| 0.3 | **GLOSSARY** (§1.3-8): entrada **arquivo de projeto** (o JSON de export/import; "bundle" é termo interno de código, **proibido na UI**) e entrada **pendência** (condição de configuração que impede a conexão de subir, derivada dos dados existentes, sem estado persistido) | `docs/GLOSSARY.md` | as duas entradas em ordem alfabética; a de "arquivo de projeto" diz explicitamente que "bundle" não aparece em tela | §1.3-8 · UX-10 |
| 0.4 | **Constantes de mensagem** (§3.1-3, §3.2-6): `MSG_PROJETO_NAO_ENCONTRADO = "Projeto não encontrado"` e `MSG_PROJETO_NOME_EM_USO = "Nome de projeto já em uso"` em `messages.py` (hoje só tem `MSG_FLOW_NAO_ENCONTRADO`, `messages.py:3`); `projects.py:21` (404), `projects.py:39` e `projects.py:62` (409) e `flows.py:134` (404 de projeto, hoje literal duplicado por valor) passam a importar. **Não confundir com `MSG_FLOW_NAO_ENCONTRADO`** — é outra entidade | `services/api/src/ottima_api/messages.py` · `routers/projects.py` · `routers/flows.py` | `grep -rn '"Projeto não encontrado"\|"Nome de projeto já em uso"' services/` só acha `messages.py`; `uv run pytest services/api` verde sem mudar nenhuma asserção de texto | §3.1-3 |
| 0.5 | **`traduzir_erro_de_validacao` extraída** para módulo próprio, sem mudança de comportamento: `_MOTIVO_POR_TIPO` (`app.py:23-39`) e `_traduzir_erro_de_validacao` (`app.py:42-56`) migram para `ottima_api/validacao.py` (novo) como `traduzir_erro_de_validacao` público; `app.py` importa e o handler (`app.py:59-68`) fica idêntico. Motivo: o import (tarefa 2.3) precisa da mesma tradução, e um router importando de `app.py` fecharia ciclo (`app.py` importa `ottima_api.ws` no topo) | `services/api/src/ottima_api/validacao.py` (novo) · `services/api/src/ottima_api/app.py` · `services/api/tests/test_validation_handler.py` | `uv run pytest services/api` verde **sem alterar nenhum teste**; grep `_traduzir_erro_de_validacao` não acha nada | dívida de forma |

**Conclusão:** `uv run pytest` (workspace) + ruff verdes. 0.1-0.3 são só documentos; 0.4-0.5 não mudam comportamento algum.

---

## Etapa 1 — Contrato de portabilidade (spec §2; decisão A-2; F6R-05)

> Pacote novo `packages/ottima-core/src/ottima_core/portability/` (`__init__.py` re-exportando o que a api usa). Tudo aqui é **puro**: nenhuma função desta etapa toca banco, Redis ou disco.

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 1.1 | **Schemas de bundle + regras de coerência extraídas** (§2.1-1/2/3): módulo com os 6 modelos da seção §Interfaces, **todos `extra="forbid"`**, reusando os aliases já existentes (`SecurityPolicy`/`SecurityMode`/`AuthMode` de `schemas/connections.py:8-10`, `Direction`/`DataType` de `schemas/tags.py:8-9`, `TsSeconds`/`DesiredState` de `schemas/flows.py:9-10`). `desired_state` é `Literal["running","stopped"]` **no schema** — sem isso um valor malformado escaparia como `IntegrityError` do CHECK `ck_flows_desired_state` (`models/flow.py`) no `flush()`, virando 500 em vez do 422 agregado (F6R-12). Em `schemas/connections.py`, as regras `erro_policy_mode` e `erro_watchdog` viram funções puras de módulo (mensagens verbatim das atuais, `connections.py:33-36` e `:39-40`) chamadas por `ConnectionCreate._coerencia` **e** por `BundleConnection._coerencia`; `erro_auth_username` (nova, "Autenticação usuário/senha exige usuário") é só do bundle — `ConnectionCreate` mantém a sua exigência de usuário **e** senha (`connections.py:37-38`) com o texto atual intacto, porque o bundle nunca carrega senha (§2.3) e a tabela §2.1-2 registra essa divergência de propósito | `packages/ottima-core/src/ottima_core/portability/__init__.py` (novo) · `portability/schemas.py` (novo) · `packages/ottima-core/src/ottima_core/schemas/connections.py` · `packages/ottima-core/tests/test_portability_schemas.py` (novo) | RED: bundle com `auth_password` ⇒ `ValidationError` (`extra_forbidden`); com `server_cert_file` ⇒ idem; com `id`/`project_id`/`connection_id` ⇒ idem; `security_policy: "basic256sha256"` + `security_mode: "none"` ⇒ reprovado com a mensagem verbatim; `auth_mode: "user_password"` **sem senha e com usuário** ⇒ **aprovado** (é o exemplo normativo de §2.1-1); sem usuário ⇒ reprovado; watchdog com um só `node_id` ⇒ reprovado; `desired_state: "paused"` ⇒ reprovado na forma; `ts_seconds: 3` ⇒ reprovado. `uv run pytest services/api` continua verde (regra de `ConnectionCreate` inalterada) | RF-102 · A-2 · F6R-05/12 |
| 1.2 | **`TAG_REF_FIELDS` e tradução nos dois sentidos** (§2.2): a lista dos campos vive **num lugar só**; a tradução é explícita por campo, nunca varredura heurística. `grafo_para_bundle` percorre `nodes[].data` (`tag_id` de `opc_read`/`opc_write`) e `nodes[].data.variables.mvs[].pid` (`write_tag_id`, `mode_cmd_tag_id`, `mode_read_tag_id` opcional, `readback_tag_id`), troca cada `*_tag_id` por `*_tag_ref` objeto e **levanta `ReferenciaTagInvalida` com a lista de problemas** quando um id não resolve; `grafo_para_banco` faz o inverso; `problemas_de_tag_ref` valida em memória sem traduzir (camada 3, §2.2-5). Nenhuma das três chama `parse_graph`: o grafo do bundle é forma **distinta** do `graph_json`, não superset — `TagConfig` (`parse.py:46-51`) e `PidBinding` (`mpc_config.py:58-68`) são `extra="forbid"` com `tag_id: int` e nunca veem `tag_ref` (§2.2-4). Campo `*_tag_ref` ausente onde é obrigatório é problema reportado, **não** `KeyError` (TST-05) | `packages/ottima-core/src/ottima_core/portability/tag_ref.py` (novo) · `packages/ottima-core/tests/test_tag_ref.py` (novo) | RED: round-trip dos 6 lugares (grafo com `opc_read`, `opc_write` e `mpc` de 2 MVs, uma com `mode_read_tag_id` e outra sem) devolve o grafo original byte a byte; id ausente do mapa ⇒ `ReferenciaTagInvalida` com o caminho do nó; `pid` sem `write_tag_ref` ⇒ problema, sem exceção de chave; **teste de completude por introspecção**: os `id_key` de `TAG_REF_FIELDS` conferidos contra `_CONFIG_KEYS` (`parse.py:19-25`) e `PidBinding.model_fields` pela convenção `*_tag_id` — campo novo com referência de tag esquecida vira vermelho (§9.1, TST-06) | A-2 · §2.2-3 |
| 1.3 | **Montagem e coerência interna** (§2.1-7, §3.2-4 camada 3): `ref_por_id` monta `{tag.id: (connection.name, tag.name)}` a partir dos models carregados; `montar_bundle` projeta projeto/conexões/tags/flows em `ProjectBundle` (ordem estável: conexões e flows por `name`, tags por `(connection, name)` — arquivo que circula entre plantas não pode ter diff espúrio) chamando `grafo_para_bundle` por flow; `problemas_de_coerencia_interna` reprova, **em memória e antes de qualquer insert**: tag apontando para conexão ausente no bundle, `tag_ref` que não casa com nenhuma `(connection, tag)` do próprio bundle, e nome duplicado dentro do bundle (conexão, flow, e tag duplicada **dentro da mesma conexão** — `Tag.name` é único por conexão, `models/tag.py`, não por projeto). Assim `IntegrityError` de unicidade nunca escapa como 500 (TST-04) | `packages/ottima-core/src/ottima_core/portability/bundle.py` (novo) · `packages/ottima-core/tests/test_bundle.py` (novo) | RED: **round-trip puro** — projeto com 2 conexões, **tag homônima nas duas** (TST-01), 1 flow MPC↔TFS ⇒ bundle ⇒ de volta a models com ids **diferentes** ⇒ grafo aponta para a tag da conexão certa; bundle sem segredos e sem ids (varredura recursiva do JSON por `auth_password`, `server_cert_file`, `id`, `project_id`, `connection_id`, `is_active`, `created_at`, `updated_at`); duas tags homônimas na **mesma** conexão ⇒ problema; duas conexões homônimas ⇒ problema; `exported_at` presente e ignorado na volta (§2.1-5) | RF-102 · A-2 · TST-01/04 |

**Conclusão:** `uv run pytest packages` + ruff verdes.

---

## Etapa 2 — Export e import (spec §3.1/§3.2; RF-102 emendado, RF-103)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 2.1 | **Agregador de 422 e predicados de pendência** (§3.2-5, §3.2-8): em `ottima_api/validacao.py` (criado em 0.5), `problemas_de_validacao(exc, prefixo="")` converte `ValidationError.errors()` em `"<caminho>: <motivo pt-BR>"` reusando `traduzir_erro_de_validacao`, e `formatar_problemas(problemas, cabecalho=…)` monta a string única `"<cabecalho> (N problemas) | p1 | p2 | …"`, **separador ` | `**, teto de 10 com sufixo `" | e mais N"` — o cabeçalho `"Import recusado"` é normativo (§3.2-5) e o export passa `"Export recusado"`. Em `ottima_core/portability/pendencias.py`, `pendencias_da_conexao` implementa os **três** predicados de §3.2-8 — `needs_password ⇔ auth_mode == "user_password" and not has_password`; `needs_server_certificate ⇔ security_policy != "none" and server_cert_file is None`; `needs_app_certificate ⇔ (security_policy != "none" or auth_mode == "certificate") and not app_cert_exists`. O terceiro fecha F6R-14: `auth_mode: certificate` reusa o par do certificado de aplicação (`opc-worker/security.py:167-176`), ausente numa instalação nova. Schemas `PendingSecretOut`/`ProjectImportIn`/`ProjectImportOut` em `schemas/projects.py`, ao lado de `ProjectOut` (`projects.py:18-26`) | `services/api/src/ottima_api/validacao.py` · `packages/ottima-core/src/ottima_core/portability/pendencias.py` (novo) · `packages/ottima-core/src/ottima_core/schemas/projects.py` · `packages/ottima-core/tests/test_pendencias.py` (novo) · `services/api/tests/test_validacao.py` (novo) | RED: **tabela-verdade completa** de `auth_mode` × `has_password` × `security_policy` × `server_cert_file` × `app_cert_exists` (3×2×2×2×2 = 48 casos, gerados por `itertools.product` e conferidos contra as 3 fórmulas); `formatar_problemas` com 13 problemas ⇒ 10 + `" | e mais 3"`; problema contendo `ns=2;s=TT101` sobrevive íntegro e a string parte de volta em 10 pedaços por `" | "` (UX-06) | A-4 · F6R-14 · UX-06 |
| 2.2 | **`GET /api/projects/{project_id}/export`** (§3.1): rota no router `projects` com `require_admin` (PRD §2 põe export/import na linha exclusiva de admin; mesmo sem segredos o bundle revela a topologia OPC completa). Carrega projeto (404 `MSG_PROJETO_NAO_ENCONTRADO` da tarefa 0.4), conexões, tags e flows do projeto; `montar_bundle(..., exported_at=datetime.now(UTC))`; responde `Response(media_type="application/json")` com `Content-Disposition: attachment; filename="<slug>.ottima.json"` — molde de `certificates.py:76-80`. `_slug` reduz o nome a `[a-z0-9-]` (minúsculas, separadores colapsados, hífens das pontas removidos); nome que reduz a vazio cai em `projeto` **[NOVA — implementação]**. `ReferenciaTagInvalida` ⇒ **422** com `formatar_problemas(…, cabecalho="Export recusado")` (tarefa 2.1), nunca exporta bundle quebrado (§2.2-5). Emite `KIND_PROJECT_EXPORTED` (novo em `bus.py`, junto do bloco de kinds — `bus.py:129-171`), severity `info`, origin `user:<id>`, payload `{project_id, name}`, **depois** da resposta ser montada, no padrão de `connections.py:240-247`. Sem paginação (RNF-01: ≤5 conexões, ~100 tags, ~10 flows) | `services/api/src/ottima_api/routers/projects.py` · `packages/ottima-core/src/ottima_core/bus.py` · `services/api/tests/test_projects_export.py` (novo) | RED: export de projeto com 2 conexões e tag homônima ⇒ 200, corpo sem `auth_password_enc`/`server_cert_file`/ids/timestamps, `tag_ref` objeto nos 6 lugares, `schema_version: 1`, `Content-Disposition` com o slug; projeto inexistente ⇒ 404 com a mensagem de **projeto**; operador ⇒ 403; grafo com `tag_id` de outro projeto ⇒ 422 agregado; evento `project_exported` publicado | RF-102 · A-14 · SEC-05 |
| 2.3 | **`POST /api/projects/import`** (§3.2): `require_admin`. **Teto de 4 MiB por leitura em stream antes de qualquer amarração Pydantic** — dependência `_ler_corpo_import(request)` no molde exato de `_ler_certificado` (`connections.py:106-126`: pré-checagem de `content-length`, depois `async for chunk in request.stream()` cortando no primeiro byte além do teto), porque um `body:` tipado já materializou o payload quando se consegue medi-lo (API-06); excedente ⇒ **413** pt-BR. Depois, na ordem: `json.loads` (falha ⇒ 422 "Corpo não é JSON válido"); `ProjectImportIn`; **camada 1** `bundle.get("schema_version") != 1` ⇒ 422 imediato, sem tentativa de migração (§3.2-2); **camada 2** `ProjectBundle.model_validate` ⇒ 422 agregado por `problemas_de_validacao` + `formatar_problemas(…, cabecalho="Import recusado")`; **camada 3** `problemas_de_coerencia_interna` ⇒ 422 agregado; nome (o de `body.name` se vier, senão `bundle.project.name`) já existente ⇒ **409** `MSG_PROJETO_NOME_EM_USO`; então **transação única** (molde de `activate_project`, `projects.py:77-112`): insere Project (**`is_active` sempre `False`** — RF-103), conexões, tags, `flush()` para obter os ids, monta `{(connection, tag) → novo_id}`, `grafo_para_banco` por flow e **camada 4** `parse_graph` + `validate_graph` ⇒ 422 agregado com `rollback`; só então insere os flows e faz **um** `commit()`. 201 `ProjectImportOut` com `pending_secrets` (tarefa 2.1; `app_cert_exists` de `read_app_certificate(settings.certs_dir).exists`, com `ValueError` — certificado ilegível, `certificates.py:33-36` — tratado como **ausente**, porque cert ilegível não autentica **[NOVA — implementação]**). Emite `KIND_PROJECT_IMPORTED` (novo em `bus.py`) com payload de contagens, depois do commit | `services/api/src/ottima_api/routers/projects.py` · `packages/ottima-core/src/ottima_core/bus.py` · `services/api/tests/test_projects_import.py` (novo) | RED, um por linha: `schema_version: 2` ⇒ 422 sem tocar o banco; campo proibido ⇒ 422 camada 2; `tag_ref` órfã ⇒ 422 camada 3; nome duplicado no bundle ⇒ 422 camada 3 **sem `IntegrityError`**; `exec_order` não contíguo ⇒ 422 camada 4; nome de projeto colidindo ⇒ 409; corpo > 4 MiB ⇒ 413 (o teste envia stream, não dict); operador ⇒ 403; sucesso ⇒ 201, `is_active is False`, `pending_secrets` com os 3 predicados, evento `project_imported`; **após cada recusa, contagem de projetos/conexões/tags/flows inalterada** | RF-103 · A-5/A-6 · API-06/07/08 · TST-04/05 |

**Conclusão:** `uv run pytest packages services/api` + ruff verdes.

---

## Etapa 3 — Health, log estruturado e superfície do Script (spec §3.3/§3.4)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 3.1 | **Campo `service` no log estruturado** (§3.4-1; A-16; RNF-07 estava **descoberto**, não cumprido): `JsonFormatter` (`logging.py`) passa a emitir `service` ao lado de `{ts, level, logger, message}`; `setup_logging(level: str = "INFO", service: str = "unknown")` guarda o nome no formatter. `record.name` é o caminho do logger Python, não o serviço — hoje a distinção só existe no prefixo de container do `docker compose logs`. Os 5 pontos de chamada informam o seu, todos hoje `setup_logging(settings.log_level)` verbatim: `api/app.py:91` ⇒ `"api"`; `api/seed.py:44` ⇒ `"api-seed"`; `opc-worker/main.py:64` ⇒ `"opc-worker"`; `flow-runtime/main.py:75` ⇒ `"flow-runtime"`; `recorder/main.py:44` ⇒ `"recorder"` (os 4 workers já têm `SERVICE_NAME` de módulo — reusar a constante existente, não literal novo) | `packages/ottima-core/src/ottima_core/logging.py` · os 5 call sites · `packages/ottima-core/tests/test_logging.py` | RED: `setup_logging("INFO", "api")` ⇒ linha JSON com `"service": "api"`; default sem serviço ⇒ `"unknown"` (nunca `KeyError`, nunca chave ausente); `exc` continua saindo quando há `exc_info`; grep confirma os 5 call sites com nome próprio | RNF-07 · A-16 · F6R-04 |
| 3.2 | **`GET /api/health` reflete as dependências** (§3.3): hoje é literal fixo (`routers/health.py:16-18`). Passa a `{"status": "ok"\|"degraded", "service": "api", "version": API_VERSION, "redis_ok": bool, "db_ok": bool}`, **sempre 200**, **pública** (é o healthcheck do compose, `docker-compose.yml:46-51`, e o passo E2E-01a do smoke — exceção a RF-003 herdada da F1, registrada em §3.3-4). **O mecanismo é normativo**: heartbeat de fundo no `lifespan` (`app.py:71-86`) gravando `app.state.redis_ok`/`app.state.db_ok`, handler **sem I/O** lendo por `getattr(app.state, ..., False)` — cópia fiel do padrão dos 3 workers (`opc-worker/main.py:52-57` + `:85` + `:108-127`), incluindo `HEARTBEAT_INTERVAL_S = 5.0` como constante de módulo (não `Settings` — os 3 workers fazem assim) e o cancelamento com `task.cancel()` + `await task` em `CancelledError` na descida. Checagem síncrona por request na rota que o compose usa como healthcheck seria vetor de lentidão auto-infligido (F6R-13) | `services/api/src/ottima_api/routers/health.py` · `services/api/src/ottima_api/app.py` · `services/api/tests/test_health.py` | RED: app cru (sem lifespan) ⇒ 200 `degraded` com os dois `false`, **sem I/O**; heartbeat com Redis fora ⇒ `redis_ok: false`, `status: "degraded"`, ainda 200; ambos ok ⇒ `"ok"`; `GET /api/health` sem token continua 200 (pública); `/api/health/workers` (`health.py:33-40`) intacto | RNF-07 · F6R-13 |
| 3.3 | **`env_file` do `flow-runtime` restrito** (§3.4-2; A-15; RNF-04): `docker-compose.yml:89` (`env_file: [.env]` do serviço `flow-runtime`) é removido e o bloco `environment:` passa a listar **só** o que o serviço lê de fato — `OTTIMA_DATABASE_URL` e `OTTIMA_REDIS_URL` (já presentes) mais `OTTIMA_LOG_LEVEL: ${OTTIMA_LOG_LEVEL:-INFO}` (interpolação vem do `deploy/.env` do diretório do projeto, independente de `env_file` — mesmo mecanismo de `${POSTGRES_USER}`). Com isso `OTTIMA_SECRET_KEY` e `OTTIMA_FERNET_KEY` (`.env.example:18,22`) saem do ambiente do processo que executa código do bloco Script — código que, a partir desta fase, pode vir de um arquivo de projeto externo (§2.3 nota). Mudança de compose, não de arquitetura: o sandbox do Script não muda (ADR-018) e o resíduo fica em TD-001. Os outros três serviços (`docker-compose.yml:35,61,115`) **não** mudam | `deploy/docker-compose.yml` · `deploy/.env.example` (comentário registrando que o flow-runtime recebe lista explícita) | `cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build --no-deps flow-runtime` ⇒ serviço `healthy`; `docker compose exec -T flow-runtime env \| grep -c 'OTTIMA_SECRET_KEY\|OTTIMA_FERNET_KEY'` ⇒ **0**; `OTTIMA_E2E=1 bash deploy/smoke.sh` verde (passo E2E-F3-L1a inclusive) | RNF-04 · A-15 · TD-001 |

**Conclusão:** `uv run pytest` (workspace) + ruff verdes; smoke L1 verde.

---

## Etapa 4 — Schema: EU nas portas e faixa da DV (spec §4.1 backend, §4.2)

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 4.1 | **`output_eu` em `ScriptConfig` e `TfsConfig`** (§4.1; A-10; DESIGN §Typography "número sem unidade de engenharia é defeito"): campo `output_eu: dict[str, str] = Field(default_factory=dict)` nos dois modelos (`parse.py:54-59` e `:86-91`), chave `"output_eu"` acrescentada a `_CONFIG_KEYS["script"]` e `_CONFIG_KEYS["tfs"]` (`parse.py:19-25` — sem isso `_parse_node` recusa a chave como desconhecida, `parse.py:251-255`), e leitura em `_parse_script_config` (`parse.py:301-319`) / `_parse_tfs_config` (`parse.py:322-347`). Chaves válidas **verbatim de `validate.py:99-111`**: `tfs` ⇒ `y1`/`y2`; `script` ⇒ `OUT1..OUT{n_outputs}`, o que depende de outro campo do mesmo modelo ⇒ `model_validator(mode="after")` em `ScriptConfig`. Chave fora do conjunto, valor não-string ou `OUT{n}` além de `n_outputs` ⇒ erro de parse pt-BR na lista de `errors`, no formato das mensagens vizinhas. **Nada é obrigatório**: flow existente sem `output_eu` continua válido byte a byte, e porta sem declaração fica sem unidade (como `Tag.eu` já admite, default `''`). Sem propagação automática entre portas (§4.1-6) | `packages/ottima-core/src/ottima_core/flowgraph/parse.py` · `packages/ottima-core/tests/test_flowgraph_parse.py` | RED: `script` com `n_outputs: 2` e `output_eu: {"OUT1": "t/h"}` ⇒ ok; `{"OUT3": "t/h"}` com `n_outputs: 2` ⇒ erro; `{"out1": "t/h"}` ⇒ erro; `tfs` com `{"y1": "C"}` ⇒ ok, `{"y3": "C"}` ⇒ erro; grafo antigo sem a chave ⇒ ok e `output_eu == {}`; `opc_read` com `output_eu` ⇒ **chave desconhecida** (só script e tfs a declaram) | RF-511/521 · A-10 · F6R-09 |
| 4.2 | **`range` opcional na `DvVar` + projeção** (§4.2; A-11; RF-702): `range: Range | None = None` em `DvVar` (`mpc_config.py:128-135`), **reusando o `Range` `{low, high}` de `ConstraintVar`** (`mpc_config.py:40-46`) — JSONB, sem migration, opcional. `DvOut` (`operate.py:99-104`) ganha `range: Range | None = None` e a projeção de `GET /api/operate/mpcs` passa a informá-lo (`operate.py:289-290`), no mesmo padrão de `ConstraintOut` (`operate.py:286`). Config antigo sem `range` continua válido | `packages/ottima-core/src/ottima_core/flowgraph/mpc_config.py` · `services/api/src/ottima_api/routers/operate.py` · `packages/ottima-core/tests/test_mpc_config.py` · `services/api/tests/test_operate.py` | RED: `DvVar` sem `range` ⇒ válido, `range is None`; com `{"low": 0, "high": 100}` ⇒ válido; com `{"low": 0}` ⇒ 422 (`Range` é `extra="forbid"` com os dois campos); `/api/operate/mpcs` projeta `range` na DV que tem e `null` na que não tem | RF-702 · A-11 · RFC-16 |

**Conclusão:** `uv run pytest packages services/api` verde.

---

## Etapa 5 — Runtime: débitos herdados da F5 (spec §5)

> Etapa mais arriscada do plano. As invariantes dos fix rounds da F4 e da F5 §6.5 valem **byte a byte**; regressão da suíte `services/flow-runtime` inteira é parte do aceite de cada tarefa.

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 5.1 | **Payload de `mpc_overrun`** (§5.1): `_report_overrun` (`blocks/mpc.py:458-468`) publica hoje `payload={}` e passa a publicar `{"overruns": self._overruns}`, tornando a família "contador publicado" simétrica a `flow_overrun` (`scheduler.py:254-259`, spec F5 §7.2-1) — é o contador que a cessação de alarme do frontend usa (duas publicações consecutivas com o valor inalterado). O contador já existe: `self._overruns`, zerado em `reset()` (`blocks/mpc.py:234`), incrementado em `:340` e `:376`. **Regressão declarada (F6R-08):** `tests/e2e/test_f4_failure.py:218` assere `evento["payload"] == {"kind": KIND_MPC_OVERRUN}` por igualdade exata — `publish_event` injeta `kind` no payload (`bus.py`, "kind primeiro e vencendo um homônimo do chamador"). A asserção é atualizada **no mesmo commit** para `{"kind": KIND_MPC_OVERRUN, "overruns": <valor>}` com `overruns >= 1`. **Correção de âncora:** a spec §5.1 cita `test_f4_failure.py:226`; a linha 226 é comentário — a asserção real é a **218** (conferido nesta sessão) | `services/flow-runtime/src/ottima_flow_runtime/blocks/mpc.py` · `services/flow-runtime/tests/test_mpc_block.py` · `tests/e2e/test_f4_failure.py` | RED: overrun no bloco ⇒ evento com `payload["overruns"] == 1`; segundo overrun sem `reset()` ⇒ **nenhum evento novo** (dedupe por `_overrun_reported` intacto); após `reset()` ⇒ evento novo com contador zerado e resomado; `uv run pytest services/flow-runtime` verde | §5.1 · F6R-08 |
| 5.2 | **`shutdown_mpc` fora do lock global** (§5.2; débito F5 §8): nos **três** caminhos que hoje chamam o `shutdown_mpc` **síncrono** (`supervisor_mpc.py:417-432`) sob o lock (`supervisor.py:172`) — `_deploy` sobre o `old_runtime` do redeploy (`supervisor.py:338`, sob a tomada de `:259`), `_handback_failed_mpc` (`supervisor.py:549`, sob `:517`) e `_force_stop` (`supervisor.py:597`, sob `:494` e `:517`) — a chamada é substituída pela **sequência de TRÊS passos**, idêntica à que `_stop` já usa (`supervisor.py:346-353`): (1) `revert_armed_mpc` (`supervisor_mpc.py:395`, não espera processo nenhum), (2) **`detach_hosts`** (`supervisor_mpc.py:347`, síncrono, esvazia `runtime.hosts`), (3) `stop_host_background` (`supervisor_mpc.py:359`) por host. **Omitir o passo 2 é o defeito que F6R-06 pegou**: deixaria o host morto alcançável em `runtime.hosts` por até `_BOOT_TIMEOUT_S = 30 s`, permitindo comando concorrente sobre um worker morrendo — violação de "nunca dois workers escrevendo na mesma malha". **Posse das tasks destacadas** (§5.2-3): `stop_host_background` guarda a task em `runtime.mpc_stop_tasks` (`supervisor.py:129`); no caminho do redeploy o dono passa a ser o **runtime novo**, já publicado no mapa em `supervisor.py:317` antes da linha 338 — assim `_teardown` (`supervisor.py:644-649`, que **aguarda** `runtime.mpc_stop_tasks` de propósito) nunca abandona um kill em voo, e o defeito que a F5 §6.5 fechou não volta. `_teardown` **fica como está**: é o único lugar onde esperar o desmonte é correto (não roda sob o lock — `Supervisor.stop()`, `supervisor.py:219-222`). `shutdown_mpc` continua existindo só para `_teardown` | `services/flow-runtime/src/ottima_flow_runtime/supervisor.py` · `services/flow-runtime/src/ottima_flow_runtime/supervisor_mpc.py` · `services/flow-runtime/tests/test_supervisor_mpc.py` | RED (clock controlado, um por caminho): comando de **outro** flow não espera o build em nenhum dos 3 caminhos (latência medida, ordem de ms, nunca de `_BOOT_TIMEOUT_S`); **`runtime.hosts` vazio imediatamente após o passo 2**, antes de a task de fundo terminar (guarda do F6R-06); nenhum worker órfão após redeploy/`_force_stop`/handback; **`_teardown` continua esperando** as tasks destacadas, inclusive as nascidas no redeploy; idempotência preservada (`revert_armed_mpc` guarda por `block.local_remote`, `MpcHost.stop()` idempotente); `mpc_arm_failed {worker_not_ready}` nos dois eixos, shed/hot-swap/watchdog intocados. `uv run pytest services/flow-runtime` verde, incluindo `-m slow` uma vez | spec F5 §8 · F6R-06 |

**Conclusão:** `uv run pytest services/flow-runtime` verde (incl. `-m slow`); `uv run pytest` (workspace) verde.

---

## Etapa 6 — Fronteira com o F6b e fechamento do plano

| # | Tarefa | Arquivos | Verificar | RF/ADR |
|---|---|---|---|---|
| 6.1 | **Contratos regenerados** (§4.1-7, §12): `frontend/openapi.json` atualizado a partir do app (rotas novas de export/import, `/api/health` ampliado, `DvOut.range`) e `cd frontend && npm run generate:api` (que encadeia `generate:contracts` ⇒ `node scripts/generate-contracts.mjs` ⇒ `uv run python -m ottima_core.contracts_export`). `_WS_MODELS` (`contracts_export.py:94`) **não** muda — nenhum payload de WS foi tocado nesta fase; o que muda é `api-types.ts` (schemas REST) e o `PORT_CONTRACTS` afetado por `output_eu`. Os dois arquivos gerados são commitados | `frontend/openapi.json` · `frontend/src/lib/api-types.ts` · `frontend/src/lib/contracts.gen.ts` · `packages/ottima-core/tests/test_contracts_export.py` | `cd frontend && npm run build` verde (mudanças aditivas); diff do gerado contém `ProjectImportOut`, `PendingSecretOut` e `range` em `DvOut`; `uv run pytest packages` verde | débito 0.2 da F4 (fonte única) |
| 6.2 | **L1 e encerramento parcial**: `deploy/smoke.sh` passo E2E-01a passa a conferir `redis_ok`/`db_ok` **presentes** e `status: ok` no `/api/health` (hoje só faz `grep -q '"status"'`); CLAUDE.md §Comandos ganha as rotas novas (`GET /api/projects/{id}/export`, `POST /api/projects/import`) e a nota do `env_file` restrito do flow-runtime; ledger `.superpowers/sdd/F6a-portabilidade-dados/progress.md` completo com as provas RED | `deploy/smoke.sh` · `CLAUDE.md` · ledger | `OTTIMA_E2E=1 bash deploy/smoke.sh` verde com o stack recém-subido; seção do CLAUDE.md reflete comandos reais | RNF-07 · CLAUDE.md §Comandos |

---

## Aderência (DoD do plano F6a)

| Critério | Tarefas |
|---|---|
| Emendas §1.3 aplicadas (PRD v1.4 + 5 notas de remissão + GLOSSARY) | 0.1, 0.2, 0.3 |
| Constantes de mensagem e tradução de validação extraídas | 0.4, 0.5 |
| Contrato de portabilidade: schemas próprios `extra="forbid"`, `tag_ref` objeto nos 6 lugares, coerência interna | 1.1, 1.2, 1.3 |
| Export por id, sem segredos, com auditoria e RBAC | 2.2 |
| Import com 4 camadas, transação única, 413/409/422 agregado, `is_active` sempre false, `pending_secrets` com 3 predicados | 2.1, 2.3 |
| RNF-07: `service` no log dos 5 pontos + `/api/health` com heartbeat de fundo | 3.1, 3.2 |
| RNF-04: segredos fora do processo que executa Script | 3.3 |
| `output_eu` (backend) e `DvVar.range` (schema + projeção) | 4.1, 4.2 |
| Débitos de runtime da F5 fechados (payload de overrun; `shutdown_mpc` em 3 passos nos 3 caminhos) | 5.1, 5.2 |
| Contratos regenerados — fronteira com o F6b | 6.1 |
| Zero regressão F1-F5 no workspace e no L1 | Conclusão de cada etapa, 5.2 (`-m slow`), 6.2 |

O aceite da FASE (PRD §8-F6) fecha no plano F6c, com o gate completo e o roteiro L3 de `docs/plans/tests-e2e-f6.md`.

## Rastreabilidade (RF/decisão por tarefa)

| Norma | Tarefas |
|---|---|
| RF-102 (export de um projeto, emendado) | 0.1, 2.2 |
| RF-103 (import cria projeto inativo) | 2.3 |
| RF-511/521 (EU nas portas) | 4.1 |
| RF-702 (faceplates com EU e limites) | 4.2 |
| RF-624 (contador de overrun publicado) | 5.1 |
| RNF-04 (segredos) | 3.3 |
| RNF-07 (observabilidade) | 3.1, 3.2, 6.2 |
| ADR-012 (portabilidade de engenharia) | 1.1, 1.2, 1.3, 2.2, 2.3 |
| ADR-018 (escopo do Script) | 3.3 |
| ADR-020 (eventos sem ACK) | 2.2, 2.3 |
| Decisões A-2/A-3/A-4/A-5/A-6/A-10/A-11/A-14/A-15/A-16 | 1.1-1.3 / 1.1+1.3 (o `.der` do servidor fica fora do arquivo: `extra="forbid"` no schema e varredura no teste de round-trip) / 2.1 / 2.3 / 2.3 / 4.1 / 4.2 / 0.1+2.2 / 3.3 / 3.1 |
| F6R-02/04/05/06/08/09/12/13/14 | 0.1 / 3.1 / 1.1 / 5.2 / 5.1 / 4.1 / 1.1 / 3.2 / 2.1 |
| TST-01/04/05/06 · API-06/07/08 · SEC-05 · UX-06 | 1.3 / 1.3+2.3 / 1.2+2.3 / 1.2 · 2.3 / 2.1 / 2.2+2.3 · 2.2 · 2.1 |
