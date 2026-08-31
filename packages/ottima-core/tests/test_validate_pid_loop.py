"""Validacao de save do pid_loop: portas por modo remoto + aresta de retorno (ADR-039 D6)."""

from ottima_core.flowgraph import TagRef, parse_graph, validate_graph

TS = 1.0


def _no(node_id: str, exec_order: int, permitted: list[str]) -> dict:
    return {
        "id": node_id,
        "type": "pid_loop",
        "position": {"x": 0.0, "y": 0.0},
        "data": {
            "exec_order": exec_order,
            "sp_hi_lim": 100.0,
            "sp_lo_lim": 0.0,
            "kc": 2.0,
            "permitted": permitted,
        },
    }


def _tag_read(node_id: str, exec_order: int, tag_id: int) -> dict:
    return {
        "id": node_id,
        "type": "opc_read",
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, "tag_id": tag_id},
    }


def _aresta(edge_id: str, source: str, source_handle: str, target: str, target_handle: str) -> dict:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "sourceHandle": source_handle,
        "targetHandle": target_handle,
    }


def _resultado(nodes: list[dict], edges: list[dict], tags: dict[int, TagRef] | None = None):
    return validate_graph(parse_graph({"nodes": nodes, "edges": edges}), tags or {}, TS)


def test_cas_em_permitted_sem_cas_in_ligado_e_erro() -> None:
    nodes = [_tag_read("pv", 1, 1), _no("fic", 2, ["oos", "man", "auto", "cas"])]
    edges = [_aresta("e1", "pv", "out", "fic", "in")]
    tags = {1: TagRef(id=1, conn_id=1, direction="r", data_type="float")}
    resultado = _resultado(nodes, edges, tags)
    assert any("cas" in e and "cas_in" in e for e in resultado.errors)


def test_cascata_com_aresta_de_retorno_nao_e_ciclo() -> None:
    nodes = [
        _tag_read("pv_lic", 1, 1),
        _tag_read("pv_fic", 2, 2),
        _no("lic", 3, ["oos", "man", "auto"]),
        _no("fic", 4, ["oos", "man", "auto", "cas"]),
    ]
    edges = [
        _aresta("e1", "pv_lic", "out", "lic", "in"),
        _aresta("e2", "pv_fic", "out", "fic", "in"),
        _aresta("e3", "lic", "out", "fic", "cas_in"),
        _aresta("e4", "fic", "bkcal_out", "lic", "bkcal_in"),  # fecha ciclo no grafo bruto
    ]
    tags = {
        1: TagRef(id=1, conn_id=1, direction="r", data_type="float"),
        2: TagRef(id=2, conn_id=1, direction="r", data_type="float"),
    }
    resultado = _resultado(nodes, edges, tags)
    assert resultado.errors == []  # aresta de retorno isenta da deteccao de ciclo
    # e isenta do aviso de inversao (retorno vai contra o fluxo de proposito)
    assert not any("bkcal_in" in w for w in resultado.warnings)


def test_ciclo_por_aresta_comum_continua_proibido() -> None:
    nodes = [
        _tag_read("pv_a", 1, 1),
        _tag_read("pv_b", 2, 2),
        _no("a", 3, ["oos", "man", "auto", "cas"]),
        _no("b", 4, ["oos", "man", "auto", "cas"]),
    ]
    edges = [
        _aresta("e1", "pv_a", "out", "a", "in"),
        _aresta("e2", "pv_b", "out", "b", "in"),
        _aresta("e3", "a", "out", "b", "cas_in"),
        _aresta("e4", "b", "out", "a", "cas_in"),  # ciclo de dados de verdade
    ]
    tags = {
        1: TagRef(id=1, conn_id=1, direction="r", data_type="float"),
        2: TagRef(id=2, conn_id=1, direction="r", data_type="float"),
    }
    resultado = _resultado(nodes, edges, tags)
    assert any("ciclo" in e.lower() for e in resultado.errors)
