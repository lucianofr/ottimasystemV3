"""Fixtures compartilhadas dos testes do opc-worker.

O helper de espera (`await_until`) e o assinante de canal (`collecting`) moraram aqui até a
tarefa 0.8; agora vivem em `worker_test_helpers.py` (nome próprio, não `conftest`, para não
colidir com o `flow-runtime/tests/conftest.py` quando as duas suítes rodam num único pytest
— débito 8 do plano F4a). Este arquivo mantém só a fixture do opcsim in-process.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from opcsim import OpcSimServer, free_port

# A suíte roda com --import-mode=importlib, que não põe o diretório dos testes no
# sys.path: sem isto os arquivos de teste não conseguem `import worker_test_helpers`.
_TESTS_DIR = str(Path(__file__).parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)


@pytest.fixture
async def sim() -> AsyncIterator[OpcSimServer]:
    server = OpcSimServer(port=free_port())
    await server.start()
    try:
        yield server
    finally:
        await server.stop()
