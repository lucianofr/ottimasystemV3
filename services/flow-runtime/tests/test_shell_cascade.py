"""S5/S6 + inversao de bits sob acao direta (ADR-039 secoes 4.3, 4.6, 4.7)."""

from shell_harness import EPS, amostra, cfg_padrao, passo

from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.kernel import StubKernel
from ottima_flow_runtime.blocks.shell.mode import Mode


def _par_cascata() -> tuple[BlockShell, BlockShell]:
    lic_cfg = cfg_padrao(out_scale_lo=0.0, out_scale_hi=400.0)  # OUT do LIC em m3/h
    lic_cfg.permitted = Mode.OOS | Mode.MAN | Mode.AUTO
    fic_cfg = cfg_padrao(sp_hi_lim=400.0, sp_lo_lim=0.0)
    fic_cfg.permitted = Mode.OOS | Mode.MAN | Mode.AUTO | Mode.CAS
    lic = BlockShell("lic", kernel=StubKernel(gain=0.2), cfg=lic_cfg)
    fic = BlockShell("fic", kernel=StubKernel(gain=0.2), cfg=fic_cfg)
    return lic, fic


async def _scan(lic, fic, t, *, lic_pv, fic_pv, bkcal_anterior):
    saida_lic = await passo(lic, t, **{"in": amostra(lic_pv), "bkcal_in": bkcal_anterior})
    saida_fic = await passo(fic, t, **{"in": amostra(fic_pv), "cas_in": saida_lic["out"]})
    return saida_lic, saida_fic, saida_fic["bkcal_out"]


async def test_s5_s6_fic_em_man_leva_lic_a_iman_e_volta_sem_degrau() -> None:
    lic, fic = _par_cascata()
    bkcal = PortSample(None, False)
    await _scan(lic, fic, 0.0, lic_pv=50.0, fic_pv=200.0, bkcal_anterior=bkcal)

    lic.write_sp(50.0)
    lic.write_target(Mode.AUTO)
    fic.write_target(Mode.CAS)
    for t in (1.0, 2.0, 3.0):
        _, _, bkcal = await _scan(lic, fic, t, lic_pv=50.0, fic_pv=200.0, bkcal_anterior=bkcal)
    assert fic.mode.actual is Mode.CAS
    assert lic.mode.actual is Mode.AUTO

    # S5: FIC vai a MAN -> bkcal_out emite IR -> LIC entra em IMAN em <= 2 scans
    fic.write_target(Mode.MAN)
    for t in (4.0, 5.0):
        _, _, bkcal = await _scan(lic, fic, t, lic_pv=50.0, fic_pv=200.0, bkcal_anterior=bkcal)
    assert lic.mode.actual is Mode.IMAN
    # LIC.out acompanha o SP de trabalho do FIC (unscale do bkcal, ADR-039 secao 4.4)
    assert abs(lic.u - (fic.sp / 400.0 * 100.0)) <= 1.0

    # S6: FIC volta a CAS -> LIC volta a AUTO... nao: LIC target=AUTO, entao IMAN cessa
    sp_fic_antes = fic.sp
    fic.write_target(Mode.CAS)
    for t in (6.0, 7.0, 8.0):
        _, _, bkcal = await _scan(lic, fic, t, lic_pv=50.0, fic_pv=200.0, bkcal_anterior=bkcal)
    assert lic.mode.actual is Mode.AUTO
    assert abs(fic.sp - sp_fic_antes) <= 400.0 * (EPS / 100.0) + 0.5  # sem degrau no SP do FIC


async def test_bits_de_limitacao_invertem_sob_acao_direta() -> None:
    cfg = cfg_padrao(direct_acting=True, out_startup=100.0)
    b = BlockShell("b", kernel=StubKernel(), cfg=cfg)
    saida = await passo(b, 0.0, **{"in": amostra(50.0)})
    bkcal = saida["bkcal_out"]
    assert bkcal.lo_limited is True and bkcal.hi_limited is False  # saturado no teto, invertido
