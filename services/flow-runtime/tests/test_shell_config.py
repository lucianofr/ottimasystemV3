"""ShellCfg e helpers de escala (ADR-039 secao 4.6)."""

from ottima_flow_runtime.blocks.shell.config import ShellCfg, clamp, scale_pct, unscale_pct
from ottima_flow_runtime.blocks.shell.mode import Mode


def test_defaults_seguros() -> None:
    cfg = ShellCfg(sp_hi_lim=100.0, sp_lo_lim=0.0, max_dt=10.0)
    assert cfg.out_lo_lim == 0.0 and cfg.out_hi_lim == 100.0
    assert cfg.out_scale_lo == 0.0 and cfg.out_scale_hi == 100.0  # identidade: % = EU
    assert cfg.permitted == Mode.OOS | Mode.MAN | Mode.AUTO
    assert cfg.sp_pv_track_in_man is True  # default ON (ADR-039 secao 4.9)
    assert cfg.shed_opt == "shed_to_auto" and cfg.shed_no_return is False
    assert cfg.out_startup == 0.0 and cfg.ff_enable is False


def test_clamp() -> None:
    assert clamp(150.0, 0.0, 100.0) == 100.0
    assert clamp(-1.0, 0.0, 100.0) == 0.0
    assert clamp(42.0, 0.0, 100.0) == 42.0


def test_escala_eu_pct_ida_e_volta() -> None:
    # OUT_SCALE (0, 400) m3/h: 50% -> 200 EU -> 50%
    assert unscale_pct(200.0, 0.0, 400.0) == 50.0
    assert scale_pct(50.0, 0.0, 400.0) == 200.0
    # identidade default
    assert scale_pct(37.5, 0.0, 100.0) == 37.5
