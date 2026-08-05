"""Contratos do espelho de valores do flow-runtime (RF-401, spec F3 §2.1, §3.0, §3.1)."""

import asyncio
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis

from ottima_core.bus import OpcValue, channel_opc_values
from ottima_flow_runtime.snapshot import ValueSnapshot
from runtime_test_helpers import AWAIT_TIMEOUT_S, await_until

TS = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)


async def publish(
    redis_client: Redis,
    conn_id: int,
    tag_id: int,
    value: float,
    quality: int = 0,
    ts: datetime = TS,
) -> int:
    """Publica um `OpcValue` e devolve quantos assinantes o receberam."""
    payload = OpcValue(tag_id=tag_id, ts=ts, value=value, quality=quality)
    return await redis_client.publish(channel_opc_values(conn_id), payload.model_dump_json())


async def pubsub_client_ids(redis_client: Redis) -> set[str]:
    """Ids das conexões em modo pubsub do servidor — permite matar só a do espelho."""
    return {client["id"] for client in await redis_client.client_list(_type="pubsub")}


@pytest.fixture
async def snapshot(redis_client: Redis):
    snap = ValueSnapshot(redis_client)
    await snap.start()
    yield snap
    await snap.stop()


async def test_valor_publicado_aparece_no_espelho(redis_client, snapshot):
    await publish(redis_client, conn_id=1, tag_id=7, value=42.5)

    await await_until(lambda: snapshot.get(7) is not None)
    tag_value = snapshot.get(7)
    assert tag_value.value == 42.5
    assert tag_value.quality == 0
    assert tag_value.ts == TS


async def test_tag_sem_valor_devolve_none(snapshot):
    """Cold start (spec §3.0): ausência é `None`, não um valor sintético."""
    assert snapshot.get(999) is None


async def test_ultima_publicacao_vence(redis_client, snapshot):
    await publish(redis_client, conn_id=1, tag_id=7, value=1.0)
    await await_until(lambda: snapshot.get(7) is not None)

    await publish(redis_client, conn_id=1, tag_id=7, value=2.0, ts=TS.replace(second=30))

    await await_until(lambda: snapshot.get(7).value == 2.0)
    assert snapshot.get(7).ts == TS.replace(second=30)


async def test_conexoes_diferentes_convivem_no_mesmo_espelho(redis_client, snapshot):
    """Prova que a assinatura por padrão cobre o padrão inteiro, não um canal só."""
    await publish(redis_client, conn_id=1, tag_id=11, value=10.0)
    await publish(redis_client, conn_id=2, tag_id=22, value=20.0)

    await await_until(lambda: snapshot.get(11) is not None and snapshot.get(22) is not None)
    assert snapshot.get(11).value == 10.0
    assert snapshot.get(22).value == 20.0


async def test_quality_ruim_e_preservada(redis_client, snapshot):
    """O espelho não filtra invalidez: quem decide é o bloco OPC-Read (spec §3.1)."""
    await publish(redis_client, conn_id=1, tag_id=7, value=3.0, quality=2)

    await await_until(lambda: snapshot.get(7) is not None)
    assert snapshot.get(7).quality == 2


async def test_payload_invalido_nao_derruba_o_assinante(redis_client, snapshot):
    await redis_client.publish(channel_opc_values(1), "{isso nao e json}")
    await redis_client.publish(channel_opc_values(1), '{"tag_id": "x"}')

    await publish(redis_client, conn_id=1, tag_id=7, value=9.0)

    await await_until(lambda: snapshot.get(7) is not None)
    assert snapshot.get(7).value == 9.0


async def test_stop_e_idempotente_e_encerra_a_absorcao(redis_client, snapshot):
    await publish(redis_client, conn_id=1, tag_id=7, value=1.0)
    await await_until(lambda: snapshot.get(7) is not None)

    await snapshot.stop()
    await snapshot.stop()  # desmonte não levanta na segunda chamada

    # Zero destinatários: a inscrição saiu do servidor, então nada mais pode ser absorvido.
    assert await publish(redis_client, conn_id=1, tag_id=7, value=2.0) == 0
    assert snapshot.get(7).value == 1.0


async def test_start_duas_vezes_nao_cria_dois_assinantes(redis_client, snapshot):
    await snapshot.start()

    # O contador de destinatários do PUBLISH é o efeito observável: dois assinantes daria 2.
    assert await publish(redis_client, conn_id=1, tag_id=7, value=5.0) == 1

    await await_until(lambda: snapshot.get(7) is not None)
    assert snapshot.get(7).value == 5.0


async def test_queda_do_assinante_e_reassinada(redis_client):
    """Exceção no laço vira reassinatura com espera, não perda permanente do espelho.

    Espelho instanciado aqui, e não pela fixture: identificar a conexão dele exige comparar
    os assinantes do servidor antes e depois do `start()`.
    """
    others = await pubsub_client_ids(redis_client)
    snap = ValueSnapshot(redis_client)
    await snap.start()
    try:
        own = await pubsub_client_ids(redis_client) - others
        assert len(own) == 1  # o espelho abre uma conexão de assinatura, e só uma
        # Mata só a conexão do espelho: `KILL TYPE pubsub` derrubaria assinantes de outros
        # arquivos de teste, que compartilham o container de escopo de sessão.
        assert await redis_client.execute_command("CLIENT", "KILL", "ID", own.pop()) == 1

        # Republica até o espelho absorver: a reassinatura é provada pelo efeito, sem sleep
        # calibrado no atraso do laço (o que foi publicado durante a queda se perde).
        loop = asyncio.get_running_loop()
        deadline = loop.time() + AWAIT_TIMEOUT_S
        while loop.time() < deadline:
            await publish(redis_client, conn_id=1, tag_id=7, value=7.0)
            if snap.get(7) is not None:
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("espelho não voltou a absorver depois da queda da conexão")

        assert snap.get(7).value == 7.0
    finally:
        await snap.stop()
