"""Hiperparâmetros do sensor virtual como contrato único (RF-587, RF-588, ADR-046): defaults,
limites, janela e faixas do Optuna saem de um módulo só, e o contrato exportado ao frontend é
derivado dos schemas (nenhum número digitado duas vezes)."""

import pytest
from annotated_types import Gt

from ottima_core.contracts_export import build_contracts
from ottima_core.softsensor import METHODS
from ottima_core.softsensor.hyperparams import (
    HYPERPARAMS,
    SEARCH_SPACE,
    EsnHyperparams,
    LstmHyperparams,
    PlsHyperparams,
    parse_hyperparams,
    window_of,
)


def test_defaults_sao_os_da_spec():
    assert PlsHyperparams().model_dump() == {"n_components": 3}
    assert EsnHyperparams().model_dump() == {
        "units": 500,
        "sr": 0.9,
        "lr": 0.3,
        "rc_connectivity": 0.1,
        "input_connectivity": 0.1,
        "input_scaling": 1.0,
        "ridge": 1e-6,
        "warmup": 100,
        "seed": 42,
    }
    assert LstmHyperparams().model_dump() == {
        "units": 64,
        "layers": 2,
        "epochs": 100,
        "batch_size": 32,
        "sequence_length": 10,
        "lr": 1e-3,
    }


def test_hyperparams_cobre_todos_os_metodos():
    assert set(HYPERPARAMS) == set(METHODS) == set(SEARCH_SPACE)


def test_units_do_esn_nao_passa_de_500():
    assert EsnHyperparams(units=500).units == 500
    with pytest.raises(ValueError, match=r"'units'.*esn.*no máximo 500"):
        parse_hyperparams("esn", {"units": 501})


def test_campo_desconhecido_e_recusado():
    with pytest.raises(ValueError, match=r"'foo'.*pls"):
        parse_hyperparams("pls", {"n_components": 3, "foo": 1})


def test_parse_traduz_limites_para_pt_br():
    with pytest.raises(ValueError, match=r"'n_components'.*pls.*no mínimo 1"):
        parse_hyperparams("pls", {"n_components": 0})
    with pytest.raises(ValueError, match=r"'sr'.*esn.*maior que 0"):
        parse_hyperparams("esn", {"sr": 0})
    with pytest.raises(ValueError, match=r"'batch_size'.*lstm.*8, 16, 32, 64"):
        parse_hyperparams("lstm", {"batch_size": 7})
    with pytest.raises(ValueError, match=r"'layers'.*lstm.*inteiro"):
        parse_hyperparams("lstm", {"layers": "muitas"})


def test_parse_sem_entrada_devolve_defaults():
    assert parse_hyperparams("esn", None) == EsnHyperparams()
    assert parse_hyperparams("lstm", {}) == LstmHyperparams()
    assert parse_hyperparams("pls", {"n_components": 5}) == PlsHyperparams(n_components=5)


def test_metodo_desconhecido_e_recusado():
    with pytest.raises(ValueError, match="xgb"):
        parse_hyperparams("xgb", {})


def test_window_of():
    assert window_of("pls", PlsHyperparams()) == 1
    assert window_of("esn", EsnHyperparams(warmup=7)) == 7
    assert window_of("lstm", LstmHyperparams(sequence_length=12)) == 12


def test_espaco_de_busca_cabe_nos_limites_do_schema():
    for method, campos in SEARCH_SPACE.items():
        modelo = HYPERPARAMS[method]
        assert set(campos) <= set(modelo.model_fields)
        for campo, faixa in campos.items():
            if faixa["kind"] == "choice":
                valores = faixa["choices"]
            else:
                assert faixa["kind"] in ("int", "float", "log")
                assert faixa["low"] < faixa["high"]
                valores = [faixa["low"], faixa["high"]]
            for valor in valores:
                modelo(**{campo: valor})  # o outros campos ficam no default


def test_contrato_exporta_default_min_max():
    contrato = build_contracts()["SOFT_SENSOR_HYPERPARAMS"]
    assert contrato["lstm"]["units"] == {"default": 64, "min": 8, "max": 256}
    assert contrato["esn"]["units"] == {"default": 500, "min": 10, "max": 500}
    assert contrato["pls"]["n_components"] == {"default": 3, "min": 1, "max": 50}
    # `gt` (limite exclusivo) carrega `exclusive_min`; `ge` não tem a chave
    assert contrato["esn"]["sr"] == {"default": 0.9, "min": 0, "max": 2.0, "exclusive_min": True}
    assert contrato["esn"]["ridge"] == {"default": 1e-6, "min": 0, "max": 1.0}
    assert "exclusive_min" not in contrato["lstm"]["units"]
    # Literal: as opções saem do schema, não de uma segunda lista
    assert contrato["lstm"]["batch_size"] == {"default": 32, "choices": [8, 16, 32, 64]}
    for method, modelo in HYPERPARAMS.items():
        assert set(contrato[method]) == set(modelo.model_fields)


def test_exclusive_min_so_nos_campos_gt():
    # Fonte independente da derivação: o metadado `Gt` do próprio campo Pydantic.
    contrato = build_contracts()["SOFT_SENSOR_HYPERPARAMS"]
    for method, modelo in HYPERPARAMS.items():
        for nome, campo in modelo.model_fields.items():
            tem_gt = any(isinstance(meta, Gt) for meta in campo.metadata)
            assert ("exclusive_min" in contrato[method][nome]) == tem_gt, f"{method}.{nome}"
            if tem_gt:
                assert contrato[method][nome]["exclusive_min"] is True


def test_contrato_exporta_espaco_de_busca():
    assert build_contracts()["SOFT_SENSOR_SEARCH_SPACE"] == SEARCH_SPACE
