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
