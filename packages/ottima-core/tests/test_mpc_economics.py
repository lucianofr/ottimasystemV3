"""Mesa de casos do bloco `economics` do `MpcConfig` (ADR-027 §9, RF-901/902).

O SSTO (camada de alvos de regime permanente) lê custos, pesos e ranks daqui. Este módulo
prova só a FORMA e o `config_hash` — a matemática do LP mora em
`ottima_flow_runtime.target_calculation` e tem mesa própria.

Retrocompatibilidade é requisito, não conveniência: config salva antes desta feature
(`economics` ausente, CV sem `priority`) tem de continuar carregando com o comportamento de
antes (SSTO desligado, ranks iguais).
"""

import pytest
from pydantic import ValidationError

from ottima_core.flowgraph import EconomicsConfig, MpcConfig, economics_config_hash, parse_graph


def base_config() -> dict:
    """Config 1×1 mínimo: uma MV, uma CV, um par habilitado."""
    return {
        "name": "MPC de teste",
        "multiplier": 5,
        "variables": {
            "mvs": [
                {
                    "id": "mv_a",
                    "name": "MV A",
                    "eu": "%",
                    "limits": {"min": 0.0, "max": 100.0},
                    "du_max": 5.0,
                }
            ],
            "cvs": [
                {
                    "id": "cv_a",
                    "name": "CV A",
                    "eu": "degC",
                    "kind": "selfreg",
                    "tss": 600.0,
                    "weight": 1.0,
                    "sp_limits": {"min": 50.0, "max": 90.0},
                }
            ],
            "constraints": [
                {
                    "id": "co_a",
                    "name": "Restrição A",
                    "eu": "bar",
                    "kind": "selfreg",
                    "tss": 300.0,
                    "range": {"low": 1.0, "high": 4.0},
                    "priority": 3,
                }
            ],
            "dvs": [{"id": "dv_a", "name": "DV A", "eu": "m3/h"}],
        },
        "models": {
            "cv_a": {
                "mv_a": {
                    "enabled": True,
                    "params": {"K": 2.0, "tau1": 60.0, "tau2": 0.0, "theta": 0.0},
                }
            },
            "co_a": {
                "mv_a": {
                    "enabled": True,
                    "params": {"K": 1.0, "tau1": 30.0, "tau2": 0.0, "theta": 0.0},
                }
            },
        },
    }


# ---------------------------------------------------------------------------------------
# Forma
# ---------------------------------------------------------------------------------------


def test_config_sem_economics_carrega_com_ssto_desligado():
    """Retrocompat: config da F4 continua válido e nasce com o SSTO desligado."""
    config = MpcConfig.model_validate(base_config())

    assert config.economics is None


def test_cv_sem_priority_recebe_rank_default():
    """`CvVar.priority` é campo novo (ADR-027 §5): default neutro, todas as CVs iguais."""
    config = MpcConfig.model_validate(base_config())

    assert config.variables.cvs[0].priority == 1


def test_cv_priority_zero_e_rejeitado():
    raw = base_config()
    raw["variables"]["cvs"][0]["priority"] = 0

    with pytest.raises(ValidationError):
        MpcConfig.model_validate(raw)


def test_economics_completo_parseia():
    raw = base_config()
    raw["economics"] = {
        "enabled": True,
        "costs": {"mv_a": 1.5, "cv_a": -3.0},
        "slack_weight": 5000.0,
        "detuning_weight": 0.25,
        "solver": "osqp",
        "integrating_tolerance": 0.01,
    }

    config = MpcConfig.model_validate(raw)

    assert config.economics is not None
    assert config.economics.enabled is True
    assert config.economics.costs == {"mv_a": 1.5, "cv_a": -3.0}
    assert config.economics.slack_weight == 5000.0
    assert config.economics.detuning_weight == 0.25
    assert config.economics.solver == "osqp"
    assert config.economics.integrating_tolerance == 0.01


def test_economics_defaults_sao_lp_puro_desligado():
    economics = EconomicsConfig()

    assert economics.enabled is False
    assert economics.costs == {}
    assert economics.detuning_weight == 0.0
    assert economics.solver == "highs"


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("slack_weight", 0.0),
        ("slack_weight", -1.0),
        ("detuning_weight", -0.1),
        ("integrating_tolerance", -0.001),
        ("solver", "cplex"),
    ],
)
def test_economics_rejeita_valor_invalido(campo: str, valor: object):
    raw = base_config()
    raw["economics"] = {"enabled": True, campo: valor}

    with pytest.raises(ValidationError):
        MpcConfig.model_validate(raw)


def test_economics_rejeita_campo_desconhecido():
    raw = base_config()
    raw["economics"] = {"enabled": True, "objetivo": "maximizar"}

    with pytest.raises(ValidationError):
        MpcConfig.model_validate(raw)


def _mpc_graph_node(economics: dict | None) -> dict:
    """Nó `mpc` mínimo do `graph_json` (spec F3 §2.1) — só a forma importa aqui."""
    data = {
        "exec_order": 1,
        "name": "MPC de teste",
        "multiplier": 1,
        "variables": {"mvs": [], "cvs": [], "constraints": [], "dvs": []},
        "models": {},
    }
    if economics is not None:
        data["economics"] = economics
    return {
        "nodes": [{"id": "m1", "type": "mpc", "position": {"x": 0.0, "y": 0.0}, "data": data}],
        "edges": [],
    }


def test_parse_graph_aceita_economics_no_no_mpc():
    """`economics` é chave prevista de `data` no bloco `mpc` — sem isto o parse reprovaria
    o grafo com 'chave desconhecida' antes de a validação semântica ver o config."""
    graph = parse_graph(_mpc_graph_node({"enabled": True, "costs": {"mv_a": 1.0}}))

    assert graph.nodes[0].config.economics == {"enabled": True, "costs": {"mv_a": 1.0}}


def test_parse_graph_sem_economics_continua_valido():
    graph = parse_graph(_mpc_graph_node(None))

    assert not hasattr(graph.nodes[0].config, "economics")


# ---------------------------------------------------------------------------------------
# config_hash (ADR-027 §9): identidade da versão de custos/limites/ranks
# ---------------------------------------------------------------------------------------


def test_config_hash_e_estavel_entre_reparses():
    config_a = MpcConfig.model_validate(base_config())
    config_b = MpcConfig.model_validate(base_config())

    assert economics_config_hash(config_a) == economics_config_hash(config_b)


def test_config_hash_ignora_ordem_das_chaves_de_custo():
    raw_a = base_config()
    raw_a["economics"] = {"enabled": True, "costs": {"mv_a": 1.0, "cv_a": -2.0}}
    raw_b = base_config()
    raw_b["economics"] = {"enabled": True, "costs": {"cv_a": -2.0, "mv_a": 1.0}}

    assert economics_config_hash(MpcConfig.model_validate(raw_a)) == economics_config_hash(
        MpcConfig.model_validate(raw_b)
    )


def test_config_hash_ignora_campo_que_nao_e_custo_limite_nem_rank():
    """O hash identifica a versão do PROBLEMA econômico — renomear o bloco não é uma versão
    nova de custos/limites/ranks."""
    raw = base_config()
    raw["name"] = "Outro nome"

    assert economics_config_hash(MpcConfig.model_validate(raw)) == economics_config_hash(
        MpcConfig.model_validate(base_config())
    )


@pytest.mark.parametrize(
    "mutacao",
    [
        pytest.param(lambda raw: raw["economics"].update({"costs": {"mv_a": 9.9}}), id="custo"),
        pytest.param(
            lambda raw: raw["variables"]["mvs"][0]["limits"].update({"max": 90.0}), id="limite_mv"
        ),
        pytest.param(
            lambda raw: raw["variables"]["cvs"][0]["sp_limits"].update({"min": 55.0}),
            id="limite_cv",
        ),
        pytest.param(
            lambda raw: raw["variables"]["constraints"][0]["range"].update({"high": 3.0}),
            id="faixa_restricao",
        ),
        pytest.param(
            lambda raw: raw["variables"]["constraints"][0].update({"priority": 7}), id="rank"
        ),
        pytest.param(lambda raw: raw["economics"].update({"detuning_weight": 0.5}), id="detuning"),
    ],
)
def test_config_hash_muda_quando_custo_limite_ou_rank_muda(mutacao):
    raw_base = base_config()
    raw_base["economics"] = {"enabled": True, "costs": {"mv_a": 1.0}}
    raw_mutado = base_config()
    raw_mutado["economics"] = {"enabled": True, "costs": {"mv_a": 1.0}}
    mutacao(raw_mutado)

    hash_base = economics_config_hash(MpcConfig.model_validate(raw_base))
    hash_mutado = economics_config_hash(MpcConfig.model_validate(raw_mutado))

    assert hash_base != hash_mutado
