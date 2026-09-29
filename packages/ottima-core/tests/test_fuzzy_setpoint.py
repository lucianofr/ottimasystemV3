"""SP do operador no bloco `fuzzy` (RF-541 revisado): a contagem de variáveis do FLL ganha
uma entrada reservada ao SP, e a introspecção rotula essa variável como porta `SP`.

Sem SP (`setpoint=None`) o contrato é o de sempre: portas mapeadas verbatim às variáveis do
FLL (ADR-029) — os testes antigos continuam valendo.
"""

import pytest
from pydantic import ValidationError

from ottima_core.flowgraph import FuzzyConfig, TagRef, parse_graph, validate_graph
from ottima_core.flowgraph.introspect import introspect_fll

SP_FLL = """Engine: com_sp
InputVariable: pv
  enabled: true
  range: 0.000 100.000
  lock-range: true
  term: baixa Triangle 0.000 0.000 100.000
  term: alta Triangle 0.000 100.000 100.000
InputVariable: sp
  enabled: true
  range: 0.000 100.000
  lock-range: true
  term: baixa Triangle 0.000 0.000 100.000
  term: alta Triangle 0.000 100.000 100.000
OutputVariable: mv
  enabled: true
  range: 0.000 100.000
  lock-range: true
  aggregation: none
  defuzzifier: WeightedAverage
  default: nan
  lock-previous: false
  term: zero Constant 0.000
  term: cem Constant 100.000
RuleBlock: regras
  enabled: true
  conjunction: AlgebraicProduct
  disjunction: Maximum
  implication: AlgebraicProduct
  activation: General
  rule: if pv is baixa and sp is baixa then mv is zero
  rule: if pv is baixa and sp is alta then mv is cem
  rule: if pv is alta and sp is baixa then mv is zero
  rule: if pv is alta and sp is alta then mv is cem
"""

UM_IN_FLL = """Engine: um_in
InputVariable: pv
  enabled: true
  range: 0.000 100.000
  lock-range: true
  term: baixa Triangle 0.000 0.000 100.000
  term: alta Triangle 0.000 100.000 100.000
OutputVariable: mv
  enabled: true
  range: 0.000 100.000
  lock-range: true
  aggregation: none
  defuzzifier: WeightedAverage
  default: nan
  lock-previous: false
  term: zero Constant 0.000
  term: cem Constant 100.000
RuleBlock: regras
  enabled: true
  conjunction: AlgebraicProduct
  disjunction: Maximum
  implication: AlgebraicProduct
  activation: General
  rule: if pv is baixa then mv is zero
  rule: if pv is alta then mv is cem
"""

TAGS = {1: TagRef(id=1, conn_id=1, direction="r", data_type="float")}


def _grafo(fll: str, setpoint) -> dict:
    dados = {"exec_order": 2, "fll": fll, "n_inputs": 1, "n_outputs": 1}
    if setpoint is not None:
        dados["setpoint"] = setpoint
    return {
        "nodes": [
            {
                "id": "r1",
                "type": "opc_read",
                "position": {"x": 0, "y": 0},
                "data": {"exec_order": 1, "tag_id": 1},
            },
            {"id": "fz1", "type": "fuzzy", "position": {"x": 0, "y": 0}, "data": dados},
        ],
        "edges": [
            {
                "id": "e1",
                "source": "r1",
                "sourceHandle": "out",
                "target": "fz1",
                "targetHandle": "IN1",
            }
        ],
    }


def erros(graf: dict) -> list[str]:
    return validate_graph(parse_graph(graf), TAGS, 1.0).errors


def test_com_setpoint_o_fll_declara_uma_entrada_a_mais():
    assert erros(_grafo(SP_FLL, 50.0)) == []


def test_com_setpoint_fll_sem_a_variavel_extra_e_erro_explicando_o_sp():
    mensagens = erros(_grafo(UM_IN_FLL, 50.0))
    assert len(mensagens) == 1
    assert "n_inputs=2" in mensagens[0]
    assert "SP do operador" in mensagens[0]


def test_sem_setpoint_a_contagem_continua_a_de_sempre():
    assert erros(_grafo(UM_IN_FLL, None)) == []
    mensagens = erros(_grafo(SP_FLL, None))
    assert len(mensagens) == 1
    assert "n_inputs=1" in mensagens[0]
    assert "SP do operador" not in mensagens[0]


def test_introspecao_rotula_a_ultima_entrada_como_sp():
    intro = introspect_fll(SP_FLL, ultima_entrada_e_sp=True)
    assert [v.port for v in intro.inputs] == ["IN1", "SP"]
    assert [v.name for v in intro.inputs] == ["pv", "sp"]

    intro = introspect_fll(SP_FLL)
    assert [v.port for v in intro.inputs] == ["IN1", "IN2"]


def test_setpoint_nao_finito_e_recusado_na_config():
    with pytest.raises(ValidationError):
        FuzzyConfig(fll=UM_IN_FLL, n_inputs=1, n_outputs=1, setpoint=float("nan"))


# --------------------------------------------------------- fonte do SP: operador x entrada


def _grafo_fonte(fll: str, *, setpoint=None, sp_source=None, fio_sp: bool = False) -> dict:
    dados: dict = {"exec_order": 2, "fll": fll, "n_inputs": 1, "n_outputs": 1}
    if setpoint is not None:
        dados["setpoint"] = setpoint
    if sp_source is not None:
        dados["sp_source"] = sp_source
    nos = [
        {
            "id": "r1",
            "type": "opc_read",
            "position": {"x": 0, "y": 0},
            "data": {"exec_order": 1, "tag_id": 1},
        },
        {"id": "fz1", "type": "fuzzy", "position": {"x": 0, "y": 0}, "data": dados},
    ]
    arestas = [
        {"id": "e1", "source": "r1", "sourceHandle": "out", "target": "fz1", "targetHandle": "IN1"}
    ]
    if fio_sp:
        nos.append(
            {
                "id": "r2",
                "type": "opc_read",
                "position": {"x": 0, "y": 0},
                "data": {"exec_order": 3, "tag_id": 2},
            }
        )
        arestas.append(
            {
                "id": "e2",
                "source": "r2",
                "sourceHandle": "out",
                "target": "fz1",
                "targetHandle": "sp",
            }
        )
    return {"nodes": nos, "edges": arestas}


TAGS_COM_SP = {
    1: TagRef(id=1, conn_id=1, direction="r", data_type="float"),
    2: TagRef(id=2, conn_id=1, direction="r", data_type="float"),
}


def erros_fonte(graf: dict) -> list[str]:
    return validate_graph(parse_graph(graf), TAGS_COM_SP, 1.0).errors


def test_sp_pela_entrada_exige_o_fio_e_casa_a_contagem():
    assert erros_fonte(_grafo_fonte(SP_FLL, sp_source="entrada", fio_sp=True)) == []


def test_sp_pela_entrada_sem_o_fio_e_erro_de_entrada_obrigatoria():
    mensagens = erros_fonte(_grafo_fonte(SP_FLL, sp_source="entrada"))
    assert any("entrada 'sp' é obrigatória" in m for m in mensagens)


def test_fio_sp_sem_a_fonte_entrada_e_porta_inexistente():
    mensagens = erros_fonte(_grafo_fonte(SP_FLL, setpoint=50.0, fio_sp=True))
    assert any("'sp' não é uma entrada" in m for m in mensagens)


def test_fonte_entrada_com_setpoint_e_recusada_no_parse():
    from ottima_core.flowgraph import GraphParseError

    with pytest.raises(GraphParseError, match="setpoint"):
        parse_graph(_grafo_fonte(SP_FLL, setpoint=50.0, sp_source="entrada", fio_sp=True))


def test_fonte_operador_sem_setpoint_e_recusada_no_parse():
    from ottima_core.flowgraph import GraphParseError

    with pytest.raises(GraphParseError, match="setpoint"):
        parse_graph(_grafo_fonte(SP_FLL, sp_source="operador", fio_sp=True))


def test_sp_source_fora_do_vocabulario_e_recusado():
    from ottima_core.flowgraph import GraphParseError

    with pytest.raises(GraphParseError):
        parse_graph(_grafo_fonte(SP_FLL, sp_source="wifi", fio_sp=True))
