"""Task de watchdog de UM flow: handshake de life-bit com o PLC (ADR-009 revisado — RF-206
move do nível de conexão para o nível de flow, porque uma conexão OPC pode ser um gateway
com vários PLCs atrás dela; o watchdog monitora especificamente onde CADA flow escreve o
controle).

A leitura é explícita, não monitored item: só assim o congelamento é medido
deterministicamente, sem depender de o servidor notificar (ADR-009, RF-206). A task não
conhece o `ConnectionRuntime` — fala com ele por três callbacks, o que evita import
circular e deixa o ciclo testável isolado.

Quem inverte o bit é o DCS/PLC: o ottima só ECOA o valor lido (cópia pura, sem NOT) —
`watchdogA := watchdogB`. O PLC faz `watchdogB := NOT(watchdogA)` do lado dele. Um NOT só
de um lado é o que garante a alternância; se os dois lados invertessem, o par convergiria
para um ponto fixo e nunca mais alternaria (trava, dispara falha no 1º ciclo)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress

from asyncua import Client, ua

from .state import ConnectionSnapshot, FlowWatchdogConfig

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
    """Handshake de life-bit com o PLC, por flow (ADR-009 revisado, RF-206).

    Pressupõe um `FlowWatchdogConfig` completo: sem os dois node_ids não há handshake e o
    runtime nem cria a task (mesma regra de coerência do schema, `erro_watchdog_flow`).
    """

    def __init__(
        self,
        config: FlowWatchdogConfig,
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
        self._period_s = config.period_ms / 1000
        self._task: asyncio.Task[None] | None = None
        self._last_value: bool | None = None
        # Decurso medido no relógio monotônico, como no heartbeat (tarefa 1.3): ajuste de
        # NTP para trás no servidor não pode adiar a detecção de um PLC parado.
        self._last_transition = 0.0

    @property
    def config(self) -> FlowWatchdogConfig:
        """Config viva desta task; usada por `ConnectionRuntime` para detectar mudança
        (node_ids ou período) e decidir se reinicia (`FlowWatchdogConfig` é comparável por
        valor, dataclass frozen)."""
        return self._config

    async def start(self) -> None:
        """Cria a task do watchdog e retorna já."""
        if self._task is not None and not self._task.done():
            return
        # Sem esta âncora a primeira verificação já acusaria congelamento.
        self._last_transition = time.monotonic()
        # Chave presente = watchdog registrado (gate de `no_watchdog` em writes.py); o
        # valor só vira True na 1ª alternância observada, em `_observe`.
        self._snapshot.flow_watchdog_alive[self._config.flow_id] = False
        self._task = asyncio.create_task(
            self._loop(), name=f"opc-watchdog-flow-{self._config.flow_id}"
        )

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
        # deixa `flow_watchdog_alive` congelado e o gate de escrita (2.3) decidindo por um
        # valor que nunca mais muda (ADR-009).
        try:
            read_node = self._client.get_node(self._config.read_node_id)
            write_node = self._client.get_node(self._config.write_node_id)
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
                # nunca poderia armar a si mesmo (spec §3.4). Cópia pura do valor lido: o
                # ottima NÃO inverte — quem inverte é o DCS/PLC do outro lado (ver
                # docstring do módulo).
                await write_node.write_value(value, ua.VariantType.Boolean)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Falha dura de sessão (spec §2.2-2): sem retry interno, quem reconecta é
                # o runtime, com backoff.
                await self._on_hard_failure(_describe(exc))
                return
            if time.monotonic() - self._last_transition > self._freeze_threshold_s:
                logger.warning(
                    "Watchdog do flow %s sem alternância por mais de %.1fs",
                    self._config.flow_id,
                    self._freeze_threshold_s,
                )
                await self._on_freeze(
                    f"sem alternância do bit de watchdog por mais de "
                    f"{self._freeze_threshold_s:.1f}s"
                )
                return

    async def _observe(self, value: bool) -> None:
        """Registra a transição do bit lido e arma o watchdog do flow na 1ª delas."""
        if value == self._last_value:
            return
        previous, self._last_value = self._last_value, value
        if previous is None:
            # 1º ciclo: não há ciclo anterior com que comparar, então ainda não houve
            # alternância. A sessão zumbi nunca chega ao 2º valor distinto.
            return
        self._last_transition = time.monotonic()
        if self._snapshot.flow_watchdog_alive.get(self._config.flow_id):
            return
        self._snapshot.flow_watchdog_alive[self._config.flow_id] = True
        await self._on_alive()

