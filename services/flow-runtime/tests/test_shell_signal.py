"""Signal (ADR-039 secao 4.1): status viaja com o valor; promocao implicita de PortSample."""

import math

from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.shell.signal import (
    Quality,
    Signal,
    Substatus,
    as_signal,
    make_signal,
)


def test_signal_e_um_portsample_e_ok_espelha_quality() -> None:
    s = make_signal(42.0, Quality.GOOD)
    assert isinstance(s, PortSample)
    assert s.v == 42.0 and s.ok is True
    assert s.is_good is True

    ruim = make_signal(1.0, Quality.BAD, substatus=Substatus.SENSOR_FAILURE)
    assert ruim.ok is False and ruim.is_good is False


def test_uncertain_e_tratado_como_good_na_v1() -> None:
    s = make_signal(7.0, Quality.UNCERTAIN)
    assert s.is_good is True and s.ok is True


def test_promocao_de_portsample_para_signal() -> None:
    bom = as_signal(PortSample(3.5, True))
    assert isinstance(bom, Signal) and bom.quality is Quality.GOOD and bom.v == 3.5

    ruim = as_signal(PortSample(1.0, False))
    assert ruim.quality is Quality.BAD and ruim.ok is False

    frio = as_signal(PortSample(None, False))
    assert frio.v is None and frio.quality is Quality.BAD


def test_promocao_de_signal_devolve_o_proprio_objeto() -> None:
    original = make_signal(1.0, Quality.GOOD, hi_limited=True)
    assert as_signal(original) is original


def test_init_request() -> None:
    ir = make_signal(50.0, Quality.GOOD, substatus=Substatus.INIT_REQUEST)
    assert ir.init_request is True
    assert make_signal(50.0, Quality.GOOD).init_request is False


def test_default_signal_e_bad_nan() -> None:
    s = Signal(v=math.nan, ok=False)
    assert s.quality is Quality.BAD and s.substatus is Substatus.NON_SPECIFIC
    assert s.hi_limited is False and s.lo_limited is False
