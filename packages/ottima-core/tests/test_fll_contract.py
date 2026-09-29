"""Contrato FLL do fuzzy_loop (SPEC_FUZZY secao 3.2, v2 multicanal). F1/F2 no validador."""

import fuzzylite as fl

from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL
from ottima_core.flowgraph.fll_contract import validate_fll_contract
from ottima_core.flowgraph.fll_defaults import fuzzy_loop_default_fll


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


def test_nomes_de_variaveis_sao_livres() -> None:
    """v2: o contrato e POSICIONAL (contagem + faixa + forma), nao por nome — renomear
    `e`/`de`/`du` mantendo as referencias das regras nao viola nada."""
    fll = (
        FUZZY_LOOP_DEFAULT_FLL.replace("InputVariable: de", "InputVariable: derr")
        .replace("de is ", "derr is ")
        .replace("OutputVariable: du", "OutputVariable: saida")
        .replace("then du is ", "then saida is ")
    )
    assert validate_fll_contract(_engine(fll)) == []


def test_contagem_de_entradas_2n_loops() -> None:
    """Default de 1 canal avaliado contra n_loops=2: faltam entradas e saidas."""
    erros = validate_fll_contract(_engine(FUZZY_LOOP_DEFAULT_FLL), n_loops=2)
    assert "FLL_INPUT_COUNT_MUST_BE_2N_LOOPS" in erros
    assert "FLL_OUTPUT_COUNT_MUST_BE_N_LOOPS" in erros


def test_default_mimo_satisfaz_o_contrato_do_seu_canal() -> None:
    for n in (2, 3, 4):
        engine = _engine(fuzzy_loop_default_fll(n))
        assert validate_fll_contract(engine, n_loops=n) == []
        assert engine.is_ready()
        assert len(list(engine.input_variables)) == 2 * n
        assert len(list(engine.output_variables)) == n


def test_default_mimo_rejeitado_como_siso() -> None:
    erros = validate_fll_contract(_engine(fuzzy_loop_default_fll(2)), n_loops=1)
    assert "FLL_INPUT_COUNT_MUST_BE_2N_LOOPS" in erros
    assert "FLL_OUTPUT_COUNT_MUST_BE_N_LOOPS" in erros


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
