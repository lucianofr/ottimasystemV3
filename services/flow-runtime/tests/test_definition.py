"""Mesa de casos de `ottima_flow_runtime.definition._conn_ids` (spec F3 §2.2-8, F4 §2.2-8).

Mesa pura: `_conn_ids` só depende do `FlowGraph` tipado e do mapa de tags do projeto, sem
serviços de runtime — mesmo padrão de `test_flowgraph.py`/`test_flowgraph_mpc.py` em
`packages/ottima-core`.
"""

from ottima_core.flowgraph import TagRef, parse_graph
from ottima_flow_runtime.definition import _conn_ids


def opc_read_node(node_id: str, *, tag_id: int, exec_order: int) -> dict:
    return {
        "id": node_id,
        "type": "opc_read",
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, "tag_id": tag_id},
    }


def pid_binding(tag_base: int, *, with_mode_read: bool = True) -> dict:
    binding = {
        "write_tag_id": tag_base,
        "target_mode": "rcas",
        "mode_cmd_tag_id": tag_base + 1,
        "readback_tag_id": tag_base + 2,
        "mode_values": {"auto": 1, "target": 3},
    }
    if with_mode_read:
        binding["mode_read_tag_id"] = tag_base + 3
    return binding


def mv(suffix: str, *, pid: dict | None = None) -> dict:
    node = {
        "id": f"mv_{suffix}",
        "name": f"MV {suffix}",
        "eu": "m3/h",
        "limits": {"min": 0.0, "max": 100.0},
        "du_max": 5.0,
        "initial_value": 0.0,
    }
    if pid is not None:
        node["pid"] = pid
    return node


def mpc_node(node_id: str, *, exec_order: int, mvs: list[dict], input_tag_id: int) -> dict:
    """Bloco `mpc` com 1 CV (par válido com toda MV) — grafo já validado (precondição do
    módulo `definition.py`, que não revalida conteúdo)."""
    cv_id = "cv_a"
    return (
        {
            "id": node_id,
            "type": "mpc",
            "position": {"x": 0.0, "y": 0.0},
            "data": {
                "exec_order": exec_order,
                "name": "MPC teste",
                "multiplier": 1,
                "variables": {
                    "mvs": mvs,
                    "cvs": [
                        {
                            "id": cv_id,
                            "name": "CV a",
                            "eu": "C",
                            "kind": "selfreg",
                            "tss": 30.0,
                            "weight": 1.0,
                            "sp_limits": {"min": 80.0, "max": 120.0},
                        }
                    ],
                    "constraints": [],
                    "dvs": [],
                },
                "models": {
                    cv_id: {
                        m["id"]: {
                            "enabled": True,
                            "params": {"K": 1.2, "tau1": 10.0, "tau2": 2.0, "theta": 15.0},
                        }
                        for m in mvs
                    }
                },
            },
        },
        cv_id,
        input_tag_id,
    )


def edge(edge_id: str, *, source: str, target: str, source_handle: str, target_handle: str) -> dict:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "sourceHandle": source_handle,
        "targetHandle": target_handle,
    }


def test_conn_ids_cobre_opc_read_e_opc_write():
    """Comportamento pré-existente (spec F3 §2.2-8) preservado pela extensão da F4."""
    graph = parse_graph(
        {
            "nodes": [
                opc_read_node("r1", tag_id=1, exec_order=1),
                {
                    "id": "w1",
                    "type": "opc_write",
                    "position": {"x": 0.0, "y": 0.0},
                    "data": {"exec_order": 2, "tag_id": 2},
                },
            ],
            "edges": [],
        }
    )
    tags = {
        1: TagRef(id=1, conn_id=10, direction="r", data_type="float"),
        2: TagRef(id=2, conn_id=20, direction="w", data_type="float"),
    }
    assert _conn_ids(graph, tags) == frozenset({10, 20})


def test_conn_ids_inclui_tags_do_pid_de_mv_do_mpc():
    """Item 3 do Entregável (tarefa 1.2): tags do `pid` do MPC entram na coleta — um
    `comm_failure` na conexão derruba o flow do MPC como derruba um OPC-Read (spec §2.2-8).
    """
    m = mv("a", pid=pid_binding(100))
    node, cv_id, input_tag_id = mpc_node("m1", exec_order=2, mvs=[m], input_tag_id=1)
    graph = parse_graph(
        {
            "nodes": [opc_read_node("r1", tag_id=input_tag_id, exec_order=1), node],
            "edges": [
                edge("e1", source="r1", target="m1", source_handle="out", target_handle=cv_id)
            ],
        }
    )
    tags = {
        1: TagRef(id=1, conn_id=10, direction="r", data_type="float"),
        100: TagRef(id=100, conn_id=30, direction="w", data_type="float"),  # write_tag_id
        101: TagRef(id=101, conn_id=30, direction="w", data_type="float"),  # mode_cmd_tag_id
        102: TagRef(id=102, conn_id=30, direction="r", data_type="float"),  # readback_tag_id
        103: TagRef(id=103, conn_id=30, direction="r", data_type="float"),  # mode_read_tag_id
    }
    assert _conn_ids(graph, tags) == frozenset({10, 30})


def test_conn_ids_ignora_mv_sem_pid():
    """MV "direta" (decisão A-8, sem `pid`) não contribui tag nenhuma à coleta."""
    m = mv("a")  # sem pid
    node, cv_id, input_tag_id = mpc_node("m1", exec_order=2, mvs=[m], input_tag_id=1)
    graph = parse_graph(
        {
            "nodes": [opc_read_node("r1", tag_id=input_tag_id, exec_order=1), node],
            "edges": [
                edge("e1", source="r1", target="m1", source_handle="out", target_handle=cv_id)
            ],
        }
    )
    tags = {1: TagRef(id=1, conn_id=10, direction="r", data_type="float")}
    assert _conn_ids(graph, tags) == frozenset({10})


def test_conn_ids_soma_conexoes_de_varias_mvs_com_pid():
    m1 = mv("a", pid=pid_binding(100, with_mode_read=False))
    m2 = mv("b", pid=pid_binding(200))
    node, cv_id, input_tag_id = mpc_node("m1", exec_order=2, mvs=[m1, m2], input_tag_id=1)
    graph = parse_graph(
        {
            "nodes": [opc_read_node("r1", tag_id=input_tag_id, exec_order=1), node],
            "edges": [
                edge("e1", source="r1", target="m1", source_handle="out", target_handle=cv_id)
            ],
        }
    )
    tags = {
        1: TagRef(id=1, conn_id=10, direction="r", data_type="float"),
        100: TagRef(id=100, conn_id=30, direction="w", data_type="float"),
        101: TagRef(id=101, conn_id=30, direction="w", data_type="float"),
        102: TagRef(id=102, conn_id=30, direction="r", data_type="float"),
        200: TagRef(id=200, conn_id=40, direction="w", data_type="float"),
        201: TagRef(id=201, conn_id=40, direction="w", data_type="float"),
        202: TagRef(id=202, conn_id=40, direction="r", data_type="float"),
        203: TagRef(id=203, conn_id=40, direction="r", data_type="float"),
    }
    assert _conn_ids(graph, tags) == frozenset({10, 30, 40})
