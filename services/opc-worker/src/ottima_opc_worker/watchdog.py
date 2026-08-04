"""Task de watchdog de uma conexão: handshake de life-bit com o PLC (spec F2 §3.1-3.4).

A leitura é explícita, não monitored item: só assim o congelamento é medido
deterministicamente, sem depender de o servidor notificar (ADR-009, RF-206). A task não
conhece o `ConnectionRuntime` — fala com ele por três callbacks, o que evita import
circular e deixa o ciclo testável isolado.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress

from asyncua import Client, ua

from .state import ConnectionConfig, ConnectionSnapshot

logger = logging.getLogger(__name__)

FREEZE_THRESHOLD_S = 10.0
"""Limiar de congelamento, FIXO em produção (ADR-009).

Não é knob de usuário nem entra em `Settings` (spec §10.1): só o período de toggle é
configurável. O parâmetro do construtor existe para os testes não gastarem 10 s por
ensaio.
"""


def _describe(exc: Exception) -> str:
    """Detalhe curto para o payload do evento, no mesmo idioma de `subscriptions.py`.

    Fica aqui, e não em `connection.py`: aquele módulo importa este, o inverso seria ciclo.
    """
    return f"{type(exc).__name__}: {exc}".strip()


class WatchdogTask:
    """Handshake de life-bit com o PLC, por conexão (ADR-009, RF-206).

    Pressupõe `config.has_watchdog`: sem o par de node_ids não existe handshake e o
    runtime nem cria a task (spec §3.5).
    """

    def __init__(
        self,
        config: ConnectionConfig,
        client: Client,
        snapshot: ConnectionSnapshot,
        *,
        on_freeze: Callable[[str], Awaitable[None]],
        on_alive: Callable[[], Awaitable[None]],
        on_hard_failure: Callable[[str], Awaitable[None]],
        freeze_threshold_s: float = FREEZE_THRESHOLD_S,
    ) -> None:
        self._config = config
        self._client = client
        self._snapshot = snapshot
        self._on_freeze = on_freeze
        self._on_alive = on_alive
        self._on_hard_failure = on_hard_failure
        self._freeze_threshold_s = freeze_threshold_s
        self._period_s = config.watchdog_period_ms / 1000
        self._task: asyncio.Task[None] | None = None
        self._last_value: bool | None = None
        # Decurso medido no relógio monotônico, como no heartbeat (tarefa 1.3): ajuste de
        # NTP para trás no servidor não pode adiar a detecção de um PLC parado.
        self._last_transition = 0.0

    async def start(self) -> None:
        """Cria a task do watchdog e retorna já."""
        if self._task is not None and not self._task.done():
            return
        # Sem esta âncora a primeira verificação já acusaria congelamento.
        self._last_transition = time.monotonic()
        self._task = asyncio.create_task(self._loop(), name=f"opc-watchdog-{self._config.id}")

    async def stop(self) -> None:
        """Cancela a task. Idempotente."""
        task, self._task = self._task, None
        if task is None or task.done():
            return
        if task is asyncio.current_task():
            # Reentrância: o callback de falha leva o runtime a derrubar a sessão, que
            # chama este stop() de dentro da própria task. Ela já está encerrando —
            # cancelar-se e se aguardar levantaria RuntimeError.
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _loop(self) -> None:
        # `get_node` já pode falhar: NodeId malformado levanta na hora de parsear. Nenhuma
        # exceção pode escapar daqui sem virar callback — task de watchdog que morre calada
        # deixa `watchdog_alive` congelado e o gate de escrita (2.3) decidindo por um valor
        # que nunca mais muda (ADR-009).
        try:
            read_node = self._client.get_node(self._config.watchdog_read_node_id)
            write_node = self._client.get_node(self._config.watchdog_write_node_id)
        except Exception as exc:
            await self._on_hard_failure(_describe(exc))
            return
        while True:
            await asyncio.sleep(self._period_s)
            try:
                value = bool(await read_node.read_value())
                await self._observe(value)
                # Escrita direta no node: não passa pelo consumidor de `opc.writes` nem
                # pelo gate de escrita, que exige watchdog vivo — pelo gate, o watchdog
                # nunca poderia armar a si mesmo (spec §3.4).
                await write_node.write_value(not value, ua.VariantType.Boolean)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Falha dura de sessão (spec §2.2-2): sem retry interno, quem reconecta é
                # o runtime, com backoff.
                await self._on_hard_failure(_describe(exc))
                return
            if time.monotonic() - self._last_transition > self._freeze_threshold_s:
                logger.warning(
                    "Watchdog da conexão %s sem alternância por mais de %.1fs",
                    self._config.id,
                    self._freeze_threshold_s,
                )
                await self._on_freeze(
                    f"sem alternância do bit de watchdog por mais de "
                    f"{self._freeze_threshold_s:.1f}s"
                )
                return

    async def _observe(self, value: bool) -> None:
        """Registra a transição do bit lido e arma `watchdog_alive` na primeira delas."""
        if value == self._last_value:
            return
        previous, self._last_value = self._last_value, value
        if previous is None:
            # 1º ciclo: não há ciclo anterior com que comparar, então ainda não houve
            # alternância. A sessão zumbi nunca chega ao 2º valor distinto.
            return
        self._last_transition = time.monotonic()
        if self._snapshot.watchdog_alive:
            return
        self._snapshot.watchdog_alive = True
        await self._on_alive()
