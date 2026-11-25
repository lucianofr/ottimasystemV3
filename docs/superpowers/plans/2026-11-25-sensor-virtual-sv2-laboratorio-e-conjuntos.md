# Sensor virtual SV-2 (laboratório e conjuntos) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir cadastrar variáveis de laboratório, lançar análises por digitação e por CSV, abrir um período de coleta e congelar um conjunto de treino emparelhado, por um serviço novo `ml-worker` que executa jobs em processo filho, com a página "Coleta e treino" (ainda sem treino).

**Arquitetura:** Quatro tabelas comuns no Postgres (`lab_variables`, `lab_samples`, `soft_sensor_datasets`, `ml_jobs`). A API só grava linhas e enfileira; o `ml-worker` consome `ml_jobs` um por vez, roda o handler num processo filho (`spawn`), recebe progresso por `Pipe` e mata o filho para cancelar. O congelamento do conjunto reusa a função de grade da SV-1 (`load_grid`). A página consulta por REST e faz polling só enquanto há job ativo.

**Tech Stack:** Python 3.12, numpy, Pydantic v2, SQLAlchemy 2.0 async, Alembic, FastAPI, `multiprocessing` (spawn), pytest · TypeScript strict, React, TanStack Query, uPlot (`TrendChart`).

**Spec:** `docs/specs/SPEC_SENSOR_VIRTUAL.md` §7.1, §7.2, §7.3, §7.5, §8.3 (página Coleta e treino, sem treino), §8.4, §9 (variáveis de laboratório no bundle), §10. **Pré-requisito:** SV-1 mergeada (`docs/superpowers/plans/2026-11-25-sensor-virtual-sv1-nucleo-e-blocos.md`).

## Global Constraints

- Identificadores em **inglês**; UI, mensagens e docs em **pt-BR**. Sem emojis. Conventional Commits em pt-BR com caminhos explícitos; **nunca `git add -A`**.
- **Nenhuma dependência nova.** O `ml-worker` desta entrega depende só de `ottima-core`, `fastapi`, `uvicorn` e `numpy`. Upload de CSV é **corpo bruto** (`text/csv`), nunca multipart: `python-multipart` não entra (mesma decisão registrada em `routers/connections.py`).
- O `ml-worker` **não usa Redis** e não recebe o `.env` inteiro: só `OTTIMA_DATABASE_URL`, `OTTIMA_LOG_LEVEL` e `OTTIMA_ML_THREADS` (RNF-04/ADR-018).
- Constantes da spec: `PERIODS_S = (1, 2, 5, 10, 30, 60, 300, 600)`, `DATASET_STEPS = 256`, `MAX_LAB_CSV_BYTES = 5 * 1024 * 1024`, `JOB_POLL_INTERVAL_S = 2.0`, porta de health **8005**, `OTTIMA_HEALTH_URL_ML_WORKER` com default `http://ml-worker:8005/health`. Chamada deste plano: `MAX_DATASET_BYTES = 64 * 1024 * 1024`.
- Análise de laboratório guarda o instante da **coleta da amostra** (`sampled_at`), nunca o da digitação. Data futura é recusada.
- Tabelas novas são **comuns**: não são hypertables e não entram em policy de retenção.
- Projeto ativo é `select(Project.id).where(Project.is_active)`; sem projeto ativo, listas devolvem `[]` e escritas devolvem 409 `"Nenhum projeto ativo"`.
- Evento de auditoria da API sai **depois** do commit, com `origin = f"user:{user.id}"` (padrão de `routers/calculated_tags.py:119-130`).
- **Sem modal novo** (regra FE-08 do projeto): formulários e confirmações são inline. Não existe componente de tabela nem de barra de progresso: use `<table>` cru no padrão de `ConnectionsPage` e `<progress>` nativo.
- `schema_version` do bundle continua 1. TDD estrito em lógica pura.

## Disciplina de worktree

Worktree **`/home/luciano/Documentos/ProjetosClaudeCode/ottimaSystemV3/.worktrees/sensor-virtual-sv2`**, branch `feat/sensor-virtual-sv2`, criada a partir da `main` **depois** do merge da SV-1. Valem as quatro regras do plano da SV-1 (caminho absoluto, `cwd` explícito, confirmação por shell, `git status --porcelain` vazio no checkout principal).

## Review Focus

1. **`ml-worker` reiniciado no meio de um job.** O job fica `running` para sempre e o conjunto fica `building` para sempre. Espera-se job `failed` com "interrompido pelo reinício do serviço" e conjunto `failed`. → Task 5, `test_job_orfao_vira_failed_na_partida`.
2. **CSV salvo pelo Excel brasileiro**: BOM UTF-8, vírgula decimal, `dd/mm/aaaa hh:mm`, aspas em todos os campos, linha em branco no fim. Espera-se importar. → Task 2, `test_csv_do_excel_brasileiro`.
3. **Mesma análise lançada duas vezes** (digitada e depois no CSV, mesmo instante). Espera-se uma linha só, com o valor mais recente, e reimportar o mesmo arquivo não mudar nada. → Task 3, `test_reimportar_o_mesmo_csv_e_idempotente`.
4. **Finalizar um conjunto sem nenhuma análise no período.** Espera-se conjunto `ready` com `paired = 0` e a página dizendo isso, não job `failed` com traceback. → Task 4, `test_sem_analises_devolve_conjunto_vazio`, e Task 5, `test_conjunto_sem_analises_fica_ready_vazio`.
5. **Cancelar um job que já terminou**, ou cancelar duas vezes. Espera-se resposta idempotente e o estado final preservado (`done` continua `done`). → Task 6, `test_cancelar_job_terminado_nao_muda_o_estado`.

---

## File Structure

**Criados**
- `packages/ottima-core/src/ottima_core/models/lab.py` — `LabVariable`, `LabSample`.
- `packages/ottima-core/src/ottima_core/models/soft_sensor_dataset.py` — `SoftSensorDataset`.
- `packages/ottima-core/src/ottima_core/models/ml_job.py` — `MlJob`.
- `packages/ottima-core/alembic/versions/0019_soft_sensor_lab_and_jobs.py`.
- `packages/ottima-core/src/ottima_core/softsensor/dataset.py` — empacotamento do conjunto e `build_dataset`.
- `services/api/src/ottima_api/lab_csv.py` — parser puro do CSV.
- `services/api/src/ottima_api/routers/softsensor_lab.py` — variáveis, análises, conjuntos, jobs.
- `services/ml-worker/pyproject.toml`, `services/ml-worker/src/ottima_ml_worker/{__init__,main,jobs,runner,handlers}.py`, `services/ml-worker/tests/test_{health,jobs,runner,dataset_build}.py`.
- `frontend/src/features/softsensor/` — `ColetaTreinoPage.tsx`, `useSoftSensorBlocks.ts`, `useLabVariables.ts`, `useLabSamples.ts`, `useDatasets.ts`, `useJobs.ts`, `coleta.ts`, `coleta.check.ts`, `types.ts`.
- Testes: `services/api/tests/test_lab_csv.py`, `test_softsensor_lab.py`, `test_softsensor_datasets.py`; `services/flow-runtime/tests/test_soft_sensor_dataset.py`; `tests/e2e/test_sv2_laboratorio.py`.

**Modificados**
- `packages/ottima-core/src/ottima_core/models/__init__.py`, `config.py` (`health_url_ml_worker`, `ml_threads`), `bus.py` (kinds de auditoria), `portability/schemas.py`, `portability/bundle.py`.
- `services/api/src/ottima_api/app.py`, `routers/health.py`, `routers/projects.py`.
- Raiz: `pyproject.toml` (`known-first-party`), `uv.lock`.
- `deploy/docker-compose.yml`, `deploy/docker-compose.e2e.yml` (comentário de contagem), `deploy/.env.example`, `deploy/smoke.sh`.
- `frontend/src/app/AppShell.tsx`, `router.tsx`, `appShell.check.ts`, `useWorkersHealth.ts`, `useWorkersHealth.check.ts`.
- `docs/PRD.md` (vocabulário de `kind` de auditoria), `CLAUDE.md`.

---

### Task 1: Tabelas (RF-585, RF-586, ADR-046 D1/D7)

**Files:**
- Create: os três arquivos de modelo e a migration `0019` (`down_revision = "0018_soft_sensor"`)
- Modify: `packages/ottima-core/src/ottima_core/models/__init__.py`
- Test: `services/api/tests/test_soft_sensor_lab_models.py` (fixture `db_session`)

**Interfaces — Produces:**
- `LabVariable` (`lab_variables`, `TimestampMixin`): `id` identity PK; `project_id` → `projects.id` `ON DELETE CASCADE`; `name` Text; `eu` Text default `''`; `description` Text default `''`. `UNIQUE(project_id, name)`.
- `LabSample` (`lab_samples`): PK `(lab_variable_id, sampled_at)`; `lab_variable_id` → `lab_variables.id` `ON DELETE CASCADE`; `sampled_at` timestamptz; `value` Double não nulo; `source` Text check `IN ('manual','csv')`; `created_by` Text; `created_at` default `now()`.
- `SoftSensorDataset` (`soft_sensor_datasets`, `TimestampMixin`): `id`; `project_id` cascade; `name` Text, `UNIQUE(project_id, name)`; `lab_variable_id` → `lab_variables.id` **sem `ON DELETE`** (variável usada por conjunto não pode ser apagada); `input_tag_ids` `ARRAY(BigInteger)`; `period_s` Double com check `IN (1,2,5,10,30,60,300,600)`; `start_ts` timestamptz; `end_ts` timestamptz nulo; `status` Text check `IN ('collecting','building','ready','failed')` default `'collecting'`; `stats` JSONB default `{}`; `inputs_meta` JSONB default `[]`; `data` LargeBinary nulo, mapeado com **`deferred=True`**; `created_by` Text. (`data` chega a 64 MiB e as listagens são consultadas por polling: quem precisa do conteúdo pede com `undefer(SoftSensorDataset.data)`.)
- `MlJob` (`ml_jobs`): `id`; `project_id` cascade; `kind` Text check `IN ('dataset_build','train','tune')`; `status` Text check `IN ('queued','running','done','failed','cancelled')` default `'queued'`; `params` JSONB; `progress` JSONB default `{}`; `result` JSONB nulo; `error` Text nulo; `cancel_requested` Boolean default false; `created_by` Text; `created_at` default `now()`; `started_at`, `finished_at` nulos. Índice `ix_ml_jobs_status_id (status, id)`.

- [ ] **Step 1: Testes que falham**

```python
async def test_nome_de_variavel_unico_por_projeto(db_session): ...
async def test_mesma_variavel_e_instante_e_uma_linha_so(db_session): ...        # segundo insert -> IntegrityError
async def test_variavel_usada_por_conjunto_nao_pode_ser_apagada(db_session): ...
async def test_apagar_projeto_apaga_variaveis_analises_conjuntos_e_jobs(db_session): ...
async def test_periodo_fora_da_lista_e_recusado(db_session): ...               # period_s=3
async def test_status_e_kind_fora_do_vocabulario_sao_recusados(db_session): ...
async def test_select_do_conjunto_nao_carrega_data(db_session):
    # select(SoftSensorDataset) -> "data" em sqlalchemy.inspect(obj).unloaded
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest services/api/tests/test_soft_sensor_lab_models.py -q` → FAIL.
- [ ] **Step 3: Implementar** modelos e migration (molde de tabela comum com FK: `0012_calculated_tags.py`).
- [ ] **Step 4: Rodar e ver passar** — mesmo comando → PASS.
- [ ] **Step 5: Commit** — `git add` dos cinco arquivos; `feat(db): tabelas de laboratório, conjunto de treino e jobs`.

---

### Task 2: Parser do CSV de análises (RF-585)

**Files:**
- Create: `services/api/src/ottima_api/lab_csv.py`
- Test: `services/api/tests/test_lab_csv.py`

**Interfaces — Produces:**
- `MAX_LAB_CSV_BYTES = 5 * 1024 * 1024`, `MAX_PROBLEMS = 50`.
- `@dataclass(frozen=True) class LabCsvRow`: `variable_id: int`, `sampled_at: datetime` (UTC aware), `value: float`.
- `class LabCsvError(ValueError)`: atributo `problems: list[str]`.
- `def parse_lab_csv(data: bytes, *, tz: str, known: Mapping[str, int], now: datetime) -> list[LabCsvRow]`.

Regras (spec §7.2): decodifica `utf-8-sig`; `csv.reader(delimiter=";")`; linha vazia é ignorada; a primeira linha não vazia é cabeçalho se a terceira coluna não vira número; cada linha tem exatamente 3 colunas; data em `dd/mm/aaaa hh:mm` ou `dd/mm/aaaa hh:mm:ss` (interpretada no fuso `tz`, via `zoneinfo`) ou ISO-8601 (se trouxer offset, ele vale; senão `tz`); valor com vírgula ou ponto decimal, finito. Problemas: nome fora de `known`, colunas em número errado, data ilegível, data posterior a `now`, valor ilegível ou não finito, fuso inválido. **Qualquer problema recusa o arquivo inteiro**: levanta `LabCsvError` com até 50 mensagens no formato `"linha <n>: <motivo>"`. Mesma variável e mesmo instante repetidos no arquivo: vale a última ocorrência.

- [ ] **Step 1: Testes que falham**

```python
CONHECIDAS = {"ENXOFRE": 1, "VISC": 2}
AGORA = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)
def p(texto, tz="America/Sao_Paulo"):
    return parse_lab_csv(texto.encode(), tz=tz, known=CONHECIDAS, now=AGORA)

def test_linha_simples():
    [r] = p('"ENXOFRE";"25/11/2026 08:30";"12,5"')
    assert r == LabCsvRow(1, datetime(2026, 11, 25, 11, 30, tzinfo=UTC), 12.5)
def test_csv_do_excel_brasileiro():
    bruto = "﻿" + '"nome do TAG";"data/hora";"valor"\r\n"ENXOFRE";"25/11/2026 08:30";"12,5"\r\n\r\n'
    assert len(parse_lab_csv(bruto.encode("utf-8"), tz="America/Sao_Paulo", known=CONHECIDAS, now=AGORA)) == 1
def test_iso_com_offset_ignora_o_tz_do_navegador(): ...       # 2026-11-25T08:30:00+00:00 -> 08:30 UTC
def test_ponto_decimal_e_segundos(): ...                      # 12.5 e hh:mm:ss
def test_sem_cabecalho_tambem_importa(): ...
def test_varias_variaveis_no_mesmo_arquivo(): ...
def test_repetida_no_arquivo_vale_a_ultima(): ...
def test_nome_desconhecido_recusa_o_arquivo_inteiro():
    with pytest.raises(LabCsvError) as e:
        p('"ENXOFRE";"25/11/2026 08:30";"1"\n"OUTRA";"25/11/2026 08:30";"2"')
    assert e.value.problems == ["linha 2: variável de laboratório 'OUTRA' não existe no projeto ativo"]
def test_data_futura_e_recusada(): ...                        # 25/11/2026 13:00 em São Paulo = 16:00 UTC > AGORA
def test_valor_nao_numerico_e_nan_sao_recusados(): ...
def test_numero_de_colunas_errado(): ...
def test_fuso_invalido(): ...                                 # tz="Marte/Olympus"
def test_lista_no_maximo_50_problemas(): ...
def test_arquivo_vazio_devolve_lista_vazia(): ...
```

- [ ] **Step 2: Rodar e ver falhar** → FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implementar `lab_csv.py`** (só biblioteca padrão: `csv`, `zoneinfo`, `datetime`).
- [ ] **Step 4: Rodar e ver passar** — `uv run pytest services/api/tests/test_lab_csv.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(api): parser do CSV de análises de laboratório`.

---

### Task 3: API de variáveis de laboratório e análises (RF-585)

**Files:**
- Create: `services/api/src/ottima_api/routers/softsensor_lab.py`
- Modify: `services/api/src/ottima_api/app.py` (`include_router(softsensor_lab.router, prefix="/api/softsensor", ...)`), `packages/ottima-core/src/ottima_core/bus.py`
- Test: `services/api/tests/test_softsensor_lab.py`

**Interfaces — Produces** (todas sob `/api/softsensor`):

| Rota | Papel | Corpo / resposta |
|---|---|---|
| `GET /lab-variables` | operador | `[{id, name, eu, description, sample_count, last_sampled_at}]` do projeto ativo |
| `POST /lab-variables` | admin | `{name, eu?, description?}` → 201; nome repetido → 409 `"Já existe uma variável de laboratório com esse nome"` |
| `PATCH /lab-variables/{id}` | admin | campos opcionais |
| `DELETE /lab-variables/{id}` | admin | 204; usada por conjunto → 409 `"Variável usada pelo conjunto '<nome>'"` |
| `GET /lab-variables/{id}/samples?start=&end=` | operador | `[{sampled_at, value, source}]`, ordem crescente, teto de 5000 |
| `POST /lab-variables/{id}/samples` | operador | `{value, sampled_at}` → 201; grava ou substitui |
| `DELETE /lab-variables/{id}/samples?sampled_at=<ISO>` | operador | 204; inexistente → 404 |
| `POST /lab-samples/import?tz=<IANA>` | operador | corpo `text/csv` bruto → `{imported: int, by_variable: {name: int}}` |

- `name` é aparado e não pode ser vazio nem conter `;` ou aspas (viraria ambíguo no CSV): 422 `"Nome não pode conter ';' nem aspas"`.
- Análise digitada: `value` finito; `sampled_at` com fuso (ISO com offset) e não posterior a agora: 422 `"A data da coleta não pode estar no futuro"`.
- Import: lê o corpo em stream com teto `MAX_LAB_CSV_BYTES` → 413 `"Arquivo excede o limite de 5 MiB."` (molde: `_ler_corpo_import`, `routers/projects.py:335-350`); `LabCsvError` → 422 com as mensagens unidas por `"; "`; grava tudo numa transação com `INSERT ... ON CONFLICT (lab_variable_id, sampled_at) DO UPDATE SET value, source='csv', created_by, created_at`.
- Kinds novos em `bus.py` (auditoria, severidade info): `KIND_LAB_VARIABLE_CREATED = "lab_variable_created"`, `..._UPDATED`, `..._DELETED`, `KIND_LAB_SAMPLE_ADDED = "lab_sample_added"`, `KIND_LAB_SAMPLE_DELETED = "lab_sample_deleted"`, `KIND_LAB_SAMPLES_IMPORTED = "lab_samples_imported"` (payload `{project_id, imported, by_variable}`).

- [ ] **Step 1: Testes que falham**

```python
async def test_crud_de_variavel_exige_admin_e_lista_serve_operador(client, admin_headers, operator_headers): ...
async def test_nome_repetido_e_409(client, admin_headers): ...
async def test_nome_com_ponto_e_virgula_e_422(client, admin_headers): ...
async def test_operador_lanca_e_apaga_analise(client, operator_headers): ...
async def test_analise_no_futuro_e_422(client, operator_headers): ...
async def test_lancar_no_mesmo_instante_substitui(client, operator_headers): ...
async def test_import_grava_e_devolve_contagem_por_variavel(client, operator_headers): ...
async def test_reimportar_o_mesmo_csv_e_idempotente(client, operator_headers, db_session): ...   # contagem de linhas igual
async def test_import_recusado_nao_grava_nada(client, operator_headers, db_session): ...        # 422 e 0 linhas
async def test_import_acima_de_5_mib_e_413(client, operator_headers): ...
async def test_variavel_de_outro_projeto_e_404(client, operator_headers): ...
async def test_sem_projeto_ativo_lista_vazia_e_escrita_409(client, admin_headers): ...
async def test_eventos_de_auditoria_saem_depois_do_commit(client, admin_headers, eventos): ...
```

- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar.** A rota de import documenta o corpo com `openapi_extra` como `import_project` faz.
- [ ] **Step 4: Rodar e ver passar** — `uv run pytest services/api/tests/test_softsensor_lab.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(api): variáveis de laboratório, análises e importação de CSV`.

---

### Task 4: Congelamento do conjunto (RF-586)

**Files:**
- Create: `packages/ottima-core/src/ottima_core/softsensor/dataset.py`
- Test: `services/flow-runtime/tests/test_soft_sensor_dataset.py` (usa `session_factory`, como `test_soft_sensor_grid.py` da SV-1)

**Interfaces:**
- Consumes: `load_grid`, `staleness_limit_s` (SV-1 Task 6); `Quality`.
- Produces (exportados de `ottima_core.softsensor`):
  - `PERIODS_S`, `DATASET_STEPS = 256`, `MAX_DATASET_BYTES = 64 * 1024 * 1024`.
  - `class DatasetError(ValueError)`.
  - `def pack_dataset(x: np.ndarray, y: np.ndarray, ts: np.ndarray) -> bytes` — `x` `float32` `[n, 256, d]` (lacuna = `nan`), `y` `float64` `[n]`, `ts` `float64` `[n]` em segundos de época UTC; levanta `DatasetError` acima do teto.
  - `def unpack_dataset(blob: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]` — `allow_pickle=False`.
  - `async def build_dataset(session: AsyncSession, *, tag_ids: Sequence[int], period_s: float, analyses: Sequence[tuple[datetime, float]], report: Callable[[int, int], None] | None = None) -> tuple[bytes, dict[str, int]]`.

Regra de `build_dataset` (spec §7.3): para cada análise, em ordem de `sampled_at`, `load_grid(session, tag_ids, end=sampled_at, period_s=period_s, steps=256)`. Cada célula da matriz só vale se a linha da grade for **GOOD**; linha UNCERTAIN ou BAD vira `nan` na linha inteira. Análise cuja **última** linha é `nan` é descartada. `stats = {"analyses": total, "dropped_no_process": d, "paired": total - d, "full_window": f}`, onde `full_window` conta as análises mantidas sem nenhum `nan`. `report(i, total)` é chamado a cada análise processada. Zero análises devolve arrays vazios com a forma certa (`[0, 256, d]`) e `stats` zerado.

- [ ] **Step 1: Testes que falham**

```python
def test_pack_unpack_preserva_forma_nan_e_tipos(): ...
def test_pack_recusa_acima_do_teto(): ...
async def test_janela_termina_no_instante_da_coleta(session): ...            # x[0, -1, 0] é a amostra em/antes de sampled_at
async def test_amostra_posterior_a_coleta_nunca_entra(session): ...
async def test_analise_sem_processo_no_instante_e_descartada(session): ...   # stats dropped_no_process == 1
async def test_lacuna_no_meio_da_janela_mantem_a_analise_com_nan(session): ...  # paired 1, full_window 0
async def test_linha_uncertain_vira_lacuna(session): ...
async def test_janela_busca_dado_anterior_ao_inicio_do_periodo(session): ...
async def test_ordem_das_colunas_segue_tag_ids(session): ...
async def test_sem_analises_devolve_conjunto_vazio(session):
    blob, stats = await build_dataset(session, tag_ids=[t1], period_s=1, analyses=[])
    x, y, ts = unpack_dataset(blob)
    assert x.shape == (0, 256, 1) and stats == {"analyses": 0, "dropped_no_process": 0, "paired": 0, "full_window": 0}
async def test_report_e_chamado_por_analise(session): ...
```

- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar `dataset.py`.**
- [ ] **Step 4: Rodar e ver passar** — `uv run pytest services/flow-runtime/tests/test_soft_sensor_dataset.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(softsensor): congelamento do conjunto de treino por janela contínua`.

---

### Task 5: Serviço `ml-worker` — fila, processo filho e `dataset_build` (ADR-046 D1/D2)

**Files:**
- Create: `services/ml-worker/pyproject.toml` (molde: `services/calc-worker/pyproject.toml`; nome `ottima-ml-worker`, pacote `src/ottima_ml_worker`, deps `ottima-core`, `fastapi>=0.115`, `uvicorn[standard]>=0.32`, `numpy>=2.5`)
- Create: `services/ml-worker/src/ottima_ml_worker/{__init__,main,jobs,runner,handlers}.py`
- Modify: raiz `pyproject.toml` (`known-first-party` ganha `"ottima_ml_worker"`), `uv.lock` (`uv lock`), `packages/ottima-core/src/ottima_core/config.py` (`ml_threads: int = 2`)
- Test: `services/ml-worker/tests/test_health.py`, `test_jobs.py`, `test_runner.py`, `test_dataset_build.py`

**Interfaces — Produces:**
- `jobs.py`:
  - `async def claim_next(session_factory) -> ClaimedJob | None` — `SELECT ... WHERE status='queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED`, marca `running` e `started_at`, commit. `ClaimedJob(id: int, kind: str, params: dict)`.
  - `async def write_progress(session_factory, job_id: int, progress: dict) -> None`.
  - `async def finish(session_factory, job_id: int, *, status: Literal["done","failed","cancelled"], result: dict | None = None, error: str | None = None) -> None` — grava `finished_at`; para `kind == 'dataset_build'` com status diferente de `done`, também `UPDATE soft_sensor_datasets SET status='failed' WHERE id = params.dataset_id AND status='building'`.
  - `async def fail_orphans(session_factory) -> int` — todo job `running` vira `failed` com `error = "interrompido pelo reinício do serviço"` (com o mesmo efeito sobre o conjunto).
  - `async def cancel_requested(session_factory, job_id: int) -> bool`.
- `handlers.py`:
  - `@dataclass class JobContext`: `job_id: int`, `params: dict`, `session_factory`, `report: Callable[[dict], None]`.
  - `HANDLERS: dict[str, Callable[[JobContext], Awaitable[dict]]]` — nesta entrega só `"dataset_build"`. A SV-3 acrescenta `"train"` e `"tune"`.
- `runner.py`:
  - `async def run_job(session_factory, job: ClaimedJob, *, database_url: str, poll_s: float = 0.5) -> None` — sobe o filho com `multiprocessing.get_context("spawn")`, lê mensagens do `Pipe` (`("progress", dict)`, `("done", dict)`, `("error", str)`), grava progresso no máximo uma vez por segundo, consulta `cancel_requested` a cada `poll_s` e, se ligado, `proc.kill()` e `finish(status="cancelled")`. Filho que sai sem mandar `done` nem `error` → `failed` com `"processo terminou sem resultado (código <n>)"`.
  - `def child_main(kind: str, job_id: int, params: dict, database_url: str, conn: Connection) -> None` — função de módulo (exigência do `spawn`); cria o próprio engine, chama `asyncio.run(HANDLERS[kind](ctx))`; exceção vira `("error", str(exc))`.
- `main.py`: `SERVICE_NAME = "ml-worker"`; `lifespan` cria engine/`session_factory`, chama `fail_orphans`, inicia o laço (`claim_next` a cada `JOB_POLL_INTERVAL_S = 2.0`, um `run_job` por vez) e o heartbeat de banco; `GET /health` sempre 200 com `{"status": "ok"|"degraded", "service": "ml-worker", "version", "job": {"running_id": int | None, "queued": int}}` (`ok` quando o banco responde). Sem Redis.
- Handler `dataset_build`, `params = {"dataset_id": int}`: carrega o conjunto (precisa estar `building`), lê as análises da variável com `start_ts <= sampled_at <= end_ts`, chama `build_dataset` com `report` traduzido para `{"done": i, "total": n}`, grava `data`, `stats`, `inputs_meta` (`[{tag_id, name, eu}]` na ordem de `input_tag_ids`) e `status = 'ready'`; devolve `stats`. Tag de entrada inexistente → levanta com `"Tag de entrada <id> não existe mais no projeto"`.

- [ ] **Step 1: Testes que falham**

```python
# test_jobs.py (fixture própria `session_factory` com TRUNCATE, molde: services/calc-worker/tests/test_supervisor.py:32-52)
async def test_claim_pega_o_mais_antigo_e_marca_running(session_factory): ...
async def test_claim_sem_fila_devolve_none(session_factory): ...
async def test_dois_claims_concorrentes_nao_pegam_o_mesmo_job(session_factory): ...
async def test_job_orfao_vira_failed_na_partida(session_factory):
    # job running + conjunto building -> fail_orphans() == 1; job failed com a mensagem; conjunto failed
async def test_finish_de_dataset_build_que_falha_marca_o_conjunto(session_factory): ...

# test_runner.py (handlers de teste registrados por monkeypatch em HANDLERS, definidos em nível de módulo)
async def test_job_que_termina_grava_done_e_result(session_factory): ...
async def test_progresso_chega_ao_banco(session_factory): ...
async def test_excecao_no_handler_vira_failed_com_a_mensagem(session_factory): ...
async def test_cancelamento_mata_o_filho_e_grava_cancelled(session_factory):
    # handler que dorme 60 s; liga cancel_requested; run_job retorna em menos de 3 s; status cancelled
async def test_filho_que_morre_sem_resultado_vira_failed(session_factory): ...     # handler que chama os._exit(3)

# test_dataset_build.py
async def test_conjunto_building_vira_ready_com_stats(session_factory): ...
async def test_conjunto_sem_analises_fica_ready_vazio(session_factory): ...
async def test_tag_de_entrada_apagada_falha_com_mensagem(session_factory): ...

# test_health.py (stubs, molde: services/calc-worker/tests/test_health.py)
async def test_health_ok_e_degraded(): ...
```

O `spawn` reimporta o módulo no filho: o `monkeypatch` do pai não chega lá. Para os testes do runner, passe o handler de teste por um nome de `kind` registrado num módulo de teste importável (`services/ml-worker/tests/handlers_de_teste.py`) e faça `child_main` resolver `HANDLERS` depois de importar o módulo indicado pela variável de ambiente `OTTIMA_ML_EXTRA_HANDLERS` (se definida). Em produção ela não é definida.

- [ ] **Step 2: Rodar e ver falhar** — `uv lock && uv sync --all-packages && uv run pytest services/ml-worker -q` → FAIL.
- [ ] **Step 3: Implementar** os cinco módulos.
- [ ] **Step 4: Rodar e ver passar** — `uv run pytest services/ml-worker -q` → PASS; `uv run ruff check services/ml-worker` limpo.
- [ ] **Step 5: Commit** — `git add services/ml-worker pyproject.toml uv.lock packages/ottima-core/src/ottima_core/config.py`; `feat(ml-worker): serviço de jobs com processo filho e congelamento de conjunto`.

---

### Task 6: API de conjuntos e jobs (RF-586)

**Files:**
- Modify: `services/api/src/ottima_api/routers/softsensor_lab.py`, `packages/ottima-core/src/ottima_core/bus.py`
- Test: `services/api/tests/test_softsensor_datasets.py`

**Interfaces — Produces:**

| Rota | Papel | Corpo / resposta |
|---|---|---|
| `GET /datasets` | operador | `[{id, name, lab_variable_id, lab_variable_name, input_tag_ids, inputs_meta, period_s, start_ts, end_ts, status, stats}]` (nunca `data`) |
| `POST /datasets` | admin | `{name, lab_variable_id, input_tag_ids, period_s, start_ts}` → 201 `{...conjunto, warnings: [str]}` |
| `POST /datasets/{id}/finalize` | admin | → 202 `{job_id}` |
| `DELETE /datasets/{id}` | admin | 204; `building` → 409 `"Conjunto em montagem; cancele o job antes"` |
| `GET /jobs?active=true|false` | operador | `[{id, kind, status, params, progress, result, error, created_at, started_at, finished_at}]` do projeto ativo, mais novos primeiro, teto 100 |
| `GET /jobs/{id}` | operador | um job |
| `POST /jobs/{id}/cancel` | admin | 202; liga `cancel_requested` só se o job estiver `queued` ou `running`; `queued` vira `cancelled` na hora |

Validações de `POST /datasets` (422): `input_tag_ids` com 1 a 32 ids, sem repetição, todos de tags do projeto ativo (`"Tag(s) de entrada inexistente(s) ou de outro projeto: ..."`); `period_s` em `PERIODS_S`; `start_ts` com fuso e não futuro; variável de laboratório do projeto ativo; nome repetido → 409. `warnings` traz `"O início é anterior à retenção do histórico (<n> dias): parte do período não terá dado de processo"` quando `start_ts < agora - retention_days` (`HistoryRetentionSettings`).

`finalize`: de `collecting`, ou de `failed` (nova tentativa: mantém o `end_ts` já gravado, para o período não mudar); de `building` ou `ready` → 409 `"Conjunto já finalizado"`. Grava `end_ts = agora` (só vindo de `collecting`), `status = 'building'` e insere `MlJob(kind='dataset_build', params={"dataset_id": id})` na mesma transação.

`cancel` de job **na fila**: a API marca `cancelled` ela mesma, então o efeito colateral de `jobs.finish` no `ml-worker` nunca roda. Por isso a própria rota, na mesma transação, faz para `kind == 'dataset_build'`: `UPDATE soft_sensor_datasets SET status='failed' WHERE id = params.dataset_id AND status='building'`. Sem isso o conjunto ficaria `building` para sempre e nem poderia ser apagado. Kinds de auditoria: `soft_sensor_dataset_created`, `soft_sensor_dataset_finalized`, `soft_sensor_dataset_deleted`.

- [ ] **Step 1: Testes que falham**

```python
async def test_criar_conjunto_valida_entradas_periodo_e_variavel(client, admin_headers): ...   # parametrizado por defeito
async def test_inicio_anterior_a_retencao_devolve_aviso(client, admin_headers): ...
async def test_finalizar_enfileira_dataset_build_e_marca_building(client, admin_headers, db_session): ...
async def test_finalizar_duas_vezes_e_409(client, admin_headers): ...
async def test_lista_de_conjuntos_nunca_traz_data(client, operator_headers): ...
async def test_apagar_conjunto_em_montagem_e_409(client, admin_headers): ...
async def test_cancelar_job_na_fila_vira_cancelled_na_hora(client, admin_headers): ...
async def test_cancelar_dataset_build_na_fila_marca_o_conjunto_failed(client, admin_headers, db_session): ...
async def test_conjunto_failed_pode_ser_finalizado_de_novo_com_o_mesmo_end_ts(client, admin_headers, db_session): ...
async def test_conjunto_failed_pode_ser_apagado(client, admin_headers): ...
async def test_cancelar_job_rodando_so_liga_a_flag(client, admin_headers, db_session): ...
async def test_cancelar_job_terminado_nao_muda_o_estado(client, admin_headers): ...            # done continua done; 202
async def test_jobs_active_filtra_queued_e_running(client, operator_headers): ...
async def test_operador_nao_cria_nem_finaliza_nem_cancela(client, operator_headers): ...       # 403
```

- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar e ver passar** — `uv run pytest services/api/tests/test_softsensor_datasets.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(api): conjuntos de treino e jobs do sensor virtual`.

---

### Task 7: `ml-worker` na stack (ADR-046 D2, emenda ao ADR-023)

**Files:**
- Modify: `deploy/docker-compose.yml`, `deploy/docker-compose.e2e.yml` (comentário "8 servicos" → 9), `deploy/.env.example`, `deploy/smoke.sh` (linhas 3, 13, 15, 43, 54, 58)
- Modify: `packages/ottima-core/src/ottima_core/config.py` (linha ~46), `services/api/src/ottima_api/routers/health.py` (linhas 99-114), `services/api/tests/test_health.py`
- Modify: `frontend/src/app/useWorkersHealth.ts` (linhas 7, 29-34, 37), `frontend/src/app/useWorkersHealth.check.ts`
- Modify: `CLAUDE.md` (lista de serviços, envs, contagem)

**Interfaces — Produces:** serviço compose `ml-worker`; `Settings.health_url_ml_worker: str = "http://ml-worker:8005/health"`; chave `"ml_worker"` em `GET /api/health/workers`; `WorkerId` ganha `"ml_worker"` com rótulo `"ML Worker"`.

Bloco do compose: copie o de `calc-worker` (linhas 147-176) trocando `PACKAGE: ottima-ml-worker`, o comando para `ottima_ml_worker.main:app` na porta `8005`, o healthcheck para `8005`, e o `environment` para exatamente:

```yaml
    environment:
      OTTIMA_DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@timescaledb:5432/${POSTGRES_DB}
      OTTIMA_LOG_LEVEL: ${OTTIMA_LOG_LEVEL:-INFO}
      OTTIMA_ML_THREADS: ${OTTIMA_ML_THREADS:-2}
    cpus: ${OTTIMA_ML_CPUS:-2}
```

`depends_on`: `timescaledb` e `api` saudáveis (sem `redis`). O comentário do bloco explica: sem Redis, sem `.env` inteiro, CPU limitada para o treino não disputar núcleo com o flow-runtime (ADR-046).

- [ ] **Step 1: Testes que falham** — em `services/api/tests/test_health.py`, estenda os três casos que citam `health_url_calc_worker` para exigir a chave `ml_worker`; em `useWorkersHealth.check.ts`, troque as expectativas de 4 para 5 entradas, na ordem `opc_worker, flow_runtime, recorder, calc_worker, ml_worker`.
- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest services/api/tests/test_health.py -q` e `cd frontend && npm run test:unit` → FAIL.
- [ ] **Step 3: Implementar** config, rota, frontend, compose, `.env.example` (`OTTIMA_ML_THREADS=2`, `OTTIMA_ML_CPUS=2` com uma linha de comentário cada) e `smoke.sh` (`ESPERADOS=9`, `"ml-worker:8005"` no laço da linha 43, `"ml_worker"` na lista da linha 58, textos "8 serviços"/"4 workers" atualizados).
- [ ] **Step 4: Rodar e ver passar** — os dois comandos do Step 2 → PASS; `docker compose -f deploy/docker-compose.yml config -q` sem erro (exige `deploy/.env`; se não existir, valide com `--env-file deploy/.env.example`).
- [ ] **Step 5: Commit** — `feat(deploy): serviço ml-worker na stack, no health agregado e no smoke`.

---

### Task 8: Variáveis de laboratório no arquivo de projeto (RF-590, ADR-046 D8)

**Files:**
- Modify: `packages/ottima-core/src/ottima_core/portability/schemas.py`, `bundle.py`; `services/api/src/ottima_api/routers/projects.py`
- Test: `services/api/tests/test_projects_export.py`, `test_projects_import.py`

**Interfaces — Produces:** `class BundleLabVariable(BaseModel)` (`extra="forbid"`): `name: str`, `eu: str = ""`, `description: str = ""`; `ProjectBundle.lab_variables: list[BundleLabVariable] = Field(default_factory=list)`.

Export leva todas as variáveis de laboratório do projeto. Import recria; nome duplicado no bundle recusa o import (422). Análises e conjuntos **nunca** entram no bundle.

- [ ] **Step 1: Testes que falham**

```python
async def test_export_leva_as_variaveis_de_laboratorio(client, admin_headers): ...
async def test_export_nunca_leva_analises_nem_conjuntos(client, admin_headers):
    # o JSON exportado não contém as chaves "lab_samples", "datasets" nem nenhum valor de análise
async def test_import_recria_as_variaveis(client, admin_headers, db_session): ...
async def test_import_com_nome_de_variavel_duplicado_e_422(client, admin_headers): ...
async def test_bundle_sem_lab_variables_continua_importando(client, admin_headers): ...
```

- [ ] **Step 2 a 4:** rodar e ver falhar, implementar, rodar e ver passar (`uv run pytest services/api/tests/test_projects_export.py services/api/tests/test_projects_import.py -q`).
- [ ] **Step 5: Commit** — `feat(portabilidade): variáveis de laboratório no arquivo de projeto`.

---

### Task 9: Página "Coleta e treino" (RF-589, sem a parte de treino)

**Files:**
- Create: `frontend/src/features/softsensor/` (arquivos listados em File Structure)
- Modify: `frontend/src/app/AppShell.tsx` (linhas 20-26 e 90-94), `router.tsx` (linha ~64), `appShell.check.ts` (`ROTAS_COM_NAV`, linhas 23-34)

**Interfaces:**
- Consumes: rotas das Tasks 3 e 6; `GET /api/softsensor/blocks` (SV-1); `TrendChart` (`features/trend/TrendChart.tsx`), `useHistory` e `montarMatriz` (`features/trend/useHistory.ts:71,112`), `useTags` (`:43`) com o filtro de projeto de `features/trend/tagsDoProjeto`; `enviarBinario` (`lib/arquivos.ts:88`); `paraIsoUtc` (`features/events/eventos.ts:43`); `useCanMutate` (`features/auth/useAuth.tsx:81`); `api`/`ApiError` (`lib/api.ts`).
- Produces:
  - Rota `/engenharia/sensor-virtual/coleta` → `ColetaTreinoPage`.
  - `useSoftSensorBlocks(): UseQueryResult<SoftSensorBlockOut[]>` (`queryKey ["softsensor","blocks"]`).
  - Item de navegação **condicional**: `{ rotulo: "Coleta e treino", para: "/engenharia/sensor-virtual/coleta", testid: "nav-sv-coleta" }`, renderizado depois de "Trend" só quando `useSoftSensorBlocks().data` tem ao menos um item. `NAV_ENGENHARIA` continua estático; o item condicional vive numa constante separada `NAV_SENSOR_VIRTUAL`, que a SV-3 estende.
  - `useJobs(ativo: boolean)` com `refetchInterval: (q) => (temJobAtivo(q.state.data) ? 2000 : false)` (molde: `useServerCertificate.ts:26-40`).
  - Funções puras em `coleta.ts`: `fusoDoNavegador(): string`; `resumoPareamento(stats): string`; `temJobAtivo(jobs): boolean`; `podeFinalizar(conjunto): boolean`; `progressoDoJob(job): { feito: number; total: number } | null`.

Seções da página, de cima para baixo (`data-testid` com prefixo `sv-coleta-`):
1. **Cabeçalho** `<h1 className="plaqueta text-sm">Sensor virtual · Coleta e treino</h1>` e seletor de conjunto (`sv-coleta-select-conjunto`), com o conjunto escolhido na query `?conjunto=<id>` (molde de URL: `FuzzyOperatePage.tsx:292-308`).
2. **Novo conjunto** (só admin, formulário inline aberto por botão `sv-coleta-novo`): nome, variável de laboratório (com atalho inline "Nova variável": nome, unidade, descrição), entradas (lista de checkboxes das tags do projeto, na ordem em que foram marcadas, teto 32; o molde é o seletor de `TrendPage.tsx:279-298`), período do modelo (`<Select>` com `1, 2, 5, 10, 30, 60, 300, 600 s`), início (`<Input type="datetime-local">` e botão "Agora"). Botão **"Iniciar coleta"**. `warnings` da resposta aparecem abaixo do formulário.
3. **Tendência das entradas** do conjunto escolhido: `TrendChart` com as primeiras 6 entradas (o teto de penas do `TrendChart`), janela de `start_ts` até `end_ts` ou agora.
4. **Análises** da variável do conjunto: formulário "Nova análise" (valor, data da coleta em `datetime-local`, botão "Adicionar", `sv-coleta-add-analise`), botão "Importar CSV" (`<input type="file" accept=".csv,text/csv" className="sr-only">` aberto por botão visível, molde `ImportarProjeto.tsx:162-190`; envia com `enviarBinario(\`/api/softsensor/lab-samples/import?tz=${encodeURIComponent(fusoDoNavegador())}\`, arquivo, "text/csv")`), e a tabela (coleta, valor, origem, apagar). Erro 422 do import é mostrado inteiro, em `role="alert"`, quebrado por `"; "`.
5. **Rodapé do conjunto**: estado (`collecting` → "Coletando desde <data>"; `building` → `<progress>` com `progressoDoJob`; `ready` → `resumoPareamento`; `failed` → erro do job), botão **"Finalizar"** (admin, só em `collecting`, `sv-coleta-finalizar`) com confirmação inline, e "Cancelar" enquanto `building`.

`resumoPareamento({analyses: 44, dropped_no_process: 3, paired: 41, full_window: 30})` devolve `"Emparelhadas 41 de 44 · 3 sem dado de processo no instante da coleta · 30 com janela completa"`; com `analyses: 0`, `"Nenhuma análise no período"`.

O gráfico de pontos das análises do esboço da spec fica para a SV-3: aqui as análises aparecem só na tabela.

- [ ] **Step 1: Checks que falham** em `coleta.check.ts`:

```ts
test("resumoPareamento com descartes", ...)            // string exata acima
test("resumoPareamento sem análises", ...)
test("temJobAtivo só com queued ou running", ...)
test("podeFinalizar só em collecting", ...)
test("progressoDoJob lê done/total e devolve null sem progresso", ...)
test("fusoDoNavegador devolve um nome IANA", ...)       // contém "/" ou é "UTC"
```

e em `appShell.check.ts`: a rota `/engenharia/sensor-virtual/coleta` em `ROTAS_COM_NAV`.

- [ ] **Step 2: Rodar e ver falhar** — `cd frontend && npm run test:unit` → FAIL.
- [ ] **Step 3: Regenerar tipos** — `npm run generate:api` (exige `frontend/openapi.json` atualizado da API desta branch; gere-o como a seção de comandos do `CLAUDE.md` indica). Tipos em `features/softsensor/types.ts`, no molde de `features/fuzzy/types.ts`.
- [ ] **Step 4: Implementar** hooks, página, rota e navegação.
- [ ] **Step 5: Rodar e ver passar** — `npm run test:unit && npm run typecheck && npm run build` → PASS.
- [ ] **Step 6: Commit** — `feat(frontend): página Coleta e treino com análises, CSV e conjuntos`.

---

### Task 10: Gates e E2E

**Files:**
- Create: `tests/e2e/test_sv2_laboratorio.py`
- Modify: `docs/PRD.md` (§7.1: kinds de auditoria das Tasks 3 e 6), `CLAUDE.md` (contagem da L2, comandos)

Cenários (`@pytest.mark.e2e`):
- **E2E-SV2-01 — do CSV ao conjunto.** Com o opcsim publicando há pelo menos 30 s: cria variável de laboratório, importa um CSV com 3 análises nos últimos 20 s, cria conjunto com 2 tags de entrada, período 1 s e início 1 minuto atrás, finaliza. Em até 60 s o job está `done`, o conjunto está `ready` e `stats.paired == 3`.
- **E2E-SV2-02 — CSV recusado.** CSV com uma linha de variável desconhecida devolve 422 citando a linha, e `GET .../samples` continua vazio.
- **E2E-SV2-03 — saúde.** `GET /api/health/workers` traz `ml_worker` com `up: true`.

Cancelamento não tem cenário L2 de propósito: o job de montagem pode terminar antes de o cancelamento chegar, e o teste seria uma corrida. A morte do processo filho é provada em `services/ml-worker/tests/test_runner.py`, e o cancelamento na fila em `test_softsensor_datasets.py`.

- [ ] **Step 1: Escrever os cenários.**
- [ ] **Step 2: Gates herméticos** — `uv run ruff check . && uv run ruff format --check .`; `cd frontend && npm run test:unit && npm run typecheck && npm run build && npm run generate:contracts && git diff --exit-code src/lib/contracts.gen.ts`.
- [ ] **Step 3: Suíte Python** — `uv run pytest -q` → PASS.
- [ ] **Step 4: Stack e L1 + L2** — sobe os 9 serviços com `--build`, roda `OTTIMA_E2E=1 bash deploy/smoke.sh` (9 serviços, 5 workers) e `uv run pytest -m e2e tests/e2e/test_sv2_laboratorio.py -v` com as credenciais inline do `CLAUDE.md`. Se a stack não subir, **pare e relate**.
- [ ] **Step 5: Docs e commit** — `test(e2e): cenários E2E-SV2-01..03 e ml-worker no smoke`.

---

## Fora deste plano

- **SV-3:** treino, Optuna, modelos na página, página Otimização, gráfico de pontos das análises, rótulos de porta no canvas.
