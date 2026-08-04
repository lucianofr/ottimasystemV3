"""Consulta do log de eventos (RF-803): ordenação, filtros, limites e papéis (ADR-015)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import insert

from ottima_core.models import events_table

BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _evento(
    offset_s: int,
    severity: str = "info",
    origin: str = "conn:1",
    kind: str = "comm_failure",
) -> dict[str, Any]:
    return {
        "ts": BASE + timedelta(seconds=offset_s),
        "severity": severity,
        "origin": origin,
        "message": "Falha de comunicação",
        "payload": {"kind": kind, "conn_id": 1},
    }


async def _inserir(db_session, linhas: list[dict[str, Any]]) -> None:
    await db_session.execute(insert(events_table), linhas)
    await db_session.commit()  # SAVEPOINT do conftest raiz — não vaza


def _ts(offset_s: int) -> str:
    return (BASE + timedelta(seconds=offset_s)).isoformat()


async def test_sem_filtro_devolve_mais_recentes_primeiro_e_default_100(
    client, operator_headers, db_session
):
    await _inserir(db_session, [_evento(i) for i in range(105)])
    r = await client.get("/api/events", headers=operator_headers)
    assert r.status_code == 200
    corpo = r.json()
    assert len(corpo) == 100  # DEFAULT_LIMIT
    timestamps = [datetime.fromisoformat(e["ts"]) for e in corpo]
    assert timestamps == sorted(timestamps, reverse=True)
    assert timestamps[0] == BASE + timedelta(seconds=104)
    assert timestamps[-1] == BASE + timedelta(seconds=5)


async def test_filtro_severity(client, operator_headers, db_session):
    await _inserir(
        db_session,
        [_evento(0, severity="info"), _evento(1, severity="alarm"), _evento(2, severity="warning")],
    )
    r = await client.get("/api/events", params={"severity": "alarm"}, headers=operator_headers)
    assert r.status_code == 200
    assert [e["severity"] for e in r.json()] == ["alarm"]
    fora = await client.get("/api/events", params={"severity": "grave"}, headers=operator_headers)
    assert fora.status_code == 422


async def test_filtro_origin_e_exato(client, operator_headers, db_session):
    await _inserir(db_session, [_evento(0, origin="conn:1"), _evento(1, origin="conn:12")])
    r = await client.get("/api/events", params={"origin": "conn:1"}, headers=operator_headers)
    assert r.status_code == 200
    assert [e["origin"] for e in r.json()] == ["conn:1"]


async def test_janela_inclusiva_nos_dois_extremos(client, operator_headers, db_session):
    await _inserir(db_session, [_evento(i) for i in range(4)])
    r = await client.get(
        "/api/events",
        params={"start": "2026-01-01T12:00:01", "end": _ts(2)},  # start naive vale como UTC
        headers=operator_headers,
    )
    assert r.status_code == 200
    assert [datetime.fromisoformat(e["ts"]) for e in r.json()] == [
        BASE + timedelta(seconds=2),
        BASE + timedelta(seconds=1),
    ]


async def test_start_depois_de_end_422(client, operator_headers):
    r = await client.get(
        "/api/events", params={"start": _ts(10), "end": _ts(0)}, headers=operator_headers
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "start deve ser anterior a end"


async def test_limite_respeitado_e_fora_da_faixa_422(client, operator_headers, db_session):
    await _inserir(db_session, [_evento(i) for i in range(5)])
    r = await client.get("/api/events", params={"limit": 2}, headers=operator_headers)
    assert r.status_code == 200 and len(r.json()) == 2
    assert (
        await client.get("/api/events", params={"limit": 0}, headers=operator_headers)
    ).status_code == 422
    assert (
        await client.get("/api/events", params={"limit": 1001}, headers=operator_headers)
    ).status_code == 422
    assert (
        await client.get("/api/events", params={"limit": 1000}, headers=operator_headers)
    ).status_code == 200


async def test_shape_do_item(client, operator_headers, db_session):
    await _inserir(db_session, [_evento(0, severity="alarm", kind="comm_failure")])
    item = (await client.get("/api/events", headers=operator_headers)).json()[0]
    assert set(item) == {"ts", "severity", "origin", "message", "payload"}
    assert item["payload"]["kind"] == "comm_failure"
    assert item["severity"] == "alarm"
    assert item["message"] == "Falha de comunicação"


async def test_operador_le_e_sem_token_401(client, operator_headers, db_session):
    await _inserir(db_session, [_evento(0)])
    assert (await client.get("/api/events", headers=operator_headers)).status_code == 200
    assert (await client.get("/api/events")).status_code == 401


async def test_filtros_combinados(client, operator_headers, db_session):
    await _inserir(
        db_session,
        [
            _evento(0, severity="alarm", origin="conn:1"),
            _evento(1, severity="alarm", origin="conn:2"),
            _evento(2, severity="info", origin="conn:1"),
            _evento(9, severity="alarm", origin="conn:1"),  # fora da janela
        ],
    )
    r = await client.get(
        "/api/events",
        params={"severity": "alarm", "origin": "conn:1", "start": _ts(0), "end": _ts(2)},
        headers=operator_headers,
    )
    assert r.status_code == 200
    assert [datetime.fromisoformat(e["ts"]) for e in r.json()] == [BASE]
