"""Mesa de casos do SSTO (ADR-027 §2/§4/§5/§6) — montagem do LP e inviabilidade.

Cobre os casos obrigatórios do brief: **1** (objetivo trivial), **2** (restrições
conflitantes ⇒ desistência por rank, com ordem), **3** (degrau de DV), **4** (mudança de
limite de CV em runtime) e **6** (não-quadrado, m > n). O **5** (flipping/detuning) mora em
`test_ssto_detuning.py`, junto do backend QP.

Invariantes que estes testes existem para travar:
- DV **nunca** é variável de decisão;
- limite de MV **nunca** é relaxado, nem em inviabilidade;
- toda desistência aparece em `given_up`, na ordem em que ocorreu.
"""

import numpy as np
import pytest

from ottima_core.flowgraph import MpcConfig
from ottima_flow_runtime.target_calculation.ssto import (
    SstoInput,
    SteadyStateOptimizer,
)

TS = 1.0


def _mv(
    id_: str,
    *,
    lo: float = 0.0,
    hi: float = 100.0,
    objective: str = "none",
    psv: float | None = None,
) -> dict:
    mv = {
        "id": id_,
        "name": id_,
        "eu": "%",
        "limits": {"min": lo, "max": hi},
        "max_rate": 5.0,
    }
    if objective != "none":
        mv["objective"] = objective
    if psv is not None:
        mv["psv"] = psv
    return mv


def _cv(
    id_: str,
    *,
    lo: float = 0.0,
    hi: float = 200.0,
    priority: int = 1,
    kind: str = "selfreg",
    objective: str = "none",
) -> dict:
    cv = {
        "id": id_,
        "name": id_,
        "eu": "degC",
        "kind": kind,
        "tss": 100.0,
        "weight": 1.0,
        "sp_limits": {"min": lo, "max": hi},
        "priority": priority,
    }
    if objective != "none":
        cv["objective"] = objective
    return cv


def _co(
    id_: str, *, lo: float = 0.0, hi: float = 10.0, priority: int = 1, objective: str = "none"
) -> dict:
    co = {
        "id": id_,
        "name": id_,
        "eu": "bar",
        "kind": "selfreg",
        "tss": 100.0,
        "range": {"low": lo, "high": hi},
        "priority": priority,
    }
    if objective != "none":
        co["objective"] = objective
    return co


def _dv(id_: str) -> dict:
    return {"id": id_, "name": id_, "eu": "m3/h"}


def _sopdt(k: float) -> dict:
    return {"enabled": True, "params": {"K": k, "tau1": 10.0, "tau2": 5.0, "theta": 0.0}}


def _iopdt(ki: float) -> dict:
    return {"enabled": True, "params": {"Ki": ki, "theta": 0.0}}


def _config(
    *,
    mvs: list[dict],
    cvs: list[dict],
    constraints: list[dict] | None = None,
    dvs: list[dict] | None = None,
    models: dict,
    economics: dict | None,
) -> MpcConfig:
    bruto = {
        "name": "MPC de teste",
        "multiplier": 1,
        "variables": {
            "mvs": mvs,
            "cvs": cvs,
            "constraints": constraints or [],
            "dvs": dvs or [],
        },
        "models": models,
    }
    if economics is not None:
        bruto["economics"] = economics
    return MpcConfig.model_validate(bruto)


def _entrada(
    u: dict[str, float],
    *,
    bias: dict[str, float],
    d: dict | None = None,
    d_prev: dict | None = None,
    sp: dict[str, float] | None = None,
) -> SstoInput:
    return SstoInput(u=u, d=d or {}, d_prev=d_prev, bias=bias, delta_mv_prev=None, sp=sp)


# ---------------------------------------------------------------------------------------
# MV congelada pelo ciclo (ADR-028) — TD-014: o LP não pode mover o que não vai se mexer
# ---------------------------------------------------------------------------------------


def test_mv_congelada_fica_com_delta_zero_e_a_saudavel_compensa():
    """Duas MVs alimentam a mesma CV com o mesmo ganho e o mesmo preço favorável; `mv_b`
    chega congelada (ADR-028). O LP não pode gerar um `cv_target` que pressuponha `mv_b` se
    movendo — só `mv_a` pode compensar, e para exatamente no limite dela (60), não da soma
    das duas (120)."""
    config = _config(
        mvs=[_mv("mv_a", lo=0.0, hi=100.0), _mv("mv_b", lo=0.0, hi=100.0)],
        cvs=[_cv("cv_a", lo=-1e6, hi=1e6)],
        models={"cv_a": {"mv_a": _sopdt(1.0), "mv_b": _sopdt(1.0)}},
        economics={"enabled": True, "costs": {"mv_a": -1.0, "mv_b": -1.0}},
    )
    ssto = SteadyStateOptimizer(config, TS)
    entrada = SstoInput(
        u={"mv_a": 40.0, "mv_b": 40.0},
        d={},
        d_prev=None,
        bias={"cv_a": 0.0},
        delta_mv_prev=None,
        frozen_mvs=frozenset({"mv_b"}),
    )

    result = ssto.solve(entrada)

    assert result.delta_mv["mv_b"] == pytest.approx(0.0)
    assert result.mv_target["mv_b"] == pytest.approx(40.0)
    assert result.delta_mv["mv_a"] == pytest.approx(60.0)
    assert result.mv_target["mv_a"] == pytest.approx(100.0)


def test_sem_mv_congelada_as_duas_se_movem_ate_o_limite():
    """Não-regressão: sem `frozen_mvs`, as duas MVs livres continuam se movendo juntas até o
    próprio limite — a config é simétrica, então o LP é indiferente a qual delas move
    primeiro; o que importa é que NENHUMA fica presa em zero."""
    config = _config(
        mvs=[_mv("mv_a", lo=0.0, hi=100.0), _mv("mv_b", lo=0.0, hi=100.0)],
        cvs=[_cv("cv_a", lo=-1e6, hi=1e6)],
        models={"cv_a": {"mv_a": _sopdt(1.0), "mv_b": _sopdt(1.0)}},
        economics={"enabled": True, "costs": {"mv_a": -1.0, "mv_b": -1.0}},
    )
    ssto = SteadyStateOptimizer(config, TS)

    result = ssto.solve(_entrada({"mv_a": 40.0, "mv_b": 40.0}, bias={"cv_a": 0.0}))

    assert result.mv_target["mv_a"] == pytest.approx(100.0)
    assert result.mv_target["mv_b"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------------------
# Caso obrigatório 1 — objetivo trivial
# ---------------------------------------------------------------------------------------


def test_custo_unico_em_mv_com_limites_folgados_leva_ao_limite_da_mv():
    """Preço negativo (maximizar a MV) e nenhuma CV apertando ⇒ a MV vai ao seu limite
    superior duro."""
    config = _config(
        mvs=[_mv("mv_a", lo=0.0, hi=100.0)],
        cvs=[_cv("cv_a", lo=-1e6, hi=1e6)],
        models={"cv_a": {"mv_a": _sopdt(1.0)}},
        economics={"enabled": True, "costs": {"mv_a": -1.0}},
    )
    ssto = SteadyStateOptimizer(config, TS)

    result = ssto.solve(_entrada({"mv_a": 40.0}, bias={"cv_a": 0.0}))

    assert result.status == "optimal"
    assert result.delta_mv["mv_a"] == pytest.approx(60.0)
    assert result.mv_target["mv_a"] == pytest.approx(100.0)
    assert result.given_up == ()


def test_limite_de_cv_segura_o_otimo_antes_do_limite_de_mv():
    """`cv = 2·mv`, CV limitada em 120 com MV partindo de 40 (CVˢˢ = 80): a MV para em 60,
    não em 100."""
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_a", lo=0.0, hi=120.0)],
        models={"cv_a": {"mv_a": _sopdt(2.0)}},
        economics={"enabled": True, "costs": {"mv_a": -1.0}},
    )
    ssto = SteadyStateOptimizer(config, TS)

    result = ssto.solve(_entrada({"mv_a": 40.0}, bias={"cv_a": 0.0}))

    assert result.mv_target["mv_a"] == pytest.approx(60.0)
    assert result.cv_target["cv_a"] == pytest.approx(120.0)
    assert "cv_a:high" in result.active_constraints


def test_bias_desloca_o_alvo():
    """O SSTO parte da predição corrigida pela medida (bias DMC), não do modelo nu."""
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_a", lo=0.0, hi=120.0)],
        models={"cv_a": {"mv_a": _sopdt(2.0)}},
        economics={"enabled": True, "costs": {"mv_a": -1.0}},
    )
    ssto = SteadyStateOptimizer(config, TS)

    result = ssto.solve(_entrada({"mv_a": 40.0}, bias={"cv_a": 20.0}))

    # CVˢˢ livre = 2*40 + 20 = 100 ⇒ só sobram 20 de folga ⇒ ΔMV = 10
    assert result.delta_mv["mv_a"] == pytest.approx(10.0)
    assert result.cv_target["cv_a"] == pytest.approx(120.0)


# ---------------------------------------------------------------------------------------
# Caso obrigatório 2 — restrições conflitantes: desistência por rank
# ---------------------------------------------------------------------------------------


def _config_conflitante() -> MpcConfig:
    """Uma MV, duas Restrições de mesmo sinal e faixas incompatíveis: `co_hi` exige a MV
    alta, `co_lo` exige a MV baixa. Nenhum ΔMV satisfaz as duas."""
    return _config(
        mvs=[_mv("mv_a", lo=0.0, hi=100.0)],
        cvs=[],
        constraints=[
            _co("co_alta", lo=80.0, hi=100.0, priority=5),
            _co("co_baixa", lo=0.0, hi=20.0, priority=2),
        ],
        models={
            "co_alta": {"mv_a": _sopdt(1.0)},
            "co_baixa": {"mv_a": _sopdt(1.0)},
        },
        economics={"enabled": True, "costs": {}},
    )


def test_inviavel_desiste_da_restricao_de_menor_prioridade():
    ssto = SteadyStateOptimizer(_config_conflitante(), TS)

    result = ssto.solve(_entrada({"mv_a": 50.0}, bias={"co_alta": 0.0, "co_baixa": 0.0}))

    assert result.status == "relaxed"
    assert result.given_up == ("co_baixa",)
    # A de maior prioridade continua respeitada.
    assert result.cv_target["co_alta"] >= 80.0 - 1e-6


def test_ordem_da_desistencia_e_crescente_em_prioridade():
    """Três linhas incompatíveis: desiste da menos importante primeiro, depois da seguinte —
    e a ordem fica registrada."""
    config = _config(
        mvs=[_mv("mv_a", lo=0.0, hi=100.0)],
        cvs=[],
        constraints=[
            _co("co_p9", lo=90.0, hi=100.0, priority=9),
            _co("co_p5", lo=40.0, hi=50.0, priority=5),
            _co("co_p1", lo=0.0, hi=10.0, priority=1),
        ],
        models={row: {"mv_a": _sopdt(1.0)} for row in ("co_p9", "co_p5", "co_p1")},
        economics={"enabled": True, "costs": {}},
    )
    ssto = SteadyStateOptimizer(config, TS)

    result = ssto.solve(_entrada({"mv_a": 50.0}, bias={"co_p9": 0.0, "co_p5": 0.0, "co_p1": 0.0}))

    assert result.given_up == ("co_p1", "co_p5")
    assert result.cv_target["co_p9"] >= 90.0 - 1e-6


def test_mv_nunca_e_relaxada_mesmo_em_inviabilidade():
    """Faixa exigindo MV = 300 com limite duro em 100: a MV para em 100 e a linha é
    desistida — nunca o contrário."""
    config = _config(
        mvs=[_mv("mv_a", lo=0.0, hi=100.0)],
        cvs=[],
        constraints=[_co("co_a", lo=300.0, hi=400.0, priority=1)],
        models={"co_a": {"mv_a": _sopdt(1.0)}},
        economics={"enabled": True, "costs": {}},
    )
    ssto = SteadyStateOptimizer(config, TS)

    result = ssto.solve(_entrada({"mv_a": 50.0}, bias={"co_a": 0.0}))

    assert result.mv_target["mv_a"] <= 100.0 + 1e-9
    assert result.given_up == ("co_a",)


def test_slack_e_a_primeira_linha_de_defesa_e_aparece_no_resultado():
    """Antes de desistir de qualquer linha, o LP paga folga penalizada — e a folga usada
    fica visível para a auditoria."""
    ssto = SteadyStateOptimizer(_config_conflitante(), TS)

    result = ssto.solve(_entrada({"mv_a": 50.0}, bias={"co_alta": 0.0, "co_baixa": 0.0}))

    assert set(result.slacks) == {"co_alta", "co_baixa"}


# ---------------------------------------------------------------------------------------
# Caso obrigatório 3 — degrau de DV
# ---------------------------------------------------------------------------------------


def test_degrau_de_dv_desloca_o_regime_por_Gd_delta_dv():
    """Um degrau de DV desloca CVˢˢ exatamente por `Gd·ΔDV` — o feedforward de regime.

    A identidade `CVˢˢ* = base + Gd·ΔDV + G·ΔMV*` é o conteúdo do caso: o deslocamento da
    DV é aditivo e vive fora do espaço de decisão. Não se afirma nada sobre QUAL ΔMV o LP
    escolhe aqui: sem preço e com a CV folgada, todo ΔMV viável é ótimo (custo 0), e um
    teste que fixasse o vértice estaria testando o desempate do HiGHS, não o SSTO.
    """
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_a", lo=-1e6, hi=1e6)],
        dvs=[_dv("dv_a")],
        models={"cv_a": {"mv_a": _sopdt(2.0), "dv_a": _sopdt(0.5)}},
        economics={"enabled": True, "costs": {}},
    )
    ssto = SteadyStateOptimizer(config, TS)

    result = ssto.solve(
        SstoInput(
            u={"mv_a": 10.0},
            d={"dv_a": 30.0},
            d_prev={"dv_a": 10.0},
            bias={"cv_a": 0.0},
            delta_mv_prev=None,
        )
    )

    # base(u, d_prev) = 2*10 + 0.5*10 = 25 ; Gd·ΔDV = 0.5*(30−10) = 10
    assert result.dv_shift["cv_a"] == pytest.approx(10.0)
    assert result.cv_target["cv_a"] == pytest.approx(25.0 + 10.0 + 2.0 * result.delta_mv["mv_a"])


def test_dv_nunca_aparece_como_variavel_de_decisao():
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_a")],
        dvs=[_dv("dv_a")],
        models={"cv_a": {"mv_a": _sopdt(2.0), "dv_a": _sopdt(0.5)}},
        economics={"enabled": True, "costs": {"mv_a": -1.0, "dv_a": -50.0}},
    )
    ssto = SteadyStateOptimizer(config, TS)

    result = ssto.solve(
        SstoInput(
            u={"mv_a": 10.0},
            d={"dv_a": 30.0},
            d_prev={"dv_a": 10.0},
            bias={"cv_a": 0.0},
            delta_mv_prev=None,
        )
    )

    assert set(result.delta_mv) == {"mv_a"}
    assert set(result.mv_target) == {"mv_a"}
    # Preço numa DV é ignorado: DV não é decisão, custo nela não move nada.
    assert ssto.decision_ids == ("mv_a",)


def test_degrau_de_dv_e_rejeitado_pela_mv_quando_a_cv_esta_limitada():
    """Feedforward de regime: a DV empurra a CV para fora da faixa e o LP move a MV para
    trazê-la de volta — sem tocar na DV.

    O preço na MV (maximizar) é o que torna o ótimo único: sem ele, qualquer ΔMV que
    devolva a CV à faixa custa o mesmo, e o teste estaria fixando o desempate do solver.
    """
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_a", lo=0.0, hi=30.0)],
        dvs=[_dv("dv_a")],
        models={"cv_a": {"mv_a": _sopdt(2.0), "dv_a": _sopdt(0.5)}},
        economics={"enabled": True, "costs": {"mv_a": -1.0}},
    )
    ssto = SteadyStateOptimizer(config, TS)

    result = ssto.solve(
        SstoInput(
            u={"mv_a": 10.0},
            d={"dv_a": 30.0},
            d_prev={"dv_a": 10.0},
            bias={"cv_a": 0.0},
            delta_mv_prev=None,
        )
    )

    # CVˢˢ livre = 25 + 10 = 35 > 30 ⇒ precisa de ΔMV = −2.5 (K=2)
    assert result.delta_mv["mv_a"] == pytest.approx(-2.5)
    assert result.cv_target["cv_a"] == pytest.approx(30.0)


# ---------------------------------------------------------------------------------------
# Caso obrigatório 4 — mudança de limite de CV em runtime
# ---------------------------------------------------------------------------------------


def _config_limite(hi: float) -> MpcConfig:
    return _config(
        mvs=[_mv("mv_a", lo=0.0, hi=100.0)],
        cvs=[_cv("cv_a", lo=0.0, hi=hi)],
        models={"cv_a": {"mv_a": _sopdt(2.0)}},
        economics={"enabled": True, "costs": {"mv_a": -1.0}},
    )


def test_aperto_de_limite_de_cv_produz_nova_solucao_viavel():
    entrada = _entrada({"mv_a": 20.0}, bias={"cv_a": 0.0})

    folgado = SteadyStateOptimizer(_config_limite(160.0), TS).solve(entrada)
    apertado = SteadyStateOptimizer(_config_limite(100.0), TS).solve(entrada)

    assert folgado.status == "optimal"
    assert apertado.status == "optimal"
    assert apertado.mv_target["mv_a"] == pytest.approx(50.0)
    assert apertado.mv_target["mv_a"] < folgado.mv_target["mv_a"]


def test_aperto_excessivo_aciona_relaxamento_por_rank():
    """Faixa abaixo do que a MV alcança no seu limite inferior ⇒ desistência da linha."""
    config = _config(
        mvs=[_mv("mv_a", lo=40.0, hi=100.0)],
        cvs=[_cv("cv_a", lo=0.0, hi=10.0)],
        models={"cv_a": {"mv_a": _sopdt(2.0)}},
        economics={"enabled": True, "costs": {"mv_a": -1.0}},
    )

    result = SteadyStateOptimizer(config, TS).solve(_entrada({"mv_a": 50.0}, bias={"cv_a": 0.0}))

    assert result.status == "relaxed"
    assert result.given_up == ("cv_a",)
    assert result.mv_target["mv_a"] >= 40.0 - 1e-9


# ---------------------------------------------------------------------------------------
# Caso obrigatório 6 — não-quadrado (m > n)
# ---------------------------------------------------------------------------------------


def test_mais_cvs_que_mvs_tem_conjunto_ativo_do_tamanho_do_numero_de_mvs():
    """No ótimo de um LP não degenerado, o nº de restrições ativas (linhas + limites de MV)
    é igual ao nº de variáveis de decisão — aqui, o nº de MVs."""
    config = _config(
        mvs=[_mv("mv_a", lo=0.0, hi=1000.0)],
        cvs=[
            _cv("cv_1", lo=0.0, hi=90.0),
            _cv("cv_2", lo=0.0, hi=60.0),
            _cv("cv_3", lo=0.0, hi=150.0),
        ],
        models={
            "cv_1": {"mv_a": _sopdt(1.0)},
            "cv_2": {"mv_a": _sopdt(0.5)},
            "cv_3": {"mv_a": _sopdt(2.0)},
        },
        economics={"enabled": True, "costs": {"mv_a": -1.0}},
    )

    result = SteadyStateOptimizer(config, TS).solve(
        _entrada({"mv_a": 10.0}, bias={"cv_1": 0.0, "cv_2": 0.0, "cv_3": 0.0})
    )

    assert result.status == "optimal"
    assert len(result.active_constraints) + len(result.active_mv_bounds) == 1
    # A que trava é a mais restritiva em ΔMV: cv_3 (150/2 = 75) < cv_2 (120) < cv_1 (90).
    assert result.active_constraints == ("cv_3:high",)


def test_duas_mvs_e_tres_cvs_ativam_duas_restricoes():
    config = _config(
        mvs=[_mv("mv_a", lo=0.0, hi=1000.0), _mv("mv_b", lo=0.0, hi=1000.0)],
        cvs=[
            _cv("cv_1", lo=0.0, hi=100.0),
            _cv("cv_2", lo=0.0, hi=100.0),
            _cv("cv_3", lo=0.0, hi=500.0),
        ],
        models={
            "cv_1": {"mv_a": _sopdt(1.0), "mv_b": _sopdt(0.2)},
            "cv_2": {"mv_a": _sopdt(0.3), "mv_b": _sopdt(1.0)},
            "cv_3": {"mv_a": _sopdt(1.0), "mv_b": _sopdt(1.0)},
        },
        economics={"enabled": True, "costs": {"mv_a": -1.0, "mv_b": -1.0}},
    )

    result = SteadyStateOptimizer(config, TS).solve(
        _entrada({"mv_a": 0.0, "mv_b": 0.0}, bias={"cv_1": 0.0, "cv_2": 0.0, "cv_3": 0.0})
    )

    assert result.status == "optimal"
    assert len(result.active_constraints) + len(result.active_mv_bounds) == 2


# ---------------------------------------------------------------------------------------
# Linha integradora e custos de linha
# ---------------------------------------------------------------------------------------


def test_linha_integradora_entra_como_taxa_nula():
    """CV integradora com `Ki = 0.4` e MV em 30 (op = 0): a taxa só zera com MV = 0."""
    config = _config(
        mvs=[_mv("mv_a", lo=-100.0, hi=100.0)],
        cvs=[_cv("cv_lvl", kind="integrating")],
        models={"cv_lvl": {"mv_a": _iopdt(0.4)}},
        economics={"enabled": True, "costs": {}, "integrating_tolerance": 0.0},
    )

    result = SteadyStateOptimizer(config, TS).solve(_entrada({"mv_a": 30.0}, bias={"cv_lvl": 0.0}))

    assert result.status == "optimal"
    assert result.mv_target["mv_a"] == pytest.approx(0.0, abs=1e-6)


def test_custo_de_linha_e_projetado_no_espaco_da_mv():
    """Preço na CV equivale ao preço `c_row·G` na MV — maximizar a CV com `K = 2` é o mesmo
    que um preço de −2 na MV."""
    config = _config(
        mvs=[_mv("mv_a", lo=0.0, hi=100.0)],
        cvs=[_cv("cv_a", lo=0.0, hi=1e6)],
        models={"cv_a": {"mv_a": _sopdt(2.0)}},
        economics={"enabled": True, "costs": {"cv_a": -1.0}},
    )

    result = SteadyStateOptimizer(config, TS).solve(_entrada({"mv_a": 0.0}, bias={"cv_a": 0.0}))

    assert result.mv_target["mv_a"] == pytest.approx(100.0)
    assert result.costs["mv_a"] == pytest.approx(-2.0)


def test_sem_economics_habilitado_o_otimizador_recusa_montar():
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_a")],
        models={"cv_a": {"mv_a": _sopdt(1.0)}},
        economics={"enabled": False},
    )

    with pytest.raises(ValueError, match="desabilitad"):
        SteadyStateOptimizer(config, TS)


def test_config_hash_acompanha_o_resultado():
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_a")],
        models={"cv_a": {"mv_a": _sopdt(1.0)}},
        economics={"enabled": True, "costs": {"mv_a": 1.0}},
    )

    result = SteadyStateOptimizer(config, TS).solve(_entrada({"mv_a": 10.0}, bias={"cv_a": 0.0}))

    assert len(result.config_hash) == 64


def test_shadow_price_da_restricao_ativa_e_publicado():
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_a", lo=0.0, hi=120.0)],
        models={"cv_a": {"mv_a": _sopdt(2.0)}},
        economics={"enabled": True, "costs": {"mv_a": -1.0}},
    )

    result = SteadyStateOptimizer(config, TS).solve(_entrada({"mv_a": 40.0}, bias={"cv_a": 0.0}))

    assert result.duals["cv_a:high"] != 0.0


def test_delta_mv_respeita_os_limites_duros_como_array():
    config = _config(
        mvs=[_mv("mv_a", lo=10.0, hi=20.0)],
        cvs=[_cv("cv_a", lo=-1e6, hi=1e6)],
        models={"cv_a": {"mv_a": _sopdt(1.0)}},
        economics={"enabled": True, "costs": {"mv_a": -1.0}},
    )

    result = SteadyStateOptimizer(config, TS).solve(_entrada({"mv_a": 15.0}, bias={"cv_a": 0.0}))

    assert np.isclose(result.mv_target["mv_a"], 20.0)


# ---------------------------------------------------------------------------------------
# Função objetivo por variável (ADR-027 §9 estendido): termos do LP derivados do enum
# ---------------------------------------------------------------------------------------


def test_cv_maximize_sem_economics_empurra_ao_limite_superior():
    """`objective="maximize"` na CV, sem bloco `economics`: preço −1/span projetado por
    `c_row·G` — equivalente ao custo negativo já coberto, agora derivado do enum."""
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_a", lo=0.0, hi=150.0, objective="maximize")],
        models={"cv_a": {"mv_a": _sopdt(2.0)}},
        economics=None,
    )

    result = SteadyStateOptimizer(config, TS).solve(_entrada({"mv_a": 40.0}, bias={"cv_a": 0.0}))

    # CV = 2·MV: teto 150 ⇒ MV para em 75 (abaixo do limite duro 100).
    assert result.cv_target["cv_a"] == pytest.approx(150.0)
    assert result.mv_target["mv_a"] == pytest.approx(75.0)
    assert result.status == "optimal"


def test_cv_target_domina_o_preco_de_maximize_da_mv():
    """Âncora `target` (W=50/span) vence o preço −1/span da MV: com SP=42 a CV para em 42
    mesmo com a MV querendo maximizar."""
    config = _config(
        mvs=[_mv("mv_a", objective="maximize")],
        cvs=[_cv("cv_a", lo=0.0, hi=200.0, objective="target")],
        models={"cv_a": {"mv_a": _sopdt(1.0)}},
        economics=None,
    )

    result = SteadyStateOptimizer(config, TS).solve(
        _entrada({"mv_a": 10.0}, bias={"cv_a": 0.0}, sp={"cv_a": 42.0})
    )

    assert result.status == "optimal"
    assert result.cv_target["cv_a"] == pytest.approx(42.0)
    assert result.mv_target["mv_a"] == pytest.approx(42.0)


def test_cv_psv_cede_ao_preco_de_maximize_da_mv():
    """Âncora `psv` (W=0.1/span) é FRACA: o preço −1/span da MV a empurra para longe do SP —
    o grau de liberdade só se acomoda no SP quando nada mais puxa."""
    config = _config(
        mvs=[_mv("mv_a", objective="maximize")],
        cvs=[_cv("cv_a", lo=0.0, hi=200.0, objective="psv")],
        models={"cv_a": {"mv_a": _sopdt(1.0)}},
        economics=None,
    )

    result = SteadyStateOptimizer(config, TS).solve(
        _entrada({"mv_a": 10.0}, bias={"cv_a": 0.0}, sp={"cv_a": 42.0})
    )

    # Preço vence: MV vai ao limite duro 100, CV acompanha (K=1), longe do SP=42.
    assert result.mv_target["mv_a"] == pytest.approx(100.0)
    assert result.cv_target["cv_a"] == pytest.approx(100.0)


def test_mv_psv_sem_mais_nada_puxando_para_no_valor_preferido():
    """PSV de MV com a CV totalmente folgada e sem preços: a âncora fraca é a única força —
    a MV para exatamente no valor preferido."""
    config = _config(
        mvs=[_mv("mv_a", objective="psv", psv=30.0)],
        cvs=[_cv("cv_a", lo=-1e6, hi=1e6)],
        models={"cv_a": {"mv_a": _sopdt(1.0)}},
        economics=None,
    )

    result = SteadyStateOptimizer(config, TS).solve(_entrada({"mv_a": 10.0}, bias={"cv_a": 0.0}))

    assert result.status == "optimal"
    assert result.mv_target["mv_a"] == pytest.approx(30.0)


def test_equalize_nivela_fracao_de_escala():
    """Duas MVs `equalize` com spans e posições iniciais distintas: o alvo nivela
    `(mv_target − min)/span` entre as duas."""
    config = _config(
        mvs=[
            _mv("mv_a", lo=0.0, hi=100.0, objective="equalize"),
            _mv("mv_b", lo=0.0, hi=200.0, objective="equalize"),
        ],
        cvs=[_cv("cv_a", lo=-1e6, hi=1e6)],
        models={"cv_a": {"mv_a": _sopdt(1.0), "mv_b": _sopdt(1.0)}},
        economics=None,
    )

    result = SteadyStateOptimizer(config, TS).solve(
        _entrada({"mv_a": 10.0, "mv_b": 40.0}, bias={"cv_a": 0.0})
    )

    assert result.status == "optimal"
    fracao_a = (result.mv_target["mv_a"] - 0.0) / 100.0
    fracao_b = (result.mv_target["mv_b"] - 0.0) / 200.0
    assert fracao_a == pytest.approx(fracao_b, abs=1e-6)


def test_observe_limit_com_folga_fica_no_sp():
    """`observe_limit` com tudo viável: a CV não sai do SP (dev = 0)."""
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_a", lo=0.0, hi=200.0, objective="observe_limit")],
        models={"cv_a": {"mv_a": _sopdt(1.0)}},
        economics=None,
    )

    result = SteadyStateOptimizer(config, TS).solve(
        _entrada({"mv_a": 50.0}, bias={"cv_a": 0.0}, sp={"cv_a": 50.0})
    )

    assert result.status == "optimal"
    assert result.cv_target["cv_a"] == pytest.approx(50.0)


def test_observe_limit_sai_do_sp_so_o_necessario_para_viabilizar():
    """`observe_limit` com uma Restrição forçando a MV: a CV sai do SP só o que a restrição
    exige — nem um EU a mais (âncora mais fraca, mas presente)."""
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_a", lo=0.0, hi=200.0, objective="observe_limit")],
        constraints=[_co("co_a", lo=0.0, hi=60.0)],
        models={"cv_a": {"mv_a": _sopdt(1.0)}, "co_a": {"mv_a": _sopdt(1.0)}},
        economics=None,
    )

    # SP=80 mas a restrição `co_a = MV ≤ 60` impõe MV = 60: CV sai de 80 para 60.
    result = SteadyStateOptimizer(config, TS).solve(
        _entrada({"mv_a": 80.0}, bias={"cv_a": 0.0, "co_a": 0.0}, sp={"cv_a": 80.0})
    )

    assert result.status == "optimal"
    assert result.cv_target["co_a"] == pytest.approx(60.0)
    assert result.cv_target["cv_a"] == pytest.approx(60.0)
    assert result.given_up == ()


def test_optimization_disabled_sem_economics_e_sem_objetivos_recusa_montar():
    config = _config(
        mvs=[_mv("mv_a")],
        cvs=[_cv("cv_a")],
        models={"cv_a": {"mv_a": _sopdt(1.0)}},
        economics=None,
    )

    with pytest.raises(ValueError, match="SSTO desabilitado"):
        SteadyStateOptimizer(config, TS)
