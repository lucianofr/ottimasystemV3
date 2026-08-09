"""Testes de `ottima_api.validacao.problemas_de_validacao` e `formatar_problemas` —
agregador de 422 do import/export de projeto (spec F6 §3.2-5, decisão A-5, UX-06).
"""

from pydantic import BaseModel, Field, ValidationError

from ottima_api.validacao import formatar_problemas, problemas_de_validacao


class _ModeloDeTeste(BaseModel):
    nome: str = Field(min_length=1)
    idade: int


def _erros_de(**kwargs: object) -> ValidationError:
    try:
        _ModeloDeTeste(**kwargs)
    except ValidationError as exc:
        return exc
    raise AssertionError("esperava ValidationError")


def test_problemas_de_validacao_reusa_traduzir_erro_de_validacao():
    exc = _erros_de(nome="", idade="abc")
    assert problemas_de_validacao(exc) == [
        "nome: mínimo de 1 caractere(s)",
        "idade: deve ser um número inteiro",
    ]


def test_problemas_de_validacao_prefixo_antepoe_ao_caminho():
    exc = _erros_de(nome="", idade=1)
    assert problemas_de_validacao(exc, prefixo="connections[0].") == [
        "connections[0].nome: mínimo de 1 caractere(s)"
    ]


def test_problemas_de_validacao_sem_prefixo_nao_altera_caminho():
    exc = _erros_de(nome="", idade=1)
    assert problemas_de_validacao(exc) == ["nome: mínimo de 1 caractere(s)"]


def test_formatar_problemas_ate_dez_sem_sufixo():
    problemas = [f"campo{i}: erro" for i in range(5)]
    resultado = formatar_problemas(problemas, cabecalho="Import recusado")
    assert resultado == (
        "Import recusado (5 problemas) | campo0: erro | campo1: erro | campo2: erro"
        " | campo3: erro | campo4: erro"
    )


def test_formatar_problemas_cabecalho_nao_hardcoded_import_nem_export():
    """A função não pode fixar nenhum dos dois cabeçalhos normativos internamente."""
    assert formatar_problemas(["x: y"], cabecalho="Import recusado").startswith(
        "Import recusado (1 problemas)"
    )
    assert formatar_problemas(["x: y"], cabecalho="Export recusado").startswith(
        "Export recusado (1 problemas)"
    )


def test_formatar_problemas_teto_de_dez_com_sufixo_e_mais_n():
    problemas = [f"campo{i}: erro" for i in range(13)]
    resultado = formatar_problemas(problemas, cabecalho="Import recusado")
    assert resultado.startswith("Import recusado (13 problemas) | ")
    assert resultado.endswith(" | e mais 3")
    corpo = resultado.removeprefix("Import recusado (13 problemas) | ").removesuffix(" | e mais 3")
    assert corpo.split(" | ") == [f"campo{i}: erro" for i in range(10)]


def test_formatar_problemas_separador_preserva_ponto_e_virgula_do_node_id():
    """UX-06: separador é ' | ', nunca ';' — node_id OPC-UA contém ';' legitimamente
    (`ns=2;s=TT101`) e não pode ser quebrado pelo split do frontend."""
    problemas = [f"campo{i}: erro" for i in range(9)] + [
        "tags[0].node_id: referência inválida para ns=2;s=TT101"
    ]
    resultado = formatar_problemas(problemas, cabecalho="Import recusado")
    corpo = resultado.removeprefix("Import recusado (10 problemas) | ")
    pedacos = corpo.split(" | ")
    assert len(pedacos) == 10
    assert pedacos[-1] == "tags[0].node_id: referência inválida para ns=2;s=TT101"
    assert "ns=2;s=TT101" in pedacos[-1]
