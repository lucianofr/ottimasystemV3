"""Amostragem vetorizada da superficie (e_n, de_n) -> du_n (SPEC_FUZZY secao 5).

pyfuzzylite 8.x aceita `numpy.ndarray` nas variaveis: UM `process()` avalia a grade toda,
o que torna a superficie inspecionavel (heatmap de comissionamento) e a validacao
automatica viavel — propriedades sobre grade densa sao triviais; sobre motor de inferencia,
nao (SPEC secao 5.1).

A resolucao e SEMPRE decidida pelo servidor (FUZZY-SEC): 257 pontos por eixo ja sao 66k
avaliacoes, e aceitar o numero do cliente daria um amplificador de carga de graca.

Import de `fuzzylite` no topo e deliberado aqui, diferente de `validate.py`: este modulo
nunca entra no caminho de `import ottima_core` — so quem vai desenhar/validar superficie o
importa, e nesse ponto o motor e o proprio trabalho.
"""

import fuzzylite as fl
import numpy as np


def sample_surface(fll: str, resolution: int = 65) -> np.ndarray:
    """Grade `(resolution, resolution)` float32: eixo 0 = `de_n`, eixo 1 = `e_n`.

    NaN onde nenhuma regra dispara — propagado de proposito, e o insumo do portao `NO_NAN`
    e a razao de `default: nan` ser obrigatorio no contrato (SPEC secao 3.2).
    """
    engine = fl.FllImporter().from_string(fll)
    eixo = np.linspace(-1.0, 1.0, resolution)
    de_grid, e_grid = np.meshgrid(eixo, eixo, indexing="ij")
    engine.input_variable("e").value = e_grid.ravel()
    engine.input_variable("de").value = de_grid.ravel()
    engine.process()
    du = np.asarray(engine.output_variable("du").value, dtype=np.float32)
    return du.reshape(resolution, resolution)
