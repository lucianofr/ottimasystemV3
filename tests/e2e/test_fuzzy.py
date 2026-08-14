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

Cenário E2E-FZ-03: com o mesmo flow deployado, o canal `fuzzy.state.<flow_id>.<block_id>`
(ADR-030) publica o estado interno do motor — μ por termo de entrada, grau por regra e valor
defuzzificado por saída — respeitando o throttle de 0,25 s da origem.
"""

import math
import time
from typing import Any

import httpx
import pytest

from ottima_core.bus import channel_fuzzy_state
from ottima_core.contracts_export import FUZZY_DEFAULT_FLL

from .conftest import Ambiente
from .f3_support import (
    StatusStream,
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


@pytest.fixture
def assinar_fuzzy(redis_bus: Any) -> Any:
    """Assinatura de `fuzzy.state.<flow_id>.<block_id>` aberta ANTES do deploy — mesmo padrão
    de `assinantes_de_status`, reusando o `StatusStream` (o contrato dele é "stream de JSON do
    barramento", não `flow.status` em particular)."""
    pubsubs: list[Any] = []

    def assinar(flow_id: int, block_id: str) -> StatusStream:
        pubsub = redis_bus.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(channel_fuzzy_state(flow_id, block_id))
        pubsubs.append(pubsub)
        return StatusStream(pubsub)

    yield assinar
    for pubsub in pubsubs:
        pubsub.close()


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
    stack real infere de verdade e respeita o RF-542 em toda amostra.

    O contrato exigido é o do RF-542, não "toda saída sempre boa": `nan`/`inf` NUNCA escapam
    com `ok=True`. O FLL padrão de fato produz `nan` em pontos isolados — `Sigmoids`/OUT2
    zera o denominador do `WeightedAverage` quando a senoide passa exatamente por
    `X ∈ {0, ±10}` (verificado varrendo a faixa da senoide contra o próprio `FuzzyBlock`) —
    e o bloco então retém o último valor bom daquela porta com `ok=False`. Exigir `ok=True`
    em TODA amostra deixaria o cenário refém da fase da senoide no instante do deploy.
    """
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
    inferencias_completas = 0
    for amostra in amostras:
        assert de_varredura(amostra), "amostra sem `ports` no meio da coleta"
        assert amostra["state"] == "running"
        saidas = [porta(amostra, "fuzzy", f"OUT{i}") for i in range(1, 5)]
        for i, saida in enumerate(saidas, start=1):
            # RF-542: `ok=True` obriga valor finito; `ok=False` traz valor retido (finito ou
            # `None` antes do primeiro bom) — em nenhum caso um nan/inf sai como válido.
            if saida["ok"]:
                assert isinstance(saida["v"], float) and math.isfinite(saida["v"]), (
                    f"OUT{i} não-finita com ok=True — RF-542 violado: {saida}"
                )
            else:
                assert saida["v"] is None or math.isfinite(saida["v"]), (
                    f"OUT{i} com ok=False propagando não-finito: {saida}"
                )
        if all(saida["ok"] for saida in saidas):
            inferencias_completas += 1

    # Prova de que o motor está inferindo, não só retendo: a senoide só toca os pontos
    # degenerados em amostras isoladas, então a janela tem varredura com as 4 saídas boas.
    assert inferencias_completas > 0, (
        "nenhuma varredura com OUT1..OUT4 ok=True — o bloco não está inferindo"
    )
    print("\nE2E-FZ-01: bloco fuzzy deployado inferiu OUT1..OUT4 respeitando o RF-542")


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


def test_e2e_fz_03_canal_fuzzy_state_publica_estado_do_motor(
    admin: httpx.Client,
    projeto_com_conexao: Ambiente,
    criar_flow: Any,
    assinar_fuzzy: Any,
) -> None:
    """E2E-FZ-03: o canal `fuzzy.state.<flow_id>.<block_id>` (ADR-030) publica, por execução,
    a fuzzificação da entrada, o grau de cada regra e o valor defuzzificado de cada saída —
    tudo o que a página FUZZY OPERATE anima. O throttle de 0,25 s na origem é observável: 3
    quadros consecutivos levam pelo menos ~0,5 s, mesmo com Ts do flow menor que isso."""
    ambiente = projeto_com_conexao
    flow_id = criar_flow("fz-03-telemetria", grafo=_grafo_fuzzy(ambiente, fll=FUZZY_DEFAULT_FLL))
    estados = assinar_fuzzy(flow_id, "fuzzy")

    deploy(admin, flow_id)
    inicio = time.monotonic()
    quadros = estados.coletar(
        quantidade=3, timeout=30.0, descricao="quadros de fuzzy.state do bloco deployado"
    )
    decorrido = time.monotonic() - inicio

    for quadro in quadros:
        assert quadro["ok"] is True, f"entrada da senoide é finita, esperado ok=True: {quadro}"
        # Fuzzificação: 1 entrada (X) com os 3 termos Bell do FLL padrão, todos com μ > 0
        # (pertinência global do Bell) e valor crisp finito.
        assert [entrada["port"] for entrada in quadro["inputs"]] == ["IN1"]
        entrada = quadro["inputs"][0]
        assert entrada["name"] == "X"
        assert math.isfinite(entrada["v"])
        assert {termo["term"] for termo in entrada["terms"]} == {"small", "medium", "large"}
        assert all(termo["degree"] > 0.0 for termo in entrada["terms"]), entrada
        # Uma regra por termo da entrada, todas ativadas em algum grau finito.
        assert len(quadro["rules"]) == 3
        assert all(math.isfinite(grau) and grau > 0.0 for grau in quadro["rules"]), quadro
        # Defuzzificação: as 4 saídas do FLL padrão. `v=None` é legítimo e esperado nos
        # pontos degenerados do WeightedAverage (`X ∈ {0, ±10}`, mesma nota do E2E-FZ-01) —
        # o contrato é "nunca nan/inf no JSON", não "sempre um número".
        assert [saida["port"] for saida in quadro["outputs"]] == ["OUT1", "OUT2", "OUT3", "OUT4"]
        for saida in quadro["outputs"]:
            assert saida["v"] is None or math.isfinite(saida["v"]), saida
        assert any(saida["v"] is not None for saida in quadro["outputs"]), (
            f"nenhuma saída defuzzificada no quadro — o motor não inferiu: {quadro}"
        )

    assert decorrido >= 0.5, f"throttle de 0,25 s não observado: 3 quadros em {decorrido:.2f}s"
    print("\nE2E-FZ-03: fuzzy.state publicou fuzzificação, regras e defuzzificação com throttle")
