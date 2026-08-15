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

def _describe(exc: Exception) -> str:
    """Detalhe curto para o payload do evento, no mesmo idioma de `polling.py`.

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
        freeze_threshold_s: float | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._snapshot = snapshot
        self._on_freeze = on_freeze
        self._on_alive = on_alive
        self._on_hard_failure = on_hard_failure
        # Limiar de congelamento configurável por flow (`watchdog_timeout_s`, RF-206); o
        # parâmetro existe para os testes não gastarem 10 s por ensaio.
        self._freeze_threshold_s = (
            config.timeout_s if freeze_threshold_s is None else freeze_threshold_s
        )
        self._period_s = config.period_ms / 1000
        # Leitura/escrita travada não pode congelar a task para sempre (achado do E2E: uma
        # sessão zumbi deixava o `read_value` pendurado e o watchdog morria calado, com a
        # chave de `flow_watchdog_alive` presa em False). Timeout generoso — escrita/leitura
        # que não completa nele é sessão morta, e o `on_hard_failure` reconecta e rearma.
        self._io_timeout_s = max(10.0, 3 * self._period_s)
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

    @property
    def is_dead(self) -> bool:
        """Task que morreu (hard failure/freeze) sem ser removida: o reconcile a reinicia
        na próxima reconciliação, em vez de deixar o flow preso em `watchdog_dead`."""
        return self._task is None or self._task.done()

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
        # Amostragem 8× mais rápida que a escrita (Nyquist, achado do gate E2E): quando
        # OUTROS escritores compartilham o mesmo par de nós — vários flows apontados ao
        # mesmo par, ou um PLC que inverte mais rápido que o período — o bit alterna a
        # N×/período e uma leitura por período veria sempre o MESMO valor (aliasing),
        # acusando congelamento de um handshake vivo. 8× cobre até 4 escritores. A ESCRITA
        # segue na cadência configurada: ela é o contrato de handshake com o PLC
        # (`watchdog_period_ms`), a leitura não. Piso de 50 ms para não virar poll cego.
        sample_s = max(0.05, self._period_s / 8)
        proxima_escrita = time.monotonic()
        while True:
            await asyncio.sleep(sample_s)
            try:
                value = bool(
                    await asyncio.wait_for(read_node.read_value(), timeout=self._io_timeout_s)
                )
                await self._observe(value)
                # Escrita direta no node: não passa pelo consumidor de `opc.writes` nem
                # pelo gate de escrita, que exige watchdog vivo — pelo gate, o watchdog
                # nunca poderia armar a si mesmo (spec §3.4). Cópia pura do valor lido: o
                # ottima NÃO inverte — quem inverte é o DCS/PLC do outro lado (ver
                # docstring do módulo).
                agora = time.monotonic()
                if agora >= proxima_escrita:
                    proxima_escrita = agora + self._period_s
                    await asyncio.wait_for(
                        write_node.write_value(value, ua.VariantType.Boolean),
                        timeout=self._io_timeout_s,
                    )
            except asyncio.CancelledError:
                raise
            except TimeoutError as exc:
                # Sessão zumbi: a leitura/escrita não completa; sem isso a task ficaria
                # pendurada para sempre e o flow preso em `watchdog_dead`.
                await self._on_hard_failure(
                    f"leitura/escrita do watchdog sem resposta em {self._io_timeout_s:.0f}s: {exc}"
                )
                return
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

