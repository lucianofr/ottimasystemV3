"""A conta dos três métodos do sensor virtual, só numpy (RF-581, ADR-046 D4; spec §5.3).

Única implementação da inferência: o flow-runtime opera com ela e o ml-worker valida o que
exporta com ela. Todo modelo é função pura das últimas K amostras (sem estado entre passos).
"""

import numpy as np

from .artifact import LoadedModel


def _standardize(x: np.ndarray, w: dict[str, np.ndarray]) -> np.ndarray:
    std = np.where(w["x_std"] == 0.0, 1.0, w["x_std"])  # entrada constante no treino
    return (x - w["x_mean"]) / std


def _sigmoid(v: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-v))


def _pls(w: dict[str, np.ndarray], x: np.ndarray) -> float:
    return float(w["w"] @ x[-1] + w["b"][0])  # w e b já em unidade de engenharia


def _esn(w: dict[str, np.ndarray], x: np.ndarray) -> float:
    # Projeção da entrada de uma vez; só a recorrência, que depende de s, fica no laço.
    drive = _standardize(x, w) @ w["Win"].T + w["bias"]
    lr = w["lr"][0]
    s = np.zeros(w["W"].shape[0])  # estado zero a cada passo: nada é carregado entre passos
    for d in drive:
        s = (1.0 - lr) * s + lr * np.tanh(w["W"] @ s + d)
    return float((w["Wout"] @ s + w["b_out"][0]) * w["y_std"][0] + w["y_mean"][0])


def _lstm(w: dict[str, np.ndarray], x: np.ndarray) -> float:
    seq = _standardize(x, w)
    k = 0
    while f"w_ih_{k}" in w:  # load_model garante camadas contíguas a partir de 0
        w_hh = w[f"w_hh_{k}"]
        gates_in = seq @ w[f"w_ih_{k}"].T + w[f"b_ih_{k}"] + w[f"b_hh_{k}"]
        h = np.zeros(w_hh.shape[1])
        c = np.zeros(w_hh.shape[1])
        out = np.empty((len(seq), w_hh.shape[1]))
        for t, g_in in enumerate(gates_in):
            # Ordem dos portões i, f, g, o em blocos de u linhas: a do PyTorch (SV-3 exporta de lá).
            i, f, g, o = np.split(g_in + w_hh @ h, 4)
            c = _sigmoid(f) * c + _sigmoid(i) * np.tanh(g)
            h = _sigmoid(o) * np.tanh(c)
            out[t] = h
        seq = out
        k += 1
    return float((w["fc_w"] @ seq[-1] + w["fc_b"][0]) * w["y_std"][0] + w["y_mean"][0])


_FORWARD = {"pls": _pls, "esn": _esn, "lstm": _lstm}


def predict(model: LoadedModel, window: np.ndarray) -> float:
    """`window` é `[warmup_steps, n_inputs]`, em unidade de engenharia, mais antiga primeiro.

    Devolve em unidade de engenharia; pode devolver não finito (quem chama rebaixa a BAD).
    """
    x = np.asarray(window, dtype=np.float64)
    expected = (model.meta.warmup_steps, model.n_inputs)
    if x.shape != expected:
        raise ValueError(f"janela com forma {x.shape}, esperado {expected}")
    if not np.isfinite(x).all():
        # tanh/sigmoide saturam: sem isto um inf na janela viraria um número finito normal.
        return float("nan")
    with np.errstate(all="ignore"):
        return _FORWARD[model.meta.method](model.weights, x)
