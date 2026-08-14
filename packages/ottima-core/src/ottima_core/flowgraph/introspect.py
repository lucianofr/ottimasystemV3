"""Introspecção de FLL para a página FUZZY OPERATE (ADR-030).

O frontend nunca parseia FLL (ADR-005, ADR-029): nomes de variáveis, curvas de pertinência
amostradas, normas e texto das regras nascem aqui e chegam prontos via API. `N_PONTOS` é
constante de servidor — a resolução da amostragem nunca vem do cliente (FUZZY-SEC), e o
custo é O(N_PONTOS × termos), limitado pelo teto de tamanho do FLL já aplicado no save.

Import lazy de `fuzzylite`/`numpy` pelo mesmo motivo de `validate._valida_fuzzy`: só este
caminho paga o import, não todo `import ottima_core`.
"""

import math

from pydantic import BaseModel

N_PONTOS = 101
"""Amostras por curva de pertinência — grade única por variável (x compartilhado)."""


class FuzzyTermOut(BaseModel):
    name: str
    kind: str  # nome da classe do termo na fuzzylite (Triangle, Bell, Ramp, ...)
    y: list[float]  # μ em cada ponto de `FuzzyVariableOut.x`; não-finito vira 0.0


class FuzzyVariableOut(BaseModel):
    port: str  # IN1..INn / OUT1..OUTn — posicional, ordem do FLL (ADR-029)
    name: str
    minimum: float
    maximum: float
    x: list[float]  # grade compartilhada pelos termos da variável (len == N_PONTOS)
    terms: list[FuzzyTermOut]
    # Só saídas:
    defuzzifier: str | None = None
    resolution: int | None = None  # só defuzzificadores integrais (Centroid etc.)
    aggregation: str | None = None
    default_value: float | None = None  # `default: nan` vira None (JSON estrito)
    lock_previous: bool = False


class FuzzyRuleBlockOut(BaseModel):
    name: str
    conjunction: str | None = None
    disjunction: str | None = None
    implication: str | None = None
    activation: str | None = None
    rules: list[str]  # texto verbatim; ordem alinhada com `FuzzyState.rules` achatado


class FuzzyIntrospection(BaseModel):
    name: str  # nome do Engine no FLL
    inputs: list[FuzzyVariableOut]
    outputs: list[FuzzyVariableOut]
    rule_blocks: list[FuzzyRuleBlockOut]


def _nome_da_classe(obj: object | None) -> str | None:
    return None if obj is None else type(obj).__name__


def introspect_fll(fll: str) -> FuzzyIntrospection:
    """Monta a introspecção completa de um FLL já validado por `validate_graph` no save.

    FLL que não parseia levanta `ValueError` (mesma mensagem-prefixo de `_valida_fuzzy`) —
    o chamador da API converte em 422.
    """
    import fuzzylite as fl
    import numpy as np

    try:
        engine = fl.FllImporter().from_string(fll)
    except Exception as erro:
        raise ValueError(f"FLL inválido — {erro}") from erro

    def variavel(prefixo: str, indice: int, var: fl.Variable) -> FuzzyVariableOut:
        x = np.linspace(var.minimum, var.maximum, N_PONTOS)
        terms = []
        for term in var.terms:
            y = np.asarray(term.membership(x), dtype=float)
            y = np.where(np.isfinite(y), y, 0.0)
            terms.append(
                FuzzyTermOut(name=term.name, kind=type(term).__name__, y=[float(v) for v in y])
            )
        out = FuzzyVariableOut(
            port=f"{prefixo}{indice}",
            name=var.name,
            minimum=float(var.minimum),
            maximum=float(var.maximum),
            x=[float(v) for v in x],
            terms=terms,
        )
        if isinstance(var, fl.OutputVariable):
            defuzzifier = var.defuzzifier
            out.defuzzifier = _nome_da_classe(defuzzifier)
            if isinstance(defuzzifier, fl.IntegralDefuzzifier):
                out.resolution = int(defuzzifier.resolution)
            out.aggregation = _nome_da_classe(var.aggregation)
            default = float(var.default_value)
            out.default_value = default if math.isfinite(default) else None
            out.lock_previous = bool(var.lock_previous)
        return out

    return FuzzyIntrospection(
        name=engine.name,
        inputs=[variavel("IN", i, var) for i, var in enumerate(engine.input_variables, start=1)],
        outputs=[variavel("OUT", i, var) for i, var in enumerate(engine.output_variables, start=1)],
        rule_blocks=[
            FuzzyRuleBlockOut(
                name=rb.name,
                conjunction=_nome_da_classe(rb.conjunction),
                disjunction=_nome_da_classe(rb.disjunction),
                implication=_nome_da_classe(rb.implication),
                activation=_nome_da_classe(rb.activation),
                rules=[rule.text for rule in rb.rules],
            )
            for rb in engine.rule_blocks
        ],
    )
