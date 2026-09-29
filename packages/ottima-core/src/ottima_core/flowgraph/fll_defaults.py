"""Base de regras padrao do `fuzzy_loop` (SPEC_FUZZY secao 3.2/4.3).

Modulo FOLHA de proposito deliberado: `parse.py` precisa da constante como default de
`FuzzyLoopConfig.fll` e `contracts_export.py` importa de `parse.py` — colocar a constante
em `contracts_export` fecharia um ciclo de import. `contracts_export` reexporta daqui.

Sugeno de ordem zero (`Constant` + `WeightedAverage`): custo O(numero de regras), exato,
consequentes legiveis em auditoria (SPEC secao 4.3). A superficie resultante e du_n = e_n
na linha de_n = 0, monotonica em `e`, zero na origem e continua — passa nos portoes da
fase K3 por construcao.
"""

FUZZY_LOOP_DEFAULT_FLL = """\
Engine: fuzzy_loop_padrao
InputVariable: e
  enabled: true
  range: -1.000 1.000
  lock-range: true
  term: NG Triangle -1.000 -1.000 -0.500
  term: NP Triangle -1.000 -0.500 0.000
  term: ZE Triangle -0.500 0.000 0.500
  term: PP Triangle 0.000 0.500 1.000
  term: PG Triangle 0.500 1.000 1.000
InputVariable: de
  enabled: true
  range: -1.000 1.000
  lock-range: true
  term: N Triangle -1.000 -1.000 0.000
  term: ZE Triangle -1.000 0.000 1.000
  term: P Triangle 0.000 1.000 1.000
OutputVariable: du
  enabled: true
  range: -1.000 1.000
  lock-range: true
  aggregation: none
  defuzzifier: WeightedAverage
  default: nan
  lock-previous: false
  term: NG Constant -1.000
  term: NP Constant -0.500
  term: ZE Constant 0.000
  term: PP Constant 0.500
  term: PG Constant 1.000
RuleBlock: regras
  enabled: true
  conjunction: AlgebraicProduct
  disjunction: Maximum
  implication: AlgebraicProduct
  activation: General
  rule: if e is NG then du is NG
  rule: if e is NP then du is NP
  rule: if e is ZE and de is N then du is NP
  rule: if e is ZE and de is ZE then du is ZE
  rule: if e is ZE and de is P then du is PP
  rule: if e is PP then du is PP
  rule: if e is PG then du is PG
"""

# Teto de canais do fuzzy_loop v2: 2*n_loops entradas cabem no teto de portas do editor
# (MAX_SCRIPT_PORTS = 8) e a superficie de comissionamento segue 2D por canal.
MAX_FUZZY_LOOPS = 4

_TERMOS_E = """\
  term: NG Triangle -1.000 -1.000 -0.500
  term: NP Triangle -1.000 -0.500 0.000
  term: ZE Triangle -0.500 0.000 0.500
  term: PP Triangle 0.000 0.500 1.000
  term: PG Triangle 0.500 1.000 1.000"""

_TERMOS_DE = """\
  term: N Triangle -1.000 -1.000 0.000
  term: ZE Triangle -1.000 0.000 1.000
  term: P Triangle 0.000 1.000 1.000"""

_TERMOS_DU = """\
  term: NG Constant -1.000
  term: NP Constant -0.500
  term: ZE Constant 0.000
  term: PP Constant 0.500
  term: PG Constant 1.000"""

_REGRAS_CANAL = """\
  rule: if {e} is NG then {du} is NG
  rule: if {e} is NP then {du} is NP
  rule: if {e} is ZE and {de} is N then {du} is NP
  rule: if {e} is ZE and {de} is ZE then {du} is ZE
  rule: if {e} is ZE and {de} is P then {du} is PP
  rule: if {e} is PP then {du} is PP
  rule: if {e} is PG then {du} is PG"""


def fuzzy_loop_default_fll(n_loops: int) -> str:
    """Base de regras padrao para `n_loops` canais (descentralizada: as regras do canal `i`
    mencionam so `e{i}`/`de{i}` — a superficie de cada canal e identica a do default de 1
    canal e passa nos portoes da SPEC secao 5.3 por construcao; regras de desacoplamento
    entre canais sao autoria do usuario).

    `n_loops == 1` devolve a constante canonica VERBATIM (nomes `e`/`de`/`du`): o contrato
    exportado e os testes golden comparam byte a byte.
    """
    if not 1 <= n_loops <= MAX_FUZZY_LOOPS:
        raise ValueError(f"n_loops fora de 1..{MAX_FUZZY_LOOPS}: {n_loops}")
    if n_loops == 1:
        return FUZZY_LOOP_DEFAULT_FLL
    partes = [f"Engine: fuzzy_loop_padrao_{n_loops}canais"]
    for i in range(1, n_loops + 1):
        partes.append(
            f"InputVariable: e{i}\n  enabled: true\n  range: -1.000 1.000\n"
            f"  lock-range: true\n{_TERMOS_E}"
        )
        partes.append(
            f"InputVariable: de{i}\n  enabled: true\n  range: -1.000 1.000\n"
            f"  lock-range: true\n{_TERMOS_DE}"
        )
    for i in range(1, n_loops + 1):
        partes.append(
            f"OutputVariable: du{i}\n  enabled: true\n  range: -1.000 1.000\n"
            f"  lock-range: true\n  aggregation: none\n  defuzzifier: WeightedAverage\n"
            f"  default: nan\n  lock-previous: false\n{_TERMOS_DU}"
        )
    regras = "\n".join(
        _REGRAS_CANAL.format(e=f"e{i}", de=f"de{i}", du=f"du{i}") for i in range(1, n_loops + 1)
    )
    partes.append(
        "RuleBlock: regras\n  enabled: true\n  conjunction: AlgebraicProduct\n"
        f"  disjunction: Maximum\n  implication: AlgebraicProduct\n  activation: General\n{regras}"
    )
    return "\n".join(partes) + "\n"
