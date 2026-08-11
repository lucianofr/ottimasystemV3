"""Testes de `ottima_core.portability.bundle` — montagem do export e coerência
interna do import (spec F6 §2.1-7, §3.2-4 camada 3, decisão A-2, TST-01/04).

Todos puros: `Project`/`OpcConnection`/`Tag`/`Flow` aqui são instâncias Python soltas,
nunca persistidas — nenhuma dependência de banco/Redis/disco.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

from ottima_core.models import Flow, OpcConnection, Project, Tag
from ottima_core.portability.bundle import (
    montar_bundle,
    problemas_de_coerencia_interna,
    ref_por_id,
)
from ottima_core.portability.schemas import (
    BundleConnection,
    BundleFlow,
    BundleProject,
    BundleTag,
    ProjectBundle,
)
from ottima_core.portability.tag_ref import grafo_para_banco

EXPORTED_AT = datetime(2026, 8, 7, 21, 40, tzinfo=UTC)


def _conexao(**over: object) -> OpcConnection:
    dados: dict[str, object] = {
        "id": 1,
        "project_id": 10,
        "name": "gateway-1",
        "endpoint": "opc.tcp://10.0.0.5:4840",
        "security_policy": "none",
        "security_mode": "none",
        "auth_mode": "anonymous",
        "auth_username": None,
        "auth_password_enc": None,
        "server_cert_file": None,
    }
    dados.update(over)
    return OpcConnection(**dados)


def _tag(**over: object) -> Tag:
    dados: dict[str, object] = {
        "id": 501,
        "connection_id": 1,
        "name": "TT-101",
        "node_id": "ns=2;s=TT101",
        "direction": "r",
        "data_type": "float",
        "eu": "C",
        "description": "",
    }
    dados.update(over)
    return Tag(**dados)


def _flow(**over: object) -> Flow:
    dados: dict[str, object] = {
        "id": 100,
        "project_id": 10,
        "name": "Coluna C-101",
        "ts_seconds": 1.0,
        "desired_state": "stopped",
        "graph_json": {"nodes": [], "edges": []},
        "watchdog_enabled": False,
        "watchdog_connection_id": None,
        "watchdog_read_node_id": None,
        "watchdog_write_node_id": None,
        "watchdog_period_ms": 1500,
    }
    dados.update(over)
    return Flow(**dados)


def _projeto(**over: object) -> Project:
    dados: dict[str, object] = {
        "id": 10,
        "name": "Planta C-101",
        "description": "Coluna debutanizadora",
        "is_active": False,
    }
    dados.update(over)
    return Project(**dados)


class TestRefPorId:
    def test_monta_dicionario_tag_id_para_connection_e_tag(self) -> None:
        gw1 = _conexao(id=1, name="gateway-1")
        gw2 = _conexao(id=2, name="gateway-2")
        t1 = _tag(id=501, connection_id=1, name="TT-101")
        t2 = _tag(id=502, connection_id=2, name="TT-101")
        assert ref_por_id([gw1, gw2], [t1, t2]) == {
            501: ("gateway-1", "TT-101"),
            502: ("gateway-2", "TT-101"),
        }


class TestMontarBundle:
    def test_ordena_conexoes_e_flows_por_name_e_tags_por_connection_e_name(self) -> None:
        gw_zulu = _conexao(id=1, name="zulu")
        gw_alpha = _conexao(id=2, name="alpha")
        tag_zulu = _tag(id=501, connection_id=1, name="zzz")
        tag_alpha = _tag(id=502, connection_id=2, name="aaa")
        flow_zulu = _flow(id=100, name="zzz-flow")
        flow_alpha = _flow(id=101, name="aaa-flow")

        bundle = montar_bundle(
            project=_projeto(),
            connections=[gw_zulu, gw_alpha],
            tags=[tag_zulu, tag_alpha],
            flows=[flow_zulu, flow_alpha],
            exported_at=EXPORTED_AT,
        )

        assert [c.name for c in bundle.connections] == ["alpha", "zulu"]
        assert [f.name for f in bundle.flows] == ["aaa-flow", "zzz-flow"]
        # tag_zulu está na conexão "zulu"; tag_alpha está na conexão "alpha" — ordenar
        # por (connection, name) põe "alpha"/"aaa" antes de "zulu"/"zzz".
        assert [(t.connection, t.name) for t in bundle.tags] == [
            ("alpha", "aaa"),
            ("zulu", "zzz"),
        ]

    def test_conexao_projetada_sem_segredos_e_com_os_campos_do_bundle(self) -> None:
        conexao = _conexao(
            id=1,
            name="gateway-1",
            endpoint="opc.tcp://10.0.0.5:4840",
            security_policy="basic256sha256",
            security_mode="sign_and_encrypt",
            auth_mode="user_password",
            auth_username="ottima",
            auth_password_enc="cifrado-nao-deve-aparecer",
            server_cert_file="certs/gateway-1.pem",
        )

        bundle = montar_bundle(
            project=_projeto(), connections=[conexao], tags=[], flows=[], exported_at=EXPORTED_AT
        )

        assert bundle.connections[0] == BundleConnection(
            name="gateway-1",
            endpoint="opc.tcp://10.0.0.5:4840",
            security_policy="basic256sha256",
            security_mode="sign_and_encrypt",
            auth_mode="user_password",
            auth_username="ottima",
        )
        assert not hasattr(bundle.connections[0], "auth_password_enc")
        assert not hasattr(bundle.connections[0], "server_cert_file")

    def test_exported_at_do_argumento_vai_para_o_bundle(self) -> None:
        bundle = montar_bundle(
            project=_projeto(), connections=[], tags=[], flows=[], exported_at=EXPORTED_AT
        )
        assert bundle.exported_at == EXPORTED_AT

    def test_flow_projetado_com_campos_de_watchdog(self) -> None:
        conexao = _conexao(id=1, name="gateway-1")
        flow = _flow(
            watchdog_enabled=True,
            watchdog_connection_id=1,
            watchdog_read_node_id="ns=2;s=WD_R",
            watchdog_write_node_id="ns=2;s=WD_W",
            watchdog_period_ms=2000,
        )

        bundle = montar_bundle(
            project=_projeto(),
            connections=[conexao],
            tags=[],
            flows=[flow],
            exported_at=EXPORTED_AT,
        )

        assert bundle.flows[0].watchdog_enabled is True
        assert bundle.flows[0].watchdog_connection == "gateway-1"
        assert bundle.flows[0].watchdog_read_node_id == "ns=2;s=WD_R"
        assert bundle.flows[0].watchdog_write_node_id == "ns=2;s=WD_W"
        assert bundle.flows[0].watchdog_period_ms == 2000


class TestRoundTripPorConexao:
    """TST-01: tag homônima em duas conexões — a referência por objeto (nunca a
    string "conexao/tag") garante que reimportar numa instalação nova, com ids
    diferentes dos originais, resolve para a tag da conexão certa (spec §2.2-2)."""

    def test_tag_homonima_em_duas_conexoes_resolve_para_a_conexao_certa_apos_reimport(
        self,
    ) -> None:
        gw1 = _conexao(id=1, name="gateway-1")
        gw2 = _conexao(id=2, name="gateway-2")
        # uq_tags_connection_name é por conexão: "TT-101" nas duas é legítimo.
        tag_gw1 = _tag(id=501, connection_id=1, name="TT-101", node_id="ns=2;s=TT101a")
        tag_gw2 = _tag(id=502, connection_id=2, name="TT-101", node_id="ns=2;s=TT101b")
        flow = _flow(
            graph_json={
                "nodes": [
                    {
                        "id": "r-gw1",
                        "type": "opc_read",
                        "position": {"x": 0.0, "y": 0.0},
                        "data": {"exec_order": 1, "label": "Leitura gw1", "tag_id": 501},
                    },
                    {
                        "id": "w-gw2",
                        "type": "opc_write",
                        "position": {"x": 100.0, "y": 0.0},
                        "data": {"exec_order": 2, "label": "Escrita gw2", "tag_id": 502},
                    },
                ],
                "edges": [],
            }
        )

        bundle = montar_bundle(
            project=_projeto(),
            connections=[gw1, gw2],
            tags=[tag_gw1, tag_gw2],
            flows=[flow],
            exported_at=EXPORTED_AT,
        )

        grafo = bundle.flows[0].graph
        no_r = next(n for n in grafo["nodes"] if n["id"] == "r-gw1")
        no_w = next(n for n in grafo["nodes"] if n["id"] == "w-gw2")
        assert no_r["data"]["tag_ref"] == {"connection": "gateway-1", "tag": "TT-101"}
        assert no_w["data"]["tag_ref"] == {"connection": "gateway-2", "tag": "TT-101"}

        # "De volta a models" numa instalação nova: tags recriadas com ids diferentes
        # dos originais (501/502) e em ORDEM INVERTIDA (gateway-2 ganha o id menor
        # desta vez) — prova que a resolução é por nome, não por coincidência de
        # ordenação/alocação de id.
        id_por_ref = {
            ("gateway-1", "TT-101"): 902,
            ("gateway-2", "TT-101"): 901,
        }
        grafo_reimportado = grafo_para_banco(grafo, id_por_ref)
        no_r2 = next(n for n in grafo_reimportado["nodes"] if n["id"] == "r-gw1")
        no_w2 = next(n for n in grafo_reimportado["nodes"] if n["id"] == "w-gw2")
        assert no_r2["data"]["tag_id"] == 902
        assert no_w2["data"]["tag_id"] == 901
        assert no_r2["data"]["tag_id"] != no_w2["data"]["tag_id"]


_CAMPOS_PROIBIDOS = frozenset(
    {
        "auth_password",
        "auth_password_enc",
        "server_cert_file",
        "id",
        "project_id",
        "connection_id",
        "is_active",
        "created_at",
        "updated_at",
    }
)


def _chaves_proibidas(valor: object, *, dentro_do_grafo: bool = False) -> Iterator[str]:
    """Varre `valor` recursivamente à procura de chave fora da fronteira do bundle
    (spec §2.3). `id` só é permitido dentro de `flows[].graph`: ali é o identificador
    do nó do React Flow (string) — nunca uma PK. Os outros campos continuam proibidos
    em qualquer profundidade, inclusive dentro do grafo."""
    if isinstance(valor, dict):
        for chave, sub in valor.items():
            if chave in _CAMPOS_PROIBIDOS and not (chave == "id" and dentro_do_grafo):
                yield chave
            yield from _chaves_proibidas(sub, dentro_do_grafo=dentro_do_grafo or chave == "graph")
    elif isinstance(valor, list):
        for item in valor:
            yield from _chaves_proibidas(item, dentro_do_grafo=dentro_do_grafo)


class TestBundleSemSegredosESemIds:
    def test_varredura_recursiva_nao_encontra_campo_fora_da_fronteira(self) -> None:
        conexao = _conexao(
            id=7,
            name="gateway-1",
            auth_password_enc="cifrado",
            server_cert_file="certs/gateway-1.pem",
        )
        tag = _tag(id=501, connection_id=7, name="TT-101")
        flow = _flow(
            id=55,
            graph_json={
                "nodes": [
                    {
                        "id": "r1",
                        "type": "opc_read",
                        "position": {"x": 0.0, "y": 0.0},
                        "data": {"exec_order": 1, "label": "Leitura", "tag_id": 501},
                    }
                ],
                "edges": [],
            },
        )

        bundle = montar_bundle(
            project=_projeto(id=10, is_active=True),
            connections=[conexao],
            tags=[tag],
            flows=[flow],
            exported_at=EXPORTED_AT,
        )

        achados = list(_chaves_proibidas(bundle.model_dump(mode="json")))
        assert achados == []


def _bundle_minimo(**over: object) -> ProjectBundle:
    dados: dict[str, object] = {
        "schema_version": 1,
        "exported_at": EXPORTED_AT,
        "project": BundleProject(name="Planta C-101"),
        "connections": [],
        "tags": [],
        "flows": [],
    }
    dados.update(over)
    return ProjectBundle(**dados)


class TestProblemasDeCoerenciaInterna:
    def test_bundle_coerente_nao_tem_problemas(self) -> None:
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
        )
        assert problemas_de_coerencia_interna(bundle) == []

    def test_conexao_duplicada_e_problema(self) -> None:
        bundle = _bundle_minimo(
            connections=[
                BundleConnection(name="gateway-1", endpoint="opc.tcp://a"),
                BundleConnection(name="gateway-1", endpoint="opc.tcp://b"),
            ]
        )
        problemas = problemas_de_coerencia_interna(bundle)
        assert any("gateway-1" in p and "duplicad" in p for p in problemas)

    def test_flow_duplicado_e_problema(self) -> None:
        bundle = _bundle_minimo(
            flows=[
                BundleFlow(name="Coluna C-101", ts_seconds=1.0, graph={"nodes": [], "edges": []}),
                BundleFlow(name="Coluna C-101", ts_seconds=2, graph={"nodes": [], "edges": []}),
            ]
        )
        problemas = problemas_de_coerencia_interna(bundle)
        assert any("Coluna C-101" in p and "duplicad" in p for p in problemas)

    def test_tag_duplicada_na_mesma_conexao_e_problema(self) -> None:
        bundle = _bundle_minimo(
            connections=[BundleConnection(name="gateway-1", endpoint="opc.tcp://a")],
            tags=[
                BundleTag(
                    connection="gateway-1",
                    name="TT-101",
                    node_id="a",
                    direction="r",
                    data_type="float",
                ),
                BundleTag(
                    connection="gateway-1",
                    name="TT-101",
                    node_id="b",
                    direction="r",
                    data_type="float",
                ),
            ],
        )
        problemas = problemas_de_coerencia_interna(bundle)
        assert any("TT-101" in p and "gateway-1" in p and "duplicad" in p for p in problemas)

    def test_tag_homonima_em_conexoes_diferentes_e_legitima_nao_e_problema(self) -> None:
        # TST-01: uq_tags_connection_name é por conexão, não por projeto — reprovar
        # isto quebraria o caso normativo que motiva a referência por objeto (§2.2-2).
        bundle = _bundle_minimo(
            connections=[
                BundleConnection(name="gateway-1", endpoint="opc.tcp://a"),
                BundleConnection(name="gateway-2", endpoint="opc.tcp://b"),
            ],
            tags=[
                BundleTag(
                    connection="gateway-1",
                    name="TT-101",
                    node_id="a",
                    direction="r",
                    data_type="float",
                ),
                BundleTag(
                    connection="gateway-2",
                    name="TT-101",
                    node_id="b",
                    direction="r",
                    data_type="float",
                ),
            ],
        )
        assert problemas_de_coerencia_interna(bundle) == []

    def test_tag_com_conexao_ausente_no_bundle_e_problema(self) -> None:
        bundle = _bundle_minimo(
            connections=[BundleConnection(name="gateway-1", endpoint="opc.tcp://a")],
            tags=[
                BundleTag(
                    connection="gateway-fantasma",
                    name="TT-101",
                    node_id="a",
                    direction="r",
                    data_type="float",
                )
            ],
        )
        problemas = problemas_de_coerencia_interna(bundle)
        assert any("gateway-fantasma" in p for p in problemas)

    def test_flow_watchdog_com_conexao_ausente_no_bundle_e_problema(self) -> None:
        bundle = _bundle_minimo(
            flows=[
                BundleFlow(
                    name="Coluna C-101",
                    ts_seconds=1.0,
                    graph={"nodes": [], "edges": []},
                    watchdog_enabled=True,
                    watchdog_connection="gateway-fantasma",
                    watchdog_read_node_id="ns=2;s=WD_R",
                    watchdog_write_node_id="ns=2;s=WD_W",
                )
            ]
        )
        problemas = problemas_de_coerencia_interna(bundle)
        assert any("gateway-fantasma" in p for p in problemas)

    def test_tag_ref_que_nao_casa_com_tag_do_bundle_e_problema_prefixado_pelo_flow(
        self,
    ) -> None:
        bundle = _bundle_minimo(
            connections=[BundleConnection(name="gateway-1", endpoint="opc.tcp://a")],
            tags=[
                BundleTag(
                    connection="gateway-1",
                    name="TT-101",
                    node_id="a",
                    direction="r",
                    data_type="float",
                )
            ],
            flows=[
                BundleFlow(
                    name="Coluna C-101",
                    ts_seconds=1.0,
                    graph={
                        "nodes": [
                            {
                                "id": "r1",
                                "type": "opc_read",
                                "data": {"tag_ref": {"connection": "gateway-1", "tag": "TT-999"}},
                            }
                        ],
                        "edges": [],
                    },
                )
            ],
        )
        problemas = problemas_de_coerencia_interna(bundle)
        assert any("fluxo 'Coluna C-101'" in p for p in problemas)
        assert any("TT-999" in p for p in problemas)

    def test_exported_at_nao_influencia_o_resultado(self) -> None:
        # §2.1-5: exported_at é metadado do arquivo, nunca insumo de validação.
        bundle_a = _bundle_minimo(exported_at=datetime(2020, 1, 1, tzinfo=UTC))
        bundle_b = _bundle_minimo(exported_at=EXPORTED_AT)
        assert (
            problemas_de_coerencia_interna(bundle_a)
            == problemas_de_coerencia_interna(bundle_b)
            == []
        )
