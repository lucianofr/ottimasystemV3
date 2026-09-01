"""Portoes sobre a superficie de controle (SPEC_FUZZY secao 5.3): falha bloqueia o save.

O equivalente fuzzy de conferir a sanidade dos ganhos de um PID antes de ligar a malha.
Propriedades sobre grade densa sao triviais de verificar; sobre motor de inferencia, nao — e
por isso que os portoes rodam sobre a superficie amostrada, nao sobre o `.fll`.

Os tetos sao DEFAULT DE SERVIDOR, deliberadamente nao configuraveis por flow: sao criterios
de seguranca, e a primeira coisa que um usuario apressado afrouxaria. Ajustar por evidencia
de campo, no codigo, com o teste ao lado.
"""

import numpy as np

TOL = 0.02
"""Tolerancia em unidades de `du_n` — 1% do universo normalizado de cada lado."""

GAIN_MAX = 8.0
"""d(du_n)/d(e_n) maximo: limita o ganho equivalente em malha fechada."""

STEP_MAX = 0.25
"""Descontinuidade maxima entre celulas vizinhas no eixo do erro."""

DEAD_ZONE_MAX = 0.3
"""Fracao maxima do eixo do erro com derivada ~zero fora da origem."""

_ORIGEM = 0.15
"""Meia-largura da vizinhanca da origem isenta do portao de zona morta."""


def run_lut_gates(grade: np.ndarray, *, direct_acting: bool = False) -> list[str]:
    """Codigos de portao reprovado; lista vazia significa superficie aceita.

    `grade[i][j]` e `du_n` em (`de_n` = eixo i, `e_n` = eixo j), como devolvido por
    `sample_surface`. Em acao direta a superficie esperada e a espelhada (o kernel aplica o
    sentido ao ERRO, ADR-039 secao 4.5), e por isso o portao avalia `-grade`.
    """
    if np.isnan(grade).any():
        return ["NO_NAN"]  # os demais portoes nao fazem sentido com buraco na base

    erros: list[str] = []
    g = -grade if direct_acting else grade
    n = g.shape[1]
    eixo_e = np.linspace(-1.0, 1.0, n)
    passo_e = float(eixo_e[1] - eixo_e[0])

    # SIGN_CONSISTENCY e avaliado na LINHA `de_n = 0`, nao na grade inteira.
    #
    # O texto literal da SPEC secao 5.3 ("du_n >= 0 para e_n > 0") reprovaria qualquer base
    # com regra de `de`, INCLUSIVE a default: com o erro subindo rapido a antecipacao
    # derivativa legitimamente manda recuar antes de `e_n` chegar a zero, e o cruzamento de
    # zero de `du_n` desloca proporcionalmente a `de_n` (medido no default: `de_n = 0.25`
    # cruza em `e_n = -0.125`; `de_n = 1`, em `-0.28`). Qualquer banda fixa de `de_n` em
    # volta de zero e arbitraria e insuficiente pelo mesmo motivo — o deslocamento e
    # proporcional, nao limitado.
    #
    # A linha `de_n = 0` e onde a lei tem de ser de erro puro, e e onde "empurrar para o
    # lado errado" e inequivoco. Uma regra de sinal invertido nao depende de `de` para
    # existir, portanto continua sendo pega ali (F4).
    #
    # Divergencia deliberada do texto da SPEC secao 5.3 — corrigida no mesmo commit.
    linha_erro_puro = g[g.shape[0] // 2, :]
    if (linha_erro_puro[eixo_e > TOL] < -TOL).any() or (linha_erro_puro[eixo_e < -TOL] > TOL).any():
        erros.append("SIGN_CONSISTENCY")

    derivada = np.diff(g, axis=1) / passo_e
    if (derivada < -TOL).any():
        erros.append("MONOTONIC_E")
    if float(derivada.max()) > GAIN_MAX:
        erros.append("BOUNDED_GAIN")

    fora_da_origem = np.abs((eixo_e[:-1] + eixo_e[1:]) / 2.0) > _ORIGEM
    mortas = (np.abs(derivada[:, fora_da_origem]) < TOL).mean(axis=1)
    if float(mortas.max()) > DEAD_ZONE_MAX:
        erros.append("NO_DEAD_ZONE")

    if float(np.abs(np.diff(g, axis=1)).max()) > STEP_MAX:
        erros.append("CONTINUITY")

    centro = n // 2
    if abs(float(g[centro, centro])) > TOL:
        erros.append("ORIGIN_ZERO")
    return erros
