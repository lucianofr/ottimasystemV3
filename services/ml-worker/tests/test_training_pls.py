"""PLS (RF-587): o `w`, `b` exportado reproduz o `predict` do scikit-learn em unidade bruta."""

import numpy as np
import pytest
from sklearn.cross_decomposition import PLSRegression

from ottima_core.softsensor import PlsHyperparams, predict
from ottima_ml_worker.training import metrics
from ottima_ml_worker.training.pls import fit_pls


def _windows(x: np.ndarray) -> np.ndarray:
    return x[:, None, :].astype(np.float32)  # [n, 1, d]: o PLS só olha a última linha


def test_paridade_com_o_predict_do_scikit_learn(as_model):
    rng = np.random.default_rng(1)
    scale = np.array([1.0, 8.0, 0.1, 3.0, 5.0])  # escalas diferentes: o export é em unidade bruta
    x = (rng.normal(size=(60, 5)) * scale + 4.0).astype(np.float32)
    y = x @ rng.normal(size=5) + rng.normal(size=60)
    hp = PlsHyperparams(n_components=3)

    model = as_model("pls", fit_pls(_windows(x), y, hp), 5, 1)
    reference = PLSRegression(n_components=3, scale=True).fit(x.astype(np.float64), y)

    for _ in range(50):
        probe = rng.normal(size=(1, 5)) * scale + 4.0
        assert abs(predict(model, probe) - reference.predict(probe).item()) < 1e-4


def test_recupera_relacao_linear_conhecida(as_model):
    rng = np.random.default_rng(2)
    x = rng.normal(size=(40, 2)).astype(np.float32)
    y = 2 * x[:, 0] - x[:, 1] + 0.5

    model = as_model("pls", fit_pls(_windows(x), y, PlsHyperparams(n_components=2)), 2, 1)
    pred = np.array([predict(model, x[i : i + 1]) for i in range(len(x))])

    assert metrics(y, pred)["rmse"] < 1e-3


def test_n_components_e_limitado_por_d_e_n():
    rng = np.random.default_rng(3)
    x = rng.normal(size=(3, 4)).astype(np.float32)  # d=4, n=3: teto = min(10, 4, 2) = 2
    y = rng.normal(size=3)

    wide = fit_pls(_windows(x), y, PlsHyperparams(n_components=10))
    capped = fit_pls(_windows(x), y, PlsHyperparams(n_components=2))

    assert np.allclose(wide["w"], capped["w"]) and np.allclose(wide["b"], capped["b"])
    assert np.isfinite(wide["w"]).all()


def test_pesos_no_formato_do_artefato():
    w = fit_pls(
        _windows(np.random.default_rng(4).normal(size=(20, 3))), np.arange(20.0), PlsHyperparams()
    )

    assert set(w) == {"w", "b"} and w["w"].shape == (3,) and w["b"].shape == (1,)


def test_entrada_constante_nao_gera_nan(as_model):
    rng = np.random.default_rng(5)
    x = np.column_stack([rng.normal(size=40), np.full(40, 3.0)]).astype(np.float32)
    y = 2 * x[:, 0] + 1

    w = fit_pls(_windows(x), y, PlsHyperparams(n_components=3))

    assert all(np.isfinite(v).all() for v in w.values()) and w["w"][1] == 0
    model = as_model("pls", w, 2, 1)
    pred = np.array([predict(model, x[i : i + 1]) for i in range(len(x))])
    assert metrics(y, pred)["rmse"] < 1e-3


def test_todas_as_entradas_constantes_devolvem_a_media(as_model):
    x = np.full((30, 3), 2.0, dtype=np.float32)
    y = np.arange(30.0)

    w = fit_pls(_windows(x), y, PlsHyperparams())

    assert np.array_equal(w["w"], np.zeros(3)) and w["b"][0] == pytest.approx(y.mean())
    assert abs(predict(as_model("pls", w, 3, 1), x[:1]) - y.mean()) < 1e-4


def test_entrada_constante_e_colinear_nao_gera_nan(as_model):
    rng = np.random.default_rng(6)
    a = rng.normal(size=40)
    x = np.column_stack([a, 2 * a, np.full(40, -1.0)]).astype(np.float32)  # posto 1 em 3 colunas
    y = 3 * a + 1

    w = fit_pls(_windows(x), y, PlsHyperparams(n_components=3))

    assert all(np.isfinite(v).all() for v in w.values())
    model = as_model("pls", w, 3, 1)
    pred = np.array([predict(model, x[i : i + 1]) for i in range(len(x))])
    assert metrics(y, pred)["rmse"] < 1e-3
