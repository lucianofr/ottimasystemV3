"""Mesa de casos dos blocos de sensor virtual no `graph_json` (RF-301, RF-581, ADR-046).

Os três tipos (`soft_sensor_pls|esn|lstm`) compartilham config e portas — só o método de
inferência muda, e ele mora no runtime —, então cada caso roda parametrizado pelos três.
"""

import pytest

from ottima_core.flowgraph import (
    MAX_SOFT_SENSOR_INPUTS,
    NODE_TYPES,
    SOFT_SENSOR_METHOD,
    SOFT_SENSOR_TYPES,
    GraphParseError,
    NodePorts,
    SoftSensorConfig,
    TagRef,
    graph_ports,
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


def _leitura(node_id: str, *, exec_order: int, tag_id: int = 1) -> dict:
    return _node(node_id, "opc_read", exec_order, tag_id=tag_id)


def _aresta(source: str, target: str, handle: str) -> dict:
    return {
        "id": f"e-{source}-{target}-{handle}",
        "source": source,
        "target": target,
        "sourceHandle": "out",
        "targetHandle": handle,
    }


def _sensor(tipo: str, *, exec_order: int = 3, **config: object) -> dict:
    return _node("ss", tipo, exec_order, **({"n_inputs": 2, "output_eu": "ppm"} | config))


def _graph(*nodes: dict, edges: list[dict] | None = None) -> dict:
    return {"nodes": list(nodes), "edges": [] if edges is None else edges}


def _ligado(tipo: str, **config: object) -> dict:
    """Duas leituras float -> IN1/IN2: o caso válido (toda entrada é obrigatória)."""
    return _graph(
        _leitura("r1", exec_order=1),
        _leitura("r2", exec_order=2),
        _sensor(tipo, **config),
        edges=[_aresta("r1", "ss", "IN1"), _aresta("r2", "ss", "IN2")],
    )


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


@pytest.mark.parametrize("tipo", SOFT_SENSOR_TYPES)
def test_parseia_com_config_tipada(tipo):
    node = parse_graph(_ligado(tipo)).node("ss")
    assert node.type == tipo
    assert node.config == SoftSensorConfig(n_inputs=2, output_eu="ppm")


@pytest.mark.parametrize("tipo", SOFT_SENSOR_TYPES)
def test_output_eu_e_opcional(tipo):
    graph = _ligado(tipo)
    del graph["nodes"][2]["data"]["output_eu"]
    assert parse_graph(graph).node("ss").config.output_eu == ""


@pytest.mark.parametrize("tipo", SOFT_SENSOR_TYPES)
@pytest.mark.parametrize("n", [1, MAX_SOFT_SENSOR_INPUTS])
def test_n_inputs_aceita_limites(tipo, n):
    graph = _graph(_sensor(tipo, n_inputs=n))
    assert parse_graph(graph).node("ss").config.n_inputs == n


@pytest.mark.parametrize("tipo", SOFT_SENSOR_TYPES)
@pytest.mark.parametrize("n", [0, MAX_SOFT_SENSOR_INPUTS + 1])
def test_n_inputs_recusa_fora_do_intervalo(tipo, n):
    erros = parse_errors(_graph(_sensor(tipo, n_inputs=n)))
    assert has(erros, "n_inputs")


@pytest.mark.parametrize("tipo", SOFT_SENSOR_TYPES)
@pytest.mark.parametrize("n", [True, 2.0, "2"])
def test_n_inputs_recusa_nao_inteiro(tipo, n):
    # `True` é `int` em Python e viraria 1 em silêncio; mesma rejeição dos demais utilitários.
    assert has(parse_errors(_graph(_sensor(tipo, n_inputs=n))), "n_inputs")


@pytest.mark.parametrize("tipo", SOFT_SENSOR_TYPES)
def test_chave_desconhecida_e_recusada(tipo):
    erros = parse_errors(_graph(_sensor(tipo, model_id=3)))
    assert has(erros, "chave desconhecida", "model_id")


def test_limite_e_mapa_de_metodos():
    assert MAX_SOFT_SENSOR_INPUTS == 32
    assert SOFT_SENSOR_METHOD == {
        "soft_sensor_pls": "pls",
        "soft_sensor_esn": "esn",
        "soft_sensor_lstm": "lstm",
    }
    assert SOFT_SENSOR_TYPES == tuple(SOFT_SENSOR_METHOD)


def test_tipos_estao_ao_fim_de_node_types():
    assert NODE_TYPES[-3:] == ("soft_sensor_pls", "soft_sensor_esn", "soft_sensor_lstm")


# --------------------------------------------------------------------------------------
# validate_graph — portas e tipos
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("tipo", SOFT_SENSOR_TYPES)
def test_portas_declaradas(tipo):
    grafo = parse_graph(_ligado(tipo))
    assert graph_ports(grafo)["ss"] == NodePorts(inputs=("IN1", "IN2"), outputs=("out",))


@pytest.mark.parametrize("tipo", SOFT_SENSOR_TYPES)
def test_grafo_ligado_e_valido(tipo):
    assert errors_of(_ligado(tipo)) == []


@pytest.mark.parametrize("tipo", SOFT_SENSOR_TYPES)
def test_entrada_desconectada_e_erro(tipo):
    graph = _graph(
        _leitura("r1", exec_order=1),
        _sensor(tipo, exec_order=2),
        edges=[_aresta("r1", "ss", "IN1")],
    )
    assert has(errors_of(graph), "'IN2'", "obrigatória")


@pytest.mark.parametrize("tipo", SOFT_SENSOR_TYPES)
def test_recusa_entrada_booleana(tipo):
    graph = _graph(
        _leitura("r1", exec_order=1, tag_id=2),
        _leitura("r2", exec_order=2),
        _sensor(tipo),
        edges=[_aresta("r1", "ss", "IN1"), _aresta("r2", "ss", "IN2")],
    )
    assert has(errors_of(graph), "booleana", "numérica")


@pytest.mark.parametrize("tipo", SOFT_SENSOR_TYPES)
def test_identidade_funcional_ignora_rotulo_e_ordem(tipo):
    base = parse_graph(_ligado(tipo)).node("ss")
    graph = _ligado(tipo)
    graph["nodes"][2]["data"]["label"] = "outro rótulo"
    graph["nodes"][2]["data"]["exec_order"] = 7
    outro = parse_graph(graph).node("ss")
    assert outro.functional_config() == base.functional_config()
    assert base.functional_config() == {
        "type": tipo,
        "n_inputs": 2,
        "output_eu": "ppm",
    }
