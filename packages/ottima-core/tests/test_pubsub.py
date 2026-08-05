"""Contratos do laço resiliente de pubsub compartilhado entre os consumidores (F4a, tarefa 0.1).

Cobre `ChannelListener` (canal fixo) e `PatternListener` (padrão glob) com o Redis real da
fixture do workspace: cada garantia do laço (confirmação antes do `start()`, reconexão,
handler que quebra, `stop()` idempotente) só se prova batendo no servidor de verdade.
"""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from ottima_core.pubsub import ChannelListener, PatternListener
from testkit.await_until import await_until

AWAIT_TIMEOUT_S = 5.0
CHANNEL = "test.pubsub.channel"
PATTERN = "test.pubsub.pattern.*"


async def _noop(*_args: object) -> None:
    """Handler vazio: o que está sob teste não é o despacho."""


async def pubsub_client_ids(redis_client: Redis) -> set[str]:
    """Ids das conexões em modo pubsub do servidor — isola a conexão do listener sob teste."""
    return {client["id"] for client in await redis_client.client_list(_type="pubsub")}


async def test_channel_listener_entrega_mensagem_do_canal(redis_client: Redis) -> None:
    received: list[str] = []
    listener = ChannelListener(redis_client, CHANNEL, received.append, name="test-channel")
    await listener.start()
    try:
        await redis_client.publish(CHANNEL, "ola")
        await await_until(lambda: received == ["ola"])
    finally:
        await listener.stop()


async def test_pattern_listener_entrega_mensagem_do_padrao(redis_client: Redis) -> None:
    received: list[tuple[str, str]] = []

    async def handler(channel: str, data: str) -> None:
        received.append((channel, data))

    listener = PatternListener(redis_client, PATTERN, handler, name="test-pattern")
    await listener.start()
    try:
        await redis_client.publish("test.pubsub.pattern.42", "ola")
        await await_until(lambda: received == [("test.pubsub.pattern.42", "ola")])
    finally:
        await listener.stop()


async def test_start_so_retorna_apos_confirmacao_sem_corrida(redis_client: Redis) -> None:
    """Publicar logo depois do `start()` não pode perder a mensagem: a inscrição já foi confirmada."""
    received: list[str] = []
    listener = ChannelListener(redis_client, CHANNEL, received.append, name="test-channel")
    await listener.start()
    try:
        assert await redis_client.publish(CHANNEL, "sem-corrida") == 1
        await await_until(lambda: received == ["sem-corrida"])
    finally:
        await listener.stop()


async def test_reconexao_apos_queda_do_redis(redis_client: Redis) -> None:
    """Mata a conexão do assinante; o listener reassina e volta a entregar."""
    received: list[str] = []
    others = await pubsub_client_ids(redis_client)
    listener = ChannelListener(redis_client, CHANNEL, received.append, name="test-channel")
    await listener.start()
    try:
        own = await pubsub_client_ids(redis_client) - others
        assert len(own) == 1  # o listener abre uma conexão de assinatura, e só uma
        assert await redis_client.execute_command("CLIENT", "KILL", "ID", own.pop()) == 1

        loop = asyncio.get_running_loop()
        deadline = loop.time() + AWAIT_TIMEOUT_S
        while loop.time() < deadline:
            await redis_client.publish(CHANNEL, "depois-da-queda")
            if received:
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("listener não voltou a entregar depois da queda da conexão")
        assert received[-1] == "depois-da-queda"
    finally:
        await listener.stop()


async def test_excecao_do_handler_nao_mata_o_laco(redis_client: Redis) -> None:
    """Handler que levanta exceção não derruba a escuta: a mensagem seguinte ainda chega."""
    calls: list[str] = []

    async def flaky_handler(data: str) -> None:
        calls.append(data)
        if data == "explode":
            raise RuntimeError("handler ruim")

    listener = ChannelListener(redis_client, CHANNEL, flaky_handler, name="test-channel")
    await listener.start()
    try:
        await redis_client.publish(CHANNEL, "explode")
        await await_until(lambda: "explode" in calls)
        await redis_client.publish(CHANNEL, "depois")
        await await_until(lambda: calls == ["explode", "depois"])
    finally:
        await listener.stop()


async def test_stop_e_idempotente(redis_client: Redis) -> None:
    listener = ChannelListener(redis_client, CHANNEL, _noop, name="test-channel")
    await listener.start()
    assert await redis_client.publish(CHANNEL, "antes") == 1

    await listener.stop()
    await listener.stop()  # segunda chamada não levanta

    # Zero destinatários: a inscrição saiu do servidor, a task encerrou.
    assert await redis_client.publish(CHANNEL, "depois") == 0
