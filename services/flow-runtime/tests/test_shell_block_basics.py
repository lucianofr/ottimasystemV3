"""BlockShell: partida, dt medido derivado de ts, SCAN_LOST (S14) e MAN basico."""

from shell_harness import EPS, EventosFake, amostra, bloco, passo

from ottima_flow_runtime.blocks.shell.block import CarriedState
from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.blocks.shell.signal import Signal


async def test_partida_fria_nasce_man_com_out_startup() -> None:
    b = bloco(out_startup=30.0)
    saida = await passo(b, 0.0, **{"in": amostra(50.0)})
    assert b.mode.target is Mode.MAN
    assert b.mode.actual is Mode.MAN
    assert abs(b.u - 30.0) <= EPS
    out = saida["out"]
    assert isinstance(out, Signal) and out.ok is True and out.v is not None


async def test_out_emite_eu_via_out_scale() -> None:
    b = bloco(out_startup=50.0, out_scale_lo=0.0, out_scale_hi=400.0)
    saida = await passo(b, 0.0, **{"in": amostra(10.0)})
    assert abs(saida["out"].v - 200.0) < 0.1  # 50% de (0..400)


async def test_primeiro_scan_nao_tem_dt_e_nao_explode() -> None:
    b = bloco()
    await passo(b, 0.0, **{"in": amostra(1.0)})  # sem dt: caminho de inicializacao
    await passo(b, 1.0, **{"in": amostra(1.0)})  # dt = 1.0 medido


async def test_s14_dt_zero_e_dt_gigante_viram_scan_lost() -> None:
    eventos = EventosFake()
    b = bloco(eventos=eventos, out_startup=40.0)
    await passo(b, 0.0, **{"in": amostra(5.0)})
    await passo(b, 0.0, **{"in": amostra(5.0)})  # dt = 0
    u_antes = b.u
    await passo(b, 200.0, **{"in": amostra(5.0)})  # dt = 200 > max_dt = 10
    assert abs(b.u - u_antes) <= EPS  # OUT mantido, sem excecao
    assert "loop_alarm" in eventos.kinds()


async def test_write_out_em_man_move_a_saida() -> None:
    b = bloco()
    await passo(b, 0.0, **{"in": amostra(5.0)})
    b.write_out(77.0)
    await passo(b, 1.0, **{"in": amostra(5.0)})
    assert abs(b.u - 77.0) <= EPS


async def test_carry_preserva_u_e_aterrissa_man_se_calculava() -> None:
    carry = CarriedState(u=63.0, sp_op=42.0, man_out=63.0, was_calculating=True)
    eventos = EventosFake()
    b = bloco(eventos=eventos)
    b2 = type(b)("malha1", kernel=b.kernel, cfg=b.cfg, emit_event=eventos, carry=carry)
    await passo(b2, 0.0, **{"in": amostra(5.0)})
    assert b2.mode.target is Mode.MAN and abs(b2.u - 63.0) <= EPS
    assert "loop_alarm" in eventos.kinds()  # aterrissagem estrutural avisada (S16)


async def test_pv_filtrado_por_pv_ftime() -> None:
    b = bloco(pv_ftime=9.0)  # alpha = 1/(9+1) = 0.1 com dt=1
    await passo(b, 0.0, **{"in": amostra(0.0)})
    await passo(b, 1.0, **{"in": amostra(10.0)})
    assert b.pv is not None and 0.5 < b.pv < 1.5  # ~1.0, nao 10.0


async def test_kernel_invalido_na_partida_forca_oos() -> None:
    from ottima_flow_runtime.blocks.shell.kernel import StubKernel

    ruim = StubKernel()
    ruim.errors.append("KU_MUST_BE_POSITIVE")
    b = bloco(kernel=ruim)
    saida = await passo(b, 0.0, **{"in": amostra(5.0)})
    assert b.mode.actual is Mode.OOS
    assert saida["out"].ok is False  # OOS emite BAD: opc_write suprime
