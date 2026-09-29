"""Mesa de casos dos blocos de barramento (`bus_publish`/`bus_subscribe`) no `graph_json`.

Mesma disciplina de `test_flowgraph_utilitarios.py`: `parse_graph` garante a FORMA da config
(só a `key`, no charset do ADR-042 D8) e `validate_graph` garante portas, obrigatoriedade,
bivalência (D7) e a unicidade da chave dentro do flow (D5).

- **bus_publish**: 1 entrada (`in`, obrigatória), nenhuma saída.
- **bus_subscribe**: nenhuma entrada, 1 saída (`out`) — bloco-fonte, válido sozinho.
"""

import pytest

from ottima_core.flowgraph import (
    BusKeyConfig,
    GraphParseError,
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
        "position": {"x": 0, "y": 0},
        "data": {"exec_order": exec_order, "label": "", **data},
    }


def _publish(node_id: str = "p1", *, exec_order: int = 2, key: object = "nivel_tanque") -> dict:
    return _node(node_id, "bus_publish", exec_order, key=key)


def _subscribe(node_id: str = "s1", *, exec_order: int = 1, key: object = "nivel_tanque") -> dict:
    return _node(node_id, "bus_subscribe", exec_order, key=key)


def _leitura(node_id: str = "r1", *, exec_order: int = 1, tag_id: int = 1) -> dict:
    return _node(node_id, "opc_read", exec_order, tag_id=tag_id)


def _escrita(node_id: str = "w1", *, exec_order: int = 2, tag_id: int = 3) -> dict:
    return _node(node_id, "opc_write", exec_order, tag_id=tag_id)


def _aresta(
    source: str, target: str, source_handle: str = "out", target_handle: str = "in"
) -> dict:
    return {
        "id": f"{source}-{target}-{target_handle}",
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
    }


def _graph(*nodes: dict, edges: list[dict] | None = None) -> dict:
    return {"nodes": list(nodes), "edges": [] if edges is None else edges}


def _tags() -> dict[int, TagRef]:
    return {
        1: TagRef(id=1, conn_id=1, direction="r", data_type="float"),
        2: TagRef(id=2, conn_id=1, direction="r", data_type="bool"),
        3: TagRef(id=3, conn_id=1, direction="w", data_type="float"),
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


@pytest.mark.parametrize("fabrica", [_publish, _subscribe])
def test_bus_parseia_com_config_tipada(fabrica):
    """Os dois tipos compartilham `BusKeyConfig` — quem discrimina o sentido é `type`."""
    node = parse_graph(_graph(fabrica(exec_order=1))).nodes[0]

    assert isinstance(node.config, BusKeyConfig)
    assert node.config.key == "nivel_tanque"


@pytest.mark.parametrize("fabrica", [_publish, _subscribe])
@pytest.mark.parametrize(
    "key",
    [
        "com ponto.no.meio",  # ponto sai do charset (D8)
        "com espaço",
        "acentuação",
        "glob*",
        "",  # vazia
        "x" * 65,  # acima do teto de 64
    ],
)
def test_bus_reprova_key_fora_do_charset(fabrica, key):
    assert has(parse_errors(_graph(fabrica(exec_order=1, key=key))), "'key'")


@pytest.mark.parametrize("fabrica", [_publish, _subscribe])
def test_bus_reprova_key_nao_string(fabrica):
    assert has(parse_errors(_graph(fabrica(exec_order=1, key=42))), "'key'")


@pytest.mark.parametrize("fabrica", [_publish, _subscribe])
def test_bus_reprova_key_ausente(fabrica):
    node = fabrica(exec_order=1)
    del node["data"]["key"]

    assert has(parse_errors(_graph(node)), "'key'")


def test_bus_reprova_campo_desconhecido():
    """O assinante NÃO tem campo de tempo: a validade vem do `period_s` do payload (D4)."""
    node = _subscribe(exec_order=1)
    node["data"]["max_age_s"] = 5

    assert has(parse_errors(_graph(node)), "max_age_s")


def test_functional_config_muda_com_a_key_e_nao_com_o_rotulo():
    """Identidade funcional do hot-swap (ADR-011): trocar a chave é bloco novo; rótulo, não."""
    base = parse_graph(_graph(_subscribe(exec_order=1))).nodes[0].functional_config()
    outra_key = parse_graph(_graph(_subscribe(exec_order=1, key="outra"))).nodes[0]
    node_rotulado = _subscribe(exec_order=1)
    node_rotulado["data"]["label"] = "Nível do tanque"
    rotulado = parse_graph(_graph(node_rotulado)).nodes[0]

    assert base != outra_key.functional_config()
    assert base == rotulado.functional_config()


# --------------------------------------------------------------------------------------
# validate_graph — portas e obrigatoriedade
# --------------------------------------------------------------------------------------


def test_portas_declaradas_dos_dois_blocos():
    graph = parse_graph(_graph(_subscribe(), _publish()))

    portas = graph_ports(graph)
    assert portas["s1"].inputs == ()
    assert portas["s1"].outputs == ("out",)
    assert portas["p1"].inputs == ("in",)
    assert portas["p1"].outputs == ()


def test_publish_com_entrada_solta_e_reprovado():
    assert has(errors_of(_graph(_publish(exec_order=1))), "'in'", "obrigatória")


def test_subscribe_sozinho_e_valido():
    """Bloco-fonte: assinar sem ninguém a jusante é legítimo (mesmo caso do `constant`)."""
    assert errors_of(_graph(_subscribe(exec_order=1))) == []


def test_par_publish_subscribe_no_mesmo_flow_e_valido():
    """Publicar e assinar a mesma chave no mesmo flow não é ciclo: o caminho é o barramento."""
    graph = _graph(
        _subscribe("s1", exec_order=1),
        _publish("p1", exec_order=2),
        _escrita("w1", exec_order=3),
        edges=[_aresta("s1", "p1"), _aresta("s1", "w1")],
    )

    assert errors_of(graph) == []


def test_bus_aceita_os_dois_lados_bivalentes():
    """D7: tag booleana entra no publicador e a saída do assinante alimenta tag float."""
    graph = _graph(
        _leitura("r1", exec_order=1, tag_id=2),
        _publish("p1", exec_order=2),
        _subscribe("s1", exec_order=3, key="outra"),
        _escrita("w1", exec_order=4),
        edges=[_aresta("r1", "p1"), _aresta("s1", "w1")],
    )

    assert errors_of(graph) == []


# --------------------------------------------------------------------------------------
# validate_graph — unicidade da chave (ADR-042 D5)
# --------------------------------------------------------------------------------------


def test_duas_publicacoes_da_mesma_key_no_flow_reprovam():
    graph = _graph(
        _leitura("r1", exec_order=1),
        _publish("p1", exec_order=2),
        _publish("p2", exec_order=3),
        edges=[_aresta("r1", "p1"), _aresta("r1", "p2")],
    )

    erros = errors_of(graph)
    assert has(erros, "nivel_tanque", "p1", "p2")


def test_publicacoes_de_keys_distintas_no_mesmo_flow_passam():
    graph = _graph(
        _leitura("r1", exec_order=1),
        _publish("p1", exec_order=2),
        _publish("p2", exec_order=3, key="outra"),
        edges=[_aresta("r1", "p1"), _aresta("r1", "p2")],
    )

    assert errors_of(graph) == []


def test_varios_assinantes_da_mesma_key_passam():
    """Um produtor, N consumidores — é o desacoplamento do ADR-002, sem limite."""
    graph = _graph(_subscribe("s1", exec_order=1), _subscribe("s2", exec_order=2))

    assert errors_of(graph) == []
