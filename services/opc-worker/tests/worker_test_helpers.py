"""Helpers de teste do opc-worker, importados por nome qualificado pelos arquivos de teste.

Nome próprio (não `conftest`) para não colidir com o slot de módulo `conftest` que o
`flow-runtime/tests/conftest.py` também expõe via `sys.path`: um pytest que rode as duas
suítes juntas resolveria `import conftest` (nome nu) para qualquer uma das duas, a depender
da ordem de coleta — débito 8 do plano F4a.

A fixture `sim` continua no `conftest.py`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from functools import partial

from redis.asyncio import Redis

from testkit.await_until import await_until as _await_until

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
