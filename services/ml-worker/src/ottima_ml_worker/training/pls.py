"""PLS (RF-587): `PLSRegression` sobre a última linha da janela, reduzido a `w` e `b` em unidade
de engenharia."""

import numpy as np
from pydantic import BaseModel
from sklearn.cross_decomposition import PLSRegression


def fit_pls(x_k: np.ndarray, y: np.ndarray, hp: BaseModel) -> dict[str, np.ndarray]:
    x = x_k[:, -1, :].astype(np.float64)
    n, d = x.shape
    model = PLSRegression(n_components=min(hp.n_components, d, n - 1), scale=True).fit(x, y)
    # O modelo é afim: `predict` em 0 e nos vetores da base dá `b` e `w` em unidade bruta, sem
    # depender de onde esta versão do scikit-learn guarda a normalização.
    b = np.ravel(model.predict(np.zeros((1, d))))
    return {"w": np.ravel(model.predict(np.eye(d))) - b[0], "b": b}
