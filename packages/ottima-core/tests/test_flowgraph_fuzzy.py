"""Mesa de casos do bloco Fuzzy no `graph_json` (RF-541..543, ADR-029).

Isolado de `test_flowgraph.py`/`test_flowgraph_parse.py` pelo mesmo motivo do
`test_flowgraph_filtros.py`: bloco novo, tabela de casos própria — o grafo de referência de
`test_flowgraph.py` não tem Fuzzy, e cada mutação deste bloco é um caso de outro requisito.
"""

import pytest

from ottima_core.contracts_export import FUZZY_DEFAULT_FLL
from ottima_core.flowgraph import FuzzyConfig, GraphParseError, TagRef, parse_graph, validate_graph
from ottima_core.flowgraph.parse import MAX_FUZZY_FLL_LENGTH

TS = 1.0

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
"""FLL mínimo válido: 1 entrada, 1 saída, defuzzifier e regras cobrindo os dois termos."""

INCOMPLETE_FLL = """Engine: incompleto
InputVariable: a
  enabled: true
  range: 0.000 10.000
  lock-range: false
  term: low Triangle 0.000 0.000 10.000
InputVariable: b
  enabled: true
  range: 0.000 10.000
  lock-range: false
  term: low Triangle 0.000 0.000 10.000
OutputVariable: out1
  enabled: true
  range: 0.000 10.000
  lock-range: false
  aggregation: Maximum
  defuzzifier: none
  default: 0.000
  lock-previous: false
  term: low Triangle 0.000 0.000 10.000
RuleBlock: rb1
  enabled: true
  conjunction: none
  disjunction: none
  implication: Minimum
  activation: General
  rule: if a is low and b is low then out1 is low"""
"""FLL estruturalmente incompleto de propósito: regra com ' and ' no antecedente sem
`conjunction` definida, e `OutputVariable` Mamdani (com `term:`) sem `defuzzifier`. Sintaxe
válida — `FllImporter` monta o `Engine` — mas `Engine.is_ready()` reprova."""

INVALID_FLL = "isto não é FuzzyLite Language nem de longe\n=== !!! ==="


def _node(node_id: str, node_type: str, exec_order: int, **data: object) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, "label": "", **data},
    }


def _fuzzy(node_id: str = "fz1", *, exec_order: int = 2, **config: object) -> dict:
    defaults = {"fll": MIN_FLL, "n_inputs": 1, "n_outputs": 1}
    return _node(node_id, "fuzzy", exec_order, **(defaults | config))


def _leitura(node_id: str = "r1", *, exec_order: int = 1, tag_id: int = 1) -> dict:
    return _node(node_id, "opc_read", exec_order, tag_id=tag_id)


def _aresta(source: str, target: str, *, edge_id: str = "e1", target_handle: str = "IN1") -> dict:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "sourceHandle": "out",
        "targetHandle": target_handle,
    }


def _graph(*nodes: dict, edges: list[dict] | None = None) -> dict:
    return {"nodes": list(nodes), "edges": [] if edges is None else edges}


def _ligado(fuzzy_node: dict) -> dict:
    """Leitura -> IN1 do Fuzzy: toda entrada declarada é obrigatória (RF-541), como no
    Script — o caso válido liga a única entrada do FLL mínimo."""
    return _graph(_leitura(), fuzzy_node, edges=[_aresta("r1", fuzzy_node["id"])])


def _ligado_n(fuzzy_node: dict, n_inputs: int) -> dict:
    """Leitura -> IN1..INn do Fuzzy: fan-out de uma única leitura, uma aresta por entrada."""
    edges = [
        _aresta("r1", fuzzy_node["id"], edge_id=f"e{i}", target_handle=f"IN{i}")
        for i in range(1, n_inputs + 1)
    ]
    return _graph(_leitura(), fuzzy_node, edges=edges)


def _tags() -> dict[int, TagRef]:
    return {1: TagRef(id=1, conn_id=1, direction="r", data_type="float")}


def parse_errors(graph: dict) -> list[str]:
    with pytest.raises(GraphParseError) as exc:
        parse_graph(graph)
    return exc.value.errors


def errors_of(graph: dict, ts_seconds: float = TS) -> list[str]:
    return validate_graph(parse_graph(graph), _tags(), ts_seconds).errors


def has(messages: list[str], *fragments: str) -> bool:
    return any(all(fragment in message for fragment in fragments) for message in messages)


# --------------------------------------------------------------------------------------
# parse_graph — forma da config (FuzzyConfig)
# --------------------------------------------------------------------------------------


def test_fuzzy_parseia_com_config_tipada():
    node = parse_graph(_ligado(_fuzzy())).node("fz1")

    assert isinstance(node.config, FuzzyConfig)
    assert node.config.fll == MIN_FLL
    assert node.config.n_inputs == 1
    assert node.config.n_outputs == 1
    assert node.config.output_eu == {}


def test_fuzzy_reprova_output_eu_com_chave_orfa():
    graph = _ligado(_fuzzy(n_outputs=1, output_eu={"OUT2": "C"}))
    assert has(parse_errors(graph), "fz1", "OUT2")


def test_fuzzy_aceita_output_eu_em_porta_existente():
    node = parse_graph(_ligado(_fuzzy(n_outputs=1, output_eu={"OUT1": "C"}))).node("fz1")
    assert node.config.output_eu == {"OUT1": "C"}


@pytest.mark.parametrize(
    ("field", "value"), [("n_inputs", 0), ("n_outputs", 0), ("n_inputs", 9), ("n_outputs", 9)]
)
def test_fuzzy_reprova_numero_de_portas_fora_de_1_8(field: str, value: int):
    graph = _ligado(_fuzzy(**{field: value}))
    assert has(parse_errors(graph), "fz1", field), (field, value)


def test_fuzzy_aceita_limite_exato_de_1_e_8():
    """1 e 8 são os dois extremos inclusivos (teto = `MAX_SCRIPT_PORTS`); 0 e 9 já reprovam
    no teste acima."""
    graph = _ligado(_fuzzy(n_inputs=1, n_outputs=8))
    config = parse_graph(graph).node("fz1").config
    assert (config.n_inputs, config.n_outputs) == (1, 8)


# --------------------------------------------------------------------------------------
# validate_graph — conteúdo do FLL (RF-541, ADR-029)
# --------------------------------------------------------------------------------------


def test_fuzzy_ligado_com_fll_valido_e_aceito():
    assert errors_of(_ligado(_fuzzy())) == []


def test_validate_reprova_fll_sintaticamente_invalido():
    graph = _ligado(_fuzzy(fll=INVALID_FLL))
    assert has(errors_of(graph), "fz1", "FLL inválido")


def test_validate_reprova_contagem_de_entradas_divergente():
    """FLL default declara 1 entrada / 4 saídas; a config aqui pede 2 entradas — diverge só
    do lado das entradas, então só esse erro deve aparecer."""
    fuzzy_node = _fuzzy(fll=FUZZY_DEFAULT_FLL, n_inputs=2, n_outputs=4)
    graph = _ligado_n(fuzzy_node, n_inputs=2)
    assert has(errors_of(graph), "fz1", "variável(is) de entrada")


def test_validate_reprova_fll_estruturalmente_incompleto():
    """Regra com `and` sem `conjunction` + saída Mamdani sem `defuzzifier`: sintaxe válida,
    `Engine.is_ready()` reprova — os erros da biblioteca chegam anexados na mensagem."""
    fuzzy_node = _fuzzy(fll=INCOMPLETE_FLL, n_inputs=2, n_outputs=1)
    graph = _ligado_n(fuzzy_node, n_inputs=2)
    assert has(errors_of(graph), "fz1", "motor fuzzy não está pronto")


def test_fuzzy_default_fll_passa_validate_graph_limpo():
    """TESTE-CHAVE (k): a paleta default (RF-541, ADR-029) precisa continuar válida contra
    a própria validação que ela vai enfrentar no save — se quebrar, todo flow novo que
    aceita o padrão do editor nasce com um bloco Fuzzy reprovado."""
    fuzzy_node = _fuzzy(fll=FUZZY_DEFAULT_FLL, n_inputs=1, n_outputs=4)
    assert errors_of(_ligado(fuzzy_node)) == []


def test_entrada_do_fuzzy_e_obrigatoria():
    graph = _graph(_leitura(), _fuzzy())
    assert has(errors_of(graph), "fz1", "IN1", "obrigatória")


def test_porta_do_fuzzy_e_numerica():
    """Decisão A-5: só o Script é bivalente; tag booleana na entrada do Fuzzy é 422."""
    graph = _ligado(_fuzzy())
    graph["nodes"][0]["data"]["tag_id"] = 2
    tags = _tags() | {2: TagRef(id=2, conn_id=1, direction="r", data_type="bool")}
    result = validate_graph(parse_graph(graph), tags, TS)
    assert has(result.errors, "booleana")


# --------------------------------------------------------------------------------------
# Tetos de custo (FUZZY-SEC): tamanho do FLL e resolution do defuzzifier
# --------------------------------------------------------------------------------------


def test_fuzzy_reprova_fll_acima_do_teto_de_caracteres():
    """FUZZY-SEC-02: o parse (forma) reprova antes do validate — o texto gigante nem chega
    ao parser da fuzzylite."""
    graph = _ligado(_fuzzy(fll="Engine: grande\n" + "x" * MAX_FUZZY_FLL_LENGTH))
    assert has(parse_errors(graph), "fz1", "excede o teto")


def test_validate_reprova_resolution_acima_do_teto():
    """FUZZY-SEC-01: `defuzzifier: Centroid <N>` sem teto alocaria array de N pontos a cada
    varredura e travaria o event loop do flow-runtime (ADR-004)."""
    graph = _ligado(_fuzzy(fll=MIN_FLL.replace("Centroid 200", "Centroid 20000")))
    assert has(errors_of(graph), "fz1", "resolution", "excede o teto de 10000")


def test_validate_aceita_resolution_no_teto():
    """10000 é o teto inclusivo — valores até ele passam (uso legítimo de campo)."""
    graph = _ligado(_fuzzy(fll=MIN_FLL.replace("Centroid 200", "Centroid 10000")))
    assert errors_of(graph) == []
