# Spec F1 — Fundação

**Fase:** F1 (PRD §8) · **Status:** aprovado seção a seção em sessão de brainstorm · 2026-08-03
**Fontes normativas:** `docs/PRD.md` (RF/RNF, contratos §7, fases §8) · `docs/adr/ADR-001…023` (prevalecem em conflito) · `docs/GLOSSARY.md` · `PRODUCT.md`/`DESIGN.md` (frontend)
**Convenção de rastreabilidade:** cada decisão cita o RF-xxx/ADR-nnn/regra de PRODUCT/DESIGN que a governa; decisões sem cobertura nos documentos estão marcadas **[NOVA — implementação]** e foram aprovadas pelo usuário nesta sessão.

Este documento especifica **implementação**. Ele não redefine produto, arquitetura nem visual; onde repete conteúdo normativo, é citação.

---

## 1. Escopo da F1

**Entrega (PRD §8-F1):** Compose, schema DB (+hypertables/retenção), auth/RBAC, CRUD de projetos/conexões/tags.
**Aceite (PRD §8-F1):** login admin/operador · retenção ativa · `docker compose up` sobe tudo.

### 1.1 Dentro da F1
- Monorepo + workspace `uv` (§2).
- DDL completo de **todas** as tabelas — inclusive `flows`, cujo CRUD é F3 — + hypertables, retention policies e continuous aggregate (§3).
- Migrations Alembic (§4).
- Auth JWT + RBAC + seed de admin (§5).
- API CRUD: `/api/users`, `/api/projects` (+`/activate`), `/api/connections`, `/api/tags`, `/api/health` (§6).
- `deploy/docker-compose.yml` com os 7 serviços (ADR-023), Dockerfiles, `.env.example` (§7). Workers sobem como **esqueleto** com `/health` (RNF-07) — funcionalidade real chega em F2/F3.
- Frontend: tokens do design system, tela de login, shell autenticado com faixa anunciadora vazia (§8).
- Infra de testes: pytest + pytest-asyncio + testcontainers + fixtures de DB (§9).

### 1.2 Fora da F1 — com destino registrado
| Item | Destino | Governança |
|---|---|---|
| Telas CRUD de engenharia (conexões/tags; projetos/flows) | F2 (comissionamento) e F3 | **[NOVA — implementação]** decisão de escopo desta sessão; aceite F1 não as exige |
| Rotas `/flows`, `/operate`, `/history`, `/events`, `/ws` | F3–F5 | PRD §7.3, §8 |
| Geração/trust de certificados (RF-202): API | F2 (opc-worker precisa do certificado de aplicação para Basic256Sha256) | ADR-021, PRD §8-F2 |
| Gestão de certificados: UI | F6 | PRD §8-F6 |
| Export/import de projeto (RF-102/103) | F6 | PRD §8-F6, ADR-012 |
| Browse do address space OPC | F2+ ("desejável", não obrigatório) | RF-203 |
| Paleta de penas de trend | F2 (primeira tendência) | DESIGN.md (`[a resolver]`) |
| Eventos de auditoria de CRUD | F2 (junto do publisher do canal `events`) | ADR-020; **[NOVA — implementação]** ver §6.3 |

---

## 2. Monorepo & workspace `uv`

Layout do CLAUDE.md (fixado; não relitigado aqui):

```
pyproject.toml            # raiz virtual: [tool.uv.workspace] members = ["packages/*", "services/*"]
                          # + [dependency-groups] dev + [tool.ruff] + [tool.pytest.ini_options]
.python-version           # 3.12
docs/                     # normativos (não editados pela implementação)
packages/
  ottima-core/            # pacote python `ottima_core`
    src/ottima_core/
      config.py           # Settings (pydantic-settings, prefixo OTTIMA_)
      db.py               # engine/session factory async
      models/             # SQLAlchemy 2.0 (declarative, async)
      schemas/            # Pydantic v2: API request/response + payloads do barramento (§7.1 do PRD)
      bus.py              # nomes de canais + helpers redis (tipado na F1; usado a partir da F2)
      security.py         # hash Argon2id, JWT, Fernet
    alembic/  alembic.ini
services/
  api/                    # `ottima_api`: FastAPI REST; routers auth/users/projects/connections/tags
  opc-worker/             # `ottima_opc_worker`: F1 = esqueleto (health + ping Redis)
  flow-runtime/           # `ottima_flow_runtime`: F1 = esqueleto
  recorder/               # `ottima_recorder`: F1 = esqueleto
frontend/                 # React + Vite (§8)
deploy/                   # docker-compose.yml, Dockerfile.python, .env.example, smoke.sh
tests/                    # cross-service (MPC↔TFS, F4+); na F1 só README de propósito
```

Decisões:
- **Python pinado em 3.12** (`requires-python = ">=3.12,<3.13"`): CLAUDE.md exige ≥3.12; teto em 3.12 por disponibilidade de wheels casadi/do-mpc (F4). Revisitar no início da F4. **[NOVA — implementação]**
- **`ottima-core` concentra o compartilhado** (CLAUDE.md): modelos, schemas, contratos do barramento já tipados na F1 (payloads do PRD §7.1 verbatim), settings, db, criptografia. Cada service depende de `ottima-core` via `[tool.uv.sources] ottima-core = { workspace = true }`.
- **Dependências F1** — core: `sqlalchemy[asyncio]`, `asyncpg`, `pydantic`, `pydantic-settings`, `alembic`, `cryptography`, `redis`; api: `fastapi`, `uvicorn[standard]`, `pwdlib[argon2]`, `pyjwt`; workers: `ottima-core` + `fastapi`/`uvicorn` (app mínimo de health; mesmo padrão dos serviços nas fases seguintes — zero dependência nova). Dev (raiz): `pytest`, `pytest-asyncio`, `testcontainers`, `httpx`, `ruff`. Novas dependências fora disso exigem justificativa (CLAUDE.md).
- **Comando canônico:** `uv sync --all-packages`. A seção "Comandos" do CLAUDE.md será atualizada na implementação da F1 (o próprio arquivo pede).
- **`ruff`** (lint + format) configurado uma única vez na raiz (CLAUDE.md).

Governança: CLAUDE.md (layout, uv workspace, convenções), ADR-001 (FastAPI/SQLAlchemy), ADR-006 (separação de serviços); o restante **[NOVA — implementação]**.

---

## 3. Banco de dados — DDL completo

Regras gerais:
- Identificadores em inglês (CLAUDE.md); GLOSSARY é o cânone de tradução na UI.
- Todos os timestamps `TIMESTAMPTZ`, UTC no servidor; conversão só no cliente.
- PKs `BIGINT GENERATED ALWAYS AS IDENTITY` — export/import referencia entidades por **nome** (PRD §7.2); UUID não compra nada. **[NOVA — implementação]**
- `created_at`/`updated_at` nos cadastros, mantidos pela aplicação (SQLAlchemy `onupdate`), sem trigger. **[NOVA — implementação]**
- O schema abaixo é a referência; a fonte executável são as migrations (§4).

### 3.1 Cadastros relacionais

```sql
-- RF-001/002, ADR-015 (User: PRD §4)
CREATE TABLE users (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username      TEXT NOT NULL,
  name          TEXT NOT NULL,
  password_hash TEXT NOT NULL,              -- Argon2id (§5.1)
  role          TEXT NOT NULL CHECK (role IN ('admin','operator')),
  is_active     BOOLEAN NOT NULL DEFAULT true,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_users_username ON users (lower(username));

-- RF-101, ADR-017
CREATE TABLE projects (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  is_active   BOOLEAN NOT NULL DEFAULT false,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- "no máx. 1 ativo" (ADR-017) garantido no banco:
CREATE UNIQUE INDEX uq_projects_single_active ON projects (is_active) WHERE is_active;

-- RF-201/206, ADR-009, ADR-021 (OpcConnection: PRD §4)
CREATE TABLE opc_connections (
  id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  project_id             BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name                   TEXT NOT NULL,
  endpoint               TEXT NOT NULL,
  security_policy        TEXT NOT NULL DEFAULT 'none'
                         CHECK (security_policy IN ('none','basic256sha256')),
  security_mode          TEXT NOT NULL DEFAULT 'none'
                         CHECK (security_mode IN ('none','sign','sign_and_encrypt')),
  auth_mode              TEXT NOT NULL DEFAULT 'anonymous'
                         CHECK (auth_mode IN ('anonymous','user_password','certificate')),
  auth_username          TEXT,
  auth_password_enc      TEXT,              -- token Fernet (§5.4); NUNCA em export/response
  server_cert_file       TEXT,              -- nome de arquivo no volume `certs` (ADR-021)
  watchdog_read_node_id  TEXT,              -- ADR-009: bits por conexão
  watchdog_write_node_id TEXT,
  watchdog_period_ms     INTEGER NOT NULL DEFAULT 1500
                         CHECK (watchdog_period_ms BETWEEN 500 AND 5000),  -- ADR-009: 1–2 s, ≪10 s
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, name),
  -- coerência policy×mode (RF-201): None anda com None; Basic256Sha256 com Sign/SignAndEncrypt
  CHECK ((security_policy = 'none' AND security_mode = 'none')
      OR (security_policy <> 'none' AND security_mode <> 'none'))
);

-- RF-203 (Tag: PRD §4)
CREATE TABLE tags (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  connection_id BIGINT NOT NULL REFERENCES opc_connections(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,              -- nome lógico
  node_id       TEXT NOT NULL,
  direction     TEXT NOT NULL CHECK (direction IN ('r','w')),
  data_type     TEXT NOT NULL CHECK (data_type IN ('float','int','bool')),
  eu            TEXT NOT NULL DEFAULT '',
  description   TEXT NOT NULL DEFAULT '',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (connection_id, name)
);

-- ADR-005/007/011/017 (Flow: PRD §4). CRUD na F3; DDL completo já na F1.
CREATE TABLE flows (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  project_id    BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  ts_seconds    NUMERIC(4,1) NOT NULL
                CHECK (ts_seconds IN (0.5,1,2,5,10,30,60)),          -- lista fixa (ADR-007)
  desired_state TEXT NOT NULL DEFAULT 'stopped'
                CHECK (desired_state IN ('running','stopped')),      -- persistido, não auto-aplicado no boot (ADR-017)
  graph_json    JSONB NOT NULL DEFAULT '{"nodes":[],"edges":[]}',    -- React Flow (ADR-005); sem versionamento (ADR-011)
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, name)
);
```

Validações que ficam na aplicação (Pydantic/serviço), não no banco:
- `auth_mode='user_password'` ⇒ `auth_username` e senha obrigatórios; `auth_mode='certificate'` ⇒ certificado presente no volume (F2). **[NOVA — implementação]**
- Watchdog: os dois node_ids preenchidos **ou** ambos vazios (RF-206 exige o par para operar; o bloqueio "sem watchdog vivo não há escrita" é RNF-03/F2).
- ≤ 5 conexões por projeto (RF-201) — regra de serviço, §6.

### 3.2 Hypertables + retention (ADR-003, ADR-020, RF-801)

```sql
-- Sample (PRD §4): payload de `opc.values.*` (PRD §7.1) persistido pelo recorder (F2)
CREATE TABLE samples (
  ts      TIMESTAMPTZ NOT NULL,
  tag_id  BIGINT NOT NULL,             -- SEM FK: ver decisão N2 abaixo
  value   DOUBLE PRECISION NOT NULL,
  quality SMALLINT NOT NULL DEFAULT 0  -- 0=good, 1=uncertain, 2=bad (ordem habilita max()=pior)
);
SELECT create_hypertable('samples', 'ts', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ix_samples_tag_ts ON samples (tag_id, ts DESC);
SELECT add_retention_policy('samples', INTERVAL '1 month');          -- RF-801, ADR-003

-- Event (PRD §4): colunas = payload do canal `events` (PRD §7.1)
CREATE TABLE events (
  ts       TIMESTAMPTZ NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('info','warning','alarm')),  -- ADR-020
  origin   TEXT NOT NULL,              -- ex.: 'user:2', 'conn:1', 'flow:3/block:mpc1'
  message  TEXT NOT NULL,
  payload  JSONB NOT NULL DEFAULT '{}'
);
SELECT create_hypertable('events', 'ts', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX ix_events_severity_ts ON events (severity, ts DESC);    -- filtros RF-803
CREATE INDEX ix_events_origin_ts   ON events (origin, ts DESC);
SELECT add_retention_policy('events', INTERVAL '1 month');           -- ADR-020: mesma política
```

### 3.3 Continuous aggregate de 1 min (RF-801/802)

```sql
CREATE MATERIALIZED VIEW samples_1m WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', ts) AS bucket,
       tag_id,
       avg(value)   AS avg_value,
       min(value)   AS min_value,
       max(value)   AS max_value,
       count(*)     AS n_samples,
       max(quality) AS worst_quality
FROM samples
GROUP BY bucket, tag_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('samples_1m',
  start_offset      => INTERVAL '1 hour',
  end_offset        => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute');

SELECT add_retention_policy('samples_1m', INTERVAL '1 month');  -- histórico >1 mês é não-objetivo (PRD §1)
```

### 3.4 Decisões [NOVA — implementação] desta seção
1. **CAgg com `min/max/count/worst_quality` além de `avg`** — ADR-003 diz "ex.: média por minuto"; média sozinha esconde picos no trend, e a pior qualidade do minuto é necessária para o tratamento `BAD` sem depender de cor (DESIGN.md, Regra do Canal Redundante).
2. **`samples.tag_id` sem FK** — FK em hypertable de alta escrita custa por insert e prende `DELETE` de tag a 1 mês de amostras; órfãos expiram pela retenção; JOIN metadado↔série (ADR-003) não exige FK.
3. **Watchdog como `node_id` direto na conexão** (não FK para `tags`) — bits de watchdog não são variáveis de processo: sem EU, fora de trends e do CRUD de tags; PRD §4 os lista como atributos da conexão.
4. **`quality` simplificada (0/1/2)** — o payload §7.1 propaga qualidade para invalidez a jusante (RF-501) e rótulo `BAD` (DESIGN.md); o StatusCode OPC bruto irá no evento de diagnóstico de mudança de qualidade (F2).
5. **Chunks:** 1 dia em `samples` (~9–17 M linhas/dia no teto do RNF-01), 7 dias em `events`. **Sem compressão** na v1 (30 dias ≈ 15–20 GB, aceitável on-prem; knob futuro sem impacto de schema).
6. **Senha de conexão como token Fernet em `TEXT`** (§5.4); nunca em export (ADR-012/021) nem em response (§6).

---

## 4. Migrations (Alembic)

- **Local:** `packages/ottima-core/alembic/` + `alembic.ini`; `env.py` async (asyncpg), `target_metadata` de `ottima_core.models`. Um único trilho para relacional + Timescale (decisão desta sessão). **[NOVA — implementação]**
- **Cadeia F1:**
  - `0001_relational` — `CREATE EXTENSION IF NOT EXISTS timescaledb;` + tabelas/índices do §3.1 (autogenerate revisado à mão).
  - `0002_timescale` — SQL cru (`op.execute`): hypertables, índices de hypertable, retention policies, CAgg + refresh policy. **Gotcha:** `CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)` não roda em transação ⇒ usar `op.get_context().autocommit_block()` nesse trecho.
- **Execução:** o entrypoint da api roda `alembic upgrade head` antes do uvicorn (§7); os testes rodam o mesmo `upgrade head` no container efêmero (§9). Migrations são a **única** fonte do schema — nenhum `create_all` fora do Alembic.
- **Evolução:** objetos Timescale mudam sempre por migration nova (incl. drop/recreate de CAgg quando necessário); nunca edição manual no banco (coerente com ADR-003: nada de manutenção manual).

---

## 5. Auth & RBAC

### 5.1 Login e token (RF-001, RNF-04, ADR-023)
- `POST /api/auth/login` — body JSON `{username, password}` → `200 {access_token, token_type: "bearer", expires_in, user: {id, username, name, role}}`. `401` com `detail` pt-BR; mensagem única para usuário inexistente/senha errada; `is_active=false` não loga.
- **JWT HS256** (PyJWT), segredo `OTTIMA_SECRET_KEY`; claims `sub` (user id), `username`, `role`, `iat`, `exp`.
- **Sessão: access token único**, TTL `OTTIMA_TOKEN_TTL_HOURS` (default **12 h** — cobre o turno da sala de controle, PRODUCT.md §Users). Sem refresh, sem revogação server-side; risco aceito coerente com a premissa HTTP interno (ADR-023). **[NOVA — implementação]** (decisão desta sessão)
- `GET /api/auth/me` → usuário atual (restauração de sessão na UI).
- **Hash Argon2id** via `pwdlib[argon2]` (PRD deixa "Argon2/bcrypt"; Argon2id é o recomendado atual; passlib está sem manutenção). Parâmetros default da lib. Senha mínima: 8 caracteres. **[NOVA — implementação]**

### 5.2 Autorização (RF-003, ADR-015)
- Dependências FastAPI: `get_current_user` (Bearer → decode → carrega user → exige `is_active`) → `require_operator` (admin **ou** operator; admin faz tudo — ADR-015) → `require_admin`.
- `401` sem token/token inválido/expirado; `403` papel insuficiente.
- **Toda rota** exceto `/api/auth/login` e `/api/health` exige token (RF-003). Na F1: GETs de engenharia (`/projects`, `/connections`, `/tags`) = `require_operator` ("enxerga tudo" — ADR-015); mutações = `require_admin`; **`/users` inteiro = `require_admin`** (gestão de usuários é exclusiva de admin — PRD §2).

### 5.3 Seed do primeiro admin **[NOVA — implementação]**
- No startup da api (após migrations): se `users` vazia, cria admin com `OTTIMA_ADMIN_USERNAME`/`OTTIMA_ADMIN_PASSWORD`/`OTTIMA_ADMIN_NAME`. Idempotente (só com tabela vazia). Vars ausentes + tabela vazia ⇒ log de erro claro, api sobe mesmo assim (instalador corrige `.env` e reinicia).
- O usuário operador do aceite F1 é criado pelo admin via `POST /api/users`.

### 5.4 Segredos de conexão OPC (ADR-021; decisão desta sessão)
- `ottima_core.security`: cifra/decifra **Fernet** com `OTTIMA_FERNET_KEY` (chave dedicada, distinta da JWT). **[NOVA — implementação]**
- API cifra ao gravar `auth_password_enc`; responses expõem apenas `has_password: bool`; opc-worker decifra em memória (F2). Perda da chave ⇒ re-informar senhas (mesmo modelo do import, ADR-012).
- Chaves privadas de certificado: **somente arquivos no volume `certs`**, nunca no banco (ADR-021).

### 5.5 Regras de usuário (RF-002)
- CRUD `/api/users` restrito a admin. Guardas: não desativar/rebaixar/excluir **a si próprio**; não remover/desativar o **último admin ativo**. **[NOVA — implementação]**
- `DELETE` físico permitido — auditoria em `events` usa `origin`/payload textuais, não FK; nada quebra (ADR-020).

---

## 6. API CRUD da F1

### 6.1 Padrões **[NOVA — implementação]**
- Prefixo **`/api`** (same-origin atrás do nginx, §7); **sem `/v1`** — uma única UI, produto on-prem.
- Erros no formato FastAPI `{detail}` com mensagens pt-BR (RNF-08); validação Pydantic v2 (422 padrão).
- **Sem paginação** na v1 (RNF-01: ~100 tags, ~10 flows, ≤5 conexões); ordenação server-side por `name`.
- OpenAPI habilitado — fonte dos tipos TS do frontend (§8).
- Schemas Pydantic em `ottima_core.schemas`, request/response separados; `ConnectionOut` jamais contém segredo.

### 6.2 Rotas

| Grupo | Rotas | Papel | Regras |
|---|---|---|---|
| `/api/users` | GET, POST, GET/{id}, PATCH/{id}, DELETE/{id} | admin | §5.5; `PATCH` cobre troca de senha e `is_active` (RF-002) |
| `/api/projects` | GET, POST, GET/{id}, PATCH/{id}, DELETE/{id} | GET: operator · resto: admin | RF-101. `DELETE` de projeto **ativo** ⇒ `409` (desativar antes; CASCADE remove conexões/tags/flows) **[NOVA — implementação]** |
| `/api/projects/{id}/activate` | POST | admin | Transação: desativa o atual, ativa o alvo; índice parcial (§3.1) garante unicidade (ADR-017). Na F1 apenas persiste; a partir da F3 encadeia o encerramento da execução do projeto anterior (RF-101) — gancho registrado |
| `/api/connections` | GET (`?project_id=`), POST, GET/{id}, PATCH/{id}, DELETE/{id} | GET: operator · resto: admin | RF-201. **≤5 por projeto** ⇒ `409`; senha write-only (§5.4); coerência policy/mode/auth no schema (§3.1) |
| `/api/tags` | GET (`?connection_id=&direction=`), POST, GET/{id}, PATCH/{id}, DELETE/{id} | GET: operator · resto: admin | RF-203; browse do address space fica na F2+ |
| `/api/health` | GET | público | `{status, service, version}` (RNF-07) |

### 6.3 Auditoria de CRUD **[NOVA — implementação]**
ADR-020 audita **operação** (escritas de processo, modos, deploy, ativação com efeito operacional). Na F1 o CRUD de engenharia **não grava** eventos — o publisher do canal `events` nasce na F2; a partir dela, ativação de projeto e mudanças de conexão (que passam a ter efeito operacional) geram evento.

---

## 7. Deploy: Compose, Dockerfiles e `.env.example`

### 7.1 `deploy/docker-compose.yml` — 7 serviços (ADR-023), rede única, `restart: unless-stopped`

| Serviço | Imagem/Build | Porta | depends_on (healthy) | Healthcheck |
|---|---|---|---|---|
| `timescaledb` | `timescale/timescaledb:2.17.2-pg17` (pin; plano pode elevar o patch) | interna | — | `pg_isready` |
| `redis` | `redis:7.4-alpine` | interna | — | `redis-cli ping` |
| `api` | `deploy/Dockerfile.python` (target api) | interna 8000 | timescaledb, redis | `GET /api/health` |
| `opc-worker` | idem (target opc-worker) | interna 8001 | redis, api | `GET /health` |
| `flow-runtime` | idem (target flow-runtime) | interna 8002 | redis, api | `GET /health` |
| `recorder` | idem (target recorder) | interna 8003 | timescaledb, redis, api | `GET /health` |
| `frontend` | `frontend/Dockerfile` (node build → `nginx:1.27-alpine`) | **`${OTTIMA_HTTP_PORT}:80` — única porta exposta** | api | `GET /` |

- **nginx** serve o build Vite e faz proxy `/api` → `api:8000` e `/ws` → `api:8000` (headers de upgrade prontos para F2+). Same-origin ⇒ sem CORS. HTTP puro (ADR-023). **[NOVA — implementação]** (forma; a existência do serviço frontend é ADR-023)
- **Entrypoint da api:** `alembic upgrade head` → seed admin (§5.3) → `uvicorn`. Workers dependem de `api: healthy` ⇒ schema garantido antes de subirem. **[NOVA — implementação]**
- **Workers na F1 = esqueleto:** app FastAPI mínimo com `/health` + task asyncio de ping no Redis. Heartbeat visível na UI é F2+ (RNF-07). Sobem verdes no `docker compose up` — exigência do aceite F1.
- **Volumes:** `pgdata` (Postgres) e `certs` (api RW; opc-worker RO) — RNF-06, ADR-021. **Redis sem volume** (pub/sub fire-and-forget, ADR-002).
- **`deploy/Dockerfile.python`** multi-stage único com `uv` (`ghcr.io/astral-sh/uv:python3.12-bookworm-slim` no build): `uv sync --frozen --no-dev --package <serviço>` por target; runtime slim, usuário não-root. **[NOVA — implementação]**
- Logs estruturados JSON com ts UTC em todos os serviços Python (RNF-07); TZ dos containers = UTC; conversão de fuso só na UI.

### 7.2 `deploy/.env.example`

```
# Porta HTTP única exposta (frontend/nginx)
OTTIMA_HTTP_PORT=80

# Banco (container timescaledb)
POSTGRES_DB=ottima
POSTGRES_USER=ottima
POSTGRES_PASSWORD=<troque>
OTTIMA_DATABASE_URL=postgresql+asyncpg://ottima:<senha>@timescaledb:5432/ottima

# Barramento (ADR-002)
OTTIMA_REDIS_URL=redis://redis:6379/0

# Segredos (gerar por instalação; nunca commitar .env real)
OTTIMA_SECRET_KEY=<openssl rand -hex 32>                       # JWT (§5.1)
OTTIMA_FERNET_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# Sessão (§5.1)
OTTIMA_TOKEN_TTL_HOURS=12

# Seed do primeiro admin (§5.3)
OTTIMA_ADMIN_USERNAME=admin
OTTIMA_ADMIN_PASSWORD=<troque>
OTTIMA_ADMIN_NAME=Administrador

OTTIMA_LOG_LEVEL=INFO
```

Comentários no arquivo real explicam como gerar cada segredo (RNF-04: segredos fora do repositório e fora do export).

---

## 8. Frontend: scaffold, tokens e tela de login

Autoridade: PRODUCT.md/DESIGN.md para UX/visual; ADRs para stack. Tooling do scaffold **[NOVA — implementação]**: Vite + React + **TS strict** · **Tailwind v4** (config CSS-first — tematização por CSS variables exigida pelo DESIGN.md §Do's) · shadcn/ui **re-vestido** (default proibido — DESIGN.md §Don'ts) · react-router · TanStack Query · tipos gerados do OpenAPI (`openapi-typescript`, script `generate:api`).

**Fontes self-hosted** via @fontsource (`archivo`, `archivo-narrow`, `spline-sans-mono`) — rede de planta sem internet (PRODUCT.md §Operating Context); CDN é proibitivo. **[NOVA — implementação]**

### 8.1 Tokens (resolve os `[a resolver]` do DESIGN.md dentro das faixas normativas)

```css
/* styles/tokens.css */
@theme {
  --color-field:    oklch(0.25 0.012 250);  /* Grafite Campo   (L 22–28, C ≤ 0.015)  */
  --color-panel:    oklch(0.29 0.012 250);  /* Chapa           (+1–2 passos)          */
  --color-well:     oklch(0.21 0.010 250);  /* Poço            (−1–2 passos)          */
  --color-hairline: oklch(0.38 0.010 250);  /* Linha 1px                              */
  --color-fg:       oklch(0.93 0.005 250);  /* Texto Primário  (~12:1 sobre chapa ✓≥7)*/
  --color-fg-muted: oklch(0.72 0.010 250);  /* Texto Secundário (~6:1 sobre chapa ✓≥4.5)*/
  --color-accent:   oklch(0.66 0.100 242);  /* Azul Industrial (L 62–70, C .08–.12, H 230–250) */
  --color-alarm:    oklch(0.60 0.190 27);   /* Vermelho Alarme — somente severidade   */
  --color-warn:     oklch(0.74 0.140 80);   /* Âmbar Advertência — somente severidade */
  --color-running:  oklch(0.60 0.090 150);  /* Verde Rodando — somente lâmpada        */
  --radius: 3px;                            /* bisel 2–4px; nunca pill (DESIGN §Shapes)*/
  --font-sans:  "Archivo";
  --font-label: "Archivo Narrow";
  --font-mono:  "Spline Sans Mono";
}
```

- Mapeamento shadcn: `--background`→field · `--card`/`--popover`→panel · `--primary`/`--ring`→accent · `--destructive`→alarm · `--border`/`--input`→hairline · `--foreground`→fg · `--muted-foreground`→fg-muted.
- Utilitários criados na F1 (assinaturas tipográficas normativas): `.plaqueta` (Archivo Narrow, caps, tracking +6%) — Regra da Plaqueta; `.process-value` (mono, `font-variant-numeric: tabular-nums`) — Regra do Número Tabular.
- Grid de espaçamento base 4px (DESIGN §Layout). Contrastes validados nos testes visuais da implementação.
- **Paleta de penas de trend → F2** (primeira tendência) — pendência registrada (§1.2).

### 8.2 Estrutura

```
frontend/src/
  app/            # main.tsx, router.tsx, providers (Query), AuthGuard, AppShell
  features/auth/  # LoginPage, useAuth (login/me/logout, storage do token)
  components/ui/  # shadcn re-vestidos: button, input, label, card, form
  lib/            # cliente fetch tipado (Bearer), types gerados do OpenAPI
  styles/         # tokens.css, fonts.css
```

### 8.3 Tela de login
Campo grafite; chapa central (canto 3px, linha 1px); wordmark **"OttimaSystem"** em Archivo SemiBold — papel Display, raro (DESIGN §Typography); logo ainda não existe (PRODUCT.md §Brand Commitments); rodapé discreto **"by LFR Automação"** (PRODUCT.md); labels-plaqueta nos campos; erro de credencial com **ícone + texto** em vermelho alarme (Regra do Canal Redundante); foco visível no azul único; strings 100% pt-BR (RNF-08).

### 8.4 Shell autenticado
- Header: produto, usuário logado, sair.
- **Faixa anunciadora** persistente no topo (DESIGN §Layout), na F1 colapsada em 1 linha "Sem alarmes ativos" — dados reais chegam com o canal `events`/WS (F5; ADR-020).
- Rota `/` protegida: mostra o **projeto ativo** (ou "nenhum projeto ativo") via `GET /api/projects` — 1 chamada read-only que valida login → token → cliente tipado → dado real; não é tela CRUD. **[NOVA — implementação]**
- `prefers-reduced-motion` respeitado desde o scaffold (DESIGN §Overview).

### 8.5 Sessão no cliente **[NOVA — implementação]**
Token em `localStorage` + header `Authorization: Bearer`; interceptor de `401` ⇒ logout + redirect `/login`; CSP básica no nginx mitiga XSS (risco residual aceito — premissa HTTP interno, ADR-023). Sem testes **unitários/componente** de frontend na F1 (type-check no build; chegam com a lógica de canvas na F3).

> **Emenda aprovada pelo usuário (2026-08-03, sessão de planos):** a F1 ganha testes **E2E de UI com Playwright** (`@playwright/test`, dev-dependency aprovada fora da stack original) rodando contra o stack composto. A bateria E2E completa — smoke, API e UI — está em `docs/specs/F1-testes-e2e.md` e é o **gate de conclusão da F1**. Esta emenda substitui a frase "sem testes de frontend" da versão original desta seção no que toca a E2E.

---

## 9. Infraestrutura de testes

- **Ferramentas:** `pytest` + `pytest-asyncio` (`asyncio_mode=auto`) + `httpx.AsyncClient` (ASGI, sem servidor) + **testcontainers-python** com a **mesma imagem pinada** do compose — paridade produção/teste (decisão desta sessão). **[NOVA — implementação]**
- **Fixtures (conftest compartilhado):**
  - `timescale_container` (sessão): sobe o container, roda `alembic upgrade head` — migrations validadas em toda execução.
  - `db_session` (função): conexão com transação externa + `AsyncSession` em SAVEPOINT; rollback ao final — isolamento por teste sem TRUNCATE.
  - `api_client` / `admin_client` / `operator_client`: app com override da dependência de sessão; clientes autenticados por papel.
- **Localização** (CLAUDE.md): unit/integração por pacote (`services/api/tests`, `packages/ottima-core/tests`); `tests/` na raiz reservado a cross-service (F4+; na F1 apenas README de propósito).
- **Cobertura F1** (integração de infra; sem teatro de TDD unitário — CLAUDE.md §Testes):
  1. **Schema/Timescale:** hypertables existem; retention policies de `samples`/`events`/`samples_1m` registradas com `INTERVAL '1 month'` (`timescaledb_information.jobs`) — evidência executável do aceite "retenção ativa"; CAgg agrega (insert → `refresh_continuous_aggregate` → confere avg/min/max/worst_quality); índice parcial rejeita 2º projeto ativo.
  2. **Auth:** login ok/erro/inativo; expiração; `require_admin` nega operador (403); rota sem token (401); seed idempotente.
  3. **CRUD:** projetos (ativação transacional; DELETE de ativo ⇒ 409), conexões (limite 5 ⇒ 409; senha cifrada no banco, ausente do response; roundtrip Fernet), tags (validações, filtros), users (regras §5.5).
- **`deploy/smoke.sh`** **[NOVA — implementação]**: `docker compose up -d` → aguarda healthchecks → `curl` nos 5 healths + login com o admin do seed. Roteiro executável do aceite "compose up sobe tudo" (manual/CI; não é pytest).
- **E2E (gate da fase — emenda 2026-08-03):** bateria definida em `docs/specs/F1-testes-e2e.md`, em 3 camadas: L1 stack (`deploy/smoke.sh`), L2 API (`pytest -m e2e` em `tests/e2e/`, contra o compose real), L3 UI (Playwright em `frontend/e2e/`). A F1 só é considerada concluída com a bateria verde.

---

## 10. Aderência ao aceite F1 (PRD §8)

| Critério | Evidência no spec |
|---|---|
| **Login admin/operador** | §5 (auth, seed, papéis) + §8.3 (tela de login); testes §9.2 |
| **Retenção ativa** | §3.2/§3.3 (policies 1 mês em `samples`, `events`, `samples_1m`); teste §9.1 consulta `timescaledb_information.jobs` |
| **`docker compose up` sobe tudo** | §7 (7 serviços, healthchecks, migrations no entrypoint, workers-esqueleto); `smoke.sh` §9 |
| Entrega: schema + hypertables/retenção | §3 completo (incl. `flows` para a F3) |
| Entrega: auth/RBAC | §5 |
| Entrega: CRUD projetos/conexões/tags | §6 (backend); telas → F2/F3 (decisão §1.2) |
| Entrega: Compose | §7 + `.env.example` |

---

## Anexo A — Decisões do brainstorm (2026-08-03)

| # | Lacuna | Decisão aprovada |
|---|---|---|
| 1 | Escopo F1 | Backend CRUD completo; frontend só shell + login; telas CRUD → F2+ |
| 2 | Migrations | Alembic único em `ottima-core`; objetos Timescale em SQL cru (`0002`, autocommit p/ CAgg) |
| 3 | Sessão JWT | Access token único, TTL 12 h configurável; sem refresh/revogação |
| 4 | Segredos OPC | Fernet com `OTTIMA_FERNET_KEY` dedicada; chaves de certificado só no volume `certs` |
| 5 | Compose | nginx same-origin; workers-esqueleto com `/health`; migrations no entrypoint da api |
| 6 | Frontend | Tailwind v4; @fontsource; react-router; TanStack Query; tipos via OpenAPI |
| 7 | Testes de DB | testcontainers-python + rollback transacional por teste |
