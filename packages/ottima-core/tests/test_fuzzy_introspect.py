"""Mesa de casos da introspecção de FLL + contrato `FuzzyState` (página FUZZY OPERATE, ADR-030).

Isolado de `test_flowgraph_fuzzy.py` pelo mesmo motivo de sempre: requisito novo (telemetria/
introspecção), tabela de casos própria. O frontend nunca parseia FLL (ADR-005/ADR-029) — tudo
que a página desenha (nomes, curvas, normas, regras) nasce em `introspect_fll`.
"""

import math
from datetime import UTC, datetime

import pytest

from ottima_core.bus import FuzzyState, FuzzyTermDegree, FuzzyVarState, channel_fuzzy_state
from ottima_core.contracts_export import FUZZY_DEFAULT_FLL, build_contracts
from ottima_core.flowgraph.introspect import N_PONTOS, introspect_fll

MIN_FLL = """Engine: minimo
InputVariable: in1
  enabled: true
  range: 0.000 10.000
  lock-range: false
  term: low Triangle 0.000 0.000 10.000
  term: high Triangle 0.000 10.000 10.000
OutputVariable: out1
  enabled: true
  range: 0.000 10.000
  lock-range: false
  aggregation: Maximum
  defuzzifier: Centroid 200
  default: 0.000
  lock-previous: false
  term: low Triangle 0.000 0.000 10.000
  term: high Triangle 0.000 10.000 10.000
RuleBlock: rb1
  enabled: true
  conjunction: none
  disjunction: none
  implication: Minimum
  activation: General
  rule: if in1 is low then out1 is low
  rule: if in1 is high then out1 is high"""


def test_canal_fuzzy_state() -> None:
    assert channel_fuzzy_state(7, "fz-1") == "fuzzy.state.7.fz-1"


def test_fuzzy_state_json_round_trip_sem_nan() -> None:
    """`v=None` cobre RF-542 no barramento: não-finito NUNCA vira `NaN` no JSON do canal."""
    state = FuzzyState(
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        ok=True,
        inputs=[
            FuzzyVarState(
                port="IN1", name="in1", v=5.0, terms=[FuzzyTermDegree(term="low", degree=0.5)]
            )
        ],
        rules=[0.5, 0.0],
        outputs=[FuzzyVarState(port="OUT1", name="out1", v=None, terms=[])],
    )
    texto = state.model_dump_json()
    assert "NaN" not in texto
    volta = FuzzyState.model_validate_json(texto)
    assert volta.outputs[0].v is None
    assert volta.rules == [0.5, 0.0]


def test_fuzzy_state_exportado_nos_contratos_ws() -> None:
    ws_payloads = build_contracts()["ws_payloads"]
    assert isinstance(ws_payloads, dict)
    assert "FuzzyState" in ws_payloads


def test_introspeccao_min_fll_variaveis() -> None:
    intro = introspect_fll(MIN_FLL)

    assert [v.port for v in intro.inputs] == ["IN1"]
    assert [v.port for v in intro.outputs] == ["OUT1"]
    entrada = intro.inputs[0]
    assert entrada.name == "in1"
    assert (entrada.minimum, entrada.maximum) == (0.0, 10.0)
    assert len(entrada.x) == N_PONTOS
    assert entrada.x[0] == 0.0
    assert entrada.x[-1] == 10.0

    saida = intro.outputs[0]
    assert saida.name == "out1"
    assert saida.defuzzifier == "Centroid"
    assert saida.resolution == 200
    assert saida.aggregation == "Maximum"
    assert saida.default_value == 0.0
    assert saida.lock_previous is False


def test_introspeccao_min_fll_curvas() -> None:
    """Geometria conhecida: `low Triangle 0 0 10` vale 1 em x=0 e 0 em x=10; simétrico no `high`."""
    intro = introspect_fll(MIN_FLL)
    entrada = intro.inputs[0]
    low = next(t for t in entrada.terms if t.name == "low")
    high = next(t for t in entrada.terms if t.name == "high")

    assert low.kind == "Triangle"
    assert len(low.y) == N_PONTOS
    assert low.y[0] == pytest.approx(1.0)
    assert low.y[-1] == pytest.approx(0.0)
    assert high.y[0] == pytest.approx(0.0)
    assert high.y[-1] == pytest.approx(1.0)
    assert all(math.isfinite(y) and 0.0 <= y <= 1.0 for t in entrada.terms for y in t.y)


def test_introspeccao_min_fll_regras() -> None:
    intro = introspect_fll(MIN_FLL)
    assert len(intro.rule_blocks) == 1
    rb = intro.rule_blocks[0]
    assert rb.name == "rb1"
    assert rb.conjunction is None
    assert rb.disjunction is None
    assert rb.implication == "Minimum"
    assert rb.activation == "General"
    assert rb.rules == [
        "if in1 is low then out1 is low",
        "if in1 is high then out1 is high",
    ]


def test_introspeccao_default_fll() -> None:
    """O FLL da paleta (1 entrada Bell, 4 saídas WeightedAverage) introspecta inteiro:
    `default: nan` vira `None` (JSON estrito) e WeightedAverage não tem `resolution`.
    """
    intro = introspect_fll(FUZZY_DEFAULT_FLL)

    assert [v.port for v in intro.inputs] == ["IN1"]
    assert intro.inputs[0].name == "X"
    assert {t.kind for t in intro.inputs[0].terms} == {"Bell"}
    assert [v.port for v in intro.outputs] == ["OUT1", "OUT2", "OUT3", "OUT4"]
    for saida in intro.outputs:
        assert saida.defuzzifier == "WeightedAverage"
        assert saida.resolution is None
        assert saida.default_value is None  # `default: nan` não pode virar NaN no JSON
    assert all(math.isfinite(y) for v in intro.inputs + intro.outputs for t in v.terms for y in t.y)


def test_introspeccao_fll_invalido() -> None:
    with pytest.raises(ValueError, match="FLL inválido"):
        introspect_fll("isto não é FuzzyLite Language nem de longe\n=== !!! ===")
