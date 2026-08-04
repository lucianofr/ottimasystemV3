"""Contrato do publisher canônico de eventos (spec F2 §7.1/7.3, ADR-020).

Testes contra Redis real (fixture `redis_client` do conftest raiz): o que importa é o que
chega no canal, não o que a função devolve.
"""

import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest
from redis.asyncio import Redis

from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_COMM_FAILURE,
    KIND_OPC_WRITE,
    EventMessage,
    publish_event,
)

RECEIVE_TIMEOUT = 5.0


@pytest.fixture
async def events_sub(redis_client):
    """Assinante do canal `events` já com a confirmação de inscrição consumida."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_EVENTS)
    confirmation = await pubsub.get_message(timeout=RECEIVE_TIMEOUT)
    assert confirmation is not None and confirmation["type"] == "subscribe"
    yield pubsub
    await pubsub.aclose()


async def receive(pubsub) -> str:
    async with asyncio.timeout(RECEIVE_TIMEOUT):
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message is not None:
                return message["data"]


async def test_publica_payload_verbatim_prd_71(redis_client, events_sub):
    await publish_event(
        redis_client,
        severity="alarm",
        origin="conn:1",
        message="Falha de comunicação com o CLP",
        kind=KIND_COMM_FAILURE,
    )
    received = EventMessage.model_validate_json(await receive(events_sub))
    assert set(received.model_dump()) == {"ts", "severity", "origin", "message", "payload"}
    assert received.severity == "alarm"
    assert received.origin == "conn:1"
    assert received.message == "Falha de comunicação com o CLP"


async def test_kind_vai_no_payload_junto_das_chaves_do_chamador(redis_client, events_sub):
    await publish_event(
        redis_client,
        severity="info",
        origin="conn:2",
        message="Escrita OPC concluída",
        kind=KIND_OPC_WRITE,
        payload={"tag_id": 7, "value": 1.5},
    )
    received = EventMessage.model_validate_json(await receive(events_sub))
    assert received.payload == {"kind": KIND_OPC_WRITE, "tag_id": 7, "value": 1.5}
    assert next(iter(received.payload)) == "kind"


async def test_kind_do_argumento_vence_o_do_dict(redis_client, events_sub):
    await publish_event(
        redis_client,
        severity="info",
        origin="api",
        message="Projeto ativado",
        kind=KIND_OPC_WRITE,
        payload={"kind": "valor_divergente", "tag_id": 3},
    )
    received = EventMessage.model_validate_json(await receive(events_sub))
    assert received.payload == {"kind": KIND_OPC_WRITE, "tag_id": 3}


async def test_ts_default_e_utc_aware_e_serializa_com_offset(redis_client, events_sub):
    antes = datetime.now(UTC)
    event = await publish_event(
        redis_client, severity="info", origin="api", message="Tag criada", kind="tag_created"
    )
    depois = datetime.now(UTC)

    assert event.ts.tzinfo is not None
    assert antes <= event.ts <= depois

    raw = await receive(events_sub)
    ts_serializado = EventMessage.model_validate_json(raw).ts
    assert ts_serializado.utcoffset() == timedelta(0)
    assert '"ts":"' in raw.replace(" ", "")
    assert raw.split('"ts":"')[1].split('"')[0].endswith(("Z", "+00:00"))


async def test_ts_naive_vira_utc_e_aware_de_outro_fuso_converte(redis_client, events_sub):
    naive = datetime(2026, 8, 3, 12, 0, 0)
    event = await publish_event(
        redis_client,
        severity="info",
        origin="api",
        message="Tag atualizada",
        kind="tag_updated",
        ts=naive,
    )
    assert event.ts == datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)
    assert EventMessage.model_validate_json(await receive(events_sub)).ts == event.ts

    em_brasilia = datetime(2026, 8, 3, 9, 0, 0, tzinfo=timezone(timedelta(hours=-3)))
    event = await publish_event(
        redis_client,
        severity="info",
        origin="api",
        message="Tag removida",
        kind="tag_deleted",
        ts=em_brasilia,
    )
    assert event.ts == datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)
    assert EventMessage.model_validate_json(await receive(events_sub)).ts == event.ts


async def test_round_trip_do_evento_retornado(redis_client, events_sub):
    event = await publish_event(
        redis_client,
        severity="warning",
        origin="recorder",
        message="Fila de amostras acima do limite",
        kind="recorder_backpressure",
        payload={"queued": 12000},
    )
    assert EventMessage.model_validate_json(await receive(events_sub)) == event


async def test_falha_de_publicacao_nao_propaga(caplog):
    # Porta morta: a publicação estoura ConnectionError, o chamador não pode sentir.
    morto = Redis.from_url(
        "redis://127.0.0.1:1/0", decode_responses=True, socket_connect_timeout=0.5
    )
    try:
        event = await publish_event(
            morto,
            severity="alarm",
            origin="conn:9",
            message="Falha de comunicação com o CLP",
            kind=KIND_COMM_FAILURE,
        )
    finally:
        await morto.aclose()

    assert event.payload["kind"] == KIND_COMM_FAILURE
    assert any(record.levelname == "ERROR" for record in caplog.records)


async def test_fixture_redis_sobe_e_responde(redis_client):
    assert await redis_client.ping() is True
    await redis_client.set("chave-de-isolamento", "1")
    assert await redis_client.get("chave-de-isolamento") == "1"  # decode_responses=True


async def test_fixture_redis_isola_entre_testes(redis_client):
    assert await redis_client.get("chave-de-isolamento") is None
