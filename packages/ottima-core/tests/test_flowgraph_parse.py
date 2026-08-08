"""Mesa de casos de `output_eu` em `ScriptConfig`/`TfsConfig` (spec F6 §4.1, tarefa 4.1).

Isolado de `test_flowgraph.py` (que já cobre o resto de `parse_graph`/`validate_graph`)
para não colidir com o arquivo de outra tarefa do mesmo batch.
"""

import pytest

from ottima_core.flowgraph import GraphParseError, parse_graph


def _iopdt(*, enabled: bool = False) -> dict:
    return {"enabled": enabled, "kind": "iopdt", "params": {"Ki": 1.0, "theta": 0.0}}


def _tfs_matrix() -> list[list[dict]]:
    return [[_iopdt(), _iopdt()], [_iopdt(), _iopdt()]]


def _node(node_id: str, node_type: str, exec_order: int, **data: object) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, "label": "", **data},
    }


def _graph(*nodes: dict) -> dict:
    return {"nodes": list(nodes), "edges": []}


def _script(node_id: str = "s1", *, n_outputs: int = 2, output_eu: dict | None = None) -> dict:
    data: dict = {"n_inputs": 1, "n_outputs": n_outputs, "code": "OUT1 = IN1"}
    if output_eu is not None:
        data["output_eu"] = output_eu
    return _node(node_id, "script", 1, **data)


def _tfs(node_id: str = "t1", *, output_eu: dict | None = None) -> dict:
    data: dict = {"matrix": _tfs_matrix()}
    if output_eu is not None:
        data["output_eu"] = output_eu
    return _node(node_id, "tfs", 1, **data)


def parse_errors(graph: dict) -> list[str]:
    with pytest.raises(GraphParseError) as exc:
        parse_graph(graph)
    return exc.value.errors


def has(messages: list[str], *fragments: str) -> bool:
    return any(all(fragment in message for fragment in fragments) for message in messages)


# --------------------------------------------------------------------------------------
# script — output_eu
# --------------------------------------------------------------------------------------


def test_script_aceita_eu_em_porta_existente():
    graph = _graph(_script(n_outputs=2, output_eu={"OUT1": "t/h"}))
    node = parse_graph(graph).node("s1")
    assert node.config.output_eu == {"OUT1": "t/h"}


def test_script_eu_e_opcional_por_porta():
    """Declarar EU só de OUT1 num Script de 3 saídas é válido."""
    graph = _graph(_script(n_outputs=3, output_eu={"OUT1": "t/h"}))
    node = parse_graph(graph).node("s1")
    assert node.config.output_eu == {"OUT1": "t/h"}


def test_script_reprova_porta_fora_do_n_outputs():
    graph = _graph(_script(n_outputs=2, output_eu={"OUT3": "t/h"}))
    assert has(parse_errors(graph), "s1", "OUT3")


def test_script_reprova_porta_com_grafia_diferente():
    graph = _graph(_script(n_outputs=2, output_eu={"out1": "t/h"}))
    assert has(parse_errors(graph), "s1", "out1")


def test_script_reprova_valor_nao_string():
    graph = _graph(_script(n_outputs=2, output_eu={"OUT1": 1}))
    assert has(parse_errors(graph), "s1", "output_eu")


def test_script_sem_output_eu_e_valido_com_dict_vazio():
    graph = _graph(_script(n_outputs=2))
    node = parse_graph(graph).node("s1")
    assert node.config.output_eu == {}


# --------------------------------------------------------------------------------------
# tfs — output_eu
# --------------------------------------------------------------------------------------


def test_tfs_aceita_y1_e_y2():
    graph = _graph(_tfs(output_eu={"y1": "C", "y2": "kg/h"}))
    node = parse_graph(graph).node("t1")
    assert node.config.output_eu == {"y1": "C", "y2": "kg/h"}


def test_tfs_reprova_porta_inexistente():
    graph = _graph(_tfs(output_eu={"y3": "C"}))
    assert has(parse_errors(graph), "t1", "y3")


def test_tfs_reprova_valor_nao_string():
    graph = _graph(_tfs(output_eu={"y1": 1}))
    assert has(parse_errors(graph), "t1", "output_eu")


def test_tfs_sem_output_eu_e_valido_com_dict_vazio():
    graph = _graph(_tfs())
    node = parse_graph(graph).node("t1")
    assert node.config.output_eu == {}


# --------------------------------------------------------------------------------------
# fora do escopo — só script e tfs declaram output_eu
# --------------------------------------------------------------------------------------


def test_opc_read_rejeita_output_eu_como_chave_desconhecida():
    graph = _graph(_node("r1", "opc_read", 1, tag_id=1, output_eu={"out": "C"}))
    assert has(parse_errors(graph), "r1", "output_eu")


# --------------------------------------------------------------------------------------
# round-trip — a chave sobrevive a parse_graph
# --------------------------------------------------------------------------------------


def test_output_eu_sobrevive_ao_parse_graph():
    graph = _graph(_script(n_outputs=1, output_eu={"OUT1": "t/h"}))
    node = parse_graph(graph).node("s1")
    assert node.functional_config()["output_eu"] == {"OUT1": "t/h"}
