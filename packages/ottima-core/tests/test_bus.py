import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ottima_core.bus import (
    CHANNEL_EVENTS,
    CHANNEL_FLOW_COMMANDS,
    CHANNEL_OPC_WRITES,
    EventMessage,
    ExchangeValue,
    FlowStatus,
    OpcValue,
    OpcWrite,
    PortValue,
    channel_flow_status,
    channel_mpc_state,
    channel_opc_values,
)
from ottima_core.signal import OpcQuality, Quality, Substatus


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
                "out": PortValue(v=42.5, quality=Quality.GOOD),
                "in": PortValue(v=None, quality=Quality.BAD),
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
                "out": {
                    "v": 42.5,
                    "quality": 2,
                    "substatus": 0,
                    "hi_limited": False,
                    "lo_limited": False,
                },
                "in": {
                    "v": None,
                    "quality": 0,
                    "substatus": 0,
                    "hi_limited": False,
                    "lo_limited": False,
                },
            }
        },
    }


def test_port_value_preserva_bool_e_float_no_round_trip():
    # O canvas desenha lâmpada para bool e número para float: True virando 1.0 é defeito
    # observável. A união em modo smart do Pydantic v2 preserva o tipo exato — travado aqui.
    booleano = PortValue.model_validate_json(
        PortValue(v=True, quality=Quality.GOOD).model_dump_json()
    )
    assert booleano.v is True

    numero = PortValue.model_validate_json(
        PortValue(v=42.5, quality=Quality.GOOD).model_dump_json()
    )
    assert not isinstance(numero.v, bool)
    assert numero.v == 42.5

    invalido = PortValue.model_validate_json(
        PortValue(v=None, quality=Quality.BAD).model_dump_json()
    )
    assert invalido.v is None
    assert invalido.quality is Quality.BAD


def test_port_value_carrega_signal_completo_sem_ok():
    pv = PortValue(v=1.5, quality=Quality.UNCERTAIN)
    data = json.loads(pv.model_dump_json())
    assert data == {
        "v": 1.5,
        "quality": 1,
        "substatus": 0,
        "hi_limited": False,
        "lo_limited": False,
    }
    assert "ok" not in data


def test_exchange_value_round_trip_com_quality():
    ev = ExchangeValue(
        key="k",
        ts=datetime.now(UTC),
        v=True,
        quality=Quality.GOOD,
        substatus=Substatus.NON_SPECIFIC,
        period_s=1.0,
    )
    volta = ExchangeValue.model_validate_json(ev.model_dump_json())
    assert volta.v is True and volta.quality is Quality.GOOD  # bool não vira 1.0 (A-5)


def test_flow_status_aceita_ports_vazio_em_transicao_de_estado():
    # Publicação de transição (deploy/stop/falha, spec F3 §2.2-5) não tem varredura atrás.
    parado = FlowStatus(state="stopped", scan_ms=0.0, overruns=0, ts=datetime.now(UTC), ports={})
    assert parado.ports == {}
    assert parado.model_dump(mode="json")["ports"] == {}


def test_opc_value_quality_vira_membro_e_o_fio_fica_byte_identico():
    # spec F1 §3.2: 0=good, 1=uncertain, 2=bad. Int cru entra (site legado nunca vira bomba
    # de runtime), membro sai, e o JSON emite o MESMO int — fio e `samples` intocados.
    v = OpcValue(tag_id=1, ts=datetime.now(UTC), value=1.5, quality=0)
    assert v.quality is OpcQuality.GOOD
    assert json.loads(v.model_dump_json())["quality"] == 0
    volta = OpcValue.model_validate_json(v.model_dump_json())
    assert volta.quality is OpcQuality.GOOD


def test_opc_value_rejeita_enum_de_porta_e_bool():
    # Em lax puro, `Quality.BAD` (=0) viraria GOOD e `Quality.GOOD` (=2) viraria BAD — as
    # duas inversões silenciosas de polaridade que o guard existe para matar (ADR-043 §4).
    # `True` é int (==1) e viraria UNCERTAIN. Só construção Python produz esses tipos:
    # o parse do fio (JSON) nunca passa por aqui.
    ts = datetime.now(UTC)
    with pytest.raises(ValidationError):
        OpcValue(tag_id=1, ts=ts, value=1.0, quality=Quality.BAD)
    with pytest.raises(ValidationError):
        OpcValue(tag_id=1, ts=ts, value=1.0, quality=Quality.GOOD)
    with pytest.raises(ValidationError):
        OpcValue(tag_id=1, ts=ts, value=1.0, quality=True)


def test_opc_value_quality_fora_do_dominio_colapsa_para_bad_sem_derrubar_a_mensagem():
    # Lado seguro (ADR-009): rejeitar descartaria o payload inteiro no espelho
    # (`snapshot._ingest` faz warning+return) e a disponibilidade do MPC seria classificada
    # sobre o último valor BOM retido. Colapsar para BAD mantém a mensagem viva e degrada a
    # tag — o recorder grava NULL (ADR-037) em vez do valor com qualidade desconhecida.
    raw = json.dumps({"tag_id": 5, "ts": "2026-09-17T10:00:00+00:00", "value": 1.5, "quality": 8})
    v = OpcValue.model_validate_json(raw)
    assert v.quality is OpcQuality.BAD
