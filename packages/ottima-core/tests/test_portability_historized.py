"""Testes de variável historiada (RF-308, ADR-041) em `ottima_core.portability` — a linha
de `tags` correspondente nunca entra em `ProjectBundle.tags` (D1), a montagem do bundle
sobrevive ao round-trip (D6) e a camada 3 do import acusa flow/bloco inexistente, porta
duplicada e colisão de nome antes de qualquer insert.

Todos puros: `Project`/`Tag`/`Flow`/`HistorizedVar` aqui são instâncias Python soltas,
nunca persistidas — nenhuma dependência de banco/Redis/disco (mesmo molde de
`test_bundle.py`, que cobre o restante do bundle e não é tocado aqui).
"""

from datetime import UTC, datetime

from ottima_core.models import Flow, HistorizedVar, Project, Tag
from ottima_core.portability.bundle import montar_bundle, problemas_de_coerencia_interna
from ottima_core.portability.schemas import (
    BundleConnection,
    BundleFlow,
    BundleHistorizedVar,
    BundleProject,
    BundleTag,
    ProjectBundle,
)

EXPORTED_AT = datetime(2026, 8, 7, 21, 40, tzinfo=UTC)


def _projeto(**over: object) -> Project:
    dados: dict[str, object] = {
        "id": 10,
        "name": "Planta C-101",
        "description": "Coluna debutanizadora",
        "is_active": False,
    }
    dados.update(over)
    return Project(**dados)


def _flow(**over: object) -> Flow:
    dados: dict[str, object] = {
        "id": 100,
        "project_id": 10,
        "name": "Coluna C-101",
        "ts_seconds": 1.0,
        "desired_state": "stopped",
        "graph_json": {"nodes": [{"id": "pid1"}, {"id": "script1"}], "edges": []},
        "watchdog_enabled": False,
        "watchdog_connection_id": None,
        "watchdog_read_node_id": None,
        "watchdog_write_node_id": None,
        "watchdog_period_ms": 1500,
        "watchdog_timeout_s": 10,
    }
    dados.update(over)
    return Flow(**dados)


def _tag_historiada(**over: object) -> Tag:
    """Mesma forma da tag calculada (`ck_tags_owner`), sem as três colunas de
    `CalculatedTag` — é a linha que `HistorizedVar.tag_id` referencia (ADR-041 D1)."""
    dados: dict[str, object] = {
        "id": 701,
        "connection_id": None,
        "project_id": 10,
        "name": "Coluna C-101.pid1.saida",
        "node_id": None,
        "direction": "r",
        "data_type": "float",
        "eu": "%",
        "description": "",
    }
    dados.update(over)
    return Tag(**dados)


def _historized_var(**over: object) -> HistorizedVar:
    dados: dict[str, object] = {
        "tag_id": 701,
        "flow_id": 100,
        "block_id": "pid1",
        "port": "saida",
    }
    dados.update(over)
    return HistorizedVar(**dados)


class TestMontarBundleHistorizedVars:
    def test_variaveis_historiadas_sobrevivem_ao_round_trip_e_nao_entram_em_tags(self) -> None:
        flow = _flow()
        tag_saida = _tag_historiada(id=701, name="Coluna C-101.pid1.saida", eu="%")
        tag_entrada = _tag_historiada(id=702, name="Coluna C-101.script1.entrada", eu="C")
        hv_saida = _historized_var(tag_id=701, flow_id=100, block_id="pid1", port="saida")
        hv_entrada = _historized_var(tag_id=702, flow_id=100, block_id="script1", port="entrada")

        bundle = montar_bundle(
            project=_projeto(),
            connections=[],
            tags=[tag_saida, tag_entrada],
            flows=[flow],
            exported_at=EXPORTED_AT,
            historized_vars=[hv_saida, hv_entrada],
        )

        # Ponto central de D6: a linha de `tags` da variável historiada cairia fora do XOR
        # de `BundleTag._coerencia` (não é OPC nem tem os três campos de tag calculada) —
        # `montar_bundle` tem de filtrá-la, nunca deixar isso só por conta do chamador.
        assert bundle.tags == []
        assert bundle.historized_vars == [
            BundleHistorizedVar(
                tag="Coluna C-101.pid1.saida",
                eu="%",
                flow="Coluna C-101",
                block_id="pid1",
                port="saida",
            ),
            BundleHistorizedVar(
                tag="Coluna C-101.script1.entrada",
                eu="C",
                flow="Coluna C-101",
                block_id="script1",
                port="entrada",
            ),
        ]

        # Round-trip: serializa (o que `export_project` devolve) e desserializa (o que
        # `import_project` recebe) — mesmo par de operações do arquivo real.
        reconstruido = ProjectBundle.model_validate(bundle.model_dump(mode="json"))
        assert reconstruido == bundle
        assert problemas_de_coerencia_interna(reconstruido) == []

    def test_sem_variaveis_historiadas_a_lista_fica_vazia(self) -> None:
        bundle = montar_bundle(
            project=_projeto(),
            connections=[],
            tags=[],
            flows=[],
            exported_at=EXPORTED_AT,
        )
        assert bundle.historized_vars == []


def _bundle_minimo(**over: object) -> ProjectBundle:
    dados: dict[str, object] = {
        "schema_version": 1,
        "exported_at": EXPORTED_AT,
        "project": BundleProject(name="Planta C-101"),
        "connections": [],
        "tags": [],
        "flows": [],
        "historized_vars": [],
    }
    dados.update(over)
    return ProjectBundle(**dados)


_FLOW_COM_PID1 = BundleFlow(
    name="Coluna C-101", ts_seconds=1.0, graph={"nodes": [{"id": "pid1"}], "edges": []}
)


class TestProblemasDeCoerenciaInternaHistorizedVars:
    def test_variavel_historiada_valida_nao_tem_problemas(self) -> None:
        bundle = _bundle_minimo(
            flows=[_FLOW_COM_PID1],
            historized_vars=[
                BundleHistorizedVar(
                    tag="Coluna C-101.pid1.pv", flow="Coluna C-101", block_id="pid1", port="pv"
                )
            ],
        )
        assert problemas_de_coerencia_interna(bundle) == []

    def test_flow_inexistente_e_problema(self) -> None:
        bundle = _bundle_minimo(
            historized_vars=[
                BundleHistorizedVar(tag="X", flow="Flow Fantasma", block_id="pid1", port="pv")
            ]
        )
        problemas = problemas_de_coerencia_interna(bundle)
        assert any("Flow Fantasma" in p and "não existe" in p for p in problemas)

    def test_block_id_inexistente_no_grafo_do_flow_e_problema(self) -> None:
        bundle = _bundle_minimo(
            flows=[_FLOW_COM_PID1],
            historized_vars=[
                BundleHistorizedVar(
                    tag="X", flow="Coluna C-101", block_id="bloco-fantasma", port="pv"
                )
            ],
        )
        problemas = problemas_de_coerencia_interna(bundle)
        assert any("bloco-fantasma" in p and "não existe" in p for p in problemas)

    def test_porta_repetida_no_bundle_e_problema(self) -> None:
        bundle = _bundle_minimo(
            flows=[_FLOW_COM_PID1],
            historized_vars=[
                BundleHistorizedVar(tag="X1", flow="Coluna C-101", block_id="pid1", port="pv"),
                BundleHistorizedVar(tag="X2", flow="Coluna C-101", block_id="pid1", port="pv"),
            ],
        )
        problemas = problemas_de_coerencia_interna(bundle)
        assert any("pid1" in p and "pv" in p and "duas vezes" in p for p in problemas)

    def test_tag_colide_com_tag_opc_existente_e_problema(self) -> None:
        bundle = _bundle_minimo(
            connections=[BundleConnection(name="gateway-1", endpoint="opc.tcp://a")],
            tags=[
                BundleTag(
                    connection="gateway-1",
                    name="TT-101",
                    node_id="ns=2;s=TT101",
                    direction="r",
                    data_type="float",
                )
            ],
            flows=[_FLOW_COM_PID1],
            historized_vars=[
                BundleHistorizedVar(tag="TT-101", flow="Coluna C-101", block_id="pid1", port="pv")
            ],
        )
        problemas = problemas_de_coerencia_interna(bundle)
        assert any("TT-101" in p and "colide" in p for p in problemas)

    def test_duas_variaveis_historiadas_com_o_mesmo_nome_de_tag_e_problema(self) -> None:
        flow = BundleFlow(
            name="Coluna C-101",
            ts_seconds=1.0,
            graph={"nodes": [{"id": "pid1"}, {"id": "pid2"}], "edges": []},
        )
        bundle = _bundle_minimo(
            flows=[flow],
            historized_vars=[
                BundleHistorizedVar(
                    tag="Coluna C-101.pid1.pv", flow="Coluna C-101", block_id="pid1", port="pv"
                ),
                BundleHistorizedVar(
                    tag="Coluna C-101.pid1.pv", flow="Coluna C-101", block_id="pid2", port="pv"
                ),
            ],
        )
        problemas = problemas_de_coerencia_interna(bundle)
        assert any("Coluna C-101.pid1.pv" in p and "colide" in p for p in problemas)


class TestProjectBundleFormatoAntigoSemHistorizedVars:
    def test_bundle_sem_o_campo_historized_vars_continua_valido(self) -> None:
        # Formato exportado antes do ADR-041: campo aditivo e opcional, `schema_version`
        # continua 1 (mesmo precedente de `exec_order`/`feedback_init`, ADR-024/ADR-040).
        bruto = {
            "schema_version": 1,
            "exported_at": EXPORTED_AT.isoformat(),
            "project": {"name": "Planta C-101", "description": ""},
            "connections": [],
            "tags": [],
            "flows": [],
        }
        bundle = ProjectBundle.model_validate(bruto)
        assert bundle.historized_vars == []
        assert problemas_de_coerencia_interna(bundle) == []
