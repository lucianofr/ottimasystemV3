"""FuzzyLoopConfig v2 (multicanal) + validacao de save do FLL (F1 na camada da API)."""

import pytest
from pydantic import ValidationError

from ottima_core.contracts_export import (
    FUZZY_DEFAULT_FLL,
    FUZZY_LOOP_DEFAULT_FLL,
    PORT_CONTRACTS,
)
from ottima_core.flowgraph import TagRef, parse_graph, validate_graph
from ottima_core.flowgraph.fll_defaults import MAX_FUZZY_LOOPS, fuzzy_loop_default_fll
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


def _aresta(edge_id: str, source: str, target: str, source_handle: str, target_handle: str) -> dict:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "sourceHandle": source_handle,
        "targetHandle": target_handle,
    }


def _resultado(nodes: list[dict], edges: list[dict]):
    tags = {1: TagRef(id=1, conn_id=1, direction="r", data_type="float")}
    return validate_graph(parse_graph({"nodes": nodes, "edges": edges}), tags, TS)


def _malha_valida(**over):
    nodes = [_tag_read("pv", 1, 1), _no("fic", 2, **over)]
    edges = [_aresta("e1", "pv", "fic", "out", "pv_1")]
    return _resultado(nodes, edges)


def test_config_minima_usa_fll_default() -> None:
    cfg = FuzzyLoopConfig.model_validate(_minima())
    assert cfg.fll == FUZZY_LOOP_DEFAULT_FLL
    assert cfg.n_loops == 1
    assert cfg.kde == 0.0 and cfg.lut_resolution == 65


def test_ganhos_invalidos_rejeitados() -> None:
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(ke=0.0))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(kde=-1.0))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(ku=0.0))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(tf_de=0.0))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(lut_resolution=300))


def test_n_loops_fora_do_teto_rejeitado() -> None:
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(n_loops=0))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(n_loops=MAX_FUZZY_LOOPS + 1))


def test_herda_as_faixas_do_shell() -> None:
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(sp_lo_lim=100.0, sp_hi_lim=0.0))


def test_modos_remotos_rejeitados_no_v2() -> None:
    """Sem portas cas_in/rcas_in/rout_in no v2: permitted e normal restritos."""
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(permitted=["oos", "man", "auto", "cas"]))
    with pytest.raises(ValidationError):
        FuzzyLoopConfig.model_validate(_minima(normal="cas"))
    cfg = FuzzyLoopConfig.model_validate(_minima(permitted=["oos", "man"], normal="man"))
    assert cfg.normal == "man"


def test_split_estrutural_inclui_fll_e_n_loops() -> None:
    a = FuzzyLoopConfig.model_validate(_minima())
    b = FuzzyLoopConfig.model_validate(_minima(ku=9.0))  # sintonia
    c = FuzzyLoopConfig.model_validate(_minima(fll=FUZZY_LOOP_DEFAULT_FLL + "\n"))
    d = FuzzyLoopConfig.model_validate(_minima(n_loops=2, fll=fuzzy_loop_default_fll(2)))
    fa = {"type": "fuzzy_loop", **a.model_dump()}
    assert loop_structural(fa) == loop_structural({"type": "fuzzy_loop", **b.model_dump()})
    assert loop_structural(fa) != loop_structural({"type": "fuzzy_loop", **c.model_dump()})
    assert loop_structural(fa) != loop_structural({"type": "fuzzy_loop", **d.model_dump()})


def test_malha_valida_com_fll_default_nao_gera_erro() -> None:
    assert _malha_valida().errors == []


def test_malha_mimo_2_canais_valida() -> None:
    """v2: n_loops=2 exige pv_1 E pv_2 ligados; a base default multicanal passa nos
    portoes de superficie dos dois canais."""
    nodes = [
        _tag_read("pv", 1, 1),
        _no("fic", 2, n_loops=2, fll=fuzzy_loop_default_fll(2)),
    ]
    edges = [
        _aresta("e1", "pv", "fic", "out", "pv_1"),
        _aresta("e2", "pv", "fic", "out", "pv_2"),
    ]
    assert _resultado(nodes, edges).errors == []


def test_malha_mimo_sem_pv_do_canal_2_reprovada() -> None:
    nodes = [
        _tag_read("pv", 1, 1),
        _no("fic", 2, n_loops=2, fll=fuzzy_loop_default_fll(2)),
    ]
    edges = [_aresta("e1", "pv", "fic", "out", "pv_1")]
    erros = _resultado(nodes, edges).errors
    assert any("pv_2" in e for e in erros)


def test_malha_mimo_com_fll_siso_reprovada() -> None:
    """FLL de 1 canal (2 entradas/1 saida) num bloco n_loops=2 viola a contagem posicional."""
    nodes = [
        _tag_read("pv", 1, 1),
        _no("fic", 2, n_loops=2),  # fll default (1 canal)
    ]
    edges = [
        _aresta("e1", "pv", "fic", "out", "pv_1"),
        _aresta("e2", "pv", "fic", "out", "pv_2"),
    ]
    erros = _resultado(nodes, edges).errors
    assert any("FLL_INPUT_COUNT_MUST_BE_2N_LOOPS" in e for e in erros)


def test_f1_save_recusa_fll_fora_do_contrato() -> None:
    # o FLL LIVRE do bloco `fuzzy` antigo (1 entrada, 4 saidas, faixa -10..10)
    resultado = _malha_valida(fll=FUZZY_DEFAULT_FLL)
    assert any("FLL" in e for e in resultado.errors)


def test_f2_save_recusa_lock_previous_com_codigo_dedicado() -> None:
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("lock-previous: false", "lock-previous: true")
    erros = _malha_valida(fll=fll).errors
    assert any("FLL_LOCK_PREVIOUS_FORBIDDEN" in e for e in erros)


def test_save_recusa_fll_com_sintaxe_invalida() -> None:
    erros = _malha_valida(fll="Engine: lixo\nsintaxe invalida").errors
    assert any("fic" in e and "FLL" in e for e in erros)


def test_f4_save_recusa_superficie_com_sinal_invertido() -> None:
    """Portao de superficie bloqueia o save (SPEC_FUZZY secao 5.3), nao so o contrato FLL."""
    fll = FUZZY_LOOP_DEFAULT_FLL.replace(
        "rule: if e is PG then du is PG", "rule: if e is PG then du is NG"
    )
    erros = _malha_valida(fll=fll).errors
    assert any("SIGN_CONSISTENCY" in e for e in erros)


def test_f4_mimo_recusa_sinal_invertido_em_um_canal() -> None:
    """O portao roda POR CANAL: inverter so as regras do canal 2 reprova citando o canal."""
    fll = fuzzy_loop_default_fll(2).replace(
        "rule: if e2 is PG then du2 is PG", "rule: if e2 is PG then du2 is NG"
    )
    nodes = [
        _tag_read("pv", 1, 1),
        _no("fic", 2, n_loops=2, fll=fll),
    ]
    edges = [
        _aresta("e1", "pv", "fic", "out", "pv_1"),
        _aresta("e2", "pv", "fic", "out", "pv_2"),
    ]
    erros = _resultado(nodes, edges).errors
    assert any("canal 2" in e and "SIGN_CONSISTENCY" in e for e in erros)
    assert not any("canal 1" in e for e in erros)


def test_save_recusa_superficie_com_buraco() -> None:
    """Regiao sem regra reprova em NO_NAN: no bloco comissionado o buraco nao passa."""
    fll = FUZZY_LOOP_DEFAULT_FLL
    for regra in ("  rule: if e is PP then du is PP\n", "  rule: if e is PG then du is PG\n"):
        fll = fll.replace(regra, "")
    erros = _malha_valida(fll=fll).errors
    assert any("NO_NAN" in e for e in erros)


def test_acao_direta_e_avaliada_no_sentido_certo() -> None:
    """Em acao direta a superficie correta e a espelhada — o portao usa `direct_acting`."""
    assert _malha_valida(direct_acting=True).errors != []
    espelhado = FUZZY_LOOP_DEFAULT_FLL
    for de_, para in (
        ("du is NG", "du is __PG"),
        ("du is NP", "du is __PP"),
        ("du is PP", "du is NP"),
        ("du is PG", "du is NG"),
    ):
        espelhado = espelhado.replace(f"then {de_}", f"then {para}")
    espelhado = espelhado.replace("du is __PG", "du is PG").replace("du is __PP", "du is PP")
    assert _malha_valida(fll=espelhado, direct_acting=True).errors == []


def test_contrato_de_portas_e_dinamico_por_canal() -> None:
    """v2: portas pv_1..pv_n / out_1..out_n derivadas de `n_loops` — sem paridade com o
    pid_loop (que segue SISO com portas fixas)."""
    fuzzy_loop = PORT_CONTRACTS["fuzzy_loop"]
    assert fuzzy_loop["dynamic"] is True
    regras = fuzzy_loop["rules"]
    assert [(r["direction"], r["prefix"], r["count_field"]) for r in regras] == [
        ("input", "pv_", "n_loops"),
        ("output", "out_", "n_loops"),
    ]
    assert fuzzy_loop["default_fll"] == FUZZY_LOOP_DEFAULT_FLL
    assert fuzzy_loop["default_counts"] == {"n_loops": 1}
    assert set(fuzzy_loop["default_fll_mimo"]) == {"2", "3", "4"}
    assert isinstance(fuzzy_loop["max_fll_length"], int)
    # O pid_loop NAO muda: portas fixas do shell.
    pid_loop = PORT_CONTRACTS["pid_loop"]
    assert pid_loop["dynamic"] is False
    assert any(p["name"] == "cas_in" for p in pid_loop["ports"])
