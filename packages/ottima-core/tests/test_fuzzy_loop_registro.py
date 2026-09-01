"""FuzzyLoopConfig + validacao de save do FLL (F1 na camada da API)."""

import pytest
from pydantic import ValidationError

from ottima_core.contracts_export import (
    FUZZY_DEFAULT_FLL,
    FUZZY_LOOP_DEFAULT_FLL,
    PORT_CONTRACTS,
)
from ottima_core.flowgraph import TagRef, parse_graph, validate_graph
from ottima_core.flowgraph.parse import FuzzyLoopConfig, loop_structural

TS = 1.0


def _minima(**over) -> dict:
    base = {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "ke": 0.1, "ku": 5.0}
    base.update(over)
    return base


def _no(node_id: str, exec_order: int, **over) -> dict:
    return {
        "id": node_id,
        "type": "fuzzy_loop",
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, **_minima(**over)},
    }


def _tag_read(node_id: str, exec_order: int, tag_id: int) -> dict:
    return {
        "id": node_id,
        "type": "opc_read",
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, "tag_id": tag_id},
    }


def _resultado(nodes: list[dict], edges: list[dict]):
    tags = {1: TagRef(id=1, conn_id=1, direction="r", data_type="float")}
    return validate_graph(parse_graph({"nodes": nodes, "edges": edges}), tags, TS)


def _malha_valida(**over):
    nodes = [_tag_read("pv", 1, 1), _no("fic", 2, **over)]
    edges = [
        {
            "id": "e1",
            "source": "pv",
            "target": "fic",
            "sourceHandle": "out",
            "targetHandle": "in",
        }
    ]
    return _resultado(nodes, edges)


def test_config_minima_usa_fll_default() -> None:
    cfg = FuzzyLoopConfig.model_validate(_minima())
    assert cfg.fll == FUZZY_LOOP_DEFAULT_FLL
    assert cfg.tf_de == 1.0 and cfg.lut_enabled is False
    assert cfg.kde == 0.0 and cfg.lut_resolution == 65


def test_ganhos_invalidos_rejeitados() -> None:
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(ke=0.0))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(ku=-1.0))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(kde=-0.1))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(tf_de=0.0))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(lut_resolution=10))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(lut_resolution=300))


def test_herda_as_faixas_do_shell() -> None:
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(sp_lo_lim=100.0, sp_hi_lim=0.0))


def test_split_estrutural_inclui_fll() -> None:
    a = FuzzyLoopConfig.model_validate(_minima())
    b = FuzzyLoopConfig.model_validate(_minima(ku=9.0))  # sintonia
    c = FuzzyLoopConfig.model_validate(_minima(fll=FUZZY_LOOP_DEFAULT_FLL + "\n"))
    fa = {"type": "fuzzy_loop", **a.model_dump()}
    assert loop_structural(fa) == loop_structural({"type": "fuzzy_loop", **b.model_dump()})
    assert loop_structural(fa) != loop_structural({"type": "fuzzy_loop", **c.model_dump()})


def test_malha_valida_com_fll_default_nao_gera_erro() -> None:
    assert _malha_valida().errors == []


def test_f1_save_recusa_fll_fora_do_contrato() -> None:
    # o FLL LIVRE do bloco `fuzzy` antigo (IN1/OUT1 posicionais, faixa -10..10)
    resultado = _malha_valida(fll=FUZZY_DEFAULT_FLL)
    assert any("FLL" in e for e in resultado.errors)


def test_f2_save_recusa_lock_previous_com_codigo_dedicado() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("lock-previous: false", "lock-previous: true")
    erros = _malha_valida(fll=fll).errors
    assert any("FLL_LOCK_PREVIOUS_FORBIDDEN" in e for e in erros)


def test_save_recusa_fll_com_sintaxe_invalida() -> None:
    erros = _malha_valida(fll="Engine: lixo\nsintaxe invalida").errors
    assert any("fic" in e and "FLL" in e for e in erros)


def test_contrato_de_portas_espelha_o_pid_loop() -> None:
    fuzzy_loop = PORT_CONTRACTS["fuzzy_loop"]
    assert fuzzy_loop["ports"] == PORT_CONTRACTS["pid_loop"]["ports"]
    assert fuzzy_loop["default_fll"] == FUZZY_LOOP_DEFAULT_FLL
    assert isinstance(fuzzy_loop["max_fll_length"], int)
