"""Montagem e hot-swap dos blocos de filtro em `build_definition` (ADR-026, spec F3 §4.1-3).

Mesa pura como `test_definition.py`: os blocos de filtro não tocam Redis, pool de scripts nem
snapshot, então os serviços entram como `None` — o que este arquivo prova é a instanciação
(tipo e parâmetros) e a preservação de instância por identidade funcional, não a fiação viva
(essa é do `test_hotswap.py`, com harness completo).
"""

from typing import Any, cast

from ottima_core.flowgraph import TagRef, parse_graph
from ottima_flow_runtime.blocks.first_order import FirstOrderBlock
from ottima_flow_runtime.blocks.kalman import KalmanBlock
from ottima_flow_runtime.definition import StagedDefinition, build_definition

TS = 1.0


def _node(node_id: str, node_type: str, exec_order: int, **data: object) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, "label": "", **data},
    }


def _graph(*, tau: float = 5.0, measurement_noise: float = 0.5, label: str = "") -> dict:
    """Leitura -> Filtro 1a ordem -> Filtro Kalman: os dois blocos com a entrada ligada."""
    return {
        "nodes": [
            _node("r1", "opc_read", 1, tag_id=1),
            _node("f1", "first_order", 2, tau=tau, label=label),
            _node("k1", "kalman", 3, measurement_noise=measurement_noise, process_noise=0.05),
        ],
        "edges": [
            {
                "id": "e1",
                "source": "r1",
                "target": "f1",
                "sourceHandle": "out",
                "targetHandle": "in",
            },
            {
                "id": "e2",
                "source": "f1",
                "target": "k1",
                "sourceHandle": "out",
                "targetHandle": "in",
            },
        ],
    }


def _tags() -> dict[int, TagRef]:
    return {1: TagRef(id=1, conn_id=1, direction="r", data_type="float")}


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
    )


def test_instancia_os_dois_blocos_de_filtro():
    staged = _build(_graph())

    assert isinstance(staged.blocks["f1"][1], FirstOrderBlock)
    assert isinstance(staged.blocks["k1"][1], KalmanBlock)


def test_ordem_de_execucao_segue_o_exec_order():
    staged = _build(_graph())

    assert [block.block_id for block in staged.definition.blocks] == ["r1", "f1", "k1"]


async def test_tau_chega_ao_bloco_com_o_ts_do_flow():
    """`tau = Ts/10 - ε` degrada para passagem direta: prova que os dois valores chegaram."""
    staged = _build(_graph(tau=TS / 10 - 1e-9))
    bloco = cast(FirstOrderBlock, staged.blocks["f1"][1])

    from ottima_flow_runtime.blocks.base import PortSample

    await bloco.step({"in": PortSample(0.0, True)})
    assert (await bloco.step({"in": PortSample(7.0, True)}))["out"].v == 7.0


def test_rotulo_nao_reinstancia_o_bloco():
    """Identidade funcional ignora `label` (ADR-024): o estado do filtro sobrevive ao swap."""
    antes = _build(_graph())

    depois = _build(_graph(label="Filtro da PV"), reuse=antes.blocks)

    assert depois.blocks["f1"][1] is antes.blocks["f1"][1]
    assert depois.blocks["k1"][1] is antes.blocks["k1"][1]


def test_mudar_tau_instancia_bloco_novo():
    antes = _build(_graph(tau=5.0))

    depois = _build(_graph(tau=30.0), reuse=antes.blocks)

    assert depois.blocks["f1"][1] is not antes.blocks["f1"][1]
    assert depois.blocks["k1"][1] is antes.blocks["k1"][1]  # o Kalman não mudou


def test_mudar_o_ruido_instancia_kalman_novo():
    antes = _build(_graph(measurement_noise=0.5))

    depois = _build(_graph(measurement_noise=2.0), reuse=antes.blocks)

    assert depois.blocks["k1"][1] is not antes.blocks["k1"][1]
    assert depois.blocks["f1"][1] is antes.blocks["f1"][1]
