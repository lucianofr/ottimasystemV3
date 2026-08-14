"""L2 do bloco Fuzzy (ADR-029, RF-541..543) — feature nova, sem cenário próprio ainda.

Cenário E2E-FZ-01: `opc_read -> fuzzy` deployado contra o stack real, com o FLL padrão do
contrato (`FUZZY_DEFAULT_FLL`, importado de `ottima_core.contracts_export` — nunca duplicado
aqui) e `n_inputs=1`/`n_outputs=4`. Os termos `Bell` da entrada do FLL padrão têm pertinência
global (nunca exatamente zero para nenhum valor finito), então a ponderação `WeightedAverage`
das 4 saídas nunca zera o denominador: com entrada finita, as 4 saídas ficam sempre finitas e
`ok=True` (RF-542). As saídas do bloco ficam desconectadas de propósito — como as MVs do MPC
(spec F4 §2.1-5), saída de bloco dinâmico nunca é entrada obrigatória (RF-302).

Cenário E2E-FZ-02 (mesmo arquivo, sem subir flow nenhum — o cenário barato do gênero): `PUT`
com FLL sintaticamente inválido é reprovado com 422, o comportamento novo de `validate_graph`
(RF-541, `FllImporter` na camada de conteúdo, `parse.py:164-168`).
"""

import math
from typing import Any

import httpx
import pytest

from ottima_core.contracts_export import FUZZY_DEFAULT_FLL

from .conftest import Ambiente
from .f3_support import (
    aresta,
    assinantes_de_status,
    bloco,
    de_varredura,
    deploy,
    fabrica_de_flows,
    montar_grafo,
    porta,
    reprovar,
)

pytestmark = pytest.mark.e2e


@pytest.fixture
def assinar_status(redis_bus: Any) -> Any:
    yield from assinantes_de_status(redis_bus)


@pytest.fixture
def criar_flow(admin: httpx.Client, projeto_com_conexao: Ambiente) -> Any:
    yield from fabrica_de_flows(admin, projeto_com_conexao)


def _grafo_fuzzy(ambiente: Ambiente, *, fll: str) -> dict:
    return montar_grafo(
        [
            bloco("leitura", "opc_read", 1, tag_id=ambiente.sine),
            bloco(
                "fuzzy",
                "fuzzy",
                2,
                fll=fll,
                n_inputs=1,
                n_outputs=4,
                output_eu={},
            ),
        ],
        [aresta("leitura", "out", "fuzzy", "IN1")],
    )


def test_e2e_fz_01_fuzzy_deployado_publica_4_saidas_finitas(
    admin: httpx.Client,
    projeto_com_conexao: Ambiente,
    criar_flow: Any,
    assinar_status: Any,
) -> None:
    """E2E-FZ-01: `opc_read -> fuzzy` (FLL padrão, 1 entrada/4 saídas) deployado contra o
    stack real publica OUT1..OUT4 sempre finitas e com `ok=True` — a senoide do opcsim é
    finita em toda amostra e os termos `Bell` do FLL padrão nunca zeram a ponderação."""
    ambiente = projeto_com_conexao
    flow_id = criar_flow("fz-01-fuzzy", grafo=_grafo_fuzzy(ambiente, fll=FUZZY_DEFAULT_FLL))
    status = assinar_status(flow_id)

    deploy(admin, flow_id)
    primeira = status.esperar(
        de_varredura, timeout=30.0, descricao="primeira varredura do flow com bloco fuzzy"
    )
    assert primeira["state"] == "running"

    # A 1ª varredura já foi consumida acima de propósito (mesmo padrão do E2E-TD-10): as
    # amostras seguintes observam o bloco em regime, não na partida do engine.
    amostras = status.coletar(
        quantidade=5, timeout=30.0, descricao="varreduras do bloco fuzzy após a partida"
    )
    for amostra in amostras:
        assert de_varredura(amostra), "amostra sem `ports` no meio da coleta"
        assert amostra["state"] == "running"
        for i in range(1, 5):
            saida = porta(amostra, "fuzzy", f"OUT{i}")
            assert saida["ok"] is True, f"OUT{i} com ok=False (entrada finita): {saida}"
            assert isinstance(saida["v"], float) and math.isfinite(saida["v"]), (
                f"OUT{i} não-finita com entrada finita (Bell tem pertinência global): {saida}"
            )
    print("\nE2E-FZ-01: bloco fuzzy deployado publicou OUT1..OUT4 finitas em toda a janela")


def test_e2e_fz_02_fll_invalido_reprovado_no_put(
    admin: httpx.Client,
    projeto_com_conexao: Ambiente,
    criar_flow: Any,
) -> None:
    """E2E-FZ-02: `PUT` com FLL sintaticamente inválido é reprovado com 422 (RF-541) — o erro
    do parser (`FllImporter`) traz "FLL inválido" (`validate.py::_valida_fuzzy`)."""
    ambiente = projeto_com_conexao
    flow_id = criar_flow("fz-02-fll-invalido")
    grafo_invalido = _grafo_fuzzy(ambiente, fll="isto não é FLL válido {{{\n")
    assert "FLL inválido" in reprovar(admin, flow_id, grafo_invalido)
