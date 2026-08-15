"""Nome das saídas do script é do chamador (ADR-018 para o bloco Script, ADR-033 para a tag
calculada). Pool real, um worker: o que se testa aqui é a resolução do nome, não o processo."""

import pytest

from ottima_core.script_pool import ScriptPool


@pytest.fixture
async def pool():
    pool = ScriptPool(size=1)
    await pool.start()
    yield pool
    await pool.stop()


async def test_output_names_explicito_le_a_saida_com_o_nome_pedido(pool):
    """Tag calculada atribui `OUT`, sem sufixo numérico — é o nome que o engenheiro escreve."""
    resultado = await pool.run(
        code="OUT = IN1 * 2.0\n",
        inputs={"IN1": 21.0},
        state=None,
        n_outputs=1,
        timeout_s=10.0,
        output_names=("OUT",),
    )
    assert resultado.status == "ok"
    assert resultado.outputs == {"OUT": 42.0}


async def test_sem_output_names_mantem_a_convencao_out1_outn(pool):
    """Ausência do parâmetro preserva o contrato do bloco Script — nenhum chamador dele muda."""
    resultado = await pool.run(
        code="OUT1 = 1.0\nOUT2 = 2.0\n",
        inputs={},
        state=None,
        n_outputs=2,
        timeout_s=10.0,
    )
    assert resultado.status == "ok"
    assert resultado.outputs == {"OUT1": 1.0, "OUT2": 2.0}


async def test_out1_nao_serve_quando_o_nome_pedido_e_out(pool):
    """`OUT1` num script de tag calculada é erro de escrita, não sinônimo: o pool acusa a saída
    que faltou em vez de publicar um valor que ninguém calculou."""
    resultado = await pool.run(
        code="OUT1 = 7.0\n",
        inputs={},
        state=None,
        n_outputs=1,
        timeout_s=10.0,
        output_names=("OUT",),
    )
    assert resultado.status == "error"
    assert resultado.detail is not None
    assert "OUT" in resultado.detail
