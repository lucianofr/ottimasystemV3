"""Trava do espelho manual de defaults dos blocos malha (ADR-034, "teste próprio").

Se este teste ficar vermelho, um default de `LoopBaseConfig`/`PidLoopConfig`/`FuzzyLoopConfig`
mudou: atualize ESTA tabela e o espelho em `frontend/src/features/flows/registro.ts`
(`DEFAULT_SERVIDOR_PID_LOOP` / `DEFAULT_SERVIDOR_FUZZY_LOOP`) no mesmo commit.
"""

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from ottima_core.flowgraph.parse import FuzzyLoopConfig, PidLoopConfig

_SHELL = {
    "permitted": ["oos", "man", "auto"],
    "normal": "auto",
    "shed_opt": "shed_to_auto",
    "shed_no_return": False,
    "direct_acting": False,
    "sp_pv_track_in_man": True,
    "use_pv_for_bkcal": False,
    "track_enable": False,
    "track_in_manual": False,
    "sp_rate_up": None,
    "sp_rate_dn": None,
    "out_hi_lim": 100.0,
    "out_lo_lim": 0.0,
    "out_rate_up": None,
    "out_rate_dn": None,
    "out_scale_lo": 0.0,
    "out_scale_hi": 100.0,
    "out_startup": 0.0,
    "pv_ftime": 0.0,
    "trk_val": 0.0,
    "lo_val": 0.0,
    "ff_scale_lo": 0.0,
    "ff_scale_hi": 100.0,
    "ff_gain": 1.0,
    "ff_enable": False,
}
_PID = {
    **_SHELL,
    "ti_seconds": 0.0,
    "td_seconds": 0.0,
    "n": 8.0,
    "beta": 1.0,
    "gamma": 0.0,
    "gap_band": 0.0,
    "gap_gain": 1.0,
}
_FUZZY = {
    **_SHELL,
    "n_loops": 1,
    "kde": 0.0,
    "tf_de": 1.0,
    "lut_enabled": False,
    "lut_resolution": 65,
}


def _defaults(model: type[BaseModel]) -> dict[str, object]:
    saida: dict[str, object] = {}
    for nome, campo in model.model_fields.items():
        if campo.default_factory is not None:
            saida[nome] = campo.default_factory()
        elif campo.default is not PydanticUndefined:
            saida[nome] = campo.default
    return saida


def test_defaults_do_pid_loop_batem_com_o_espelho_do_editor() -> None:
    assert _defaults(PidLoopConfig) == _PID


def test_defaults_do_fuzzy_loop_batem_com_o_espelho_do_editor() -> None:
    reais = _defaults(FuzzyLoopConfig)
    reais.pop("fll")  # exportado em PORT_CONTRACTS.fuzzy_loop.default_fll
    assert reais == _FUZZY
