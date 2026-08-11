"""Mesa de casos de `ottima_flow_runtime.definition._conn_ids` (spec F3 §2.2-8, F4 §2.2-8).

Mesa pura: `_conn_ids` só depende do `FlowGraph` tipado e do mapa de tags do projeto, sem
serviços de runtime — mesmo padrão de `test_flowgraph.py`/`test_flowgraph_mpc.py` em
`packages/ottima-core`.
"""

from ottima_core.flowgraph import FlowGraph, TagRef, parse_graph
from ottima_flow_runtime.blocks.mpc import MpcBlock
from ottima_flow_runtime.definition import _conn_ids, _mpc_pid_tag_ids, build_definition
from ottima_flow_runtime.script_pool import ScriptPool


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


def test_mpc_pid_tag_ids_devolve_exatamente_as_tags_do_pid():
    """Reforça `test_conn_ids_soma_conexoes_de_varias_mvs_com_pid`: aquele teste só confere
    o `frozenset` de `conn_id` (passaria mesmo se `_mpc_pid_tag_ids` rendesse um `tag_id`
    estranho que caísse por acaso na mesma conexão) — este confere os `tag_id` exatos que a
    função devolve, MV sem `pid` incluída (não deve render nada dela)."""
    m1 = mv("a", pid=pid_binding(100, with_mode_read=False))
    m2 = mv("b", pid=pid_binding(200))
    m3 = mv("c")  # sem pid — decisão A-8, MV "direta"
    node, _cv_id, _input_tag_id = mpc_node("m1", exec_order=2, mvs=[m1, m2, m3], input_tag_id=1)
    graph = parse_graph({"nodes": [node], "edges": []})

    assert set(_mpc_pid_tag_ids(graph.node("m1"))) == {100, 101, 102, 200, 201, 202, 203}


# --------------------------------------------------------------------------------------
# TD-004 revisado (ADR-009): watchdog virou config do FLOW, não da conexão —
# `_mpc_escreve_sem_watchdog`/`_mv_direta_escreve_sem_watchdog` (a varredura de grafo por
# conexão sem watchdog) morreram; o gate de `MpcBlock.auto_arm_blocked_reason()` é hoje só
# `not watchdog_enabled`, resolvido em `_instantiate`. Os dois testes abaixo cobrem o FIO
# em `build_definition` — o comportamento do bloco em si já tem cobertura direta em
# `test_mpc_block.py::test_auto_arm_blocked_reason_bloqueia_quando_escreve_sem_watchdog`.
# --------------------------------------------------------------------------------------


class _FakeRedis:
    """Duplo do Redis: `build_definition` só usa o cliente dentro de fechamentos
    (`write_opc`/`publish`/`emit_event`) — nenhum dos dois testes abaixo chama `step()`
    nem `host.start()`, então nenhum fechamento dispara."""


class _FakeSnapshot:
    """Duplo do `ValueSnapshot`: `auto_arm_blocked_reason()` decide pelo `host.ready`
    (sempre `False` aqui — o `MpcHost` real nasce em `build_definition`, mas nunca sobe)
    antes de olhar o snapshot; o `.get()` nunca chega a ser chamado."""

    def get(self, tag_id: int) -> None:
        return None


def _grafo_mpc_mv_direta() -> tuple[FlowGraph, dict[int, TagRef]]:
    """Esqueleto mínimo válido: 1 CV (via OPC-Read) + 1 MV direta (sem `pid`, decisão A-8)
    — `_conn_ids`/`_mpc_pid_tag_ids` não entram nesta mesa; só o gate do arme importa."""
    m = mv("a")
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
    return graph, tags


def test_build_definition_com_watchdog_desabilitado_bloqueia_arme_do_mpc():
    """`watchdog_enabled=False` (default do deploy): `_instantiate` passa
    `escreve_sem_watchdog=True` ao `MpcBlock` — TD-004 bloqueia o arme ANTES de qualquer
    outro motivo."""
    graph, tags = _grafo_mpc_mv_direta()

    staged = build_definition(
        graph,
        tags,
        flow_id=1,
        ts_seconds=1.0,
        reuse={},
        redis_client=_FakeRedis(),
        pool=ScriptPool(),
        snapshot=_FakeSnapshot(),
        watchdog_enabled=False,
    )

    block = staged.blocks["m1"][1]
    assert isinstance(block, MpcBlock)
    assert block.auto_arm_blocked_reason() == "write_target_sem_watchdog"


def test_build_definition_com_watchdog_habilitado_nao_bloqueia_por_td_004():
    """`watchdog_enabled=True`: `escreve_sem_watchdog=False` — o motivo TD-004 nunca
    aparece. O host real desta mesa nunca sobe (`MpcHost.start()` não é chamado), então o
    gate cai no próximo motivo (`worker_not_ready`) — o que este teste prova é que NÃO é
    mais o de escrita sem watchdog, o único que `watchdog_enabled` controla."""
    graph, tags = _grafo_mpc_mv_direta()

    staged = build_definition(
        graph,
        tags,
        flow_id=1,
        ts_seconds=1.0,
        reuse={},
        redis_client=_FakeRedis(),
        pool=ScriptPool(),
        snapshot=_FakeSnapshot(),
        watchdog_enabled=True,
    )

    block = staged.blocks["m1"][1]
    assert isinstance(block, MpcBlock)
    assert block.auto_arm_blocked_reason() != "write_target_sem_watchdog"
