"""Mesa de casos dos blocos de compensação dinâmica no `graph_json` (lead_lag, dead_time).

Arquivo próprio pelo mesmo motivo de `test_flowgraph_filtros.py`/`test_flowgraph_utilitarios.py`:
o grafo de referência de `test_flowgraph.py` não tem estes blocos, e cada mutação deles é um
caso de outra regra.
"""

import pytest

from ottima_core.flowgraph import (
    DeadTimeConfig,
    GraphParseError,
    LeadLagConfig,
    TagRef,
    parse_graph,
    validate_graph,
)

POS = {"x": 0, "y": 0}
TS = 1.0


def _node(node_id: str, tipo: str, exec_order: int, **data: object) -> dict:
    return {
        "id": node_id,
        "type": tipo,
        "position": POS,
        "data": {"exec_order": exec_order, "label": "", **data},
    }


def _leitura(node_id: str = "r1", exec_order: int = 1, tag_id: int = 10) -> dict:
    return _node(node_id, "opc_read", exec_order, tag_id=tag_id)


def _lead_lag(node_id: str = "c1", *, exec_order: int = 2, **config: object) -> dict:
    base: dict[str, object] = {"gain": 1.0, "tau_lead": 20.0, "tau_lag": 10.0}
    return _node(node_id, "lead_lag", exec_order, **(base | config))


def _dead_time(node_id: str = "d1", *, exec_order: int = 2, **config: object) -> dict:
    base: dict[str, object] = {"theta": 30.0}
    return _node(node_id, "dead_time", exec_order, **(base | config))


def _aresta(source: str, target: str, alvo: str = "in") -> dict:
    return {
        "id": f"e-{source}-{target}",
        "source": source,
        "target": target,
        "sourceHandle": "out",
        "targetHandle": alvo,
    }


def _graph(*nodes: dict, edges: list[dict] | None = None) -> dict:
    return {"nodes": list(nodes), "edges": edges or []}


def _ligado(bloco: dict) -> dict:
    """Entrada `in` é obrigatória nos dois blocos: o caso válido a liga."""
    return _graph(_leitura(), bloco, edges=[_aresta("r1", bloco["id"])])


def parse_errors(graph: dict) -> list[str]:
    with pytest.raises(GraphParseError) as exc:
        parse_graph(graph)
    return exc.value.errors


def has(errors: list[str], *trechos: str) -> bool:
    return any(all(trecho in erro for trecho in trechos) for erro in errors)


# --------------------------------------------------------------------------------------
# lead_lag — config
# --------------------------------------------------------------------------------------


def test_lead_lag_parseia_com_config_tipada():
    node = parse_graph(_ligado(_lead_lag())).node("c1")

    assert isinstance(node.config, LeadLagConfig)
    assert node.config.gain == 1.0
    assert node.config.tau_lead == 20.0
    assert node.config.tau_lag == 10.0


@pytest.mark.parametrize("gain", [-3.0, 0.0, 2.5])
def test_lead_lag_aceita_ganho_de_qualquer_sinal(gain: float):
    """Feedforward negativo é rotineiro: distúrbio que sobe a CV pede correção para baixo.
    `gain = 0` desliga o feedforward sem apagar o bloco (comissionamento) — não é config
    ausente."""
    node = parse_graph(_ligado(_lead_lag(gain=gain))).node("c1")

    assert node.config.gain == gain


def test_lead_lag_aceita_tau_lead_zero():
    """`tau_lead = 0` é lag puro — constante legítima, não erro."""
    assert parse_graph(_ligado(_lead_lag(tau_lead=0.0))).node("c1").config.tau_lead == 0.0


def test_lead_lag_aceita_a_razao_no_teto_exato():
    """O teto é inclusivo: r = 10 salva. Quem configurar exatamente 10 não pode levar 422."""
    node = parse_graph(_ligado(_lead_lag(tau_lead=100.0, tau_lag=10.0))).node("c1")

    assert node.config.tau_lead / node.config.tau_lag == 10.0


def test_lead_lag_reprova_razao_acima_do_teto():
    """`r` é o realce de alta frequência relativo ao ganho DC; o ganho de alta frequência do
    bloco é `gain*r`. Ligada a `bias_in`, essa amplificação chega à válvula sem atenuação
    integral (ADR-039 D10 soma depois do integrador)."""
    erros = parse_errors(_ligado(_lead_lag(tau_lead=101.0, tau_lag=10.0)))

    assert has(erros, "tau_lead/tau_lag")


@pytest.mark.parametrize("tau_lag", [0.0, -1.0])
def test_lead_lag_reprova_tau_lag_nao_positivo(tau_lag: float):
    """`tau_lag` é divisor na razão e na discretização: zero é imprópria, não passagem
    direta (a convenção do ADR-026 para `tau` não vale aqui)."""
    assert has(parse_errors(_ligado(_lead_lag(tau_lag=tau_lag))), "tau_lag")


def test_lead_lag_reprova_tau_lead_negativo():
    assert has(parse_errors(_ligado(_lead_lag(tau_lead=-1.0))), "tau_lead")


@pytest.mark.parametrize("campo", ["gain", "tau_lead", "tau_lag"])
@pytest.mark.parametrize("valor", [float("inf"), float("nan"), "5", None, True])
def test_lead_lag_reprova_valor_invalido(campo: str, valor: object):
    assert has(parse_errors(_ligado(_lead_lag(**{campo: valor}))), campo)


def test_lead_lag_reprova_chave_desconhecida():
    assert has(parse_errors(_ligado(_lead_lag(tau=1.0))), "tau")


def test_lead_lag_reprova_campo_ausente():
    graph = _graph(_leitura(), _node("c1", "lead_lag", 2, gain=1.0, tau_lead=5.0))
    assert has(parse_errors(graph), "tau_lag")


# --------------------------------------------------------------------------------------
# dead_time — config
# --------------------------------------------------------------------------------------


def test_dead_time_parseia_com_config_tipada():
    node = parse_graph(_ligado(_dead_time())).node("d1")

    assert isinstance(node.config, DeadTimeConfig)
    assert node.config.theta == 30.0


def test_dead_time_aceita_theta_zero():
    """`theta = 0` é passagem direta — constante legítima."""
    assert parse_graph(_ligado(_dead_time(theta=0.0))).node("d1").config.theta == 0.0


@pytest.mark.parametrize("valor", [-1.0, float("inf"), float("nan"), "30", None, True])
def test_dead_time_reprova_theta_invalido(valor: object):
    assert has(parse_errors(_ligado(_dead_time(theta=valor))), "theta")


def test_dead_time_reprova_chave_desconhecida():
    """A chave é `theta`, o mesmo termo dos modelos SOPDT/IOPDT (GLOSSARY) — `dead_time`
    seria sinônimo inventado para um termo que a casa já fixou."""
    assert has(parse_errors(_ligado(_dead_time(dead_time=30.0))), "dead_time")


def test_contrato_exportado_carrega_portas_e_schema_dos_dois_blocos():
    """`_NODE_CONFIG_MODELS` é fácil de esquecer e o gate do CI NÃO pega o esquecimento:
    sem a classe na tupla não há schema, logo o arquivo gerado não muda, logo
    `git diff --exit-code` passa VERDE com o contrato incompleto — e o frontend volta a
    tipar `DadosLeadLag` à mão, quebrando o espelho do ADR-034 em silêncio."""
    from ottima_core.contracts_export import build_contracts

    contratos = build_contracts()

    for tipo in ("lead_lag", "dead_time"):
        portas = contratos["port_contracts"][tipo]
        assert portas["dynamic"] is False
        assert [p["name"] for p in portas["ports"]] == ["in", "out"]
        assert all(p["type"] == "num" for p in portas["ports"])

    assert "LeadLagConfig" in contratos["node_configs"]
    assert "DeadTimeConfig" in contratos["node_configs"]


# --------------------------------------------------------------------------------------
# Portas no grafo validado
# --------------------------------------------------------------------------------------


def _tags(data_type: str = "float") -> dict[int, TagRef]:
    return {10: TagRef(id=10, conn_id=1, name="TT101", data_type=data_type, direction="r")}


@pytest.mark.parametrize("bloco", [_lead_lag, _dead_time])
def test_grafo_valido_nao_tem_erro(bloco):
    resultado = validate_graph(parse_graph(_ligado(bloco())), _tags(), TS)

    assert resultado.errors == []


@pytest.mark.parametrize("bloco", [_lead_lag, _dead_time])
def test_entrada_obrigatoria(bloco):
    """RF-302: `in` desligada é erro de validação, como nos filtros."""
    no = bloco()
    resultado = validate_graph(parse_graph(_graph(_leitura(), no)), _tags(), TS)

    assert any(no["id"] in erro for erro in resultado.errors)


@pytest.mark.parametrize("bloco", [_lead_lag, _dead_time])
def test_recusa_entrada_booleana(bloco):
    """Portas dos dois blocos são numéricas: tag `bool` na entrada não passa no save."""
    resultado = validate_graph(parse_graph(_ligado(bloco())), _tags("bool"), TS)

    assert resultado.errors


# --------------------------------------------------------------------------------------
# dead_time — teto da fila (depende do Ts, por isso vive no validate)
# --------------------------------------------------------------------------------------


def test_dead_time_reprova_fila_acima_do_teto():
    """Mesmo teto e mesma constante do TFS (`MAX_DELAY_SAMPLES`): 7201 amostras não passam."""
    resultado = validate_graph(parse_graph(_ligado(_dead_time(theta=7201.0))), _tags(), TS)

    assert any("7201" in erro and "7200" in erro for erro in resultado.errors)


def test_dead_time_aceita_a_fila_no_teto_exato():
    resultado = validate_graph(parse_graph(_ligado(_dead_time(theta=7200.0))), _tags(), TS)

    assert resultado.errors == []


def test_dead_time_conta_amostras_e_nao_segundos():
    """O teto é em AMOSTRAS: com Ts = 2 s, 7201 s cabe (3601 amostras)."""
    resultado = validate_graph(parse_graph(_ligado(_dead_time(theta=7201.0))), _tags(), 2.0)

    assert resultado.errors == []
