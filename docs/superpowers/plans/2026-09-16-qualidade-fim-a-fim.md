# Qualidade Fim-a-Fim (Signal como contrato de porta) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o booleano `ok` das portas por `Signal` (quality tri-state Fieldbus + substatus + limites) em todo o sistema — blocos, `flow.status`, `flow.exchange`, WS, frontend — preservando byte-a-byte o comportamento de atuação e a persistência.

**Architecture:** `Quality`/`Substatus` (IntEnum, BAD=0/UNCERTAIN=1/GOOD=2) nascem em `ottima-core`; o dataclass `Signal` substitui `PortSample` em `blocks/base.py` com `ok` como propriedade derivada (`quality is GOOD` — emenda ADR-039 §4.1), o que deixa TODOS os leitores de `.ok` intocados; só construtores mudam. `opc_read` é o único tradutor OpcValue→Quality; `_historized_value` mapeia não-GOOD→2 (persistência idêntica). Payloads `PortValue`/`ExchangeValue` trocam `ok` pelos campos do Signal.

**Tech Stack:** Python 3.12 / Pydantic v2 / dataclasses / pytest · TypeScript strict / React (contratos gerados via `generate:contracts`).

**Spec:** `docs/specs/SPEC_QUALIDADE_FIM_A_FIM.md` (D1–D9 — o plano argumenta a partir dela; leia antes).

## Global Constraints

- ADRs são normativos; este plano MATERIALIZA ADR-043 + emendas listadas na spec §8 — nenhuma outra decisão pode ser relitigada.
- Comportamento de atuação CONGELADO: nenhuma asserção comportamental de teste existente muda (asserções de payload/tipo mudam). A aceitação MPC↔TFS (RNF-09) passa sem edição.
- Persistência byte-idêntica: recorder, `samples`, RF-804/ADR-037 intocados. Nenhuma DDL.
- `opc.values.*`/`calc.values`/`flow.values` (payload `OpcValue`) intocados. calc-worker intocado.
- Polaridade Fieldbus em porta: `Quality` BAD=0 / UNCERTAIN=1 / GOOD=2 (NUNCA a polaridade do OpcValue 0=good).
- Bloco não-shell emite `substatus=NON_SPECIFIC`, `hi_limited=lo_limited=False` (D9); blocos de barramento transportam verbatim.
- Identificadores em inglês, strings de UI em pt-BR, commits Conventional em pt-BR, type hints obrigatórios, sem dependência nova.
- Nunca bloquear o event loop; nenhum canal de barramento novo.
- Rodar SÓ os testes do arquivo/serviço tocado em cada task; a suíte completa e os gates ficam na Task 7.

---

### Task 1: Enums `Quality`/`Substatus` em ottima-core

**Files:**
- Create: `packages/ottima-core/src/ottima_core/signal.py`
- Test: `packages/ottima-core/tests/test_signal.py`

**Interfaces:**
- Produces: `ottima_core.signal.Quality` (IntEnum: BAD=0, UNCERTAIN=1, GOOD=2), `ottima_core.signal.Substatus` (IntEnum: NON_SPECIFIC=0, INIT_REQUEST=1, NOT_INVITED=2, LOCAL_OVERRIDE=3, SENSOR_FAILURE=4, CONFIG_ERROR=5, DEVICE_FAILURE=6). Tasks 2–4 importam daqui.

- [ ] **Step 1: Write the failing test**

```python
# packages/ottima-core/tests/test_signal.py
"""Vocabulário de qualidade de porta (ADR-043; valores herdados do ADR-039)."""

from ottima_core.signal import Quality, Substatus


def test_polaridade_fieldbus_e_ordem_de_pior():
    # min() = pior: BAD < UNCERTAIN < GOOD — é a regra D6 da spec.
    assert (Quality.BAD, Quality.UNCERTAIN, Quality.GOOD) == (0, 1, 2)
    assert min(Quality.GOOD, Quality.UNCERTAIN) is Quality.UNCERTAIN
    assert min(Quality.UNCERTAIN, Quality.BAD) is Quality.BAD


def test_substatus_codigos_do_adr_039():
    assert [s.value for s in Substatus] == [0, 1, 2, 3, 4, 5, 6]
    assert Substatus.NON_SPECIFIC == 0
    assert Substatus.INIT_REQUEST == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/ottima-core/tests/test_signal.py -v`
Expected: FAIL — `ModuleNotFoundError: ottima_core.signal`

- [ ] **Step 3: Write minimal implementation**

```python
# packages/ottima-core/src/ottima_core/signal.py
"""Vocabulário de qualidade de porta (ADR-043 D1; valores do ADR-039 §4.1).

Polaridade Fieldbus: BAD=0 < UNCERTAIN=1 < GOOD=2 — `min()` é "pior de".
NUNCA confundir com `OpcValue.quality` (0=good/1=uncertain/2=bad, spec F1 §3.2):
a tradução entre os dois vocabulários acontece SÓ no bloco OPC-Read e em
`scheduler._historized_value` (ADR-043 §4).
"""

from enum import IntEnum


class Quality(IntEnum):
    BAD = 0
    UNCERTAIN = 1
    GOOD = 2


class Substatus(IntEnum):
    NON_SPECIFIC = 0
    INIT_REQUEST = 1  # IR: o bloco a jusante não está aceitando cascata
    NOT_INVITED = 2  # reservado ao CONTROL_SELECTOR (ADR-039 §9)
    LOCAL_OVERRIDE = 3
    SENSOR_FAILURE = 4
    CONFIG_ERROR = 5
    DEVICE_FAILURE = 6
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/ottima-core/tests/test_signal.py -v`
Expected: PASS (2 testes)

- [ ] **Step 5: Commit**

```bash
git add packages/ottima-core/src/ottima_core/signal.py packages/ottima-core/tests/test_signal.py
git commit -m "feat(core): enums Quality/Substatus do contrato de porta (ADR-043)"
```

---

### Task 2: `Signal` substitui `PortSample` — fusão + migração mecânica dos construtores

A task central. `ok` vira propriedade derivada, então **leitores de `.ok` não mudam**
(`mpc.py:484,498,503,584`, `opc_write.py:101`, `pid.py:127`, `fuzzy.py:148`, `tfs.py:209`,
`script.py:98`, `shell/block.py:316,373`). Mudam: a classe, os CONSTRUTORES (mapa abaixo) e
os helpers do shell (`as_signal`/`make_signal` morrem — emenda ADR-039 §4.1 embutida em `ok`).

**Files:**
- Modify: `services/flow-runtime/src/ottima_flow_runtime/blocks/base.py` (classe + `null_outputs`)
- Delete: `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/signal.py`
- Modify: `services/flow-runtime/src/ottima_flow_runtime/blocks/shell/block.py`, `shell/__init__.py` (e qualquer outro import de `shell.signal` — descubra com grep)
- Modify: `services/flow-runtime/src/ottima_flow_runtime/scheduler.py:53,367`
- Modify (construtores): `blocks/opc_read.py:46,50` · `constant.py:29` · `scaler.py:62` · `first_order.py:57` · `kalman.py:70` · `integrator.py:76,84,91,96,99` · `tfs.py:197-210` · `script.py:98-101` · `fuzzy.py:147-148,173,187,191` · `pid.py:126-128,157,161` · `mpc.py:462,792,827,840-841` · `bus_subscribe.py:52,60`
- Test: suíte do flow-runtime (atualizar TODO teste que constrói `PortSample(v, ok)` — descubra com `grep -l "PortSample" services/flow-runtime/tests`)

**Interfaces:**
- Consumes: `ottima_core.signal.Quality`, `Substatus` (Task 1)
- Produces: `ottima_flow_runtime.blocks.base.Signal` — dataclass frozen/slots com campos `v: float | bool | None`, `quality: Quality = Quality.BAD`, `substatus: Substatus = Substatus.NON_SPECIFIC`, `hi_limited: bool = False`, `lo_limited: bool = False`; propriedades `ok` (= `quality is Quality.GOOD`) e `init_request` (= `substatus is Substatus.INIT_REQUEST`). O nome `PortSample` DEIXA DE EXISTIR. Tasks 3–4 dependem.

- [ ] **Step 1: Write the failing test (contrato do Signal)**

```python
# services/flow-runtime/tests/test_signal_contract.py
"""Signal como contrato de porta (ADR-043 D1/D3/D5)."""

from ottima_core.signal import Quality, Substatus
from ottima_flow_runtime.blocks.base import Signal, has_cold_input, null_outputs


def test_ok_derivado_uncertain_invalida_atuacao():
    # Emenda ADR-039 §4.1 (ADR-043 D3): só GOOD é ok — UNCERTAIN invalida como BAD.
    assert Signal(1.0, Quality.GOOD).ok is True
    assert Signal(1.0, Quality.UNCERTAIN).ok is False
    assert Signal(1.0, Quality.BAD).ok is False


def test_defaults_sao_bad_non_specific_sem_limites():
    s = Signal(None)
    assert s.quality is Quality.BAD
    assert s.substatus is Substatus.NON_SPECIFIC
    assert (s.hi_limited, s.lo_limited) == (False, False)
    assert s.init_request is False


def test_cold_start_continua_por_v_none():
    assert has_cold_input({"in": Signal(None)}) is True
    assert has_cold_input({"in": Signal(0.0, Quality.BAD)}) is False


def test_null_outputs_nulos_e_bad():
    outs = null_outputs(("a", "b"))
    assert all(s.v is None and s.quality is Quality.BAD for s in outs.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest services/flow-runtime/tests/test_signal_contract.py -v`
Expected: FAIL — `ImportError: cannot import name 'Signal' from 'ottima_flow_runtime.blocks.base'`

- [ ] **Step 3: Rewrite `blocks/base.py` — Signal no lugar de PortSample**

Substituir o bloco `@dataclass PortSample` (base.py:29-38) por:

```python
from ottima_core.signal import Quality, Substatus


@dataclass(frozen=True, slots=True)
class Signal:
    """Valor de uma porta numa varredura (ADR-043; forma do ADR-039 §4.1).

    `v is None` é cold start. `ok` é DERIVADO: só GOOD atua (emenda ADR-039 §4.1 —
    UNCERTAIN invalida atuação igual a BAD; a distinção é diagnóstico). Substatus e
    limites são produzidos SÓ pelo shell (D9); os demais blocos emitem os defaults.
    """

    v: float | bool | None
    quality: Quality = Quality.BAD
    substatus: Substatus = Substatus.NON_SPECIFIC
    hi_limited: bool = False
    lo_limited: bool = False

    @property
    def ok(self) -> bool:
        return self.quality is Quality.GOOD

    @property
    def init_request(self) -> bool:
        return self.substatus is Substatus.INIT_REQUEST
```

Ajustes no mesmo arquivo: `step()`/`has_cold_input`/`null_outputs` trocam a anotação
`PortSample`→`Signal`; `null_outputs` retorna `{port: Signal(None) for port in ports}`.
Docstring de `null_outputs` continua verdadeira ("nulas e inválidas").

- [ ] **Step 4: Migrar TODOS os construtores pelo mapa**

Regra geral: `PortSample(x, True)` → `Signal(x, Quality.GOOD)`; `PortSample(x, False)` →
`Signal(x)` (BAD default); `PortSample(x, sample.ok)` → `Signal(x, sample.quality)`
(propagação D6). Sites e formas exatas:

| arquivo:linha | de | para |
|---|---|---|
| scheduler.py:53 | `COLD = PortSample(None, False)` | `COLD = Signal(None)` |
| scheduler.py:367 | `PortSample(seed, True)` | `Signal(seed, Quality.GOOD)` (semente ADR-040 nasce GOOD) |
| opc_read.py:46 | `PortSample(None, False)` | `Signal(None)` |
| opc_read.py:50 | `PortSample(value, tag_value.quality == 0)` | `Signal(value, _QUALITY_FROM_OPC.get(tag_value.quality, Quality.BAD))` + no topo do módulo: `_QUALITY_FROM_OPC = {0: Quality.GOOD, 1: Quality.UNCERTAIN, 2: Quality.BAD}` — ÚNICA tradução OpcValue→Quality (ADR-043 §4) |
| constant.py:29 | `PortSample(self._value, True)` | `Signal(self._value, Quality.GOOD)` |
| scaler.py:62 | `PortSample(escalado, sample.ok)` | `Signal(escalado, sample.quality)` |
| first_order.py:57 | `PortSample(self._lag.step(value), sample.ok)` | `Signal(self._lag.step(value), sample.quality)` |
| kalman.py:70 | `PortSample(self._x, sample.ok)` | `Signal(self._x, sample.quality)` |
| integrator.py:76 | `PortSample(0.0, sample.ok)` | `Signal(0.0, sample.quality)` |
| integrator.py:84,96 | `PortSample(self._total, False)` | `Signal(self._total)` (vira UNCERTAIN na Task 3) |
| integrator.py:91 | `PortSample(self._total, sample.ok)` | `Signal(self._total, sample.quality)` |
| integrator.py:99 | `PortSample(self._total, True)` | `Signal(self._total, Quality.GOOD)` |
| tfs.py:197-210 | `ok = True` … `ok = ok and sample.ok` … `PortSample(total, ok)` | `q = Quality.GOOD` … `q = min(q, sample.quality)` … `Signal(total, q)` — POR LINHA, só elementos habilitados (forma quality do AND, ADR-022; linha toda desabilitada segue GOOD) |
| script.py:98-101 | `ok = all(sample.ok …)` … `PortSample(result.outputs[port], ok)` | `q = min((s.quality for s in inputs.values()), default=Quality.GOOD)` … `Signal(result.outputs[port], q)` (D6/D8) |
| pid.py:126-128 | `ok_entradas = all(sample.ok and math.isfinite(float(sample.v)) …)` | `q_entradas = min((s.quality for s in inputs.values()), default=Quality.GOOD)`; em seguida `if any(not math.isfinite(float(s.v)) for s in inputs.values()): q_entradas = Quality.BAD` (não-finito era inválido; continua) |
| pid.py:157 | `PortSample(resultado, ok_entradas)` | `Signal(resultado, q_entradas)` |
| pid.py:161 | `PortSample(self._last, False)` | `Signal(self._last)` (vira UNCERTAIN na Task 3) |
| fuzzy.py:147-148 | `ok_entradas = all(sample.ok and math.isfinite(…))` | mesmo par `min(…)` + rebaixa a BAD por não-finito do pid acima |
| fuzzy.py:187 | `PortSample(value, ok_entradas)` | `Signal(value, q_entradas)` |
| fuzzy.py:173,191 | `PortSample(…, False)` | `Signal(…)` (vira UNCERTAIN na Task 3) |
| mpc.py:462 | `PortSample(None, False)` | `Signal(None)` |
| mpc.py:792 | `PortSample(None, False)` | `Signal(None)` |
| mpc.py:827 | `PortSample(v, ok)` | `Signal(v, Quality.GOOD if ok else Quality.BAD)` (semântica própria do MPC preservada) |
| mpc.py:840-841 | `PortSample(1.0 if … else 0.0, ok)` | `Signal(1.0 if … else 0.0, Quality.GOOD if ok else Quality.BAD)` |
| bus_subscribe.py:52 | `PortSample(None, False)` | `Signal(None)` |
| bus_subscribe.py:60 | `PortSample(value.v, value.ok and fresco)` | `Signal(value.v, value.quality if fresco else Quality.BAD)` (payload ainda tem `ok` até a Task 4 — use `Quality.GOOD if value.ok else Quality.BAD` como quality do payload NESTA task; a Task 4 troca pelo campo real) |

Em cada arquivo: trocar o import `from .base import Block, PortSample` por
`from .base import Block, Signal` (+ `from ottima_core.signal import Quality` onde usado)
e as anotações de tipo `PortSample`→`Signal`.

- [ ] **Step 5: Fundir o shell — deletar `shell/signal.py`, rewire `shell/block.py`**

1. `rm services/flow-runtime/src/ottima_flow_runtime/blocks/shell/signal.py`
2. `grep -rn "shell.signal\|from .signal\|as_signal\|make_signal" services/flow-runtime/` e migrar todo import para `ottima_flow_runtime.blocks.base` (Signal) / `ottima_core.signal` (Quality, Substatus). Inclui `shell/__init__.py` (reexports) e testes do shell.
3. Em `shell/block.py`:
   - linha 299: `self.pv_ok = as_signal(sample).is_good` → `self.pv_ok = sample.ok` (a emenda §4.1: UNCERTAIN agora derruba PV — comportamento vivo preservado, pois hoje uncertain chega colapsado em BAD)
   - linha 313: `as_signal(bk).init_request` → `bk.init_request`
   - linha 323: `not as_signal(fonte).is_good` → `not fonte.ok`
   - linhas 400-401: `sinal = as_signal(sample)` some; usar `sample.ok` / `float(sample.v)` direto
   - linhas 457-…, 466-…: `make_signal(x, q, substatus=…, hi_limited=…, lo_limited=…)` → `Signal(x, q, substatus=…, hi_limited=…, lo_limited=…)` (mesma ordem de campos; `ok` não é mais passado — derivado)

- [ ] **Step 6: Migrar os testes construtores**

`grep -rln "PortSample" services/flow-runtime/tests packages/ottima-core/tests` — em cada arquivo,
aplicar o MESMO mapa do Step 4 (True→`Quality.GOOD`, False→default BAD, `ok=x.ok`→`quality=x.quality`).
Asserções `sample.ok is False` etc. continuam válidas (propriedade). Asserções que comparem
dataclass inteiro (`== PortSample(…)`) viram `== Signal(…)`.

- [ ] **Step 7: Run flow-runtime suite**

Run: `uv run pytest services/flow-runtime/tests packages/ottima-core/tests -x -q`
Expected: PASS integral — nenhuma asserção comportamental foi editada, só construtores/tipos.
`grep -rn "PortSample" services/ packages/` devolve VAZIO.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(flow-runtime): Signal substitui PortSample — quality tri-state em toda porta (ADR-043)"
```

---

### Task 3: Retenção emite UNCERTAIN (D7)

Os quatro pontos internos onde "último valor conhecido, inválido" vira UNCERTAIN
(UncertainLastUsable). Atuação idêntica (`ok` False nos dois casos) — muda SÓ o rótulo.

**Files:**
- Modify: `blocks/pid.py:161` · `blocks/fuzzy.py:173,191` · `blocks/integrator.py:84,96`
- Test: arquivos de teste existentes de pid/fuzzy/integrator (acrescentar asserções de quality)

**Interfaces:**
- Consumes: `Signal`, `Quality` (Tasks 1–2)
- Produces: nada novo — refinamento de semântica

- [ ] **Step 1: Write the failing tests** (um por bloco, no arquivo de teste existente de cada um)

```python
# services/flow-runtime/tests/test_pid_block.py (acrescentar)
async def test_retido_sai_uncertain_com_ultimo_valor(pid_convergido):
    """RF-553 + ADR-043 D7: retenção = último bom com UNCERTAIN, não BAD."""
    saida = await pid_convergido.step({"pv": Signal(float("nan"), Quality.GOOD), "sp": Signal(50.0, Quality.GOOD)})
    assert saida["out"].ok is False
    assert saida["out"].quality is Quality.UNCERTAIN
    assert saida["out"].v is not None
```

```python
# services/flow-runtime/tests/test_integrator_block.py (acrescentar)
async def test_lacuna_retem_total_com_uncertain(integrator_com_total):
    saida = await integrator_com_total.step({"in": Signal(1.0, Quality.BAD)})
    assert saida["out"].quality is Quality.UNCERTAIN
    assert saida["out"].ok is False
```

```python
# services/flow-runtime/tests/test_fuzzy_block.py (acrescentar)
async def test_retencao_sai_uncertain(fuzzy_apos_bom):
    saida = await fuzzy_apos_bom.step({"in1": Signal(float("inf"), Quality.GOOD)})
    assert all(s.quality is Quality.UNCERTAIN for s in saida.values())
```

(Adapte os fixtures aos nomes REAIS já existentes em cada arquivo de teste — os três
arquivos já têm fixtures que levam o bloco ao estado "tem último valor bom"; reuse-os.
NÃO crie fixture nova se uma equivalente existir.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest services/flow-runtime/tests/test_pid_block.py services/flow-runtime/tests/test_integrator_block.py services/flow-runtime/tests/test_fuzzy_block.py -q`
Expected: os 3 novos FALHAM com `quality is BAD`; o resto PASSA. (Se os caminhos de teste
tiverem outro nome, localize com `grep -rln "def test_.*retid\|_retido\|retención\|retencao" services/flow-runtime/tests`.)

- [ ] **Step 3: Implement**

- `pid.py:161`: `return {"out": Signal(self._last, Quality.UNCERTAIN)}` — e docstring de `_retido` ganha "(UNCERTAIN, ADR-043 D7)".
- `fuzzy.py:173`: `port: Signal(sample.v, Quality.UNCERTAIN) for …`
- `fuzzy.py:191`: `outputs[port] = Signal(self._last_outputs[port].v, Quality.UNCERTAIN)`
- `integrator.py:84,96`: `return {"out": Signal(self._total, Quality.UNCERTAIN)}`

- [ ] **Step 4: Run tests to verify pass**

Run: mesmo comando do Step 2. Expected: PASS integral.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(flow-runtime): retenção emite UNCERTAIN — UncertainLastUsable (ADR-043 D7)"
```

---

### Task 4: Payloads `PortValue`/`ExchangeValue` + scheduler + blocos de barramento

**Files:**
- Modify: `packages/ottima-core/src/ottima_core/bus.py:69-86` (ExchangeValue), `:98-104` (PortValue)
- Modify: `services/flow-runtime/src/ottima_flow_runtime/scheduler.py:536`
- Modify: `services/flow-runtime/src/ottima_flow_runtime/blocks/bus_publish.py:61-67`, `bus_subscribe.py:50-60`
- Modify: testes que constroem os dois modelos — `packages/ottima-core/tests/test_bus.py`, `services/flow-runtime/tests/test_bus_blocks.py`, `test_snapshot.py`, `services/api/tests/test_ws*.py` (+ o que `grep -rln "PortValue(\|ExchangeValue(" services packages` achar)
- Test: os mesmos arquivos

**Interfaces:**
- Consumes: `Quality`, `Substatus` (Task 1), `Signal` (Task 2)
- Produces: `PortValue{v, quality: Quality, substatus: Substatus, hi_limited: bool, lo_limited: bool}` e `ExchangeValue{key, ts, v, quality, substatus, hi_limited, lo_limited, period_s}` — SEM `ok`. Task 5 regenera o contrato TS destes modelos.

- [ ] **Step 1: Write the failing tests**

```python
# packages/ottima-core/tests/test_bus.py (acrescentar/substituir os round-trips de PortValue/ExchangeValue)
from ottima_core.signal import Quality, Substatus


def test_port_value_carrega_signal_completo_sem_ok():
    pv = PortValue(v=1.5, quality=Quality.UNCERTAIN)
    data = json.loads(pv.model_dump_json())
    assert data == {"v": 1.5, "quality": 1, "substatus": 0, "hi_limited": False, "lo_limited": False}
    assert "ok" not in data


def test_exchange_value_round_trip_com_quality():
    ev = ExchangeValue(key="k", ts=datetime.now(UTC), v=True, quality=Quality.GOOD,
                       substatus=Substatus.NON_SPECIFIC, period_s=1.0)
    volta = ExchangeValue.model_validate_json(ev.model_dump_json())
    assert volta.v is True and volta.quality is Quality.GOOD  # bool não vira 1.0 (A-5)
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest packages/ottima-core/tests/test_bus.py -q`
Expected: FAIL — `ValidationError`/`TypeError` (campos não existem; `ok` requerido)

- [ ] **Step 3: Implement models**

`bus.py` — `PortValue` (substituir campos, manter docstring atualizada):

```python
class PortValue(BaseModel):
    """Valor de uma porta de bloco numa varredura (spec F3 §4.2; ADR-043 §6).

    Polaridade Fieldbus (BAD=0/UNCERTAIN=1/GOOD=2) — NUNCA a de OpcValue.
    Validade para render: `quality == GOOD`; o canvas dessatura o resto.
    """

    v: float | bool | None
    quality: Quality
    substatus: Substatus = Substatus.NON_SPECIFIC
    hi_limited: bool = False
    lo_limited: bool = False
```

`ExchangeValue` — trocar `ok: bool` por (docstring segue explicando D3/D4 do ADR-042 com
a emenda ADR-043):

```python
    quality: Quality
    substatus: Substatus = Substatus.NON_SPECIFIC
    hi_limited: bool = False
    lo_limited: bool = False
```

Import no topo: `from ottima_core.signal import Quality, Substatus`.

- [ ] **Step 4: Implement produtores/consumidores**

`scheduler.py:536`:

```python
block_id: {
    port: PortValue(
        v=sample.v,
        quality=sample.quality,
        substatus=sample.substatus,
        hi_limited=sample.hi_limited,
        lo_limited=sample.lo_limited,
    )
    for port, sample in ports.items()
}
```

`bus_publish.py:61-67` (transporte verbatim, D9):

```python
value = ExchangeValue(
    key=self._key,
    ts=ts if ts is not None else datetime.now(UTC),
    v=sample.v,
    quality=sample.quality,
    substatus=sample.substatus,
    hi_limited=sample.hi_limited,
    lo_limited=sample.lo_limited,
    period_s=self._period_s,
)
```

`bus_subscribe.py:50-60` (expiração rebaixa para UNCERTAIN — D7; nunca ELEVA um BAD publicado):

```python
value = self._snapshot.get(self._key)
if value is None:
    return {"out": Signal(None)}

agora = ts if ts is not None else datetime.now(UTC)
idade = (agora - value.ts).total_seconds()
limite = STALE_PERIODS * value.period_s
fresco = math.isfinite(limite) and limite > 0 and idade <= limite
quality = value.quality if fresco else min(value.quality, Quality.UNCERTAIN)
return {
    "out": Signal(
        value.v,
        quality,
        substatus=value.substatus,
        hi_limited=value.hi_limited,
        lo_limited=value.lo_limited,
    )
}
```

Atualizar as docstrings dos dois blocos (falam em `ok`/decisão A-6 → ADR-043).

- [ ] **Step 5: Migrar testes de payload**

`grep -rln "PortValue(\|ExchangeValue(" services packages` — todo construtor ganha
`quality=` no lugar de `ok=` (True→`Quality.GOOD`; False→`Quality.BAD`). Asserções de
dict JSON incluem os campos novos. Golden de contrato (`contracts_export`, ADR-034):
rodar `uv run pytest packages/ottima-core -q` e atualizar o golden conforme o
procedimento que o próprio teste documentar.

- [ ] **Step 6: Run**

Run: `uv run pytest packages/ottima-core services/flow-runtime/tests services/api/tests -q`
Expected: PASS integral. `grep -rn '\bok\b' packages/ottima-core/src/ottima_core/bus.py` sem hit em PortValue/ExchangeValue.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(core): PortValue/ExchangeValue carregam Signal completo — ok sai do wire (ADR-043 §6)"
```

---

### Task 5: Frontend — contrato regenerado + validade por quality

**Files:**
- Regenerate: `frontend/src/lib/contracts.gen.ts` (via script; NUNCA à mão)
- Modify: `frontend/src/features/flows/canalPrimitivos.ts:100-106` · `frontend/src/features/flows/graph.ts:433` · `frontend/src/features/flows/nodes/BlocoChapa.tsx:43-66`
- Test: specs de `npm run test:unit` que cubram `lerPortValue`/`graph`/chapa (localizar com `grep -rln "lerPortValue\|PortValue" frontend/src frontend/tests 2>/dev/null || grep -rln "lerPortValue" frontend`)

**Interfaces:**
- Consumes: modelos da Task 4 via `npm run generate:contracts`
- Produces: `portaValida(p: PortValue): boolean` e `QUALITY_GOOD`/`QUALITY_UNCERTAIN` em `canalPrimitivos.ts` — únicos pontos do frontend que interpretam quality

- [ ] **Step 1: Regenerar contratos**

Run: `cd frontend && npm run generate:contracts`
Expected: `contracts.gen.ts` com `PortValue { v; quality; substatus; hi_limited; lo_limited }`.
`npm run typecheck` agora FALHA nos consumidores de `.ok` — é o teste que guia a task.

- [ ] **Step 2: Atualizar `canalPrimitivos.ts`**

```typescript
/** Polaridade Fieldbus do ADR-043 (BAD=0/UNCERTAIN=1/GOOD=2). */
export const QUALITY_GOOD = 2;
export const QUALITY_UNCERTAIN = 1;

/** Validade para atuação/render (emenda ADR-039 §4.1): só GOOD. */
export function portaValida(valor: PortValue): boolean {
  return valor.quality === QUALITY_GOOD;
}

export function lerPortValue(bruto: unknown): PortValue | null {
  const item = objeto(bruto);
  if (item === null || typeof item.quality !== "number") return null;
  const v = item.v;
  if (v !== null && typeof v !== "number" && typeof v !== "boolean") return null;
  return {
    v,
    quality: item.quality,
    substatus: typeof item.substatus === "number" ? item.substatus : 0,
    hi_limited: item.hi_limited === true,
    lo_limited: item.lo_limited === true,
  };
}
```

- [ ] **Step 3: Consumidores**

- `graph.ts:433`: `return portaValida(porta) ? "good" : "bad";` (import de `canalPrimitivos`)
- `BlocoChapa.tsx` (`ValorPorta`): `valor.ok` → `portaValida(valor)` (linhas 57 e 63); no
  rótulo de invalidez, distinguir: `{!portaValida(valor) && (<span …>{valor.quality === QUALITY_UNCERTAIN ? "incerto" : "inválido"}</span>)}`
  e `title` do span externo com substatus quando `valor.substatus !== 0` (mapa local
  `SUBSTATUS_ROTULO: Record<number, string>` com os 7 nomes do ADR-039 em pt-BR).
- Qualquer outro erro de typecheck apontando `.ok` de **PortValue** segue o mesmo padrão
  (`portaValida`). NÃO tocar `.ok` de outras origens (fuzzy state, tagValues/OpcValue,
  `res.ok` do fetch).

- [ ] **Step 4: Run**

Run: `cd frontend && npm run typecheck && npm run test:unit && npm run build`
Expected: PASS. Ajustar specs que montavam `{v, ok}` para a forma nova.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(frontend): portas com quality/substatus — validade por GOOD (ADR-043)"
```

---

### Task 6: Documentação normativa (spec §8) + CLAUDE.md

**Files:**
- Create: `docs/adr/ADR-043-qualidade-fim-a-fim.md`
- Modify: `docs/adr/ADR-039-block-shell.md` (nota de emenda no §4.1) · `docs/adr/ADR-042-troca-de-variaveis-entre-flows.md` (nota em D3/D4) · `docs/PRD.md` §7.1 (linhas `flow.exchange` e `flow.status`) · `docs/GLOSSARY.md` (3 entradas) · `CLAUDE.md` (invariante ADR-042: `ok=False` → vocabulário novo)

**Interfaces:** nenhuma de código — materializa o que as Tasks 1–5 implementaram.

- [ ] **Step 1: ADR-043**

Estrutura (usar o formato dos ADRs vizinhos — Contexto/Decisão/Consequências):
Contexto (dois vocabulários, colapso no opc_read, pedido de fim-a-fim); Decisões D1–D9
COPIADAS da spec §2 (verbatim, com a tabela de tradução da spec §4 e a tabela de
propagação da §5); Emendas explícitas: ADR-039 §4.1 (`is_good` → `quality is GOOD`;
regras 5-8 passam a disparar também em UNCERTAIN — comportamento vivo preservado),
ADR-042 D3/D4 (payload novo + expiração rebaixa a UNCERTAIN), decisão A-6 da F3
(flag → tri-state); Registro: persistência byte-idêntica (não-GOOD historiado → `quality=2`;
ADR-037/RF-804 intactos); Fora de escopo = spec §10.

- [ ] **Step 2: Notas de emenda + PRD + GLOSSARY + CLAUDE.md**

- ADR-039 §4.1: acrescentar logo abaixo da linha "v1: `UNCERTAIN` é tratado como GOOD…":
  `> **Emendado pelo ADR-043:** UNCERTAIN invalida atuação (`is_good` ≡ `quality is GOOD`). Texto original mantido por histórico.`
- ADR-042 D3/D4: nota análoga apontando payload/expiração do ADR-043.
- PRD §7.1 (linhas 258 e 260):
  `flow.exchange … {key, ts, v, quality, substatus, hi_limited, lo_limited, period_s}`
  `flow.status.<flow_id> … ports{block_id→{porta:{v, quality, substatus, hi_limited, lo_limited}}}` + nota curta: "quality/substatus em polaridade Fieldbus (ADR-043); NÃO confundir com OpcValue.quality".
- GLOSSARY: `qualidade (de porta)` — tri-state Fieldbus BAD/UNCERTAIN/GOOD (ADR-043); `substatus` — campo de uso futuro, códigos por ADR (ADR-039/043); `status (de sinal)` — termo guarda-chuva FF = quality+substatus+limites; DISTINTO do status de MV (RF-626).
- CLAUDE.md, invariante do ADR-042: trocar "saída com `ok=False` mantendo o último valor" por "saída rebaixada a UNCERTAIN (inválida para atuação) mantendo o último valor (ADR-043)".

- [ ] **Step 3: Conferir consistência**

Releia ADR-043 contra a spec §2 — as nove decisões batem 1:1; nenhuma decisão nova
inventada aqui. `grep -n "ok" docs/PRD.md` nas linhas §7.1 editadas: sem sobra.

- [ ] **Step 4: Commit**

```bash
git add docs CLAUDE.md
git commit -m "docs: ADR-043 qualidade fim-a-fim + emendas ADR-039/042, PRD §7.1, GLOSSARY"
```

---

### Task 7: Gate integral

**Files:** nenhum novo — só execução e correções pontuais que os gates apontarem.

- [ ] **Step 1: Workspace** — `uv run pytest` (sobe Timescale efêmero). Expected: verde, incluindo aceitação MPC↔TFS sem NENHUMA asserção comportamental editada neste plano.
- [ ] **Step 2: Lint** — `uv run ruff check . && uv run ruff format --check .`
- [ ] **Step 3: Contrato em dia** — `cd frontend && npm run generate:contracts && git diff --exit-code`
- [ ] **Step 4: Frontend** — `npm run test:unit && npm run typecheck && npm run build`
- [ ] **Step 5: E2E** — stack com os dois composes; `OTTIMA_E2E=1 bash deploy/smoke.sh` (L1); L2 com credenciais inline (comando completo no CLAUDE.md §Comandos) — atenção aos cenários F3/F5 que assertam `ports`: eles devem ter sido atualizados nas Tasks 4–5 se assertavam a forma `{v, ok}`.
- [ ] **Step 6: Commit final de ajustes** (se houver) — `git commit -m "test: ajustes do gate integral da qualidade fim-a-fim"`

---

## Self-Review (executada na escrita do plano)

- **Spec coverage:** D1→T1/T2 · D2→T2 (opc_read) + constraint global · D3→T2 Step 5 + T6 · D4/D9→T2/T4 (defaults+transporte) + T6 · D5→T2 · D6→T2 Step 4 · D7→T3 + T4 (subscribe) · D8→T2 (script) · §4→T2 (opc_read; `_historized_value` fica correto SEM edição — `not sample.ok → 2` já cobre não-GOOD) · §6→T4 · §7→T5 · §8→T6 · §9→T7 · §10 respeitado (nenhuma task toca recorder/calc-worker/opc-worker/DDL).
- **Placeholders:** nenhum TBD; os dois pontos deliberadamente delegados ao executor (nomes reais de fixtures em T3, lista de arquivos de teste via grep em T2/T4/T5) vêm com o comando exato de descoberta.
- **Type consistency:** `Signal(v, quality, substatus=, hi_limited=, lo_limited=)` idêntico em T2/T3/T4; `portaValida`/`QUALITY_GOOD` definidos em T5 Step 2 e usados em T5 Step 3; `_QUALITY_FROM_OPC` definido e usado só em opc_read.
