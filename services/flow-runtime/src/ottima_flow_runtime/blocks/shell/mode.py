"""Modos do shell (ADR-039 secao 4.2). Bits identicos ao Foundation Fieldbus."""

from dataclasses import dataclass, field
from enum import IntFlag


class Mode(IntFlag):
    """Pesos FF. Valor numerico maior = prioridade maior."""

    OOS = 0x80  # out of service
    IMAN = 0x40  # initialization manual, imposto pelo bloco a jusante
    LO = 0x20  # local override, imposto por intertravamento
    MAN = 0x10  # operador escreve OUT
    AUTO = 0x08  # SP local
    CAS = 0x04  # SP de cas_in
    RCAS = 0x02  # SP de rcas_in (supervisor, MPC)
    ROUT = 0x01  # OUT de rout_in (supervisor)


CALCULATING_MODES: frozenset[Mode] = frozenset({Mode.AUTO, Mode.CAS, Mode.RCAS})

MODE_NAMES: dict[Mode, str] = {
    Mode.OOS: "oos",
    Mode.IMAN: "iman",
    Mode.LO: "lo",
    Mode.MAN: "man",
    Mode.AUTO: "auto",
    Mode.CAS: "cas",
    Mode.RCAS: "rcas",
    Mode.ROUT: "rout",
}

_BY_NAME = {name: mode for mode, name in MODE_NAMES.items()}


def mode_from_name(name: str) -> Mode:
    return _BY_NAME[name]


@dataclass(slots=True)
class ModeBlock:
    target: Mode = Mode.MAN  # TARGET nasce MAN: engajar e ato do operador (ADR-039 4.10)
    actual: Mode = Mode.OOS
    permitted: Mode = field(default=Mode.OOS | Mode.MAN | Mode.AUTO)
    normal: Mode = Mode.AUTO
