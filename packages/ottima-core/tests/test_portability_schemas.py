"""Testes dos schemas do arquivo de projeto (bundle) — spec F6 §2.1-4.

Todos puros: nenhuma dependência de banco/Redis/disco.
"""

import pytest
from pydantic import ValidationError

from ottima_core.portability.schemas import (
    SCHEMA_VERSION,
    BundleCalcInputRef,
    BundleConnection,
    BundleFlow,
    BundleProject,
    BundleTag,
    BundleTagRef,
    ProjectBundle,
)
from ottima_core.schemas.calculated_tags import MAX_CALC_SCRIPT_LENGTH

# Contrato verbatim da spec §2.1-4: exemplo normativo de conexão com auth_mode
# "user_password", usuário presente e SEM senha (o bundle nunca carrega senha).
CONEXAO_NORMATIVA = {
    "name": "gateway-1",
    "endpoint": "opc.tcp://10.0.0.5:4840",
    "security_policy": "basic256sha256",
    "security_mode": "sign_and_encrypt",
    "auth_mode": "user_password",
    "auth_username": "ottima",
}


def test_schema_version_e_1():
    assert SCHEMA_VERSION == 1


def test_bundle_project_rejeita_campo_fora_da_fronteira():
    with pytest.raises(ValidationError) as exc_info:
        BundleProject(name="Planta C-101", description="Coluna debutanizadora", id=1)
    assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


@pytest.mark.parametrize("campo_extra", ["auth_password", "server_cert_file", "id", "project_id"])
def test_bundle_connection_rejeita_campo_fora_da_fronteira(campo_extra):
    with pytest.raises(ValidationError) as exc_info:
        BundleConnection(**CONEXAO_NORMATIVA, **{campo_extra: "x"})
    assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


    conexao = BundleConnection(name="gw1", endpoint="opc.tcp://10.0.0.5:4840")


@pytest.mark.parametrize("campo_extra", ["connection_id", "id"])
def test_bundle_tag_rejeita_campo_fora_da_fronteira(campo_extra):
    with pytest.raises(ValidationError) as exc_info:
        BundleTag(
            connection="gateway-1",
            name="TT-101",
            node_id="ns=2;s=TT101",
            direction="r",
            data_type="float",
            **{campo_extra: 1},
        )
    assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


def test_bundle_connection_reprova_policy_mode_incoerente_com_mensagem_verbatim():
    dados = {**CONEXAO_NORMATIVA, "security_mode": "none"}
    with pytest.raises(ValidationError) as exc_info:
        BundleConnection(**dados)
    assert (
        "SecurityPolicy None exige modo None; Basic256Sha256 exige Sign ou SignAndEncrypt"
        in str(exc_info.value)
    )


def test_bundle_connection_user_password_sem_senha_com_usuario_e_valido():
    # Exemplo normativo §2.1-1: o bundle nunca carrega senha, então este caso é aprovado
    # apesar de ConnectionCreate recusar o mesmo dado por exigir senha também.
    conexao = BundleConnection(**CONEXAO_NORMATIVA)
    assert conexao.auth_username == "ottima"
    assert not hasattr(conexao, "auth_password")


def test_bundle_connection_user_password_sem_usuario_reprova():
    dados = {**CONEXAO_NORMATIVA, "auth_username": None}
    with pytest.raises(ValidationError):
        BundleConnection(**dados)


def test_bundle_flow_desired_state_invalido_reprova_na_forma():
    with pytest.raises(ValidationError):
        BundleFlow(
            name="Coluna C-101",
            ts_seconds=1.0,
            desired_state="paused",
            graph={"nodes": [], "edges": []},
        )


def test_bundle_flow_ts_seconds_fora_do_conjunto_reprova():
    with pytest.raises(ValidationError):
        BundleFlow(
            name="Coluna C-101",
            ts_seconds=3,
            desired_state="stopped",
            graph={"nodes": [], "edges": []},
        )


def test_bundle_flow_rejeita_campo_fora_da_fronteira():
    with pytest.raises(ValidationError) as exc_info:
        BundleFlow(
            name="Coluna C-101",
            ts_seconds=1.0,
            desired_state="stopped",
            graph={"nodes": [], "edges": []},
            id=1,
        )
    assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


def test_bundle_flow_watchdog_valido_e_aceito():
    flow = BundleFlow(
        name="Coluna C-101",
        ts_seconds=1.0,
        graph={"nodes": [], "edges": []},
        watchdog_enabled=True,
        watchdog_connection="gateway-1",
        watchdog_read_node_id="ns=2;s=WD_R",
        watchdog_write_node_id="ns=2;s=WD_W",
        watchdog_period_ms=2000,
    )
    assert flow.watchdog_connection == "gateway-1"
    assert flow.watchdog_period_ms == 2000


def test_bundle_flow_watchdog_habilitado_sem_conexao_reprova():
    with pytest.raises(ValidationError):
        BundleFlow(
            name="Coluna C-101",
            ts_seconds=1.0,
            graph={"nodes": [], "edges": []},
            watchdog_enabled=True,
            watchdog_read_node_id="ns=2;s=WD_R",
            watchdog_write_node_id="ns=2;s=WD_W",
        )


def test_bundle_flow_watchdog_com_node_ids_iguais_reprova():
    with pytest.raises(ValidationError):
        BundleFlow(
            name="Coluna C-101",
            ts_seconds=1.0,
            graph={"nodes": [], "edges": []},
            watchdog_enabled=True,
            watchdog_connection="gateway-1",
            watchdog_read_node_id="ns=2;s=WD",
            watchdog_write_node_id="ns=2;s=WD",
        )


def test_bundle_tag_ref_e_objeto_com_connection_e_tag():
    ref = BundleTagRef(connection="gateway-1", tag="TT-101")
    assert ref.connection == "gateway-1"
    assert ref.tag == "TT-101"


def test_bundle_tag_ref_rejeita_campo_fora_da_fronteira():
    with pytest.raises(ValidationError) as exc_info:
        BundleTagRef(connection="gateway-1", tag="TT-101", connection_id=1)
    assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


def test_project_bundle_monta_o_contrato_verbatim_da_spec():
    bundle = ProjectBundle(
        schema_version=1,
        exported_at="2026-08-07T21:40:00Z",
        project=BundleProject(name="Planta C-101", description="Coluna debutanizadora"),
        connections=[BundleConnection(**CONEXAO_NORMATIVA)],
        tags=[
            BundleTag(
                connection="gateway-1",
                name="TT-101",
                node_id="ns=2;s=TT101",
                direction="r",
                data_type="float",
                eu="C",
                description="Temperatura de topo",
            )
        ],
        flows=[
            BundleFlow(
                name="Coluna C-101",
                ts_seconds=1.0,
                desired_state="stopped",
                graph={"nodes": [], "edges": []},
            )
        ],
    )
    assert bundle.connections[0].name == "gateway-1"
    assert bundle.tags[0].node_id == "ns=2;s=TT101"
    assert bundle.flows[0].desired_state == "stopped"


def test_project_bundle_rejeita_campo_fora_da_fronteira():
    with pytest.raises(ValidationError) as exc_info:
        ProjectBundle(
            schema_version=1,
            exported_at="2026-08-07T21:40:00Z",
            project=BundleProject(name="Planta C-101"),
            connections=[],
            tags=[],
            flows=[],
            created_at="2026-08-07T21:40:00Z",
        )
    assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())


def test_bundle_tag_opc_com_campo_de_tag_calculada_reprova():
    # XOR (RF-208, ADR-033 D6): connection+node_id (OPC) não pode conviver com period_seconds.
    with pytest.raises(ValidationError):
        BundleTag(
            connection="gateway-1",
            name="TT-101",
            node_id="ns=2;s=TT101",
            direction="r",
            data_type="float",
            period_seconds=5,
        )


def test_bundle_tag_calculada_valida_e_aceita():
    tag = BundleTag(
        name="CALC-1",
        direction="r",
        data_type="float",
        period_seconds=5,
        code="OUT = IN1 * 2",
        input_tags=[BundleCalcInputRef(connection="gateway-1", tag="TT-101")],
    )
    assert tag.connection is None
    assert tag.node_id is None
    assert tag.input_tags == [BundleCalcInputRef(connection="gateway-1", tag="TT-101")]


def test_bundle_tag_code_acima_do_teto_reprova():
    with pytest.raises(ValidationError):
        BundleTag(
            name="CALC-1",
            direction="r",
            data_type="float",
            period_seconds=5,
            code="x" * (MAX_CALC_SCRIPT_LENGTH + 1),
            input_tags=[],
        )


def test_bundle_tag_calculada_sem_entradas_e_valida():
    tag = BundleTag(
        name="CALC-1",
        direction="r",
        data_type="float",
        period_seconds=5,
        code="OUT = 1.0",
        input_tags=[],
    )
    assert tag.input_tags == []


def test_bundle_tag_nem_opc_nem_calculada_reprova():
    # connection presente mas node_id ausente: não é OPC completa nem calculada.
    with pytest.raises(ValidationError):
        BundleTag(connection="gateway-1", name="TT-101", direction="r", data_type="float")


def test_bundle_tag_calculada_com_campo_ausente_reprova():
    # period_seconds e code presentes, mas input_tags ausente: XOR exige os três juntos.
    with pytest.raises(ValidationError):
        BundleTag(
            name="CALC-1",
            direction="r",
            data_type="float",
            period_seconds=5,
            code="OUT = 1.0",
        )


def test_bundle_calc_input_ref_aceita_connection_none_para_referenciar_outra_calculada():
    ref = BundleCalcInputRef(connection=None, tag="CALC-A")
    assert ref.connection is None
    assert ref.tag == "CALC-A"


def test_bundle_calc_input_ref_rejeita_campo_fora_da_fronteira():
    with pytest.raises(ValidationError) as exc_info:
        BundleCalcInputRef(connection="gateway-1", tag="TT-101", tag_id=1)
    assert any(e["type"] == "extra_forbidden" for e in exc_info.value.errors())
