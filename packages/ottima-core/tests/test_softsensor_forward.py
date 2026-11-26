"""Testes da conta dos três métodos do sensor virtual (RF-581, ADR-046 D4, spec §5.3).

A prova de corretude do ESN e do LSTM são as referências escritas por extenso aqui (laço Python,
escalar por escalar, sem vetorizar), com padronização NÃO trivial: os sintéticos usam média 0 e
desvio 1, e sem repadronizar uma (des)padronização ausente ou invertida passaria despercebida.
"""

import math

import numpy as np
import pytest

from ottima_core.softsensor import (
    ModelMeta,
    load_model,
    pack_weights,
    predict,
    synthetic,
    unpack_weights,
)

ESN_GOLDEN = (
    -1.6527817099701174
)  # trava regressão; a prova de corretude é a recorrência por extenso

NORMALIZACAO = {
    "x_mean": np.array([1.5, -2.0]),
    "x_std": np.array([0.5, 0.0]),  # desvio zero (entrada constante no treino) vale 1.0
    "y_mean": np.array([3.0]),
    "y_std": np.array([2.0]),
}


def _modelo(par: tuple[ModelMeta, bytes]):
    return load_model(1, par[0].model_dump(mode="json"), par[1])


def _modelo_padronizado(par: tuple[ModelMeta, bytes]):
    pesos = unpack_weights(par[1]) | NORMALIZACAO
    return _modelo((par[0], pack_weights(pesos)))


def _janela(linhas: int, colunas: int = 2, semente: int = 1) -> np.ndarray:
    # Valores assimétricos: a ordem das linhas e das colunas muda o resultado.
    return np.random.default_rng(semente).uniform(-3.0, 3.0, size=(linhas, colunas))


def _padroniza(valor: float, media: float, desvio: float) -> float:
    return (valor - media) / (desvio if desvio != 0.0 else 1.0)


def test_pls_e_o_produto_escalar_mais_o_termo_independente():
    m = _modelo(synthetic.pls([2.0, -1.0], 0.5))
    assert predict(m, np.array([[3.0, 4.0]])) == pytest.approx(2.5)


def test_pls_usa_so_a_ultima_amostra_da_janela():
    meta, blob = synthetic.pls([2.0, -1.0], 0.5)
    m = load_model(1, meta.model_dump(mode="json") | {"warmup_steps": 3}, blob)
    janela = np.array([[100.0, 100.0], [-50.0, 7.0], [3.0, 4.0]])
    assert predict(m, janela) == pytest.approx(2.5)


def test_esn_e_funcao_pura_da_janela():
    m = _modelo(synthetic.esn(2, warmup=5))
    janela = np.random.default_rng(1).random((5, 2))
    assert predict(m, janela) == predict(m, janela.copy())


def test_esn_valor_fixo_com_semente_fixa():
    m = _modelo(synthetic.esn(2, units=20, warmup=5, seed=42))
    janela = np.linspace(0.0, 1.0, 10).reshape(5, 2)
    assert predict(m, janela) == pytest.approx(ESN_GOLDEN, rel=1e-5)


def test_esn_confere_com_a_recorrencia_escrita_por_extenso():
    m = _modelo_padronizado(synthetic.esn(2, units=7, warmup=6, seed=3))
    janela = _janela(6)
    w = {k: v.tolist() for k, v in m.weights.items()}
    u, lr = len(w["bias"]), w["lr"][0]
    s = [0.0] * u
    for linha in janela:
        xn = [_padroniza(x, w["x_mean"][j], w["x_std"][j]) for j, x in enumerate(linha.tolist())]
        pre = [
            sum(w["W"][r][c] * s[c] for c in range(u))
            + sum(w["Win"][r][c] * xn[c] for c in range(len(xn)))
            + w["bias"][r]
            for r in range(u)
        ]
        s = [(1 - lr) * s[r] + lr * math.tanh(pre[r]) for r in range(u)]
    y = sum(w["Wout"][r] * s[r] for r in range(u)) + w["b_out"][0]
    esperado = y * w["y_std"][0] + w["y_mean"][0]
    assert predict(m, janela) == pytest.approx(esperado, rel=1e-9)


def test_esn_depende_da_ordem_das_linhas_da_janela():
    m = _modelo(synthetic.esn(2, warmup=5))
    janela = _janela(5)
    assert predict(m, janela) != pytest.approx(predict(m, janela[::-1]), rel=1e-6)


def test_lstm_com_pesos_zero_devolve_o_bias_da_camada_final_despadronizado():
    meta, blob = synthetic.lstm(2, units=4, layers=2, sequence_length=3)
    pesos = {k: np.zeros_like(v) for k, v in unpack_weights(blob).items()}
    pesos |= NORMALIZACAO | {"fc_b": np.array([0.7])}
    m = _modelo((meta, pack_weights(pesos)))
    # Com todos os pesos zero o estado oculto é 0.5*tanh(0) = 0: y = fc_b*y_std + y_mean.
    assert predict(m, _janela(3)) == pytest.approx(0.7 * 2.0 + 3.0)


def _sigmoide(v: float) -> float:
    return 1.0 / (1.0 + math.exp(-v))


def test_lstm_confere_com_a_celula_escrita_por_extenso():
    m = _modelo_padronizado(synthetic.lstm(2, units=3, layers=2, sequence_length=4, seed=5))
    janela = _janela(4)
    w = {k: v.tolist() for k, v in m.weights.items()}
    u = len(w["fc_w"])
    seq = [
        [_padroniza(x, w["x_mean"][j], w["x_std"][j]) for j, x in enumerate(linha)]
        for linha in janela.tolist()
    ]
    for k in range(2):
        h, c, saida = [0.0] * u, [0.0] * u, []
        for x in seq:
            # PyTorch: gates = w_ih@x + b_ih + w_hh@h + b_hh, em blocos de u linhas i, f, g, o.
            gates = [
                sum(w[f"w_ih_{k}"][r][j] * x[j] for j in range(len(x)))
                + w[f"b_ih_{k}"][r]
                + sum(w[f"w_hh_{k}"][r][j] * h[j] for j in range(u))
                + w[f"b_hh_{k}"][r]
                for r in range(4 * u)
            ]
            i, f, g, o = (gates[b * u : (b + 1) * u] for b in range(4))
            c = [_sigmoide(f[j]) * c[j] + _sigmoide(i[j]) * math.tanh(g[j]) for j in range(u)]
            h = [_sigmoide(o[j]) * math.tanh(c[j]) for j in range(u)]
            saida.append(h)
        seq = saida
    y = sum(w["fc_w"][j] * seq[-1][j] for j in range(u)) + w["fc_b"][0]
    esperado = y * w["y_std"][0] + w["y_mean"][0]
    assert predict(m, janela) == pytest.approx(esperado, rel=1e-9)


def test_lstm_depende_da_ordem_das_linhas_da_janela():
    m = _modelo(synthetic.lstm(2, units=3, layers=2, sequence_length=4))
    janela = _janela(4)
    assert predict(m, janela) != pytest.approx(predict(m, janela[::-1]), rel=1e-6)


def test_predict_devolve_nao_finito_sem_levantar():
    m = _modelo(synthetic.pls([1.0], 0.0))
    assert not math.isfinite(predict(m, np.array([[float("inf")]])))


@pytest.mark.parametrize("ruim", [float("inf"), float("-inf"), float("nan")])
@pytest.mark.parametrize(
    "par",
    [
        lambda: synthetic.esn(2, warmup=4),
        lambda: synthetic.lstm(2, sequence_length=4),
    ],
    ids=["esn", "lstm"],
)
def test_janela_nao_finita_nunca_vira_saida_finita(par, ruim):
    # tanh e sigmoide saturam: sem a guarda, um inf na janela renderia um número "normal".
    m = _modelo(par())
    janela = _janela(4)
    janela[1, 0] = ruim
    assert not math.isfinite(predict(m, janela))


def test_predict_nao_levanta_com_overflow_em_entrada_finita():
    m = _modelo(synthetic.pls([1e30, 1e30], 0.0))
    assert not math.isfinite(predict(m, np.array([[1e300, 1e300]])))


def test_predict_recusa_janela_de_forma_errada():
    m = _modelo(synthetic.esn(2, warmup=5))
    with pytest.raises(ValueError):
        predict(m, np.zeros((6, 2)))  # buffer maior que warmup_steps
    with pytest.raises(ValueError):
        predict(m, np.zeros((5, 3)))
