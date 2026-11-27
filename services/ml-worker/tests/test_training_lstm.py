"""LSTM (RF-587): o export do PyTorch reproduz o forward pela inferência numpy compartilhada."""

import numpy as np
import pytest
import torch

from ottima_core.softsensor import LstmHyperparams, predict
from ottima_ml_worker.training import metrics
from ottima_ml_worker.training.lstm import Net, export_weights, fit_lstm


def test_paridade_com_o_forward_do_pytorch(as_model):
    torch.manual_seed(0)
    net = Net(d=3, units=8, layers=2)
    for p in net.parameters():  # pesos maiores que o default: portões longe da região linear
        p.data.normal_(0.0, 0.8)
    x_mean, x_std = np.array([1.0, -2.0, 0.5]), np.array([2.0, 0.5, 3.0])
    y_mean, y_std = 10.0, 4.0
    model = as_model("lstm", export_weights(net, x_mean, x_std, y_mean, y_std), 3, 6)

    rng = np.random.default_rng(1)
    for _ in range(30):
        window = rng.normal(size=(6, 3)) * x_std + x_mean
        standardized = torch.tensor((window - x_mean) / x_std, dtype=torch.float32)[None]
        with torch.no_grad():
            expected = net(standardized).item() * y_std + y_mean
        assert abs(predict(model, window) - expected) < 1e-4


def _noise(m: int = 40, k: int = 5):
    rng = np.random.default_rng(2)
    return rng.normal(size=(m, k, 2)).astype(np.float32), rng.normal(size=m)


@pytest.mark.slow
def test_parada_antecipada_interrompe_antes_de_todas_as_epocas():
    x, y = _noise()  # alvo sem relação com a entrada: a perda para de melhorar sem demora
    epochs: list[int] = []
    hp = LstmHyperparams(units=8, layers=1, epochs=300, batch_size=16, sequence_length=5, lr=0.1)

    fit_lstm(x, y, hp, epoch_cb=lambda epoch, loss: epochs.append(epoch))

    assert 10 < len(epochs) < 300


def test_epoch_cb_e_chamado_por_epoca():
    x, y = _noise()
    calls: list[tuple[int, float]] = []
    hp = LstmHyperparams(units=8, layers=1, epochs=3, batch_size=16, sequence_length=5)

    fit_lstm(x, y, hp, epoch_cb=lambda epoch, loss: calls.append((epoch, loss)))

    assert [c[0] for c in calls] == [1, 2, 3]
    assert all(np.isfinite(c[1]) and c[1] > 0 for c in calls)


def test_pesos_no_formato_do_artefato():
    x, y = _noise()
    hp = LstmHyperparams(units=8, layers=2, epochs=2, batch_size=16, sequence_length=5)

    w = fit_lstm(x, y, hp)

    assert {k: v.shape for k, v in w.items()} == {
        "w_ih_0": (32, 2), "w_hh_0": (32, 8), "b_ih_0": (32,), "b_hh_0": (32,),
        "w_ih_1": (32, 8), "w_hh_1": (32, 8), "b_ih_1": (32,), "b_hh_1": (32,),
        "fc_w": (8,), "fc_b": (1,), "x_mean": (2,), "x_std": (2,), "y_mean": (1,), "y_std": (1,),
    }  # fmt: skip


@pytest.mark.slow
def test_aprende_relacao_temporal_simples(as_model):
    rng = np.random.default_rng(3)
    x = rng.normal(size=(300, 6, 2)).astype(np.float32)
    y = 0.7 * x[:, -1, 0] + 0.3 * x[:, -3, 1]
    hp = LstmHyperparams(units=16, layers=1, epochs=60, batch_size=32, sequence_length=6, lr=0.01)

    model = as_model("lstm", fit_lstm(x[:240], y[:240], hp), 2, 6)
    pred = np.array([predict(model, x[i]) for i in range(240, 300)])

    assert metrics(y[240:], pred)["r2"] > 0.8
