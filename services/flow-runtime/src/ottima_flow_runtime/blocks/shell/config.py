"""Configuracao runtime do shell (ADR-039 secoes 4.6, 4.8, 4.9).

Dataclass mutavel de proposito: a classe de sintonia do hot-swap (ADR-039 D11) troca este
objeto in-place via BlockShell.apply_tuning, preservando o estado do bloco.
"""

from dataclasses import dataclass

from ottima_flow_runtime.blocks.shell.mode import Mode


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def scale_pct(pct: float, lo: float, hi: float) -> float:
    """% do span -> EU."""
    return lo + (pct / 100.0) * (hi - lo)


def unscale_pct(v_eu: float, lo: float, hi: float) -> float:
    """EU -> % do span."""
    return (v_eu - lo) / (hi - lo) * 100.0


@dataclass(slots=True)
class ShellCfg:
    sp_hi_lim: float
    sp_lo_lim: float
    max_dt: float
    permitted: Mode = Mode.OOS | Mode.MAN | Mode.AUTO
    normal: Mode = Mode.AUTO
    shed_opt: str = "shed_to_auto"
    shed_no_return: bool = False
    direct_acting: bool = False
    sp_pv_track_in_man: bool = True
    use_pv_for_bkcal: bool = False
    track_enable: bool = False
    track_in_manual: bool = False
    sp_rate_up: float | None = None
    sp_rate_dn: float | None = None
    out_hi_lim: float = 100.0
    out_lo_lim: float = 0.0
    out_rate_up: float | None = None
    out_rate_dn: float | None = None
    out_scale_lo: float = 0.0
    out_scale_hi: float = 100.0
    out_startup: float = 0.0
    pv_ftime: float = 0.0
    trk_val: float = 0.0
    lo_val: float = 0.0
    ff_scale_lo: float = 0.0
    ff_scale_hi: float = 100.0
    ff_gain: float = 1.0
    ff_enable: bool = False
