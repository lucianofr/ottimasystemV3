"""Mesa de casos de `ottima_core.flowgraph` (RF-302/307, ADR-024, spec F3 §5.2).

Cada caso inválido é uma mutação de um campo do grafo válido de referência montado por
`base_graph()`, para que a diferença entre "passa" e "reprova" fique explícita no teste.
"""

import pytest

from ottima_core.flowgraph import (
    GraphParseError,
    ScriptConfig,
    TagRef,
    parse_graph,
    validate_graph,
)

TS = 1.0


def sopdt(**params: float) -> dict:
    """Elemento SOPDT habilitado; `params` sobrescreve os defaults."""
    defaults = {"K": 1.0, "tau1": 10.0, "tau2": 0.0, "theta": 0.0}
    return {"enabled": True, "kind": "sopdt", "params": defaults | params}


def off() -> dict:
    """Elemento SOPDT desabilitado (bem-formado, mas fora da soma da linha)."""
    element = sopdt()
    element["enabled"] = False
    return element


def base_graph() -> dict:
    """Grafo válido de referência: r1 -> s1 -> w1 e r2 -> t1.

    O TFS tem apenas o elemento y1/u1 habilitado, logo `u2` é legalmente desconectada
    (spec §3.4). Os `exec_order` são 1..5 em ordem topológica: zero warnings.
    """
    return {
        "nodes": [
            {
                "id": "r1",
                "type": "opc_read",
                "position": {"x": 0.0, "y": 0.0},
                "data": {"exec_order": 1, "label": "Leitura PV", "tag_id": 1},
            },
            {
                "id": "s1",
                "type": "script",
                "position": {"x": 200.0, "y": 0.0},
                "data": {
                    "exec_order": 2,
                    "n_inputs": 1,
                    "n_outputs": 1,
                    "code": "OUT1 = IN1 * 2",
                },
            },
            {
                "id": "w1",
                "type": "opc_write",
                "position": {"x": 400.0, "y": 0.0},
                "data": {"exec_order": 3, "tag_id": 2},
            },
            {
                "id": "r2",
                "type": "opc_read",
                "position": {"x": 0.0, "y": 200.0},
                "data": {"exec_order": 4, "tag_id": 3},
            },
            {
                "id": "t1",
                "type": "tfs",
                "position": {"x": 200.0, "y": 200.0},
                "data": {"exec_order": 5, "matrix": [[sopdt(), off()], [off(), off()]]},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "r1",
                "target": "s1",
                "sourceHandle": "out",
                "targetHandle": "IN1",
            },
            {
                "id": "e2",
                "source": "s1",
                "target": "w1",
                "sourceHandle": "OUT1",
                "targetHandle": "in",
            },
            {
                "id": "e3",
                "source": "r2",
                "target": "t1",
                "sourceHandle": "out",
                "targetHandle": "u1",
            },
        ],
    }


def base_tags() -> dict[int, TagRef]:
    return {
        1: TagRef(id=1, conn_id=1, direction="r", data_type="float"),
        2: TagRef(id=2, conn_id=1, direction="w", data_type="float"),
        3: TagRef(id=3, conn_id=1, direction="r", data_type="float"),
    }


def node_of(graph: dict, node_id: str) -> dict:
    return next(n for n in graph["nodes"] if n["id"] == node_id)


def edge_of(graph: dict, edge_id: str) -> dict:
    return next(e for e in graph["edges"] if e["id"] == edge_id)


def parse_errors(graph: dict) -> list[str]:
    with pytest.raises(GraphParseError) as exc:
        parse_graph(graph)
    return exc.value.errors


def errors_of(
    graph: dict, tags: dict[int, TagRef] | None = None, ts_seconds: float = TS
) -> list[str]:
    result = validate_graph(parse_graph(graph), base_tags() if tags is None else tags, ts_seconds)
    return result.errors


def has(messages: list[str], *fragments: str) -> bool:
    """Alguma mensagem contém todos os fragmentos."""
    return any(all(fragment in message for fragment in fragments) for message in messages)


# --------------------------------------------------------------------------------------
# parse_graph — forma e tipagem estática
# --------------------------------------------------------------------------------------


def test_grafo_de_referencia_parseia_com_config_tipada():
    graph = parse_graph(base_graph())

    assert [n.id for n in graph.nodes] == ["r1", "s1", "w1", "r2", "t1"]
    assert [e.id for e in graph.edges] == ["e1", "e2", "e3"]

    script = graph.node("s1")
    assert isinstance(script.config, ScriptConfig)
    assert script.config.n_inputs == 1
    assert script.config.code == "OUT1 = IN1 * 2"
    assert script.label == ""  # default quando o editor não manda rótulo
    assert graph.node("r1").label == "Leitura PV"
    assert graph.node("t1").config.matrix[0][0].params.theta == 0.0


def test_grafo_vazio_e_valido():
    """`POST /api/flows` grava `{"nodes": [], "edges": []}` (spec §5.1)."""
    graph = parse_graph({"nodes": [], "edges": []})

    assert graph.nodes == []
    assert validate_graph(graph, {}, TS).errors == []


def test_identidade_funcional_ignora_exec_order_label_e_position():
    """ADR-024/spec §4.1-3: mexer em ordem, rótulo ou posição não reinicia o estado."""
    before = parse_graph(base_graph()).node("s1").functional_config()

    graph = base_graph()
    node_of(graph, "s1")["data"]["exec_order"] = 4
    node_of(graph, "s1")["data"]["label"] = "outro rótulo"
    node_of(graph, "s1")["position"] = {"x": 999.0, "y": 999.0}
    node_of(graph, "r2")["data"]["exec_order"] = 2
    after = parse_graph(graph).node("s1").functional_config()

    assert before == after

    graph = base_graph()
    node_of(graph, "s1")["data"]["code"] = "OUT1 = IN1 * 3"
    assert parse_graph(graph).node("s1").functional_config() != before


# regra 1 — nodes/edges presentes e listas


def test_parse_exige_nodes_e_edges_como_listas():
    errors = parse_errors({"edges": []})
    assert has(errors, "nodes")

    errors = parse_errors({"nodes": [], "edges": {}})
    assert has(errors, "edges")

    errors = parse_errors([])
    assert has(errors, "graph_json")


# regra 2 — ids


def test_parse_rejeita_id_de_no_vazio_ou_ausente():
    graph = base_graph()
    node_of(graph, "r1")["id"] = ""
    assert has(parse_errors(graph), "id")

    graph = base_graph()
    del node_of(graph, "r1")["id"]
    assert has(parse_errors(graph), "id")


def test_parse_rejeita_id_de_no_duplicado():
    graph = base_graph()
    node_of(graph, "r2")["id"] = "r1"
    assert has(parse_errors(graph), "duplicado", "r1")


def test_parse_rejeita_id_de_aresta_duplicado():
    graph = base_graph()
    edge_of(graph, "e2")["id"] = "e1"
    assert has(parse_errors(graph), "duplicado", "e1")


# regra 3 — tipos de nó


def test_parse_rejeita_tipo_desconhecido():
    graph = base_graph()
    node_of(graph, "r1")["type"] = "pid"
    errors = parse_errors(graph)
    assert has(errors, "r1", "pid")


def test_parse_rejeita_bloco_mpc_com_mensagem_propria():
    """Decisão A-1: MPC existe na paleta desabilitado, mas o grafo é 422 na F3."""
    graph = base_graph()
    node_of(graph, "r1")["type"] = "mpc"
    node_of(graph, "r1")["data"] = {"exec_order": 1}
    errors = parse_errors(graph)
    assert has(errors, "r1", "MPC", "F4")
    assert not has(errors, "desconhecido")


# regra 4 — exec_order


def test_parse_exige_exec_order_inteiro_maior_ou_igual_a_um():
    for mutation in (None, 0, -1, "2", 1.5, True):
        graph = base_graph()
        if mutation is None:
            del node_of(graph, "s1")["data"]["exec_order"]
        else:
            node_of(graph, "s1")["data"]["exec_order"] = mutation
        assert has(parse_errors(graph), "s1", "exec_order"), mutation


# regra 5 — config obrigatória e chaves desconhecidas


def test_parse_exige_config_obrigatoria_por_tipo():
    graph = base_graph()
    del node_of(graph, "r1")["data"]["tag_id"]
    assert has(parse_errors(graph), "r1", "tag_id")

    graph = base_graph()
    del node_of(graph, "s1")["data"]["code"]
    assert has(parse_errors(graph), "s1", "code")

    graph = base_graph()
    del node_of(graph, "t1")["data"]["matrix"]
    assert has(parse_errors(graph), "t1", "matrix")


def test_parse_rejeita_chave_desconhecida_em_data():
    graph = base_graph()
    node_of(graph, "r1")["data"]["tag_ids"] = [1, 2]
    assert has(parse_errors(graph), "r1", "tag_ids")


def test_parse_rejeita_tag_id_nao_inteiro():
    graph = base_graph()
    node_of(graph, "r1")["data"]["tag_id"] = "1"
    assert has(parse_errors(graph), "r1", "tag_id")


def test_parse_exige_position_numerica():
    graph = base_graph()
    del node_of(graph, "r1")["position"]
    assert has(parse_errors(graph), "r1", "position")

    graph = base_graph()
    node_of(graph, "r1")["position"] = {"x": "0", "y": 0.0}
    assert has(parse_errors(graph), "r1", "position")


def test_parse_exige_campos_de_aresta():
    for field in ("source", "target", "sourceHandle", "targetHandle"):
        graph = base_graph()
        del edge_of(graph, "e1")[field]
        assert has(parse_errors(graph), "e1", field), field


# regra 6 — tetos estáticos


def test_parse_rejeita_numero_de_portas_do_script_fora_de_0_8():
    for field, value in (("n_inputs", 9), ("n_outputs", 9), ("n_inputs", -1)):
        graph = base_graph()
        node_of(graph, "s1")["data"][field] = value
        assert has(parse_errors(graph), "s1", field), (field, value)


def test_parse_aceita_script_sem_portas():
    graph = base_graph()
    node_of(graph, "s1")["data"]["n_inputs"] = 0
    node_of(graph, "s1")["data"]["n_outputs"] = 0
    graph["edges"] = [e for e in graph["edges"] if e["id"] not in {"e1", "e2"}]
    assert parse_graph(graph).node("s1").config.n_inputs == 0


def test_parse_exige_matriz_2x2_no_tfs():
    graph = base_graph()
    node_of(graph, "t1")["data"]["matrix"] = [[sopdt(), off()]]
    assert has(parse_errors(graph), "t1", "matrix")

    graph = base_graph()
    node_of(graph, "t1")["data"]["matrix"] = [[sopdt()], [off(), off()]]
    assert has(parse_errors(graph), "t1", "matrix")


def test_parse_rejeita_kind_invalido_no_elemento_do_tfs():
    graph = base_graph()
    node_of(graph, "t1")["data"]["matrix"][0][0]["kind"] = "foptd"
    assert has(parse_errors(graph), "t1", "kind")


def test_parse_exige_params_exatos_do_kind():
    graph = base_graph()
    del node_of(graph, "t1")["data"]["matrix"][0][0]["params"]["tau2"]
    assert has(parse_errors(graph), "t1", "tau2")

    graph = base_graph()
    node_of(graph, "t1")["data"]["matrix"][0][0]["params"]["Ki"] = 1.0
    assert has(parse_errors(graph), "t1", "Ki")

    graph = base_graph()
    node_of(graph, "t1")["data"]["matrix"][0][0] = {
        "enabled": True,
        "kind": "iopdt",
        "params": {"Ki": 0.5, "theta": 1.0},
    }
    assert parse_graph(graph).node("t1").config.matrix[0][0].params.Ki == 0.5


def test_parse_rejeita_constantes_de_tempo_negativas_mas_aceita_zero():
    for field in ("tau1", "tau2", "theta"):
        graph = base_graph()
        node_of(graph, "t1")["data"]["matrix"][0][0]["params"][field] = -1.0
        assert has(parse_errors(graph), "t1", field), field

    graph = base_graph()
    node_of(graph, "t1")["data"]["matrix"][0][0]["params"]["tau1"] = 0.0
    assert parse_graph(graph).node("t1").config.matrix[0][0].params.tau1 == 0.0


def test_parse_rejeita_ganho_nao_finito():
    graph = base_graph()
    node_of(graph, "t1")["data"]["matrix"][0][0]["params"]["K"] = float("inf")
    assert has(parse_errors(graph), "t1", "K")

    graph = base_graph()
    node_of(graph, "t1")["data"]["matrix"][0][0]["params"]["theta"] = float("nan")
    assert has(parse_errors(graph), "t1", "theta")


def test_parse_acumula_todos_os_problemas_estruturais():
    graph = base_graph()
    node_of(graph, "r1")["type"] = "pid"
    del node_of(graph, "s1")["data"]["exec_order"]
    errors = parse_errors(graph)

    assert has(errors, "r1", "pid")
    assert has(errors, "s1", "exec_order")


# --------------------------------------------------------------------------------------
# validate_graph — semântica com contexto (tags, Ts, topologia)
# --------------------------------------------------------------------------------------


def test_grafo_de_referencia_sem_erros_nem_warnings():
    result = validate_graph(parse_graph(base_graph()), base_tags(), TS)
    assert result.errors == []
    assert result.warnings == []


# regra 1 — exec_order único e contíguo 1..N


def test_exec_order_duplicado_e_erro():
    graph = base_graph()
    node_of(graph, "r2")["data"]["exec_order"] = 2
    errors = errors_of(graph)
    assert has(errors, "exec_order", "s1", "r2")


def test_exec_order_com_buraco_e_erro():
    graph = base_graph()
    graph["nodes"] = graph["nodes"][:3]
    graph["edges"] = [e for e in graph["edges"] if e["id"] != "e3"]
    node_of(graph, "w1")["data"]["exec_order"] = 4  # 1, 2, 4 com N=3
    errors = errors_of(graph)
    assert has(errors, "exec_order", "1", "3")


# regra 2 — arestas referenciam nós e handles existentes


def test_aresta_com_no_inexistente_e_erro():
    graph = base_graph()
    edge_of(graph, "e1")["source"] = "fantasma"
    errors = errors_of(graph)
    assert has(errors, "e1", "source", "fantasma")

    graph = base_graph()
    edge_of(graph, "e1")["target"] = "fantasma"
    assert has(errors_of(graph), "e1", "target", "fantasma")


def test_handle_inexistente_e_erro():
    graph = base_graph()
    edge_of(graph, "e1")["sourceHandle"] = "out2"
    assert has(errors_of(graph), "e1", "sourceHandle", "out2", "r1")

    graph = base_graph()
    edge_of(graph, "e1")["targetHandle"] = "IN2"  # o script tem n_inputs=1
    assert has(errors_of(graph), "e1", "targetHandle", "IN2", "s1")


def test_handle_de_saida_usado_como_entrada_e_erro():
    graph = base_graph()
    edge_of(graph, "e2")["targetHandle"] = "out"  # w1 não tem porta 'out'
    assert has(errors_of(graph), "e2", "targetHandle", "w1")


# regra 3 — fan-in


def test_duas_arestas_na_mesma_porta_de_entrada_e_erro():
    graph = base_graph()
    graph["edges"].append(
        {
            "id": "e4",
            "source": "r2",
            "target": "s1",
            "sourceHandle": "out",
            "targetHandle": "IN1",
        }
    )
    errors = errors_of(graph)
    assert has(errors, "s1", "IN1", "e1", "e4")


# regra 4 — tipagem de portas (decisão A-5)


def test_read_booleano_em_entrada_numerica_do_tfs_e_recusado():
    graph = base_graph()
    tags = base_tags()
    tags[3] = TagRef(id=3, conn_id=1, direction="r", data_type="bool")
    errors = errors_of(graph, tags)
    assert has(errors, "e3", "r2", "t1")


def test_read_numerico_em_write_booleano_e_recusado():
    graph = base_graph()
    graph["edges"] = [e for e in graph["edges"] if e["id"] != "e2"]
    graph["edges"].append(
        {
            "id": "e4",
            "source": "r1",
            "target": "w1",
            "sourceHandle": "out",
            "targetHandle": "in",
        }
    )
    node_of(graph, "s1")["data"]["n_inputs"] = 0
    node_of(graph, "s1")["data"]["n_outputs"] = 0
    graph["edges"] = [e for e in graph["edges"] if e["id"] != "e1"]
    tags = base_tags()
    tags[2] = TagRef(id=2, conn_id=1, direction="w", data_type="bool")
    errors = errors_of(graph, tags)
    assert has(errors, "e4", "r1", "w1")


def test_saida_de_script_em_write_booleano_e_aceita():
    """Resolução do controlador 3: a bivalência é propriedade da porta do Script."""
    tags = base_tags()
    tags[2] = TagRef(id=2, conn_id=1, direction="w", data_type="bool")
    assert errors_of(base_graph(), tags) == []


def test_read_booleano_em_entrada_de_script_e_aceito():
    tags = base_tags()
    tags[1] = TagRef(id=1, conn_id=1, direction="r", data_type="bool")
    assert errors_of(base_graph(), tags) == []


# regra 5 — ciclos


def test_ciclo_de_dois_nos_e_erro():
    graph = base_graph()
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] in {"s1", "w1"}]
    node_of(graph, "s1")["data"]["exec_order"] = 1
    node_of(graph, "w1")["data"]["exec_order"] = 2
    node_of(graph, "w1")["type"] = "script"
    node_of(graph, "w1")["data"] = {
        "exec_order": 2,
        "n_inputs": 1,
        "n_outputs": 1,
        "code": "OUT1 = IN1",
    }
    graph["edges"] = [
        {
            "id": "e1",
            "source": "s1",
            "target": "w1",
            "sourceHandle": "OUT1",
            "targetHandle": "IN1",
        },
        {
            "id": "e2",
            "source": "w1",
            "target": "s1",
            "sourceHandle": "OUT1",
            "targetHandle": "IN1",
        },
    ]
    errors = errors_of(graph)
    assert has(errors, "ciclo", "s1", "w1")


def test_ciclo_de_tres_nos_e_erro():
    def script_node(node_id: str, order: int) -> dict:
        return {
            "id": node_id,
            "type": "script",
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": order, "n_inputs": 1, "n_outputs": 1, "code": "OUT1 = IN1"},
        }

    def link(edge_id: str, source: str, target: str) -> dict:
        return {
            "id": edge_id,
            "source": source,
            "target": target,
            "sourceHandle": "OUT1",
            "targetHandle": "IN1",
        }

    graph = {
        "nodes": [script_node("a", 1), script_node("b", 2), script_node("c", 3)],
        "edges": [link("e1", "a", "b"), link("e2", "b", "c"), link("e3", "c", "a")],
    }
    errors = errors_of(graph)
    assert has(errors, "ciclo", "a", "b", "c")


# regra 6 — entradas obrigatórias conectadas


def test_entrada_do_write_desconectada_e_erro():
    graph = base_graph()
    graph["edges"] = [e for e in graph["edges"] if e["id"] != "e2"]
    assert has(errors_of(graph), "w1", "in")


def test_entrada_do_script_desconectada_e_erro():
    graph = base_graph()
    graph["edges"] = [e for e in graph["edges"] if e["id"] != "e1"]
    assert has(errors_of(graph), "s1", "IN1")


def test_u2_desconectada_e_valida_quando_a_coluna_2_nao_tem_elemento_habilitado():
    assert errors_of(base_graph()) == []


def test_u2_desconectada_e_erro_quando_a_coluna_2_tem_elemento_habilitado():
    graph = base_graph()
    node_of(graph, "t1")["data"]["matrix"][1][1] = sopdt()
    assert has(errors_of(graph), "t1", "u2")


# regra 7 — integridade de tag


def test_tag_inexistente_e_erro():
    graph = base_graph()
    node_of(graph, "r1")["data"]["tag_id"] = 99
    assert has(errors_of(graph), "r1", "99", "projeto")


def test_tag_com_direcao_trocada_e_erro():
    graph = base_graph()
    node_of(graph, "r1")["data"]["tag_id"] = 2  # tag de escrita num opc_read
    assert has(errors_of(graph), "r1", "2", "direção")

    graph = base_graph()
    node_of(graph, "w1")["data"]["tag_id"] = 3  # tag de leitura num opc_write
    assert has(errors_of(graph), "w1", "3", "direção")


# regra 8 — teto de atraso do TFS


def test_teto_de_atraso_do_tfs_depende_do_ts():
    graph = base_graph()
    node_of(graph, "t1")["data"]["matrix"][0][0]["params"]["theta"] = 4000.0

    # Ts=0,5 s => d = 8000 amostras, acima do teto de 7200.
    assert has(errors_of(graph, ts_seconds=0.5), "t1", "7200")
    # Ts=10 s => d = 400 amostras: o mesmo grafo passa.
    assert errors_of(graph, ts_seconds=10.0) == []


def test_teto_de_atraso_ignora_elemento_desabilitado():
    graph = base_graph()
    node_of(graph, "t1")["data"]["matrix"][1][1]["params"]["theta"] = 4000.0
    assert errors_of(graph, ts_seconds=0.5) == []


def test_ts_invalido_e_erro_de_programacao():
    graph = parse_graph(base_graph())
    with pytest.raises(ValueError, match="ts_seconds"):
        validate_graph(graph, base_tags(), 0.0)


# warnings de inversão de aresta


def test_aresta_invertida_gera_warning_sem_erro():
    graph = base_graph()
    node_of(graph, "r1")["data"]["exec_order"] = 2
    node_of(graph, "s1")["data"]["exec_order"] = 1
    result = validate_graph(parse_graph(graph), base_tags(), TS)

    assert result.errors == []
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert "r1" in warning and "s1" in warning
    assert "2" in warning and "1" in warning
    assert "varredura anterior" in warning


def test_grafo_em_ordem_nao_gera_warning():
    assert validate_graph(parse_graph(base_graph()), base_tags(), TS).warnings == []
