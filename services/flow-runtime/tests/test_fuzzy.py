"""Contratos do bloco Fuzzy contra hand-calc e semântica de não-finito (RF-541..543, ADR-029).

`IDENTIDADE_FLL` é um motor Mamdani mínimo (1 entrada/1 saída) com cobertura total e
simetria de propósito: qualquer ponto interior do domínio dá um agregado simétrico em torno
de si mesmo, então o centroide é o próprio ponto — hand-calc por simetria, sem precisar
resolver a integral do defuzzificador à mão.
"""

import math

import pytest

from ottima_core.contracts_export import FUZZY_DEFAULT_FLL
from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.fuzzy import FuzzyBlock

IDENTIDADE_FLL = """Engine: identidade
InputVariable: X
  enabled: true
  range: 0.000 10.000
  lock-range: false
  term: low Triangle 0.000 0.000 10.000
  term: high Triangle 0.000 10.000 10.000
OutputVariable: Y
  enabled: true
  range: 0.000 10.000
  lock-range: false
  aggregation: Maximum
  defuzzifier: Centroid 1000
  default: nan
  lock-previous: false
  term: low Triangle 0.000 0.000 10.000
  term: high Triangle 0.000 10.000 10.000
RuleBlock: rb1
  enabled: true
  conjunction: none
  disjunction: none
  implication: Minimum
  activation: General
  rule: if X is low then Y is low
  rule: if X is high then Y is high"""
"""Partição linear low/high (soma das pertinências = 1 em todo o domínio, 'cobertura
total'); termos de saída espelham os de entrada, então em qualquer x o agregado é simétrico
em torno de x e o centroide é exatamente x (por simetria, não por integral)."""

SEM_COBERTURA_FLL = """Engine: sem_cobertura
InputVariable: X
  enabled: true
  range: 0.000 10.000
  lock-range: false
  term: mid Triangle 4.000 5.000 6.000
OutputVariable: Y
  enabled: true
  range: 0.000 10.000
  lock-range: false
  aggregation: Maximum
  defuzzifier: Centroid 1000
  default: nan
  lock-previous: false
  term: mid Triangle 4.000 5.000 6.000
RuleBlock: rb1
  enabled: true
  conjunction: none
  disjunction: none
  implication: Minimum
  activation: General
  rule: if X is mid then Y is mid"""
"""Termo estreito (Triangle 4-5-6): fora de [4,6] nenhuma regra dispara, o conjunto
agregado fica vazio e a defuzzificação cai no `default: nan` — não-cobertura de propósito."""

LOCK_PREVIOUS_FLL = """Engine: retem
InputVariable: X
  enabled: true
  range: 0.000 10.000
  lock-range: false
  term: mid Triangle 4.000 5.000 6.000
OutputVariable: Y
  enabled: true
  range: 0.000 10.000
  lock-range: false
  aggregation: Maximum
  defuzzifier: Centroid 1000
  default: 0.000
  lock-previous: true
  term: mid Triangle 4.000 5.000 6.000
RuleBlock: rb1
  enabled: true
  conjunction: none
  disjunction: none
  implication: Minimum
  activation: General
  rule: if X is mid then Y is mid"""
"""Mesmo termo estreito, mas `lock-previous: true`: fora de [4,6] a `fuzzylite` retém o
último valor defuzzificado (estado interno do `Engine`, não deste bloco) em vez de cair no
`default`."""

INCOMPLETO_FLL = """Engine: incompleto
InputVariable: a
  enabled: true
  range: 0.000 10.000
  lock-range: false
  term: low Triangle 0.000 0.000 10.000
InputVariable: b
  enabled: true
  range: 0.000 10.000
  lock-range: false
  term: low Triangle 0.000 0.000 10.000
OutputVariable: out1
  enabled: true
  range: 0.000 10.000
  lock-range: false
  aggregation: Maximum
  defuzzifier: none
  default: 0.000
  lock-previous: false
  term: low Triangle 0.000 0.000 10.000
RuleBlock: rb1
  enabled: true
  conjunction: none
  disjunction: none
  implication: Minimum
  activation: General
  rule: if a is low and b is low then out1 is low"""
"""Sintaxe válida, `Engine.is_ready()` reprova: regra com `and` sem `conjunction`, saída
Mamdani sem `defuzzifier`."""

INVALIDO_FLL = "isto não é FuzzyLite Language nem de longe\n=== !!! ==="


def bloco(fll: str, *, n_inputs: int = 1, n_outputs: int = 1, block_id: str = "fz1") -> FuzzyBlock:
    return FuzzyBlock(block_id, fll=fll, n_inputs=n_inputs, n_outputs=n_outputs)


async def passo(block: FuzzyBlock, valor: float | None, *, ok: bool = True) -> PortSample:
    return (await block.step({"IN1": PortSample(valor, ok)}))["OUT1"]


# --------------------------------------------------------------------------------------
# (a) hand-calc por simetria + (b) cold start + (c) invalidez propagada
# --------------------------------------------------------------------------------------


async def test_a_hand_calc_por_simetria():
    saida = await passo(bloco(IDENTIDADE_FLL), 5.0)
    assert saida.v == pytest.approx(5.0, abs=0.05)
    assert saida.ok is True


async def test_b_cold_start_devolve_null_outputs():
    saida = await passo(bloco(IDENTIDADE_FLL), None)
    assert saida == PortSample(None, False)


async def test_c_entrada_ok_false_executa_e_propaga_flag():
    """Decisão A-6 estendida (RF-542): valor finito com flag ruim ainda executa o motor."""
    saida = await passo(bloco(IDENTIDADE_FLL), 5.0, ok=False)
    assert saida.v == pytest.approx(5.0, abs=0.05)
    assert saida.ok is False


# --------------------------------------------------------------------------------------
# (d)/(e)/(e2) falhas de construção
# --------------------------------------------------------------------------------------


def test_d_fll_invalido_levanta_na_construcao():
    with pytest.raises(ValueError, match="FLL inválido"):
        bloco(INVALIDO_FLL)


def test_e_contagem_divergente_levanta_na_construcao():
    """`IDENTIDADE_FLL` declara 1 entrada; pedir 2 diverge."""
    with pytest.raises(ValueError, match="variável"):
        bloco(IDENTIDADE_FLL, n_inputs=2)


def test_e2_is_ready_reprovado_levanta_com_mensagem_da_lib():
    with pytest.raises(ValueError, match="motor fuzzy não está pronto"):
        bloco(INCOMPLETO_FLL, n_inputs=2, n_outputs=1)


# --------------------------------------------------------------------------------------
# (f) exceção em process()
# --------------------------------------------------------------------------------------


async def test_f_excecao_em_process_mantem_saidas_e_marca_ok_false(monkeypatch):
    block = bloco(IDENTIDADE_FLL)
    primeiro = await passo(block, 5.0)
    assert primeiro.ok is True

    def _explode() -> None:
        raise RuntimeError("falha simulada do motor fuzzy")

    monkeypatch.setattr(block._engine, "process", _explode)
    segundo = await passo(block, 7.0)
    assert segundo.v == primeiro.v
    assert segundo.ok is False


# --------------------------------------------------------------------------------------
# (g) sem cobertura: (None, False) antes do 1o bom, (ultimo bom, False) depois
# --------------------------------------------------------------------------------------


async def test_g_saida_nao_finita_mantem_ultimo_bom_por_porta():
    block = bloco(SEM_COBERTURA_FLL)

    antes_do_primeiro_bom = await passo(block, 1.0)  # fora de [4,6]: default:nan
    assert antes_do_primeiro_bom == PortSample(None, False)

    scan_bom = await passo(block, 5.0)  # pico do termo: agregado não-vazio
    assert scan_bom.v is not None
    assert math.isfinite(scan_bom.v)
    assert scan_bom.ok is True

    depois_do_bom = await passo(block, 1.0)  # fora de [4,6] de novo: default:nan
    assert depois_do_bom.v == scan_bom.v
    assert depois_do_bom.ok is False


# --------------------------------------------------------------------------------------
# (h) lock-previous retém entre varreduras; reset() limpa o estado da fuzzylite
# --------------------------------------------------------------------------------------


async def test_h_lock_previous_retem_e_reset_limpa_o_estado_da_lib():
    block = bloco(LOCK_PREVIOUS_FLL)

    pico = await passo(block, 5.0)  # dentro de [4,6]: valor real, fica retido internamente
    assert pico.v == pytest.approx(5.0, abs=0.05)

    retido = await passo(block, 1.0)  # fora de [4,6]: lock-previous devolve o valor de pico
    assert retido.v == pytest.approx(pico.v, abs=1e-9)
    assert retido.ok is True

    block.reset()  # engine.restart(): limpa previous_value junto com as entradas (RF-543)

    pos_reset = await passo(block, 1.0)  # mesma consulta: sem estado travado, cai no default
    assert pos_reset.v == pytest.approx(0.0, abs=1e-9)
    assert pos_reset.v != pytest.approx(pico.v, abs=0.1)


async def test_construcao_nao_contamina_lock_previous_do_warmup():
    """Regressão do hot-swap-add: `scheduler._adopt_staged` nunca chama `reset()` em bloco
    novo, então o `self.reset()` no fim de `__init__` é a única defesa — sem ele, o
    `process()` de aquecimento do construtor deixaria `previous_value` contaminado e a
    primeira varredura fora de cobertura devolveria o valor do warmup em vez do default."""
    block = bloco(LOCK_PREVIOUS_FLL)

    # Primeira consulta fora de [4,6] logo após a construção: se o warmup contaminou o
    # lock-previous, viria o valor de meio-de-faixa do aquecimento, não o default 0.0.
    primeira = await passo(block, 1.0)
    assert primeira.v == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------------------
# (i) nan com ok=True executa e marca ok=False; (j) inf tratado como não-finito
# --------------------------------------------------------------------------------------


async def test_i_entrada_nan_com_ok_true_executa_mas_marca_ok_false():
    saida = await passo(bloco(IDENTIDADE_FLL), float("nan"), ok=True)
    assert saida.ok is False
    assert saida.v is None or math.isfinite(saida.v)  # nunca nan/inf escapando


async def test_j_saida_infinita_e_tratada_como_nao_finita(monkeypatch):
    block = bloco(IDENTIDADE_FLL)

    def _saida_infinita() -> None:
        block._engine.output_variables[0].value = float("inf")

    monkeypatch.setattr(block._engine, "process", _saida_infinita)
    saida = await passo(block, 5.0)
    assert saida.v is None  # nenhum scan bom anterior — nada para reter
    assert saida.ok is False


# --------------------------------------------------------------------------------------
# Deploy default: a paleta que o editor cola por padrão precisa construir e processar
# --------------------------------------------------------------------------------------


async def test_deploy_default_constroi_e_processa():
    block = FuzzyBlock("fz-default", fll=FUZZY_DEFAULT_FLL, n_inputs=1, n_outputs=4)
    assert block.input_ports == ("IN1",)
    assert block.output_ports == ("OUT1", "OUT2", "OUT3", "OUT4")

    saidas = await block.step({"IN1": PortSample(0.0, True)})
    assert set(saidas) == {"OUT1", "OUT2", "OUT3", "OUT4"}
