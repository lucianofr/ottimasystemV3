"""Helpers compartilhados dos testes do flow-runtime.

Uma versão única da espera por condição para os arquivos de teste deste serviço: sem isto,
cada tarefa da fase acrescentaria a própria cópia no mesmo diretório. O que é específico de
um arquivo de teste continua nele.

As fixtures de infraestrutura (`redis_client`, `db_session`) continuam vindo do `conftest.py`
da raiz do repositório.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

# A suíte roda com --import-mode=importlib, que não põe o diretório dos testes no
# sys.path: sem isto os arquivos de teste não conseguem `from conftest import ...`.
_TESTS_DIR = str(Path(__file__).parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

# Teto das esperas do flow-runtime: o Redis dos testes é local e o laço de reassinatura tem
# freio de 1 s, então não satisfazer a condição em 5 s é falha real, não lentidão.
AWAIT_TIMEOUT_S = 5.0


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
