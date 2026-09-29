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


def sample_surface(
    fll: str, resolution: int = 65, n_loops: int = 1, channel: int = 0
) -> np.ndarray:
    """Grade `(resolution, resolution)` float32 do canal `channel`: eixo 0 = `de_n`, eixo 1
    = `e_n`. Variaveis posicioneis (contrato v2): entrada `2c` = `e_n` do canal `c`,
    entrada `2c+1` = `de_n`; os DEMAIS canais ficam no ponto de operacao zero — a fatia
    inspectavel e sempre 2D, e e assim que os portoes da SPEC secao 5.3 rodam por canal.

    NaN onde nenhuma regra dispara — propagado de proposito, e o insumo do portao `NO_NAN`
    e a razao de `default: nan` ser obrigatorio no contrato (SPEC secao 3.2).
    """
    if not 0 <= channel < n_loops:
        raise ValueError(f"channel {channel} fora de 0..{n_loops - 1}")
    engine = fl.FllImporter().from_string(fll)
    eixo = np.linspace(-1.0, 1.0, resolution)
    de_grid, e_grid = np.meshgrid(eixo, eixo, indexing="ij")
    entradas = list(engine.input_variables)
    if len(entradas) != 2 * n_loops:
        raise ValueError(
            f"FLL declara {len(entradas)} entradas; o contrato do canal espera {2 * n_loops}"
        )
    for var in entradas:
        var.value = 0.0
    entradas[2 * channel].value = e_grid.ravel()
    entradas[2 * channel + 1].value = de_grid.ravel()
    engine.process()
    du = np.asarray(list(engine.output_variables)[channel].value, dtype=np.float32)
    return du.reshape(resolution, resolution)
