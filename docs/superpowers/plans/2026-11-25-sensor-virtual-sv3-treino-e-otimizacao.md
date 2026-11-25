# Sensor virtual SV-3 (treino e otimização) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Treinar modelos PLS, ESN e LSTM a partir dos conjuntos congelados, otimizar hiperparâmetros com Optuna, e fechar o ciclo na interface: gerar modelo, comparar métricas, ativar num bloco, acompanhar a troca, e a página "Otimização".

**Arquitetura:** O treino roda como job (`train`, `tune`) no `ml-worker` da SV-2, em processo filho. Cada método tem um treinador que devolve o artefato numérico da SV-1; as métricas são calculadas pela **mesma** função de inferência que o flow-runtime usa (`ottima_core.softsensor.predict`), e um teste de paridade compara essa função com scikit-learn e PyTorch. Os limites e defaults dos hiperparâmetros moram num módulo só, exportado para o frontend pelo espelho de contratos (ADR-034).

**Tech Stack:** Python 3.12, numpy, scikit-learn, PyTorch (CPU), Optuna, Pydantic v2, FastAPI, pytest · TypeScript strict, React, TanStack Query.

**Spec:** `docs/specs/SPEC_SENSOR_VIRTUAL.md` §6 (teste de paridade), §8.1, §8.2, §8.3, §8.4, §5.1 (rótulos de porta), §11 (cenário L2 com MPC). **Pré-requisito:** SV-1 e SV-2 mergeadas.

## Global Constraints

- Identificadores em **inglês**; UI, mensagens e docs em **pt-BR**. Sem emojis. Conventional Commits em pt-BR com caminhos explícitos; **nunca `git add -A`**.
- Dependências novas, **só em `services/ml-worker/pyproject.toml`**: `torch` (roda de CPU, sem CUDA), `scikit-learn`, `optuna`. Nenhuma delas pode aparecer no `uv sync --package` de `ottima-flow-runtime`, `ottima-api` ou `ottima-core`. Sem pandas, sem bibmon, sem reservoirpy, sem tensorflow.
- A raiz fixa `numpy>=2.5` por `override-dependencies`. Se `uv lock` não resolver com as três bibliotecas, **pare e relate**; não afrouxe o override.
- Métricas e objetivo do Optuna são sempre calculados por `ottima_core.softsensor.predict` sobre o artefato exportado, nunca pelo `predict` da biblioteca de treino.
- Divisão de dados **sempre em ordem de tempo**, nunca embaralhada: teste = últimos 20%; Optuna = `TimeSeriesSplit(n_splits=3)` sobre os 80% iniciais.
- `MIN_TRAIN_ROWS = 20`. Modelo gravado é reajustado sobre 100% dos dados com os hiperparâmetros escolhidos.
- Faixas de busca do Optuna: as da spec §8.2, copiadas na Task 4. `units` do ESN vai até **500**.
- Threads: `torch.set_num_threads(settings.ml_threads)` e `OMP_NUM_THREADS`/`OPENBLAS_NUM_THREADS` definidos no processo filho antes de importar numpy/torch.
- Sementes fixas para reprodutibilidade: `torch.manual_seed(42)`, `TPESampler(seed=42)`, `seed` do ESN vindo dos hiperparâmetros (default 42).
- **Sem modal novo**; `<table>` cru e `<progress>` nativo. `schema_version` do bundle continua 1. TDD estrito em lógica pura.
- Testes que treinam LSTM com mais de 20 épocas levam `@pytest.mark.slow`.

## Disciplina de worktree

Worktree **`/home/luciano/Documentos/ProjetosClaudeCode/ottimaSystemV3/.worktrees/sensor-virtual-sv3`**, branch `feat/sensor-virtual-sv3`, criada da `main` depois do merge da SV-2. Valem as quatro regras do plano da SV-1.

## Review Focus

1. **Conjunto com poucas análises utilizáveis para a janela pedida.** 30 análises emparelhadas, mas só 12 com os últimos 50 passos sem lacuna, e o usuário pede LSTM com janela 50. Espera-se job `failed` com "São necessárias ao menos 20 análises utilizáveis para a janela de 50 passos; há 12", não exceção de forma do numpy. → Task 2, `test_poucas_linhas_utilizaveis_falha_com_mensagem`.
2. **Alvo constante** (todas as análises com o mesmo valor). `y_std` é zero e o R² é indefinido. Espera-se modelo que devolve a constante, métricas com `r2 = 0.0`, sem `nan` no artefato nem no JSON. → Task 2, `test_alvo_constante_nao_gera_nan`.
3. **Tentativa do Optuna que diverge** (ESN com `sr = 1.5` produzindo estados enormes, LSTM com perda `nan`). Espera-se a tentativa contar como falha com R² muito baixo e o estudo seguir, não o job inteiro falhar. → Task 4, `test_tentativa_que_diverge_nao_derruba_o_estudo`.
4. **Apagar um modelo que está aquecendo como candidato.** Espera-se 409 nomeando o bloco, igual ao modelo em uso. → Task 5, `test_apagar_modelo_candidato_e_409`.
5. **Dois jobs de treino pedindo o mesmo nome de modelo.** O segundo termina depois e bate na unicidade. Espera-se job `failed` com "Já existe um modelo com o nome '<nome>'", e o primeiro modelo intacto. → Task 3, `test_nome_de_modelo_repetido_falha_o_segundo_job`.

---

## File Structure

**Criados**
- `packages/ottima-core/src/ottima_core/softsensor/hyperparams.py` — schemas, defaults e limites dos hiperparâmetros; `window_of`.
- `services/ml-worker/src/ottima_ml_worker/training/__init__.py`, `data.py`, `pls.py`, `esn.py`, `lstm.py`, `train.py`, `tune.py`.
- `services/ml-worker/tests/test_training_{data,pls,esn,lstm,train}.py`, `test_tune.py`, `test_train_job.py`.
- `frontend/src/features/softsensor/` — `OtimizacaoPage.tsx`, `SecaoTreino.tsx`, `TabelaModelos.tsx`, `useModels.ts`, `treino.ts`, `treino.check.ts`.
- `tests/e2e/test_sv3_treino.py`.

**Modificados**
- `services/ml-worker/pyproject.toml`, `uv.lock`, `services/ml-worker/src/ottima_ml_worker/handlers.py`, `runner.py` (variáveis de thread no filho).
- `packages/ottima-core/src/ottima_core/softsensor/__init__.py`, `contracts_export.py`.
- `services/api/src/ottima_api/routers/softsensor_lab.py` (`POST /jobs`), `routers/softsensor.py` (`DELETE /models/{id}`, `active_input_names` em `/blocks`).
- `frontend/src/features/softsensor/ColetaTreinoPage.tsx`, `useSoftSensorBlocks.ts`; `frontend/src/app/AppShell.tsx`, `router.tsx`, `appShell.check.ts`; `frontend/src/features/flows/nodes/index.tsx` (rótulos de porta); `frontend/src/lib/contracts.gen.ts` (gerado).
- `CLAUDE.md`.

---

### Task 1: Hiperparâmetros como contrato único (RF-587, RF-588)

**Files:**
- Create: `packages/ottima-core/src/ottima_core/softsensor/hyperparams.py`
- Modify: `packages/ottima-core/src/ottima_core/softsensor/__init__.py`, `packages/ottima-core/src/ottima_core/contracts_export.py` (`build_contracts`, linha ~381), `frontend/src/lib/contracts.gen.ts` (gerado)
- Test: `packages/ottima-core/tests/test_softsensor_hyperparams.py`, e o teste existente `packages/ottima-core/tests/test_contracts_export.py`

**Interfaces — Produces** (exportados de `ottima_core.softsensor`):

```python
class PlsHyperparams(BaseModel):      # extra="forbid"
    n_components: int = Field(3, ge=1, le=50)
class EsnHyperparams(BaseModel):
    units: int = Field(500, ge=10, le=500)
    sr: float = Field(0.9, gt=0, le=2.0)
    lr: float = Field(0.3, gt=0, le=1.0)
    rc_connectivity: float = Field(0.1, gt=0, le=1.0)
    input_connectivity: float = Field(0.1, gt=0, le=1.0)
    input_scaling: float = Field(1.0, gt=0, le=5.0)
    ridge: float = Field(1e-6, ge=0, le=1.0)
    warmup: int = Field(100, ge=1, le=256)
    seed: int = Field(42, ge=0, le=99999)
class LstmHyperparams(BaseModel):
    units: int = Field(64, ge=8, le=256)
    layers: int = Field(2, ge=1, le=4)
    epochs: int = Field(100, ge=1, le=500)
    batch_size: Literal[8, 16, 32, 64] = 32
    sequence_length: int = Field(10, ge=2, le=256)
    lr: float = Field(1e-3, gt=0, le=0.1)

HYPERPARAMS: dict[str, type[BaseModel]] = {"pls": PlsHyperparams, "esn": EsnHyperparams, "lstm": LstmHyperparams}
def parse_hyperparams(method: str, raw: Mapping[str, Any] | None) -> BaseModel      # ValidationError -> ValueError pt-BR
def window_of(method: str, hp: BaseModel) -> int                                    # pls 1; esn hp.warmup; lstm hp.sequence_length
SEARCH_SPACE: dict[str, dict[str, dict[str, Any]]]                                  # faixas do Optuna (Task 4), mesma fonte que a UI mostra
```

`SEARCH_SPACE` (spec §8.2), com `kind` em `int` / `float` / `log` / `choice`:
- `pls`: `n_components` int 1..20 (o teto efetivo é `min(n_entradas, n_linhas - 1, 20)`, aplicado na Task 4).
- `esn`: `units` int 100..500; `sr` float 0.1..1.5; `rc_connectivity` float 0.01..0.99; `input_connectivity` float 0.01..0.99; `lr` float 0.01..1.0; `ridge` log 1e-8..1e-1; `input_scaling` float 0.1..3.0; `warmup` int 10..200.
- `lstm`: `units` int 16..256; `layers` int 1..4; `epochs` int 30..200; `batch_size` choice [8,16,32,64]; `sequence_length` int 3..50; `lr` log 1e-4..1e-2.

`build_contracts()` ganha a chave `"SOFT_SENSOR_HYPERPARAMS"`: por método, por campo, `{default, min, max}` (ou `{default, choices}`), derivados dos schemas Pydantic, mais `"SOFT_SENSOR_SEARCH_SPACE": SEARCH_SPACE`. O frontend lê defaults e limites dali; nenhum número é digitado duas vezes.

- [ ] **Step 1: Testes que falham**

```python
def test_defaults_sao_os_da_spec(): ...                      # um assert por campo dos três schemas
def test_units_do_esn_nao_passa_de_500(): ...
def test_campo_desconhecido_e_recusado(): ...
def test_window_of(): assert window_of("pls", PlsHyperparams()) == 1 and window_of("esn", EsnHyperparams(warmup=7)) == 7 ...
def test_espaco_de_busca_cabe_nos_limites_do_schema(): ...   # todo low/high de SEARCH_SPACE valida no schema do método
def test_contrato_exporta_default_min_max(): ...             # build_contracts()["SOFT_SENSOR_HYPERPARAMS"]["lstm"]["units"] == {"default": 64, "min": 8, "max": 256}
```

- [ ] **Step 2 a 4:** rodar e ver falhar; implementar; `cd frontend && npm run generate:contracts`; `uv run pytest packages/ottima-core/tests/test_softsensor_hyperparams.py packages/ottima-core/tests/test_contracts_export.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(softsensor): hiperparâmetros e espaço de busca como contrato único`.

---

### Task 2: Treinadores e teste de paridade (RF-587, ADR-046 D4)

**Files:**
- Modify: `services/ml-worker/pyproject.toml`, `uv.lock`
- Create: `services/ml-worker/src/ottima_ml_worker/training/{__init__,data,pls,esn,lstm,train}.py`
- Test: `services/ml-worker/tests/test_training_{data,pls,esn,lstm,train}.py`

**Dependências.** Acrescente `scikit-learn`, `optuna` e `torch` ao `ml-worker`. O `torch` tem de vir da roda **de CPU**: consulte a documentação atual do `uv` sobre índice explícito para PyTorch (`[[tool.uv.index]]` com `explicit = true` e `[tool.uv.sources]`) antes de escrever, inclusive onde o índice precisa ser declarado num workspace. Critério de aceite: depois de `uv lock`, `grep -c "nvidia" uv.lock` devolve `0`, e `uv sync --frozen --no-dev --package ottima-flow-runtime --dry-run` não lista `torch`, `scikit-learn` nem `optuna`.

**Interfaces — Produces** (pacote `ottima_ml_worker.training`):

```python
MIN_TRAIN_ROWS = 20
class TrainingError(ValueError)                     # mensagem pt-BR, vira o `error` do job

@dataclass(frozen=True)
class TrainData:                                    # linhas em ordem crescente de ts
    x: np.ndarray        # float32 [n, 256, d], nan = lacuna
    y: np.ndarray        # float64 [n]
    ts: np.ndarray       # float64 [n]

def load_train_data(blobs: Sequence[bytes]) -> TrainData                       # unpack_dataset + concat + ordena por ts
def select_rows(data: TrainData, k: int) -> tuple[np.ndarray, np.ndarray]      # (x[:, -k:, :] das linhas sem nan nesses k passos, y)
def chrono_split(n: int, test_fraction: float = 0.2) -> tuple[slice, slice]    # treino = primeiros; teste = últimos, ao menos 1 linha
def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]        # r2, rmse, mae; r2 = 0.0 se var(y_true) == 0

def fit(method: str, x_k: np.ndarray, y: np.ndarray, hp: BaseModel, *,
        epoch_cb: Callable[[int, float], None] | None = None) -> dict[str, np.ndarray]   # pesos no formato do artefato (SV-1 Task 1)

@dataclass(frozen=True)
class InputSeed: name: str; eu: str

def train(method: str, data: TrainData, hp: BaseModel, *, inputs: Sequence[InputSeed],
          output_name: str, output_eu: str, period_s: float, dataset_ids: Sequence[int],
          epoch_cb: Callable[[int, float], None] | None = None) -> tuple[ModelMeta, bytes, dict]
          # devolve (meta, pesos empacotados, {"rows_used": int, "rows_test": int})
```

Regras:
- `train`: `k = window_of(method, hp)`; `select_rows`; menos de 20 linhas → `TrainingError(f"São necessárias ao menos 20 análises utilizáveis para a janela de {k} passos; há {n}")`. Divide 80/20 em ordem de tempo; ajusta nos 80%; calcula `metrics` nos 20% com `ottima_core.softsensor.predict` sobre um `LoadedModel` montado com os pesos; **reajusta sobre 100%**; `inputs[i].min/max` são o mínimo e o máximo de cada entrada sobre todas as linhas e todos os `k` passos usados; `warmup_steps = k`; `hyperparams` = `hp.model_dump()`.
- **PLS** (`pls.py`): `PLSRegression(n_components=min(hp.n_components, d, n - 1), scale=True)` sobre `x_k[:, -1, :]`. Exportação independente da versão do scikit-learn: `b = model.predict(zeros(1, d))[0]` e `w[j] = model.predict(e_j)[0] - b` (o modelo é afim, então isso é exato).
- **ESN** (`esn.py`): padroniza `x` e `y` (desvio zero vira 1). `rng = np.random.default_rng(hp.seed)`; `W`: máscara com densidade `rc_connectivity`, valores `rng.normal`, reescalada para raio espectral `sr` (`max(abs(eigvals))`; raio zero deixa `W` como está); `Win`: máscara com densidade `input_connectivity`, valores `rng.uniform(-1, 1) * input_scaling`; `bias`: `rng.uniform(-1, 1)`. Estados finais calculados de uma vez para todas as linhas (`S` `[m, units]`, laço só sobre os `k` passos). Saída por `sklearn.linear_model.Ridge(alpha=hp.ridge)` sobre `S`.
- **LSTM** (`lstm.py`): `torch.nn.LSTM(d, units, num_layers=layers, batch_first=True)` + `Linear(units, 1)` sobre a saída do último passo; Adam com `lr`; MSE; `DataLoader` com `shuffle=True` **só dentro do treino** (a divisão treino/teste já foi feita em ordem de tempo); parada antecipada com paciência 10 sobre a perda média da época; `epoch_cb(epoch, perda)` a cada época. Exportação: `weight_ih_l{k}` → `w_ih_{k}`, `weight_hh_l{k}` → `w_hh_{k}`, `bias_ih_l{k}` → `b_ih_{k}`, `bias_hh_l{k}` → `b_hh_{k}`, `fc.weight[0]` → `fc_w`, `fc.bias` → `fc_b`.

- [ ] **Step 1: Testes que falham**

```python
# test_training_data.py
def test_load_concatena_e_ordena_por_tempo(): ...
def test_select_rows_usa_so_os_ultimos_k_passos():
    # linha com nan no passo 100 (de 256): entra com k=50, sai com k=200
def test_chrono_split_nunca_embaralha_e_teste_tem_ao_menos_uma_linha(): ...
def test_metrics_com_alvo_constante_devolve_r2_zero(): ...

# test_training_pls.py
def test_paridade_com_o_predict_do_scikit_learn():
    # dados aleatórios (n=60, d=5); para 50 entradas aleatórias:
    # abs(predict(modelo_exportado, x[None, :]) - sk_model.predict(x[None, :])) < 1e-4
def test_recupera_relacao_linear_conhecida(): ...         # y = 2*x0 - x1 + 0.5 sem ruído -> rmse < 1e-3
def test_n_components_e_limitado_por_d_e_n(): ...

# test_training_esn.py
def test_estado_de_treino_e_o_mesmo_da_inferencia_compartilhada():
    # para 20 janelas aleatórias: predict(modelo_exportado, janela) == saída calculada pela matriz S do treino, tol 1e-4
def test_raio_espectral_e_o_pedido(): ...                # abs(max|eig(W)| - sr) < 1e-3
def test_densidade_das_matrizes_segue_a_conectividade(): ...
def test_mesma_semente_gera_o_mesmo_modelo(): ...
def test_aprende_media_movel_dos_ultimos_passos(): ...   # alvo = média de x0 nos últimos 5 passos; r2 de teste > 0.8

# test_training_lstm.py
def test_paridade_com_o_forward_do_pytorch():
    # rede pequena (units=8, layers=2, k=6) com pesos aleatórios; 30 janelas aleatórias:
    # abs(predict(modelo_exportado, janela) - torch_net(janela_padronizada) despadronizado) < 1e-4
def test_parada_antecipada_interrompe_antes_de_todas_as_epocas(): ...
def test_epoch_cb_e_chamado_por_epoca(): ...
@pytest.mark.slow
def test_aprende_relacao_temporal_simples(): ...

# test_training_train.py
def test_poucas_linhas_utilizaveis_falha_com_mensagem():
    # 30 análises, 12 com os últimos 50 passos íntegros, LstmHyperparams(sequence_length=50)
    # -> TrainingError("São necessárias ao menos 20 análises utilizáveis para a janela de 50 passos; há 12")
def test_alvo_constante_nao_gera_nan():
    # y todo igual a 7.0 -> metrics["r2"] == 0.0; nenhum nan nos pesos; predict devolve ~7.0
def test_metricas_vem_do_teste_e_o_modelo_final_usa_tudo(): ...     # rows_test == ceil(0.2*n); faixas min/max cobrem as linhas de teste
def test_faixas_de_entrada_no_meta_cobrem_os_k_passos(): ...
def test_artefato_gerado_carrega_com_load_model(): ...             # para os três métodos
```

- [ ] **Step 2: Rodar e ver falhar** — `uv lock && uv sync --all-packages && uv run pytest services/ml-worker/tests -k training -q` → FAIL.
- [ ] **Step 3: Implementar** os seis módulos.
- [ ] **Step 4: Rodar e ver passar** — mesmo comando → PASS; critério de aceite das dependências (acima) conferido e os dois números colados no relato.
- [ ] **Step 5: Commit** — `git add services/ml-worker uv.lock`; `feat(ml-worker): treinadores PLS/ESN/LSTM com paridade contra a inferência compartilhada`.

---

### Task 3: Job `train` (RF-587)

**Files:**
- Modify: `services/ml-worker/src/ottima_ml_worker/handlers.py`, `runner.py`
- Test: `services/ml-worker/tests/test_train_job.py`

**Interfaces:**
- Consumes: `train`, `load_train_data`, `TrainingError`, `InputSeed` (Task 2); `parse_hyperparams` (Task 1); `JobContext`, `HANDLERS` (SV-2 Task 5); `SoftSensorModel`, `SoftSensorDataset`.
- Produces: `HANDLERS["train"]`; `params = {"method": str, "dataset_ids": [int], "hyperparams": dict, "name": str}`; `result = {"model_id": int, "metrics": {r2, rmse, mae}, "rows_used": int, "rows_test": int}`; `progress = {"stage": "loading" | "training" | "saving", "epoch": int?, "epochs": int?}`.
- `async def load_compatible_datasets(session, project_id: int, dataset_ids: Sequence[int]) -> list[SoftSensorDataset]` em `packages/ottima-core/src/ottima_core/softsensor/dataset.py` (o handler e a API da Task 5 usam a mesma função) — exige ao menos um; todos do projeto, `ready`, com a mesma `lab_variable_id`, o mesmo `input_tag_ids` (mesma ordem) e o mesmo `period_s`; senão levanta `DatasetError` com o motivo em pt-BR (`"Conjunto '<nome>' ainda não está pronto"`, `"Conjuntos com variáveis de laboratório diferentes"`, `"Conjuntos com entradas diferentes"`, `"Conjuntos com períodos diferentes"`, `"Conjunto <id> não existe neste projeto"`). O handler converte `DatasetError` em falha do job com a mesma mensagem.

O handler grava `SoftSensorModel` com `input_tag_ids` do conjunto, `n_inputs`, `period_s`, `meta = ModelMeta.model_dump(mode="json")`, `weights`. `IntegrityError` no nome → `TrainingError(f"Já existe um modelo com o nome '{name}'")`. **Threads:** defina `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` e `MKL_NUM_THREADS` (valor de `settings.ml_threads`) em `os.environ` **no processo pai**, em `runner.run_job`, antes de `proc.start()`. Não adianta fazer isso dentro de `child_main`: com `spawn`, o filho importa `runner` → `handlers` → `training` (numpy e torch) antes de o corpo de `child_main` rodar, e as bibliotecas leem essas variáveis na importação. `torch.set_num_threads(settings.ml_threads)` continua sendo chamado no treinador do LSTM.

- [ ] **Step 1: Testes que falham**

```python
async def test_treino_pls_grava_modelo_com_metricas_e_tags_de_entrada(session_factory): ...
async def test_dois_conjuntos_compativeis_sao_concatenados(session_factory): ...        # rows_used soma os dois
@pytest.mark.parametrize("defeito", ["variavel", "entradas", "ordem_das_entradas", "periodo", "nao_ready", "outro_projeto"])
async def test_conjuntos_incompativeis_falham_com_o_motivo(session_factory, defeito): ...
async def test_nome_de_modelo_repetido_falha_o_segundo_job(session_factory): ...
async def test_hiperparametro_invalido_falha_com_mensagem(session_factory): ...
async def test_progresso_do_lstm_informa_a_epoca(session_factory): ...
async def test_filho_nasce_com_o_limite_de_threads(session_factory):
    # handler de teste que devolve os.environ["OMP_NUM_THREADS"] no result -> igual a str(settings.ml_threads)
```

- [ ] **Step 2 a 4:** rodar e ver falhar; implementar; `uv run pytest services/ml-worker/tests/test_train_job.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(ml-worker): job de treino grava o modelo com métricas de teste`.

---

### Task 4: Job `tune` com Optuna (RF-588)

**Files:**
- Create: `services/ml-worker/src/ottima_ml_worker/training/tune.py`
- Modify: `services/ml-worker/src/ottima_ml_worker/handlers.py`
- Test: `services/ml-worker/tests/test_tune.py`

**Interfaces:**
- Consumes: Tasks 1 a 3.
- Produces:
  - `def tune(method: str, data: TrainData, *, n_trials: int, min_r2: float, base: BaseModel, on_trial: Callable[[dict], None] | None = None) -> BaseModel` — devolve os melhores hiperparâmetros como instância do schema do método (campos fora do espaço de busca, como `seed`, vêm de `base`).
  - `HANDLERS["tune"]`; `params = {"method", "dataset_ids", "n_trials" (10..500), "min_r2" (0..1), "name"}`; `result` igual ao de `train`, mais `"best_params": dict`, `"best_cv_r2": float`, `"trials_run": int`; `progress = {"trial": int, "n_trials": int, "best_r2": float | None, "trials": [{"number", "r2", "state", "params"}]}` (as últimas 500).

Regras (spec §8.2):
- Estudo `optuna.create_study(direction="maximize", sampler=TPESampler(seed=42))`; para LSTM, também `pruner=MedianPruner(n_startup_trials=3, n_warmup_steps=10)`. `optuna.logging.set_verbosity(WARNING)`. Estudo em memória.
- O espaço de busca vem de `SEARCH_SPACE[method]`; `n_components` do PLS tem teto `min(d, linhas_de_treino - 1, 20)`.
- Objetivo: sobre os **80% iniciais** das linhas utilizáveis para o `k` da tentativa, `TimeSeriesSplit(n_splits=3)`; em cada dobra `fit` no treino da dobra e R² na validação via `predict` compartilhado; devolve a média. Dobra com menos de **2** linhas de validação (R² não existe com uma só), qualquer exceção do ajuste, ou predição não finita → a tentativa devolve `-1e9` (valor finito; a tentativa conta e o estudo segue). O piso é 2 e não mais porque o mínimo de 20 linhas deixa 16 no treino, e `TimeSeriesSplit(3)` sobre 16 dá dobras de validação de 4 linhas: um piso maior reprovaria toda tentativa de um conjunto pequeno.
- **Estudo sem nenhuma tentativa válida** (melhor valor igual a `-1e9`, ou nenhuma tentativa completa): `tune` levanta `TrainingError("Nenhuma tentativa produziu um modelo válido; reveja o conjunto ou reduza a janela")`. O job falha e **nenhum modelo é gravado**: sem isso, o job salvaria um modelo com parâmetros arbitrários.
- LSTM reporta `trial.report(-perda, passo)` por época e levanta `TrialPruned` quando `should_prune()`.
- Parada pelo R² mínimo: callback que chama `study.stop()` quando `min_r2 > 0` e `study.best_value >= min_r2`.
- Ao fim, o handler chama `train(...)` com os melhores hiperparâmetros (mesma regra de 80/20 e reajuste em 100%) e grava o modelo como o job `train`.

- [ ] **Step 1: Testes que falham**

```python
def test_pls_encontra_n_components_melhor_que_o_default(): ...       # dados com 3 fatores latentes; best >= 3
def test_validacao_e_em_ordem_de_tempo():
    # espiona os índices passados ao fit: em toda dobra, max(treino) < min(validação)
def test_r2_minimo_para_o_estudo_cedo():
    # relação linear perfeita, min_r2=0.9, n_trials=50 -> trials_run < 50
def test_r2_minimo_zero_roda_todas_as_tentativas(): ...
def test_tentativa_que_diverge_nao_derruba_o_estudo(monkeypatch):
    # fit que levanta em 1 de cada 2 tentativas -> tune devolve params; trials com r2 == -1e9 no progresso
def test_conjunto_minimo_de_20_linhas_ainda_produz_tentativas_validas(): ...   # 20 linhas, PLS: best_cv_r2 > -1e9
def test_estudo_sem_tentativa_valida_falha_e_nao_devolve_parametros(monkeypatch):
    # fit que sempre levanta -> TrainingError("Nenhuma tentativa produziu um modelo válido; ...")
def test_on_trial_recebe_numero_r2_estado_e_parametros(): ...
def test_parametros_fora_do_espaco_de_busca_vem_da_base(): ...       # seed do ESN preservado
def test_mesma_semente_repete_o_resultado(): ...                      # duas execuções -> mesmos best_params (PLS)
async def test_job_tune_grava_o_modelo_final(session_factory): ...
@pytest.mark.slow
def test_lstm_poda_tentativas_ruins(): ...                            # ao menos 1 trial com state "PRUNED" em 10
```

- [ ] **Step 2 a 4:** rodar e ver falhar; implementar; `uv run pytest services/ml-worker/tests/test_tune.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(ml-worker): otimização de hiperparâmetros com Optuna e validação em ordem de tempo`.

---

### Task 5: API — enfileirar treino e otimização, apagar modelo, nomes de porta (RF-587, RF-588, RF-581)

**Files:**
- Modify: `services/api/src/ottima_api/routers/softsensor_lab.py`, `routers/softsensor.py`, `packages/ottima-core/src/ottima_core/bus.py`
- Test: `services/api/tests/test_softsensor_training.py`

**Interfaces — Produces:**
- `POST /api/softsensor/jobs` (admin, 202 `{job_id}`): corpo discriminado por `kind`:
  - `{"kind": "train", "method", "dataset_ids", "name", "hyperparams"?}`
  - `{"kind": "tune", "method", "dataset_ids", "name", "n_trials": int (10..500, default 20), "min_r2": float (0..1, default 0)}`
- `DELETE /api/softsensor/models/{id}` (admin, 204).
- `GET /api/softsensor/blocks` ganha `ts_seconds: float` (Ts do flow), `active_input_names: list[str] | None` (nomes de `meta.inputs` do modelo em uso) e `warmup_s: float | None` (`warmup_steps * period_s` do modelo em uso).
- `GET /api/softsensor/models` ganha `warmup_s`, `hyperparams` e `in_use: [{flow_id, flow_name, block_id, state}]`, com `state` em `"active"` / `"candidate"` / `"pending"` (`desired` diferente de `active` e sem candidato).

Recusas (422, antes de enfileirar): método fora de `pls/esn/lstm`; conjuntos incompatíveis (mesma função e mesmas mensagens da Task 3); `hyperparams` inválido (`parse_hyperparams`); nome vazio; nome já usado por um modelo do projeto → 409. `DELETE` de modelo referenciado por qualquer coluna de `soft_sensor_bindings` → 409 `"Modelo em uso pelo bloco '<block_id>' do flow '<nome>'"`. Auditoria: `soft_sensor_job_queued` (payload `{job_id, kind, method, name}`) e `soft_sensor_model_deleted`.

- [ ] **Step 1: Testes que falham**

```python
async def test_enfileirar_treino_cria_job_queued(client, admin_headers, db_session): ...
async def test_enfileirar_otimizacao_valida_n_trials_e_min_r2(client, admin_headers): ...     # 9, 501, -0.1, 1.1 -> 422
async def test_conjuntos_incompativeis_sao_recusados_antes_da_fila(client, admin_headers, db_session): ...
async def test_hiperparametro_fora_do_limite_e_422(client, admin_headers): ...               # esn units=1000
async def test_nome_de_modelo_ja_usado_e_409(client, admin_headers): ...
async def test_operador_nao_enfileira(client, operator_headers): ...                         # 403
async def test_apagar_modelo_livre(client, admin_headers): ...
async def test_apagar_modelo_em_uso_e_409(client, admin_headers): ...
async def test_apagar_modelo_candidato_e_409(client, admin_headers): ...
async def test_blocks_traz_nomes_das_entradas_do_modelo_em_uso(client, operator_headers): ...
async def test_models_traz_estado_de_uso(client, operator_headers): ...                      # active, candidate, pending
```

- [ ] **Step 2 a 4:** rodar e ver falhar; implementar; `uv run pytest services/api/tests/test_softsensor_training.py services/api/tests/test_softsensor.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(api): fila de treino e otimização, exclusão de modelo e nomes de porta`.

---

### Task 6: Treino e modelos na página "Coleta e treino" (RF-589, RF-584)

**Files:**
- Create: `frontend/src/features/softsensor/SecaoTreino.tsx`, `TabelaModelos.tsx`, `useModels.ts`, `treino.ts`, `treino.check.ts`
- Modify: `frontend/src/features/softsensor/ColetaTreinoPage.tsx`, `useSoftSensorBlocks.ts`

**Interfaces:**
- Consumes: `SOFT_SENSOR_HYPERPARAMS` de `contracts.gen.ts` (Task 1); rotas da Task 5; `POST /api/operate/{flow_id}/{block_id}/model` (SV-1).
- Produces, em `treino.ts` (puras):
  - `hiperparametrosIniciais(metodo): Record<string, number>` — defaults do contrato.
  - `problemaDoCampo(metodo, campo, valor): string | null` — `"Deve estar entre <min> e <max>"`.
  - `blocosCompativeis(modelo, blocos): SoftSensorBlockOut[]` — mesmo método, mesmo `n_inputs`, e `period_s` múltiplo do `ts_seconds` do flow (campo de `/blocks`, Task 5).
  - `estadoDoModelo(modelo): string` — `"em uso em <flow> / <bloco>"`, `"aquecendo em ..."`, `"aguardando o runtime em ..."`, ou `"—"`.
  - `formatarAquecimento(segundos): string` — `"nenhum"` para um passo de PLS, `"10 min"`, `"1 h 40 min"`.
  - `precisaAcompanhar(blocos): boolean` — algum bloco com candidato, ou com `desired_model_id !== active_model_id`.

Na página, abaixo do rodapé do conjunto (só para conjunto `ready`; `data-testid` com prefixo `sv-coleta-`):
- **Gerar modelo** (admin): método (`<Select>` PLS/ESN/LSTM), nome do modelo, campos de hiperparâmetros do método com os defaults do contrato e validação por `problemaDoCampo`, caixas para incluir outros conjuntos compatíveis, botão **"Gerar modelo"** (`sv-coleta-gerar`). Com job `train` ativo: `<progress>` e "Cancelar". Job `failed`: a mensagem do `error` em `role="alert"`.
- **Modelos** (tabela): nome, método, R², RMSE, MAE, aquecimento, estado, e as ações de admin **"Ativar ▾"** (`<Select>` com `blocosCompativeis`, mais botão de confirmação inline) e **"Apagar"** (confirmação inline; 409 mostrado como veio). Erro 422 da ativação é mostrado inteiro.
- `useSoftSensorBlocks` passa a usar `refetchInterval: (q) => (precisaAcompanhar(q.state.data) ? 2000 : false)`, e `useModels` idem: é assim que "aquecendo" vira "em uso" na tela, sem depender do WebSocket.
- O gráfico de pontos das análises do esboço da spec: um segundo `TrendChart` abaixo da tendência das entradas, com a série da variável de laboratório, **se** o `TrendChart` desenhar série esparsa sem alteração; se exigir mudança no componente, mantenha só a tabela e registre no relato.

- [ ] **Step 1: Checks que falham** em `treino.check.ts`:

```ts
test("defaults vêm do contrato", ...)                               // lstm.units === 64, esn.units === 500
test("campo fora do limite devolve a mensagem com a faixa", ...)    // esn.units = 600 -> "Deve estar entre 10 e 500"
test("blocosCompativeis filtra por método, entradas e período", ...)
test("estadoDoModelo distingue em uso, aquecendo e aguardando", ...)
test("formatarAquecimento", ...)                                    // 0 passos úteis -> "nenhum"; 600 -> "10 min"; 6000 -> "1 h 40 min"
test("precisaAcompanhar só com troca pendente", ...)
```

- [ ] **Step 2 a 4:** `cd frontend && npm run test:unit` falha; regenerar tipos (`npm run generate:api`); implementar; `npm run test:unit && npm run typecheck && npm run build` → PASS.
- [ ] **Step 5: Commit** — `feat(frontend): gerar, comparar e ativar modelos na página Coleta e treino`.

---

### Task 7: Página "Otimização" e rótulos de porta (RF-589, RF-581)

**Files:**
- Create: `frontend/src/features/softsensor/OtimizacaoPage.tsx`
- Modify: `frontend/src/app/AppShell.tsx` (`NAV_SENSOR_VIRTUAL`), `router.tsx`, `appShell.check.ts`, `frontend/src/features/flows/nodes/index.tsx` (`NoSensorVirtual`), `frontend/src/features/softsensor/treino.ts`, `treino.check.ts`

**Interfaces — Produces:**
- Rota `/engenharia/sensor-virtual/otimizacao` → `OtimizacaoPage`; item condicional `{ rotulo: "Otimização", para: "/engenharia/sensor-virtual/otimizacao", testid: "nav-sv-otim" }`, depois de "Coleta e treino", sob a mesma condição.
- Em `treino.ts`: `linhasDeTentativas(progress): { numero: number; r2: string; estado: string; parametros: string }[]` (mais nova primeiro; `r2` de `-1e9` vira `"falhou"`; `state` `PRUNED` vira `"podada"`); `rotuloDaPorta(indice: number, nomes: readonly string[] | null): string` — `"IN1"` sem nomes, `"IN1 · <nome>"` com nomes.

Página (`data-testid` com prefixo `sv-otim-`): seletor de conjunto(s) `ready` compatíveis, método, nome do modelo, **"Tentativas"** (10 a 500, default 20), **"R² mínimo"** (0 a 1, default 0, com o texto "0 = não parar antes do fim"), tabela somente leitura das faixas de busca do método (de `SOFT_SENSOR_SEARCH_SPACE`), botões **"Otimizar"** e **"Cancelar"** (admin). Com job `tune` ativo: `<progress value={trial} max={n_trials}>`, "Tentativa k de N", "Melhor R² até agora: x", e a tabela de `linhasDeTentativas`. Ao terminar: melhores parâmetros, R²/RMSE/MAE do modelo gerado, e um link "Ativar na página Coleta e treino" (`?conjunto=<id>`). Operador vê tudo e não vê os botões.

No canvas, `NoSensorVirtual` rotula cada porta de entrada com `rotuloDaPorta(i, active_input_names)`, lendo `useSoftSensorBlocks()` e casando por `flow_id` e `block_id`.

- [ ] **Step 1: Checks que falham**

```ts
test("linhasDeTentativas ordena da mais nova e traduz falha e poda", ...)
test("rotuloDaPorta sem modelo mostra só IN<n>", ...)
test("rotuloDaPorta com modelo mostra o nome da tag", ...)       // "IN2 · TIC-101.PV"
test("rota de otimização está na navegação", ...)                // appShell.check.ts
```

- [ ] **Step 2 a 4:** falhar; implementar; `npm run test:unit && npm run typecheck && npm run build` → PASS.
- [ ] **Step 5: Commit** — `feat(frontend): página Otimização e nomes das tags nas portas do bloco`.

---

### Task 8: Gates, imagem e E2E

**Files:**
- Create: `tests/e2e/test_sv3_treino.py`
- Modify: `CLAUDE.md` (contagem da L2, seção de comandos: `uv run pytest -m slow services/ml-worker/tests`)

Cenários (`@pytest.mark.e2e`):
- **E2E-SV3-01 — do conjunto ao bloco.** Com o opcsim publicando duas tags e uma terceira que é combinação linear delas: importa 30 análises sintéticas (valor = a terceira tag nos instantes das análises, lida de `/api/history`), congela o conjunto, treina PLS, espera `done`, confere R² de teste maior que 0.9, ativa no bloco de um flow em execução e vê `out` GOOD com o modelo novo em `active_model_id`.
- **E2E-SV3-02 — otimização.** `tune` de PLS com 10 tentativas sobre o mesmo conjunto: job `done`, `result.trials_run == 10`, modelo gravado.
- **E2E-SV3-03 — cancelamento de otimização.** `tune` de LSTM com 500 tentativas; cancela depois da primeira tentativa aparecer no progresso; em até 10 s o job está `cancelled` e nenhum modelo com aquele nome existe.
- **E2E-SV3-04 — malha com MPC** (cenário da spec §11, adiado da SV-1). Flow com `opc_read` → `soft_sensor_pls` → CV de um MPC com `fail_action` configurada, montado a partir dos helpers dos cenários F4 de `tests/e2e`. Tornar BAD uma tag de entrada do sensor virtual (o opcsim permite forçar qualidade; use o mesmo recurso dos cenários de `comm_failure`/qualidade existentes) faz o `mpc.state` reportar a CV como inválida e aplicar a ação de falha; o MPC **não** fica com as saídas nulas do portão frio. Se o opcsim não tiver como forçar qualidade BAD numa tag só, **pare e relate** em vez de aproximar o cenário.

- [ ] **Step 1: Escrever os cenários.**
- [ ] **Step 2: Gates herméticos** — `uv run ruff check . && uv run ruff format --check .`; `cd frontend && npm run test:unit && npm run typecheck && npm run build && npm run generate:contracts && git diff --exit-code src/lib/contracts.gen.ts`.
- [ ] **Step 3: Suíte Python, incluindo `slow` do ml-worker** — `uv run pytest -q` e `uv run pytest -m slow services/ml-worker/tests -q` → PASS.
- [ ] **Step 4: Imagem** — `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.e2e.yml build ml-worker flow-runtime` e `docker image ls | grep -E "ml-worker|flow-runtime"`. Cole os dois tamanhos no relato. A imagem do `flow-runtime` não pode ter crescido em relação à `main`; a do `ml-worker` sem CUDA fica na casa de 1 GB, e acima de 2 GB indica roda errada do torch.
- [ ] **Step 5: Stack, L1 e L2** — sobe os 9 serviços, `OTTIMA_E2E=1 bash deploy/smoke.sh`, e `uv run pytest -m e2e tests/e2e/test_sv3_treino.py tests/e2e/test_sv1_sensor_virtual.py tests/e2e/test_sv2_laboratorio.py -v` com as credenciais inline. Se a stack não subir, **pare e relate**.
- [ ] **Step 6: Roteiro de navegador** (L3, com a ferramenta de browser, screenshot por passo): abrir Coleta e treino, gerar um modelo PLS, ver a linha na tabela com métricas, ativar num bloco e ver "aquecendo" virar "em uso"; abrir Otimização, rodar 10 tentativas e ver a tabela crescer; abrir o flow no canvas e ver os nomes das tags nas portas.
- [ ] **Step 7: Docs e commit.** No `docs/PRD.md` §7.1, acrescente ao vocabulário de `kind` os de auditoria desta entrega (`soft_sensor_job_queued`, `soft_sensor_model_deleted`). Commit: `test(e2e): cenários E2E-SV3-01..04 do treino e da malha com MPC`.
