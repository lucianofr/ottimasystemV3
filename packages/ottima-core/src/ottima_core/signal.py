"""Vocabulários de qualidade — os DOIS dialetos, num arquivo só (ADR-043 §4).

`Quality` (porta, ADR-039 §4.1): polaridade Fieldbus, BAD=0 < UNCERTAIN=1 < GOOD=2 —
ordenada por utilidade, "pior de" é `min()`.
`OpcQuality` (barramento/histórico, spec F1 §3.2): polaridade OPC, GOOD=0 < BAD=2 —
herdada do StatusCode (0 = sem erro), "pior de" é `max()`.
NUNCA misturar: a tradução entre os dois acontece SÓ no bloco OPC-Read e em
`scheduler._historized_value` (ADR-043 §4); `OpcValue.quality` rejeita enum de porta.
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


class OpcQuality(IntEnum):
    """Qualidade OPC (spec F1 §3.2): 0=good, 1=uncertain, 2=bad — a INVERSA de `Quality`.

    Valores imutáveis: estão gravados em `samples.quality` (até 1 mês de hypertable) e no
    JSON dos canais `opc.values.*`/`calc.values`/`flow.values`. Definição ÚNICA do lado OPC:
    opc-worker, recorder, calc-worker e flow-runtime importam daqui — nenhum literal 0/1/2
    de qualidade OPC fora deste arquivo.
    """

    GOOD = 0
    UNCERTAIN = 1
    BAD = 2
