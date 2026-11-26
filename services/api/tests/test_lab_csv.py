"""Parser do CSV de análises de laboratório (RF-585, spec do sensor virtual §7.2)."""

from datetime import UTC, datetime

import pytest

from ottima_api.lab_csv import MAX_LAB_CSV_BYTES, LabCsvError, LabCsvRow, parse_lab_csv

CONHECIDAS = {"ENXOFRE": 1, "VISC": 2}
AGORA = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)
SP_08_30 = datetime(2026, 11, 25, 11, 30, tzinfo=UTC)  # 08:30 em São Paulo (UTC-3, sem verão)


def p(texto, tz="America/Sao_Paulo"):
    return parse_lab_csv(texto.encode(), tz=tz, known=CONHECIDAS, now=AGORA)


def problemas(texto, tz="America/Sao_Paulo"):
    with pytest.raises(LabCsvError) as e:
        p(texto, tz)
    return e.value.problems


def test_constantes_do_contrato():
    assert MAX_LAB_CSV_BYTES == 5 * 1024 * 1024


def test_linha_simples():
    [r] = p('"ENXOFRE";"25/11/2026 08:30";"12,5"')
    assert r == LabCsvRow(1, datetime(2026, 11, 25, 11, 30, tzinfo=UTC), 12.5)


def test_csv_do_excel_brasileiro():
    bruto = (
        "\ufeff"
        + '"nome do TAG";"data/hora";"valor"\r\n"ENXOFRE";"25/11/2026 08:30";"12,5"\r\n\r\n'
    )
    rows = parse_lab_csv(bruto.encode("utf-8"), tz="America/Sao_Paulo", known=CONHECIDAS, now=AGORA)
    assert rows == [LabCsvRow(1, SP_08_30, 12.5)]


def test_iso_com_offset_ignora_o_tz_do_navegador():
    [r] = p('"ENXOFRE";"2026-11-25T08:30:00+00:00";"1"', tz="America/Sao_Paulo")
    assert r.sampled_at == datetime(2026, 11, 25, 8, 30, tzinfo=UTC)
    [z] = p("ENXOFRE;2026-11-25T08:30:00Z;1", tz="America/Sao_Paulo")
    assert z.sampled_at == datetime(2026, 11, 25, 8, 30, tzinfo=UTC)


def test_iso_sem_offset_usa_o_tz():
    [r] = p("ENXOFRE;2026-11-25T08:30:00;1")
    assert r.sampled_at == SP_08_30


def test_ponto_decimal_e_segundos():
    [r] = p('"ENXOFRE";"25/11/2026 08:30:15";"12.5"')
    assert r == LabCsvRow(1, datetime(2026, 11, 25, 11, 30, 15, tzinfo=UTC), 12.5)


def test_sem_cabecalho_tambem_importa():
    assert p("ENXOFRE;25/11/2026 08:30;12,5") == [LabCsvRow(1, SP_08_30, 12.5)]
    assert p("nome;data;valor\nENXOFRE;25/11/2026 08:30;12,5") == [LabCsvRow(1, SP_08_30, 12.5)]


def test_varias_variaveis_no_mesmo_arquivo():
    rows = p("ENXOFRE;25/11/2026 08:30;1\nVISC;25/11/2026 08:30;2,5\nENXOFRE;25/11/2026 09:00;3")
    assert rows == [
        LabCsvRow(1, SP_08_30, 1.0),
        LabCsvRow(2, SP_08_30, 2.5),
        LabCsvRow(1, datetime(2026, 11, 25, 12, 0, tzinfo=UTC), 3.0),
    ]


def test_repetida_no_arquivo_vale_a_ultima():
    # Mesmo instante escrito de duas formas: ON CONFLICT não admite a mesma chave duas vezes.
    rows = p(
        "ENXOFRE;25/11/2026 08:30;1\nENXOFRE;25/11/2026 08:30:00;2\nENXOFRE;2026-11-25T11:30:00Z;3"
    )
    assert rows == [LabCsvRow(1, SP_08_30, 3.0)]


def test_nome_desconhecido_recusa_o_arquivo_inteiro():
    with pytest.raises(LabCsvError) as e:
        p('"ENXOFRE";"25/11/2026 08:30";"1"\n"OUTRA";"25/11/2026 08:30";"2"')
    assert e.value.problems == [
        "linha 2: variável de laboratório 'OUTRA' não existe no projeto ativo"
    ]


def test_data_futura_e_recusada():
    # 13:00 em São Paulo = 16:00 UTC > AGORA (15:00 UTC)
    assert problemas("ENXOFRE;25/11/2026 13:00;1") == [
        "linha 1: data/hora '25/11/2026 13:00' é posterior ao momento atual"
    ]
    # exatamente agora (12:00 em SP = 15:00 UTC) não é futuro
    assert p("ENXOFRE;25/11/2026 12:00;1")[0].sampled_at == AGORA


def test_data_ilegivel():
    texto = "ENXOFRE;31/02/2026 08:30;1\nENXOFRE;ontem;1\nENXOFRE;25/11/26 08:30;1"
    assert problemas(texto) == [
        "linha 1: data/hora '31/02/2026 08:30' ilegível (use dd/mm/aaaa hh:mm ou ISO-8601)",
        "linha 2: data/hora 'ontem' ilegível (use dd/mm/aaaa hh:mm ou ISO-8601)",
        "linha 3: data/hora '25/11/26 08:30' ilegível (use dd/mm/aaaa hh:mm ou ISO-8601)",
    ]


def test_data_fora_do_intervalo_do_utc_e_ilegivel_nao_estoura():
    assert problemas("ENXOFRE;9999-12-31T23:59:59-05:00;1") == [
        "linha 1: data/hora '9999-12-31T23:59:59-05:00' ilegível (use dd/mm/aaaa hh:mm ou ISO-8601)"
    ]


def test_valor_nao_numerico_e_nan_sao_recusados():
    texto = (
        "nome;data;valor\n"
        "ENXOFRE;25/11/2026 08:30;abc\n"
        "ENXOFRE;25/11/2026 08:30;nan\n"
        "ENXOFRE;25/11/2026 08:30;inf\n"
        "ENXOFRE;25/11/2026 08:30;1.234,5\n"
        "ENXOFRE;25/11/2026 08:30;1_0\n"
        "ENXOFRE;25/11/2026 08:30;"
    )
    assert problemas(texto) == [
        "linha 2: valor 'abc' não é um número finito",
        "linha 3: valor 'nan' não é um número finito",
        "linha 4: valor 'inf' não é um número finito",
        "linha 5: valor '1.234,5' não é um número finito",
        "linha 6: valor '1_0' não é um número finito",
        "linha 7: valor '' não é um número finito",
    ]


def test_primeira_linha_com_valor_ilegivel_e_tratada_como_cabecalho():
    # Regra da spec §7.2 lida ao pé da letra: a linha 1 sem número na 3a coluna é descartada.
    assert p("ENXOFRE;25/11/2026 08:30;abc\nENXOFRE;25/11/2026 09:30;2") == [
        LabCsvRow(1, datetime(2026, 11, 25, 12, 30, tzinfo=UTC), 2.0)
    ]


def test_nan_na_primeira_linha_e_dado_nao_cabecalho():
    # "nan" é número para float(); só texto que não vira número faz a linha 1 ser cabeçalho.
    assert problemas("ENXOFRE;25/11/2026 08:30;nan") == [
        "linha 1: valor 'nan' não é um número finito"
    ]


def test_numero_de_colunas_errado():
    texto = "ENXOFRE;25/11/2026 08:30\nENXOFRE;25/11/2026 08:30;1;extra\nENXOFRE;25/11/2026 08:30;1"
    assert problemas(texto) == [
        "linha 1: esperadas 3 colunas, encontradas 2",
        "linha 2: esperadas 3 colunas, encontradas 4",
    ]


def test_fuso_invalido():
    assert problemas(
        "ENXOFRE;25/11/2026 08:30;1\nENXOFRE;25/11/2026 09:30;1", tz="Marte/Olympus"
    ) == ["linha 1: fuso horário 'Marte/Olympus' inválido"]
    # fuso mal formado (caminho) não escapa como exceção estranha
    assert problemas("ENXOFRE;25/11/2026 08:30;1", tz="../etc/passwd")[0].startswith(
        "linha 1: fuso"
    )


def test_fuso_invalido_so_importa_quando_a_data_nao_traz_offset():
    [r] = p("ENXOFRE;2026-11-25T08:30:00Z;1", tz="Marte/Olympus")
    assert r.sampled_at == datetime(2026, 11, 25, 8, 30, tzinfo=UTC)


def test_lista_no_maximo_50_problemas():
    ruim = "\n".join("OUTRA;25/11/2026 08:30;1" for _ in range(60))
    msgs = problemas(ruim)
    assert len(msgs) == 50
    assert msgs[0].startswith("linha 1:")
    assert msgs[-1].startswith("linha 50:")


def test_numero_da_linha_e_fisico_com_vazias_e_campo_multilinha():
    texto = (
        "nome;data;valor\n\n\n"  # cabeçalho na linha 1, vazias nas linhas 2 e 3
        "OUTRA;25/11/2026 08:30;1\n"  # linha 4
        '"a\nb";25/11/2026 08:30;1\n'  # registro nas linhas 5-6
        "OUTRA;25/11/2026 08:30;1"  # linha 7
    )
    assert [m.split(":")[0] for m in problemas(texto)] == ["linha 4", "linha 5", "linha 7"]


def test_linha_so_de_separadores_do_excel_e_vazia():
    assert p("ENXOFRE;25/11/2026 08:30;1\n;;\n  ;  ;  \n") == [LabCsvRow(1, SP_08_30, 1.0)]


def test_campo_gigante_e_recusado_como_csv_malformado():
    assert problemas("ENXOFRE;25/11/2026 08:30;" + "9" * 200_000) == ["linha 1: CSV malformado"]


def test_arquivo_vazio_devolve_lista_vazia():
    assert p("") == []
    assert p("\r\n\r\n") == []
    assert p("\ufeff") == []  # só BOM
    assert p('"nome do TAG";"data/hora";"valor"') == []  # só cabeçalho


def test_so_a_primeira_linha_nao_vazia_pode_ser_cabecalho():
    assert problemas("ENXOFRE;25/11/2026 08:30;1\nnome;data;valor") == [
        "linha 2: variável de laboratório 'nome' não existe no projeto ativo"
    ]


def test_nao_utf8_e_recusado_com_a_linha_do_byte_ruim():
    bruto = b"ENXOFRE;25/11/2026 08:30;1\nENXOFRE;25/11/2026 09:30;\xff\n"
    with pytest.raises(LabCsvError) as e:
        parse_lab_csv(bruto, tz="America/Sao_Paulo", known=CONHECIDAS, now=AGORA)
    assert e.value.problems == ["linha 2: arquivo não está em UTF-8"]


def test_lab_csv_error_e_value_error():
    assert issubclass(LabCsvError, ValueError)
    assert str(LabCsvError(["linha 1: x", "linha 2: y"])) == "linha 1: x; linha 2: y"
