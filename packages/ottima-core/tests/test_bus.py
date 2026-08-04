from datetime import UTC, datetime

from ottima_core.bus import (
    CHANNEL_EVENTS,
    CHANNEL_FLOW_COMMANDS,
    CHANNEL_OPC_WRITES,
    EventMessage,
    FlowStatus,
    OpcValue,
    OpcWrite,
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
    assert set(OpcWrite(conn_id=1, tag_id=2, value=3.0, source="user:1", ts=ts).model_dump()) == {
        "conn_id",
        "tag_id",
        "value",
        "source",
        "ts",
    }
    assert set(FlowStatus(state="running", scan_ms=12.5, overruns=0, ts=ts).model_dump()) == {
        "state",
        "scan_ms",
        "overruns",
        "ts",
    }
    assert set(
        EventMessage(ts=ts, severity="alarm", origin="conn:1", message="x", payload={}).model_dump()
    ) == {"ts", "severity", "origin", "message", "payload"}
