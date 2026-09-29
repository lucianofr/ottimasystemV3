"""Vocabulário de qualidade de porta (ADR-043; valores herdados do ADR-039)."""

from ottima_core.signal import Quality, Substatus


def test_polaridade_fieldbus_e_ordem_de_pior():
    # min() = pior: BAD < UNCERTAIN < GOOD — é a regra D6 da spec.
    assert (Quality.BAD, Quality.UNCERTAIN, Quality.GOOD) == (0, 1, 2)
    assert min(Quality.GOOD, Quality.UNCERTAIN) is Quality.UNCERTAIN
    assert min(Quality.UNCERTAIN, Quality.BAD) is Quality.BAD


def test_substatus_codigos_do_adr_039():
    assert [s.value for s in Substatus] == [0, 1, 2, 3, 4, 5, 6]
    assert Substatus.NON_SPECIFIC == 0
    assert Substatus.INIT_REQUEST == 1
