"""Contrato do .fll de um bloco fuzzy_loop (SPEC_FUZZY secao 3.2, v2 multicanal).

Compartilhado entre a validacao de save (`validate.py`, com import lazy de fuzzylite) e o
kernel em runtime — a MESMA funcao nas duas camadas do ADR-029, para que um FLL aceito no
save nunca surpreenda no deploy.

v2 (redesenho MIMO): o bloco tem `n_loops` canais de controle; o FLL declara exatamente
`2*n_loops` entradas e `n_loops` saidas, MAPEADAS POSICIONALMENTE (mesma filosofia do
bloco `fuzzy`, ADR-029): a entrada `2i` e o erro normalizado `e_n` do canal `i+1`, a
entrada `2i+1` e a derivada filtrada `de_n` do mesmo canal, e a saida `i` e a taxa `du_n`
do canal. Os NOMES das variaveis sao livres — o contrato trava contagem, faixa e forma,
porque o kernel escala tudo para o universo normalizado [-1,1] e le as saidas em ordem.

`engine` e tipado como `Any` de proposito: este modulo nao importa fuzzylite. Quem chama ja
pagou o import (o validador, dentro da funcao; o kernel, no topo do proprio modulo), e
`ottima_core` continua importavel sem a dependencia carregada.

Por que `lock-previous: false` e `default: nan` sao obrigatorios: com `lock-previous`
ativo o fuzzylite troca resultado invalido pelo ultimo valido, mascarando buraco na base de
regras — a malha parece funcionar por semanas e um dia congela numa regiao nao coberta. O
contrato faz o buraco aparecer como alarme no comissionamento (SPEC secao 4.4).
"""

import math
from typing import Any

CODIGOS = (
    "FLL_INPUT_COUNT_MUST_BE_2N_LOOPS",
    "FLL_OUTPUT_COUNT_MUST_BE_N_LOOPS",
    "FLL_RANGE_MUST_BE_UNIT",
    "FLL_LOCK_RANGE_REQUIRED",
    "FLL_LOCK_PREVIOUS_FORBIDDEN",
    "FLL_DEFAULT_MUST_BE_NAN",
    "FLL_RULEBLOCK_MUST_BE_SINGLE",
)
"""Vocabulario fechado de violacoes — a API formata cada codigo em pt-BR (SPEC secao 3.2)."""


def validate_fll_contract(engine: Any, n_loops: int = 1) -> list[str]:
    """Lista de codigos de violacao do contrato; vazia significa FLL aceito.

    Acumula TODAS as violacoes em vez de parar na primeira: quem cola um .fll do bloco
    `fuzzy` livre no `fuzzy_loop` erra em varios itens de uma vez, e ver a lista completa
    e a diferenca entre uma correcao e cinco rodadas de save.
    """
    erros: list[str] = []
    entradas = list(engine.input_variables)
    saidas = list(engine.output_variables)

    if len(entradas) != 2 * n_loops:
        erros.append("FLL_INPUT_COUNT_MUST_BE_2N_LOOPS")
    if len(saidas) != n_loops:
        erros.append("FLL_OUTPUT_COUNT_MUST_BE_N_LOOPS")

    variaveis = [*entradas, *saidas]
    if any(
        not (math.isclose(var.minimum, -1.0) and math.isclose(var.maximum, 1.0))
        for var in variaveis
    ):
        erros.append("FLL_RANGE_MUST_BE_UNIT")
    if any(not var.lock_range for var in variaveis):
        erros.append("FLL_LOCK_RANGE_REQUIRED")

    for saida in saidas:
        if saida.lock_previous:
            erros.append("FLL_LOCK_PREVIOUS_FORBIDDEN")
        if not math.isnan(saida.default_value):
            erros.append("FLL_DEFAULT_MUST_BE_NAN")

    if len(list(engine.rule_blocks)) != 1:
        erros.append("FLL_RULEBLOCK_MUST_BE_SINGLE")
    return erros
