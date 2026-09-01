"""FuzzyKernel (SPEC_FUZZY secao 3.3): normalizacao, filtro, NaN, isolamento (F3/F6/F7)."""

import math

from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL
from ottima_flow_runtime.blocks.kernels.fuzzy import FuzzyKernelCfg, build_fuzzy_kernel


def _kernel(**over):
    cfg = FuzzyKernelCfg(ke=0.1, kde=0.0, ku=5.0)
    for k, v in over.items():
        setattr(cfg, k, v)
    return build_fuzzy_kernel(FUZZY_LOOP_DEFAULT_FLL, cfg)


def test_erro_zero_da_du_zero() -> None:
    k = _kernel()
    k.align(50.0, 10.0, 10.0)
    assert abs(k.compute(sp=10.0, pv=10.0, dt=1.0)) < 1e-6


def test_sinal_consistente_e_ganho_ku() -> None:
    k = _kernel(ku=5.0)
    k.align(0.0, 10.0, 10.0)
    sobe = k.compute(sp=15.0, pv=10.0, dt=1.0)  # erro +5, e_n = 0.5
    assert sobe > 0.0
    k2 = _kernel(ku=10.0)
    k2.align(0.0, 10.0, 10.0)
    assert abs(k2.compute(sp=15.0, pv=10.0, dt=1.0) - 2.0 * sobe) < 1e-6  # F6 no kernel


def test_direct_acting_inverte() -> None:
    k = _kernel(direct_acting=True)
    k.align(0.0, 10.0, 10.0)
    assert k.compute(sp=15.0, pv=10.0, dt=1.0) < 0.0


def test_saturacao_do_universo() -> None:
    k = _kernel(ke=0.1, ku=5.0)
    k.align(0.0, 0.0, 0.0)
    a = k.compute(sp=100.0, pv=0.0, dt=1.0)  # e_n satura em 1
    k.align(0.0, 0.0, 0.0)
    b = k.compute(sp=1000.0, pv=0.0, dt=1.0)  # ainda 1
    assert abs(a - b) < 1e-6


def test_kde_zero_ignora_a_derivada() -> None:
    """KDE = 0 e o default de comissionamento (SPEC secao 6.4): de_n colapsa em 0."""
    k = _kernel(kde=0.0)
    k.align(0.0, 0.0, 0.0)
    k.compute(sp=10.0, pv=0.0, dt=1.0)
    assert k.diag["de_n"] == 0.0


def test_filtro_da_derivada_e_de_primeira_ordem() -> None:
    """de_f converge para de com passos a = dt/(tf+dt) — robusto a dt variavel."""
    k = _kernel(kde=1.0, tf_de=1.0)
    k.align(0.0, 0.0, 0.0)  # e_prev = 0
    k.compute(sp=1.0, pv=0.0, dt=1.0)  # de = 1.0, a = 0.5 -> de_f = 0.5
    assert abs(k.diag["de_n"] - 0.5) < 1e-9


def test_f3_regiao_sem_regra_propaga_nan() -> None:
    # FLL valido no contrato mas com buraco: so cobre e negativo
    com_buraco = FUZZY_LOOP_DEFAULT_FLL
    for regra in (
        "  rule: if e is ZE and de is N then du is NP\n",
        "  rule: if e is ZE and de is ZE then du is ZE\n",
        "  rule: if e is ZE and de is P then du is PP\n",
        "  rule: if e is PP then du is PP\n",
        "  rule: if e is PG then du is PG\n",
    ):
        com_buraco = com_buraco.replace(regra, "")
    k = build_fuzzy_kernel(com_buraco, FuzzyKernelCfg(ke=0.1, kde=0.0, ku=5.0))
    assert k.validate() == []  # o buraco NAO viola o contrato: e erro de comissionamento
    k.align(0.0, 0.0, 0.0)
    assert math.isnan(k.compute(sp=50.0, pv=0.0, dt=1.0))  # e_n=1.0: sem regra


def test_f7_duas_instancias_mesmo_fll_sao_isoladas() -> None:
    cfg = FuzzyKernelCfg(ke=0.1, kde=0.0, ku=5.0)
    a = build_fuzzy_kernel(FUZZY_LOOP_DEFAULT_FLL, cfg)
    b = build_fuzzy_kernel(FUZZY_LOOP_DEFAULT_FLL, cfg)
    a.align(0.0, 0.0, 0.0)
    b.align(0.0, 0.0, 0.0)
    ra = a.compute(sp=10.0, pv=0.0, dt=1.0)
    rb = b.compute(sp=-10.0, pv=0.0, dt=1.0)
    assert ra > 0.0 > rb  # entradas divergentes, saidas independentes
    assert a.eng is not b.eng  # SPEC secao 4.2: uma Engine por instancia, nunca compartilhada


def test_diag_exposto() -> None:
    k = _kernel()
    k.align(0.0, 0.0, 0.0)
    k.compute(sp=5.0, pv=0.0, dt=1.0)
    assert set(k.diag) >= {"e_n", "de_n", "du_n", "rule_fire_count"}
    assert k.diag["rule_fire_count"] >= 1.0
    assert abs(k.diag["e_n"] - 0.5) < 1e-9  # erro 5 * ke 0.1


def test_fll_quebrado_vira_broken_kernel() -> None:
    k = build_fuzzy_kernel(
        "Engine: lixo\nsintaxe invalida", FuzzyKernelCfg(ke=1.0, kde=0.0, ku=1.0)
    )
    assert k.validate() != []
    assert math.isnan(k.compute(sp=1.0, pv=0.0, dt=1.0))  # nunca calcula: shell segura OUT


def test_fll_fora_do_contrato_vira_broken_kernel() -> None:
    """F1 na camada de DEPLOY: o que passou no save mas degradou nasce OOS+CONFIG_ERROR."""
    fll = FUZZY_LOOP_DEFAULT_FLL.replace("lock-previous: false", "lock-previous: true")
    k = build_fuzzy_kernel(fll, FuzzyKernelCfg(ke=1.0, kde=0.0, ku=1.0))
    assert "FLL_LOCK_PREVIOUS_FORBIDDEN" in k.validate()


def test_validate_ganhos() -> None:
    assert "KU_MUST_BE_POSITIVE" in _kernel(ku=0.0).validate()
    assert "TF_DE_MUST_BE_POSITIVE" in _kernel(tf_de=0.0).validate()
    assert "KE_MUST_BE_POSITIVE" in _kernel(ke=0.0).validate()
    assert "KDE_MUST_BE_NON_NEGATIVE" in _kernel(kde=-1.0).validate()
    assert _kernel().validate() == []
