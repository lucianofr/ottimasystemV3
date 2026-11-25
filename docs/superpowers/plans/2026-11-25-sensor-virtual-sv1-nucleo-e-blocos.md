# Sensor virtual SV-1 (núcleo e blocos) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Colocar no canvas os blocos `soft_sensor_pls`, `soft_sensor_esn` e `soft_sensor_lstm`, que estimam uma variável a cada passo de modelo a partir de um artefato numérico guardado no Postgres, com qualidade de saída conforme a spec, troca de modelo sem interrupção, pré-aquecimento pelo histórico e transporte do modelo no arquivo de projeto.

**Arquitetura:** A inferência mora num módulo só de numpy em `ottima_core.softsensor` (artefato, conta dos três métodos, buffer de amostras, regra de qualidade, função de grade sobre `samples`). O bloco de runtime guarda um "slot" por modelo (modelo + buffer + divisor de passo), promove o candidato quando ele não piora a saída e grava o estado em `soft_sensor_bindings`. A troca de modelo entra por um `cmd` novo em `flow.commands`; nenhum canal novo. Esta entrega **não treina nada**: os modelos chegam por import de projeto ou por artefatos sintéticos nos testes.

**Tech Stack:** Python 3.12, numpy, Pydantic v2, SQLAlchemy 2.0 async, Alembic, FastAPI, pytest + pytest-asyncio, ruff · TypeScript strict, React, React Flow, checks `*.check.ts`.

**Spec:** `docs/specs/SPEC_SENSOR_VIRTUAL.md` (aprovada em 2026-11-25). Este plano cobre a entrega **SV-1** do §11. SV-2 (laboratório e conjuntos) e SV-3 (treino e otimização) têm planos próprios, escritos depois desta.

## Global Constraints

- Identificadores de código em **inglês**; strings de UI, mensagens de erro e docs em **pt-BR**. Sem emojis.
- Commits em **Conventional Commits**, mensagem em pt-BR, com caminhos explícitos. **NUNCA `git add -A` / `git add .`**.
- **Nenhuma dependência nova** nesta entrega. `torch`, `scikit-learn` e `optuna` só entram na SV-2/SV-3, e só no `ml-worker`.
- O flow-runtime **nunca** importa biblioteca de treino nem abre pickle. Todo `.npz` é lido com `allow_pickle=False`.
- **Nenhum canal de barramento novo.** Só o `cmd` `soft_sensor_model` em `flow.commands` e cinco `kind` em `events`.
- Constantes da spec, com estes nomes e valores: `MAX_SOFT_SENSOR_INPUTS = 32`, `BUFFER_STEPS = 256`, `RANGE_MARGIN = 0.05`, `MAX_ARTIFACT_BYTES = 8 * 1024 * 1024`, `PREWARM_TIMEOUT_S = 5.0`, `MIN_PROMOTION_TIMEOUT_S = 60.0`, `MAX_IMPORT_BUNDLE_BYTES = 32 * 1024 * 1024`.
- Tolerância de idade de amostra na grade: `max(3 * period_s, 180.0)` segundos.
- Qualidade segue o ADR-043: `Quality.BAD = 0`, `UNCERTAIN = 1`, `GOOD = 2` nas portas; em `samples.quality` a polaridade é a OPC (`0` GOOD, `1` UNCERTAIN, `2` BAD, valor `NULL` quando BAD).
- `v = None` na saída só enquanto o bloco **nunca calculou** um valor desde que foi instanciado. Depois disso, saída BAD mantém o último valor.
- `frontend/src/lib/contracts.gen.ts` é **gerado** (`npm run generate:contracts`), nunca editado à mão.
- `schema_version` do arquivo de projeto **continua 1**; todo campo novo do bundle é opcional com default vazio.
- TDD estrito (RED, GREEN, REFACTOR) em toda lógica pura. Nenhuma tarefa roda o gate E2E nem `docker compose`, exceto a Task 12.

**Contratos de barramento (verbatim; SV-3 e o E2E casam por eles).**

Comando em `flow.commands`: `{flow_id, cmd: "soft_sensor_model", args: {"block_id": str, "model_id": int}, user, ts}`.

Eventos em `events`, todos com `origin = "flow-runtime"` e, no `payload`, `kind`, `flow_id` (int) e `block_id` (str), mais os campos da tabela. O `flow_id` é posto pela closure `emit_event` que o `definition.py` injeta; o bloco só informa o resto.

| `kind` | severidade | campos extras do payload | quando |
|---|---|---|---|
| `soft_sensor_model_activated` | info | `model_id`, `previous_model_id` (int ou null) | candidato promovido, ou modelo assumido no deploy/sem modelo em uso |
| `soft_sensor_model_rejected` | warning | `model_id`, `reason` (`incomplete`, `bad_sample`, `non_finite`, `extrapolating`, `uncertain`, `corrupt`, `method`, `n_inputs`, `period`) | candidato descartado no prazo, ou recusado ao carregar |
| `soft_sensor_model_missing` | warning | `reason` (`no_model`, `corrupt`, `method`, `n_inputs`, `period`) | bloco em execução sem modelo, uma vez por instância |
| `soft_sensor_extrapolating` | warning | `active` (bool), `model_id` | borda de entrada (`true`) e de saída (`false`) da extrapolação |
| `soft_sensor_prewarm_skipped` | info | `model_id`, `reason` (`tags`, `timeout`, `error`) | pré-aquecimento não feito |

**Ordem é dependência real.** O frontend indexa `PORT_CONTRACTS[tipo]` do arquivo gerado; a Task 9 só compila depois da Task 3. O bloco (Task 5) depende do módulo de inferência (Tasks 1 e 2) e das tabelas (Task 4).

## Disciplina de worktree (LEIA ANTES DO PRIMEIRO `read`)

Este plano roda na worktree **`/home/luciano/Documentos/ProjetosClaudeCode/ottimaSystemV3/.worktrees/sensor-virtual-sv1`**, branch `feat/sensor-virtual-sv1`. O checkout principal é `/home/luciano/Documentos/ProjetosClaudeCode/ottimaSystemV3`.

A spec e este plano precisam estar **commitados** antes de a worktree ser criada (arquivo não rastreado não viaja para a worktree).

Em TODA tarefa:

1. Todo `read`/`write`/`edit` usa o caminho **absoluto** da worktree.
2. Todo comando de shell passa `cwd` explícito da worktree.
3. Depois de cada escrita, confirme por shell (`grep`/`wc -l`) que o conteúdo chegou ao arquivo certo.
4. Antes de relatar tarefa concluída, `git -C /home/luciano/Documentos/ProjetosClaudeCode/ottimaSystemV3 status --porcelain` tem de estar vazio.

Existe outra worktree ativa, `.worktrees/refactor-frontend`. Não toque nela. Se a Task 9 encontrar um arquivo de `frontend/src/features/flows/` diferente do que este plano descreve, siga o padrão que estiver no arquivo e relate a diferença.

## Review Focus

Cinco condições que a spec implica, que nenhum molde de teste existente cobre, e que morderiam quem usa o sistema. Cada linha tem o teste na tarefa dona do código.

1. **Apagar um projeto que tem modelo vinculado a um bloco.** A FK do vínculo para o modelo não pode impedir a cascata do projeto. Espera-se que o projeto apague por inteiro. → Task 4, `test_apagar_projeto_com_modelo_vinculado`.
2. **Candidato com `period_s` diferente do modelo em uso.** As amostras do buffer do modelo em uso estão no espaçamento errado para ele. Espera-se que o candidato use um buffer próprio e nunca seja avaliado sobre amostras do outro período. → Task 5, `test_candidato_de_outro_periodo_nao_herda_o_buffer`.
3. **Entrada parada num valor constante** (`max == min` no treino, span zero). A margem de 5% vira zero e qualquer ruído de ponto flutuante marcaria extrapolação. Espera-se GOOD quando o valor é igual ao do treino. → Task 2, `test_faixa_de_span_zero_aceita_o_proprio_valor`.
4. **Artefato corrompido ou com forma errada no banco** (bytes truncados, matriz com `n_inputs` diferente). Espera-se bloco sem modelo, saída BAD e evento `soft_sensor_model_missing`; o deploy do flow nunca falha por isso. → Task 1, `test_load_model_recusa_forma_errada`, e Task 6, `test_deploy_com_artefato_corrompido_sobe_sem_modelo`.
5. **Flow salvo com `n_inputs` alterado e modelo vinculado.** O bloco é recriado com outro número de portas e o modelo vinculado deixa de servir. Espera-se bloco sem modelo e evento, não exceção na varredura. → Task 6, `test_reload_com_n_inputs_diferente_do_modelo`.

---

## File Structure

**Criados**
- `packages/ottima-core/src/ottima_core/softsensor/__init__.py` — reexporta a API pública do pacote.
- `packages/ottima-core/src/ottima_core/softsensor/artifact.py` — metadados (`ModelMeta`), empacotamento `.npz`, `LoadedModel`, validação de forma.
- `packages/ottima-core/src/ottima_core/softsensor/forward.py` — `predict`: a conta de PLS, ESN e LSTM.
- `packages/ottima-core/src/ottima_core/softsensor/window.py` — `SampleBuffer`, `evaluate`: regra de qualidade do §5.4.
- `packages/ottima-core/src/ottima_core/softsensor/grid.py` — grade de instantes, LOCF e consulta a `samples`.
- `packages/ottima-core/src/ottima_core/softsensor/synthetic.py` — artefatos sintéticos determinísticos, usados pelos testes de todos os pacotes e pelo E2E.
- `packages/ottima-core/src/ottima_core/models/soft_sensor.py` — `SoftSensorModel`, `SoftSensorBinding`.
- `packages/ottima-core/alembic/versions/0018_soft_sensor.py` — as duas tabelas.
- `services/flow-runtime/src/ottima_flow_runtime/blocks/soft_sensor.py` — `SoftSensorBlock`.
- `services/flow-runtime/src/ottima_flow_runtime/soft_sensor_seeds.py` — carga de modelo e pré-aquecimento no deploy; comando de troca.
- `services/api/src/ottima_api/softsensor.py` — poda de vínculos no save do flow, validação de ativação.
- `services/api/src/ottima_api/routers/softsensor.py` — `GET /api/softsensor/blocks`, `GET /api/softsensor/models`.
- `frontend/src/features/flows/config/CamposSensorVirtual.tsx`, `frontend/src/features/flows/sensorVirtual.check.ts`.
- `docs/adr/ADR-046-sensor-virtual.md`.
- Testes: `packages/ottima-core/tests/test_softsensor_{artifact,forward,window,grid}.py`, `packages/ottima-core/tests/test_flowgraph_soft_sensor.py`, `services/flow-runtime/tests/test_soft_sensor_{block,swap,seeds}.py`, `services/api/tests/test_softsensor.py`, `tests/e2e/test_sv1_sensor_virtual.py`.

**Modificados**
- `packages/ottima-core/src/ottima_core/flowgraph/parse.py`, `validate.py`, `__init__.py` — três tipos, `SoftSensorConfig`, portas.
- `packages/ottima-core/src/ottima_core/contracts_export.py` — `PORT_CONTRACTS`, `_NODE_CONFIG_MODELS`.
- `packages/ottima-core/src/ottima_core/bus.py` — cinco `KIND_SOFT_SENSOR_*`.
- `packages/ottima-core/src/ottima_core/models/__init__.py` — reexport.
- `packages/ottima-core/src/ottima_core/portability/schemas.py`, `bundle.py` — modelos e vínculos no bundle.
- `services/flow-runtime/src/ottima_flow_runtime/definition.py`, `supervisor.py` — instanciação, sementes, comando.
- `services/api/src/ottima_api/routers/operate.py`, `flows.py`, `projects.py`, e o registro de routers da API.
- `packages/ottima-mcp/src/ottima_mcp/server.py` + `packages/ottima-mcp/tests/test_server.py`.
- `frontend/nginx.conf`, `frontend/src/features/projects/importar.check.ts` e o texto do limite de import.
- `frontend/src/features/flows/graph.ts`, `registro.ts`, `nodes/index.tsx`, `config/ModalConfigBloco.tsx`; `frontend/src/lib/contracts.gen.ts` (gerado).
- `docs/PRD.md`, `docs/GLOSSARY.md`, `docs/specs/F6-portabilidade-hardening.md`, `CLAUDE.md`.

---

### Task 0: Materializar as propostas normativas

Implementa a seção 12 da spec. A aprovação da spec pelo usuário é a autorização para editar `docs/` (CLAUDE.md, item 4).

**Files:**
- Create: `docs/adr/ADR-046-sensor-virtual.md`
- Modify: `docs/PRD.md`, `docs/GLOSSARY.md`, `docs/specs/F6-portabilidade-hardening.md`, `CLAUDE.md`

- [ ] **Step 1: Escrever o ADR-046** com Status `Aceito · 2026-11-25`, "Emenda ao ADR-004 e ao ADR-023", Contexto (três parágrafos tirados da spec §1 e §4), Decisão com **D1 a D9 copiados da spec §12.1** e expandidos com o texto das seções que cada um cita, e Consequências. Siga a forma do `docs/adr/ADR-033-tags-calculadas.md`.
- [ ] **Step 2: PRD.** Aplicar a spec §12.2: linha de changelog `3.3`, RF-301 com três tipos a mais, nova §5.19 com **RF-581 a RF-591** (um parágrafo cada, texto da seção da spec citada), `ml-worker` no §3 e §4, `cmd` e `kind` novos no §7.1, grupo `/api/softsensor` no §7.3, fase nova no §8 com SV-1, SV-2 e SV-3 e os critérios de aceite da spec §11. A linha "Documentos-irmãos" passa a citar `ADR-001 … ADR-046`.
- [ ] **Step 3: GLOSSARY.** Acrescentar as sete linhas da spec §12.3 e incluir os três tipos na lista de tipos do termo **Bloco**.
- [ ] **Step 4: Spec F6 §3.2-1.** Trocar o teto de 4 MiB por 32 MiB e anotar "emenda da SPEC_SENSOR_VIRTUAL §9".
- [ ] **Step 5: CLAUDE.md.** Aplicar a spec §12.5 (invariante de fila, invariante de pickle, `services/ml-worker/` no layout com a nota "chega na SV-2").
- [ ] **Step 6: Verificar e commitar**

Run: `grep -c "RF-58\|RF-59" docs/PRD.md` — Expected: `11` ou mais.
Run: `grep -n "soft_sensor" docs/GLOSSARY.md | wc -l` — Expected: `1` ou mais.

```bash
git add docs/adr/ADR-046-sensor-virtual.md docs/PRD.md docs/GLOSSARY.md docs/specs/F6-portabilidade-hardening.md CLAUDE.md
git commit -m "docs: ADR-046 e requisitos do sensor virtual (RF-581..591)"
```

---

### Task 1: Artefato do modelo e a conta dos três métodos (RF-581, ADR-046 D3/D4)

**Files:**
- Create: `packages/ottima-core/src/ottima_core/softsensor/__init__.py`, `artifact.py`, `forward.py`, `synthetic.py`
- Test: `packages/ottima-core/tests/test_softsensor_artifact.py`, `test_softsensor_forward.py`

**Interfaces:**
- Consumes: nada.
- Produces (todos exportados de `ottima_core.softsensor`):
  - `METHODS: tuple[str, ...] = ("pls", "esn", "lstm")`, `BUFFER_STEPS = 256`, `RANGE_MARGIN = 0.05`, `MAX_ARTIFACT_BYTES = 8 * 1024 * 1024`.
  - `class ArtifactError(ValueError)`.
  - `class InputMeta(BaseModel)`: `name: str`, `eu: str = ""`, `min: float`, `max: float`.
  - `class ModelMeta(BaseModel)` (`extra="forbid"`, `allow_inf_nan=False`): `schema_version: Literal[1]`, `method: Literal["pls","esn","lstm"]`, `period_s: float` (`gt=0`), `inputs: list[InputMeta]` (1 a 32), `output_name: str`, `output_eu: str = ""`, `hyperparams: dict[str, float]`, `warmup_steps: int` (`ge=1`, `le=256`), `metrics: dict[str, float] = {}`, `trained_at: datetime`, `dataset_ids: list[int] = []`.
  - `def pack_weights(arrays: Mapping[str, np.ndarray]) -> bytes` — converte para `float32`, `np.savez_compressed`; levanta `ArtifactError` acima de `MAX_ARTIFACT_BYTES`.
  - `def unpack_weights(blob: bytes) -> dict[str, np.ndarray]` — `np.load(..., allow_pickle=False)`; qualquer falha de leitura vira `ArtifactError`.
  - `@dataclass(frozen=True) class LoadedModel`: `model_id: int`, `meta: ModelMeta`, `weights: dict[str, np.ndarray]`; propriedade `n_inputs`.
  - `def load_model(model_id: int, meta: Mapping[str, Any], blob: bytes) -> LoadedModel` — valida `meta`, as chaves exigidas do método e as formas contra `n_inputs`; levanta `ArtifactError`.
  - `def predict(model: LoadedModel, window: np.ndarray) -> float` — `window` tem forma `[warmup_steps, n_inputs]`, em unidade de engenharia, mais antiga primeiro. Devolve em unidade de engenharia; pode devolver não finito.
  - `synthetic.pls(w: Sequence[float], b: float, *, period_s: float = 1.0, ranges: Sequence[tuple[float, float]] | None = None) -> tuple[ModelMeta, bytes]`, `synthetic.esn(n_inputs: int, *, units: int = 20, warmup: int = 5, seed: int = 42, period_s: float = 1.0)`, `synthetic.lstm(n_inputs: int, *, units: int = 4, layers: int = 2, sequence_length: int = 3, seed: int = 42, period_s: float = 1.0)`, as três com o mesmo tipo de retorno. `ranges` ausente vira `(-1e6, 1e6)` por entrada.

Chaves de pesos por método (spec §6):
- `pls`: `w` `[n_inputs]`, `b` `[1]`.
- `esn`: `W` `[u,u]`, `Win` `[u,n_inputs]`, `bias` `[u]`, `Wout` `[u]`, `b_out` `[1]`, `lr` `[1]`, `x_mean`, `x_std` `[n_inputs]`, `y_mean`, `y_std` `[1]`.
- `lstm`: por camada `k` (0-based) `w_ih_{k}` `[4u, in_k]`, `w_hh_{k}` `[4u,u]`, `b_ih_{k}`, `b_hh_{k}` `[4u]`; `fc_w` `[u]`, `fc_b` `[1]`; `x_mean`, `x_std`, `y_mean`, `y_std`. `in_0 = n_inputs`, `in_k = u` para `k > 0`. O número de camadas é inferido das chaves.

- [ ] **Step 1: Escrever os testes que falham**

`test_softsensor_artifact.py`:

```python
def test_pack_unpack_preserva_valores_em_float32():
    blob = pack_weights({"w": np.array([1.5, -2.0]), "b": np.array([0.25])})
    out = unpack_weights(blob)
    assert out["w"].dtype == np.float32
    np.testing.assert_allclose(out["w"], [1.5, -2.0])

def test_unpack_recusa_bytes_truncados():
    blob = pack_weights({"w": np.zeros(4), "b": np.zeros(1)})
    with pytest.raises(ArtifactError):
        unpack_weights(blob[: len(blob) // 2])

def test_unpack_nunca_aceita_pickle():
    buf = io.BytesIO()
    np.savez(buf, w=np.array([object()], dtype=object))
    with pytest.raises(ArtifactError):
        unpack_weights(buf.getvalue())

def test_pack_recusa_acima_do_teto():
    grande = np.random.default_rng(0).random(3_000_000)  # ~12 MB em float32, incompressível
    with pytest.raises(ArtifactError):
        pack_weights({"w": grande, "b": np.zeros(1)})

def test_load_model_recusa_forma_errada():
    meta, _ = synthetic.pls([1.0, 2.0], 0.0)
    blob = pack_weights({"w": np.zeros(3), "b": np.zeros(1)})  # 3 pesos, 2 entradas
    with pytest.raises(ArtifactError):
        load_model(1, meta.model_dump(mode="json"), blob)

def test_load_model_recusa_chave_ausente():
    meta, _ = synthetic.pls([1.0], 0.0)
    with pytest.raises(ArtifactError):
        load_model(1, meta.model_dump(mode="json"), pack_weights({"w": np.zeros(1)}))

def test_meta_recusa_mais_de_32_entradas_e_warmup_fora_de_1_256(): ...
```

`test_softsensor_forward.py`:

```python
def _modelo(par):  # par = (ModelMeta, bytes)
    return load_model(1, par[0].model_dump(mode="json"), par[1])

def test_pls_e_o_produto_escalar_mais_o_termo_independente():
    m = _modelo(synthetic.pls([2.0, -1.0], 0.5))
    assert predict(m, np.array([[3.0, 4.0]])) == pytest.approx(2.5)

def test_esn_e_funcao_pura_da_janela():
    m = _modelo(synthetic.esn(2, warmup=5))
    janela = np.random.default_rng(1).random((5, 2))
    assert predict(m, janela) == predict(m, janela.copy())

def test_esn_valor_fixo_com_semente_fixa():
    m = _modelo(synthetic.esn(2, units=20, warmup=5, seed=42))
    janela = np.linspace(0.0, 1.0, 10).reshape(5, 2)
    assert predict(m, janela) == pytest.approx(ESN_GOLDEN, rel=1e-5)

def test_esn_confere_com_a_recorrencia_escrita_por_extenso():
    # Reimplementa no teste, com laço Python e sem vetorizar a janela:
    # s = 0; para cada linha x: s = (1-lr)*s + lr*tanh(W@s + Win@((x-x_mean)/x_std) + bias)
    # y = (Wout@s + b_out)*y_std + y_mean
    ...

def test_lstm_com_pesos_zero_devolve_o_bias_da_camada_final_despadronizado(): ...

def test_lstm_confere_com_a_celula_escrita_por_extenso():
    # Reimplementa no teste, escalar por escalar, a célula do PyTorch:
    # gates = w_ih@x + b_ih + w_hh@h + b_hh ; ordem i, f, g, o (blocos de u linhas)
    # c = sigmoid(f)*c + sigmoid(i)*tanh(g) ; h = sigmoid(o)*tanh(c)
    ...

def test_predict_devolve_nao_finito_sem_levantar():
    m = _modelo(synthetic.pls([1.0], 0.0))
    assert not math.isfinite(predict(m, np.array([[float("inf")]])))
```

`ESN_GOLDEN` é gravado no teste na primeira vez que o Step 4 passar em todos os outros testes: rode, copie o valor impresso para a constante e mantenha. Ele trava regressão; a prova de corretude do ESN é `test_esn_confere_com_a_recorrencia_escrita_por_extenso`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest packages/ottima-core/tests/test_softsensor_artifact.py packages/ottima-core/tests/test_softsensor_forward.py -q`
Expected: FAIL com `ModuleNotFoundError: ottima_core.softsensor`.

- [ ] **Step 3: Implementar** os quatro arquivos com as assinaturas do bloco Interfaces.

Pontos que a assinatura não decide:
- `x_std` igual a zero é tratado como `1.0` na padronização (entrada constante no treino).
- `synthetic.esn` gera `W` denso com `rng.normal`, reescala para raio espectral `0.9`, `Win` e `bias` com `rng.uniform(-1, 1)`, `Wout` com `rng.normal`, `lr = 0.3`, médias zero e desvios um. `synthetic.lstm` gera todos os pesos com `rng.normal(scale=0.5)`. Ambos usam `np.random.default_rng(seed)` e preenchem `warmup_steps` com `warmup` / `sequence_length`.
- `predict` não captura overflow: `np.errstate(all="ignore")` em volta da conta.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest packages/ottima-core/tests/test_softsensor_artifact.py packages/ottima-core/tests/test_softsensor_forward.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/ottima-core/src/ottima_core/softsensor packages/ottima-core/tests/test_softsensor_artifact.py packages/ottima-core/tests/test_softsensor_forward.py
git commit -m "feat(softsensor): artefato numérico e inferência PLS/ESN/LSTM em numpy"
```

---

### Task 2: Buffer de amostras e regra de qualidade (RF-583, ADR-046 D5)

**Files:**
- Create: `packages/ottima-core/src/ottima_core/softsensor/window.py`
- Test: `packages/ottima-core/tests/test_softsensor_window.py`

**Interfaces:**
- Consumes: `LoadedModel`, `predict`, `BUFFER_STEPS`, `RANGE_MARGIN` (Task 1); `Quality` de `ottima_core.signal`.
- Produces:
  - `class SampleBuffer`: `__init__(self, n_inputs: int, capacity: int = BUFFER_STEPS)`; `push(self, values: Sequence[float | None], quality: Quality) -> None` (qualquer `None` ou não finito força `Quality.BAD` e grava `nan`); `preload(self, values: np.ndarray, qualities: Sequence[Quality]) -> None` (substitui o conteúdo; mais antiga primeiro); `__len__`; `last(self, k: int) -> tuple[np.ndarray, tuple[Quality, ...]] | None` (`None` se houver menos de `k`); `copy(self) -> SampleBuffer`.
  - `Reason = Literal["ok", "incomplete", "bad_sample", "non_finite", "uncertain", "extrapolating"]`
  - `@dataclass(frozen=True) class Evaluation`: `value: float | None`, `quality: Quality`, `reason: Reason`.
  - `def evaluate(model: LoadedModel, buffer: SampleBuffer) -> Evaluation`.

Regra de `evaluate`, na ordem (spec §5.4):
1. `buffer.last(K)` é `None` → `Evaluation(None, BAD, "incomplete")`.
2. Alguma das `K` qualidades é BAD → `(None, BAD, "bad_sample")`.
3. Calcula `predict`. Não finito → `(None, BAD, "non_finite")`.
4. Alguma entrada de alguma das `K` linhas fora de `[min - 0.05*span, max + 0.05*span]` → `(valor, UNCERTAIN, "extrapolating")`.
5. Alguma das `K` qualidades é UNCERTAIN → `(valor, UNCERTAIN, "uncertain")`.
6. Senão `(valor, GOOD, "ok")`.

- [ ] **Step 1: Escrever os testes que falham**

```python
PLS = lambda **kw: load_model(1, *_dump(synthetic.pls([1.0, 1.0], 0.0, **kw)))
LSTM3 = lambda: load_model(2, *_dump(synthetic.lstm(2, sequence_length=3)))

def test_janela_incompleta_e_bad_sem_valor():
    buf = SampleBuffer(2); buf.push([1.0, 1.0], Quality.GOOD)
    assert evaluate(LSTM3(), buf) == Evaluation(None, Quality.BAD, "incomplete")

def test_amostra_bad_na_janela_contamina_ate_sair():
    buf = SampleBuffer(2)
    buf.push([1.0, 1.0], Quality.BAD)
    for _ in range(2): buf.push([1.0, 1.0], Quality.GOOD)
    assert evaluate(LSTM3(), buf).reason == "bad_sample"
    buf.push([1.0, 1.0], Quality.GOOD)          # a BAD saiu da janela de 3
    assert evaluate(LSTM3(), buf).quality is Quality.GOOD

def test_porta_sem_valor_vira_bad():
    buf = SampleBuffer(2); buf.push([None, 1.0], Quality.GOOD)
    assert evaluate(PLS(), buf).reason == "bad_sample"

def test_uncertain_na_janela_rebaixa_mas_calcula():
    buf = SampleBuffer(2); buf.push([1.0, 2.0], Quality.UNCERTAIN)
    ev = evaluate(PLS(), buf)
    assert (ev.value, ev.quality, ev.reason) == (pytest.approx(3.0), Quality.UNCERTAIN, "uncertain")

def test_fora_da_faixa_alem_de_5_por_cento_e_extrapolacao():
    m = PLS(ranges=[(0.0, 10.0), (0.0, 10.0)])
    buf = SampleBuffer(2); buf.push([10.5, 5.0], Quality.GOOD)     # exatamente no limite
    assert evaluate(m, buf).quality is Quality.GOOD
    buf.push([10.51, 5.0], Quality.GOOD)
    assert evaluate(m, buf).reason == "extrapolating"

def test_faixa_de_span_zero_aceita_o_proprio_valor():
    m = PLS(ranges=[(7.0, 7.0), (0.0, 10.0)])
    buf = SampleBuffer(2); buf.push([7.0, 5.0], Quality.GOOD)
    assert evaluate(m, buf).quality is Quality.GOOD

def test_resultado_nao_finito_e_bad_sem_valor():
    m = PLS(); buf = SampleBuffer(2); buf.push([1e308, 1e308], Quality.GOOD)
    # w=[1,1] em float32 estoura: predict devolve inf
    assert evaluate(m, buf) == Evaluation(None, Quality.BAD, "non_finite")

def test_buffer_e_circular_em_256():
    buf = SampleBuffer(1)
    for i in range(300): buf.push([float(i)], Quality.GOOD)
    assert len(buf) == 256 and buf.last(1)[0][0, 0] == 299.0

def test_preload_substitui_e_copy_e_independente(): ...
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest packages/ottima-core/tests/test_softsensor_window.py -q` → FAIL (`ImportError`).
- [ ] **Step 3: Implementar `window.py`** e exportar de `softsensor/__init__.py`. Estrutura: `collections.deque(maxlen=capacity)` de `(np.ndarray, Quality)`.
- [ ] **Step 4: Rodar e ver passar** — mesmo comando → PASS.
- [ ] **Step 5: Commit**

```bash
git add packages/ottima-core/src/ottima_core/softsensor/window.py packages/ottima-core/src/ottima_core/softsensor/__init__.py packages/ottima-core/tests/test_softsensor_window.py
git commit -m "feat(softsensor): buffer de amostras e regra de qualidade da saída"
```

---

### Task 3: Tipos de bloco, config e contrato de portas (RF-301, RF-581)

**Files:**
- Modify: `packages/ottima-core/src/ottima_core/flowgraph/parse.py` (`NodeType` linha ~15, `NODE_TYPES` linha 36, `_CONFIG_KEYS` linha 62, união `NodeConfig` linha 637, despacho de `_parse_config` linha ~841)
- Modify: `packages/ottima-core/src/ottima_core/flowgraph/validate.py` (`_output_handles` linha 155, `_input_handles` linha 193)
- Modify: `packages/ottima-core/src/ottima_core/flowgraph/__init__.py`, `packages/ottima-core/src/ottima_core/contracts_export.py` (`PORT_CONTRACTS` linha 141, `_NODE_CONFIG_MODELS` linha 359)
- Modify: `packages/ottima-mcp/src/ottima_mcp/server.py` (`TipoBlocoLiteral` linha 494), `packages/ottima-mcp/tests/test_server.py`
- Modify (gerado): `frontend/src/lib/contracts.gen.ts`
- Test: `packages/ottima-core/tests/test_flowgraph_soft_sensor.py` (criar)

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces, exportados de `ottima_core.flowgraph`:
  - `MAX_SOFT_SENSOR_INPUTS = 32`
  - `SOFT_SENSOR_METHOD: dict[str, str] = {"soft_sensor_pls": "pls", "soft_sensor_esn": "esn", "soft_sensor_lstm": "lstm"}` e `SOFT_SENSOR_TYPES = tuple(SOFT_SENSOR_METHOD)`.
  - `class SoftSensorConfig(BaseModel)` (`extra="forbid"`): `n_inputs: int = Field(ge=1, le=MAX_SOFT_SENSOR_INPUTS)`, `output_eu: str = ""`.
  - Os três tipos ao FIM de `NODE_TYPES`, na ordem `soft_sensor_pls`, `soft_sensor_esn`, `soft_sensor_lstm`.
  - Portas: entradas `IN1..INn` (todas obrigatórias, numéricas), saída `out` (numérica).

- [ ] **Step 1: Escrever o teste que falha.** Copie o esqueleto (`_node`, `_leitura`, `parse_errors`, `errors_of`) de `packages/ottima-core/tests/test_flowgraph_filtros.py` e escreva, parametrizado pelos três tipos:

```python
@pytest.mark.parametrize("tipo", SOFT_SENSOR_TYPES)
def test_parseia_com_config_tipada(tipo): ...          # config == SoftSensorConfig(n_inputs=2, output_eu="ppm")
def test_output_eu_e_opcional(tipo): ...               # ausente -> ""
def test_n_inputs_aceita_1_e_32(tipo): ...
def test_n_inputs_recusa_0_e_33(tipo): ...             # GraphParseError citando 'n_inputs'
def test_chave_desconhecida_e_recusada(tipo): ...      # data com "model_id": 3 -> erro "chave desconhecida"
def test_portas_declaradas(tipo):
    assert graph_ports(grafo)["ss"] == NodePorts(inputs=("IN1", "IN2"), outputs=("out",))
def test_entrada_desconectada_e_erro(tipo): ...        # IN2 sem aresta -> erro de entrada obrigatória
def test_recusa_entrada_booleana(tipo): ...            # opc_read de tag bool em IN1
def test_identidade_funcional_ignora_rotulo_e_ordem(tipo): ...
def test_tipos_estao_ao_fim_de_node_types():
    assert NODE_TYPES[-3:] == ("soft_sensor_pls", "soft_sensor_esn", "soft_sensor_lstm")
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest packages/ottima-core/tests/test_flowgraph_soft_sensor.py -q` → FAIL (`ImportError: SOFT_SENSOR_TYPES`).
- [ ] **Step 3: Implementar em `parse.py` e `validate.py`.** `_CONFIG_KEYS[tipo] = ("n_inputs", "output_eu")`. O parser segue o molde de `_parse_fuzzy_config` (validação Pydantic com erros traduzidos para a lista `errors`). Nenhuma validação de conteúdo em `validate_graph` além das portas: o modelo não está no grafo.
- [ ] **Step 4: `PORT_CONTRACTS`.** Uma entrada por tipo, `"dynamic": True`, `"source": "config.n_inputs (RF-581, ADR-046)"`, `"rules"` com uma regra `{"direction": "input", "prefix": "IN", "count_field": "n_inputs", "max": MAX_SOFT_SENSOR_INPUTS, "type": "num"}` e `"ports": [{"name": "out", "direction": "output", "type": "num"}]`, mais `"default_counts": {"n_inputs": 2}`. Nenhuma entrada dinâmica existente tem porta fixa: se `frontend/scripts/generate-contracts.mjs` ou o tipo gerado recusarem a mistura `rules` + `ports`, ajuste o gerador o mínimo necessário e descreva o ajuste no relato da tarefa. `SoftSensorConfig` entra em `_NODE_CONFIG_MODELS`.
- [ ] **Step 5: MCP.** Acrescentar os três tipos a `TipoBlocoLiteral` e ao teste que confere a lista contra `NODE_TYPES`.
- [ ] **Step 6: Regenerar o contrato e rodar tudo**

Run: `cd frontend && npm run generate:contracts && cd .. && uv run pytest packages/ottima-core/tests/test_flowgraph_soft_sensor.py packages/ottima-core/tests/test_contracts_export.py packages/ottima-mcp/tests -q`
Expected: PASS. `git diff --stat frontend/src/lib/contracts.gen.ts` mostra só adições.

- [ ] **Step 7: Commit**

```bash
git add packages/ottima-core/src/ottima_core/flowgraph packages/ottima-core/src/ottima_core/contracts_export.py packages/ottima-core/tests/test_flowgraph_soft_sensor.py packages/ottima-mcp/src/ottima_mcp/server.py packages/ottima-mcp/tests/test_server.py frontend/src/lib/contracts.gen.ts
git commit -m "feat(flowgraph): tipos soft_sensor_pls/esn/lstm com config e portas"
```

---

### Task 4: Tabelas de modelo e vínculo (ADR-046 D6)

**Files:**
- Create: `packages/ottima-core/src/ottima_core/models/soft_sensor.py`, `packages/ottima-core/alembic/versions/0018_soft_sensor.py`
- Modify: `packages/ottima-core/src/ottima_core/models/__init__.py`
- Test: `services/api/tests/test_soft_sensor_models.py` (criar; o `ottima-core` não tem fixture de banco: use `db_session` de `services/api/tests/conftest.py`, como `test_historized_vars.py`)

**Interfaces:**
- Produces:
  - `SoftSensorModel` (`soft_sensor_models`, com `TimestampMixin`): `id` BigInteger identity PK; `project_id` → `projects.id` `ON DELETE CASCADE`; `name` Text; `method` Text com check `IN ('pls','esn','lstm')`; `period_s` Double; `n_inputs` SmallInteger; `input_tag_ids` `ARRAY(BigInteger)` com default `'{}'`; `meta` JSONB; `weights` LargeBinary, mapeado com **`deferred=True`**; `created_by` Text. `UNIQUE(project_id, name)` (`uq_soft_sensor_models_project_name`). (`weights` chega a 8 MB e as listagens de modelos e blocos serão consultadas por polling na SV-3: quem precisa dos pesos — carga no deploy, comando de troca, export — pede com `undefer(SoftSensorModel.weights)`.)
  - `SoftSensorBinding` (`soft_sensor_bindings`): PK `(flow_id, block_id)`; `flow_id` → `flows.id` `ON DELETE CASCADE`; `block_id` Text; `desired_model_id`, `active_model_id`, `candidate_model_id` BigInteger nulos → `soft_sensor_models.id` **sem cláusula `ON DELETE`** (o default `NO ACTION`); `updated_by` Text; `updated_at`.

`NO ACTION`, e não `RESTRICT`: os dois impedem apagar um modelo vinculado, mas `RESTRICT` é checado na hora e barraria a cascata do projeto, que apaga flows (e vínculos) e modelos no mesmo comando. `input_tag_ids` não tem FK (é array): tag apagada fica como id órfão, e a Task 6 trata isso.

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_nome_de_modelo_e_unico_por_projeto(session): ...       # IntegrityError no segundo
async def test_modelo_vinculado_nao_pode_ser_apagado(session): ...    # delete do modelo -> IntegrityError
async def test_apagar_o_flow_apaga_o_vinculo(session): ...
async def test_apagar_projeto_com_modelo_vinculado(session):
    # projeto com 1 flow, 1 modelo e 1 vínculo (desired = active = modelo)
    await session.delete(projeto); await session.commit()
    assert (await session.scalar(select(func.count()).select_from(SoftSensorModel))) == 0
async def test_metodo_fora_do_vocabulario_e_recusado(session): ...
async def test_select_do_modelo_nao_carrega_os_pesos(session):
    # select(SoftSensorModel) -> "weights" em sqlalchemy.inspect(obj).unloaded
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest services/api/tests/test_soft_sensor_models.py -q` → FAIL.
- [ ] **Step 3: Implementar os modelos e a migration `0018`** (`down_revision` = a revisão de `0017_loop_setpoints_channel.py`). Tabelas comuns: não são hypertables e não entram em nenhuma policy de retenção.
- [ ] **Step 4: Rodar e ver passar**, e conferir que a migration sobe e desce: `uv run pytest services/api/tests/test_soft_sensor_models.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add packages/ottima-core/src/ottima_core/models/soft_sensor.py packages/ottima-core/src/ottima_core/models/__init__.py packages/ottima-core/alembic/versions/0018_soft_sensor.py services/api/tests/test_soft_sensor_models.py
git commit -m "feat(db): tabelas soft_sensor_models e soft_sensor_bindings"
```

---

### Task 5: `SoftSensorBlock` — passo de modelo, qualidade e troca (RF-582, RF-583, RF-584)

**Files:**
- Create: `services/flow-runtime/src/ottima_flow_runtime/blocks/soft_sensor.py`
- Modify: `packages/ottima-core/src/ottima_core/bus.py` (constantes `KIND_*`, junto das demais, linha ~345)
- Test: `services/flow-runtime/tests/test_soft_sensor_block.py`, `services/flow-runtime/tests/test_soft_sensor_swap.py`

**Interfaces:**
- Consumes: `LoadedModel`, `SampleBuffer`, `evaluate`, `Evaluation` (Tasks 1 e 2); `Block`, `Signal` de `blocks/base.py`.
- Produces:
  - Em `ottima_core.bus`: `KIND_SOFT_SENSOR_MODEL_ACTIVATED = "soft_sensor_model_activated"`, `KIND_SOFT_SENSOR_MODEL_REJECTED = "soft_sensor_model_rejected"`, `KIND_SOFT_SENSOR_MODEL_MISSING = "soft_sensor_model_missing"`, `KIND_SOFT_SENSOR_EXTRAPOLATING = "soft_sensor_extrapolating"`, `KIND_SOFT_SENSOR_PREWARM_SKIPPED = "soft_sensor_prewarm_skipped"`.
  - `@dataclass(frozen=True) class BindingUpdate`: `active_model_id: int | None`, `candidate_model_id: int | None`, `reset_desired_to_active: bool = False`.
  - `class SoftSensorBlock(Block)`:

```python
def __init__(
    self,
    block_id: str,
    *,
    n_inputs: int,
    ts_seconds: float,
    model: LoadedModel | None,
    prewarm: SampleBuffer | None,
    missing_reason: str | None,
    emit_event: Callable[..., Awaitable[None]],      # kwargs de publish_event, sem `ts`
    persist: Callable[[BindingUpdate], Awaitable[None]],
) -> None
def set_candidate(self, model: LoadedModel, buffer: SampleBuffer | None) -> None
@property
def active_model_id(self) -> int | None
@property
def candidate_model_id(self) -> int | None
@property
def active_period_s(self) -> float | None
def active_buffer_copy(self) -> SampleBuffer | None
```

Comportamento que os testes pinam:
- **Slot** = modelo + `SampleBuffer` + divisor `n = round(period_s / ts_seconds)`. Um slot para o modelo em uso, um para o candidato. A cada varredura `i` (contador próprio do bloco, a partir de 0), o slot empurra uma amostra e avalia quando `i % n == 0`.
- Amostra = valores das portas `IN1..INn` naquela varredura, com a pior qualidade entre elas (porta ausente em `inputs` ou com `v is None` conta como BAD).
- PLS avalia inline; ESN e LSTM por `asyncio.get_running_loop().run_in_executor(None, evaluate, model, buffer.copy())`.
- Saída `out`: valor = último valor calculado pelo modelo em uso (`None` enquanto nunca houve um); qualidade = `min(qualidade da última avaliação, pior porta da varredura atual)`. Avaliação sem valor (`incomplete`, `bad_sample`, `non_finite`) deixa o valor anterior e marca BAD.
- Sem modelo em uso: `out = Signal(None)`; emite `soft_sensor_model_missing` uma vez (payload `flow_id` não está no bloco: o `emit_event` injetado já o carrega; aqui vão `block_id` e `reason = missing_reason or "no_model"`).
- `soft_sensor_extrapolating` sai só na borda: `payload {"block_id", "active": True}` quando a avaliação passa a `extrapolating`, `{"active": False}` quando deixa de ser.
- **Promoção** (spec §5.6), checada no passo do candidato: o candidato calculou valor **e** `qualidade do candidato >= qualidade atual da saída`. Ao promover: o slot do candidato vira o em uso, o antigo é descartado, `await persist(BindingUpdate(active_model_id=novo, candidate_model_id=None))`, evento `soft_sensor_model_activated` (info) com `block_id`, `model_id`, `previous_model_id`.
- **Sem modelo em uso**, `set_candidate` promove na hora (mesmos `persist` e evento), mesmo com janela incompleta.
- **Rejeição:** o candidato tem `max(2 * K * period_s, 60.0)` segundos, contados em varreduras (`ceil(prazo / ts_seconds)`), sem relógio de parede. Vencido: descarta, `persist(BindingUpdate(active_model_id=atual, candidate_model_id=None, reset_desired_to_active=True))`, evento `soft_sensor_model_rejected` (warning) com `reason` igual ao `reason` da última avaliação do candidato.
- **`set_candidate` só enfileira.** Ele guarda o pedido numa variável e retorna; quem aplica é o `step`, no **início** da varredura seguinte, antes de ler as portas. Motivo: o `step` tem pontos de `await` (`run_in_executor`, `persist`) e o handler do comando roda sob o lock do supervisor, que não é o do laço de varredura. Aplicado no meio de um `step`, o pedido poderia trocar o candidato entre a avaliação e a promoção e promover um modelo já descartado.
- Segundo `set_candidate` durante a troca substitui o candidato e reinicia o prazo (o último pedido enfileirado vence).
- `persist` e `emit_event` que levantam exceção são capturados e logados: `step` nunca levanta.
- `reset()` (deploy/stop) zera contador de varredura e o último valor, e **mantém** modelos e buffers.

- [ ] **Step 1: Escrever os testes que falham.** Use um harness local:

```python
def bloco(model=None, *, ts=1.0, n_inputs=2, prewarm=None, missing_reason=None):
    eventos, gravacoes = [], []
    async def emit(**kw): eventos.append(kw)
    async def persist(u): gravacoes.append(u)
    b = SoftSensorBlock("ss", n_inputs=n_inputs, ts_seconds=ts, model=model, prewarm=prewarm,
                        missing_reason=missing_reason, emit_event=emit, persist=persist)
    return b, eventos, gravacoes

def entradas(*vals, q=Quality.GOOD):
    return {f"IN{i+1}": Signal(v, quality=q) for i, v in enumerate(vals)}
```

`test_soft_sensor_block.py`:

```python
async def test_sem_modelo_sai_none_bad_e_avisa_uma_vez(): ...          # 3 steps -> 1 evento model_missing
async def test_pls_sai_good_no_primeiro_passo():
    b, *_ = bloco(carregar(synthetic.pls([2.0, -1.0], 0.5)))
    out = (await b.step(entradas(3.0, 4.0)))["out"]
    assert (out.v, out.quality) == (pytest.approx(2.5), Quality.GOOD)
async def test_passo_de_modelo_a_cada_n_varreduras():
    # period_s=5, ts=1: só as varreduras 0, 5, 10 recalculam; entre elas o valor é mantido
async def test_entre_passos_porta_bad_rebaixa_a_saida_mantida(): ...
async def test_lstm_sem_prewarm_sai_none_ate_a_janela_encher():        # sequence_length=3 -> None, None, valor
async def test_lstm_com_prewarm_sai_good_no_primeiro_passo(): ...      # prewarm com 3 linhas GOOD
async def test_bad_no_meio_mantem_o_ultimo_valor_com_qualidade_bad():
    # LSTM K=3 aquecido; uma varredura com IN1 BAD -> out.v == valor anterior, out.quality BAD
    # por 3 passos; no 4o passo limpo volta GOOD com valor novo
async def test_porta_ausente_conta_como_bad(): ...
async def test_extrapolacao_emite_evento_so_na_borda(): ...            # entra: 1 evento active=True; fica: 0; sai: 1 active=False
async def test_persist_que_levanta_nao_derruba_o_step(): ...
async def test_reset_mantem_modelo_e_buffer(): ...
```

`test_soft_sensor_swap.py`:

```python
async def test_candidato_do_mesmo_periodo_e_promovido_no_passo_seguinte():
    # ativo PLS id=1; set_candidate(PLS id=2, buffer=b.active_buffer_copy()); 1 step
    # -> active_model_id == 2, gravacoes[-1] == BindingUpdate(2, None), evento activated
async def test_saida_nunca_piora_na_troca():
    # registra out.quality de todas as varreduras antes, durante e depois: nunca < GOOD
async def test_candidato_sem_valor_nao_e_promovido_mesmo_com_o_ativo_bad():
    # ativo com janela contaminada (BAD); candidato LSTM de janela maior ainda incompleta
    # -> continua o ativo; nada gravado
async def test_candidato_extrapolando_espera_e_e_rejeitado_no_prazo():
    # candidato com faixa estreita; saída atual GOOD; prazo = max(2*1*1, 60) = 60 varreduras
    # -> na varredura 60: BindingUpdate(1, None, reset_desired_to_active=True),
    #    evento rejected com reason="extrapolating"
async def test_candidato_de_outro_periodo_nao_herda_o_buffer():
    # ativo period_s=1 com buffer cheio; candidato period_s=5, buffer=None
    # -> o slot do candidato começa vazio e só empurra amostra nas varreduras múltiplas de 5
async def test_sem_modelo_em_uso_o_candidato_assume_na_hora(): ...
async def test_segundo_candidato_substitui_o_primeiro_e_reinicia_o_prazo(): ...
async def test_set_candidate_no_meio_de_um_step_so_vale_no_step_seguinte():
    # persist que, ao ser chamado na promoção do candidato id=2, chama b.set_candidate(id=3)
    # -> ao fim desse step: active_model_id == 2 e candidate_model_id is None
    # -> no step seguinte: candidate_model_id == 3 (ou já promovido, se válido)
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest services/flow-runtime/tests/test_soft_sensor_block.py services/flow-runtime/tests/test_soft_sensor_swap.py -q` → FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implementar `blocks/soft_sensor.py`** e as cinco constantes em `bus.py`. Módulo-doc no padrão de `blocks/kalman.py`, citando RF-582/583/584 e ADR-046.
- [ ] **Step 4: Rodar e ver passar** — mesmo comando → PASS.
- [ ] **Step 5: Commit**

```bash
git add services/flow-runtime/src/ottima_flow_runtime/blocks/soft_sensor.py packages/ottima-core/src/ottima_core/bus.py services/flow-runtime/tests/test_soft_sensor_block.py services/flow-runtime/tests/test_soft_sensor_swap.py
git commit -m "feat(flow-runtime): SoftSensorBlock com passo de modelo, qualidade e troca sem interrupção"
```

---

### Task 6: Grade sobre `samples`, carga no deploy e pré-aquecimento (RF-591, ADR-046 D9)

**Files:**
- Create: `packages/ottima-core/src/ottima_core/softsensor/grid.py`, `services/flow-runtime/src/ottima_flow_runtime/soft_sensor_seeds.py`
- Modify: `services/flow-runtime/src/ottima_flow_runtime/definition.py` (`build_definition` linha 123, `_instantiate` linha 285), `services/flow-runtime/src/ottima_flow_runtime/supervisor.py` (`_build` linha 560)
- Test: `services/flow-runtime/tests/test_soft_sensor_grid.py`, `services/flow-runtime/tests/test_soft_sensor_seeds.py` (os dois usam a fixture `session_factory` de `services/flow-runtime/tests/conftest.py`; o `ottima-core` não tem fixture de banco)

**Interfaces:**
- Consumes: `SampleBuffer`, `load_model`, `ArtifactError` (Tasks 1 e 2); `SoftSensorModel`, `SoftSensorBinding` (Task 4); `SoftSensorBlock`, `BindingUpdate` (Task 5); `SOFT_SENSOR_METHOD` (Task 3); `samples_table` de `ottima_core.models.timeseries`.
- Produces:
  - Em `ottima_core.softsensor.grid`:
    - `def staleness_limit_s(period_s: float) -> float` — `max(3 * period_s, 180.0)`.
    - `def grid_instants(end: datetime, period_s: float, steps: int) -> list[datetime]` — `end - k*period_s`, `k = steps-1 .. 0` (mais antigo primeiro).
    - `async def load_grid(session: AsyncSession, tag_ids: Sequence[int], *, end: datetime, period_s: float, steps: int) -> tuple[np.ndarray, list[Quality]]` — matriz `[steps, len(tag_ids)]` (`nan` na lacuna) e a pior qualidade por linha.
  - Em `soft_sensor_seeds`:
    - `@dataclass(frozen=True) class SoftSensorSeed`: `model: LoadedModel | None`, `prewarm: SampleBuffer | None`, `missing_reason: str | None`.
    - `def model_mismatch(model_method: str, model_n_inputs: int, model_period_s: float, *, block_type: str, n_inputs: int, ts_seconds: float) -> str | None` — devolve `"method"`, `"n_inputs"`, `"period"` ou `None`. `"period"` quando `period_s / ts_seconds` não é inteiro (tolerância `1e-9`) ou é menor que 1.
    - `async def load_seeds(session_factory: async_sessionmaker[AsyncSession], flow_id: int, graph: FlowGraph, *, ts_seconds: float, skip: Container[str], emit_event) -> dict[str, SoftSensorSeed]` — uma entrada por nó de sensor virtual **fora de `skip`**.
    - `def make_persist(session_factory, flow_id: int, block_id: str) -> Callable[[BindingUpdate], Awaitable[None]]`.
  - `build_definition(..., soft_sensor_seeds: Mapping[str, SoftSensorSeed] | None = None)`, que repassa `soft_sensor_seed=(soft_sensor_seeds or {}).get(node.id)` a `_instantiate(..., soft_sensor_seed: SoftSensorSeed | None = None)`.

Regra de cada ponto da grade (spec §5.7 e §7.3): a **última** amostra da tag com `ts <= instante` e `ts > instante - staleness_limit`. Sem amostra, ou amostra com `quality = 2` / `value IS NULL` → `nan` e `Quality.BAD`. `quality = 1` → `UNCERTAIN`. `quality = 0` → `GOOD`.

A consulta é **uma instrução SQL**, não um laço em Python: `unnest` dos instantes × `unnest` dos `tag_ids`, com `LEFT JOIN LATERAL (SELECT value, quality FROM samples WHERE tag_id = t AND ts <= i AND ts > i - limite ORDER BY ts DESC LIMIT 1)`. Com 256 passos de 600 s a janela cobre 42 horas; trazer as linhas cruas para o Python não cabe nos 5 s.

Regra de `load_seeds` para cada bloco:
1. Sem vínculo, ou `desired_model_id` nulo → `SoftSensorSeed(None, None, "no_model")`.
2. `load_model` levanta `ArtifactError` → `(None, None, "corrupt")`.
3. `model_mismatch` devolve motivo → `(None, None, motivo)`.
4. Modelo válido: grava `active_model_id = desired_model_id`, `candidate_model_id = NULL` no vínculo.
5. Pré-aquecimento: se `len(input_tag_ids) != n_inputs` ou algum id não existe em `tags` → sem buffer, evento `soft_sensor_prewarm_skipped` (info) com `reason = "tags"`. Senão `await asyncio.wait_for(load_grid(..., end=agora, period_s=modelo, steps=256), 5.0)`; `TimeoutError` ou erro de banco → sem buffer, evento com `reason = "timeout"` ou `"error"`. Com dados, `SampleBuffer.preload`.

**Sessões e prazo (três regras que os testes unitários não pegam sozinhos):**
- `load_seeds` **não usa a sessão de `_build`**. Essa sessão só lê e nunca dá `commit` (nenhum `commit()` em `supervisor.py`); uma escrita nela se perde. `load_seeds` abre a própria sessão por `session_factory`, grava o passo 4 e dá `commit` explícito. O teste lê o vínculo de volta por **outra** sessão.
- O pré-aquecimento roda em **mais uma** sessão própria. `asyncio.wait_for` cancela a consulta em andamento, e uma sessão cancelada no meio de uma consulta não pode continuar sendo usada por `carregar_sp_seeds`/`carregar_loop_seeds`.
- O prazo de 5 s é **um por deploy**, não por bloco: `load_seeds` roda sob o lock do supervisor. Calcule `deadline = loop.time() + PREWARM_TIMEOUT_S` uma vez e dê a cada bloco só o que sobrar; esgotado, os blocos restantes sobem sem pré-aquecer, com `reason = "timeout"`.

O índice `ix_samples_tag_ts (tag_id, ts DESC)` já existe (migration `0002_timescale.py:24`) e é o que sustenta a consulta `LATERAL`; nenhuma migration nova para isso.

Em `Supervisor._build`, `skip` é o conjunto dos `block_id` de `reuse` cuja config funcional é igual à do nó novo (os que `build_definition` vai reaproveitar): bloco reaproveitado mantém modelo e buffer vivos e não é recarregado.

- [ ] **Step 1: Escrever os testes que falham**

`test_soft_sensor_grid.py` (banco efêmero; insira direto em `samples_table`; `session` abaixo é uma sessão aberta da `session_factory`):

```python
def test_limite_de_idade(): assert staleness_limit_s(1) == 180.0 and staleness_limit_s(600) == 1800.0
def test_instantes_do_mais_antigo_ao_mais_novo(): ...
async def test_ponto_usa_a_ultima_amostra_em_ou_antes_do_instante(session): ...
async def test_amostra_posterior_ao_instante_nunca_entra(session): ...
async def test_amostra_mais_velha_que_o_limite_e_lacuna(session): ...      # nan + BAD
async def test_ultima_amostra_bad_e_lacuna_mesmo_com_boa_anterior(session):
    # t-10s GOOD 5.0 ; t-2s quality=2 value NULL  -> ponto em t é nan/BAD (não olha para trás)
async def test_amostra_uncertain_mantem_valor_e_rebaixa_a_linha(session): ...
async def test_qualidade_da_linha_e_a_pior_entre_as_tags(session): ...
async def test_ordem_das_colunas_segue_tag_ids(session): ...
```

`test_soft_sensor_seeds.py`:

```python
def test_model_mismatch(): 
    assert model_mismatch("pls", 2, 5.0, block_type="soft_sensor_esn", n_inputs=2, ts_seconds=1.0) == "method"
    assert model_mismatch("pls", 3, 5.0, block_type="soft_sensor_pls", n_inputs=2, ts_seconds=1.0) == "n_inputs"
    assert model_mismatch("pls", 2, 5.0, block_type="soft_sensor_pls", n_inputs=2, ts_seconds=2.0) == "period"
    assert model_mismatch("pls", 2, 0.5, block_type="soft_sensor_pls", n_inputs=2, ts_seconds=1.0) == "period"
    assert model_mismatch("pls", 2, 6.0, block_type="soft_sensor_pls", n_inputs=2, ts_seconds=2.0) is None
async def test_deploy_carrega_o_desejado_e_grava_o_ativo(session_factory):
    # depois de load_seeds, abre OUTRA sessão e confere active_model_id == desired_model_id
async def test_prazo_de_preaquecimento_e_um_so_para_o_deploy(session_factory, monkeypatch):
    # 3 blocos; load_grid que dorme 0,4 s; PREWARM_TIMEOUT_S reduzido a 1,0 por monkeypatch
    # -> 2 blocos pré-aquecem, o 3o sobe sem buffer com evento reason="timeout";
    #    load_seeds retorna em menos de 1,5 s
async def test_sessao_do_chamador_segue_utilizavel_apos_timeout(session_factory, monkeypatch):
    # após um load_seeds com timeout, carregar_sp_seeds numa sessão aberta ANTES funciona
async def test_deploy_com_historico_integro_preaquece(session):          # buffer com 256 linhas GOOD
async def test_deploy_com_artefato_corrompido_sobe_sem_modelo(session):  # weights = b"lixo" -> missing_reason "corrupt"
async def test_reload_com_n_inputs_diferente_do_modelo(session):         # missing_reason "n_inputs"
async def test_tag_de_entrada_apagada_pula_o_preaquecimento(session):    # evento prewarm_skipped reason="tags", modelo carregado
async def test_consulta_lenta_pula_o_preaquecimento(session, monkeypatch):# load_grid que dorme 10 s, timeout reduzido por monkeypatch
async def test_bloco_reaproveitado_nao_e_recarregado(session): ...       # block_id em skip -> ausente do dict
async def test_build_definition_instancia_o_bloco_com_a_semente(): ...   # SoftSensorBlock.active_model_id == id
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest services/flow-runtime/tests/test_soft_sensor_grid.py services/flow-runtime/tests/test_soft_sensor_seeds.py -q` → FAIL.
- [ ] **Step 3: Implementar `grid.py` e `soft_sensor_seeds.py`.** `make_persist` abre sessão própria por gravação e faz `UPDATE` do vínculo; com `reset_desired_to_active`, também `desired_model_id = active_model_id`.
- [ ] **Step 4: Ligar em `definition.py` e `supervisor.py`.** Em `_instantiate`, antes do `return TfsBlock(...)` final:

```python
if node.type in SOFT_SENSOR_TYPES:
    seed = soft_sensor_seed or SoftSensorSeed(None, None, "no_model")
    return SoftSensorBlock(node.id, n_inputs=config.n_inputs, ts_seconds=ts_seconds,
                           model=seed.model, prewarm=seed.prewarm,
                           missing_reason=seed.missing_reason,
                           emit_event=emit_event, persist=make_persist(session_factory, flow_id, node.id))
```

`emit_event` é a mesma closure sobre `publish_event` que `_instantiate_mpc` monta (linha ~430), com `origin="flow-runtime"` e `flow_id` no payload. Em `_build`, chame `load_seeds` logo depois de carregar `historized_vars` e passe o resultado a `build_definition`.

- [ ] **Step 5: Rodar e ver passar**, mais a regressão do que foi tocado

Run: `uv run pytest services/flow-runtime/tests/test_soft_sensor_grid.py services/flow-runtime/tests/test_soft_sensor_seeds.py services/flow-runtime/tests/test_definition.py services/flow-runtime/tests/test_hotswap.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/ottima-core/src/ottima_core/softsensor/grid.py packages/ottima-core/src/ottima_core/softsensor/__init__.py services/flow-runtime/src/ottima_flow_runtime/soft_sensor_seeds.py services/flow-runtime/src/ottima_flow_runtime/definition.py services/flow-runtime/src/ottima_flow_runtime/supervisor.py services/flow-runtime/tests/test_soft_sensor_grid.py services/flow-runtime/tests/test_soft_sensor_seeds.py
git commit -m "feat(flow-runtime): carga de modelo no deploy e pré-aquecimento pelo histórico"
```

---

### Task 7: Comando `soft_sensor_model` no runtime (RF-584)

**Files:**
- Modify: `services/flow-runtime/src/ottima_flow_runtime/supervisor.py` (mapa `handlers` linha 294; método novo ao lado de `_fuzzy_command` linha 327), `services/flow-runtime/src/ottima_flow_runtime/soft_sensor_seeds.py`
- Test: `services/flow-runtime/tests/test_soft_sensor_command.py` (criar; molde: os testes de `fuzzy_sp` em `test_fuzzy_setpoint.py` e os helpers de `runtime_test_helpers.py`)

**Interfaces:**
- Consumes: `SoftSensorBlock.set_candidate`, `active_period_s`, `active_buffer_copy` (Task 5); `load_grid`, `model_mismatch`, `make_persist` (Task 6).
- Produces: `async def soft_sensor_command(session_factory, runtime, command: FlowCommand, *, emit_event) -> None` em `soft_sensor_seeds.py`; entrada `"soft_sensor_model": self._soft_sensor_command` no mapa de handlers. Contrato do comando: `FlowCommand(cmd="soft_sensor_model", args={"block_id": str, "model_id": int})`.

Regra:
1. Flow não está rodando, bloco inexistente ou não é `SoftSensorBlock` → retorna sem efeito (a API já gravou `desired_model_id`; o próximo deploy carrega).
2. Lê o modelo do banco; `ArtifactError` ou `model_mismatch` → evento `soft_sensor_model_rejected` com `reason` `"corrupt"` / `"method"` / `"n_inputs"` / `"period"`, e `desired_model_id` volta ao valor de `active_model_id`.
3. Buffer do candidato: mesmo `period_s` do modelo em uso → `block.active_buffer_copy()`. Período diferente, ou bloco sem modelo → pré-aquecimento pela mesma rotina da Task 6 (com os mesmos eventos de `prewarm_skipped`), ou `None`.
4. Grava `candidate_model_id` no vínculo e chama `block.set_candidate(model, buffer)`.

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_comando_com_flow_rodando_cria_candidato_e_grava_candidate_model_id(...): ...
async def test_comando_com_flow_parado_nao_faz_nada(...): ...
async def test_comando_para_bloco_que_nao_e_sensor_virtual_e_ignorado(...): ...
async def test_modelo_de_metodo_errado_e_rejeitado_e_o_desejado_volta_ao_ativo(...): ...
async def test_mesmo_periodo_herda_copia_do_buffer_do_ativo(...): ...
async def test_periodo_diferente_preaquece_pelo_historico(...): ...
async def test_apos_alguns_scans_o_ativo_no_banco_e_o_modelo_novo(...): ...   # integra com o laço de varredura
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest services/flow-runtime/tests/test_soft_sensor_command.py -q` → FAIL.
- [ ] **Step 3: Implementar.** O handler roda sob o `self._lock` do supervisor, como os demais; a leitura do banco é `await`, nunca bloqueia o laço de varredura.
- [ ] **Step 4: Rodar e ver passar** — mesmo comando, mais `services/flow-runtime/tests/test_fuzzy_setpoint.py` → PASS.
- [ ] **Step 5: Commit**

```bash
git add services/flow-runtime/src/ottima_flow_runtime/supervisor.py services/flow-runtime/src/ottima_flow_runtime/soft_sensor_seeds.py services/flow-runtime/tests/test_soft_sensor_command.py
git commit -m "feat(flow-runtime): comando soft_sensor_model troca o modelo do bloco em execução"
```

---

### Task 8: API — ativação, consulta e poda de vínculos (RF-584)

**Files:**
- Create: `services/api/src/ottima_api/softsensor.py`, `services/api/src/ottima_api/routers/softsensor.py`
- Modify: `services/api/src/ottima_api/routers/operate.py` (rota nova depois de `set_sp`, linha ~425), `services/api/src/ottima_api/routers/flows.py` (linha 304, ao lado de `podar_variaveis_historiadas`), `services/api/src/ottima_api/app.py` (`include_router`, linha ~100, com `prefix="/api/softsensor"`)
- Test: `services/api/tests/test_softsensor.py` (criar; molde de fixtures: `test_operate_fuzzy.py` e `test_historized_vars.py`)

**Interfaces:**
- Consumes: modelos da Task 4; `SOFT_SENSOR_METHOD`, `graph_ports` (Task 3); `_publicar_comando`, `_node_do_flow`, `_reprovado` de `routers/operate.py`.
- Produces:
  - `POST /api/operate/{flow_id}/{block_id}/model` — body `{"model_id": int}`, `require_admin`, 202.
  - `GET /api/softsensor/blocks` — `require_operator`; blocos de sensor virtual dos flows do **projeto ativo**: `[{flow_id, flow_name, block_id, label, method, n_inputs, desired_model_id, active_model_id, candidate_model_id}]`.
  - `GET /api/softsensor/models` — `require_operator`; modelos do projeto ativo, **sem `weights`**: `[{id, name, method, period_s, n_inputs, warmup_steps, metrics, input_names, created_at}]`.
  - `async def podar_vinculos_soft_sensor(db: AsyncSession, flow_id: int, grafo: FlowGraph) -> int` em `ottima_api/softsensor.py` — apaga o vínculo de todo `block_id` ausente do grafo ou cujo nó não é mais do tipo de sensor virtual; devolve quantos apagou.

Recusas da rota de ativação (422, mensagem pt-BR via `_reprovado`):
- bloco não é sensor virtual: `"Bloco '<id>' não é um bloco de sensor virtual"`;
- modelo inexistente ou de outro projeto: `"Modelo <id> não existe neste projeto"`;
- método: `"Modelo '<nome>' é <MÉTODO>; o bloco '<id>' é <MÉTODO do bloco>"`;
- entradas: `"Modelo '<nome>' tem <a> entradas; o bloco '<id>' tem <b>"`;
- período: `"Período do modelo (<p> s) não é múltiplo do Ts do flow (<ts> s)"`.

Aceito: `INSERT ... ON CONFLICT (flow_id, block_id) DO UPDATE SET desired_model_id = ...`, `updated_by = f"user:{user.id}"`, depois `_publicar_comando(..., "soft_sensor_model", {"block_id": block_id, "model_id": model_id})`. A API **não** escreve `active_model_id` nem `candidate_model_id` e não emite evento.

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_ativacao_grava_o_desejado_e_publica_o_comando(client, redis_espia): ...
async def test_ativacao_exige_admin(client_operador): ...                       # 403
@pytest.mark.parametrize("caso, trecho", [("metodo", "é PLS"), ("entradas", "tem 3 entradas"),
                                           ("periodo", "não é múltiplo"), ("outro_projeto", "não existe neste projeto"),
                                           ("bloco_comum", "não é um bloco de sensor virtual")])
async def test_ativacao_recusada(client, caso, trecho): ...                     # 422 com o trecho
async def test_ativacao_nunca_escreve_ativo_nem_candidato(client, session): ...
async def test_reativar_o_mesmo_modelo_e_idempotente(client, session): ...
async def test_blocks_lista_so_o_projeto_ativo_com_o_vinculo(client): ...
async def test_models_nunca_devolve_os_pesos(client): ...                       # "weights" not in item
async def test_save_que_remove_o_bloco_apaga_o_vinculo(client, session): ...
async def test_save_que_troca_o_tipo_do_bloco_apaga_o_vinculo(client, session): ...
async def test_save_que_so_muda_rotulo_mantem_o_vinculo(client, session): ...
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest services/api/tests/test_softsensor.py -q` → FAIL.
- [ ] **Step 3: Implementar.** A poda roda na mesma transação do save do flow, na linha seguinte à de `podar_variaveis_historiadas`.
- [ ] **Step 4: Rodar e ver passar** — mesmo comando, mais `services/api/tests/test_flows.py services/api/tests/test_operate_fuzzy.py` → PASS.
- [ ] **Step 5: Regenerar tipos do frontend** se `frontend/openapi.json` existir localmente (`cd frontend && npm run generate:api`); senão, anote no relato que ficou para a Task 12.
- [ ] **Step 6: Commit**

```bash
git add services/api/src/ottima_api/softsensor.py services/api/src/ottima_api/routers/softsensor.py services/api/src/ottima_api/routers/operate.py services/api/src/ottima_api/routers/flows.py services/api/src/ottima_api/app.py services/api/tests/test_softsensor.py
git commit -m "feat(api): ativação de modelo de sensor virtual, consulta e poda de vínculos"
```

---

### Task 9: Blocos no canvas (RF-301, RF-581)

**Files:**
- Create: `frontend/src/features/flows/config/CamposSensorVirtual.tsx`, `frontend/src/features/flows/sensorVirtual.check.ts`
- Modify: `frontend/src/features/flows/graph.ts`, `registro.ts`, `nodes/index.tsx`, `config/ModalConfigBloco.tsx`

**Interfaces:**
- Consumes: `SoftSensorConfig` e `PORT_CONTRACTS["soft_sensor_*"]` de `contracts.gen.ts` (Task 3).
- Produces: `DadosSensorVirtual = DadosBase & Pick<SoftSensorConfig, keyof SoftSensorConfig>`; `MAX_ENTRADAS_SENSOR_VIRTUAL` lido do contrato (molde: `MAX_PORTAS_FUZZY`, `graph.ts:98`); três entradas no registro, com rótulos **"Sensor virtual PLS"**, **"Sensor virtual ESN"**, **"Sensor virtual LSTM"** e descrição **"Estima uma variável de laboratório por modelo treinado"**; config inicial `{ n_inputs: 2, output_eu: "" }`.

O molde é o bloco `fuzzy` em cada um dos quatro arquivos (portas `IN1..INn` por contagem na config), com uma saída fixa `out`. O formulário tem dois campos: **"Número de entradas"** (inteiro de 1 a `MAX_ENTRADAS_SENSOR_VIRTUAL`) e **"Unidade da saída"** (texto). Abaixo dos campos, um texto fixo: **"O modelo é escolhido na página Coleta e treino, não aqui."** Um componente só (`NoSensorVirtual`) atende os três tipos.

Rótulos de porta com o nome da tag esperada (spec §5.1) ficam para a SV-3, junto com as páginas; aqui as portas mostram `IN1..INn`.

- [ ] **Step 1: Escrever os checks que falham** em `sensorVirtual.check.ts` (molde: `filtros.check.ts`):

```ts
check("criarBloco nasce com 2 entradas e EU vazia", ...)           // para os 3 tipos
check("portas de entrada seguem n_inputs", ...)                    // n_inputs=3 -> ["IN1","IN2","IN3"]
check("saída é sempre 'out'", ...)
check("reduzir n_inputs remove as arestas das portas que sumiram", ...)
check("teto de entradas vem do contrato e vale 32", ...)
check("entrada booleana é recusada na conexão", ...)
```

- [ ] **Step 2: Rodar e ver falhar** — `cd frontend && npm run test:unit` → FAIL nos checks novos.
- [ ] **Step 3: Implementar** nos quatro arquivos e criar `CamposSensorVirtual.tsx`.
- [ ] **Step 4: Rodar e ver passar** — `cd frontend && npm run test:unit && npm run typecheck` → PASS, zero erros.
- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/flows/graph.ts frontend/src/features/flows/registro.ts frontend/src/features/flows/nodes/index.tsx frontend/src/features/flows/config/ModalConfigBloco.tsx frontend/src/features/flows/config/CamposSensorVirtual.tsx frontend/src/features/flows/sensorVirtual.check.ts
git commit -m "feat(frontend): blocos de sensor virtual na paleta e no modal de configuração"
```

---

### Task 10: Modelo no arquivo de projeto e tetos de tamanho (RF-590, ADR-046 D8)

**Files:**
- Modify: `packages/ottima-core/src/ottima_core/portability/schemas.py` (ao lado de `BundleHistorizedVar`, linha 149; `ProjectBundle`, linha 166), `packages/ottima-core/src/ottima_core/portability/bundle.py` (`montar_bundle`, `problemas_de_coerencia_interna`)
- Modify: `services/api/src/ottima_api/routers/projects.py` (`MAX_IMPORT_BUNDLE_BYTES` linha 316, `_MSG_IMPORT_GRANDE` linha 318, `import_project` linha 368, e a rota de export)
- Modify: `frontend/nginx.conf` (`location /api/`), `frontend/src/features/projects/importar.check.ts` (linha 59) e o texto do limite onde ele aparecer no frontend
- Test: `services/api/tests/test_projects_export.py`, `test_projects_import.py`; `tests/e2e/test_f6_portabilidade.py` (caso de 413, linha ~576)

**Interfaces:**
- Consumes: modelos da Task 4; `load_model`, `ArtifactError` (Task 1); `ref_por_id` de `portability/bundle.py`.
- Produces:
  - `class BundleSoftSensorModel(BaseModel)` (`extra="forbid"`): `name: str`, `method: Literal["pls","esn","lstm"]`, `period_s: float`, `n_inputs: int`, `meta: dict[str, Any]`, `weights_b64: str`, `input_tags: list[BundleTagRef | None] = []`.
  - `class BundleSoftSensorBinding(BaseModel)` (`extra="forbid"`): `flow: str`, `block_id: str`, `model: str`.
  - `ProjectBundle.soft_sensor_models: list[BundleSoftSensorModel] = Field(default_factory=list)` e `soft_sensor_bindings: list[BundleSoftSensorBinding] = Field(default_factory=list)`.

Regras:
- **Export** leva só os modelos referenciados por algum vínculo (`desired_model_id`), e um vínculo por bloco apontando o modelo **desejado**. Tag de entrada sem referência exportável (tag calculada, variável historiada, tag apagada) vira `None` na lista.
- **Import** recria os modelos, religa `input_tags` pelo mesmo mapa de referências que o import já monta para o grafo (referência que não resolve vira lista vazia de `input_tag_ids`, e o import **não** falha por isso), e cria cada vínculo com `desired_model_id` preenchido e `active_model_id`/`candidate_model_id` nulos.
- **Recusa do import inteiro** (422, nada gravado, mesmo padrão das recusas existentes): `weights_b64` que não decodifica, artefato que `load_model` recusa, nome de modelo duplicado no bundle, vínculo que cita flow, bloco ou modelo inexistente no bundle, vínculo para bloco que não é sensor virtual.
- Variáveis de laboratório no bundle (spec §9) chegam com a tabela delas, na SV-2.
- `MAX_IMPORT_BUNDLE_BYTES = 32 * 1024 * 1024`; mensagem `"Corpo do import excede o limite de 32 MiB."`; `client_max_body_size 32m;` dentro de `location /api/` no nginx.

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_export_leva_o_modelo_vinculado_e_o_vinculo(client): ...
async def test_export_nao_leva_modelo_sem_vinculo(client): ...
async def test_roundtrip_export_import_preserva_a_estimativa(client, session):
    # exporta, importa com outro nome, carrega o modelo importado e compara
    # predict(original, janela) == predict(importado, janela)
async def test_import_cria_vinculo_so_com_o_desejado(client, session): ...
async def test_import_com_tag_de_entrada_que_nao_resolve_nao_falha(client, session): ...   # input_tag_ids == []
@pytest.mark.parametrize("defeito", ["base64", "artefato", "nome_duplicado", "vinculo_orfao", "bloco_comum"])
async def test_import_recusado_nao_grava_nada(client, session, defeito): ...               # 422 e contagens inalteradas
async def test_bundle_antigo_sem_os_campos_novos_continua_importando(client): ...
async def test_import_aceita_corpo_de_20_mib_e_recusa_de_40(client): ...                   # 413 só no segundo
```

Atualize o teste existente do teto (`test_projects_import.py`, ~linha 349: hoje manda 8 MiB e espera 413) para mandar 40 MiB, e a mensagem esperada em `importar.check.ts` e em `tests/e2e/test_f6_portabilidade.py`.

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest services/api/tests/test_projects_export.py services/api/tests/test_projects_import.py -q` → FAIL nos testes novos.
- [ ] **Step 3: Implementar** schemas, export, import e os tetos.
- [ ] **Step 4: Rodar e ver passar** — mesmo comando → PASS; `cd frontend && npm run test:unit` → PASS; `grep -n "client_max_body_size" frontend/nginx.conf` mostra a linha dentro de `location /api/`.
- [ ] **Step 5: Commit**

```bash
git add packages/ottima-core/src/ottima_core/portability services/api/src/ottima_api/routers/projects.py services/api/tests/test_projects_export.py services/api/tests/test_projects_import.py frontend/nginx.conf frontend/src/features/projects/importar.check.ts tests/e2e/test_f6_portabilidade.py
git commit -m "feat(portabilidade): modelo de sensor virtual no arquivo de projeto e teto de 32 MiB"
```
(inclua qualquer outro arquivo de frontend onde o texto "4 MiB" foi trocado.)

---

### Task 11: Prova de malha — saída inválida não cai no portão frio

Teste de aceitação no runtime, sem stack: prova a propriedade que justificou a emenda da tabela de qualidade (spec §5.4, ★).

A spec §11 lista um cenário L2 com MPC real aplicando `fail_action`. Nesta entrega ele é substituído por esta prova no runtime: o que o sensor virtual controla é entregar `v` retido com qualidade BAD (e portanto não acionar `has_cold_input`); o que o MPC faz com uma CV que tem valor e qualidade ruim já é coberto por `services/flow-runtime/tests/test_mpc_block.py` (casos com `entradas(20.0, ok=False)`, linhas ~700 e ~841). O cenário L2 com MPC entra na SV-3, quando houver modelo treinado e página para montar a malha.

**Files:**
- Test: `services/flow-runtime/tests/test_soft_sensor_acceptance.py` (criar; molde de montagem de flow em memória: `test_realimentacao.py` e `runtime_test_helpers.py`)

**Interfaces:**
- Consumes: tudo das Tasks 1 a 7. Não produz código de produção.

- [ ] **Step 1: Escrever os testes**

```python
async def test_flow_com_pls_estima_a_cada_varredura():
    # constante(3.0) -> IN1, constante(4.0) -> IN2, PLS w=[2,-1] b=0.5 -> out == 2.5 GOOD em todo scan

async def test_entrada_bad_no_meio_entrega_valor_retido_e_nao_none():
    # fonte controlável -> soft_sensor_lstm (K=3, aquecido) -> bloco espião
    # ao tornar a fonte BAD: o espião recebe Signal(v=<último valor>, quality=BAD),
    # e has_cold_input({"cv": sinal}) é False  (import de blocks.base)

async def test_primeiro_aquecimento_sem_prewarm_e_cold():
    # mesmo flow, sem prewarm: nos 2 primeiros scans has_cold_input é True; no 3o, False

async def test_troca_de_modelo_no_flow_rodando_nunca_piora_a_qualidade():
    # PLS id=1 rodando; comando soft_sensor_model para PLS id=2; registra out.quality por scan
    # -> todas GOOD; a partir de algum scan out.v passa a ser o do modelo 2

async def test_hot_swap_que_nao_mexe_no_bloco_mantem_modelo_e_buffer():
    # reload com mudança só em OUTRO bloco -> mesma instância de SoftSensorBlock, sem novo aquecimento
```

- [ ] **Step 2: Rodar** — `uv run pytest services/flow-runtime/tests/test_soft_sensor_acceptance.py -q` → PASS. Se algum falhar, o defeito está numa das Tasks 5 a 7: corrija lá, com um teste unitário novo na tarefa dona.
- [ ] **Step 3: Commit**

```bash
git add services/flow-runtime/tests/test_soft_sensor_acceptance.py
git commit -m "test(flow-runtime): aceitação do sensor virtual em flow (valor retido, troca, hot-swap)"
```

---

### Task 12: Gates e cenários E2E

**Files:**
- Create: `tests/e2e/test_sv1_sensor_virtual.py`
- Modify: `CLAUDE.md` (contagem de cenários da L2 na seção de comandos)

**Interfaces:**
- Consumes: a stack de 8 serviços com o código das Tasks 0 a 11; `ottima_core.softsensor.synthetic` para montar o bundle; os helpers de `tests/e2e/conftest.py` (login, opcsim, import de projeto, deploy).

Cenários (marcados `@pytest.mark.e2e`):
- **E2E-SV-01 — import, deploy, estimativa.** Importa um projeto com conexão ao opcsim, duas tags de leitura, um flow `opc_read ×2 → soft_sensor_pls` e um modelo PLS sintético vinculado. Deploy. Em até 5 varreduras, `out` em `flow.status` é GOOD e igual a `w·x + b` das leituras, com tolerância `1e-3`. `GET /api/softsensor/blocks` mostra `active_model_id == desired_model_id`.
- **E2E-SV-02 — troca em execução.** O bundle do teste é montado à mão com dois modelos PLS (`b` diferente) e vínculo só para o primeiro (o import aceita modelo sem vínculo; é o export que não o leva). `POST /api/operate/{flow}/{bloco}/model`. Em até 10 s, `active_model_id` é o segundo, chegou o evento `soft_sensor_model_activated`, e nenhuma amostra de `out` coletada no intervalo teve qualidade diferente de GOOD.
- **E2E-SV-03 — pré-aquecimento.** Flow com `soft_sensor_lstm` (`sequence_length = 10`, `period_s = Ts = 1`), deployado depois de o opcsim publicar por 20 s. `out` sai GOOD em até 3 varreduras do deploy (sem pré-aquecimento seriam 10).
- **E2E-SV-04 — recusa.** Ativar um modelo ESN num bloco PLS devolve 422 com "é ESN"; `GET /api/softsensor/blocks` não muda.

- [ ] **Step 1: Escrever os quatro cenários.**
- [ ] **Step 2: Gates herméticos**

Run: `uv run ruff check . && uv run ruff format --check .` — Expected: sem achados.
Run: `cd frontend && npm run test:unit && npm run typecheck && npm run build && npm run generate:contracts && git diff --exit-code src/lib/contracts.gen.ts` — Expected: tudo verde, diff vazio.

- [ ] **Step 3: Suíte Python inteira**

Run: `uv run pytest -q` — Expected: PASS (o default exclui `slow` e `e2e`).

- [ ] **Step 4: Subir a stack e rodar a L2 dos cenários novos**

```bash
cd deploy && docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build
cd .. && E2E_ADMIN_USERNAME=$(grep -m1 '^OTTIMA_ADMIN_USERNAME=' deploy/.env|cut -d= -f2-) E2E_ADMIN_PASSWORD=$(grep -m1 '^OTTIMA_ADMIN_PASSWORD=' deploy/.env|cut -d= -f2-) uv run pytest -m e2e tests/e2e/test_sv1_sensor_virtual.py tests/e2e/test_f6_portabilidade.py -v
```

Expected: os 4 cenários novos e os de portabilidade PASS. Se `deploy/.env` não existir ou a stack não subir, **pare e relate**: não marque a tarefa como concluída com a L2 sem rodar.

- [ ] **Step 5: Atualizar o `CLAUDE.md`** (linha da L2: de 43 para 47 cenários, com "+ 4 SV") e commitar

```bash
git add tests/e2e/test_sv1_sensor_virtual.py CLAUDE.md
git commit -m "test(e2e): cenários E2E-SV-01..04 do sensor virtual"
```

---

## Fora deste plano (entregas seguintes)

- **SV-2:** `lab_variables`, `lab_samples`, CSV, `soft_sensor_datasets`, serviço `ml-worker` com `dataset_build`, página Coleta e treino sem treino; variáveis de laboratório no bundle.
- **SV-3:** jobs `train` e `tune`, exportadores reais com **teste de paridade contra scikit-learn e PyTorch** (é ele que valida de vez a conta do LSTM e do PLS escrita na Task 1), lista de modelos com ativação na página, página Otimização, `DELETE` de modelo, rótulos de porta com o nome da tag no canvas, navegação condicional.
