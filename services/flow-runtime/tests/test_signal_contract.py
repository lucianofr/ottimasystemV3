"""Signal como contrato de porta (ADR-043 D1/D3/D5)."""

import pytest

from ottima_core.signal import Quality, Substatus
from ottima_flow_runtime.blocks.base import Signal, has_cold_input, null_outputs


def test_ok_derivado_uncertain_invalida_atuacao():
    # Emenda ADR-039 §4.1 (ADR-043 D3): só GOOD é ok — UNCERTAIN invalida como BAD.
    assert Signal(1.0, quality=Quality.GOOD).ok is True
    assert Signal(1.0, quality=Quality.UNCERTAIN).ok is False
    assert Signal(1.0, quality=Quality.BAD).ok is False


def test_defaults_sao_bad_non_specific_sem_limites():
    s = Signal(None)
    assert s.quality is Quality.BAD
    assert s.substatus is Substatus.NON_SPECIFIC
    assert (s.hi_limited, s.lo_limited) == (False, False)
    assert s.init_request is False


def test_cold_start_continua_por_v_none():
    assert has_cold_input({"in": Signal(None)}) is True
    assert has_cold_input({"in": Signal(0.0, quality=Quality.BAD)}) is False


def test_null_outputs_nulos_e_bad():
    outs = null_outputs(("a", "b"))
    assert all(s.v is None and s.quality is Quality.BAD for s in outs.values())


def test_quality_posicional_e_erro():
    # Defesa contra a corrupção silenciosa bool→IntEnum (ADR-043 §3): 60+ call sites
    # migraram de `PortSample(v, ok: bool)`; resíduo posicional tem de explodir.
    with pytest.raises(TypeError):
        Signal(1.0, Quality.GOOD)  # type: ignore[misc]
