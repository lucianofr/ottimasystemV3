"""PidLoopConfig no graph_json (SPEC_PID secao 5; ADR-039 D11)."""

import pytest
from pydantic import ValidationError

from ottima_core.flowgraph.parse import LOOP_STRUCTURAL_KEYS, PidLoopConfig, loop_structural


def _minima(**over) -> dict:
    base = {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "kc": 2.0}
    base.update(over)
    return base


def test_config_minima_e_defaults() -> None:
    cfg = PidLoopConfig.model_validate(_minima())
    assert cfg.permitted == ["oos", "man", "auto"]
    assert cfg.sp_pv_track_in_man is True
    assert cfg.ti_seconds == 0.0 and cfg.beta == 1.0 and cfg.gamma == 0.0
    assert cfg.out_scale_lo == 0.0 and cfg.out_scale_hi == 100.0


def test_kc_negativo_ou_zero_rejeitado() -> None:
    with pytest.raises(ValidationError):
        PidLoopConfig.model_validate(_minima(kc=0.0))
    with pytest.raises(ValidationError):
        PidLoopConfig.model_validate(_minima(kc=-2.0))


def test_faixas_incoerentes_rejeitadas() -> None:
    with pytest.raises(ValidationError):
        PidLoopConfig.model_validate(_minima(sp_lo_lim=100.0, sp_hi_lim=0.0))
    with pytest.raises(ValidationError):
        PidLoopConfig.model_validate(_minima(out_startup=150.0))
    with pytest.raises(ValidationError):
        PidLoopConfig.model_validate(_minima(permitted=["auto", "banana"]))


def test_split_estrutural() -> None:
    functional = {"type": "pid_loop", "kc": 2.0, "out_scale_lo": 0.0, "out_scale_hi": 400.0}
    assert loop_structural(functional) == {
        "type": "pid_loop",
        "out_scale_lo": 0.0,
        "out_scale_hi": 400.0,
    }
    assert "kc" not in LOOP_STRUCTURAL_KEYS  # kc e classe de sintonia
