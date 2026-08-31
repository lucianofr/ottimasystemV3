"""P1-P14 (SPEC_PID secao 9). Processo simulado: 1a ordem pv' = (K*u_eu - pv)/tau.

Setup compartilhado por todos os casos: o SP inicial e escrito ANTES do scan de partida em
MAN para o kernel alinhar com erro zero — sem isso, o primeiro scan AUTO carrega um chute
proporcional fantasma (ep_prev alinhado em sp=0) que nao existe no bloco legado e quebra a
comparacao de P1/P2.
"""

import random

from shell_harness import EPS, amostra, passo

from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.kernels.pid import PidKernel, PidKernelCfg
from ottima_flow_runtime.blocks.pid import PidBlock
from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.config import ShellCfg
from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.blocks.shell.signal import Quality, make_signal


def _malha(kc: float = 2.0, ti: float = 20.0, td: float = 0.0, **shell_over) -> BlockShell:
    cfg = ShellCfg(sp_hi_lim=100.0, sp_lo_lim=0.0, max_dt=10.0, sp_pv_track_in_man=False)
    for k, v in shell_over.items():
        setattr(cfg, k, v)
    kernel = PidKernel(PidKernelCfg(kc=kc, ti=ti, td=td))
    return BlockShell("loop", kernel=kernel, cfg=cfg)


async def _engajar(m: BlockShell, pv0: float, sp_final: float) -> None:
    """Scan de partida em MAN com erro zero, depois SP e AUTO — o engate do legado."""
    m.write_sp(pv0)
    await passo(m, 0.0, **{"in": amostra(pv0)})
    m.write_sp(sp_final)
    m.write_target(Mode.AUTO)


async def _trajetorias(sp_final: float, disturbio: float = 0.0) -> tuple[list[float], list[float]]:
    """P1/P2: pid legado vs pid_loop na MESMA malha simulada, dt fixo = 1s."""
    legado = PidBlock(
        "legado",
        kc=2.0,
        ti_seconds=20.0,
        td_seconds=0.0,
        setpoint=50.0,
        output_min=0.0,
        output_max=100.0,
        auto_mode=True,
        proportional_on_measurement=False,
        differential_on_measurement=True,
        starting_output=30.0,
        ts_seconds=1.0,
    )
    malha = _malha(out_startup=30.0)
    pv_a = pv_b = 40.0
    tra_a: list[float] = []
    tra_b: list[float] = []
    await _engajar(malha, pv0=40.0, sp_final=sp_final)
    t = 0.0
    for i in range(300):
        t += 1.0
        d = disturbio if i >= 150 else 0.0
        saida_a = await legado.step(
            {"pv": PortSample(pv_a, True), "sp": PortSample(sp_final, True)}
        )
        await passo(malha, t, **{"in": amostra(pv_b)})
        u_a = saida_a["out"].v or 0.0
        u_b = malha.u
        pv_a += (u_a - pv_a) / 8.0 + d
        pv_b += (u_b - pv_b) / 8.0 + d
        tra_a.append(u_a)
        tra_b.append(u_b)
    return tra_a, tra_b


async def test_p1_degrau_de_sp_trajetorias_coincidem() -> None:
    a, b = await _trajetorias(sp_final=60.0)
    assert max(abs(x - y) for x, y in zip(a, b, strict=True)) <= 0.5  # 0.5% span / 300s


async def test_p4_ti_alterado_via_hotswap_sem_degrau() -> None:
    """P4: TI muda com a malha em AUTO e erro de 5% — nenhum salto alem do incremento
    normal (o integrador persiste; so o incremento usa o TI novo)."""
    b = _malha(kc=2.0, ti=20.0)
    b.write_sp(50.0)
    await passo(b, 0.0, **{"in": amostra(45.0)})  # erro 5% desde a partida
    b.write_target(Mode.AUTO)
    t = 0.0
    for _ in range(10):
        t += 1.0
        await passo(b, t, **{"in": amostra(45.0)})
    u_antes = b.u
    nova = ShellCfg(sp_hi_lim=100.0, sp_lo_lim=0.0, max_dt=10.0, sp_pv_track_in_man=False)
    b.apply_tuning(nova, PidKernelCfg(kc=2.0, ti=30.0))  # TI +50%
    t += 1.0
    await passo(b, t, **{"in": amostra(45.0)})
    assert abs(b.u - u_antes) <= 2.0 * 5.0 / 30.0 + EPS  # so o incremento I com TI novo


async def test_p8_saturacao_sai_do_limite_em_1_scan() -> None:
    m = _malha(kc=2.0, ti=5.0)
    t = 0.0
    m.write_sp(50.0)
    await passo(m, t, **{"in": amostra(45.0)})  # erro +5% desde a partida
    m.write_target(Mode.AUTO)
    for _ in range(60):
        t += 1.0
        await passo(m, t, **{"in": amostra(45.0)})
    assert m.u == 100.0  # saturada no limite alto
    m.write_sp(40.0)  # erro invertido (-10%)
    t += 1.0
    await passo(m, t, **{"in": amostra(45.0)})
    assert m.u < 100.0  # OUT deixa o limite em <= 1 scan


async def test_p2_disturbio_de_carga() -> None:
    a, b = await _trajetorias(sp_final=50.0, disturbio=1.0)
    assert max(abs(x - y) for x, y in zip(a, b, strict=True)) <= 0.5


async def test_p5_beta_zero_reduz_sobressinal() -> None:
    async def _overshoot(beta: float) -> float:
        m = _malha(kc=4.0, ti=10.0)
        m.kernel.cfg.beta = beta
        pv, pico, t = 40.0, 0.0, 0.0
        m.write_sp(40.0)
        await passo(m, t, **{"in": amostra(pv)})
        m.write_sp(60.0)
        m.write_target(Mode.AUTO)
        for _ in range(200):
            t += 1.0
            await passo(m, t, **{"in": amostra(pv)})
            pv += (m.u - pv) / 8.0
            pico = max(pico, pv)
        return pico - 60.0

    assert await _overshoot(0.0) < await _overshoot(1.0)


async def test_p6_p7_sem_pico_derivativo() -> None:
    m = _malha(kc=2.0, ti=0.0, td=8.0)
    t = 0.0
    m.write_sp(50.0)
    await passo(m, t, **{"in": amostra(50.0)})
    m.write_target(Mode.AUTO)
    t += 1.0
    await passo(m, t, **{"in": amostra(50.0)})
    u0 = m.u
    m.write_sp(70.0)  # P6: degrau de SP com GAMMA=0
    t += 1.0
    await passo(m, t, **{"in": amostra(50.0)})
    # o P sobe (beta=1), mas o D nao pode chutar: variacao limitada ao termo P
    assert abs(m.u - u0) <= 2.0 * 20.0 + EPS

    # P7: MAN durante rampa de PV, retomada sem pico
    m.write_target(Mode.MAN)
    pv = 50.0
    for _ in range(120):
        t += 1.0
        pv += 0.2
        await passo(m, t, **{"in": amostra(pv)})
    u_man = m.u
    m.write_target(Mode.AUTO)
    t += 1.0
    await passo(m, t, **{"in": amostra(pv)})
    assert abs(m.u - u_man) <= 1.0  # sem pico derivativo da rampa acumulada


async def test_p9_p10_p13_feedforward() -> None:
    m = _malha(ff_enable=True, ff_gain=1.0, out_startup=20.0)
    t = 0.0
    ff = make_signal(30.0, Quality.GOOD)
    m.write_sp(50.0)
    await passo(m, t, **{"in": amostra(50.0), "bias_in": ff})
    m.write_target(Mode.AUTO)
    t += 1.0
    await passo(m, t, **{"in": amostra(50.0), "bias_in": ff})
    u_ok = m.u
    # P9: FF degrada para BAD -> bias mantem ultimo bom, sem degrau
    t += 1.0
    await passo(m, t, **{"in": amostra(50.0), "bias_in": make_signal(999.0, Quality.BAD)})
    assert abs(m.u - u_ok) <= EPS
    # P10: MAN -> AUTO com FF != 0, sem degrau
    m.write_target(Mode.MAN)
    t += 1.0
    await passo(m, t, **{"in": amostra(50.0), "bias_in": ff})
    m.write_target(Mode.AUTO)
    t += 1.0
    await passo(m, t, **{"in": amostra(50.0), "bias_in": ff})
    assert abs(m.u - u_ok) <= EPS
    # P13: FF_GAIN muda via apply_tuning -> rebase de u_int, sem degrau
    nova = ShellCfg(
        sp_hi_lim=100.0,
        sp_lo_lim=0.0,
        max_dt=10.0,
        sp_pv_track_in_man=False,
        ff_enable=True,
        ff_gain=2.0,
    )
    m.apply_tuning(nova)
    t += 1.0
    await passo(m, t, **{"in": amostra(50.0), "bias_in": ff})
    assert abs(m.u - u_ok) <= EPS


async def test_p11_acao_direta_inverte_bits() -> None:
    m = _malha(out_startup=100.0, direct_acting=True)
    saida = await passo(m, 0.0, **{"in": amostra(50.0)})
    assert saida["bkcal_out"].lo_limited is True and saida["bkcal_out"].hi_limited is False


async def test_p12_gap_band_segura_ruido() -> None:
    rng = random.Random(7)
    m = _malha(kc=2.0, ti=30.0)
    m.kernel.cfg.gap_band = 5.0
    m.kernel.cfg.gap_gain = 0.1
    t = 0.0
    m.write_sp(50.0)
    await passo(m, t, **{"in": amostra(50.0)})
    m.write_target(Mode.AUTO)
    u0 = None
    for _ in range(100):
        t += 1.0
        ruido = rng.uniform(-2.0, 2.0)
        await passo(m, t, **{"in": amostra(50.0 + ruido)})
        if u0 is None:
            u0 = m.u
    assert abs(m.u - u0) <= 2.0  # praticamente imovel dentro da banda


async def test_p14_jitter() -> None:
    async def _regime(jitter: bool) -> float:
        rng = random.Random(3)
        m = _malha(kc=2.0, ti=15.0)
        pv, t, ultimo_dt = 40.0, 0.0, 1.0
        m.write_sp(40.0)
        await passo(m, t, **{"in": amostra(pv)})
        m.write_sp(60.0)
        m.write_target(Mode.AUTO)
        for _ in range(300):
            dt = 1.0 + (rng.uniform(-0.3, 0.3) if jitter else 0.0)
            t += dt
            pv += (m.u - pv) * ultimo_dt / 8.0
            await passo(m, t, **{"in": amostra(pv)})
            ultimo_dt = dt
        return m.u

    assert abs(await _regime(False) - await _regime(True)) <= 0.5
