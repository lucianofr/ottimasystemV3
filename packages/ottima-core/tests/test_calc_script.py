"""Testes de `ottima_core.calc_script.problemas_do_script` (RF-208, ADR-033 §3):
validador único de conteúdo de script, compartilhado entre CRUD e import (achado crítico
da revisão de fase 5) — inclui a defesa em profundidade estendida de
`flowgraph.validate.check_script_code` (dunder em mais tipos de nó, reatribuição de
atributo de módulo injetado), exercitada aqui pelo passo 1 de `problemas_do_script`.
"""

import ast

from ottima_core.calc_script import problemas_do_script


def test_script_valido_sem_problemas():
    assert problemas_do_script("OUT = IN1 + IN2", 2) == []


def test_dunder_name_e_reprovado():
    problemas = problemas_do_script("OUT = 1\nx = __class__\n", 0)
    assert problemas == ["código não pode acessar nomes dunder"]


def test_dunder_attribute_e_reprovado():
    problemas = problemas_do_script("OUT = len(().__class__.__mro__)\n", 0)
    assert problemas == ["código não pode acessar nomes dunder"]


def test_dunder_em_parametro_de_funcao_nunca_referenciado_e_reprovado():
    """`__x__` só aparece como `ast.arg` — a checagem original (só `Name`/`Attribute`)
    deixava passar; a extensão da revisão de fase 5 cobre o parâmetro."""
    problemas = problemas_do_script("def f(__x__):\n    return 1\nOUT = f(1)\n", 0)
    assert problemas == ["código não pode acessar nomes dunder"]


def test_dunder_em_alias_de_import_e_reprovado():
    problemas = problemas_do_script("import __os__\nOUT = 1\n", 0)
    assert problemas == ["código não pode acessar nomes dunder"]


def test_dunder_em_asname_de_import_e_reprovado():
    problemas = problemas_do_script("import functools as __ft__\nOUT = 1\n", 0)
    assert problemas == ["código não pode acessar nomes dunder"]


def test_dunder_em_except_handler_e_reprovado():
    codigo = "try:\n    pass\nexcept Exception as __e__:\n    pass\nOUT = 1\n"
    assert problemas_do_script(codigo, 0) == ["código não pode acessar nomes dunder"]


def test_dunder_em_nome_de_funcao_e_reprovado():
    problemas = problemas_do_script("def __init__():\n    pass\nOUT = 1\n", 0)
    assert problemas == ["código não pode acessar nomes dunder"]


def test_dunder_em_nome_de_classe_e_reprovado():
    problemas = problemas_do_script("class __C__:\n    pass\nOUT = 1\n", 0)
    assert problemas == ["código não pode acessar nomes dunder"]


def test_dunder_em_global_e_reprovado():
    codigo = "def f():\n    global __g__\nOUT = 1\n"
    assert problemas_do_script(codigo, 0) == ["código não pode acessar nomes dunder"]


def test_reatribuicao_de_atributo_de_math_e_reprovada():
    problemas = problemas_do_script("math.pi = 3\nOUT = 1.0\n", 0)
    assert len(problemas) == 1
    assert "math" in problemas[0]
    assert "reatribuir" in problemas[0]


def test_reatribuicao_de_atributo_de_np_e_reprovada():
    problemas = problemas_do_script("np.foo = 1\nOUT = 1.0\n", 0)
    assert len(problemas) == 1
    assert "np" in problemas[0]


def test_reatribuicao_de_atributo_aninhado_de_numpy_e_reprovada():
    problemas = problemas_do_script("numpy.random.bit_generator = None\nOUT = 1.0\n", 0)
    assert len(problemas) == 1
    assert "numpy" in problemas[0]


def test_reatribuicao_de_atributo_de_state_e_permitida():
    """`state` é o único módulo injetado que o contrato do script espera que seja
    mutado (`ottima_core.script_pool`) — não pode virar falso positivo."""
    assert problemas_do_script("state.counter = 1\nOUT = state.counter\n", 0) == []


def test_chamada_que_muda_estado_global_de_numpy_nao_e_fechada_por_esta_checagem():
    """Residual documentado (ADR-033): uma CHAMADA (não um `Store` de atributo) não passa
    por esta checagem — `numpy.seterr(...)` seria fechado só por sandbox mais pesado."""
    assert problemas_do_script("numpy.seterr(all='ignore')\nOUT = 1.0\n", 0) == []


def test_erro_de_sintaxe_vira_problema_com_linha_e_coluna():
    problemas = problemas_do_script("OUT = (", 0)
    assert len(problemas) == 1
    assert "sintaxe" in problemas[0].lower()
    assert "linha" in problemas[0].lower()


def test_sem_atribuir_out_e_problema():
    assert problemas_do_script("x = 1", 0) == ["O script precisa atribuir a variável OUT"]


def test_in_acima_do_alcance_e_problema():
    problemas = problemas_do_script("OUT = IN3", 2)
    assert len(problemas) == 1
    assert "IN3" in problemas[0]


def test_ordem_dunder_precede_atribuicao_de_out():
    """Dunder é a checagem 1: mesmo sem `OUT` atribuído (que só falharia na checagem 3),
    só o motivo do dunder aparece — a mesma ordem que o CRUD sempre impôs."""
    problemas = problemas_do_script("x = __class__\n", 0)
    assert problemas == ["código não pode acessar nomes dunder"]


def test_memory_error_no_parser_nao_escapa_como_500(monkeypatch):
    def _explode(*args, **kwargs):
        raise MemoryError

    monkeypatch.setattr(ast, "parse", _explode)
    problemas = problemas_do_script("OUT = 1", 0)
    assert len(problemas) == 1
    assert "limite" in problemas[0].lower()


def test_recursion_error_no_parser_nao_escapa_como_500(monkeypatch):
    def _explode(*args, **kwargs):
        raise RecursionError

    monkeypatch.setattr(ast, "parse", _explode)
    problemas = problemas_do_script("OUT = 1", 0)
    assert len(problemas) == 1
    assert "limite" in problemas[0].lower()


def test_value_error_no_compile_nao_escapa_como_500(monkeypatch):
    def _explode(*args, **kwargs):
        raise ValueError("source code string cannot contain null bytes")

    monkeypatch.setattr("builtins.compile", _explode)
    problemas = problemas_do_script("OUT = 1", 0)
    assert len(problemas) == 1
    assert "limite" in problemas[0].lower()
