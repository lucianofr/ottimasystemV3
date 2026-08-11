from datetime import UTC, datetime

from ottima_core.bus import (
    CHANNEL_EVENTS,
    CHANNEL_FLOW_COMMANDS,
    CHANNEL_OPC_WRITES,
    EventMessage,
    FlowStatus,
    OpcValue,
    OpcWrite,
    PortValue,
    channel_flow_status,
    channel_mpc_state,
    channel_opc_values,
)


def test_nomes_de_canais_prd_71():
    assert CHANNEL_OPC_WRITES == "opc.writes"
    assert CHANNEL_FLOW_COMMANDS == "flow.commands"
    assert CHANNEL_EVENTS == "events"
    assert channel_opc_values(3) == "opc.values.3"
    assert channel_flow_status(7) == "flow.status.7"
    assert channel_mpc_state(7, "mpc1") == "mpc.state.7.mpc1"


def test_payloads_verbatim_prd_71():
    ts = datetime.now(UTC)
    assert set(OpcValue(tag_id=1, ts=ts, value=1.5, quality=0).model_dump()) == {
        "tag_id",
        "ts",
        "value",
        "quality",
    }
    assert set(
        OpcWrite(conn_id=1, tag_id=2, flow_id=7, value=3.0, source="user:1", ts=ts).model_dump()
    ) == {
        "conn_id",
        "tag_id",
        "flow_id",
        "value",
        "source",
        "ts",
    }
    assert set(FlowStatus(state="running", scan_ms=12.5, overruns=0, ts=ts).model_dump()) == {
        "state",
        "scan_ms",
        "overruns",
        "ts",
        "ports",
    }
    assert set(
        EventMessage(ts=ts, severity="alarm", origin="conn:1", message="x", payload={}).model_dump()
    ) == {"ts", "severity", "origin", "message", "payload"}


def test_flow_status_com_ports_serializa_verbatim_spec_f3_42():
    # Exemplo verbatim do spec F3 §4.2 (emenda PRD §7.1 v1.2): o canvas ao vivo lê daqui.
    status = FlowStatus(
        state="running",
        scan_ms=3.2,
        overruns=0,
        ts=datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC),
        ports={
            "blk-1": {
                "out": PortValue(v=42.5, ok=True),
                "in": PortValue(v=None, ok=False),
            }
        },
    )
    assert status.model_dump(mode="json") == {
        "state": "running",
        "scan_ms": 3.2,
        "overruns": 0,
        "ts": "2026-08-04T12:00:00Z",
        "ports": {
            "blk-1": {
                "out": {"v": 42.5, "ok": True},
                "in": {"v": None, "ok": False},
            }
        },
    }


def test_port_value_preserva_bool_e_float_no_round_trip():
    # O canvas desenha lâmpada para bool e número para float: True virando 1.0 é defeito
    # observável. A união em modo smart do Pydantic v2 preserva o tipo exato — travado aqui.
    booleano = PortValue.model_validate_json(PortValue(v=True, ok=True).model_dump_json())
    assert booleano.v is True

    numero = PortValue.model_validate_json(PortValue(v=42.5, ok=True).model_dump_json())
    assert not isinstance(numero.v, bool)
    assert numero.v == 42.5

    invalido = PortValue.model_validate_json(PortValue(v=None, ok=False).model_dump_json())
    assert invalido.v is None
    assert invalido.ok is False


def test_flow_status_aceita_ports_vazio_em_transicao_de_estado():
    # Publicação de transição (deploy/stop/falha, spec F3 §2.2-5) não tem varredura atrás.
    parado = FlowStatus(state="stopped", scan_ms=0.0, overruns=0, ts=datetime.now(UTC), ports={})
    assert parado.ports == {}
    assert parado.model_dump(mode="json")["ports"] == {}
