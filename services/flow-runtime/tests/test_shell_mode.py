"""Modos FF (ADR-039 secao 4.2): peso numerico maior = prioridade maior."""

from ottima_flow_runtime.blocks.shell.mode import (
    CALCULATING_MODES,
    MODE_NAMES,
    Mode,
    ModeBlock,
    mode_from_name,
)


def test_pesos_ff_dao_a_ordem_de_prioridade() -> None:
    assert Mode.OOS > Mode.IMAN > Mode.LO > Mode.MAN > Mode.AUTO > Mode.CAS > Mode.RCAS > Mode.ROUT


def test_permitted_e_mascara() -> None:
    mb = ModeBlock()
    assert mb.target is Mode.MAN and mb.actual is Mode.OOS
    assert Mode.AUTO & mb.permitted
    assert not (Mode.CAS & mb.permitted)  # cascata exige habilitacao explicita


def test_modos_calculantes() -> None:
    assert CALCULATING_MODES == frozenset({Mode.AUTO, Mode.CAS, Mode.RCAS})
    assert Mode.MAN not in CALCULATING_MODES


def test_nomes_ida_e_volta() -> None:
    for mode, name in MODE_NAMES.items():
        assert mode_from_name(name) is mode
    assert mode_from_name("auto") is Mode.AUTO
