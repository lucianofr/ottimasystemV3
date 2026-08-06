"""Espera por condição com polling — util único do workspace (F4a, débito 7).

Substitui as cinco cópias quase idênticas deste helper que existiam em
`services/flow-runtime/tests/conftest.py`, `services/opc-worker/tests/conftest.py`,
`services/recorder/tests/test_backpressure.py`, `services/recorder/tests/test_pipeline.py`
e `tests/opcsim/tests/test_server.py`. A assinatura aqui é o superset das cinco: aceita
tanto uma `condition` síncrona quanto assíncrona (ou qualquer callable cujo retorno seja
um awaitable).
"""

import asyncio
import inspect
from collections.abc import Awaitable, Callable


async def await_until(
    condition: Callable[[], bool | Awaitable[bool]],
    timeout_s: float = 5.0,
    interval: float = 0.02,
) -> None:
    """Aguarda a condição virar verdadeira, com polling — evita sleep cego nos testes.

    `condition` pode devolver `bool` direto ou um awaitable que resolve para `bool`: cobre
    tanto `lambda: ...` síncrono quanto `async def` chamado sem `await` no ponto de chamada.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        result = condition()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"condição não satisfeita em {timeout_s}s")
