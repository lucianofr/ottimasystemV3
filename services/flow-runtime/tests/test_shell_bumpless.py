"""S1-S4, S9, S12: bumpless, tracking, anti-windup, kernel NaN (ADR-039 secao 7)."""

import math

from shell_harness import EPS, EventosFake, amostra, bloco, passo

from ottima_flow_runtime.blocks.shell.kernel import StubKernel
from ottima_flow_runtime.blocks.shell.mode import Mode


async def test_s1_man_para_auto_sem_degrau_com_pv_diferente_de_sp() -> None:
    k = StubKernel(gain=0.0)  # kernel quieto: qualquer degrau viria do shell
    b = bloco(kernel=k, out_startup=40.0)
    await passo(b, 0.0, **{"in": amostra(30.0)})
    b.write_sp(70.0)  # SP != PV
    b.write_target(Mode.AUTO)
    await passo(b, 1.0, **{"in": amostra(30.0)})
    assert b.mode.actual is Mode.AUTO
    assert abs(b.u - 40.0) <= EPS  # primeiro scan em Auto: sem salto


async def test_s2_auto_man_auto_120s_sem_degrau() -> None:
    k = StubKernel(gain=0.1)
    b = bloco(kernel=k, out_startup=40.0, sp_pv_track_in_man=False)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_sp(50.0)
    b.write_target(Mode.AUTO)
    t = 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    u_auto = b.u
    b.write_target(Mode.MAN)
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    assert abs(b.u - u_auto) <= EPS  # entrada em MAN herda u
    for _ in range(120):
        t += 1.0
        await passo(b, t, **{"in": amostra(50.0)})
    b.write_target(Mode.AUTO)
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    assert abs(b.u - u_auto) <= EPS


async def test_s3_tracking_engata_e_solta_sem_degrau() -> None:
    b = bloco(track_enable=True, trk_val=80.0, out_startup=20.0)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_sp(50.0)
    b.write_target(Mode.AUTO)
    await passo(b, 1.0, **{"in": amostra(50.0)})
    await passo(b, 2.0, **{"in": amostra(50.0), "trk_in_d": amostra(True)})
    assert abs(b.u - 80.0) <= EPS  # OUT == TRK_VAL durante
    await passo(b, 3.0, **{"in": amostra(50.0), "trk_in_d": amostra(False)})
    assert abs(b.u - 80.0) <= EPS  # solta a partir de 80, sem salto


async def test_s4_anti_windup_sai_da_saturacao_em_1_scan() -> None:
    k = StubKernel()
    b = bloco(kernel=k, out_startup=50.0)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.AUTO)
    k.rate = 50.0  # empurra forte para cima
    t = 0.0
    for _ in range(20):
        t += 1.0
        await passo(b, t, **{"in": amostra(50.0)})
    assert b.u == 100.0  # saturado no teto
    k.rate = -10.0  # inverte
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    assert b.u < 100.0 - EPS  # deixou o limite em <= 1 scan: integrador nao acumulou


async def test_s9_local_override_retoma_de_lo_val() -> None:
    b = bloco(lo_val=10.0, out_startup=60.0)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    await passo(b, 1.0, **{"in": amostra(50.0), "lo_in_d": amostra(True)})
    assert abs(b.u - 10.0) <= EPS
    await passo(b, 2.0, **{"in": amostra(50.0), "lo_in_d": amostra(False)})
    assert abs(b.u - 10.0) <= EPS  # retoma DE lo_val, sem degrau


async def test_s12_kernel_nan_segura_out_e_alarma() -> None:
    eventos = EventosFake()
    k = StubKernel(gain=1.0)
    b = bloco(kernel=k, eventos=eventos, out_startup=45.0)
    await passo(b, 0.0, **{"in": amostra(40.0)})
    b.write_sp(40.0)
    b.write_target(Mode.AUTO)
    await passo(b, 1.0, **{"in": amostra(40.0)})
    modo_antes, u_antes = b.mode.actual, b.u
    k.rate = math.nan
    await passo(b, 2.0, **{"in": amostra(40.0)})
    assert abs(b.u - u_antes) <= EPS
    assert b.mode.actual is modo_antes  # ACTUAL inalterado
    assert "loop_alarm" in eventos.kinds()
    assert len(k.align_calls) > 0  # kernel realinhado no scan invalido


async def test_s15_apply_tuning_em_auto_sem_degrau() -> None:
    from shell_harness import cfg_padrao

    k = StubKernel(gain=0.5)
    b = bloco(kernel=k, out_startup=35.0)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_sp(50.0)
    b.write_target(Mode.AUTO)
    await passo(b, 1.0, **{"in": amostra(50.0)})
    u_antes = b.u
    nova = cfg_padrao(out_rate_up=5.0)  # classe de sintonia
    b.apply_tuning(nova)
    await passo(b, 2.0, **{"in": amostra(50.0)})
    assert abs(b.u - u_antes) <= EPS
    assert b.mode.actual is Mode.AUTO  # modo preservado
