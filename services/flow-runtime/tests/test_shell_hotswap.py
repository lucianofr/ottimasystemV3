"""S16: troca estrutural com a malha calculante aterrissa em MAN com u mantido."""

from shell_harness import EPS, EventosFake, amostra, bloco, cfg_padrao, passo

from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.kernel import StubKernel
from ottima_flow_runtime.blocks.shell.mode import Mode


async def test_s16_troca_estrutural_em_auto_aterrissa_man() -> None:
    velho = bloco(kernel=StubKernel(gain=0.3), out_startup=25.0)
    await passo(velho, 0.0, **{"in": amostra(50.0)})
    velho.write_sp(55.0)
    velho.write_target(Mode.AUTO)
    await passo(velho, 1.0, **{"in": amostra(50.0)})
    assert velho.mode.actual is Mode.AUTO

    eventos = EventosFake()
    carry = velho.carry_state()
    assert carry.was_calculating is True
    novo = BlockShell(
        "malha1",
        kernel=StubKernel(),
        cfg=cfg_padrao(out_scale_hi=400.0),  # mudanca estrutural
        emit_event=eventos,
        carry=carry,
    )
    await passo(novo, 2.0, **{"in": amostra(50.0)})
    assert novo.mode.actual is Mode.MAN
    assert abs(novo.u - velho.u) <= EPS  # u carregado
    assert "loop_alarm" in eventos.kinds()


async def test_carry_de_bloco_em_man_nao_alarma() -> None:
    velho = bloco()
    await passo(velho, 0.0, **{"in": amostra(50.0)})  # nasce MAN
    carry = velho.carry_state()
    assert carry.was_calculating is False
    eventos = EventosFake()
    novo = BlockShell(
        "malha1", kernel=StubKernel(), cfg=cfg_padrao(), emit_event=eventos, carry=carry
    )
    await passo(novo, 1.0, **{"in": amostra(50.0)})
    assert eventos.kinds().count("loop_alarm") == 0
