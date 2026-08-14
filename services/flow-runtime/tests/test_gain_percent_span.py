"""Ganho %/% (RF-602 revisado, RF-609): o span de instrumento escala o ganho em EU.

Prova determinística, sem planta: `build_steady_state_model().g` com CV span=200/MV
span=100 deve dar EXATAMENTE o dobro do ganho de span=100/100 para o mesmo `K=1`
declarado; e com os defaults 0/100 em tudo, `g` é idêntico ao ganho cru de antes do
zero/span (regressão bit a bit). Espelha o caminho do builder dinâmico
(`discretize_sopdt` recebe o mesmo `K` escalado pelo mesmo `eu_gain_params`).
"""

from ottima_core.flowgraph import MpcConfig
from ottima_flow_runtime.mpc.discretize import eu_gain_params
from ottima_flow_runtime.target_calculation.model import build_steady_state_model


def _config(span_mv: float, span_cv: float, *, k: float = 1.0) -> MpcConfig:
    return MpcConfig.model_validate(
        {
            "name": "ganho-percent",
            "multiplier": 1,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_1",
                        "name": "MV",
                        "eu": "%",
                        "zero": 0.0,
                        "span": span_mv,
                        "limits": {"min": 0.0, "max": 100.0},
                        "max_rate": 5.0,
                    }
                ],
                "cvs": [
                    {
                        "id": "cv_1",
                        "name": "CV",
                        "eu": "%",
                        "zero": 0.0,
                        "span": span_cv,
                        "kind": "selfreg",
                        "tss": 30.0,
                        "weight": 1.0,
                        "sp_limits": {"min": 0.0, "max": 100.0},
                    }
                ],
                "constraints": [],
                "dvs": [],
            },
            "models": {
                "cv_1": {
                    "mv_1": {
                        "enabled": True,
                        "params": {"K": k, "tau1": 10.0, "tau2": 0.0, "theta": 0.0},
                    }
                }
            },
        }
    )


def test_span_da_linha_dobra_o_ganho_em_eu() -> None:
    """K=1 %/%: CV span 200 / MV span 100 ⇒ ganho EU 2× o de 100/100."""
    g_base = build_steady_state_model(_config(100.0, 100.0), ts_mpc=1.0).g[0, 0]
    g_dobro = build_steady_state_model(_config(100.0, 200.0), ts_mpc=1.0).g[0, 0]
    assert g_dobro == 2.0 * g_base


def test_span_da_coluna_divide_o_ganho_em_eu() -> None:
    """MV span 50 (mesma CV): 1% da MV passa a valer 0,5 EU — o ganho EU dobra de novo."""
    g_base = build_steady_state_model(_config(100.0, 100.0), ts_mpc=1.0).g[0, 0]
    g_mv50 = build_steady_state_model(_config(50.0, 100.0), ts_mpc=1.0).g[0, 0]
    assert g_mv50 == 2.0 * g_base


def test_defaults_reproduzem_o_ganho_cru_anterior() -> None:
    """Defaults 0/100 em tudo ⇒ razão 1 ⇒ `g` igual ao K cru de antes do zero/span."""
    config = _config(100.0, 100.0, k=2.5)
    g = build_steady_state_model(config, ts_mpc=1.0).g[0, 0]
    # SOPDT com tau2=0 degrada a 1a ordem: g_ss = K_escalado = 2.5 (razão de spans 1).
    assert g == 2.5


def test_eu_gain_params_escala_k_e_ki_e_nao_muta_o_original() -> None:
    params = {"K": 1.5, "tau1": 10.0, "tau2": 0.0, "theta": 0.0}
    convertido = eu_gain_params(params, kind="selfreg", row_span=200.0, col_span=50.0)
    assert convertido["K"] == 6.0
    assert params["K"] == 1.5  # cópia rasa: o config do chamador nunca é mutado

    integrador = {"Ki": 0.5, "theta": 0.0}
    assert (
        eu_gain_params(integrador, kind="integrating", row_span=100.0, col_span=25.0)["Ki"]
        == 2.0
    )
