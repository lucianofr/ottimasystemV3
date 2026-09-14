"""Contrato do bloco utilitário Constant (fonte fixa, sem entrada).

Sem estado e sem entrada: `out` é sempre o `value` configurado, com `ok=True` em toda
varredura (`value` já validado finito no parse). Cobre também a instanciação via
`build_definition` e o hot-swap ao mudar `value` (ADR-024/ADR-011).
"""

from typing import Any, cast

from ottima_core.flowgraph import TagRef, parse_graph
from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.constant import ConstantBlock
from ottima_flow_runtime.definition import StagedDefinition, build_definition

TS = 1.0


async def test_constant_emite_o_valor_configurado_com_ok_true():
    bloco = ConstantBlock("c1", value=7.5)

    assert (await bloco.step({}))["out"] == PortSample(7.5, True)


async def test_constant_repete_o_mesmo_valor_em_varreduras_seguidas():
    bloco = ConstantBlock("c1", value=-3.0)

    primeira = await bloco.step({})
    segunda = await bloco.step({})

    assert primeira["out"] == PortSample(-3.0, True)
    assert segunda["out"] == PortSample(-3.0, True)


def test_constant_declara_nenhuma_entrada_e_uma_saida():
    bloco = ConstantBlock("c1", value=1.0)

    assert bloco.input_ports == ()
    assert bloco.output_ports == ("out",)


# --------------------------------------------------------------------------------------
# build_definition — instanciação e hot-swap
# --------------------------------------------------------------------------------------


def _node(node_id: str, node_type: str, exec_order: int, **data: object) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, "label": "", **data},
    }


def _graph(*, value: float = 42.0) -> dict:
    """Constant -> OPC-Write: a única fiação possível (Constant não tem entrada)."""
    return {
        "nodes": [
            _node("c1", "constant", 1, value=value),
            _node("w1", "opc_write", 2, tag_id=1),
        ],
        "edges": [
            {
                "id": "e1",
                "source": "c1",
                "target": "w1",
                "sourceHandle": "out",
                "targetHandle": "in",
            },
        ],
    }


def _tags() -> dict[int, TagRef]:
    return {1: TagRef(id=1, conn_id=1, direction="w", data_type="float")}


def _build(graph: dict, reuse: dict | None = None) -> StagedDefinition:
    none: Any = None
    return build_definition(
        parse_graph(graph),
        _tags(),
        flow_id=1,
        ts_seconds=TS,
        reuse={} if reuse is None else reuse,
        redis_client=none,
        pool=none,
        snapshot=none,
        exchange=none,
    )


def test_instancia_o_bloco_constant():
    staged = _build(_graph())

    assert isinstance(staged.blocks["c1"][1], ConstantBlock)


def test_mudar_o_valor_instancia_constant_novo():
    antes = _build(_graph(value=1.0))
    depois = _build(_graph(value=2.0), reuse=cast(dict, antes.blocks))

    assert depois.blocks["c1"][1] is not antes.blocks["c1"][1]
