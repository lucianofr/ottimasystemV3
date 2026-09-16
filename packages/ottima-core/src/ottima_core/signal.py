"""Vocabulário de qualidade de porta (ADR-043 D1; valores do ADR-039 §4.1).

Polaridade Fieldbus: BAD=0 < UNCERTAIN=1 < GOOD=2 — `min()` é "pior de".
NUNCA confundir com `OpcValue.quality` (0=good/1=uncertain/2=bad, spec F1 §3.2):
a tradução entre os dois vocabulários acontece SÓ no bloco OPC-Read e em
`scheduler._historized_value` (ADR-043 §4).
"""

from enum import IntEnum


class Quality(IntEnum):
    BAD = 0
    UNCERTAIN = 1
    GOOD = 2


class Substatus(IntEnum):
    NON_SPECIFIC = 0
    INIT_REQUEST = 1  # IR: o bloco a jusante não está aceitando cascata
    NOT_INVITED = 2  # reservado ao CONTROL_SELECTOR (ADR-039 §9)
    LOCAL_OVERRIDE = 3
    SENSOR_FAILURE = 4
    CONFIG_ERROR = 5
    DEVICE_FAILURE = 6
