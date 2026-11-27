"""`train` (RF-587, spec §8.1): 80/20 no tempo, métricas do teste, reajuste em 100%, artefato."""

import importlib

import numpy as np
import pytest

from ottima_core.softsensor import (
    EsnHyperparams,
    LstmHyperparams,
    PlsHyperparams,
    load_model,
    predict,
    unpack_weights,
)
from ottima_ml_worker.training import (
    InputSeed,
    TrainData,
    TrainingError,
    chrono_split,
    metrics,
    select_rows,
    train,
)
from ottima_ml_worker.training.pls import fit_pls

# `training.train` é função e submódulo ao mesmo tempo: o atributo do pacote é a função.
train_module = importlib.import_module("ottima_ml_worker.training.train")

SEEDS = [InputSeed("T1", "°C"), InputSeed("P1", "bar")]
HPS = {
    "pls": PlsHyperparams(n_components=2),
    "esn": EsnHyperparams(units=20, warmup=5, ridge=1e-3),
    "lstm": LstmHyperparams(units=8, layers=1, epochs=5, batch_size=16, sequence_length=5, lr=0.05),
}


def _data(n: int = 50, y=None, seed: int = 0) -> TrainData:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 256, 2)).astype(np.float32)
    noisy = 2.0 * x[:, -1, 0] - x[:, -1, 1] + 3.0 + rng.normal(size=n) * 0.5
    target = noisy if y is None else np.asarray(y, dtype=float)
    return TrainData(x=x, y=target, ts=np.arange(n, dtype=float))


def _train(method: str, data: TrainData, **kw):
    return train(
        method,
        data,
        HPS[method],
        inputs=SEEDS,
        output_name="Viscosidade",
        output_eu="cP",
        period_s=60.0,
        dataset_ids=[1, 2],
        **kw,
    )


def test_nomes_de_entrada_em_numero_diferente_do_conjunto_falham_com_mensagem():
    with pytest.raises(TrainingError) as raised:
        train(
            "pls",
            _data(30),  # 2 entradas
            HPS["pls"],
            inputs=[InputSeed("T1", "°C")],
            output_name="y",
            output_eu="",
            period_s=1.0,
            dataset_ids=[],
        )

    assert str(raised.value) == (
        "O conjunto tem 2 entrada(s), mas foram informados 1 nome(s) de entrada"
    )


def test_poucas_linhas_utilizaveis_falha_com_mensagem():
    data = _data(30)
    data.x[:18, 220, 0] = np.nan  # só 12 análises com os últimos 50 passos íntegros
    hp = LstmHyperparams(sequence_length=50)

    with pytest.raises(TrainingError) as raised:
        train(
            "lstm",
            data,
            hp,
            inputs=SEEDS,
            output_name="y",
            output_eu="",
            period_s=1.0,
            dataset_ids=[],
        )

    assert str(raised.value) == (
        "São necessárias ao menos 20 análises utilizáveis para a janela de 50 passos; há 12"
    )


@pytest.mark.parametrize("method", ["pls", "esn", "lstm"])
def test_alvo_constante_nao_gera_nan(method, as_model):
    data = _data(40, y=np.full(40, 7.0))

    meta, blob, _ = _train(method, data)

    assert meta.metrics["r2"] == 0.0
    weights = unpack_weights(blob)
    assert all(np.isfinite(v).all() for v in weights.values())
    window = select_rows(data, meta.warmup_steps)[0][0]
    assert abs(predict(load_model(1, meta.model_dump(mode="json"), blob), window) - 7.0) < 0.05


@pytest.mark.parametrize("method", ["pls", "lstm"])
def test_entrada_constante_nao_gera_nan(method):
    data = _data(40)
    data.x[:, :, 1] = 4.0  # P1 travada (sensor congelado, setpoint fixo)

    meta, blob, _ = _train(method, data)

    assert all(np.isfinite(v).all() for v in unpack_weights(blob).values())
    assert all(np.isfinite(v) for v in meta.metrics.values())
    assert meta.metrics["r2"] > 0  # o teste mede só a entrada que varia: nenhum pior que a média
    window = select_rows(data, meta.warmup_steps)[0][0]
    assert np.isfinite(predict(load_model(1, meta.model_dump(mode="json"), blob), window))


def test_metricas_vem_do_teste_e_o_modelo_final_usa_tudo(as_model):
    data = _data(50)
    x, y = select_rows(data, 1)
    fit_rows, test_rows = chrono_split(len(y))

    meta, blob, info = _train("pls", data)

    on_80 = as_model("pls", fit_pls(x[fit_rows], y[fit_rows], HPS["pls"]), 2, 1)
    expected = metrics(
        y[test_rows], np.array([predict(on_80, x[i]) for i in range(test_rows.start, 50)])
    )
    assert meta.metrics == pytest.approx(expected)
    assert info == {"rows_used": 50, "rows_test": 10}
    assert info["rows_test"] == -(-50 // 5)  # ceil(0.2 * n)
    final = fit_pls(x, y, HPS["pls"])  # o gravado é o reajuste sobre as 50 linhas
    assert np.allclose(unpack_weights(blob)["w"], final["w"], rtol=1e-5)
    assert not np.allclose(on_80.weights["w"], final["w"], rtol=1e-6)


def test_faixas_de_entrada_no_meta_cobrem_os_k_passos():
    data = _data(40)
    data.x[:, 0, 0] = 1e6  # fora dos últimos 5 passos: não entra na faixa
    data.x[3, -2, 1] = -50.0

    meta, _, _ = _train("lstm", data)

    last5 = data.x[:, -5:, :]
    for j, seed in enumerate(SEEDS):
        assert meta.inputs[j].name == seed.name and meta.inputs[j].eu == seed.eu
        assert meta.inputs[j].min == pytest.approx(float(last5[..., j].min()))
        assert meta.inputs[j].max == pytest.approx(float(last5[..., j].max()))
    assert meta.inputs[1].min == -50.0 and meta.inputs[0].max < 1e3


@pytest.mark.parametrize("method", ["pls", "esn", "lstm"])
def test_artefato_gerado_carrega_com_load_model(method):
    data = _data(40)

    meta, blob, _ = _train(method, data)
    model = load_model(1, meta.model_dump(mode="json"), blob)

    assert model.meta.method == method
    assert model.meta.warmup_steps == {"pls": 1, "esn": 5, "lstm": 5}[method]
    assert model.meta.hyperparams == HPS[method].model_dump()
    assert model.meta.dataset_ids == [1, 2]
    assert (model.meta.output_name, model.meta.output_eu, model.meta.period_s) == (
        "Viscosidade",
        "cP",
        60.0,
    )
    assert set(model.meta.metrics) == {"r2", "rmse", "mae"}


def test_pesos_nao_finitos_falham_com_mensagem(monkeypatch):
    monkeypatch.setattr(
        train_module, "fit", lambda *a, **k: {"w": np.array([np.nan]), "b": np.zeros(1)}
    )

    with pytest.raises(TrainingError, match="não finitos"):
        _train("pls", _data(40))


def test_peso_que_estoura_o_float32_falha_com_mensagem(monkeypatch):
    """Finito em float64, mas o `pack_weights` o grava como inf: a recusa é antes do artefato."""
    monkeypatch.setattr(
        train_module, "fit", lambda *a, **k: {"w": np.array([1e39, 0.0]), "b": np.zeros(1)}
    )

    with pytest.raises(TrainingError, match="não finitos"):
        _train("pls", _data(40))


@pytest.mark.parametrize("quebra_na_chamada", [1, 2])  # 1 = ajuste nos 80%, 2 = reajuste em 100%
def test_value_error_da_biblioteca_vira_mensagem_em_ptbr(monkeypatch, quebra_na_chamada):
    real_fit, chamadas = train_module.fit, []

    def fit(*args, **kw):
        chamadas.append(1)
        if len(chamadas) == quebra_na_chamada:
            raise ValueError("slice 0 has a NaN entry")
        return real_fit(*args, **kw)

    monkeypatch.setattr(train_module, "fit", fit)

    with pytest.raises(TrainingError) as raised:
        _train("pls", _data(40))

    assert str(raised.value) == "O ajuste do PLS falhou com estes dados (ver o log do ml-worker)"
    assert isinstance(raised.value.__cause__, ValueError)  # o original fica encadeado e no log


def test_training_error_do_ajuste_passa_sem_troca_de_mensagem(monkeypatch):
    def fit(*args, **kw):
        raise TrainingError("mensagem do projeto")

    monkeypatch.setattr(train_module, "fit", fit)

    with pytest.raises(TrainingError, match="^mensagem do projeto$"):
        _train("pls", _data(40))


def test_epoch_cb_chega_ao_treinador():
    calls: list[int] = []

    _train("lstm", _data(40), epoch_cb=lambda epoch, loss: calls.append(epoch))

    assert calls == [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]  # as épocas do ajuste nos 80% e as do reajuste
