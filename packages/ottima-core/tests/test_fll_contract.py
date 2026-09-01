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


def test_default_fll_e_sugeno_ordem_zero() -> None:
    """SPEC secao 4.3: Sugeno + WeightedAverage e o padrao de producao (custo O(regras))."""
    assert _engine(FUZZY_LOOP_DEFAULT_FLL).infer_type() is fl.Engine.Type.TakagiSugeno


def test_f2_lock_previous_true_e_rejeitado_com_codigo_dedicado() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("lock-previous: false", "lock-previous: true")
    assert "FLL_LOCK_PREVIOUS_FORBIDDEN" in validate_fll_contract(_engine(fll))


def test_default_nan_obrigatorio() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("default: nan", "default: 0.000")
    assert "FLL_DEFAULT_MUST_BE_NAN" in validate_fll_contract(_engine(fll))


def test_nomes_e_contagem_de_variaveis() -> None:
    # As REFERENCIAS nas regras tambem sao renomeadas: renomear so a declaracao faz o
    # `from_string` levantar SyntaxError ("expected variable ... but found 'de'") e o
    # contrato nunca seria exercido.
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("InputVariable: de", "InputVariable: derr").replace(
        "de is ", "derr is "
    )
    assert "FLL_INPUTS_MUST_BE_E_DE" in validate_fll_contract(_engine(fll))


def test_nome_da_saida() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("OutputVariable: du", "OutputVariable: saida").replace(
        "then du is ", "then saida is "
    )
    assert "FLL_OUTPUT_MUST_BE_DU" in validate_fll_contract(_engine(fll))


def test_faixa_fora_do_unitario() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("range: -1.000 1.000", "range: -2.000 2.000", 1)
    assert "FLL_RANGE_MUST_BE_UNIT" in validate_fll_contract(_engine(fll))


def test_lock_range_obrigatorio() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("lock-range: true", "lock-range: false", 1)
    assert "FLL_LOCK_RANGE_REQUIRED" in validate_fll_contract(_engine(fll))


def test_um_unico_rule_block() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL + (
        "RuleBlock: extra\n"
        "  enabled: true\n"
        "  conjunction: AlgebraicProduct\n"
        "  disjunction: Maximum\n"
        "  implication: AlgebraicProduct\n"
        "  activation: General\n"
        "  rule: if e is NG then du is NG\n"
    )
    assert "FLL_RULEBLOCK_MUST_BE_SINGLE" in validate_fll_contract(_engine(fll))
