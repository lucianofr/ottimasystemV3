"""PLS (RF-587): `PLSRegression` sobre a última linha da janela, reduzido a `w` e `b` em unidade
de engenharia."""

import numpy as np
from pydantic import BaseModel
from sklearn.cross_decomposition import PLSRegression


def fit_pls(x_k: np.ndarray, y: np.ndarray, hp: BaseModel) -> dict[str, np.ndarray]:
    x = x_k[:, -1, :].astype(np.float64)
    n, d = x.shape
    # Coluna constante vira zero depois de centrada: o NIPALS deflaciona X a zero e o componente
    # seguinte dá 0/0. Só as colunas que variam entram, e o teto é o posto delas, não a contagem.
    varies = np.ptp(x, axis=0) > 0
    w, b = np.zeros(d), np.array([float(np.mean(y))])  # tudo constante: o modelo é a média de y
    if varies.any():
        xv = x[:, varies]
        rank = np.linalg.matrix_rank((xv - xv.mean(0)) / xv.std(0))
        model = PLSRegression(n_components=max(1, min(hp.n_components, rank, n - 1)), scale=True)
        model.fit(xv, y)
        # O modelo é afim: `predict` em 0 e nos vetores da base dá `b` e `w` em unidade bruta, sem
        # depender de onde esta versão do scikit-learn guarda a normalização.
        b = np.ravel(model.predict(np.zeros((1, xv.shape[1]))))
        w[varies] = np.ravel(model.predict(np.eye(xv.shape[1]))) - b[0]
    return {"w": w, "b": b}
