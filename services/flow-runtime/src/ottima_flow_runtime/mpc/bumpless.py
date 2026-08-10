"""Init bumpless — rotina única de armar/re-armar (spec F4 §3.6; TDD estrito).

Usada em MAN→AUTO, respawn e rebuild (worker é dono da chamada, F4b). Zera o erro de
predição inicial por construção: `bias := y_medido − C·x` corrige QUALQUER estado inicial
para que a predição em `t=0` bata exatamente na medida — mas a escolha do próprio `x`
ainda importa, porque é o que faz a primeira MV do `make_step` ficar perto do valor
vigente (o "sem salto" do aceite da fase, PRD §8-F4), não só a predição em `t=0`.

Consome `BuiltMpc.pair_init` (tarefa 2.2) para saber, por par HABILITADO da matriz
`models`, os nomes exatos dos estados no modelo agregado — nunca reconstrói a matriz a
partir de `MpcConfig` (que nem é parâmetro desta função, por assinatura do plano F4a).
"""

from collections.abc import Mapping

import numpy as np

from .builder import BuiltMpc, PairInit


def _pair_input_value(
    pair_init: PairInit, u_now: Mapping[str, float], d_now: Mapping[str, float]
) -> float:
    """Entrada vigente da coluna do par, JÁ em desvio do ponto de linearização — mesma
    coordenada em que `builder.py` alimenta o par. É o valor usado no `x_ss` e nos estados
    de atraso (constante, então o atraso não muda o valor em regime).

    Resolver com o valor absoluto poria `x_ss` em `K·u_op` e o bias no simétrico: a
    predição bateria em `t=0` por compensação, mas o estado inicial seria um ponto que a
    planta nunca ocupou — e numa linha integradora o erro nem é constante, é uma rampa."""
    absoluto = u_now[pair_init.col_id] if pair_init.is_mv_column else d_now[pair_init.col_id]
    return absoluto - pair_init.col_operating_point


def _steady_state(pair_init: PairInit, u_eff: float) -> np.ndarray:
    """`x = x_ss(u, d)` de um par autorregulável: resolve `(I−A)·x = B·u_eff` (spec §3.6-1).

    Nunca singular para SOPDT/1a-ordem exata: os pólos `a = e^(-Ts/tau)` de `discretize_sopdt`
    são sempre `< 1` em módulo (ZOH de um estágio estável), então `I−A` nunca é singular.
    """
    n = len(pair_init.state_names)
    identity_minus_a = np.eye(n) - pair_init.pair.a
    b_u = (pair_init.pair.b * u_eff).reshape(n)
    return np.linalg.solve(identity_minus_a, b_u)


def init_bumpless(
    built: BuiltMpc,
    u_now: Mapping[str, float],
    y_now: Mapping[str, float],
    d_now: Mapping[str, float],
) -> None:
    """Arma/re-arma o `BuiltMpc` sem salto (spec F4 §3.6).

    1. Pares autorreguláveis: estado em `x_ss(u_vigente, d_vigente)`.
    2. Pares integradores: estado de saída = CV medida (`y_now` da linha) — o integrador não
       tem estado estacionário, a medida é a verdade.
    3. Estados de atraso preenchidos com a entrada vigente do par.
    4. `u_prev := u_vigente` por MV.
    5. `bias := y_medido − C·x` por linha, escrito no `_tvp` de bias em TODO o horizonte
       (mesmo padrão do `dumax` em `build_mpc` — `set_tvp_fun` sempre devolve a mesma
       referência de `tvp_template`, então cada passo do horizonte precisa do próprio valor).
    6. `set_initial_guess()` no controller, depois de tudo preenchido.
    """
    model = built.mpc.model
    x0 = model.x(0.0)

    row_contribution: dict[str, float] = dict.fromkeys(built.prediction_rows, 0.0)

    for pair_init in built.pair_init:
        u_eff = _pair_input_value(pair_init, u_now, d_now)

        for name in pair_init.delay_state_names:
            x0[name] = u_eff

        if not pair_init.state_names:
            # Ganho puro sem estado (SOPDT duplamente degenerado) — contribui direto na
            # linha via `direct_gain`, sem estado `_x` para inicializar (builder.py).
            row_contribution[pair_init.row_id] += pair_init.direct_gain * u_eff
            continue

        if pair_init.kind == "integrating":
            # Sem estado estacionário (integrador puro) — a medida é a verdade (spec §3.6-2).
            state_values = np.full(len(pair_init.state_names), y_now[pair_init.row_id])
        else:
            state_values = _steady_state(pair_init, u_eff)

        for name, value in zip(pair_init.state_names, state_values, strict=True):
            x0[name] = float(value)

        contribution = pair_init.pair.c @ np.asarray(state_values, dtype=float)
        row_contribution[pair_init.row_id] += float(contribution[0])

    for mv_id, state_name in built.u_prev_state_name.items():
        x0[state_name] = u_now[mv_id]

    built.mpc.x0 = x0

    for row_id, bias_name in built.bias_tvp_name.items():
        bias_value = y_now[row_id] - row_contribution[row_id]
        built.tvp_template["_tvp", :, bias_name] = bias_value

    built.mpc.set_initial_guess()
