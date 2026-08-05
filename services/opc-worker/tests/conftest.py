"""Helpers compartilhados dos testes do opc-worker.

Uma versão única de cada helper que as tarefas 1.1-2.1 haviam duplicado entre os arquivos
de teste: espera por condição, assinante de canal do barramento e o servidor opcsim
in-process. O que é específico de um arquivo continua nele.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from functools import partial
from pathlib import Path

import pytest
from redis.asyncio import Redis

from opcsim import OpcSimServer, free_port
from testkit.await_until import await_until as _await_until

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


await_until = partial(_await_until, timeout_s=AWAIT_TIMEOUT_S)


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
