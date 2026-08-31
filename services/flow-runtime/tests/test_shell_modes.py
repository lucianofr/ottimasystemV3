"""Rebaixamento de modo (ADR-039 secao 4.3): shed, retorno automatico, no-return."""

from shell_harness import EPS, EventosFake, amostra, bloco, passo

from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.blocks.shell.signal import Quality, make_signal


def _cfg_cascata() -> dict:
    return {"permitted": Mode.OOS | Mode.MAN | Mode.AUTO | Mode.CAS | Mode.RCAS}


async def _ate_auto(b, t0=0.0):
    await passo(b, t0, **{"in": amostra(50.0)})
    b.write_target(Mode.AUTO)
    await passo(b, t0 + 1.0, **{"in": amostra(50.0)})


async def test_s7_cas_bad_rebaixa_em_1_scan_e_retorna_sozinho() -> None:
    eventos = EventosFake()
    b = bloco(eventos=eventos, **_cfg_cascata())
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.CAS)
    await passo(b, 1.0, **{"in": amostra(50.0), "cas_in": make_signal(60.0, Quality.GOOD)})
    assert b.mode.actual is Mode.CAS

    u_antes = b.u
    await passo(b, 2.0, **{"in": amostra(50.0), "cas_in": make_signal(60.0, Quality.BAD)})
    assert b.mode.actual is Mode.AUTO  # shed_to_auto default
    assert abs(b.u - u_antes) <= 1.0  # continuo (kernel P zero-erro; sem salto)
    assert "loop_shed" in eventos.kinds()

    await passo(b, 3.0, **{"in": amostra(50.0), "cas_in": make_signal(60.0, Quality.GOOD)})
    assert b.mode.actual is Mode.CAS  # retorno automatico: TARGET intocado


async def test_s17_shed_no_return_reescreve_target() -> None:
    b = bloco(shed_no_return=True, **_cfg_cascata())
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.CAS)
    await passo(b, 1.0, **{"in": amostra(50.0), "cas_in": make_signal(60.0, Quality.GOOD)})
    await passo(b, 2.0, **{"in": amostra(50.0), "cas_in": make_signal(60.0, Quality.BAD)})
    assert b.mode.target is Mode.AUTO  # TARGET reescrito
    await passo(b, 3.0, **{"in": amostra(50.0), "cas_in": make_signal(60.0, Quality.GOOD)})
    assert b.mode.actual is Mode.AUTO  # NAO volta a CAS sozinho


async def test_s8_rcas_bad_rebaixa() -> None:
    b = bloco(**_cfg_cascata())
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.RCAS)
    await passo(b, 1.0, **{"in": amostra(50.0), "rcas_in": make_signal(55.0, Quality.GOOD)})
    assert b.mode.actual is Mode.RCAS
    await passo(b, 2.0, **{"in": amostra(50.0), "rcas_in": make_signal(55.0, Quality.BAD)})
    assert b.mode.actual is Mode.AUTO


async def test_s10_pv_bad_forca_man_e_retomada_bumpless() -> None:
    b = bloco()
    await _ate_auto(b)
    u_antes = b.u
    await passo(b, 2.0, **{"in": amostra(50.0, ok=False)})
    assert b.mode.actual is Mode.MAN
    assert abs(b.u - u_antes) <= EPS  # OUT mantido
    await passo(b, 3.0, **{"in": amostra(50.0)})
    assert b.mode.actual is Mode.AUTO
    assert abs(b.u - u_antes) <= EPS  # retomada sem degrau (erro zero)


async def test_regra2_target_fora_de_permitted_cai_no_normal() -> None:
    b = bloco()
    await passo(b, 0.0, **{"in": amostra(50.0)})
    assert b.write_target(Mode.CAS) is False  # CAS nao esta em permitted default
    b.mode.target = Mode.CAS  # simula target invalido vindo de config antiga
    await passo(b, 1.0, **{"in": amostra(50.0)})
    assert b.mode.actual is b.mode.normal


async def test_lo_tem_prioridade_sobre_man() -> None:
    b = bloco(lo_val=15.0)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    await passo(b, 1.0, **{"in": amostra(50.0), "lo_in_d": amostra(True)})
    assert b.mode.actual is Mode.LO
    assert abs(b.u - 15.0) <= EPS
