"""Contratos de `mpc.discretize` contra a solução analítica (spec F4 §3.1; débito m2).

TDD estrito: a discretização por par é o alicerce numérico da montagem do-mpc (tarefa 2.2)
— cada teste compara a propagação discreta (`x[k+1] = A x[k] + B u[k]`, `y[k] = C x[k]`,
avançando o estado antes de ler a saída — ver docstring de `mpc.discretize` para a prova de
que essa ordem coincide, termo a termo, com a recorrência "atualiza-e-emite" do bloco TFS de
simulação) contra a solução fechada do modelo contínuo amostrada nos mesmos instantes, ou
contra invariantes exatos (IOPDT, tempo morto, banker's, limiar de passagem direta — mesmo
limiar do TFS).
"""

import math
from collections import deque

import numpy as np
import pytest

from ottima_flow_runtime.mpc.discretize import (
    DIRECT_PASS_RATIO,
    PairSS,
    discretize_iopdt,
    discretize_sopdt,
)


def propagate(pair: PairSS, u: float, n: int) -> list[float]:
    """Propaga `n` amostras com entrada constante `u`; devolve `y[1..n]`.

    Avança o estado (`x <- A x + B u`) e só então lê `C @ x` — é essa ordem que faz `y[k]`
    coincidir com a k-ésima chamada "atualiza-e-emite" do TFS (ver `mpc.discretize`).
    """
    x = np.zeros((pair.a.shape[0], 1))
    out: list[float] = []
    for _ in range(n):
        x = pair.a @ x + pair.b * u
        out.append(float((pair.c @ x)[0, 0]))
    return out


def first_order(K: float, tau: float, t: float) -> float:
    return K * (1.0 - math.exp(-t / tau))


def second_order(K: float, tau1: float, tau2: float, t: float) -> float:
    numerator = tau1 * math.exp(-t / tau1) - tau2 * math.exp(-t / tau2)
    return K * (1.0 - numerator / (tau1 - tau2))


# --------------------------------------------------------------------------------------
# SOPDT — dois estágios ativos vs solução analítica
# --------------------------------------------------------------------------------------


def test_sopdt_step_transiente_dentro_de_1_por_cento():
    """Cascata de dois ZOH exatos != ZOH exato do produto do continuo — mesmo efeito do
    TFS (`ottima_flow_runtime.blocks.tfs`, mesmos parâmetros): erro limitado a ~1% de K no
    transiente, não exato amostra a amostra. TFS documenta pico de erro 0,0154 (0,77% de K)
    em t=9s para tau1=20, tau2=5, K=2, Ts=0,5 — mesmos valores usados aqui.
    """
    K, tau1, tau2, ts = 2.0, 20.0, 5.0, 0.5
    pair = discretize_sopdt(K=K, tau1=tau1, tau2=tau2, theta=0.0, ts=ts)

    got = propagate(pair, u=1.0, n=400)

    for n, value in enumerate(got, start=1):
        assert value == pytest.approx(second_order(K, tau1, tau2, n * ts), abs=0.02)


def test_sopdt_step_regime_permanente_exato():
    """Em regime (muitas amostras) o erro cai a ruído de ponto flutuante — <1e-6."""
    K, tau1, tau2, ts = 2.0, 20.0, 5.0, 0.5
    pair = discretize_sopdt(K=K, tau1=tau1, tau2=tau2, theta=0.0, ts=ts)

    got = propagate(pair, u=1.0, n=3000)

    assert got[-1] == pytest.approx(K, abs=1e-6)


def test_sopdt_polos_sao_e_menos_ts_sobre_tau():
    """Autovalores de `a` (triangular inferior: a própria diagonal) = pólos ZOH-exatos por
    estágio — a "forma canônica" pedida pela spec F4 §3.1."""
    ts = 0.5
    pair = discretize_sopdt(K=1.0, tau1=20.0, tau2=5.0, theta=0.0, ts=ts)

    poles = sorted(np.linalg.eigvals(pair.a).real)
    expected = sorted([math.exp(-ts / 20.0), math.exp(-ts / 5.0)])
    assert poles == pytest.approx(expected, rel=1e-12)


# --------------------------------------------------------------------------------------
# tau2 = 0 -> 1a ordem exata
# --------------------------------------------------------------------------------------


def test_tau2_zero_e_primeira_ordem_zoh_exata():
    K, tau1, ts = 3.0, 12.0, 0.5
    pair = discretize_sopdt(K=K, tau1=tau1, tau2=0.0, theta=0.0, ts=ts)

    assert pair.a.shape == (1, 1)
    got = propagate(pair, u=1.0, n=80)

    for n, value in enumerate(got, start=1):
        assert value == pytest.approx(first_order(K, tau1, n * ts), rel=1e-12)


# --------------------------------------------------------------------------------------
# Limiar Ts/DIRECT_PASS_RATIO -> passagem direta (mesmo limiar do TFS)
# --------------------------------------------------------------------------------------


def test_limiar_tau2_desprezivel_degrada_para_1a_ordem_do_estagio_1():
    K, tau1, ts = 2.0, 20.0, 0.5
    pair = discretize_sopdt(K=K, tau1=tau1, tau2=ts / 100, theta=0.0, ts=ts)

    assert pair.a.shape == (1, 1)
    got = propagate(pair, u=1.0, n=80)
    for n, value in enumerate(got, start=1):
        assert value == pytest.approx(first_order(K, tau1, n * ts), rel=1e-12)


def test_limiar_tau1_desprezivel_degrada_para_1a_ordem_do_estagio_2():
    """O estágio que some (tau1) deixa a entrada alimentar o outro estágio direto — a
    resposta passa a ser a do estágio 2 sozinho, com o ganho K (mesma regra do TFS)."""
    K, tau2, ts = 2.0, 20.0, 0.5
    pair = discretize_sopdt(K=K, tau1=ts / 100, tau2=tau2, theta=0.0, ts=ts)

    assert pair.a.shape == (1, 1)
    got = propagate(pair, u=1.0, n=80)
    for n, value in enumerate(got, start=1):
        assert value == pytest.approx(first_order(K, tau2, n * ts), rel=1e-12)


def test_limiar_e_o_mesmo_valor_do_tfs():
    from ottima_flow_runtime.blocks.tfs import DIRECT_PASS_RATIO as TFS_RATIO

    assert DIRECT_PASS_RATIO == TFS_RATIO


# --------------------------------------------------------------------------------------
# IOPDT — integrador retangular exato
# --------------------------------------------------------------------------------------


def test_iopdt_rampa_exata():
    Ki, ts = 0.25, 0.5
    pair = discretize_iopdt(Ki=Ki, theta=0.0, ts=ts)

    assert pair.a.shape == (1, 1)
    got = propagate(pair, u=2.0, n=50)

    for n, value in enumerate(got, start=1):
        assert value == pytest.approx(Ki * ts * 2.0 * n, rel=1e-12)


def test_iopdt_incremento_por_amostra_e_ki_ts_u():
    Ki, u, ts = 0.4, 3.0, 1.0
    pair = discretize_iopdt(Ki=Ki, theta=0.0, ts=ts)

    got = propagate(pair, u=u, n=5)

    # `strict=False` é deliberado: got e got[1:] têm, por construção, um elemento de
    # diferença — o mesmo idioma de `test_tfs.py::test_segunda_ordem_segue_a_solucao_analitica`.
    increments = [b - a for a, b in zip(got, got[1:], strict=False)]
    assert increments == pytest.approx([Ki * ts * u] * 4, rel=1e-12)


# --------------------------------------------------------------------------------------
# Tempo morto: delay = round(theta/ts) amostras (banker's)
# --------------------------------------------------------------------------------------


def delayed_propagate(pair: PairSS, u: float, n: int) -> list[float]:
    """Combina `pair.delay` (fila de atraso na entrada) com a propagação de estado — a
    mesma composição que a montagem (2.2) fará como shift register."""
    queue: deque[float] = deque([0.0] * pair.delay)
    x = np.zeros((pair.a.shape[0], 1))
    out: list[float] = []
    for _ in range(n):
        queue.append(u)
        delayed_u = queue.popleft()
        x = pair.a @ x + pair.b * delayed_u
        out.append(float((pair.c @ x)[0, 0]))
    return out


def test_tempo_morto_desloca_exatamente_delay_amostras():
    K, tau1, ts = 2.0, 20.0, 0.5
    theta = 5 * ts
    plain = discretize_sopdt(K=K, tau1=tau1, tau2=0.0, theta=0.0, ts=ts)
    delayed = discretize_sopdt(K=K, tau1=tau1, tau2=0.0, theta=theta, ts=ts)

    assert delayed.delay == 5
    plain_series = propagate(plain, u=1.0, n=60)
    delayed_series = delayed_propagate(delayed, u=1.0, n=60)

    assert delayed_series[5:] == pytest.approx(plain_series[:-5], rel=1e-12)
    assert delayed_series[:5] == pytest.approx([0.0] * 5, abs=1e-12)


def test_round_banker_2_5_arredonda_para_2():
    """`round(2.5) == 2`, não 3 — half-even, mesma convenção do TFS e da validação (nota
    normativa em `mpc.discretize._delay_samples`; spec F4 §3.1, débito m2)."""
    pair = discretize_iopdt(Ki=1.0, theta=2.5, ts=1.0)
    assert pair.delay == 2


def test_round_banker_3_5_arredonda_para_4():
    pair = discretize_iopdt(Ki=1.0, theta=3.5, ts=1.0)
    assert pair.delay == 4
