# Fuzzy Malha (`fuzzy_loop`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar o bloco `fuzzy_loop` ("Fuzzy Malha") — `FuzzyKernel` incremental sobre pyfuzzylite, contrato FLL validado em duas camadas, registro do tipo, heatmap de superfície e (fase K3) LUT content-addressed com portões de validação — com F1–F11 verdes.

**Architecture:** Reusa integralmente a infra do plano `pid_loop` (shell, `loop_samples`/`loop_setpoints`, canal `loop.state.*`, comandos `loop_*`, rotas, faceplate). Novidades: validador do contrato FLL em `ottima-core` (compartilhado entre save e runtime), `FuzzyKernel` em `flow-runtime`, tipo `fuzzy_loop` nos pontos de registro, endpoint de superfície + aba heatmap, e a fase K3 (LUT + portões + migration 0016).

**Tech Stack:** pyfuzzylite 8.0.6 (API snake_case), numpy (já no workspace), demais idênticos ao plano pid_loop.

**Spec:** `docs/specs/SPEC_FUZZY_with_SHELL.md` (+ `docs/adr/ADR-039-block-shell.md`). Pré-requisitos OBRIGATÓRIOS: planos `2026-08-31-block-shell-foundation.md` e `2026-08-31-pid-loop.md` concluídos.

## Global Constraints

- Bloco `fuzzy` existente **não é alterado** (SPEC §1.1: "Alterações previstas: nenhuma").
- Contrato FLL (SPEC §3.2): entradas exatamente `e` e `de` em `-1.000 1.000` com `lock-range: true`; saída exatamente `du` em `-1.000 1.000` com `lock-range: true`, `lock-previous: false`, `default: nan`; exatamente 1 rule block.
- Validação nas duas camadas do ADR-029: save (`validate_graph`, 422 pt-BR, import lazy de fuzzylite) e deploy (kernel nasce `OOS` + `CONFIG_ERROR` se o FLL degradou).
- Uma `Engine` por instância de bloco, construída uma vez — nunca compartilhada (SPEC §4.2).
- Troca de `FLL_SOURCE` é classe ESTRUTURAL (`fll` já está em `LOOP_STRUCTURAL_KEYS` do plano pid_loop): re-instancia e aterrissa em MAN se calculava (F11).
- `KE`/`KDE`/`KU` são classe de sintonia: hot-swap in-place sem degrau (F10).
- Tetos FUZZY-SEC continuam valendo: `MAX_FUZZY_FLL_LENGTH` no campo `fll`, resolução de amostragem definida no SERVIDOR.
- Teste F9 marcado `@pytest.mark.slow` (excluído do addopts default).
- Mesmas regras de lint/teste/commit do plano pid_loop.

**Interfaces herdadas (nomes exatos, já existentes após o plano pid_loop):** `LoopBaseConfig`, `LOOP_STRUCTURAL_KEYS` (contém `"fll"`), `loop_structural`, `LOOP_TYPES` (em `validate.py` E em `definition.py` — as duas recebem `"fuzzy_loop"` aqui), `shell_cfg_from(config, ts_seconds)`, `_instantiate_loop(...)`, ramo de hot-swap em `build_definition`, `BlockShell` (+ `command`, `apply_tuning`, `diag`), `LoopState.diag: dict[str, float]`, rotas `/api/operate/...` com `_loop_config`/`_validar_comando_loop`, `LoopOperatePage`, `PORT_CONTRACTS`.

---

### Task 1: Contrato FLL + `FUZZY_LOOP_DEFAULT_FLL` (ottima-core)

**Files:**
- Create: `packages/ottima-core/src/ottima_core/flowgraph/fll_contract.py`
- Modify: `packages/ottima-core/src/ottima_core/contracts_export.py` (constante `FUZZY_LOOP_DEFAULT_FLL`)
- Test: `packages/ottima-core/tests/test_fll_contract.py`

**Interfaces:**
- Produces: `validate_fll_contract(engine) -> list[str]` (códigos: `FLL_INPUTS_MUST_BE_E_DE`, `FLL_RANGE_MUST_BE_UNIT`, `FLL_LOCK_RANGE_REQUIRED`, `FLL_OUTPUT_MUST_BE_DU`, `FLL_LOCK_PREVIOUS_FORBIDDEN`, `FLL_DEFAULT_MUST_BE_NAN`, `FLL_RULEBLOCK_MUST_BE_SINGLE`) e `FUZZY_LOOP_DEFAULT_FLL: str` (Sugeno ordem zero, satisfaz o contrato). Usados pela Task 2 (kernel.validate), Task 3 (save) e Task 6 (LUT).

- [ ] **Step 1: Write the failing test**

```python
# packages/ottima-core/tests/test_fll_contract.py
"""Contrato FLL do fuzzy_loop (SPEC_FUZZY secao 3.2). F1/F2 na camada do validador."""

import fuzzylite as fl

from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL
from ottima_core.flowgraph.fll_contract import validate_fll_contract


def _engine(fll: str) -> fl.Engine:
    return fl.FllImporter().from_string(fll)


def test_default_fll_satisfaz_o_contrato_e_esta_pronto() -> None:
    engine = _engine(FUZZY_LOOP_DEFAULT_FLL)
    assert validate_fll_contract(engine) == []
    assert engine.is_ready()


def test_f2_lock_previous_true_e_rejeitado_com_codigo_dedicado() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("lock-previous: false", "lock-previous: true")
    assert "FLL_LOCK_PREVIOUS_FORBIDDEN" in validate_fll_contract(_engine(fll))


def test_default_nan_obrigatorio() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("default: nan", "default: 0.000")
    assert "FLL_DEFAULT_MUST_BE_NAN" in validate_fll_contract(_engine(fll))


def test_nomes_e_contagem_de_variaveis() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("InputVariable: de", "InputVariable: derr")
    assert "FLL_INPUTS_MUST_BE_E_DE" in validate_fll_contract(_engine(fll))


def test_faixa_fora_do_unitario() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("range: -1.000 1.000", "range: -2.000 2.000", 1)
    assert "FLL_RANGE_MUST_BE_UNIT" in validate_fll_contract(_engine(fll))
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest packages/ottima-core/tests/test_fll_contract.py -q` → FAIL (imports)

- [ ] **Step 3: Implement**

```python
# packages/ottima-core/src/ottima_core/flowgraph/fll_contract.py
"""Contrato do .fll de um bloco fuzzy_loop (SPEC_FUZZY secao 3.2).

Compartilhado entre a validacao de save (validate.py, lazy) e o kernel em runtime.
Nunca importar fuzzylite no topo de modulos quentes — quem chama ja importou.
"""

import math
from typing import Any


def validate_fll_contract(engine: Any) -> list[str]:
    errs: list[str] = []
    entradas = list(engine.input_variables)
    if [v.name for v in entradas] != ["e", "de"]:
        errs.append("FLL_INPUTS_MUST_BE_E_DE")
    saidas = list(engine.output_variables)
    if [v.name for v in saidas] != ["du"]:
        errs.append("FLL_OUTPUT_MUST_BE_DU")
    for var in [*entradas, *saidas]:
        if not (math.isclose(var.minimum, -1.0) and math.isclose(var.maximum, 1.0)):
            errs.append("FLL_RANGE_MUST_BE_UNIT")
            break
    if any(not var.lock_range for var in [*entradas, *saidas]):
        errs.append("FLL_LOCK_RANGE_REQUIRED")
    for out in saidas:
        if out.lock_previous:
            errs.append("FLL_LOCK_PREVIOUS_FORBIDDEN")
        if not math.isnan(out.default_value if hasattr(out, "default_value") else out.default):
            errs.append("FLL_DEFAULT_MUST_BE_NAN")
    if len(list(engine.rule_blocks)) != 1:
        errs.append("FLL_RULEBLOCK_MUST_BE_SINGLE")
    return errs
```

(Conferir no `fuzzy.py` existente / na 8.0.6 o nome exato do atributo de default da `OutputVariable` — `default_value` vs `default` — e do `lock_previous`/`lock_range`; ajustar o código para o nome real e REMOVER o `hasattr` de transição.)

Em `contracts_export.py`, ao lado de `FUZZY_DEFAULT_FLL` (linhas ~60-118), a constante literal:

```python
FUZZY_LOOP_DEFAULT_FLL = """\
Engine: fuzzy_loop_padrao
InputVariable: e
  enabled: true
  range: -1.000 1.000
  lock-range: true
  term: NG Triangle -1.000 -1.000 -0.500
  term: NP Triangle -1.000 -0.500 0.000
  term: ZE Triangle -0.500 0.000 0.500
  term: PP Triangle 0.000 0.500 1.000
  term: PG Triangle 0.500 1.000 1.000
InputVariable: de
  enabled: true
  range: -1.000 1.000
  lock-range: true
  term: N Triangle -1.000 -1.000 0.000
  term: ZE Triangle -1.000 0.000 1.000
  term: P Triangle 0.000 1.000 1.000
OutputVariable: du
  enabled: true
  range: -1.000 1.000
  lock-range: true
  aggregation: none
  defuzzifier: WeightedAverage
  default: nan
  lock-previous: false
  term: NG Constant -1.000
  term: NP Constant -0.500
  term: ZE Constant 0.000
  term: PP Constant 0.500
  term: PG Constant 1.000
RuleBlock: regras
  enabled: true
  conjunction: AlgebraicProduct
  disjunction: Maximum
  implication: AlgebraicProduct
  activation: General
  rule: if e is NG then du is NG
  rule: if e is NP then du is NP
  rule: if e is ZE and de is N then du is NP
  rule: if e is ZE and de is ZE then du is ZE
  rule: if e is ZE and de is P then du is PP
  rule: if e is PP then du is PP
  rule: if e is PG then du is PG
"""
```

(Sugeno ordem zero: monotônica em `e`, sinal-consistente, zero na origem — passa nos portões da fase K3 por construção. Se o parser 8.0.6 recusar algum detalhe sintático, ajustar comparando com o `FUZZY_DEFAULT_FLL` existente e manter o teste `is_ready()` como juiz.)

- [ ] **Step 4: Run tests** — `uv run pytest packages/ottima-core/tests/test_fll_contract.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check packages/ottima-core && uv run ruff format packages/ottima-core
git add packages/ottima-core/src/ottima_core/flowgraph/fll_contract.py packages/ottima-core/src/ottima_core/contracts_export.py packages/ottima-core/tests/test_fll_contract.py
git commit -m "feat(fuzzy_loop): contrato FLL compartilhado e FLL default Sugeno (F1/F2)"
```

---

### Task 2: FuzzyKernel incremental

**Files:**
- Create: `services/flow-runtime/src/ottima_flow_runtime/blocks/kernels/fuzzy.py`
- Modify: `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py` (uma linha: copiar `kernel.diag` após compute válido)
- Test: `services/flow-runtime/tests/test_fuzzy_kernel.py`

**Interfaces:**
- Consumes: `validate_fll_contract`, `FUZZY_LOOP_DEFAULT_FLL`, protocol `ControlKernel`.
- Produces: `FuzzyKernelCfg` (dataclass mutável: `ke, kde, ku, tf_de, direct_acting`), `FuzzyKernel(engine, cfg)` (código normativo da SPEC §3.3 + `diag: dict[str, float]` com `e_n`, `de_n`, `du_n`, `rule_fire_count` atualizados por `compute`), `build_fuzzy_kernel(fll: str, cfg: FuzzyKernelCfg) -> ControlKernel` (devolve `FuzzyKernel` ou, se o FLL falhar parse/contrato, um `BrokenKernel(errors)` cujo `validate()` devolve os erros — o shell o coloca em `OOS`+`CONFIG_ERROR`, F1 na camada de deploy).

- [ ] **Step 1: Write the failing test**

```python
# services/flow-runtime/tests/test_fuzzy_kernel.py
"""FuzzyKernel (SPEC_FUZZY secao 3.3): normalizacao, filtro, NaN, isolamento (F3/F7)."""

import math

from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL
from ottima_flow_runtime.blocks.kernels.fuzzy import FuzzyKernelCfg, build_fuzzy_kernel


def _kernel(**over):
    cfg = FuzzyKernelCfg(ke=0.1, kde=0.0, ku=5.0)
    for k, v in over.items():
        setattr(cfg, k, v)
    return build_fuzzy_kernel(FUZZY_LOOP_DEFAULT_FLL, cfg)


def test_erro_zero_da_du_zero() -> None:
    k = _kernel()
    k.align(50.0, 10.0, 10.0)
    assert abs(k.compute(sp=10.0, pv=10.0, dt=1.0)) < 1e-6


def test_sinal_consistente_e_ganho_ku() -> None:
    k = _kernel(ku=5.0)
    k.align(0.0, 10.0, 10.0)
    sobe = k.compute(sp=15.0, pv=10.0, dt=1.0)  # erro +5, e_n = 0.5
    assert sobe > 0.0
    k2 = _kernel(ku=10.0)
    k2.align(0.0, 10.0, 10.0)
    assert abs(k2.compute(sp=15.0, pv=10.0, dt=1.0) - 2.0 * sobe) < 1e-6  # F6 no kernel


def test_direct_acting_inverte() -> None:
    k = _kernel(direct_acting=True)
    k.align(0.0, 10.0, 10.0)
    assert k.compute(sp=15.0, pv=10.0, dt=1.0) < 0.0


def test_saturacao_do_universo() -> None:
    k = _kernel(ke=0.1, ku=5.0)
    k.align(0.0, 0.0, 0.0)
    a = k.compute(sp=100.0, pv=0.0, dt=1.0)   # e_n satura em 1
    k.align(0.0, 0.0, 0.0)
    b = k.compute(sp=1000.0, pv=0.0, dt=1.0)  # ainda 1
    assert abs(a - b) < 1e-6


def test_f3_regiao_sem_regra_propaga_nan() -> None:
    # FLL valido no contrato mas com buraco: so cobre e negativo
    com_buraco = FUZZY_LOOP_DEFAULT_FLL
    for regra in (
        "  rule: if e is ZE and de is N then du is NP\n",
        "  rule: if e is ZE and de is ZE then du is ZE\n",
        "  rule: if e is ZE and de is P then du is PP\n",
        "  rule: if e is PP then du is PP\n",
        "  rule: if e is PG then du is PG\n",
    ):
        com_buraco = com_buraco.replace(regra, "")
    k = build_fuzzy_kernel(com_buraco, FuzzyKernelCfg(ke=0.1, kde=0.0, ku=5.0))
    k.align(0.0, 0.0, 0.0)
    assert math.isnan(k.compute(sp=50.0, pv=0.0, dt=1.0))  # e_n=1.0: sem regra


def test_f7_duas_instancias_mesmo_fll_sao_isoladas() -> None:
    cfg = FuzzyKernelCfg(ke=0.1, kde=0.0, ku=5.0)
    a = build_fuzzy_kernel(FUZZY_LOOP_DEFAULT_FLL, cfg)
    b = build_fuzzy_kernel(FUZZY_LOOP_DEFAULT_FLL, cfg)
    a.align(0.0, 0.0, 0.0)
    b.align(0.0, 0.0, 0.0)
    ra = a.compute(sp=10.0, pv=0.0, dt=1.0)
    rb = b.compute(sp=-10.0, pv=0.0, dt=1.0)
    assert ra > 0.0 > rb  # entradas divergentes, saidas independentes


def test_diag_exposto() -> None:
    k = _kernel()
    k.align(0.0, 0.0, 0.0)
    k.compute(sp=5.0, pv=0.0, dt=1.0)
    assert set(k.diag) >= {"e_n", "de_n", "du_n", "rule_fire_count"}
    assert k.diag["rule_fire_count"] >= 1.0


def test_fll_quebrado_vira_broken_kernel() -> None:
    k = build_fuzzy_kernel("Engine: lixo\nsintaxe invalida", FuzzyKernelCfg(ke=1.0, kde=0.0, ku=1.0))
    assert k.validate() != []


def test_validate_ganhos() -> None:
    assert "KU_MUST_BE_POSITIVE" in _kernel(ku=0.0).validate()
    assert "TF_DE_MUST_BE_POSITIVE" in _kernel(tf_de=0.0).validate()
    assert "KE_MUST_BE_POSITIVE" in _kernel(ke=0.0).validate()
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest services/flow-runtime/tests/test_fuzzy_kernel.py -q` → FAIL

- [ ] **Step 3: Implement** — copiar o código normativo da SPEC §3.3 (`FuzzyKernelCfg`, `FuzzyKernel`) para `kernels/fuzzy.py`, completando:

```python
import math
from dataclasses import dataclass

import fuzzylite as fl
import numpy as np

from ottima_core.flowgraph.fll_contract import validate_fll_contract


def _sat(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


class BrokenKernel:
    """Kernel de config invalida: o shell le validate() e prende o bloco em OOS."""

    def __init__(self, errors: list[str], cfg) -> None:
        self.errors = errors
        self.cfg = cfg
        self.diag: dict[str, float] = {}

    def compute(self, sp: float, pv: float, dt: float) -> float:  # noqa: ARG002
        return math.nan

    def align(self, u: float, sp: float, pv: float) -> None:  # noqa: ARG002
        return None

    def reset(self) -> None:
        return None

    def validate(self) -> list[str]:
        return list(self.errors)


def build_fuzzy_kernel(fll: str, cfg: "FuzzyKernelCfg"):
    try:
        engine = fl.FllImporter().from_string(fll)
    except Exception as erro:  # F1 na camada de deploy
        return BrokenKernel([f"FLL_PARSE_ERROR: {erro}"], cfg)
    erros = validate_fll_contract(engine)
    if erros or not engine.is_ready():
        return BrokenKernel(erros or ["ENGINE_NOT_READY"], cfg)
    return FuzzyKernel(engine, cfg)
```

`FuzzyKernel` conforme a SPEC §3.3 com os acréscimos: no `compute`, após `self.eng.process()`, preencher `self.diag` (`e_n`/`de_n` = valores saturados enviados; `du_n` = valor bruto; `rule_fire_count` = `float(sum(1 for rb in self.eng.rule_blocks for r in rb.rules if r.activation_degree > 0.0))` — conferir o atributo exato de grau de ativação usado em `ADR-030`/`fuzzy.py` existente, `rule.activation_degree`); `validate()` inclui `KE_MUST_BE_POSITIVE` quando `ke <= 0`. Em `shell/block.py`, logo após o `du_dt` finito: `kernel_diag = getattr(self.kernel, "diag", None); if kernel_diag: self.diag = dict(kernel_diag)`.

- [ ] **Step 4: Run tests** — `uv run pytest services/flow-runtime/tests/test_fuzzy_kernel.py services/flow-runtime/tests -q` → PASS, sem regressão.

- [ ] **Step 5: Commit**

```bash
uv run ruff check services/flow-runtime && uv run ruff format services/flow-runtime
git add services/flow-runtime/src/ottima_flow_runtime/blocks/kernels/fuzzy.py services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py services/flow-runtime/tests/test_fuzzy_kernel.py
git commit -m "feat(fuzzy_loop): FuzzyKernel incremental com diag e BrokenKernel (F3/F6/F7)"
```

---

### Task 3: Registro do tipo `fuzzy_loop` em todas as camadas

**Files:**
- Modify: `packages/ottima-core/src/ottima_core/flowgraph/parse.py` (`FuzzyLoopConfig`, literal, union, `_CONFIG_KEYS`, ramo)
- Modify: `packages/ottima-core/src/ottima_core/flowgraph/validate.py` (`LOOP_TYPES += fuzzy_loop`; `_valida_fuzzy_loop` no estágio de conteúdo)
- Modify: `services/flow-runtime/src/ottima_flow_runtime/definition.py` (`LOOP_TYPES += fuzzy_loop`; kernel dispatch em `_instantiate_loop` e no ramo de sintonia de `build_definition`)
- Modify: `packages/ottima-core/src/ottima_core/contracts_export.py` (`PORT_CONTRACTS["fuzzy_loop"]` — mesmos ports do `pid_loop`, mais `default_fll`/`max_fll_length` no contrato)
- Modify: `frontend/src/features/flows/registro.ts` + `frontend/src/features/flows/nodes/index.tsx` (entrada "Fuzzy Malha" + `NoFuzzyLoop`)
- Test: `packages/ottima-core/tests/test_fuzzy_loop_registro.py`, `services/flow-runtime/tests/test_fuzzy_loop_definition.py`

**Interfaces:**
- Produces: `FuzzyLoopConfig(LoopBaseConfig)` com `ke: float = Field(gt=0)`, `kde: float = Field(default=0.0, ge=0)`, `ku: float = Field(gt=0)`, `tf_de: float = Field(default=1.0, gt=0)`, `fll: str = Field(default=FUZZY_LOOP_DEFAULT_FLL, max_length=MAX_FUZZY_FLL_LENGTH)`, `lut_enabled: bool = False`, `lut_resolution: int = Field(default=65, ge=33, le=257)`; `fuzzy_kernel_cfg_from(config) -> FuzzyKernelCfg`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/ottima-core/tests/test_fuzzy_loop_registro.py
"""FuzzyLoopConfig + validacao de save do FLL (F1 na camada da API)."""

import pytest
from pydantic import ValidationError

from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL
from ottima_core.flowgraph.parse import FuzzyLoopConfig


def _minima(**over) -> dict:
    base = {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "ke": 0.1, "ku": 5.0}
    base.update(over)
    return base


def test_config_minima_usa_fll_default() -> None:
    cfg = FuzzyLoopConfig.model_validate(_minima())
    assert cfg.fll == FUZZY_LOOP_DEFAULT_FLL
    assert cfg.tf_de == 1.0 and cfg.lut_enabled is False


def test_ganhos_invalidos_rejeitados() -> None:
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(ke=0.0))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(ku=-1.0))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(lut_resolution=10))


def test_f1_save_recusa_fll_fora_do_contrato() -> None:
    # via validate_graph: no fuzzy_loop com o FLL LIVRE do bloco fuzzy antigo
    from ottima_core.contracts_export import FUZZY_DEFAULT_FLL

    grafo = montar_grafo(  # mesmo helper dos testes de validate (Task 3 do plano pid_loop)
        [no_fuzzy_loop("m", 1, fll=FUZZY_DEFAULT_FLL)], []
    )
    resultado = validate_graph(grafo, tags={}, ts_seconds=1.0)
    assert any("FLL" in e for e in resultado.errors)
```

```python
# services/flow-runtime/tests/test_fuzzy_loop_definition.py
"""fuzzy_loop no runtime: instanciacao, F10 (sintonia in-place) e F11 (estrutural->MAN)."""

from ottima_core.flowgraph.parse import FuzzyLoopConfig
from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.definition import fuzzy_kernel_cfg_from, shell_cfg_from
from shell_harness import EPS, amostra, passo


def _config(**over) -> FuzzyLoopConfig:
    base = {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "ke": 0.05, "ku": 3.0}
    base.update(over)
    return FuzzyLoopConfig.model_validate(base)


def _malha(cfg: FuzzyLoopConfig):
    from ottima_flow_runtime.blocks.kernels.fuzzy import build_fuzzy_kernel
    from ottima_flow_runtime.blocks.shell.block import BlockShell

    return BlockShell("m", kernel=build_fuzzy_kernel(cfg.fll, fuzzy_kernel_cfg_from(cfg)),
                      cfg=shell_cfg_from(cfg, 1.0))


async def test_f10_troca_de_ku_em_auto_sem_degrau() -> None:
    b = _malha(_config())
    t = 0.0
    await passo(b, t, **{"in": amostra(50.0)})
    b.write_sp(55.0)
    b.write_target(Mode.AUTO)
    for _ in range(5):
        t += 1.0
        await passo(b, t, **{"in": amostra(50.0)})
    u_antes = b.u
    nova = _config(ku=6.0)  # dobra KU: classe de sintonia
    b.apply_tuning(shell_cfg_from(nova, 1.0), fuzzy_kernel_cfg_from(nova))
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    # sem degrau de posicao: variacao do scan e apenas o incremento (agora 2x maior)
    assert abs(b.u - u_antes) <= 2.0 * 3.0 * 1.0 + EPS


async def test_f11_troca_de_fll_e_estrutural() -> None:
    from ottima_core.flowgraph.parse import loop_structural

    a = _config()
    outro_fll = a.fll.replace("Engine: fuzzy_loop_padrao", "Engine: outro")
    b = _config(fll=outro_fll)
    fa = {"type": "fuzzy_loop", **a.model_dump()}
    fb = {"type": "fuzzy_loop", **b.model_dump()}
    assert loop_structural(fa) != loop_structural(fb)  # build_definition re-instancia
    assert loop_structural(fa) == loop_structural({"type": "fuzzy_loop", **_config(ku=9.0).model_dump()})
```

- [ ] **Step 2: Run to verify it fails** → FAIL (imports)

- [ ] **Step 3: Implement**

1. `parse.py`: literal `"fuzzy_loop"` em `NodeType`/`NODE_TYPES`; `FuzzyLoopConfig` (campos do bloco Interfaces; import de `FUZZY_LOOP_DEFAULT_FLL`/`MAX_FUZZY_FLL_LENGTH` — atenção a import circular com `contracts_export`: se houver, mover as duas constantes FLL para um módulo folha `ottima_core.fll_defaults` e reexportar em `contracts_export`); union `NodeConfig`; `_CONFIG_KEYS`; ramo em `_parse_config`.
2. `validate.py`: `LOOP_TYPES = frozenset({"pid_loop", "fuzzy_loop"})`; função `_valida_fuzzy_loop(node, errors)` — espelho de `_valida_fuzzy` (335-380: import lazy, parse com erro pt-BR, `is_ready`) MAIS `validate_fll_contract(engine)` com erros formatados `f"{where}: contrato FLL violado — {codigo}"`; chamada no `validate_graph` junto de `_check_fuzzy_nodes`.
3. `definition.py`: `LOOP_TYPES` ganha `"fuzzy_loop"`; `fuzzy_kernel_cfg_from(config) -> FuzzyKernelCfg(ke=config.ke, kde=config.kde, ku=config.ku, tf_de=config.tf_de, direct_acting=config.direct_acting)`; em `_instantiate_loop`, o kernel vira dispatch: `kernel = PidKernel(pid_kernel_cfg_from(config)) if node.type == "pid_loop" else build_fuzzy_kernel(config.fll, fuzzy_kernel_cfg_from(config))`; no ramo de sintonia de `build_definition`, o `kernel_cfg` passa a ser `pid_kernel_cfg_from(...)` ou `fuzzy_kernel_cfg_from(...)` conforme `node.type`.
4. `contracts_export.py`: `PORT_CONTRACTS["fuzzy_loop"]` = mesmos 10 ports do `pid_loop` + chaves `{"default_fll": FUZZY_LOOP_DEFAULT_FLL, "max_fll_length": MAX_FUZZY_FLL_LENGTH}`.
5. Frontend: `registro.ts` entrada `fuzzy_loop: { rotulo: "Fuzzy Malha", descricao: "Controle fuzzy industrial com modos e cascata (ADR-039)", defaults: () => ({ sp_hi_lim: 100, sp_lo_lim: 0, ke: 0.1, ku: 5, permitted: ["oos", "man", "auto"], fll: contratoFuzzyLoop.default_fll }) }` (ler `contratoFuzzyLoop` de `contracts.gen.ts` como o `fuzzy` faz com `contratoFuzzy`); `nodes/index.tsx` componente `NoFuzzyLoop` no molde do `NoFuzzy` (LinhaResumo de `KE`/`KU` + linhas do FLL) registrado em `TIPOS_DE_NO`.
6. Regenerar contratos: `cd frontend && npm run generate:contracts`.

- [ ] **Step 4: Run** — `uv run pytest packages/ottima-core/tests services/flow-runtime/tests -q` e `cd frontend && npm run typecheck && npm run test:unit` → PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format packages/ottima-core services/flow-runtime
git add -A packages/ottima-core services/flow-runtime frontend/src
git commit -m "feat(fuzzy_loop): tipo registrado em parse/validate/definition/contratos/paleta"
```

---

### Task 4: Aceitação — S-suíte com FuzzyKernel + F5

**Files:**
- Test: `services/flow-runtime/tests/test_fuzzy_loop_acceptance.py`

- [ ] **Step 1: Write the tests**

```python
# services/flow-runtime/tests/test_fuzzy_loop_acceptance.py
"""F5 + reexecucao dos cenarios S criticos com o FuzzyKernel real (SPEC_FUZZY secao 9)."""

from ottima_core.flowgraph.parse import FuzzyLoopConfig
from ottima_flow_runtime.blocks.kernels.fuzzy import build_fuzzy_kernel
from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.definition import fuzzy_kernel_cfg_from, shell_cfg_from
from shell_harness import EPS, amostra, passo


def _malha(**over) -> BlockShell:
    base = {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "ke": 0.05, "kde": 0.0, "ku": 4.0}
    base.update(over)
    cfg = FuzzyLoopConfig.model_validate(base)
    return BlockShell("m", kernel=build_fuzzy_kernel(cfg.fll, fuzzy_kernel_cfg_from(cfg)),
                      cfg=shell_cfg_from(cfg, 1.0))


async def test_f5_degrau_de_sp_sem_sobressinal_e_sem_erro_de_regime() -> None:
    b = _malha(ku=1.0)  # a malha fuzzy-PI e um integrador puro: ku alto gera sobressinal
    pv, t, pico = 40.0, 0.0, 0.0
    await passo(b, t, **{"in": amostra(pv)})
    b.write_sp(50.0)
    b.write_target(Mode.AUTO)
    for _ in range(600):
        t += 1.0
        await passo(b, t, **{"in": amostra(pv)})
        pv += (b.u - pv) / 8.0
        pico = max(pico, pv)
    assert pico <= 50.0 + 1.0          # sobressinal <= 1% do span (criterio F5)
    assert abs(pv - 50.0) <= 1.0       # erro de regime < 1% (integracao no shell)


async def test_s1_s2_bumpless_com_kernel_fuzzy() -> None:
    b = _malha()
    t = 0.0
    await passo(b, t, **{"in": amostra(30.0)})
    b.write_sp(70.0)
    b.write_target(Mode.AUTO)
    u0 = b.u
    t += 1.0
    await passo(b, t, **{"in": amostra(30.0)})
    assert abs(b.u - u0) <= 4.0 * 1.0 + EPS  # so o incremento do kernel, sem salto
    b.write_target(Mode.MAN)
    t += 1.0
    await passo(b, t, **{"in": amostra(30.0)})
    u_man = b.u
    for _ in range(120):
        t += 1.0
        await passo(b, t, **{"in": amostra(45.0)})
    b.write_target(Mode.AUTO)
    t += 1.0
    await passo(b, t, **{"in": amostra(45.0)})
    assert abs(b.u - u_man) <= 4.0 * 1.0 + EPS  # align zerou de_f: sem chute (S2)


async def test_s12_regiao_sem_regra_segura_out() -> None:
    fll_com_buraco = FuzzyLoopConfig.model_validate(
        {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "ke": 0.05, "ku": 4.0}
    ).fll
    for regra in ("  rule: if e is PP then du is PP\n", "  rule: if e is PG then du is PG\n"):
        fll_com_buraco = fll_com_buraco.replace(regra, "")
    b = _malha(fll=fll_com_buraco, ke=0.1)
    t = 0.0
    await passo(b, t, **{"in": amostra(50.0)})
    b.write_sp(50.0)
    b.write_target(Mode.AUTO)
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    u_antes = b.u
    b.write_sp(90.0)  # empurra o ponto de operacao para o buraco (e_n grande positivo)
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    assert abs(b.u - u_antes) <= EPS  # OUT mantido (F3 na malha fechada)
```

- [ ] **Step 2: Run** — `uv run pytest services/flow-runtime/tests/test_fuzzy_loop_acceptance.py -q` → PASS

- [ ] **Step 3: Commit**

```bash
git add services/flow-runtime/tests/test_fuzzy_loop_acceptance.py
git commit -m "test(fuzzy_loop): aceitacao F5 e cenarios S com kernel fuzzy real"
```

---

### Task 5: Introspecção de superfície + aba heatmap

**Files:**
- Create: `packages/ottima-core/src/ottima_core/flowgraph/fuzzy_surface.py` (`sample_surface`)
- Modify: `services/api/src/ottima_api/routers/operate.py` (rota `GET /api/operate/loop/{flow_id}/{block_id}/surface`)
- Create: `frontend/src/features/loop/HeatmapSuperficie.tsx` + integrar como aba na `LoopOperatePage` (visível só para `fuzzy_loop`)
- Test: `packages/ottima-core/tests/test_fuzzy_surface.py`

**Interfaces:**
- Produces: `sample_surface(fll: str, resolution: int = 65) -> np.ndarray` (shape `(resolution, resolution)`, float32, eixo 0 = `de_n`, eixo 1 = `e_n`, grade uniforme em `[-1, 1]²` — geração vetorizada, UMA chamada a `process()` com arrays, SPEC §5.1); resposta da rota: `{"resolution": int, "values": list[list[float | None]]}` (NaN → `null` — `JSON` não aceita NaN, mesma regra do ADR-030). Resolução SEMPRE a do servidor (query param proibido — FUZZY-SEC).

- [ ] **Step 1: Write the failing test**

```python
# packages/ottima-core/tests/test_fuzzy_surface.py
import numpy as np

from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL
from ottima_core.flowgraph.fuzzy_surface import sample_surface


def test_superficie_default_65x65_sem_nan_e_com_origem_zero() -> None:
    grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL, resolution=65)
    assert grade.shape == (65, 65) and grade.dtype == np.float32
    assert not np.isnan(grade).any()
    centro = grade[32, 32]  # (e_n=0, de_n=0)
    assert abs(float(centro)) <= 0.02


def test_sinal_consistente_no_eixo_do_erro() -> None:
    grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL, resolution=65)
    assert float(grade[32, 64]) > 0.0  # e_n = +1 -> du_n > 0
    assert float(grade[32, 0]) < 0.0   # e_n = -1 -> du_n < 0
```

- [ ] **Step 2: Run to verify it fails** → FAIL

- [ ] **Step 3: Implement**

```python
# packages/ottima-core/src/ottima_core/flowgraph/fuzzy_surface.py
"""Amostragem vetorizada da superficie (e_n, de_n) -> du_n (SPEC_FUZZY secao 5).

pyfuzzylite 8.x aceita numpy.ndarray nas variaveis: um process() avalia a grade toda.
Resolucao e SEMPRE decidida pelo servidor (FUZZY-SEC).
"""

import fuzzylite as fl
import numpy as np


def sample_surface(fll: str, resolution: int = 65) -> np.ndarray:
    engine = fl.FllImporter().from_string(fll)
    eixo = np.linspace(-1.0, 1.0, resolution)
    de_grid, e_grid = np.meshgrid(eixo, eixo, indexing="ij")
    engine.input_variable("e").value = e_grid.ravel()
    engine.input_variable("de").value = de_grid.ravel()
    engine.process()
    du = np.asarray(engine.output_variable("du").value, dtype=np.float32)
    return du.reshape(resolution, resolution)
```

(Se a 8.0.6 exigir `restart()` antes de reatribuir arrays ou devolver shape diferente, ajustar guiado pelo teste — o contrato do teste é o juiz.)

Rota em `operate.py` (junto do GET de config da Task 8 do plano pid_loop): `GET /{flow_id}/{block_id}/surface`… **não** — manter no namespace de leitura: `GET /api/operate/loop/{flow_id}/{block_id}/surface`, `require_operator`, corpo: carrega `FuzzyLoopConfig` via `_loop_config`, 422 se o nó não for `fuzzy_loop`, roda `sample_surface(config.fll)` em `asyncio.to_thread` (mesmo padrão da introspecção do ADR-030), converte NaN→None.

Frontend: `HeatmapSuperficie.tsx` — react-query no endpoint, `<canvas>` com `ImageData` (azul→branco→vermelho para du_n −1..+1, célula por pixel escalado por CSS), ponto de operação sobreposto lendo `estado.diag.e_n`/`estado.diag.de_n` do `loop_state`; aba "Superfície" na `LoopOperatePage` renderizada quando o discovery marcar o bloco como `fuzzy_loop` (adicionar `type` no payload do discovery da Task 8 do plano pid_loop, se ainda não tiver).

- [ ] **Step 4: Run** — `uv run pytest packages/ottima-core/tests/test_fuzzy_surface.py -q` → PASS; `cd frontend && npm run typecheck && npm run test:unit` → PASS. Smoke visual: dev stack + `/loop` num `fuzzy_loop`, heatmap com ponto se mexendo.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && git add -A packages/ottima-core services/api frontend/src
git commit -m "feat(fuzzy_loop): superficie amostrada server-side e heatmap com ponto de operacao"
```

---

### Task 6: Fase K3 — LUT content-addressed + portões (F4, F8, F9)

**Files:**
- Create: `packages/ottima-core/alembic/versions/0016_fuzzy_surface_lut.py`
- Create: `packages/ottima-core/src/ottima_core/flowgraph/lut_gates.py`
- Modify: `packages/ottima-core/src/ottima_core/flowgraph/validate.py` (`_valida_fuzzy_loop` passa a rodar os portões sobre a superfície amostrada)
- Modify: `services/flow-runtime/src/ottima_flow_runtime/blocks/kernels/fuzzy.py` (interpolação bilinear quando `lut_enabled`)
- Modify: `services/api` (persistência da LUT no save por `fll_hash`; a rota `/surface` passa a preferir a LUT persistida)
- Test: `packages/ottima-core/tests/test_lut_gates.py`, `services/flow-runtime/tests/test_fuzzy_lut.py`

**Interfaces:**
- Produces: tabela `fuzzy_surface_lut (fll_hash text PK, resolution int, payload bytea, generated_at timestamptz)` (migration 0016, `down_revision = "0015_loop_tables"`); `run_lut_gates(grade: np.ndarray, *, direct_acting: bool = False) -> list[str]` com códigos `NO_NAN`, `SIGN_CONSISTENCY`, `MONOTONIC_E`, `BOUNDED_GAIN`, `NO_DEAD_ZONE`, `CONTINUITY`, `ORIGIN_ZERO` e constantes `GAIN_MAX = 8.0`, `STEP_MAX = 0.25`, `DEAD_ZONE_MAX = 0.3`, `TOL = 0.02` (defaults de servidor; ajustáveis depois por evidência de campo); `FuzzyKernel` com `lut: np.ndarray | None` e `_interp_bilinear(e_n, de_n) -> float`.

- [ ] **Step 1: Write the failing gate tests**

```python
# packages/ottima-core/tests/test_lut_gates.py
"""Portoes de validacao da superficie (SPEC_FUZZY secao 5.3). F4 na camada dos portoes."""

import numpy as np

from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL
from ottima_core.flowgraph.fuzzy_surface import sample_surface
from ottima_core.flowgraph.lut_gates import run_lut_gates


def test_default_fll_passa_em_todos_os_portoes() -> None:
    assert run_lut_gates(sample_surface(FUZZY_LOOP_DEFAULT_FLL)) == []


def test_f4_sinal_invertido_bloqueia() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace(
        "rule: if e is PG then du is PG", "rule: if e is PG then du is NG"
    )
    assert "SIGN_CONSISTENCY" in run_lut_gates(sample_surface(fll))


def test_nan_bloqueia() -> None:
    grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL).copy()
    grade[10, 10] = np.nan
    assert "NO_NAN" in run_lut_gates(grade)


def test_origem_fora_de_zero_bloqueia() -> None:
    grade = sample_surface(FUZZY_LOOP_DEFAULT_FLL) + np.float32(0.5)
    erros = run_lut_gates(grade)
    assert "ORIGIN_ZERO" in erros
```

- [ ] **Step 2: Run to verify it fails** → FAIL

- [ ] **Step 3: Implement `lut_gates.py`**

```python
# packages/ottima-core/src/ottima_core/flowgraph/lut_gates.py
"""Portoes sobre a superficie (SPEC_FUZZY secao 5.3): falha bloqueia o save."""

import numpy as np

TOL = 0.02
GAIN_MAX = 8.0        # d(du_n)/d(e_n) maximo (ganho equivalente em malha fechada)
STEP_MAX = 0.25       # descontinuidade maxima entre celulas vizinhas no eixo e
DEAD_ZONE_MAX = 0.3   # fracao maxima do eixo e com derivada ~zero fora da origem


def run_lut_gates(grade: np.ndarray, *, direct_acting: bool = False) -> list[str]:
    erros: list[str] = []
    if np.isnan(grade).any():
        return ["NO_NAN"]  # os demais portoes nao fazem sentido com buraco
    g = -grade if direct_acting else grade
    n = g.shape[1]
    eixo_e = np.linspace(-1.0, 1.0, n)
    passo_e = eixo_e[1] - eixo_e[0]

    # SIGN_CONSISTENCY avaliado na faixa central de de (|de_n| <= 0.25): fora dela a
    # anticipacao derivativa legitima inverte du (ex.: e~0+ com de N -> du NP), e o texto
    # literal da SPEC secao 5.3 reprovaria qualquer base com regra de de. Divergencia
    # deliberada — corrigir o criterio da SPEC secao 5.3 no MESMO commit desta task.
    eixo_de = np.linspace(-1.0, 1.0, g.shape[0])
    gc = g[np.abs(eixo_de) <= 0.25, :]
    if (gc[:, eixo_e > TOL] < -TOL).any() or (gc[:, eixo_e < -TOL] > TOL).any():
        erros.append("SIGN_CONSISTENCY")
    de_dg = np.diff(g, axis=1) / passo_e
    if (de_dg < -TOL).any():
        erros.append("MONOTONIC_E")
    if float(de_dg.max()) > GAIN_MAX:
        erros.append("BOUNDED_GAIN")
    fora_da_origem = np.abs((eixo_e[:-1] + eixo_e[1:]) / 2.0) > 0.15
    mortas = (np.abs(de_dg[:, fora_da_origem]) < TOL).mean(axis=1)
    if float(mortas.max()) > DEAD_ZONE_MAX:
        erros.append("NO_DEAD_ZONE")
    if float(np.abs(np.diff(g, axis=1)).max()) > STEP_MAX:
        erros.append("CONTINUITY")
    centro = n // 2
    if abs(float(g[centro, centro])) > TOL:
        erros.append("ORIGIN_ZERO")
    return erros
```

- [ ] **Step 4: Wire into save + runtime + persistence**

1. `validate.py::_valida_fuzzy_loop`: após o contrato, `from ottima_core.flowgraph.fuzzy_surface import sample_surface; from ottima_core.flowgraph.lut_gates import run_lut_gates` (lazy, dentro da função) e anexar cada código como erro pt-BR: `f"{where}: portao de superficie reprovado — {codigo}"`.
2. Migration `0016_fuzzy_surface_lut.py` (idiomas de 0014; PK `fll_hash`, sem FK — content-addressed, ADR-039 D11).
3. No save da API (onde `PUT /api/flows/{id}` valida e grava — localizar com `grep -rn "validate_graph" services/api`): para cada nó `fuzzy_loop` com `lut_enabled`, calcular `fll_hash = sha256(fll)`, e upsert em `fuzzy_surface_lut` com `payload = grade.astype(np.float32).tobytes()` se o hash não existir (dedupe).
4. `kernels/fuzzy.py`: `build_fuzzy_kernel` ganha parâmetro `lut_enabled`/`lut_resolution`; quando habilitado, gera a grade na instanciação (`sample_surface`, uma chamada) e `compute` usa `_interp_bilinear` (saturação nas bordas) em vez de `eng.process()` — o engine fica só para revalidação. `definition.py` repassa os dois campos.

- [ ] **Step 5: Write F8/F9 tests**

```python
# services/flow-runtime/tests/test_fuzzy_lut.py
"""F8: LUT vs inferencia direta; F9 (slow): carga Mamdani a Ts=0.5s."""

import random
import time

import pytest

from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL
from ottima_flow_runtime.blocks.kernels.fuzzy import FuzzyKernelCfg, build_fuzzy_kernel


def test_f8_lut_coincide_com_inferencia_em_10k_pontos() -> None:
    cfg = FuzzyKernelCfg(ke=1.0, kde=1.0, ku=100.0)  # e/de ja normalizados no teste
    direto = build_fuzzy_kernel(FUZZY_LOOP_DEFAULT_FLL, cfg)
    com_lut = build_fuzzy_kernel(FUZZY_LOOP_DEFAULT_FLL, cfg, lut_enabled=True, lut_resolution=65)
    rng = random.Random(1)
    pior = 0.0
    for _ in range(10_000):
        e = rng.uniform(-1.0, 1.0)
        direto.align(0.0, e, 0.0)
        com_lut.align(0.0, e, 0.0)
        a = direto.compute(sp=e, pv=0.0, dt=1.0)
        b = com_lut.compute(sp=e, pv=0.0, dt=1.0)
        pior = max(pior, abs(a - b))
    assert pior <= 0.5  # 0.5% do span (ku=100 -> du/dt em % ja e o proprio du_n*100)


@pytest.mark.slow
def test_f9_50_blocos_mamdani_centroid_em_meio_segundo() -> None:
    mamdani = FUZZY_LOOP_DEFAULT_FLL.replace("aggregation: none", "aggregation: Maximum").replace(
        "defuzzifier: WeightedAverage", "defuzzifier: Centroid 100"
    ).replace("implication: AlgebraicProduct", "implication: Minimum")
    for termo in ("NG Constant -1.000", "NP Constant -0.500", "ZE Constant 0.000",
                  "PP Constant 0.500", "PG Constant 1.000"):
        nome, _, valor = termo.partition(" Constant ")
        v = float(valor)
        mamdani = mamdani.replace(
            f"term: {termo}", f"term: {nome} Triangle {v - 0.5:.3f} {v:.3f} {v + 0.5:.3f}"
        )
    cfg = FuzzyKernelCfg(ke=0.1, kde=0.0, ku=5.0)
    blocos = [build_fuzzy_kernel(mamdani, cfg) for _ in range(50)]
    assert all(b.validate() == [] for b in blocos)
    inicio = time.perf_counter()
    for b in blocos:
        b.compute(sp=3.0, pv=0.0, dt=0.5)
    total = time.perf_counter() - inicio
    assert total < 0.5 * 0.30  # soma dos steps < 30% do periodo de 0.5s
```

- [ ] **Step 6: Run**

```bash
uv run pytest packages/ottima-core/tests/test_lut_gates.py services/flow-runtime/tests/test_fuzzy_lut.py -q
uv run pytest services/flow-runtime/tests/test_fuzzy_lut.py -m slow -q   # F9 explicito
uv run alembic -c packages/ottima-core/alembic.ini upgrade head --sql | tail -20
```
Expected: PASS nos três. Se F9 estourar o orçamento, a recomendação da SPEC §4.3 (Sugeno como padrão) vira obrigatória — documentar o resultado no commit.

- [ ] **Step 7: Commit**

```bash
uv run ruff check . && uv run ruff format packages/ottima-core services
git add -A packages/ottima-core services frontend/src
git commit -m "feat(fuzzy_loop): fase K3 — LUT content-addressed, portoes de superficie e F8/F9"
```

---

### Task 7: Gate final

- [ ] **Step 1: Backend + frontend completos**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest packages/ottima-core/tests services/flow-runtime/tests services/api/tests services/recorder/tests -q
cd frontend && npm run test:unit && npm run typecheck && npm run build
npm run generate:contracts && git diff --exit-code -- src/lib/contracts.gen.ts
```

- [ ] **Step 2: Smoke end-to-end** — dev stack: flow com `tfs → fuzzy_loop → (malha fechada via tfs)`, deploy; faceplate `/loop`: MAN→AUTO com o FLL default, ver PV convergir ao SP; abrir a aba Superfície e ver o ponto `(e_n, de_n)` caminhar para a origem; colar um FLL com `lock-previous: true` no editor e confirmar o 422 pt-BR no save (F2 fim-a-fim); trocar o FLL válido com a malha em AUTO e confirmar a aterrissagem em MAN + evento no banner (F11 fim-a-fim).

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat(fuzzy_loop): Fuzzy Malha completo — kernel, contrato FLL, heatmap e LUT"
```

---

## Cobertura F1–F11 (SPEC_FUZZY §9)

| F | Onde |
|---|---|
| F1 | `test_fll_contract.py` (validador) + `test_fuzzy_loop_registro.py` (save 422) + `BrokenKernel` (deploy→OOS) |
| F2 | `test_fll_contract.py::test_f2_lock_previous_true_e_rejeitado_com_codigo_dedicado` |
| F3 | `test_fuzzy_kernel.py::test_f3_regiao_sem_regra_propaga_nan` + `test_fuzzy_loop_acceptance.py::test_s12_regiao_sem_regra_segura_out` |
| F4 | `test_lut_gates.py::test_f4_sinal_invertido_bloqueia` (K3) |
| F5 | `test_fuzzy_loop_acceptance.py::test_f5_...` |
| F6 | `test_fuzzy_kernel.py::test_sinal_consistente_e_ganho_ku` |
| F7 | `test_fuzzy_kernel.py::test_f7_duas_instancias_mesmo_fll_sao_isoladas` |
| F8 | `test_fuzzy_lut.py::test_f8_...` (K3) |
| F9 | `test_fuzzy_lut.py::test_f9_...` (K3, `-m slow`) |
| F10 | `test_fuzzy_loop_definition.py::test_f10_troca_de_ku_em_auto_sem_degrau` |
| F11 | `test_fuzzy_loop_definition.py::test_f11_troca_de_fll_e_estrutural` + smoke fim-a-fim (Task 7) |
