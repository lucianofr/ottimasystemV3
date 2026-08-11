"""Mesa de casos dos blocos de filtro no `graph_json` (RF-531/532/533, ADR-026).

Isolado de `test_flowgraph.py` (que cobre o resto de `parse_graph`/`validate_graph`) pelo
mesmo motivo de `test_flowgraph_parse.py`: o grafo de referência de lá tem os cinco blocos
originais e cada mutação sua é um caso de outro requisito.
"""

import pytest

from ottima_core.flowgraph import (
    FirstOrderConfig,
    GraphParseError,
    KalmanConfig,
    TagRef,
    parse_graph,
    validate_graph,
)

TS = 1.0


def _node(node_id: str, node_type: str, exec_order: int, **data: object) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, "label": "", **data},
    }


def _first_order(node_id: str = "f1", *, exec_order: int = 2, **config: object) -> dict:
    return _node(node_id, "first_order", exec_order, **({"tau": 5.0} | config))


def _kalman(node_id: str = "k1", *, exec_order: int = 2, **config: object) -> dict:
    defaults = {"measurement_noise": 0.5, "process_noise": 0.05}
    return _node(node_id, "kalman", exec_order, **(defaults | config))


def _leitura(node_id: str = "r1", *, exec_order: int = 1, tag_id: int = 1) -> dict:
    return _node(node_id, "opc_read", exec_order, tag_id=tag_id)


def _aresta(source: str, target: str) -> dict:
    return {
        "id": f"e-{source}-{target}",
        "source": source,
        "target": target,
        "sourceHandle": "out",
        "targetHandle": "in",
    }


def _graph(*nodes: dict, edges: list[dict] | None = None) -> dict:
    return {"nodes": list(nodes), "edges": [] if edges is None else edges}


def _ligado(filtro: dict) -> dict:
    """Leitura -> filtro: a entrada `in` é obrigatória (RF-531), então o caso válido a liga."""
    return _graph(_leitura(), filtro, edges=[_aresta("r1", filtro["id"])])


def _tags() -> dict[int, TagRef]:
    return {
        1: TagRef(id=1, conn_id=1, direction="r", data_type="float"),
        2: TagRef(id=2, conn_id=1, direction="r", data_type="bool"),
    }


def parse_errors(graph: dict) -> list[str]:
    with pytest.raises(GraphParseError) as exc:
        parse_graph(graph)
    return exc.value.errors


def errors_of(graph: dict, ts_seconds: float = TS) -> list[str]:
    return validate_graph(parse_graph(graph), _tags(), ts_seconds).errors


def has(messages: list[str], *fragments: str) -> bool:
    return any(all(fragment in message for fragment in fragments) for message in messages)


# --------------------------------------------------------------------------------------
# parse_graph — forma da config
# --------------------------------------------------------------------------------------


def test_first_order_parseia_com_config_tipada():
    node = parse_graph(_ligado(_first_order())).node("f1")

    assert isinstance(node.config, FirstOrderConfig)
    assert node.config.tau == 5.0


def test_kalman_parseia_com_config_tipada():
    node = parse_graph(_ligado(_kalman())).node("k1")

    assert isinstance(node.config, KalmanConfig)
    assert node.config.measurement_noise == 0.5
    assert node.config.process_noise == 0.05


def test_first_order_aceita_tau_zero():
    """`tau = 0` é passagem direta (ADR-026), constante legítima — não é erro."""
    node = parse_graph(_ligado(_first_order(tau=0.0))).node("f1")

    assert node.config.tau == 0.0


def test_kalman_aceita_process_noise_zero():
    """`process_noise = 0` modela valor verdadeiro constante; o ganho tende a zero."""
    node = parse_graph(_ligado(_kalman(process_noise=0.0))).node("k1")

    assert node.config.process_noise == 0.0


@pytest.mark.parametrize("valor", [-1.0, float("inf"), float("nan"), "5", None, True])
def test_first_order_reprova_tau_invalido(valor: object):
    assert has(parse_errors(_ligado(_first_order(tau=valor))), "f1", "tau")


def test_first_order_reprova_tau_ausente():
    graph = _graph(_leitura(), _node("f1", "first_order", 2))
    assert has(parse_errors(graph), "f1", "tau")


@pytest.mark.parametrize("valor", [0.0, -0.5, float("inf"), float("nan"), "0.5", None, True])
def test_kalman_reprova_measurement_noise_invalido(valor: object):
    """Zero também reprova: `measurement_noise` é o divisor do ganho (ADR-026).

    `True` entra na lista porque `bool` é subclasse de `int` em Python: sem o guarda de
    `_is_number`, `measurement_noise=True` viraria um ruído de 1.0 em silêncio.
    """
    errors = parse_errors(_ligado(_kalman(measurement_noise=valor)))
    assert has(errors, "k1", "measurement_noise")


@pytest.mark.parametrize("valor", [-0.5, float("inf"), float("nan"), "0.05", None, True])
def test_kalman_reprova_process_noise_invalido(valor: object):
    assert has(parse_errors(_ligado(_kalman(process_noise=valor))), "k1", "process_noise")


def test_kalman_reprova_campo_ausente():
    graph = _graph(_leitura(), _node("k1", "kalman", 2, measurement_noise=0.5))
    assert has(parse_errors(graph), "k1", "process_noise")


@pytest.mark.parametrize(
    ("filtro", "extra"),
    [(_first_order, "q"), (_kalman, "tau")],
)
def test_filtros_reprovam_chave_desconhecida(filtro, extra: str):
    """Mesma regra de todo bloco (`_parse_node`): chave extra em `data` é bug de versão."""
    graph = _graph(_leitura(), filtro(**{extra: 1.0}))
    assert has(parse_errors(graph), extra)


# --------------------------------------------------------------------------------------
# identidade funcional (hot-swap, ADR-011/024)
# --------------------------------------------------------------------------------------


def test_identidade_funcional_do_first_order_ignora_rotulo_e_ordem():
    antes = parse_graph(_ligado(_first_order())).node("f1").functional_config()

    graph = _ligado(_first_order())
    graph["nodes"][1]["data"]["label"] = "Filtro da PV"
    depois = parse_graph(graph).node("f1").functional_config()

    assert antes == depois


def test_identidade_funcional_do_kalman_muda_com_o_ruido():
    antes = parse_graph(_ligado(_kalman())).node("k1").functional_config()
    depois = parse_graph(_ligado(_kalman(measurement_noise=2.0))).node("k1").functional_config()

    assert antes != depois


# --------------------------------------------------------------------------------------
# validate_graph — portas, obrigatoriedade e tipo
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("filtro", [_first_order, _kalman])
def test_filtro_ligado_a_leitura_e_valido(filtro):
    assert errors_of(_ligado(filtro())) == []


@pytest.mark.parametrize("filtro", [_first_order, _kalman])
def test_entrada_do_filtro_e_obrigatoria(filtro):
    graph = _graph(_leitura(), filtro())
    assert has(errors_of(graph), filtro()["id"], "'in'", "obrigatória")


@pytest.mark.parametrize("filtro", [_first_order, _kalman])
def test_filtro_recusa_handle_de_entrada_inexistente(filtro):
    graph = _ligado(filtro())
    graph["edges"][0]["targetHandle"] = "u1"
    assert has(errors_of(graph), "targetHandle", "u1")


@pytest.mark.parametrize("filtro", [_first_order, _kalman])
def test_filtro_recusa_handle_de_saida_inexistente(filtro):
    """Saída única é `out`; ligar por `y1` é 422 antes de virar aresta pendurada."""
    graph = _ligado(filtro())
    graph["nodes"].append(_node("w1", "opc_write", 3, tag_id=1))
    graph["edges"].append(
        {
            "id": "e2",
            "source": filtro()["id"],
            "target": "w1",
            "sourceHandle": "y1",
            "targetHandle": "in",
        }
    )
    assert has(errors_of(graph), "sourceHandle", "y1")


@pytest.mark.parametrize("filtro", [_first_order, _kalman])
def test_porta_do_filtro_e_numerica(filtro):
    """Decisão A-5: só o Script é bivalente; tag booleana na entrada do filtro é 422."""
    graph = _ligado(filtro())
    graph["nodes"][0]["data"]["tag_id"] = 2
    assert has(errors_of(graph), "booleana")
