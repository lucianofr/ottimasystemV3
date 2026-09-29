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
    eu_gain_params,
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


def test_ifopdt_tau1_zero_e_identico_ao_integrador_puro():
    """`tau1` ausente/zero tem de reproduzir o IOPDT puro bit a bit — todo config gravado
    antes do campo continua valendo (1 estado, mesma série)."""
    puro = discretize_iopdt(Ki=0.25, theta=0.0, ts=0.5)
    com_campo = discretize_iopdt(Ki=0.25, theta=0.0, ts=0.5, tau1=0.0)

    assert com_campo.a.shape == (1, 1)
    assert propagate(com_campo, u=2.0, n=20) == pytest.approx(propagate(puro, u=2.0, n=20))


def test_ifopdt_e_o_integrador_alimentado_pelo_lag_de_1a_ordem():
    """IFOPDT `Ki·e^(-θs)/(s·(τ1·s+1))`: estágio de 1a ordem exato no ZOH em série com o
    integrador retangular, mesma composição "atualiza-e-emite" do SOPDT (o acumulador
    consome a saída JÁ atualizada do estágio). Série fechada: com `a1 = e^(-Ts/τ1)`,
    `x1[k] = u·(1−a1^k)` e `y[k] = Ki·Ts·u·(k − a1·(1−a1^k)/(1−a1))`."""
    Ki, tau1, ts, u = 0.4, 10.0, 1.0, 2.0
    pair = discretize_iopdt(Ki=Ki, theta=0.0, ts=ts, tau1=tau1)

    assert pair.a.shape == (2, 2)
    a1 = math.exp(-ts / tau1)
    got = propagate(pair, u=u, n=80)
    for k, value in enumerate(got, start=1):
        esperado = Ki * ts * u * (k - a1 * (1 - a1**k) / (1 - a1))
        assert value == pytest.approx(esperado, rel=1e-12)


def test_ifopdt_taxa_assintotica_e_a_do_integrador_puro():
    """O lag atrasa a rampa, nunca muda a taxa de regime: o incremento por amostra converge
    para `Ki·Ts·u` (= a taxa `Ki` por segundo, a base declarada do campo)."""
    Ki, ts, u = 0.4, 1.0, 2.0
    got = propagate(discretize_iopdt(Ki=Ki, theta=0.0, ts=ts, tau1=10.0), u=u, n=600)

    assert got[-1] - got[-2] == pytest.approx(Ki * ts * u, rel=1e-12)
    # ... e fica ATRÁS do integrador puro pelo transiente do lag (nunca à frente).
    puro = propagate(discretize_iopdt(Ki=Ki, theta=0.0, ts=ts), u=u, n=600)
    assert got[-1] < puro[-1]


def test_ifopdt_polos_sao_o_integrador_e_o_lag():
    ts, tau1 = 0.5, 20.0
    poles = sorted(np.linalg.eigvals(discretize_iopdt(1.0, 0.0, ts, tau1=tau1).a).real)

    assert poles == pytest.approx(sorted([1.0, math.exp(-ts / tau1)]), rel=1e-12)


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


def test_ki_do_campo_e_taxa_por_1pct_da_coluna() -> None:
    """Base do campo `Ki` é **%/%/s** (RF-602, reafirmada em 2026-09-12): 1% da coluna rampa
    a linha a `Ki` %/s, sem ÷100 nenhum. Caso de campo (flow 987, linha de nível
    `cv_ij93`×`mv_chns`, Ki=0,00379): 1 ponto de FV-201 move o nível a 0,00379 %/s, e a
    coluna inteira (100%) a 0,379 %/s. Fixa a razão de spans PURA no caminho
    config→discretização, junto do `·ts`."""
    params = eu_gain_params(
        {"Ki": 0.00379, "theta": 0.0}, kind="integrating", row_span=100.0, col_span=100.0
    )
    ts = 2.0
    por_1pct = propagate(discretize_iopdt(params["Ki"], params["theta"], ts=ts), u=1.0, n=10)
    assert por_1pct[-1] / (ts * len(por_1pct)) == pytest.approx(0.00379, rel=1e-12)

    em_100pct = propagate(discretize_iopdt(params["Ki"], params["theta"], ts=ts), u=100.0, n=10)
    assert em_100pct[-1] / (ts * len(em_100pct)) == pytest.approx(0.379, rel=1e-12)


def test_ganho_integrador_e_invariante_de_base_de_tempo() -> None:
    """Contrato de unidade do campo Ki (rótulo da UI: "Ki (%/%/s)", base: % do span da linha
    por segundo por 1% do span da coluna): o caminho config→modelo trata Ki como taxa POR
    SEGUNDO, então a rampa de saída por unidade de TEMPO não pode depender do Ts de
    amostragem. Discretizar o MESMO Ki com ts=1 s e ts=2 s tem de dar a mesma taxa %/s
    (y(t)/t igual nos dois); só o incremento POR AMOSTRA muda (Ki·ts). Se alguém trocar a
    base de tempo (Ki por minuto, ou esquecer o `·ts`), as duas taxas divergem e este teste
    falha."""
    params = eu_gain_params(
        {"Ki": 0.5, "theta": 0.0}, kind="integrating", row_span=100.0, col_span=100.0
    )
    u_degrau = 1.0  # 1% do span da coluna — a base declarada do campo (%/%/s)

    taxa: dict[float, float] = {}
    for ts in (1.0, 2.0):
        got = propagate(discretize_iopdt(params["Ki"], params["theta"], ts=ts), u=u_degrau, n=6)
        tempo_total = ts * len(got)
        taxa[ts] = got[-1] / tempo_total  # % por segundo

    assert taxa[1.0] == pytest.approx(0.5, rel=1e-12)
    assert taxa[2.0] == pytest.approx(taxa[1.0], rel=1e-12)
