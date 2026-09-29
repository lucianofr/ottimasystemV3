# Block Shell Foundation (ADR-039 fases 1–2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar o shell de bloco de controle do ADR-039 (`BlockShell` + contratos `Signal`/`Mode`/`ControlKernel` + kernel stub) com os testes de aceitação S1–S17 verdes — sem tocar em nenhum bloco existente.

**Architecture:** Novo pacote `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/` contendo tipos puros (signal, mode, kernel, config) e a classe `BlockShell(Block)` — a máquina de modos FF que envolve um kernel incremental injetado. Nenhuma mudança em scheduler, base class, parse, API ou frontend neste plano (isso é o plano `2026-08-31-pid-loop.md`). Tudo é testável por pytest puro com um kernel stub determinístico.

**Tech Stack:** Python (workspace `uv`), pytest com `asyncio_mode=auto` (funções `async def test_*` soltas, sem fixtures — convenção de `services/flow-runtime/tests/test_pid.py`), dataclasses stdlib. Zero dependências novas.

**Spec:** `docs/adr/ADR-039-block-shell.md` (§3 D1–D11, §4 contratos, §7 testes S1–S17). Specs consumidoras: `docs/specs/SPEC_PID_with_SHELL.md`, `docs/specs/SPEC_FUZZY_with_SHELL.md`.

## Global Constraints

- Blocos existentes (`pid`, `fuzzy`, `mpc`, filtros) **não são alterados** (ADR-039 D8).
- Nenhuma mudança em `scheduler.py`, `base.py`, `definition.py` neste plano — o shell deriva `dt` sozinho a partir do `ts` que `step()` já recebe (ADR-039 D7).
- `u` interno sempre em % entre `OUT_LO_LIM`/`OUT_HI_LIM`; porta `out` emite EU via `OUT_SCALE` (ADR-039 §4.6).
- Nenhum `if` que teste transição específica de modo no shell (critério de revisão do ADR-039 §4.7).
- NaN/None nunca propagam para a porta `out` com `ok=True` (garantia da casa, ADR-029/031).
- Strings de mensagem/alarme em pt-BR; código e identificadores em inglês (convenção do repo).
- Lint: `uv run ruff check .` e `uv run ruff format .` antes de cada commit.
- Testes: `uv run pytest services/flow-runtime/tests/<arquivo> -q`. Nunca rodar a suíte inteira do workspace no meio do plano.
- Commits: conventional commits (`feat:`, `test:`, `refactor:`).
- Tolerância dos testes S: `EPS = 0.01` (% do span de OUT), conforme ADR-039 §7.

**Interfaces da casa (fatos verificados, não invente variações):**

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/base.py:29-81 (JÁ EXISTE — não alterar)
@dataclass(frozen=True, slots=True)
class PortSample:
    v: float | bool | None
    ok: bool

class Block(ABC):
    def __init__(self, block_id: str) -> None: ...
    @property
    def input_ports(self) -> tuple[str, ...]: ...
    @property
    def output_ports(self) -> tuple[str, ...]: ...
    @abstractmethod
    async def step(self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None) -> dict[str, PortSample]: ...
    def reset(self) -> None: ...
```

---

### Task 1: Signal — status que viaja com o valor

**Files:**
- Create: `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/__init__.py`
- Create: `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/signal.py`
- Test: `services/flow-runtime/tests/test_shell_signal.py`

**Interfaces:**
- Consumes: `PortSample` de `ottima_flow_runtime.blocks.base`.
- Produces: `Quality(IntEnum)`, `Substatus(IntEnum)`, `Signal(PortSample)` com campos extras `quality/substatus/hi_limited/lo_limited` e propriedades `is_good`/`init_request`; `make_signal(value, quality, substatus=..., hi_limited=..., lo_limited=...) -> Signal`; `as_signal(sample: PortSample) -> Signal` (promoção implícita ADR-039 §4.1). Tasks 5–11 e os planos pid/fuzzy usam exatamente esses nomes.

- [ ] **Step 1: Write the failing test**

```python
# services/flow-runtime/tests/test_shell_signal.py
"""Signal (ADR-039 secao 4.1): status viaja com o valor; promocao implicita de PortSample."""

import math

from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.shell.signal import Quality, Signal, Substatus, as_signal, make_signal


def test_signal_e_um_portsample_e_ok_espelha_quality() -> None:
    s = make_signal(42.0, Quality.GOOD)
    assert isinstance(s, PortSample)
    assert s.v == 42.0 and s.ok is True
    assert s.is_good is True

    ruim = make_signal(1.0, Quality.BAD, substatus=Substatus.SENSOR_FAILURE)
    assert ruim.ok is False and ruim.is_good is False


def test_uncertain_e_tratado_como_good_na_v1() -> None:
    s = make_signal(7.0, Quality.UNCERTAIN)
    assert s.is_good is True and s.ok is True


def test_promocao_de_portsample_para_signal() -> None:
    bom = as_signal(PortSample(3.5, True))
    assert isinstance(bom, Signal) and bom.quality is Quality.GOOD and bom.v == 3.5

    ruim = as_signal(PortSample(1.0, False))
    assert ruim.quality is Quality.BAD and ruim.ok is False

    frio = as_signal(PortSample(None, False))
    assert frio.v is None and frio.quality is Quality.BAD


def test_promocao_de_signal_devolve_o_proprio_objeto() -> None:
    original = make_signal(1.0, Quality.GOOD, hi_limited=True)
    assert as_signal(original) is original


def test_init_request() -> None:
    ir = make_signal(50.0, Quality.GOOD, substatus=Substatus.INIT_REQUEST)
    assert ir.init_request is True
    assert make_signal(50.0, Quality.GOOD).init_request is False


def test_default_signal_e_bad_nan() -> None:
    s = Signal(v=math.nan, ok=False)
    assert s.quality is Quality.BAD and s.substatus is Substatus.NON_SPECIFIC
    assert s.hi_limited is False and s.lo_limited is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest services/flow-runtime/tests/test_shell_signal.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ottima_flow_runtime.blocks.shell'`

- [ ] **Step 3: Write minimal implementation**

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/shell/__init__.py
"""Shell de bloco de controle no padrao Fieldbus Foundation (ADR-039)."""
```

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/shell/signal.py
"""Signal: valor + status na mesma porta (ADR-039 secao 4.1).

`Signal` ESTENDE o PortSample existente: todo consumidor legado le `v`/`ok` sem saber de
quality; blocos malha leem o status completo. Promocao implicita nas arestas via
`as_signal` — sem blocos conversores. UNCERTAIN e tratado como GOOD na v1 (STATUS_OPTS:
ADR-039 secao 9).
"""

from dataclasses import dataclass
from enum import IntEnum

from ottima_flow_runtime.blocks.base import PortSample


class Quality(IntEnum):
    BAD = 0
    UNCERTAIN = 1
    GOOD = 2


class Substatus(IntEnum):
    NON_SPECIFIC = 0
    INIT_REQUEST = 1  # IR: o bloco a jusante nao esta aceitando cascata
    NOT_INVITED = 2  # reservado ao CONTROL_SELECTOR (ADR-039 secao 9)
    LOCAL_OVERRIDE = 3
    SENSOR_FAILURE = 4
    CONFIG_ERROR = 5
    DEVICE_FAILURE = 6


@dataclass(frozen=True, slots=True)
class Signal(PortSample):
    quality: Quality = Quality.BAD
    substatus: Substatus = Substatus.NON_SPECIFIC
    hi_limited: bool = False
    lo_limited: bool = False

    @property
    def is_good(self) -> bool:
        return self.quality is not Quality.BAD

    @property
    def init_request(self) -> bool:
        return self.substatus is Substatus.INIT_REQUEST


def make_signal(
    value: float | None,
    quality: Quality,
    *,
    substatus: Substatus = Substatus.NON_SPECIFIC,
    hi_limited: bool = False,
    lo_limited: bool = False,
) -> Signal:
    """Constroi um Signal mantendo o invariante `ok == (quality != BAD)`."""
    return Signal(
        v=value,
        ok=quality is not Quality.BAD,
        quality=quality,
        substatus=substatus,
        hi_limited=hi_limited,
        lo_limited=lo_limited,
    )


def as_signal(sample: PortSample) -> Signal:
    """Promocao implicita da aresta: (v, ok) -> Signal; Signal passa intacto."""
    if isinstance(sample, Signal):
        return sample
    return Signal(v=sample.v, ok=sample.ok, quality=Quality.GOOD if sample.ok else Quality.BAD)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest services/flow-runtime/tests/test_shell_signal.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check services/flow-runtime && uv run ruff format services/flow-runtime
git add services/flow-runtime/src/ottima_flow_runtime/blocks/shell/ services/flow-runtime/tests/test_shell_signal.py
git commit -m "feat(shell): Signal com quality/substatus estendendo PortSample (ADR-039 D4)"
```

---

### Task 2: Mode — modos FF, alvo × real

**Files:**
- Create: `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/mode.py`
- Test: `services/flow-runtime/tests/test_shell_mode.py`

**Interfaces:**
- Produces: `Mode(IntFlag)` (OOS=0x80, IMAN=0x40, LO=0x20, MAN=0x10, AUTO=0x08, CAS=0x04, RCAS=0x02, ROUT=0x01), `ModeBlock` (dataclass mutável: `target`, `actual`, `permitted`, `normal`), `CALCULATING_MODES: frozenset[Mode]`, `MODE_NAMES: dict[Mode, str]` (nomes minúsculos p/ eventos: `"oos"`, `"iman"`, `"lo"`, `"man"`, `"auto"`, `"cas"`, `"rcas"`, `"rout"`), `mode_from_name(name: str) -> Mode`. Tasks 5–11 e os planos pid/fuzzy usam esses nomes.

- [ ] **Step 1: Write the failing test**

```python
# services/flow-runtime/tests/test_shell_mode.py
"""Modos FF (ADR-039 secao 4.2): peso numerico maior = prioridade maior."""

from ottima_flow_runtime.blocks.shell.mode import (
    CALCULATING_MODES,
    Mode,
    ModeBlock,
    mode_from_name,
    MODE_NAMES,
)


def test_pesos_ff_dao_a_ordem_de_prioridade() -> None:
    assert Mode.OOS > Mode.IMAN > Mode.LO > Mode.MAN > Mode.AUTO > Mode.CAS > Mode.RCAS > Mode.ROUT


def test_permitted_e_mascara() -> None:
    mb = ModeBlock()
    assert mb.target is Mode.MAN and mb.actual is Mode.OOS
    assert Mode.AUTO & mb.permitted
    assert not (Mode.CAS & mb.permitted)  # cascata exige habilitacao explicita


def test_modos_calculantes() -> None:
    assert CALCULATING_MODES == frozenset({Mode.AUTO, Mode.CAS, Mode.RCAS})
    assert Mode.MAN not in CALCULATING_MODES


def test_nomes_ida_e_volta() -> None:
    for mode, name in MODE_NAMES.items():
        assert mode_from_name(name) is mode
    assert mode_from_name("auto") is Mode.AUTO
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest services/flow-runtime/tests/test_shell_mode.py -q`
Expected: FAIL — `ModuleNotFoundError` (mode.py não existe)

- [ ] **Step 3: Write minimal implementation**

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/shell/mode.py
"""Modos do shell (ADR-039 secao 4.2). Bits identicos ao Foundation Fieldbus."""

from dataclasses import dataclass, field
from enum import IntFlag


class Mode(IntFlag):
    """Pesos FF. Valor numerico maior = prioridade maior."""

    OOS = 0x80  # out of service
    IMAN = 0x40  # initialization manual, imposto pelo bloco a jusante
    LO = 0x20  # local override, imposto por intertravamento
    MAN = 0x10  # operador escreve OUT
    AUTO = 0x08  # SP local
    CAS = 0x04  # SP de cas_in
    RCAS = 0x02  # SP de rcas_in (supervisor, MPC)
    ROUT = 0x01  # OUT de rout_in (supervisor)


CALCULATING_MODES: frozenset[Mode] = frozenset({Mode.AUTO, Mode.CAS, Mode.RCAS})

MODE_NAMES: dict[Mode, str] = {
    Mode.OOS: "oos",
    Mode.IMAN: "iman",
    Mode.LO: "lo",
    Mode.MAN: "man",
    Mode.AUTO: "auto",
    Mode.CAS: "cas",
    Mode.RCAS: "rcas",
    Mode.ROUT: "rout",
}

_BY_NAME = {name: mode for mode, name in MODE_NAMES.items()}


def mode_from_name(name: str) -> Mode:
    return _BY_NAME[name]


@dataclass(slots=True)
class ModeBlock:
    target: Mode = Mode.MAN  # TARGET nasce MAN: engajar e ato do operador (ADR-039 4.10)
    actual: Mode = Mode.OOS
    permitted: Mode = field(default=Mode.OOS | Mode.MAN | Mode.AUTO)
    normal: Mode = Mode.AUTO
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest services/flow-runtime/tests/test_shell_mode.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
uv run ruff check services/flow-runtime && uv run ruff format services/flow-runtime
git add services/flow-runtime/src/ottima_flow_runtime/blocks/shell/mode.py services/flow-runtime/tests/test_shell_mode.py
git commit -m "feat(shell): Mode/ModeBlock com bits FF e CALCULATING_MODES (ADR-039 D5)"
```

---

### Task 3: ControlKernel protocol + kernel stub determinístico

**Files:**
- Create: `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/kernel.py`
- Test: `services/flow-runtime/tests/test_shell_kernel.py`

**Interfaces:**
- Produces: `ControlKernel(Protocol)` com `compute(sp, pv, dt) -> float` (du/dt em %span/s; NaN = inválido), `align(u, sp, pv) -> None`, `reset() -> None`, `validate() -> list[str]`; e `StubKernel` (kernel de teste: `gain` proporcional ao erro + `rate` constante, `align_calls: list[tuple[float, float, float]]`, `errors: list[str]`). `PidKernel`/`FuzzyKernel` (planos seguintes) implementam este protocol; todos os testes S usam `StubKernel`.

- [ ] **Step 1: Write the failing test**

```python
# services/flow-runtime/tests/test_shell_kernel.py
"""Protocolo do kernel (ADR-039 secao 4.5) e o stub deterministico dos testes S."""

import math

from ottima_flow_runtime.blocks.shell.kernel import ControlKernel, StubKernel


def test_stub_satisfaz_o_protocol() -> None:
    kernel: ControlKernel = StubKernel()
    assert kernel.validate() == []


def test_stub_proporcional_ao_erro_mais_taxa_constante() -> None:
    k = StubKernel(gain=2.0, rate=0.5)
    assert k.compute(sp=10.0, pv=7.0, dt=0.5) == 2.0 * 3.0 + 0.5


def test_stub_registra_align_e_reset_limpa() -> None:
    k = StubKernel()
    k.align(50.0, 10.0, 9.0)
    assert k.align_calls == [(50.0, 10.0, 9.0)]
    k.reset()
    assert k.align_calls == []


def test_stub_pode_devolver_nan() -> None:
    k = StubKernel()
    k.rate = math.nan
    assert math.isnan(k.compute(0.0, 0.0, 1.0))


def test_stub_erros_de_validacao_configuraveis() -> None:
    k = StubKernel()
    k.errors.append("CONFIG_QUALQUER")
    assert k.validate() == ["CONFIG_QUALQUER"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest services/flow-runtime/tests/test_shell_kernel.py -q`
Expected: FAIL — `ModuleNotFoundError` (kernel.py não existe)

- [ ] **Step 3: Write minimal implementation**

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/shell/kernel.py
"""Protocolo do kernel de controle (ADR-039 secao 4.5) e o stub dos testes S."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ControlKernel(Protocol):
    def compute(self, sp: float, pv: float, dt: float) -> float:
        """Retorna du/dt em % do span de OUT por segundo.

        Pode retornar NaN para sinalizar que o algoritmo nao produziu resultado valido
        neste scan. O shell trata NaN mantendo a saida e alarmando; nunca propaga NaN.
        """
        ...

    def align(self, u: float, sp: float, pv: float) -> None:
        """Realinha o historico interno para o estado corrente.

        Chamado pelo shell a cada scan em que compute() nao executa. Apos align(), a
        proxima chamada a compute() nao pode produzir transiente de historico obsoleto.
        """
        ...

    def reset(self) -> None:
        """Descarta todo historico interno."""
        ...

    def validate(self) -> list[str]:
        """Lista de erros de configuracao. Vazia = kernel apto a operar."""
        ...


class StubKernel:
    """Kernel deterministico dos testes de aceitacao do shell (ADR-039 secao 7).

    `compute` devolve `gain * (sp - pv) + rate` — um P puro em forma incremental, o
    suficiente para fechar malha nos cenarios S sem depender de PID/Fuzzy reais.
    """

    def __init__(self, *, gain: float = 0.0, rate: float = 0.0) -> None:
        self.gain = gain
        self.rate = rate
        self.align_calls: list[tuple[float, float, float]] = []
        self.errors: list[str] = []

    def compute(self, sp: float, pv: float, dt: float) -> float:  # noqa: ARG002
        return self.gain * (sp - pv) + self.rate

    def align(self, u: float, sp: float, pv: float) -> None:
        self.align_calls.append((u, sp, pv))

    def reset(self) -> None:
        self.align_calls.clear()

    def validate(self) -> list[str]:
        return list(self.errors)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest services/flow-runtime/tests/test_shell_kernel.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
uv run ruff check services/flow-runtime && uv run ruff format services/flow-runtime
git add services/flow-runtime/src/ottima_flow_runtime/blocks/shell/kernel.py services/flow-runtime/tests/test_shell_kernel.py
git commit -m "feat(shell): protocolo ControlKernel e StubKernel deterministico (ADR-039 D2/D3)"
```

---

### Task 4: ShellCfg — configuração runtime + escala/clamp

**Files:**
- Create: `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/config.py`
- Test: `services/flow-runtime/tests/test_shell_config.py`

**Interfaces:**
- Produces: `ShellCfg` (dataclass mutável, tudo em unidades de runtime), `SHED_TO: dict[str, ...]` não — o destino do shed resolve na Task 6; aqui: helpers `clamp(v, lo, hi) -> float`, `scale_pct(v_eu, lo, hi) -> float` (EU→%), `unscale_pct(pct, lo, hi) -> float` (%→EU). Campos de `ShellCfg` (usados por TODAS as tasks seguintes e pelos planos pid/fuzzy — nomes exatos):
  `permitted: Mode`, `normal: Mode`, `shed_opt: str` (`"shed_to_auto" | "shed_to_man" | "shed_to_normal"`), `shed_no_return: bool`, `direct_acting: bool`, `sp_pv_track_in_man: bool`, `use_pv_for_bkcal: bool`, `track_enable: bool`, `track_in_manual: bool`, `sp_hi_lim: float`, `sp_lo_lim: float`, `sp_rate_up: float | None`, `sp_rate_dn: float | None` (EU/s), `out_hi_lim: float`, `out_lo_lim: float` (%), `out_rate_up: float | None`, `out_rate_dn: float | None` (%/s), `out_scale_lo: float`, `out_scale_hi: float` (EU), `out_startup: float` (%), `pv_ftime: float` (s, 0 = sem filtro), `max_dt: float` (s), `trk_val: float`, `lo_val: float` (%), `ff_scale_lo: float`, `ff_scale_hi: float`, `ff_gain: float`, `ff_enable: bool`.

- [ ] **Step 1: Write the failing test**

```python
# services/flow-runtime/tests/test_shell_config.py
"""ShellCfg e helpers de escala (ADR-039 secao 4.6)."""

from ottima_flow_runtime.blocks.shell.config import ShellCfg, clamp, scale_pct, unscale_pct
from ottima_flow_runtime.blocks.shell.mode import Mode


def test_defaults_seguros() -> None:
    cfg = ShellCfg(sp_hi_lim=100.0, sp_lo_lim=0.0, max_dt=10.0)
    assert cfg.out_lo_lim == 0.0 and cfg.out_hi_lim == 100.0
    assert cfg.out_scale_lo == 0.0 and cfg.out_scale_hi == 100.0  # identidade: % = EU
    assert cfg.permitted == Mode.OOS | Mode.MAN | Mode.AUTO
    assert cfg.sp_pv_track_in_man is True  # default ON (ADR-039 secao 4.9)
    assert cfg.shed_opt == "shed_to_auto" and cfg.shed_no_return is False
    assert cfg.out_startup == 0.0 and cfg.ff_enable is False


def test_clamp() -> None:
    assert clamp(150.0, 0.0, 100.0) == 100.0
    assert clamp(-1.0, 0.0, 100.0) == 0.0
    assert clamp(42.0, 0.0, 100.0) == 42.0


def test_escala_eu_pct_ida_e_volta() -> None:
    # OUT_SCALE (0, 400) m3/h: 50% -> 200 EU -> 50%
    assert unscale_pct(200.0, 0.0, 400.0) == 50.0
    assert scale_pct(50.0, 0.0, 400.0) == 200.0
    # identidade default
    assert scale_pct(37.5, 0.0, 100.0) == 37.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest services/flow-runtime/tests/test_shell_config.py -q`
Expected: FAIL — `ModuleNotFoundError` (config.py não existe)

- [ ] **Step 3: Write minimal implementation**

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/shell/config.py
"""Configuracao runtime do shell (ADR-039 secoes 4.6, 4.8, 4.9).

Dataclass mutavel de proposito: a classe de sintonia do hot-swap (ADR-039 D11) troca este
objeto in-place via BlockShell.apply_tuning, preservando o estado do bloco.
"""

from dataclasses import dataclass

from ottima_flow_runtime.blocks.shell.mode import Mode


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def scale_pct(pct: float, lo: float, hi: float) -> float:
    """% do span -> EU."""
    return lo + (pct / 100.0) * (hi - lo)


def unscale_pct(v_eu: float, lo: float, hi: float) -> float:
    """EU -> % do span."""
    return (v_eu - lo) / (hi - lo) * 100.0


@dataclass(slots=True)
class ShellCfg:
    sp_hi_lim: float
    sp_lo_lim: float
    max_dt: float
    permitted: Mode = Mode.OOS | Mode.MAN | Mode.AUTO
    normal: Mode = Mode.AUTO
    shed_opt: str = "shed_to_auto"
    shed_no_return: bool = False
    direct_acting: bool = False
    sp_pv_track_in_man: bool = True
    use_pv_for_bkcal: bool = False
    track_enable: bool = False
    track_in_manual: bool = False
    sp_rate_up: float | None = None
    sp_rate_dn: float | None = None
    out_hi_lim: float = 100.0
    out_lo_lim: float = 0.0
    out_rate_up: float | None = None
    out_rate_dn: float | None = None
    out_scale_lo: float = 0.0
    out_scale_hi: float = 100.0
    out_startup: float = 0.0
    pv_ftime: float = 0.0
    trk_val: float = 0.0
    lo_val: float = 0.0
    ff_scale_lo: float = 0.0
    ff_scale_hi: float = 100.0
    ff_gain: float = 1.0
    ff_enable: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest services/flow-runtime/tests/test_shell_config.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
uv run ruff check services/flow-runtime && uv run ruff format services/flow-runtime
git add services/flow-runtime/src/ottima_flow_runtime/blocks/shell/config.py services/flow-runtime/tests/test_shell_config.py
git commit -m "feat(shell): ShellCfg e helpers de escala OUT (ADR-039 secao 4.6)"
```

---

### Task 5: BlockShell — esqueleto, dt medido, partida e S14

**Files:**
- Create: `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py`
- Create: `services/flow-runtime/tests/shell_harness.py` (helpers compartilhados pelos testes S)
- Test: `services/flow-runtime/tests/test_shell_block_basics.py`

**Interfaces:**
- Consumes: Tasks 1–4 (`Signal`, `Mode`, `ControlKernel`, `ShellCfg`).
- Produces: `BlockShell(Block)` com:
  - `__init__(self, block_id: str, *, kernel: ControlKernel, cfg: ShellCfg, emit_event: EmitEvent | None = None, publish_state: PublishState | None = None, persist_op: PersistOp | None = None, sp_seed: float | None = None, man_out_seed: float | None = None, carry: CarriedState | None = None)` — closures async opcionais (`EmitEvent = Callable[..., Awaitable[None]]` com kwargs `kind, severity, message, payload`; `PersistOp = Callable[[str, float], Awaitable[None]]`).
  - `input_ports = ("in", "cas_in", "rcas_in", "rout_in", "bkcal_in", "bias_in", "trk_in_d", "lo_in_d")`; `output_ports = ("out", "bkcal_out")`.
  - Estado público lido pelos testes e pelo `LoopState` (plano pid): `mode: ModeBlock`, `u: float` (%), `u_int: float`, `sp: float` (EU), `sp_op: float`, `man_out: float`, `pv: float | None`, `pv_ok: bool`, `diag: dict[str, float]`.
  - Escritas de operação: `write_target(mode: Mode) -> bool` (False se fora de `permitted`), `write_sp(value: float) -> None`, `write_out(value: float) -> None` (escreve `man_out`, clampado).
  - `CarriedState` (dataclass: `u: float`, `sp_op: float`, `man_out: float`, `was_calculating: bool`) — usado pelo hot-swap estrutural (S16).
  - Constantes de evento: `KIND_LOOP_MODE_CHANGED = "loop_mode_changed"`, `KIND_LOOP_SHED = "loop_shed"`, `KIND_LOOP_MODE_REJECTED = "loop_mode_rejected"`, `KIND_LOOP_ALARM = "loop_alarm"`, `KIND_LOOP_LIMITED = "loop_limited"` (o plano pid as re-declara em `bus.py` com os mesmos literais).

Nesta task só entram: construtor, `_measure_dt`, filtro de PV, partida (u = `out_startup` ou carry), caminho `SCAN_LOST` e um `step()` que em MAN devolve `man_out` escalado. Modos/shed/kernel vêm nas Tasks 6–9 — o teste desta task não os exercita.

- [ ] **Step 1: Write the harness + failing test**

```python
# services/flow-runtime/tests/shell_harness.py
"""Helpers dos testes do BlockShell — espelha o estilo bloco/alimenta/passo de test_pid.py."""

from datetime import UTC, datetime, timedelta

from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.config import ShellCfg
from ottima_flow_runtime.blocks.shell.kernel import StubKernel

EPS = 0.01  # % do span (ADR-039 secao 7)
TS0 = datetime(2026, 1, 1, tzinfo=UTC)


class EventosFake:
    def __init__(self) -> None:
        self.eventos: list[dict] = []

    async def __call__(self, **kwargs) -> None:
        self.eventos.append(kwargs)

    def kinds(self) -> list[str]:
        return [e["kind"] for e in self.eventos]


def cfg_padrao(**over) -> ShellCfg:
    base = ShellCfg(sp_hi_lim=100.0, sp_lo_lim=0.0, max_dt=10.0)
    for chave, valor in over.items():
        setattr(base, chave, valor)
    return base


def bloco(*, kernel: StubKernel | None = None, eventos: EventosFake | None = None, **cfg_over) -> BlockShell:
    return BlockShell(
        "malha1",
        kernel=kernel or StubKernel(),
        cfg=cfg_padrao(**cfg_over),
        emit_event=eventos,
    )


def amostra(v: float | bool | None, ok: bool = True) -> PortSample:
    return PortSample(v, ok)


async def passo(b: BlockShell, segundos: float, **portas) -> dict[str, PortSample]:
    """Executa um scan na marca `segundos` do relogio de teste."""
    inputs = {nome: valor for nome, valor in portas.items()}
    return await b.step(inputs, ts=TS0 + timedelta(seconds=segundos))
```

```python
# services/flow-runtime/tests/test_shell_block_basics.py
"""BlockShell: partida, dt medido derivado de ts, SCAN_LOST (S14) e MAN basico."""

import math

from ottima_flow_runtime.blocks.shell.block import CarriedState
from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.blocks.shell.signal import Signal
from shell_harness import EPS, EventosFake, amostra, bloco, passo


async def test_partida_fria_nasce_man_com_out_startup() -> None:
    b = bloco(out_startup=30.0)
    saida = await passo(b, 0.0, **{"in": amostra(50.0)})
    assert b.mode.target is Mode.MAN
    assert b.mode.actual is Mode.MAN
    assert abs(b.u - 30.0) <= EPS
    out = saida["out"]
    assert isinstance(out, Signal) and out.ok is True and out.v is not None


async def test_out_emite_eu_via_out_scale() -> None:
    b = bloco(out_startup=50.0, out_scale_lo=0.0, out_scale_hi=400.0)
    saida = await passo(b, 0.0, **{"in": amostra(10.0)})
    assert abs(saida["out"].v - 200.0) < 0.1  # 50% de (0..400)


async def test_primeiro_scan_nao_tem_dt_e_nao_explode() -> None:
    b = bloco()
    await passo(b, 0.0, **{"in": amostra(1.0)})  # sem dt: caminho de inicializacao
    await passo(b, 1.0, **{"in": amostra(1.0)})  # dt = 1.0 medido


async def test_s14_dt_zero_e_dt_gigante_viram_scan_lost() -> None:
    eventos = EventosFake()
    b = bloco(eventos=eventos, out_startup=40.0)
    await passo(b, 0.0, **{"in": amostra(5.0)})
    await passo(b, 0.0, **{"in": amostra(5.0)})  # dt = 0
    u_antes = b.u
    await passo(b, 200.0, **{"in": amostra(5.0)})  # dt = 200 > max_dt = 10
    assert abs(b.u - u_antes) <= EPS  # OUT mantido, sem excecao
    assert "loop_alarm" in eventos.kinds()


async def test_write_out_em_man_move_a_saida() -> None:
    b = bloco()
    await passo(b, 0.0, **{"in": amostra(5.0)})
    b.write_out(77.0)
    await passo(b, 1.0, **{"in": amostra(5.0)})
    assert abs(b.u - 77.0) <= EPS


async def test_carry_preserva_u_e_aterrissa_man_se_calculava() -> None:
    carry = CarriedState(u=63.0, sp_op=42.0, man_out=63.0, was_calculating=True)
    eventos = EventosFake()
    b = bloco(eventos=eventos)
    b2 = type(b)("malha1", kernel=b.kernel, cfg=b.cfg, emit_event=eventos, carry=carry)
    await passo(b2, 0.0, **{"in": amostra(5.0)})
    assert b2.mode.target is Mode.MAN and abs(b2.u - 63.0) <= EPS
    assert "loop_alarm" in eventos.kinds()  # aterrissagem estrutural avisada (S16)


async def test_pv_filtrado_por_pv_ftime() -> None:
    b = bloco(pv_ftime=9.0)  # alpha = 1/(9+1) = 0.1 com dt=1
    await passo(b, 0.0, **{"in": amostra(0.0)})
    await passo(b, 1.0, **{"in": amostra(10.0)})
    assert b.pv is not None and 0.5 < b.pv < 1.5  # ~1.0, nao 10.0


async def test_kernel_invalido_na_partida_forca_oos() -> None:
    from ottima_flow_runtime.blocks.shell.kernel import StubKernel

    ruim = StubKernel()
    ruim.errors.append("KU_MUST_BE_POSITIVE")
    b = bloco(kernel=ruim)
    saida = await passo(b, 0.0, **{"in": amostra(5.0)})
    assert b.mode.actual is Mode.OOS
    assert saida["out"].ok is False  # OOS emite BAD: opc_write suprime
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest services/flow-runtime/tests/test_shell_block_basics.py -q`
Expected: FAIL — `ModuleNotFoundError` (block.py não existe)

- [ ] **Step 3: Write the implementation**

```python
# services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py
"""BlockShell: a maquina de modos FF que envolve um ControlKernel (ADR-039).

Nenhum `if` deste arquivo testa uma TRANSICAO especifica de modo — as transicoes emergem
da resolucao por prioridade (secao 4.3) e da tabela de saida forcada (secao 4.4). Um `if`
de transicao aqui e defeito de projeto (ADR-039 secao 4.7).
"""

import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ottima_flow_runtime.blocks.base import Block, PortSample
from ottima_flow_runtime.blocks.shell.config import ShellCfg, clamp, scale_pct, unscale_pct
from ottima_flow_runtime.blocks.shell.kernel import ControlKernel
from ottima_flow_runtime.blocks.shell.mode import CALCULATING_MODES, MODE_NAMES, Mode, ModeBlock
from ottima_flow_runtime.blocks.shell.signal import Quality, Signal, Substatus, as_signal, make_signal

KIND_LOOP_MODE_CHANGED = "loop_mode_changed"
KIND_LOOP_SHED = "loop_shed"
KIND_LOOP_MODE_REJECTED = "loop_mode_rejected"
KIND_LOOP_ALARM = "loop_alarm"
KIND_LOOP_LIMITED = "loop_limited"

EmitEvent = Callable[..., Awaitable[None]]
PublishState = Callable[[Any], Awaitable[None]]
PersistOp = Callable[[str, float], Awaitable[None]]

_SHED_DESTINO = {"shed_to_auto": Mode.AUTO, "shed_to_man": Mode.MAN}


@dataclass(frozen=True, slots=True)
class CarriedState:
    """Estado carregado de uma instancia anterior no hot-swap estrutural (ADR-039 D11)."""

    u: float
    sp_op: float
    man_out: float
    was_calculating: bool


class BlockShell(Block):
    def __init__(
        self,
        block_id: str,
        *,
        kernel: ControlKernel,
        cfg: ShellCfg,
        emit_event: EmitEvent | None = None,
        publish_state: PublishState | None = None,
        persist_op: PersistOp | None = None,
        sp_seed: float | None = None,
        man_out_seed: float | None = None,
        carry: CarriedState | None = None,
    ) -> None:
        super().__init__(block_id)
        self.kernel = kernel
        self.cfg = cfg
        self._emit_event = emit_event
        self._publish_state = publish_state
        self._persist_op = persist_op

        self.mode = ModeBlock(permitted=cfg.permitted, normal=cfg.normal)
        self.pv: float | None = None
        self.pv_ok = False
        self.diag: dict[str, float] = {}
        self._ts_prev: datetime | None = None
        self._prev_actual = Mode.OOS
        self._bias = 0.0
        self._rebase_bias = False
        self._pendentes: list[dict[str, Any]] = []

        if carry is not None:
            self.u = clamp(carry.u, cfg.out_lo_lim, cfg.out_hi_lim)
            self.sp_op = clamp(carry.sp_op, cfg.sp_lo_lim, cfg.sp_hi_lim)
            self.man_out = clamp(carry.man_out, cfg.out_lo_lim, cfg.out_hi_lim)
            if carry.was_calculating:
                self._defer_event(
                    kind=KIND_LOOP_ALARM,
                    severity="warning",
                    message="Config estrutural trocada com a malha calculante: aterrissagem em MAN",
                    payload={"block_id": block_id, "code": "structural_swap_landed_man"},
                )
        else:
            self.u = clamp(cfg.out_startup, cfg.out_lo_lim, cfg.out_hi_lim)
            self.sp_op = clamp(sp_seed if sp_seed is not None else cfg.sp_lo_lim, cfg.sp_lo_lim, cfg.sp_hi_lim)
            self.man_out = clamp(man_out_seed if man_out_seed is not None else self.u, cfg.out_lo_lim, cfg.out_hi_lim)
        self.u_int = self.u
        self.u_prev = self.u
        self.sp = self.sp_op

    # -- portas -------------------------------------------------------------
    @property
    def input_ports(self) -> tuple[str, ...]:
        return ("in", "cas_in", "rcas_in", "rout_in", "bkcal_in", "bias_in", "trk_in_d", "lo_in_d")

    @property
    def output_ports(self) -> tuple[str, ...]:
        return ("out", "bkcal_out")

    # -- escritas de operacao ------------------------------------------------
    def write_target(self, mode: Mode) -> bool:
        if not (mode & self.cfg.permitted):
            self._defer_event(
                kind=KIND_LOOP_MODE_REJECTED,
                severity="warning",
                message=f"Modo '{MODE_NAMES[mode]}' fora de PERMITTED",
                payload={"block_id": self.block_id, "requested": MODE_NAMES[mode]},
            )
            return False
        self.mode.target = mode
        return True

    def write_sp(self, value: float) -> None:
        self.sp_op = clamp(value, self.cfg.sp_lo_lim, self.cfg.sp_hi_lim)

    def write_out(self, value: float) -> None:
        self.man_out = clamp(value, self.cfg.out_lo_lim, self.cfg.out_hi_lim)

    def apply_tuning(self, cfg: ShellCfg, kernel_cfg: Any | None = None) -> None:
        """Classe de sintonia do hot-swap (ADR-039 D11): in-place, sem perder estado."""
        self.cfg = cfg
        self.mode.permitted = cfg.permitted
        self.mode.normal = cfg.normal
        if kernel_cfg is not None:
            self.kernel.cfg = kernel_cfg  # type: ignore[attr-defined]
        self._rebase_bias = True

    def carry_state(self) -> CarriedState:
        return CarriedState(
            u=self.u,
            sp_op=self.sp_op,
            man_out=self.man_out,
            was_calculating=self.mode.actual in CALCULATING_MODES,
        )

    # -- ciclo ---------------------------------------------------------------
    async def step(
        self, inputs: Mapping[str, PortSample], *, ts: datetime | None = None
    ) -> dict[str, PortSample]:
        dt = self._measure_dt(ts)
        self._update_pv(inputs.get("in"), dt)
        pv_k = self.pv if self.pv is not None else self.sp
        kernel_errors = self.kernel.validate()

        if dt is None or not (0.0 < dt <= self.cfg.max_dt):
            if dt is not None:
                self._defer_event(
                    kind=KIND_LOOP_ALARM,
                    severity="warning",
                    message=f"Scan perdido (dt={dt:.3f}s)",
                    payload={"block_id": self.block_id, "code": "scan_lost", "dt": dt},
                )
            if not kernel_errors and dt is None:
                self.mode.actual = self._resolve_mode(inputs, kernel_errors)
                m = self.mode.actual
                self._entrar_em_man_inicializa_man_out(m)
                forced = self._forced_output(m, inputs)
                if forced is not None:
                    self.u = clamp(forced, self.cfg.out_lo_lim, self.cfg.out_hi_lim)
                    self.u_int = self.u - self._bias
                    self.u_prev = self.u
            self.kernel.align(self.u, self.sp, pv_k)
            return await self._finish(inputs)

        self.mode.actual = self._resolve_mode(inputs, kernel_errors)
        m = self.mode.actual
        self.sp = self._resolve_sp(m, inputs, dt)
        bias = self._resolve_bias(inputs.get("bias_in"))
        if self._rebase_bias:
            self.u_int = self.u - bias
            self._rebase_bias = False

        self._entrar_em_man_inicializa_man_out(m)
        forced = self._forced_output(m, inputs)
        if forced is not None:
            self.u = clamp(forced, self.cfg.out_lo_lim, self.cfg.out_hi_lim)
            self.u_int = self.u - bias
            self.kernel.align(self.u, self.sp, pv_k)
            self.u_prev = self.u
            return await self._finish(inputs)

        du_dt = self.kernel.compute(self.sp, pv_k, dt)
        if not math.isfinite(du_dt):
            self._defer_event(
                kind=KIND_LOOP_ALARM,
                severity="warning",
                message="Kernel devolveu resultado invalido; OUT mantido",
                payload={"block_id": self.block_id, "code": "kernel_invalid_output"},
            )
            self.kernel.align(self.u, self.sp, pv_k)
            return await self._finish(inputs)

        u = self._rate_limit(self.u_int + du_dt * dt + bias, dt)
        self.u = clamp(u, self.cfg.out_lo_lim, self.cfg.out_hi_lim)
        self.u_int = self.u - bias
        self.u_prev = self.u
        return await self._finish(inputs)

    # -- pedacos -------------------------------------------------------------
    def _measure_dt(self, ts: datetime | None) -> float | None:
        if ts is None:
            return None
        prev, self._ts_prev = self._ts_prev, ts
        if prev is None:
            return None
        return (ts - prev).total_seconds()

    def _update_pv(self, sample: PortSample | None, dt: float | None) -> None:
        if sample is None or sample.v is None:
            self.pv_ok = False
            return
        v = float(sample.v)
        if not math.isfinite(v):
            self.pv_ok = False
            return
        self.pv_ok = as_signal(sample).is_good
        if self.pv is None or self.cfg.pv_ftime <= 0.0 or dt is None or dt <= 0.0:
            self.pv = v
            return
        a = dt / (self.cfg.pv_ftime + dt)
        self.pv = self.pv + a * (v - self.pv)

    def _resolve_mode(self, inputs: Mapping[str, PortSample], kernel_errors: list[str]) -> Mode:
        cfg = self.cfg
        target = self.mode.target
        if kernel_errors or target is Mode.OOS:
            return Mode.OOS
        efetivo = target if (target & cfg.permitted) else self.mode.normal
        bk = inputs.get("bkcal_in")
        if bk is not None and bk.v is not None and as_signal(bk).init_request:
            return Mode.IMAN
        lo = inputs.get("lo_in_d")
        if lo is not None and bool(lo.v) and lo.ok:
            return Mode.LO
        if not self.pv_ok and efetivo in CALCULATING_MODES:
            return Mode.MAN
        for modo, porta in ((Mode.CAS, "cas_in"), (Mode.RCAS, "rcas_in"), (Mode.ROUT, "rout_in")):
            if efetivo is modo:
                fonte = inputs.get(porta)
                if fonte is None or fonte.v is None or not as_signal(fonte).is_good:
                    return self._shed(efetivo)
        return efetivo

    def _shed(self, alvo: Mode) -> Mode:
        destino = _SHED_DESTINO.get(self.cfg.shed_opt, self.mode.normal)
        if self.cfg.shed_no_return and self.mode.target is alvo:
            self.mode.target = destino
        self._defer_event(
            kind=KIND_LOOP_SHED,
            severity="warning",
            message=f"Fonte remota degradada: rebaixado para '{MODE_NAMES[destino]}'",
            payload={
                "block_id": self.block_id,
                "target": MODE_NAMES[alvo],
                "actual": MODE_NAMES[destino],
                "shed_opt": self.cfg.shed_opt,
            },
        )
        return destino

    def _resolve_sp(self, m: Mode, inputs: Mapping[str, PortSample], dt: float) -> float:
        cfg = self.cfg
        remoto = {Mode.CAS: "cas_in", Mode.RCAS: "rcas_in"}.get(m)
        if remoto is not None:
            fonte = inputs.get(remoto)
            if fonte is not None and fonte.v is not None:
                return clamp(float(fonte.v), cfg.sp_lo_lim, cfg.sp_hi_lim)
            return self.sp
        if m is Mode.AUTO:
            alvo = clamp(self.sp_op, cfg.sp_lo_lim, cfg.sp_hi_lim)
            subida = alvo - self.sp
            if cfg.sp_rate_up is not None and subida > cfg.sp_rate_up * dt:
                return self.sp + cfg.sp_rate_up * dt
            if cfg.sp_rate_dn is not None and -subida > cfg.sp_rate_dn * dt:
                return self.sp - cfg.sp_rate_dn * dt
            return alvo
        if cfg.sp_pv_track_in_man and self.pv is not None:
            rastreado = clamp(self.pv, cfg.sp_lo_lim, cfg.sp_hi_lim)
            self.sp_op = rastreado
            return rastreado
        return self.sp

    def _entrar_em_man_inicializa_man_out(self, m: Mode) -> None:
        if m is Mode.MAN and self._prev_actual is not Mode.MAN:
            self.man_out = self.u  # transicao para MAN nunca salta (ADR-039 secao 4.4)

    def _forced_output(self, m: Mode, inputs: Mapping[str, PortSample]) -> float | None:
        cfg = self.cfg
        trk = inputs.get("trk_in_d")
        rastreando = trk is not None and bool(trk.v) and trk.ok
        if m is Mode.OOS:
            return self.u
        if m is Mode.IMAN:
            bk = inputs.get("bkcal_in")
            if bk is not None and bk.v is not None:
                return unscale_pct(float(bk.v), cfg.out_scale_lo, cfg.out_scale_hi)
            return self.u
        if m is Mode.LO:
            return cfg.lo_val
        if m is Mode.MAN:
            if rastreando and cfg.track_in_manual:
                return cfg.trk_val
            return self.man_out
        if m is Mode.ROUT:
            ro = inputs.get("rout_in")
            if ro is not None and ro.v is not None:
                return unscale_pct(float(ro.v), cfg.out_scale_lo, cfg.out_scale_hi)
            return self.u
        if rastreando and cfg.track_enable:
            return cfg.trk_val
        return None

    def _resolve_bias(self, sample: PortSample | None) -> float:
        cfg = self.cfg
        if not cfg.ff_enable or sample is None or sample.v is None:
            return self._bias
        sinal = as_signal(sample)
        if not sinal.is_good or not math.isfinite(float(sinal.v)):
            return self._bias  # BAD: mantem o ultimo bom (ADR-039 D10)
        pct = unscale_pct(float(sinal.v), cfg.ff_scale_lo, cfg.ff_scale_hi)
        self._bias = cfg.ff_gain * pct
        return self._bias

    def _rate_limit(self, u: float, dt: float) -> float:
        cfg = self.cfg
        delta = u - self.u_prev
        if cfg.out_rate_up is not None and delta > cfg.out_rate_up * dt:
            return self.u_prev + cfg.out_rate_up * dt
        if cfg.out_rate_dn is not None and -delta > cfg.out_rate_dn * dt:
            return self.u_prev - cfg.out_rate_dn * dt
        return u

    # -- emissao -------------------------------------------------------------
    async def _finish(self, inputs: Mapping[str, PortSample]) -> dict[str, PortSample]:
        m = self.mode.actual
        if m is not self._prev_actual:
            self._defer_event(
                kind=KIND_LOOP_MODE_CHANGED,
                severity="info",
                message=f"Modo: {MODE_NAMES[self._prev_actual]} -> {MODE_NAMES[m]}",
                payload={
                    "block_id": self.block_id,
                    "from": MODE_NAMES[self._prev_actual],
                    "to": MODE_NAMES[m],
                },
            )
            self._prev_actual = m
        await self._flush_events()
        return self._emit()

    def _emit(self) -> dict[str, PortSample]:
        cfg, m = self.cfg, self.mode.actual
        hi = self.u >= cfg.out_hi_lim
        lo = self.u <= cfg.out_lo_lim
        out = make_signal(
            scale_pct(self.u, cfg.out_scale_lo, cfg.out_scale_hi),
            Quality.BAD if m is Mode.OOS else Quality.GOOD,
            substatus=Substatus.LOCAL_OVERRIDE if m is Mode.LO else Substatus.NON_SPECIFIC,
            hi_limited=hi,
            lo_limited=lo,
        )
        d = cfg.direct_acting
        valor_bkcal = self.pv if (cfg.use_pv_for_bkcal and self.pv is not None) else self.sp
        bkcal = make_signal(
            valor_bkcal,
            Quality.GOOD,
            substatus=Substatus.NON_SPECIFIC if m is Mode.CAS else Substatus.INIT_REQUEST,
            hi_limited=lo if d else hi,
            lo_limited=hi if d else lo,
        )
        return {"out": out, "bkcal_out": bkcal}

    def _defer_event(self, **kwargs: Any) -> None:
        self._pendentes.append(kwargs)

    async def _flush_events(self) -> None:
        pendentes, self._pendentes = self._pendentes, []
        if self._emit_event is None:
            return
        for evento in pendentes:
            await self._emit_event(origin=f"bloco:{self.block_id}", **evento)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest services/flow-runtime/tests/test_shell_block_basics.py services/flow-runtime/tests/test_shell_signal.py services/flow-runtime/tests/test_shell_mode.py -q`
Expected: PASS. Se `test_kernel_invalido_na_partida_forca_oos` falhar, confira que `_resolve_mode` roda ANTES do caminho SCAN_LOST retornar no primeiro scan (o código acima resolve modo no ramo `dt is None`).

- [ ] **Step 5: Commit**

```bash
uv run ruff check services/flow-runtime && uv run ruff format services/flow-runtime
git add services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py services/flow-runtime/tests/shell_harness.py services/flow-runtime/tests/test_shell_block_basics.py
git commit -m "feat(shell): BlockShell com dt medido, partida MAN e SCAN_LOST (ADR-039 D7, S14)"
```

---

### Task 6: Rebaixamento de modo — shed, no-return, PV BAD, PERMITTED

**Files:**
- Modify: `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py` (só se algum teste apontar defeito — a lógica já foi escrita na Task 5)
- Test: `services/flow-runtime/tests/test_shell_modes.py`

**Interfaces:**
- Consumes: `BlockShell.write_target`, `_resolve_mode` (via `step`), `EventosFake`, `make_signal`.
- Produces: cobertura de S7, S8, S10, S17 e das regras 2/5/6/7 da §4.3 do ADR-039.

- [ ] **Step 1: Write the failing tests**

```python
# services/flow-runtime/tests/test_shell_modes.py
"""Rebaixamento de modo (ADR-039 secao 4.3): shed, retorno automatico, no-return."""

from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.blocks.shell.signal import Quality, make_signal
from shell_harness import EPS, EventosFake, amostra, bloco, passo


def _cfg_cascata() -> dict:
    return {"permitted": Mode.OOS | Mode.MAN | Mode.AUTO | Mode.CAS | Mode.RCAS}


async def _ate_auto(b, t0=0.0):
    await passo(b, t0, **{"in": amostra(50.0)})
    b.write_target(Mode.AUTO)
    await passo(b, t0 + 1.0, **{"in": amostra(50.0)})


async def test_s7_cas_bad_rebaixa_em_1_scan_e_retorna_sozinho() -> None:
    eventos = EventosFake()
    b = bloco(eventos=eventos, **_cfg_cascata())
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.CAS)
    await passo(b, 1.0, **{"in": amostra(50.0), "cas_in": make_signal(60.0, Quality.GOOD)})
    assert b.mode.actual is Mode.CAS

    u_antes = b.u
    await passo(b, 2.0, **{"in": amostra(50.0), "cas_in": make_signal(60.0, Quality.BAD)})
    assert b.mode.actual is Mode.AUTO  # shed_to_auto default
    assert abs(b.u - u_antes) <= 1.0  # continuo (kernel P zero-erro; sem salto)
    assert "loop_shed" in eventos.kinds()

    await passo(b, 3.0, **{"in": amostra(50.0), "cas_in": make_signal(60.0, Quality.GOOD)})
    assert b.mode.actual is Mode.CAS  # retorno automatico: TARGET intocado


async def test_s17_shed_no_return_reescreve_target() -> None:
    b = bloco(shed_no_return=True, **_cfg_cascata())
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.CAS)
    await passo(b, 1.0, **{"in": amostra(50.0), "cas_in": make_signal(60.0, Quality.GOOD)})
    await passo(b, 2.0, **{"in": amostra(50.0), "cas_in": make_signal(60.0, Quality.BAD)})
    assert b.mode.target is Mode.AUTO  # TARGET reescrito
    await passo(b, 3.0, **{"in": amostra(50.0), "cas_in": make_signal(60.0, Quality.GOOD)})
    assert b.mode.actual is Mode.AUTO  # NAO volta a CAS sozinho


async def test_s8_rcas_bad_rebaixa() -> None:
    b = bloco(**_cfg_cascata())
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.RCAS)
    await passo(b, 1.0, **{"in": amostra(50.0), "rcas_in": make_signal(55.0, Quality.GOOD)})
    assert b.mode.actual is Mode.RCAS
    await passo(b, 2.0, **{"in": amostra(50.0), "rcas_in": make_signal(55.0, Quality.BAD)})
    assert b.mode.actual is Mode.AUTO


async def test_s10_pv_bad_forca_man_e_retomada_bumpless() -> None:
    b = bloco()
    await _ate_auto(b)
    u_antes = b.u
    await passo(b, 2.0, **{"in": amostra(50.0, ok=False)})
    assert b.mode.actual is Mode.MAN
    assert abs(b.u - u_antes) <= EPS  # OUT mantido
    await passo(b, 3.0, **{"in": amostra(50.0)})
    assert b.mode.actual is Mode.AUTO
    assert abs(b.u - u_antes) <= EPS  # retomada sem degrau (erro zero)


async def test_regra2_target_fora_de_permitted_cai_no_normal() -> None:
    b = bloco()
    await passo(b, 0.0, **{"in": amostra(50.0)})
    assert b.write_target(Mode.CAS) is False  # CAS nao esta em permitted default
    b.mode.target = Mode.CAS  # simula target invalido vindo de config antiga
    await passo(b, 1.0, **{"in": amostra(50.0)})
    assert b.mode.actual is b.mode.normal


async def test_lo_tem_prioridade_sobre_man() -> None:
    b = bloco(lo_val=15.0)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    await passo(b, 1.0, **{"in": amostra(50.0), "lo_in_d": amostra(True)})
    assert b.mode.actual is Mode.LO
    assert abs(b.u - 15.0) <= EPS
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest services/flow-runtime/tests/test_shell_modes.py -q`
Expected: PASS se a Task 5 implementou a §4.3 corretamente; qualquer FAIL aqui é defeito na ordem das regras de `_resolve_mode` — corrigir seguindo a tabela do ADR-039 §4.3 (a ordem é: kernel/OOS → PERMITTED→NORMAL → IMAN → LO → PV BAD → shed CAS/RCAS/ROUT).

- [ ] **Step 3: Commit**

```bash
git add services/flow-runtime/tests/test_shell_modes.py services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py
git commit -m "test(shell): rebaixamento de modo, shed com retorno automatico e no-return (S7/S8/S10/S17)"
```

---

### Task 7: Bumpless, tracking, anti-windup e NaN — S1–S4, S9, S12

**Files:**
- Test: `services/flow-runtime/tests/test_shell_bumpless.py`

**Interfaces:**
- Consumes: tudo das Tasks 1–6.

- [ ] **Step 1: Write the failing tests**

```python
# services/flow-runtime/tests/test_shell_bumpless.py
"""S1-S4, S9, S12: bumpless, tracking, anti-windup, kernel NaN (ADR-039 secao 7)."""

import math

from ottima_flow_runtime.blocks.shell.kernel import StubKernel
from ottima_flow_runtime.blocks.shell.mode import Mode
from shell_harness import EPS, EventosFake, amostra, bloco, passo


async def test_s1_man_para_auto_sem_degrau_com_pv_diferente_de_sp() -> None:
    k = StubKernel(gain=0.0)  # kernel quieto: qualquer degrau viria do shell
    b = bloco(kernel=k, out_startup=40.0)
    await passo(b, 0.0, **{"in": amostra(30.0)})
    b.write_sp(70.0)  # SP != PV
    b.write_target(Mode.AUTO)
    await passo(b, 1.0, **{"in": amostra(30.0)})
    assert b.mode.actual is Mode.AUTO
    assert abs(b.u - 40.0) <= EPS  # primeiro scan em Auto: sem salto


async def test_s2_auto_man_auto_120s_sem_degrau() -> None:
    k = StubKernel(gain=0.1)
    b = bloco(kernel=k, out_startup=40.0, sp_pv_track_in_man=False)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_sp(50.0)
    b.write_target(Mode.AUTO)
    t = 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    u_auto = b.u
    b.write_target(Mode.MAN)
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    assert abs(b.u - u_auto) <= EPS  # entrada em MAN herda u
    for _ in range(120):
        t += 1.0
        await passo(b, t, **{"in": amostra(50.0)})
    b.write_target(Mode.AUTO)
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    assert abs(b.u - u_auto) <= EPS


async def test_s3_tracking_engata_e_solta_sem_degrau() -> None:
    b = bloco(track_enable=True, trk_val=80.0, out_startup=20.0)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_sp(50.0)
    b.write_target(Mode.AUTO)
    await passo(b, 1.0, **{"in": amostra(50.0)})
    await passo(b, 2.0, **{"in": amostra(50.0), "trk_in_d": amostra(True)})
    assert abs(b.u - 80.0) <= EPS  # OUT == TRK_VAL durante
    await passo(b, 3.0, **{"in": amostra(50.0), "trk_in_d": amostra(False)})
    assert abs(b.u - 80.0) <= EPS  # solta a partir de 80, sem salto


async def test_s4_anti_windup_sai_da_saturacao_em_1_scan() -> None:
    k = StubKernel()
    b = bloco(kernel=k, out_startup=50.0)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.AUTO)
    k.rate = 50.0  # empurra forte para cima
    t = 0.0
    for _ in range(20):
        t += 1.0
        await passo(b, t, **{"in": amostra(50.0)})
    assert b.u == 100.0  # saturado no teto
    k.rate = -10.0  # inverte
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    assert b.u < 100.0 - EPS  # deixou o limite em <= 1 scan: integrador nao acumulou


async def test_s9_local_override_retoma_de_lo_val() -> None:
    b = bloco(lo_val=10.0, out_startup=60.0)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    await passo(b, 1.0, **{"in": amostra(50.0), "lo_in_d": amostra(True)})
    assert abs(b.u - 10.0) <= EPS
    await passo(b, 2.0, **{"in": amostra(50.0), "lo_in_d": amostra(False)})
    assert abs(b.u - 10.0) <= EPS  # retoma DE lo_val, sem degrau


async def test_s12_kernel_nan_segura_out_e_alarma() -> None:
    eventos = EventosFake()
    k = StubKernel(gain=1.0)
    b = bloco(kernel=k, eventos=eventos, out_startup=45.0)
    await passo(b, 0.0, **{"in": amostra(40.0)})
    b.write_sp(40.0)
    b.write_target(Mode.AUTO)
    await passo(b, 1.0, **{"in": amostra(40.0)})
    modo_antes, u_antes = b.mode.actual, b.u
    k.rate = math.nan
    await passo(b, 2.0, **{"in": amostra(40.0)})
    assert abs(b.u - u_antes) <= EPS
    assert b.mode.actual is modo_antes  # ACTUAL inalterado
    assert "loop_alarm" in eventos.kinds()
    assert len(k.align_calls) > 0  # kernel realinhado no scan invalido


async def test_s15_apply_tuning_em_auto_sem_degrau() -> None:
    from shell_harness import cfg_padrao

    k = StubKernel(gain=0.5)
    b = bloco(kernel=k, out_startup=35.0)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_sp(50.0)
    b.write_target(Mode.AUTO)
    await passo(b, 1.0, **{"in": amostra(50.0)})
    u_antes = b.u
    nova = cfg_padrao(out_rate_up=5.0)  # classe de sintonia
    b.apply_tuning(nova)
    await passo(b, 2.0, **{"in": amostra(50.0)})
    assert abs(b.u - u_antes) <= EPS
    assert b.mode.actual is Mode.AUTO  # modo preservado
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest services/flow-runtime/tests/test_shell_bumpless.py -q`
Expected: PASS. FAIL em S4 = o clamp não está retro-alimentando `u_int` (rever `self.u_int = self.u - bias` no passo de integração). FAIL em S2 = `man_out` não está herdando `u` na entrada em MAN (`_entrar_em_man_inicializa_man_out`).

- [ ] **Step 3: Commit**

```bash
git add services/flow-runtime/tests/test_shell_bumpless.py
git commit -m "test(shell): bumpless, tracking, anti-windup, NaN e apply_tuning (S1-S4, S9, S12, S15)"
```

---

### Task 8: Cascata — S5/S6, bits de limitação, IMAN

**Files:**
- Test: `services/flow-runtime/tests/test_shell_cascade.py`

**Interfaces:**
- Consumes: dois `BlockShell` ligados manualmente no teste (primário LIC % → EU via `out_scale`; secundário FIC). O harness do teste replica o wiring do scheduler: `FIC.cas_in = LIC.out (mesmo scan)`, `LIC.bkcal_in = FIC.bkcal_out (scan anterior — atraso de 1 scan, ADR-039 D6)`.

- [ ] **Step 1: Write the failing tests**

```python
# services/flow-runtime/tests/test_shell_cascade.py
"""S5/S6 + inversao de bits sob acao direta (ADR-039 secoes 4.3, 4.6, 4.7)."""

from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.kernel import StubKernel
from ottima_flow_runtime.blocks.shell.mode import Mode
from shell_harness import EPS, amostra, cfg_padrao, passo


def _par_cascata() -> tuple[BlockShell, BlockShell]:
    lic_cfg = cfg_padrao(out_scale_lo=0.0, out_scale_hi=400.0)  # OUT do LIC em m3/h
    lic_cfg.permitted = Mode.OOS | Mode.MAN | Mode.AUTO
    fic_cfg = cfg_padrao(sp_hi_lim=400.0, sp_lo_lim=0.0)
    fic_cfg.permitted = Mode.OOS | Mode.MAN | Mode.AUTO | Mode.CAS
    lic = BlockShell("lic", kernel=StubKernel(gain=0.2), cfg=lic_cfg)
    fic = BlockShell("fic", kernel=StubKernel(gain=0.2), cfg=fic_cfg)
    return lic, fic


async def _scan(lic, fic, t, *, lic_pv, fic_pv, bkcal_anterior):
    saida_lic = await passo(lic, t, **{"in": amostra(lic_pv), "bkcal_in": bkcal_anterior})
    saida_fic = await passo(fic, t, **{"in": amostra(fic_pv), "cas_in": saida_lic["out"]})
    return saida_lic, saida_fic, saida_fic["bkcal_out"]


async def test_s5_s6_fic_em_man_leva_lic_a_iman_e_volta_sem_degrau() -> None:
    lic, fic = _par_cascata()
    bkcal = PortSample(None, False)
    await _scan(lic, fic, 0.0, lic_pv=50.0, fic_pv=200.0, bkcal_anterior=bkcal)

    lic.write_sp(50.0)
    lic.write_target(Mode.AUTO)
    fic.write_target(Mode.CAS)
    for t in (1.0, 2.0, 3.0):
        _, _, bkcal = await _scan(lic, fic, t, lic_pv=50.0, fic_pv=200.0, bkcal_anterior=bkcal)
    assert fic.mode.actual is Mode.CAS
    assert lic.mode.actual is Mode.AUTO

    # S5: FIC vai a MAN -> bkcal_out emite IR -> LIC entra em IMAN em <= 2 scans
    fic.write_target(Mode.MAN)
    for t in (4.0, 5.0):
        _, _, bkcal = await _scan(lic, fic, t, lic_pv=50.0, fic_pv=200.0, bkcal_anterior=bkcal)
    assert lic.mode.actual is Mode.IMAN
    # LIC.out acompanha o SP de trabalho do FIC (unscale do bkcal, ADR-039 secao 4.4)
    assert abs(lic.u - (fic.sp / 400.0 * 100.0)) <= 1.0

    # S6: FIC volta a CAS -> LIC volta a AUTO... nao: LIC target=AUTO, entao IMAN cessa
    sp_fic_antes = fic.sp
    fic.write_target(Mode.CAS)
    for t in (6.0, 7.0, 8.0):
        _, _, bkcal = await _scan(lic, fic, t, lic_pv=50.0, fic_pv=200.0, bkcal_anterior=bkcal)
    assert lic.mode.actual is Mode.AUTO
    assert abs(fic.sp - sp_fic_antes) <= 400.0 * (EPS / 100.0) + 0.5  # sem degrau no SP do FIC


async def test_bits_de_limitacao_invertem_sob_acao_direta() -> None:
    cfg = cfg_padrao(direct_acting=True, out_startup=100.0)
    b = BlockShell("b", kernel=StubKernel(), cfg=cfg)
    saida = await passo(b, 0.0, **{"in": amostra(50.0)})
    bkcal = saida["bkcal_out"]
    assert bkcal.lo_limited is True and bkcal.hi_limited is False  # saturado no teto, invertido
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest services/flow-runtime/tests/test_shell_cascade.py -q`
Expected: PASS. FAIL no IMAN = `bkcal_out` do FIC não está emitindo `INIT_REQUEST` fora de CAS (rever `_emit`).

- [ ] **Step 3: Commit**

```bash
git add services/flow-runtime/tests/test_shell_cascade.py
git commit -m "test(shell): cascata IMAN/retorno bumpless e bits invertidos (S5/S6, P11 no shell)"
```

---

### Task 9: Jitter e malha fechada — S11

**Files:**
- Test: `services/flow-runtime/tests/test_shell_jitter.py`

**Interfaces:**
- Consumes: `StubKernel(gain=...)` fechando malha contra um processo de 1ª ordem simulado no próprio teste.

- [ ] **Step 1: Write the failing test**

```python
# services/flow-runtime/tests/test_shell_jitter.py
"""S11: jitter de dt de +-30% nao muda o regime (ADR-039 D7)."""

import random

from ottima_flow_runtime.blocks.shell.kernel import StubKernel
from ottima_flow_runtime.blocks.shell.mode import Mode
from shell_harness import amostra, bloco, passo


async def _regime(jitter: bool) -> float:
    """Malha fechada: processo pv' = (u - pv)/tau, kernel P incremental."""
    rng = random.Random(42)
    b = bloco(kernel=StubKernel(gain=1.5), out_startup=0.0)
    pv, tau, t = 0.0, 5.0, 0.0
    await passo(b, t, **{"in": amostra(pv)})
    b.write_sp(60.0)
    b.write_target(Mode.AUTO)
    ultimo_dt = 1.0
    for _ in range(300):
        dt = 1.0 + (rng.uniform(-0.3, 0.3) if jitter else 0.0)
        t += dt
        pv += (b.u - pv) * (ultimo_dt / tau)
        await passo(b, t, **{"in": amostra(pv)})
        ultimo_dt = dt
    return b.u


async def test_s11_regime_identico_com_e_sem_jitter() -> None:
    sem = await _regime(jitter=False)
    com = await _regime(jitter=True)
    assert abs(sem - com) <= 0.5  # 0.5% do span (ADR-039 secao 7)
```

- [ ] **Step 2: Run test**

Run: `uv run pytest services/flow-runtime/tests/test_shell_jitter.py -q`
Expected: PASS — a forma incremental integra `du_dt * dt` com o dt medido; se falhar, algum caminho está usando dt nominal.

- [ ] **Step 3: Commit**

```bash
git add services/flow-runtime/tests/test_shell_jitter.py
git commit -m "test(shell): regime invariante a jitter de dt (S11)"
```

---

### Task 10: Hot-swap estrutural no nível do shell — S16 + suíte completa

**Files:**
- Test: `services/flow-runtime/tests/test_shell_hotswap.py`

**Interfaces:**
- Consumes: `BlockShell.carry_state() -> CarriedState`, construtor com `carry=`.
- Produces: contrato que o plano `pid-loop` usa em `build_definition` (troca estrutural = nova instância com `carry=antigo.carry_state()`).

- [ ] **Step 1: Write the failing test**

```python
# services/flow-runtime/tests/test_shell_hotswap.py
"""S16: troca estrutural com a malha calculante aterrissa em MAN com u mantido."""

from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.kernel import StubKernel
from ottima_flow_runtime.blocks.shell.mode import Mode
from shell_harness import EPS, EventosFake, amostra, bloco, cfg_padrao, passo


async def test_s16_troca_estrutural_em_auto_aterrissa_man() -> None:
    velho = bloco(kernel=StubKernel(gain=0.3), out_startup=25.0)
    await passo(velho, 0.0, **{"in": amostra(50.0)})
    velho.write_sp(55.0)
    velho.write_target(Mode.AUTO)
    await passo(velho, 1.0, **{"in": amostra(50.0)})
    assert velho.mode.actual is Mode.AUTO

    eventos = EventosFake()
    carry = velho.carry_state()
    assert carry.was_calculating is True
    novo = BlockShell(
        "malha1",
        kernel=StubKernel(),
        cfg=cfg_padrao(out_scale_hi=400.0),  # mudanca estrutural
        emit_event=eventos,
        carry=carry,
    )
    await passo(novo, 2.0, **{"in": amostra(50.0)})
    assert novo.mode.actual is Mode.MAN
    assert abs(novo.u - velho.u) <= EPS  # u carregado
    assert "loop_alarm" in eventos.kinds()


async def test_carry_de_bloco_em_man_nao_alarma() -> None:
    velho = bloco()
    await passo(velho, 0.0, **{"in": amostra(50.0)})  # nasce MAN
    carry = velho.carry_state()
    assert carry.was_calculating is False
    eventos = EventosFake()
    novo = BlockShell("malha1", kernel=StubKernel(), cfg=cfg_padrao(), emit_event=eventos, carry=carry)
    await passo(novo, 1.0, **{"in": amostra(50.0)})
    assert eventos.kinds().count("loop_alarm") == 0
```

- [ ] **Step 2: Run the full shell suite**

Run: `uv run pytest services/flow-runtime/tests/test_shell_signal.py services/flow-runtime/tests/test_shell_mode.py services/flow-runtime/tests/test_shell_kernel.py services/flow-runtime/tests/test_shell_config.py services/flow-runtime/tests/test_shell_block_basics.py services/flow-runtime/tests/test_shell_modes.py services/flow-runtime/tests/test_shell_bumpless.py services/flow-runtime/tests/test_shell_cascade.py services/flow-runtime/tests/test_shell_jitter.py services/flow-runtime/tests/test_shell_hotswap.py -q`
Expected: PASS — S1–S17 cobertos (S13 adiado por ADR-039 §9: exige `CONTROL_SELECTOR`, fora deste plano).

- [ ] **Step 3: Verify existing tests still pass (o plano não tocou nada existente)**

Run: `uv run pytest services/flow-runtime/tests -q`
Expected: PASS — inclusive `test_pid.py`/`test_fuzzy*.py` intactos.

- [ ] **Step 4: Lint and final commit**

```bash
uv run ruff check services/flow-runtime && uv run ruff format --check services/flow-runtime
git add services/flow-runtime/tests/test_shell_hotswap.py
git commit -m "test(shell): hot-swap estrutural com aterrissagem em MAN (S16) — S1-S17 verdes"
```

---

## Cobertura dos testes de aceitação (ADR-039 §7)

| S | Onde |
|---|---|
| S1, S2, S3, S4, S9, S12, S15 | `test_shell_bumpless.py` |
| S5, S6 (+inversão de bits) | `test_shell_cascade.py` |
| S7, S8, S10, S17 | `test_shell_modes.py` |
| S11 | `test_shell_jitter.py` |
| S14 | `test_shell_block_basics.py` |
| S16 | `test_shell_hotswap.py` |
| S13 | adiado (ADR-039 §9, `CONTROL_SELECTOR`) |

**Próximo plano:** `docs/superpowers/plans/2026-08-31-pid-loop.md` — registra o tipo `pid_loop` de ponta a ponta (kernel, parse/validate, definition/hot-swap, migrations, bus/ws/recorder, API, frontend).
