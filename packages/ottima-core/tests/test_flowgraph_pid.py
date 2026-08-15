"""Mesa de casos do bloco PID no `graph_json` (RF-551..554, ADR-031).

Isolado de `test_flowgraph.py`/`test_flowgraph_filtros.py` pelo mesmo motivo do
`test_flowgraph_fuzzy.py`: bloco novo, tabela de casos própria — cada mutação deste bloco é
um caso de outro requisito (forma ISA, sinal de `kc`, limites nulos, portas `pv`/`sp`).
"""

import pytest

from ottima_core.flowgraph import GraphParseError, PidConfig, TagRef, parse_graph, validate_graph

TS = 1.0


def _node(node_id: str, node_type: str, exec_order: int, **data: object) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, "label": "", **data},
    }


def _pid(node_id: str = "p1", *, exec_order: int = 2, **config: object) -> dict:
    defaults = {
        "kc": 2.0,
        "ti_seconds": 5.0,
        "td_seconds": 1.0,
        "setpoint": 50.0,
        "output_min": 0.0,
        "output_max": 100.0,
        "auto_mode": True,
        "proportional_on_measurement": False,
        "differential_on_measurement": True,
        "starting_output": 0.0,
    }
    return _node(node_id, "pid", exec_order, **(defaults | config))


def _leitura(node_id: str = "r1", *, exec_order: int = 1, tag_id: int = 1) -> dict:
    return _node(node_id, "opc_read", exec_order, tag_id=tag_id)


def _aresta(source: str, target: str, *, edge_id: str = "e1", target_handle: str = "pv") -> dict:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "sourceHandle": "out",
        "targetHandle": target_handle,
    }


def _graph(*nodes: dict, edges: list[dict] | None = None) -> dict:
    return {"nodes": list(nodes), "edges": [] if edges is None else edges}


def _ligado(pid_node: dict) -> dict:
    """Leitura -> pv do PID: só `pv` é obrigatória (RF-552); o caso válido liga só ela."""
    return _graph(_leitura(), pid_node, edges=[_aresta("r1", pid_node["id"])])


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
# parse_graph — forma da config (PidConfig)
# --------------------------------------------------------------------------------------


def test_pid_parseia_com_config_tipada():
    node = parse_graph(_ligado(_pid())).node("p1")
    assert isinstance(node.config, PidConfig)
    assert node.config.kc == 2.0
    assert node.config.ti_seconds == 5.0
    assert node.config.td_seconds == 1.0
    assert node.config.setpoint == 50.0
    assert node.config.output_min == 0.0
    assert node.config.output_max == 100.0
    assert node.config.auto_mode is True
    assert node.config.proportional_on_measurement is False
    assert node.config.differential_on_measurement is True
    assert node.config.starting_output == 0.0


def test_pid_aceita_kc_negativo():
    """`kc < 0` é ação reversa, sinal legítimo (RF-551) — prova que `pid` não caiu em
    `_FILTER_KEYS`, cujo mapa `bool` não sabe expressar sinal livre."""
    node = parse_graph(_ligado(_pid(kc=-2.0))).node("p1")
    assert node.config.kc == -2.0


@pytest.mark.parametrize("valor", [float("inf"), float("nan"), "2.0", None, True])
def test_pid_reprova_kc_nao_finito(valor: object):
    assert has(parse_errors(_ligado(_pid(kc=valor))), "p1", "kc")


@pytest.mark.parametrize("valor", [float("inf"), float("nan"), "50.0", None, True])
def test_pid_reprova_setpoint_nao_finito(valor: object):
    assert has(parse_errors(_ligado(_pid(setpoint=valor))), "p1", "setpoint")


@pytest.mark.parametrize("valor", [float("inf"), float("nan"), "0.0", None, True])
def test_pid_reprova_starting_output_nao_finito(valor: object):
    assert has(parse_errors(_ligado(_pid(starting_output=valor))), "p1", "starting_output")


@pytest.mark.parametrize("campo", ["ti_seconds", "td_seconds"])
@pytest.mark.parametrize("valor", [float("inf"), float("nan"), "5.0", None, True])
def test_pid_reprova_ti_td_nao_finito(campo: str, valor: object):
    assert has(parse_errors(_ligado(_pid(**{campo: valor}))), "p1", campo)


@pytest.mark.parametrize("campo", ["ti_seconds", "td_seconds"])
def test_pid_reprova_ti_td_negativo(campo: str):
    """`ti_seconds`/`td_seconds` só desligam a ação em zero (RF-551); negativo é erro de
    sinal, mensagem distinta de 'não finito' (mesmo padrão de `_parse_filter_config`)."""
    errors = parse_errors(_ligado(_pid(**{campo: -1.0})))
    assert has(errors, "p1", campo, "negativo")


def test_pid_aceita_ti_e_td_zero():
    """`ti_seconds = 0` desliga a ação integral; `td_seconds = 0` desliga a derivativa —
    ambas constantes legítimas (RF-551), não erro."""
    node = parse_graph(_ligado(_pid(ti_seconds=0.0, td_seconds=0.0))).node("p1")
    assert (node.config.ti_seconds, node.config.td_seconds) == (0.0, 0.0)


@pytest.mark.parametrize("campo", ["output_min", "output_max"])
def test_pid_aceita_limite_none(campo: str):
    node = parse_graph(_ligado(_pid(**{campo: None}))).node("p1")
    assert getattr(node.config, campo) is None


@pytest.mark.parametrize("campo", ["output_min", "output_max"])
@pytest.mark.parametrize("valor", [float("inf"), float("nan"), "0.0", True])
def test_pid_reprova_limite_invalido(campo: str, valor: object):
    assert has(parse_errors(_ligado(_pid(**{campo: valor}))), "p1", campo)


def test_pid_reprova_output_min_maior_que_output_max():
    graph = _ligado(_pid(output_min=100.0, output_max=0.0))
    assert has(parse_errors(graph), "p1", "output_min")


def test_pid_reprova_limites_iguais():
    """Limites iguais fixam a saída — erro de config, não clamp silencioso (mesma filosofia
    do descasamento de portas do Fuzzy, ADR-029)."""
    graph = _ligado(_pid(output_min=50.0, output_max=50.0))
    assert has(parse_errors(graph), "p1", "output_min")


def test_pid_aceita_apenas_um_limite():
    """Regra cruzada só vale quando os DOIS limites estão presentes."""
    node = parse_graph(_ligado(_pid(output_min=10.0, output_max=None))).node("p1")
    assert (node.config.output_min, node.config.output_max) == (10.0, None)


def test_pid_reprova_starting_output_fora_dos_limites():
    graph = _ligado(_pid(output_min=0.0, output_max=10.0, starting_output=20.0))
    assert has(parse_errors(graph), "p1", "starting_output")


def test_pid_aceita_starting_output_no_limite():
    """Limite inclusivo dos dois lados."""
    graph = _ligado(_pid(output_min=0.0, output_max=10.0, starting_output=10.0))
    node = parse_graph(graph).node("p1")
    assert node.config.starting_output == 10.0


@pytest.mark.parametrize(
    "campo", ["auto_mode", "proportional_on_measurement", "differential_on_measurement"]
)
@pytest.mark.parametrize("valor", [1, 0, "true", "false", None, 1.0])
def test_pid_reprova_booleano_invalido(campo: str, valor: object):
    """`bool` é subclasse de `int`: só `isinstance(v, bool)` distingue os dois — `1`/`0`
    numéricos não colam como booleano aqui."""
    assert has(parse_errors(_ligado(_pid(**{campo: valor}))), "p1", campo)


def test_pid_usa_defaults_dos_booleanos_quando_ausentes():
    graph = _ligado(_pid())
    del graph["nodes"][1]["data"]["auto_mode"]
    del graph["nodes"][1]["data"]["proportional_on_measurement"]
    del graph["nodes"][1]["data"]["differential_on_measurement"]
    node = parse_graph(graph).node("p1")
    assert node.config.auto_mode is True
    assert node.config.proportional_on_measurement is False
    assert node.config.differential_on_measurement is True


def test_pid_reprova_chave_desconhecida():
    """Mesma regra de todo bloco (`_parse_node`): chave extra em `data` é bug de versão."""
    graph = _ligado(_pid(kp=1.0))
    assert has(parse_errors(graph), "kp")


def test_pid_acumula_multiplos_erros():
    """Nunca curto-circuita: `kc` inválido e `ti_seconds` negativo reportam os dois."""
    errors = parse_errors(_ligado(_pid(kc=float("nan"), ti_seconds=-1.0)))
    assert has(errors, "p1", "kc")
    assert has(errors, "p1", "ti_seconds")


# --------------------------------------------------------------------------------------
# identidade funcional (hot-swap, ADR-011/024)
# --------------------------------------------------------------------------------------


def test_identidade_funcional_do_pid_inclui_os_dez_campos():
    config = parse_graph(_ligado(_pid())).node("p1").functional_config()
    assert set(config) == {
        "type",
        "kc",
        "ti_seconds",
        "td_seconds",
        "setpoint",
        "output_min",
        "output_max",
        "auto_mode",
        "proportional_on_measurement",
        "differential_on_measurement",
        "starting_output",
    }


def test_identidade_funcional_do_pid_muda_com_kc():
    antes = parse_graph(_ligado(_pid())).node("p1").functional_config()
    depois = parse_graph(_ligado(_pid(kc=3.0))).node("p1").functional_config()
    assert antes != depois


def test_identidade_funcional_do_pid_ignora_rotulo_e_ordem():
    antes = parse_graph(_ligado(_pid())).node("p1").functional_config()
    graph = _ligado(_pid(exec_order=9))
    graph["nodes"][1]["data"]["label"] = "outro rótulo"
    depois = parse_graph(graph).node("p1").functional_config()
    assert antes == depois


# --------------------------------------------------------------------------------------
# validate_graph — portas, obrigatoriedade e tipo
# --------------------------------------------------------------------------------------


def test_pid_ligado_apenas_a_pv_e_valido():
    assert errors_of(_ligado(_pid())) == []


def test_pv_do_pid_e_obrigatoria_sp_nao():
    """RF-552: sem `pv` nem `sp` ligadas, só `pv` é reportada como obrigatória."""
    graph = _graph(_leitura(), _pid())
    errors = errors_of(graph)
    assert has(errors, "p1", "'pv'", "obrigatória")
    assert not has(errors, "p1", "'sp'", "obrigatória")


def test_pid_aceita_sp_conectada_alem_de_pv():
    graph = _graph(
        _leitura("r1", exec_order=1, tag_id=1),
        _leitura("r2", exec_order=2, tag_id=1),
        _pid(exec_order=3),
        edges=[
            _aresta("r1", "p1", edge_id="e1", target_handle="pv"),
            _aresta("r2", "p1", edge_id="e2", target_handle="sp"),
        ],
    )
    assert errors_of(graph) == []


def test_pid_recusa_handle_de_entrada_inexistente():
    graph = _ligado(_pid())
    graph["edges"][0]["targetHandle"] = "in"
    assert has(errors_of(graph), "targetHandle", "in")


def test_pid_recusa_handle_de_saida_inexistente():
    """Saída única é `out`; ligar por `y1` é 422 antes de virar aresta pendurada."""
    graph = _ligado(_pid())
    graph["nodes"].append(_node("w1", "opc_write", 3, tag_id=1))
    graph["edges"].append(
        {
            "id": "e2",
            "source": "p1",
            "target": "w1",
            "sourceHandle": "y1",
            "targetHandle": "in",
        }
    )
    assert has(errors_of(graph), "sourceHandle", "y1")


def test_porta_do_pid_e_numerica():
    """Decisão A-5: só o Script é bivalente; tag booleana na entrada do PID é 422."""
    graph = _ligado(_pid())
    graph["nodes"][0]["data"]["tag_id"] = 2
    assert has(errors_of(graph), "booleana")


# --------------------------------------------------------------------------------------
# Ganhos derivados da conversão ISA (ADR-031)
# --------------------------------------------------------------------------------------


def test_pid_reprova_ti_que_estoura_o_ganho_integral():
    """`ti_seconds` denormal passa campo a campo, mas `Ki = kc/ti` vira `inf`.

    Sem esta checagem o save aceitaria a config e o `_integral` do simple-pid ficaria
    envenenado com `inf`/`nan` para sempre — malha presa em `ok=False`, com um único
    `write_suppressed` no histórico e silêncio depois.
    """
    assert has(parse_errors(_ligado(_pid(kc=1.0, ti_seconds=1e-320))), "ganho integral")


def test_pid_reprova_td_que_estoura_o_ganho_derivativo():
    assert has(parse_errors(_ligado(_pid(kc=1e300, td_seconds=1e300))), "ganho derivativo")


def test_pid_aceita_ti_pequeno_que_ainda_cabe_em_float():
    """O teto é o overflow, não um mínimo arbitrário: Ki grande porém finito é decisão
    de sintonia do engenheiro, não erro de config."""
    graph = _ligado(_pid(kc=1.0, ti_seconds=1e-6))
    assert parse_graph(graph).node("p1").config.ti_seconds == 1e-6
    assert errors_of(graph) == []
