"""Vetores-golden Python->TS do bloco MPC (spec F5 §7.6-2, plano F5b tarefa 6.1, decisão A-9).

Fonte única de verdade para `derive_horizons`, `mpc_state_dimension`, arredondamento
banker's, tetos de variável (§2.2-2) e o veredito de `_check_mpc_caps/_matrix/_numbers/
_horizons` (spec §2.2-2/3/4/5/7) — `frontend/src/features/flows/mpc/mpcLogic.golden.check.ts`
(tarefa 6.2) compara campo a campo contra o JSON commitado aqui ao lado
(`mpcLogic.golden.json`). Mudar o Python sem regenerar o golden vira teste vermelho aqui
mesmo (§7.6-4, drift bidirecional); divergir do lado TS vira vermelho lá.

Escopo espelhado no TS (`mpcLogic.ts:205-442`): `derivarHorizontes`, `arredondarBankers`,
`dimensaoEstado`, tetos de variável e `validarConfigMpc`/`paramsValidosParaKind`. Fora do
escopo (só servidor, nunca mirrorado no TS): integridade de tag da MV (§2.2-6,
`_check_mpc_tags`) — por isso toda MV aqui sai sem `pid` e sem `readback_tag_id`, e o
veredito reusa `_check_mpc_nodes` (que chama `_check_mpc_tags` internamente, mas ela vira
no-op sem tag referenciada, sem precisar de um mapa de tags real).

Executável como `uv run python -m ottima_core.mpc_golden_export`.
"""

import json
from collections.abc import Mapping

from ottima_core.flowgraph.mpc_config import MpcConfig, derive_horizons, mpc_state_dimension
from ottima_core.flowgraph.parse import FlowNode, MpcRawConfig, Position
from ottima_core.flowgraph.validate import TagRef, _check_mpc_nodes

_NODE = FlowNode(
    id="golden", type="mpc", position=Position(x=0.0, y=0.0), exec_order=1, config=MpcRawConfig()
)
_NO_TAGS: Mapping[int, TagRef] = {}

_SELFREG_PARAMS = {"K": 1.0, "tau1": 10.0, "tau2": 0.0, "theta": 0.0}
_INTEGRATING_PARAMS = {"Ki": 1.0, "theta": 0.0}


# --------------------------------------------------------------------------------------
# Fábricas mínimas de variável/par (mesmos nomes de campo de `MpcConfig` — verbatim,
# consumível direto pelo TS como `VariaveisMpc`/`ParModeloMpc`, sem tradução de chave).
# --------------------------------------------------------------------------------------


def _mv(sufixo: str, **overrides: object) -> dict[str, object]:
    var: dict[str, object] = {
        "id": f"mv_{sufixo}",
        "name": "",
        "eu": "",
        "limits": {"min": 0.0, "max": 100.0},
        "du_max": 1.0,
        # TD-007: defaults neutros de `MvVar.du_min`/`.move_weight` — as regras espelhadas em
        # `validarConfigMpc` (piso `du_min >= 0`/`du_min <= du_max`, `move_weight > 0`) exigem
        # os dois campos presentes, senão os casos de validação existentes ganhariam erros
        # espúrios do lado TS (campo ausente vira `undefined`, nunca `>= 0`).
        "du_min": 0.0,
        "move_weight": 1.0,
        "initial_value": 0.0,
        "pid": None,
    }
    var.update(overrides)
    return var


def _cv(sufixo: str, **overrides: object) -> dict[str, object]:
    var: dict[str, object] = {
        "id": f"cv_{sufixo}",
        "name": "",
        "eu": "",
        "kind": "selfreg",
        "tss": 30.0,
        "weight": 1.0,
        "sp_limits": {"min": 0.0, "max": 100.0},
    }
    var.update(overrides)
    return var


def _co(sufixo: str, **overrides: object) -> dict[str, object]:
    var: dict[str, object] = {
        "id": f"co_{sufixo}",
        "name": "",
        "eu": "",
        "kind": "selfreg",
        "tss": 30.0,
        "range": {"low": 0.0, "high": 100.0},
        "priority": 1,
    }
    var.update(overrides)
    return var


def _dv(sufixo: str) -> dict[str, object]:
    return {"id": f"dv_{sufixo}", "name": "", "eu": ""}


def _par(kind: str = "selfreg", enabled: bool = True, **overrides: float) -> dict[str, object]:
    params = dict(_SELFREG_PARAMS if kind == "selfreg" else _INTEGRATING_PARAMS)
    params.update(overrides)
    return {"enabled": enabled, "params": params}


def _config(
    mvs: list[dict[str, object]],
    cvs: list[dict[str, object]] | None = None,
    constraints: list[dict[str, object]] | None = None,
    dvs: list[dict[str, object]] | None = None,
    models: dict[str, dict[str, object]] | None = None,
    multiplier: int = 1,
) -> dict[str, object]:
    return {
        "name": "golden",
        "multiplier": multiplier,
        "variables": {
            "mvs": mvs,
            "cvs": cvs or [],
            "constraints": constraints or [],
            "dvs": dvs or [],
        },
        "models": models or {},
    }


def _verdict(config_data: dict[str, object], ts_flow_segundos: float) -> dict[str, int]:
    """Roda o mesmo caminho de `validate_graph` para o bloco `mpc` (sem `_check_mpc_tags`
    surtir efeito — todo `pid` é `None`), devolvendo só a contagem de erros/avisos: o texto
    pt-BR é livre entre Python e TS (§7.6-2), a comparação é pelo veredito estrutural."""
    config = MpcConfig.model_validate(config_data)
    errors: list[str] = []
    warnings: list[str] = []
    _check_mpc_nodes([_NODE], {_NODE.id: config}, _NO_TAGS, ts_flow_segundos, errors, warnings)
    return {"erros": len(errors), "avisos": len(warnings)}


# --------------------------------------------------------------------------------------
# arredondamento_bankers — espelho de `arredondarBankers` (mpcLogic.ts:235-241)
# --------------------------------------------------------------------------------------


def _arredondamento_bankers() -> list[dict[str, object]]:
    valores = [0.0, 0.5, 1.5, 2.5, 3.5, 2.3, 2.7, 99.5, 100.5]
    return [{"valor": valor, "esperado": round(valor)} for valor in valores]


# --------------------------------------------------------------------------------------
# horizontes — espelho puro de `derive_horizons`/`derivarHorizontes` (mpcLogic.ts:219-229)
# --------------------------------------------------------------------------------------


def _horizonte(multiplier: int, ts_flow: float, tss: list[float]) -> dict[str, object]:
    horizons = derive_horizons(multiplier, ts_flow, tss)
    return {
        "multiplier": multiplier,
        "ts_flow": ts_flow,
        "tss": tss,
        "ts_mpc": horizons.ts_mpc,
        "np": horizons.np,
        "nc": horizons.nc,
    }


def _horizontes() -> list[dict[str, object]]:
    return [
        _horizonte(5, 1.0, [600.0]),  # caso canônico do brief: Np=120, Nc=30
        _horizonte(10, 100.0, [600.0]),  # Np=1, abaixo do piso (política é da validação)
        _horizonte(1, 1.0, [1000.0]),  # Np=1000, acima do teto (política é da validação)
    ]


# --------------------------------------------------------------------------------------
# dimensao_estado — espelho puro de `mpc_state_dimension`/`dimensaoEstado` (:248-268)
# --------------------------------------------------------------------------------------


def _dimensao_estado() -> list[dict[str, object]]:
    especificacoes = [
        ("simples_sopdt_sem_atraso", "selfreg", 0.0, True),
        ("atraso_com_banker_meio_par", "selfreg", 2.5, True),
        ("iopdt_soma_um_estado", "integrating", 0.0, True),
        ("par_desabilitado_nao_soma_estado", "selfreg", 2.5, False),
    ]
    casos: list[dict[str, object]] = []
    for nome, kind, theta, enabled in especificacoes:
        mv_ = _mv("a")
        cv_ = _cv("a", kind=kind)
        modelos = {cv_["id"]: {mv_["id"]: _par(kind=kind, enabled=enabled, theta=theta)}}
        config_data = _config([mv_], [cv_], models=modelos)
        config = MpcConfig.model_validate(config_data)
        casos.append(
            {
                "nome": nome,
                "variaveis": config_data["variables"],
                "modelos": config_data["models"],
                "ts_mpc": 1.0,
                "esperado": mpc_state_dimension(config, 1.0),
            }
        )
    return casos


# --------------------------------------------------------------------------------------
# validacao — um caso por regra de _check_mpc_caps/_matrix/_numbers/_horizons (§2.2-2/3/4/5/7)
# --------------------------------------------------------------------------------------


def _cenario_config_minima_valida() -> tuple[str, dict[str, object], float]:
    mv_, cv_ = _mv("a"), _cv("a")
    modelos = {cv_["id"]: {mv_["id"]: _par()}}
    return "config_minima_valida_sem_erro_nem_aviso", _config([mv_], [cv_], models=modelos), 1.0


def _cenario_caps_mv() -> tuple[str, dict[str, object], float]:
    mvs = [_mv(letra) for letra in "abcde"]  # 5 MVs, acima do teto [1,4]
    cv_ = _cv("a")
    modelos = {cv_["id"]: {mv["id"]: _par() for mv in mvs}}
    return "caps_mv_acima_do_teto", _config(mvs, [cv_], models=modelos), 1.0


def _cenario_caps_cv_restricao() -> tuple[str, dict[str, object], float]:
    mv_ = _mv("a")
    cvs = [_cv(letra) for letra in "abcdefg"]  # 7 CVs, acima do teto [1,6]
    modelos = {cv["id"]: {mv_["id"]: _par()} for cv in cvs}
    return "caps_cv_mais_restricao_acima_do_teto", _config([mv_], cvs, models=modelos), 1.0


def _cenario_caps_dv() -> tuple[str, dict[str, object], float]:
    mv_, cv_ = _mv("a"), _cv("a")
    dvs = [_dv(letra) for letra in "abcde"]  # 5 DVs, acima do teto [0,4]
    modelos = {cv_["id"]: {mv_["id"]: _par(), **{dv["id"]: _par() for dv in dvs}}}
    return "caps_dv_acima_do_teto", _config([mv_], [cv_], dvs=dvs, models=modelos), 1.0


def _cenario_matrix_params_invalidos() -> tuple[str, dict[str, object], float]:
    mv_, cv_ = _mv("a"), _cv("a")
    modelos = {cv_["id"]: {mv_["id"]: _par(K=0.0)}}  # K=0 viola selfreg (spec §2.2-3)
    return (
        "matrix_par_habilitado_com_params_invalidos",
        _config([mv_], [cv_], models=modelos),
        1.0,
    )


def _cenario_matrix_linha_sem_par_mv() -> tuple[str, dict[str, object], float]:
    mv_ = _mv("a")
    cv_a, cv_b = _cv("a"), _cv("b")
    modelos = {cv_a["id"]: {}, cv_b["id"]: {mv_["id"]: _par()}}
    return "matrix_linha_sem_par_mv", _config([mv_], [cv_a, cv_b], models=modelos), 1.0


def _cenario_matrix_mv_sem_par() -> tuple[str, dict[str, object], float]:
    mv_a, mv_b = _mv("a"), _mv("b")
    cv_ = _cv("a")
    modelos = {cv_["id"]: {mv_a["id"]: _par()}}
    return "matrix_mv_sem_par_habilitado", _config([mv_a, mv_b], [cv_], models=modelos), 1.0


def _cenario_matrix_dv_sem_par() -> tuple[str, dict[str, object], float]:
    mv_, cv_, dv_ = _mv("a"), _cv("a"), _dv("a")
    modelos = {cv_["id"]: {mv_["id"]: _par()}}
    return "matrix_dv_sem_par_habilitado", _config([mv_], [cv_], dvs=[dv_], models=modelos), 1.0


def _cenario_numbers_mv_limits() -> tuple[str, dict[str, object], float]:
    mv_ = _mv("a", limits={"min": 100.0, "max": 50.0})
    cv_ = _cv("a")
    modelos = {cv_["id"]: {mv_["id"]: _par()}}
    return (
        "numbers_mv_limits_min_nao_menor_que_max",
        _config([mv_], [cv_], models=modelos),
        1.0,
    )


def _cenario_numbers_mv_du_max() -> tuple[str, dict[str, object], float]:
    mv_ = _mv("a", du_max=0.0)
    cv_ = _cv("a")
    modelos = {cv_["id"]: {mv_["id"]: _par()}}
    return "numbers_mv_du_max_nao_positivo", _config([mv_], [cv_], models=modelos), 1.0


def _cenario_numbers_cv_tss() -> tuple[str, dict[str, object], float]:
    mv_ = _mv("a")
    cv_ok, cv_bad = _cv("a"), _cv("b", tss=0.0)
    modelos = {cv_ok["id"]: {mv_["id"]: _par()}, cv_bad["id"]: {mv_["id"]: _par()}}
    return "numbers_cv_tss_nao_positivo", _config([mv_], [cv_ok, cv_bad], models=modelos), 1.0


def _cenario_numbers_cv_sp_limits() -> tuple[str, dict[str, object], float]:
    mv_ = _mv("a")
    cv_ = _cv("a", sp_limits={"min": 100.0, "max": 50.0})
    modelos = {cv_["id"]: {mv_["id"]: _par()}}
    return (
        "numbers_cv_sp_limits_min_nao_menor_que_max",
        _config([mv_], [cv_], models=modelos),
        1.0,
    )


def _cenario_numbers_cv_weight() -> tuple[str, dict[str, object], float]:
    mv_ = _mv("a")
    cv_ = _cv("a", weight=0.0)
    modelos = {cv_["id"]: {mv_["id"]: _par()}}
    return "numbers_cv_weight_nao_positivo", _config([mv_], [cv_], models=modelos), 1.0


def _cenario_numbers_co_tss() -> tuple[str, dict[str, object], float]:
    mv_ = _mv("a")
    cv_ok = _cv("a")  # tss válido: mantém max(tss) longe de 0, isola a regra numérica
    co_bad = _co("a", tss=0.0)
    modelos = {cv_ok["id"]: {mv_["id"]: _par()}, co_bad["id"]: {mv_["id"]: _par()}}
    return (
        "numbers_co_tss_nao_positivo",
        _config([mv_], [cv_ok], constraints=[co_bad], models=modelos),
        1.0,
    )


def _cenario_numbers_co_range() -> tuple[str, dict[str, object], float]:
    mv_ = _mv("a")
    co_ = _co("a", range={"low": 100.0, "high": 50.0})
    modelos = {co_["id"]: {mv_["id"]: _par()}}
    return (
        "numbers_co_range_low_nao_menor_que_high",
        _config([mv_], constraints=[co_], models=modelos),
        1.0,
    )


def _cenario_horizons_np_abaixo() -> tuple[str, dict[str, object], float]:
    mv_, cv_ = _mv("a"), _cv("a")  # tss=30 (padrão)
    modelos = {cv_["id"]: {mv_["id"]: _par()}}
    return (
        "horizons_np_abaixo_do_piso",
        _config([mv_], [cv_], models=modelos, multiplier=100),
        1.0,
    )


def _cenario_horizons_np_acima() -> tuple[str, dict[str, object], float]:
    mv_ = _mv("a")
    cv_ = _cv("a", tss=1000.0)
    modelos = {cv_["id"]: {mv_["id"]: _par()}}
    return "horizons_np_acima_do_teto", _config([mv_], [cv_], models=modelos, multiplier=1), 1.0


def _cenario_horizons_np_aviso() -> tuple[str, dict[str, object], float]:
    mv_ = _mv("a")
    cv_ = _cv("a", tss=100.0)
    modelos = {cv_["id"]: {mv_["id"]: _par()}}
    return (
        "horizons_np_acima_de_60_e_aviso",
        _config([mv_], [cv_], models=modelos, multiplier=1),
        1.0,
    )


def _cenario_horizons_dimensao_aviso() -> tuple[str, dict[str, object], float]:
    mvs = [_mv(letra) for letra in "abcd"]  # 4 MVs (teto)
    cvs = [_cv(letra) for letra in "abcdef"]  # 6 CVs (teto), tss=30 -> Np=30, sem aviso de Np
    modelos = {cv["id"]: {mv["id"]: _par(theta=3.0) for mv in mvs} for cv in cvs}
    return (
        "horizons_dimensao_de_estados_acima_de_120_e_aviso",
        _config(mvs, cvs, models=modelos, multiplier=1),
        1.0,
    )


def _validacao() -> list[dict[str, object]]:
    construtores = (
        _cenario_config_minima_valida,
        _cenario_caps_mv,
        _cenario_caps_cv_restricao,
        _cenario_caps_dv,
        _cenario_matrix_params_invalidos,
        _cenario_matrix_linha_sem_par_mv,
        _cenario_matrix_mv_sem_par,
        _cenario_matrix_dv_sem_par,
        _cenario_numbers_mv_limits,
        _cenario_numbers_mv_du_max,
        _cenario_numbers_cv_tss,
        _cenario_numbers_cv_sp_limits,
        _cenario_numbers_cv_weight,
        _cenario_numbers_co_tss,
        _cenario_numbers_co_range,
        _cenario_horizons_np_abaixo,
        _cenario_horizons_np_acima,
        _cenario_horizons_np_aviso,
        _cenario_horizons_dimensao_aviso,
    )
    casos: list[dict[str, object]] = []
    for construtor in construtores:
        regra, config_data, ts_flow_segundos = construtor()
        casos.append(
            {
                "regra": regra,
                "ts_flow_segundos": ts_flow_segundos,
                "config": config_data,
                "esperado": _verdict(config_data, ts_flow_segundos),
            }
        )
    return casos


def build_golden() -> dict[str, object]:
    """Monta o payload golden completo — puro, sem I/O."""
    return {
        "arredondamento_bankers": _arredondamento_bankers(),
        "dimensao_estado": _dimensao_estado(),
        "horizontes": _horizontes(),
        "validacao": _validacao(),
    }


def main() -> None:
    print(json.dumps(build_golden(), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
