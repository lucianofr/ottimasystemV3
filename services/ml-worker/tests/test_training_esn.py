"""ESN (RF-587): o treino usa a MESMA recorrência da inferência compartilhada (forward.py)."""

import numpy as np

from ottima_core.softsensor import EsnHyperparams, predict
from ottima_ml_worker.training import metrics
from ottima_ml_worker.training.esn import fit_esn, reservoir_states

HP = EsnHyperparams(units=30, warmup=8, lr=0.4, ridge=1e-3)


def _data(m: int = 60, k: int = 8, d: int = 3, seed: int = 0):
    rng = np.random.default_rng(seed)
    x = (rng.normal(size=(m, k, d)) * [1.0, 5.0, 0.2][:d] + [0.0, 10.0, -1.0][:d]).astype(
        np.float32
    )
    return x, x[:, -1, 0] + 0.5 * x[:, -2, 1] + rng.normal(size=m) * 0.1


def test_estado_de_treino_e_o_mesmo_da_inferencia_compartilhada(as_model):
    x, y = _data()
    w = fit_esn(x, y, HP)
    model = as_model("esn", w, 3, 8)

    std = np.where(w["x_std"] == 0, 1.0, w["x_std"])
    states = reservoir_states((x - w["x_mean"]) / std, w["W"], w["Win"], w["bias"], w["lr"][0])
    from_training = (states @ w["Wout"] + w["b_out"][0]) * w["y_std"][0] + w["y_mean"][0]

    for i in np.random.default_rng(5).choice(len(x), 20, replace=False):
        assert abs(predict(model, x[i]) - from_training[i]) < 1e-4


def test_raio_espectral_e_o_pedido():
    x, y = _data()

    w = fit_esn(x, y, EsnHyperparams(units=30, warmup=8, sr=0.7, rc_connectivity=0.3))

    assert abs(np.abs(np.linalg.eigvals(w["W"])).max() - 0.7) < 1e-3


def test_densidade_das_matrizes_segue_a_conectividade():
    x, y = _data(m=40, k=8, d=3)
    x = np.concatenate([x] * 4, axis=2)[:, :, :10]  # d=10: matriz de entrada com 1000 elementos

    w = fit_esn(
        x, y, EsnHyperparams(units=100, warmup=8, rc_connectivity=0.2, input_connectivity=0.3)
    )

    assert abs(np.count_nonzero(w["W"]) / w["W"].size - 0.2) < 0.02
    assert abs(np.count_nonzero(w["Win"]) / w["Win"].size - 0.3) < 0.05


def test_mesma_semente_gera_o_mesmo_modelo():
    x, y = _data()

    a, b = fit_esn(x, y, HP), fit_esn(x, y, HP)
    other = fit_esn(x, y, EsnHyperparams(units=30, warmup=8, lr=0.4, ridge=1e-3, seed=7))

    assert all(np.array_equal(a[k], b[k]) for k in a)
    assert not np.array_equal(a["W"], other["W"])


def test_pesos_no_formato_do_artefato():
    x, y = _data()

    w = fit_esn(x, y, HP)

    assert {k: v.shape for k, v in w.items()} == {
        "W": (30, 30), "Win": (30, 3), "bias": (30,), "Wout": (30,), "b_out": (1,), "lr": (1,),
        "x_mean": (3,), "x_std": (3,), "y_mean": (1,), "y_std": (1,),
    }  # fmt: skip
    assert w["lr"][0] == np.float32(0.4)


def test_aprende_media_movel_dos_ultimos_passos(as_model):
    rng = np.random.default_rng(6)
    x = rng.normal(size=(400, 20, 2)).astype(np.float32)
    y = x[:, -5:, 0].mean(axis=1)  # média de x0 nos últimos 5 passos
    hp = EsnHyperparams(units=100, warmup=20, lr=0.5, ridge=1e-4, input_connectivity=0.5)

    model = as_model("esn", fit_esn(x[:320], y[:320], hp), 2, 20)
    pred = np.array([predict(model, x[i]) for i in range(320, 400)])

    assert metrics(y[320:], pred)["r2"] > 0.8


def test_entrada_e_alvo_constantes_nao_geram_nan(as_model):
    x = np.full((30, 8, 3), 2.0, dtype=np.float32)

    w = fit_esn(x, np.full(30, 7.0), HP)

    assert all(np.isfinite(v).all() for v in w.values())
    assert abs(predict(as_model("esn", w, 3, 8), x[0]) - 7.0) < 1e-3
