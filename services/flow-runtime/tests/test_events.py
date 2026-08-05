"""Contratos do assinante de canais do barramento do runtime (spec F3 §2.2-8)."""

import asyncio

import pytest
from redis.asyncio import Redis

from ottima_core.bus import CHANNEL_EVENTS
from ottima_flow_runtime.events import ChannelListener
from runtime_test_helpers import AWAIT_TIMEOUT_S


async def _handler(data: str) -> None:
    """Handler vazio: o que está sob teste é a inscrição, não o despacho."""


async def test_falha_ao_assinar_nao_vaza_inscricao_nem_conexao(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SUBSCRIBE que estoura fecha o pubsub: sem vazamento de conexão e inscrição.

    Mesma propriedade que o espelho (`snapshot.py`) e o hub da API já afirmam: o pubsub
    falhou antes de virar `self._pubsub`, onde nem `stop()` o alcançaria — e o laço de
    reassinatura chama `_subscribe` a cada 1 s enquanto o Redis estiver fora.
    """

    async def explode(self: ChannelListener, pubsub) -> None:
        raise TimeoutError("confirmação de inscrição não chegou")

    monkeypatch.setattr(ChannelListener, "_await_confirmation", explode)
    listener = ChannelListener(redis_client, CHANNEL_EVENTS, _handler, name="test-events-listener")
    canais_antes = await redis_client.pubsub_channels()

    with pytest.raises(TimeoutError):
        await listener.start()

    # O `aclose` da guarda é aguardado dentro do `start()`, mas o Redis processa o
    # fechamento da conexão no relógio dele: a prova é a inscrição sumir do servidor.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + AWAIT_TIMEOUT_S
    while loop.time() < deadline:
        if await redis_client.pubsub_channels() == canais_antes:
            break
        await asyncio.sleep(0.02)
    else:
        raise AssertionError("inscrição do assinante ficou pendurada no servidor")

    await listener.stop()  # sem task nem pubsub pendentes, o desmonte é no-op
