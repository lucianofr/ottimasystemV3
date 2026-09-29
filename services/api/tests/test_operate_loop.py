"""Validacao estatica dos comandos de malha (ADR-039 4.10): PERMITTED e faixas na API."""

import pytest
from fastapi import HTTPException

from ottima_api.routers.operate import LoopModeCommand, LoopValueCommand, _validar_comando_loop
from ottima_core.flowgraph.fll_defaults import fuzzy_loop_default_fll
from ottima_core.flowgraph.parse import FuzzyLoopConfig, PidLoopConfig


def _cfg(**over) -> PidLoopConfig:
    base = {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "kc": 2.0}
    base.update(over)
    return PidLoopConfig.model_validate(base)


def test_target_fora_de_permitted_e_recusado() -> None:
    with pytest.raises(HTTPException) as exc:
        _validar_comando_loop(_cfg(), "loop_mode", LoopModeCommand(target="cas"))
    assert exc.value.status_code == 422


def test_sp_fora_da_faixa_e_recusado() -> None:
    with pytest.raises(HTTPException):
        _validar_comando_loop(_cfg(), "loop_sp", LoopValueCommand(value=150.0))
    with pytest.raises(HTTPException):
        _validar_comando_loop(_cfg(), "loop_sp", LoopValueCommand(value=-1.0))


def test_out_fora_da_faixa_e_recusado() -> None:
    with pytest.raises(HTTPException):
        _validar_comando_loop(_cfg(), "loop_out", LoopValueCommand(value=101.0))


def test_comandos_validos_passam() -> None:
    _validar_comando_loop(_cfg(), "loop_mode", LoopModeCommand(target="auto"))
    _validar_comando_loop(_cfg(), "loop_sp", LoopValueCommand(value=50.0))
    _validar_comando_loop(_cfg(), "loop_out", LoopValueCommand(value=99.0))


def test_target_valido_fora_de_permitted_e_recusado() -> None:
    # 'cas' e modo do vocabulario, mas nao esta em permitted
    with pytest.raises(HTTPException):
        _validar_comando_loop(
            _cfg(permitted=["oos", "man", "auto"]), "loop_mode", LoopModeCommand(target="cas")
        )
    # e passa quando esta
    _validar_comando_loop(
        _cfg(permitted=["oos", "man", "auto", "cas"]), "loop_mode", LoopModeCommand(target="cas")
    )


def _cfg_fuzzy(**over) -> FuzzyLoopConfig:
    base = {
        "sp_hi_lim": 100.0,
        "sp_lo_lim": 0.0,
        "ke": 0.05,
        "ku": 2.0,
        "n_loops": 2,
        "fll": fuzzy_loop_default_fll(2),
    }
    base.update(over)
    return FuzzyLoopConfig.model_validate(base)


def test_canal_dentro_do_bloco_passa() -> None:
    _validar_comando_loop(_cfg_fuzzy(), "loop_sp", LoopValueCommand(value=50.0, channel=1))
    _validar_comando_loop(_cfg_fuzzy(), "loop_out", LoopValueCommand(value=50.0, channel=1))


def test_canal_fora_do_bloco_e_recusado() -> None:
    with pytest.raises(HTTPException) as exc:
        _validar_comando_loop(_cfg_fuzzy(), "loop_sp", LoopValueCommand(value=50.0, channel=2))
    assert exc.value.status_code == 422
    # pid_loop e SISO: so o canal 0 existe
    with pytest.raises(HTTPException):
        _validar_comando_loop(_cfg(), "loop_sp", LoopValueCommand(value=50.0, channel=1))
