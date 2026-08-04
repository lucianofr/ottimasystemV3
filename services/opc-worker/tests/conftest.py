"""Helpers compartilhados dos testes do opc-worker.

Uma versão única de cada helper que as tarefas 1.1-2.1 haviam duplicado entre os arquivos
de teste: espera por condição, assinante de canal do barramento e o servidor opcsim
in-process. O que é específico de um arquivo continua nele.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import pytest
from redis.asyncio import Redis

from opcsim import OpcSimServer, free_port

# A suíte roda com --import-mode=importlib, que não põe o diretório dos testes no
# sys.path: sem isto os arquivos de teste não conseguem `from conftest import ...`.
_TESTS_DIR = str(Path(__file__).parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

# Teto generoso porque a espera mais longa da suíte cobre queda de sessão, backoff e
# reconexão contra o opcsim (a checagem de sessão do runtime roda a cada 1 s).
AWAIT_TIMEOUT_S = 20.0
# Teto do SUBSCRIBE: o Redis dos testes é local, não confirmar em 5 s é falha real.
SUBSCRIBE_TIMEOUT_S = 5.0


async def await_until(
    condition: Callable[[], bool], timeout_s: float = AWAIT_TIMEOUT_S, interval: float = 0.02
) -> None:
    """Aguarda a condição virar verdadeira, com polling — evita sleep cego nos testes."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if condition():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"condição não satisfeita em {timeout_s}s")


@asynccontextmanager
async def collecting(redis_client: Redis, channel: str) -> AsyncIterator[list[dict]]:
    """Assinante de teste de um canal; só devolve depois do SUBSCRIBE confirmado."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    received: list[dict] = []
    subscribed = asyncio.Event()

    async def _reader() -> None:
        async for message in pubsub.listen():
            if message["type"] == "subscribe":
                subscribed.set()
            elif message["type"] == "message":
                received.append(json.loads(message["data"]))

    task = asyncio.create_task(_reader(), name=f"test-reader-{channel}")
    try:
        await asyncio.wait_for(subscribed.wait(), timeout=SUBSCRIBE_TIMEOUT_S)
        yield received
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await pubsub.aclose()


@pytest.fixture
async def sim() -> AsyncIterator[OpcSimServer]:
    server = OpcSimServer(port=free_port())
    await server.start()
    try:
        yield server
    finally:
        await server.stop()
