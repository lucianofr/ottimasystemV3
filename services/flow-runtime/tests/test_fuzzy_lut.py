"""F8: LUT vs inferencia direta; F9 (slow): carga Mamdani a Ts=0.5s."""

import math
import random
import time

import pytest

from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL
from ottima_flow_runtime.blocks.kernels.fuzzy import FuzzyKernelCfg, build_fuzzy_kernel


def _mamdani() -> str:
    """Mesma base de regras em Mamdani/Centroid — o caminho caro da SPEC secao 4.3."""
    fll = (
        FUZZY_LOOP_DEFAULT_FLL.replace("aggregation: none", "aggregation: Maximum")
        .replace("defuzzifier: WeightedAverage", "defuzzifier: Centroid 100")
        .replace("implication: AlgebraicProduct", "implication: Minimum")
    )
    for termo in (
        "NG Constant -1.000",
        "NP Constant -0.500",
        "ZE Constant 0.000",
        "PP Constant 0.500",
        "PG Constant 1.000",
    ):
        nome, _, valor = termo.partition(" Constant ")
        v = float(valor)
        fll = fll.replace(
            f"term: {termo}", f"term: {nome} Triangle {v - 0.5:.3f} {v:.3f} {v + 0.5:.3f}"
        )
    return fll


MAMDANI = _mamdani()


def test_f8_lut_coincide_com_inferencia_em_10k_pontos() -> None:
    cfg = FuzzyKernelCfg(ke=1.0, kde=1.0, ku=100.0)  # e/de ja normalizados no teste
    direto = build_fuzzy_kernel(FUZZY_LOOP_DEFAULT_FLL, cfg)
    com_lut = build_fuzzy_kernel(
        FUZZY_LOOP_DEFAULT_FLL,
        FuzzyKernelCfg(ke=1.0, kde=1.0, ku=100.0, lut_enabled=True, lut_resolution=65),
    )
    rng = random.Random(1)
    pior = 0.0
    for _ in range(10_000):
        e = rng.uniform(-1.0, 1.0)
        direto.align(0.0, e, 0.0)
        com_lut.align(0.0, e, 0.0)
        a = direto.compute(sp=e, pv=0.0, dt=1.0)
        b = com_lut.compute(sp=e, pv=0.0, dt=1.0)
        pior = max(pior, abs(a - b))
    assert pior <= 0.5  # 0.5% do span (ku=100 -> du/dt em % e o proprio du_n*100)


def test_f8_lut_tambem_coincide_fora_da_linha_de_zero() -> None:
    """Varre as DUAS entradas: um bug de eixo trocado passaria calado no teste de `de = 0`."""
    cfg = FuzzyKernelCfg(ke=1.0, kde=1.0, ku=100.0)
    direto = build_fuzzy_kernel(MAMDANI, cfg)
    com_lut = build_fuzzy_kernel(
        MAMDANI,
        FuzzyKernelCfg(ke=1.0, kde=1.0, ku=100.0, lut_enabled=True, lut_resolution=129),
    )
    rng = random.Random(7)
    pior, maior_de_n = 0.0, 0.0
    for _ in range(2_000):
        # align fixa e_prev = e0; o scan seguinte com erro e1 da de = (e1 - e0)/dt e, com
        # tf_de = dt = 1, de_f = 0.5 * (e1 - e0). Escolher e0 e e1 independentes varre as
        # DUAS entradas, nao a diagonal.
        e0, e1 = rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0)
        for k in (direto, com_lut):
            k.align(0.0, e0, 0.0)
        a = direto.compute(sp=e1, pv=0.0, dt=1.0)
        b = com_lut.compute(sp=e1, pv=0.0, dt=1.0)
        pior = max(pior, abs(a - b))
        assert abs(direto.diag["de_n"] - com_lut.diag["de_n"]) < 1e-12
        maior_de_n = max(maior_de_n, abs(direto.diag["de_n"]))
    assert maior_de_n > 0.5  # a varredura de fato saiu da linha de_n = 0
    assert pior <= 1.0  # 1% do span: Mamdani/Centroid tem curvatura entre nos da grade


def test_lut_satura_nas_bordas_em_vez_de_indexar_fora() -> None:
    # ke alto: e_n satura em +1
    cfg = FuzzyKernelCfg(ke=10.0, kde=0.0, ku=1.0, lut_enabled=True)
    com_lut = build_fuzzy_kernel(FUZZY_LOOP_DEFAULT_FLL, cfg)
    com_lut.align(0.0, 0.0, 0.0)
    assert abs(com_lut.compute(sp=50.0, pv=0.0, dt=1.0) - 1.0) < 1e-6


def test_lut_com_buraco_propaga_nan() -> None:
    """A LUT nao pode 'consertar' regiao sem regra por interpolacao (F3 continua valendo)."""
    com_buraco = FUZZY_LOOP_DEFAULT_FLL
    for regra in ("  rule: if e is PP then du is PP\n", "  rule: if e is PG then du is PG\n"):
        com_buraco = com_buraco.replace(regra, "")
    k = build_fuzzy_kernel(com_buraco, FuzzyKernelCfg(ke=1.0, kde=0.0, ku=1.0, lut_enabled=True))
    k.align(0.0, 0.0, 0.0)
    assert math.isnan(k.compute(sp=1.0, pv=0.0, dt=1.0))


@pytest.mark.slow
def test_f9_50_blocos_mamdani_centroid_em_meio_segundo() -> None:
    cfg = FuzzyKernelCfg(ke=0.1, kde=0.0, ku=5.0)
    blocos = [build_fuzzy_kernel(MAMDANI, cfg) for _ in range(50)]
    assert all(b.validate() == [] for b in blocos)
    for b in blocos:
        b.align(0.0, 0.0, 0.0)
    inicio = time.perf_counter()
    for b in blocos:
        b.compute(sp=3.0, pv=0.0, dt=0.5)
    total = time.perf_counter() - inicio
    assert total < 0.5 * 0.30  # soma dos steps < 30% do periodo de 0.5 s


# --------------------------------------------------------------------------------------
# LUT como classe de SINTONIA (SPEC_FUZZY §6.3): ligar/desligar/reescalar in-place
# --------------------------------------------------------------------------------------


def _kernel_lut(**over):
    cfg = FuzzyKernelCfg(ke=0.05, kde=0.0, ku=2.0)
    for k, v in over.items():
        setattr(cfg, k, v)
    return build_fuzzy_kernel(FUZZY_LOOP_DEFAULT_FLL, cfg)


def test_rule_fire_count_ausente_com_lut_em_vez_de_nan() -> None:
    """Sem inferencia no scan nao existe grau de ativacao — a chave sai do diag.

    NaN ali viajaria como `null` num campo tipado `float` no espelho TS (mentira de tipo);
    ausente, o faceplate cai no proprio fallback e o contrato continua honesto.
    """
    k = _kernel_lut(lut_enabled=True)
    k.align(0.0, 0.0, 0.0)
    k.compute(sp=10.0, pv=0.0, dt=1.0)
    assert "rule_fire_count" not in k.diag
    assert set(k.diag) == {"e_n", "de_n", "du_n"}
    sem_lut = _kernel_lut()
    sem_lut.align(0.0, 0.0, 0.0)
    sem_lut.compute(sp=10.0, pv=0.0, dt=1.0)
    assert sem_lut.diag["rule_fire_count"] >= 1.0


def test_ligar_a_lut_por_sintonia_materializa_a_grade() -> None:
    """SPEC §6.3 lista LUT_ENABLED como classe de SINTONIA: in-place, sem re-instanciar.

    Regressao: a LUT morava na instancia e nao no `cfg`, entao `apply_tuning` trocava so o
    `cfg` e o toggle era silenciosamente inocuo — a config dizia LUT ligada e o runtime
    seguia inferindo.
    """
    k = _kernel_lut()
    assert k.lut is None
    k.cfg = FuzzyKernelCfg(ke=0.05, kde=0.0, ku=2.0, lut_enabled=True)
    assert k.lut is not None and k.lut.shape == (65, 65)


def test_reescalar_a_lut_por_sintonia_regenera_a_grade() -> None:
    k = _kernel_lut(lut_enabled=True, lut_resolution=33)
    assert k.lut is not None and k.lut.shape == (33, 33)
    k.cfg = FuzzyKernelCfg(ke=0.05, kde=0.0, ku=2.0, lut_enabled=True, lut_resolution=129)
    assert k.lut is not None and k.lut.shape == (129, 129)


def test_desligar_a_lut_volta_para_a_inferencia() -> None:
    k = _kernel_lut(lut_enabled=True)
    k.cfg = FuzzyKernelCfg(ke=0.05, kde=0.0, ku=2.0, lut_enabled=False)
    assert k.lut is None
    k.align(0.0, 0.0, 0.0)
    k.compute(sp=10.0, pv=0.0, dt=1.0)
    assert k.diag["rule_fire_count"] >= 1.0


def test_sintonia_que_nao_toca_a_lut_nao_paga_reamostragem() -> None:
    """Trocar KU nao pode regerar a superficie: a grade e a MESMA (identidade preservada)."""
    k = _kernel_lut(lut_enabled=True)
    antes = k.lut
    k.cfg = FuzzyKernelCfg(ke=0.05, kde=0.0, ku=9.0, lut_enabled=True)
    assert k.lut is antes
