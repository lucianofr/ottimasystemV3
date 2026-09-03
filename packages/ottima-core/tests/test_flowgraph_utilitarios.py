"""Mesa de casos dos blocos utilitários SCALER e INTEGRATOR no `graph_json`.

Mesma disciplina dos blocos de filtro (`test_flowgraph_filtros.py`): parse garante a FORMA
(escalares finitos, chaves exatas) e `validate_graph` garante portas, obrigatoriedade e
tipo numérico (decisão A-5).

- **Scaler**: 1 entrada (`in`, obrigatória), 1 saída (`out`), config
  `in_min`/`in_max`/`out_min`/`out_max`. `in_max > in_min` (divisor); a faixa de saída
  pode ser invertida (`out_max < out_min` é ação reversa legítima).
- **Integrator**: entradas `in` (obrigatória) e `reset` (opcional), saída `out`, config
  `time_base` ∈ {"s", "min", "h"}.
"""

import pytest

from ottima_core.flowgraph import (
    GraphParseError,
    IntegratorConfig,
    ScalerConfig,
    TagRef,
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


def _scaler(node_id: str = "s1", *, exec_order: int = 2, **config: object) -> dict:
    defaults = {"in_min": 0.0, "in_max": 100.0, "out_min": 4.0, "out_max": 20.0}
    return _node(node_id, "scaler", exec_order, **(defaults | config))


def _integrator(node_id: str = "i1", *, exec_order: int = 2, **config: object) -> dict:
    return _node(node_id, "integrator", exec_order, **({"time_base": "min"} | config))


def _leitura(node_id: str = "r1", *, exec_order: int = 1, tag_id: int = 1) -> dict:
    return _node(node_id, "opc_read", exec_order, tag_id=tag_id)


def _aresta(source: str, target: str, target_handle: str = "in") -> dict:
    return {
        "id": f"{source}-{target}-{target_handle}",
        "source": source,
        "sourceHandle": "out",
        "target": target,
        "targetHandle": target_handle,
    }


def _graph(*nodes: dict, edges: list[dict] | None = None) -> dict:
    return {"nodes": list(nodes), "edges": [] if edges is None else edges}


def _ligado(bloco: dict) -> dict:
    return _graph(_leitura(), bloco, edges=[_aresta("r1", bloco["id"])])


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
# parse_graph — forma da config
# --------------------------------------------------------------------------------------


def test_scaler_parseia_com_config_tipada():
    node = parse_graph(_ligado(_scaler())).node("s1")

    assert isinstance(node.config, ScalerConfig)
    assert node.config.in_min == 0.0
    assert node.config.in_max == 100.0
    assert node.config.out_min == 4.0
    assert node.config.out_max == 20.0


def test_integrator_parseia_com_config_tipada():
    node = parse_graph(_ligado(_integrator())).node("i1")

    assert isinstance(node.config, IntegratorConfig)
    assert node.config.time_base == "min"


@pytest.mark.parametrize("campo", ["in_min", "in_max", "out_min", "out_max"])
@pytest.mark.parametrize("valor", [float("inf"), float("nan"), "5", None, True])
def test_scaler_reprova_escala_invalida(campo: str, valor: object):
    assert has(parse_errors(_ligado(_scaler(**{campo: valor}))), "s1", campo)


@pytest.mark.parametrize("campo", ["in_min", "in_max", "out_min", "out_max"])
def test_scaler_reprova_campo_ausente(campo: str):
    config = {"in_min": 0.0, "in_max": 100.0, "out_min": 4.0, "out_max": 20.0}
    del config[campo]
    assert has(parse_errors(_ligado(_node("s1", "scaler", 2, **config))), "s1", campo)


@pytest.mark.parametrize("in_min,in_max", [(100.0, 100.0), (100.0, 0.0)])
def test_scaler_reprova_faixa_de_entrada_degenerada(in_min: float, in_max: float):
    """`in_max <= in_min` zeraria ou inverteria o divisor da proporcionalidade."""
    assert has(parse_errors(_ligado(_scaler(in_min=in_min, in_max=in_max))), "s1", "in_max")


def test_scaler_aceita_faixa_de_saida_invertida():
    """`out_max < out_min` é ação reversa legítima (ex.: 4-20 mA → 100-0 %)."""
    node = parse_graph(_ligado(_scaler(out_min=100.0, out_max=0.0))).node("s1")

    assert node.config.out_max == 0.0


def test_scaler_reprova_ganho_derivado_nao_finito():
    """Faixas patológicas transbordam a divisão do ganho — o bloco emitiria ±inf com ok=True."""
    assert has(
        parse_errors(_ligado(_scaler(in_min=0.0, in_max=1e-320, out_min=0.0, out_max=1.0))),
        "s1",
        "ganho",
    )


@pytest.mark.parametrize("base", ["s", "min", "h"])
def test_integrator_aceita_as_tres_bases(base: str):
    node = parse_graph(_ligado(_integrator(time_base=base))).node("i1")

    assert node.config.time_base == base


@pytest.mark.parametrize("valor", ["segundo", "ms", "", 1, 1.0, None, True])
def test_integrator_reprova_base_invalida(valor: object):
    assert has(parse_errors(_ligado(_integrator(time_base=valor))), "i1", "time_base")


def test_integrator_reprova_base_ausente():
    assert has(parse_errors(_ligado(_node("i1", "integrator", 2))), "i1", "time_base")


@pytest.mark.parametrize(
    ("bloco", "extra"),
    [(_scaler, "ganho"), (_integrator, "in_min")],
)
def test_utilitarios_reprovam_chave_desconhecida(bloco, extra: str):
    """Mesma regra de todo bloco (`_parse_node`): chave extra em `data` é bug de versão."""
    assert has(parse_errors(_ligado(bloco(**{extra: 1.0}))), extra)


# --------------------------------------------------------------------------------------
# identidade funcional (hot-swap, ADR-011/024)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("bloco", [_scaler, _integrator])
def test_identidade_funcional_ignora_rotulo_e_ordem(bloco):
    antes = parse_graph(_ligado(bloco())).node(bloco()["id"]).functional_config()

    graph = _ligado(bloco())
    graph["nodes"][1]["data"]["label"] = "Totalizador da vazão"
    graph["nodes"][1]["data"]["exec_order"] = 9
    depois = parse_graph(graph).node(bloco()["id"]).functional_config()

    assert antes == depois


def test_identidade_funcional_do_scaler_muda_com_a_escala():
    antes = parse_graph(_ligado(_scaler())).node("s1").functional_config()
    depois = parse_graph(_ligado(_scaler(out_max=10.0))).node("s1").functional_config()

    assert antes != depois


# --------------------------------------------------------------------------------------
# validate_graph — portas, obrigatoriedade e tipo
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("bloco", [_scaler, _integrator])
def test_bloco_ligado_a_leitura_e_valido(bloco):
    assert errors_of(_ligado(bloco())) == []


@pytest.mark.parametrize("bloco", [_scaler, _integrator])
def test_entrada_in_e_obrigatoria(bloco):
    graph = _graph(_leitura(), bloco())
    assert has(errors_of(graph), bloco()["id"], "'in'", "obrigatória")


def test_reset_do_integrator_e_opcional():
    """Sem aresta em `reset` o totalizador simplesmente nunca zera pela porta."""
    assert errors_of(_graph(_leitura(), _integrator())) != []
    assert not has(errors_of(_ligado(_integrator())), "i1", "reset")


def test_integrator_aceita_aresta_no_reset():
    graph = _ligado(_integrator())
    graph["nodes"].append(_leitura("r2", exec_order=3, tag_id=1))
    graph["edges"].append(_aresta("r2", "i1", "reset"))

    assert errors_of(graph) == []


@pytest.mark.parametrize("bloco", [_scaler, _integrator])
def test_recusa_handle_de_entrada_inexistente(bloco):
    graph = _ligado(bloco())
    graph["edges"][0]["targetHandle"] = "u1"
    assert has(errors_of(graph), "targetHandle", "u1")


@pytest.mark.parametrize("bloco", [_scaler, _integrator])
def test_recusa_handle_de_saida_inexistente(bloco):
    graph = _ligado(bloco())
    graph["edges"][0]["sourceHandle"] = "y1"
    assert has(errors_of(graph), "sourceHandle", "y1")


@pytest.mark.parametrize("bloco", [_scaler, _integrator])
def test_portas_sao_numericas(bloco):
    """Decisão A-5: só o Script é bivalente; tag booleana na entrada é 422."""
    graph = _ligado(bloco())
    tags = {1: TagRef(id=1, conn_id=1, direction="r", data_type="bool")}

    assert has(validate_graph(parse_graph(graph), tags, TS).errors, "booleana")
