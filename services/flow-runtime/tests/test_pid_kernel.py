"""PidKernel incremental (SPEC_PID secao 3): gap continuo, memoria de taxa, align."""

import math

from ottima_flow_runtime.blocks.kernels.pid import PidKernel, PidKernelCfg


def _cfg(**over) -> PidKernelCfg:
    base = PidKernelCfg(kc=2.0)
    for k, v in over.items():
        setattr(base, k, v)
    return base


def test_p_puro_e_derivada_do_erro_proporcional() -> None:
    k = PidKernel(_cfg(kc=2.0))
    k.align(50.0, 10.0, 10.0)  # erro zero
    # erro salta de 0 para 1 EU em dt=1: du/dt = KC * (ep-ep_prev)/dt = 2.0
    assert abs(k.compute(sp=11.0, pv=10.0, dt=1.0) - 2.0) < 1e-9
    # erro constante em seguida: P nao contribui mais
    assert abs(k.compute(sp=11.0, pv=10.0, dt=1.0)) < 1e-9


def test_integral_e_kc_vezes_erro_sobre_ti() -> None:
    k = PidKernel(_cfg(kc=3.0, ti=10.0))
    k.align(0.0, 5.0, 0.0)  # ep_prev ja com erro 5: P zera, sobra I
    assert abs(k.compute(sp=5.0, pv=0.0, dt=1.0) - 3.0 * 5.0 / 10.0) < 1e-9


def test_ti_zero_desliga_integral() -> None:
    k = PidKernel(_cfg(kc=3.0, ti=0.0))
    k.align(0.0, 5.0, 0.0)
    assert abs(k.compute(sp=5.0, pv=0.0, dt=1.0)) < 1e-9


def test_direct_acting_inverte_o_erro() -> None:
    rev = PidKernel(_cfg(kc=2.0, ti=10.0))
    dirt = PidKernel(_cfg(kc=2.0, ti=10.0, direct_acting=True))
    rev.align(0.0, 5.0, 0.0)
    dirt.align(0.0, 5.0, 0.0)
    assert rev.compute(5.0, 0.0, 1.0) == -dirt.compute(5.0, 0.0, 1.0)


def test_gap_transformacao_continua_e_path_independent() -> None:
    # g(x) com banda 2 e ganho 0.5: g(1)=0.5, g(2)=1.0, g(4)=1.0+2=3.0
    k = PidKernel(_cfg(kc=1.0, gap_band=2.0, gap_gain=0.5))
    assert abs(k._gap(1.0) - 0.5) < 1e-9
    assert abs(k._gap(-1.0) + 0.5) < 1e-9
    assert abs(k._gap(4.0) - 3.0) < 1e-9
    # continuidade na fronteira
    assert abs(k._gap(2.0 - 1e-9) - k._gap(2.0 + 1e-9)) < 1e-6

    # path-independence do P: entrar e sair da banda num ciclo fechado soma zero
    k.align(0.0, 0.0, 0.0)
    total = 0.0
    for pv in (0.0, -1.0, -3.0, -1.0, 0.0):  # erro 0 -> 1 -> 3 -> 1 -> 0
        total += k.compute(sp=0.0, pv=pv, dt=1.0) * 1.0
    assert abs(total) < 1e-9  # sem TI, ciclo fechado de erro nao deixa residuo


def test_derivada_com_memoria_de_taxa_sem_pico_apos_align() -> None:
    k = PidKernel(_cfg(kc=1.0, td=4.0, n=8.0))
    k.align(0.0, 0.0, 10.0)  # PV em movimento durante MAN...
    # primeiro scan apos retomada: termo D deve ser ~zero (r_prev zerado, edf igualado)
    assert abs(k.compute(sp=0.0, pv=10.0, dt=1.0)) < 1e-9


def test_gamma_zero_sem_chute_em_degrau_de_sp() -> None:
    k = PidKernel(_cfg(kc=1.0, td=4.0, n=8.0, ti=0.0, beta=0.0, gamma=0.0))
    k.align(0.0, 10.0, 10.0)
    # degrau de SP 10->20 com PV parado: com beta=0 e gamma=0 nada muda no P nem no D
    assert abs(k.compute(sp=20.0, pv=10.0, dt=1.0)) < 1e-9


def test_validate() -> None:
    assert PidKernel(_cfg()).validate() == []
    assert "KC_MUST_BE_POSITIVE" in PidKernel(_cfg(kc=0.0)).validate()
    assert "KC_MUST_BE_POSITIVE" in PidKernel(_cfg(kc=-1.0)).validate()
    assert "TI_MUST_BE_NON_NEGATIVE" in PidKernel(_cfg(ti=-1.0)).validate()
    assert "TD_MUST_BE_NON_NEGATIVE" in PidKernel(_cfg(td=-1.0)).validate()
    assert "N_MUST_BE_POSITIVE" in PidKernel(_cfg(td=1.0, n=0.0)).validate()
    assert "BETA_OUT_OF_RANGE" in PidKernel(_cfg(beta=1.5)).validate()
    assert "GAMMA_OUT_OF_RANGE" in PidKernel(_cfg(gamma=-0.1)).validate()
    assert "GAP_CONFIG_INVALID" in PidKernel(_cfg(gap_gain=2.0)).validate()
    assert not math.isnan(PidKernel(_cfg()).compute(1.0, 0.0, 1.0))
