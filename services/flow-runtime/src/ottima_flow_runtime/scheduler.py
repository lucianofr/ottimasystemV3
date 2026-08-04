"""Laço de varredura de um flow (RF-401/402/404, ADR-004/007/011/024, spec F3 §2.2, §4.2).

Uma FlowTask por flow rodando, cada uma numa task asyncio própria: falha de um flow não
alcança os demais (RF-402). O laço recebe uma `FlowDefinition` pronta — blocos instanciados e
fiação resolvida — e por isso não conhece banco, `flowgraph` nem sessão OPC; quem monta a
definição é o supervisor.

Duas escolhas carregam o aceite da fase ("0,5 s sem jitter > 10%"):

1. **Fronteira absoluta.** A varredura `n` dispara em `t0 + n·Ts`, com `n` inteiro e `t0`
   ancorado no deploy. `sleep(Ts)` acumularia o custo de cada varredura na grade e a deriva
   apareceria como jitter crescente.
2. **Tabela de portas persistente.** Ela sobrevive à varredura, então a semântica do RF-401
   cai sozinha: aresta em ordem normal lê o valor escrito nesta varredura, aresta invertida lê
   o da anterior, e na primeira varredura a invertida lê `null` — que é o cold start (§3.0).
   Nenhum caso especial para nenhuma das três situações.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from redis.asyncio import Redis

from ottima_core.bus import (
    KIND_FLOW_FAILED,
    KIND_FLOW_OVERRUN,
    FlowStatus,
    PortValue,
    channel_flow_status,
    publish_event,
)

from .blocks.base import Block, PortSample

logger = logging.getLogger(__name__)

COLD = PortSample(None, False)
"""Valor de porta que nunca foi escrito desde o deploy (§3.0). Imutável, logo compartilhável."""


class Clock(Protocol):
    """Relógio do laço, injetado para os testes poderem ser exatos em vez de tolerantes."""

    def monotonic(self) -> float: ...

    def now(self) -> datetime: ...

    async def sleep_until(self, deadline_monotonic: float) -> None: ...


class SystemClock:
    """Relógio real.

    A grade vive no **monotônico**: um ajuste de NTP para trás não pode deslocar fronteira
    (a F2 já pagou esse conserto no heartbeat do opc-worker). O `ts` publicado é hora de
    parede porque quem o lê é gente e o banco.
    """

    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep_until(self, deadline_monotonic: float) -> None:
        await asyncio.sleep(max(0.0, deadline_monotonic - time.monotonic()))


@dataclass(frozen=True, slots=True)
class FlowDefinition:
    """O que o laço precisa para varrer: blocos prontos, em ordem, e a fiação entre eles."""

    flow_id: int
    ts_seconds: float
    blocks: tuple[Block, ...]
    """Já em ordem crescente de `exec_order` (ADR-024): a tupla É a ordem de execução."""
    wiring: Mapping[str, Mapping[str, tuple[str, str]]]
    """`wiring[block_id][input_handle] = (source_block_id, source_handle)`."""


class FlowTask:
    """Um flow rodando: estado, grade de varredura e publicação de `flow.status`."""

    def __init__(
        self,
        definition: FlowDefinition,
        *,
        redis_client: Redis,
        clock: Clock | None = None,
    ) -> None:
        self._definition = definition
        self._redis = redis_client
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._state: Literal["running", "stopped", "failed"] = "stopped"
        self._ports: dict[str, dict[str, PortSample]] = {}
        self._staged: FlowDefinition | None = None
        self._task: asyncio.Task[None] | None = None
        self._t0 = 0.0
        self._scan_ms = 0.0
        self._overruns = 0
        self._last_scan_ts: datetime | None = None
        self._overrun_armed = True
        self._reset_ports()

    @property
    def state(self) -> Literal["running", "stopped", "failed"]:
        return self._state

    @property
    def scan_ms(self) -> float:
        return self._scan_ms

    @property
    def overruns(self) -> int:
        return self._overruns

    @property
    def last_scan_ts(self) -> datetime | None:
        return self._last_scan_ts

    async def start(self, *, user: str) -> None:
        """Ancora a grade e sobe a task. Idempotente: deploy em rodando é no-op (RNF-05)."""
        if self._state == "running":
            return
        self._reset_blocks()
        self._reset_ports()
        self._scan_ms = 0.0
        self._overruns = 0
        self._overrun_armed = True
        self._last_scan_ts = None
        self._t0 = self._clock.monotonic()
        self._state = "running"
        logger.info(
            "Flow %s iniciado por %s (Ts=%s s)",
            self._definition.flow_id,
            user,
            self._definition.ts_seconds,
        )
        await self._publish_transition()
        self._task = asyncio.create_task(self._run(), name=f"flow-{self._definition.flow_id}")

    async def stop(self, *, user: str, reason: str) -> None:
        """Encerra a task. Idempotente e nunca levanta: é caminho de desmonte (RNF-05).

        Flow em `failed` não volta a `stopped`: falha é terminal e só deploy manual retoma
        (§2.2-6). Publicar `stopped` aqui apagaria o alarme da tela.
        """
        if self._state != "running":
            return
        self._state = "stopped"
        await self._cancel_task()
        self._reset_blocks()
        logger.info("Flow %s parado por %s (motivo=%s)", self._definition.flow_id, user, reason)
        await self._publish_transition()

    async def fail(self, *, reason: str) -> None:
        """Falha imposta de fora: `comm_failure` derruba os flows da conexão caída (RF-207)."""
        if self._state != "running":
            return
        self._state = "failed"
        await self._cancel_task()
        self._reset_blocks()
        logger.warning("Flow %s em falha (motivo=%s)", self._definition.flow_id, reason)
        await self._publish_transition()
        await self._emit_failed(
            reason=reason,
            message=f"Flow {self._definition.flow_id} parado em falha (motivo: {reason})",
        )

    def stage(self, definition: FlowDefinition) -> None:
        """Guarda a definição nova para o laço adotar na fronteira seguinte.

        Nunca no meio da varredura corrente (ADR-011). Quem monta a definição e preserva o
        estado interno dos blocos por `block_id` é o supervisor.
        """
        self._staged = definition

    async def _run(self) -> None:
        index = 1
        try:
            while True:
                await self._clock.sleep_until(self._t0 + index * self._definition.ts_seconds)
                if self._staged is not None:
                    index = self._adopt_staged(self._staged, index)
                fired_at = self._clock.monotonic()
                fired_ts = self._clock.now()
                await self._scan()
                self._scan_ms = (self._clock.monotonic() - fired_at) * 1000.0
                self._last_scan_ts = fired_ts
                await self._publish_status(ts=fired_ts, ports=self._port_values())
                index = await self._settle_grid(index)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._handle_loop_failure()

    async def _scan(self) -> None:
        """Uma varredura: blocos na ordem da tupla, lendo e escrevendo a tabela de portas."""
        wiring = self._definition.wiring
        for block in self._definition.blocks:
            ports = self._ports[block.block_id]
            inputs: dict[str, PortSample] = {}
            for handle, (source_id, source_handle) in wiring.get(block.block_id, {}).items():
                sample = self._ports[source_id][source_handle]
                inputs[handle] = sample
                # A entrada também vai para a tabela: o canvas desenha os dois lados da
                # aresta (§4.2). Só o dict `inputs` é restrito às portas conectadas.
                ports[handle] = sample
            for handle, sample in (await block.step(inputs)).items():
                ports[handle] = sample

    async def _settle_grid(self, index: int) -> int:
        """Devolve o índice da próxima varredura, pulando as fronteiras perdidas (§2.2-2).

        `overruns` conta **varreduras** que fecharam depois da fronteira seguinte, não
        fronteiras puladas: é a leitura que o aceite "zero overruns" mede (E2E-F3-03). Uma
        varredura de 10×Ts conta 1, não 10.
        """
        ts_seconds = self._definition.ts_seconds
        now = self._clock.monotonic()
        if now <= self._t0 + (index + 1) * ts_seconds:
            self._overrun_armed = True  # varredura no orçamento re-arma o dedupe do evento
            return index + 1

        self._overruns += 1
        if self._overrun_armed:
            self._overrun_armed = False
            await publish_event(
                self._redis,
                severity="warning",
                origin=self._origin,
                message=(
                    f"Varredura do flow {self._definition.flow_id} estourou o tempo de ciclo"
                    f" de {ts_seconds} s ({self._scan_ms:.1f} ms)"
                ),
                kind=KIND_FLOW_OVERRUN,
                payload={
                    "flow_id": self._definition.flow_id,
                    "scan_ms": self._scan_ms,
                    "ts_seconds": ts_seconds,
                    "overruns": self._overruns,
                },
            )
        return self._first_future_index(now, index, ts_seconds)

    def _first_future_index(self, now: float, index: int, ts_seconds: float) -> int:
        """Primeira fronteira da grade não anterior ao relógio — nunca uma fila de compensação.

        O índice é sempre inteiro e a fronteira sempre recalculada como `t0 + n·Ts`: a grade
        não guarda soma nenhuma, então não há onde a deriva se acumular. O `while` corrige o
        arredondamento da divisão (`Ts` de uma casa decimal raramente é exato em binário).
        """
        candidate = max(index + 1, int((now - self._t0) // ts_seconds))
        while self._t0 + candidate * ts_seconds < now:
            candidate += 1
        return candidate

    def _adopt_staged(self, staged: FlowDefinition, index: int) -> int:
        """Troca atômica na fronteira (ADR-011). Devolve o índice corrente da grade vigente."""
        self._staged = None
        previous_ts = self._definition.ts_seconds
        self._definition = staged
        self._carry_ports()
        logger.info("Flow %s adotou a definição staged", staged.flow_id)
        if staged.ts_seconds != previous_ts:
            # Ts novo re-ancora a grade no instante da troca (spec §4.1-4): manter o `t0`
            # antigo faria as fronteiras novas caírem em posições arbitrárias da grade velha.
            self._t0 = self._clock.monotonic()
            return 0
        return index

    def _carry_ports(self) -> None:
        """Tabela da definição nova preservando o valor das portas que sobreviveram.

        Editar o grafo não pode zerar o histórico de quem não mudou: a aresta invertida
        perderia a varredura anterior por causa de uma edição em outro canto do flow. Porta
        nova nasce fria (§3.0); porta que saiu do grafo desaparece da publicação.
        """
        previous = self._ports
        self._reset_ports()
        for block_id, ports in self._ports.items():
            carried = previous.get(block_id, {})
            for port in ports:
                if port in carried:
                    ports[port] = carried[port]

    def _reset_ports(self) -> None:
        """Toda porta declarada — entrada e saída — nasce nula e inválida, nunca 0.0."""
        self._ports = {
            block.block_id: dict.fromkeys((*block.input_ports, *block.output_ports), COLD)
            for block in self._definition.blocks
        }

    def _reset_blocks(self) -> None:
        for block in self._definition.blocks:
            try:
                block.reset()
            except Exception:
                # `stop()` não levanta: bloco com `reset` defeituoso não trava o desmonte.
                logger.exception(
                    "Falha ao zerar o bloco %s do flow %s",
                    block.block_id,
                    self._definition.flow_id,
                )

    def _port_values(self) -> dict[str, dict[str, PortValue]]:
        """Tabela inteira: todas as portas de todos os blocos são o que o canvas desenha."""
        return {
            block_id: {port: PortValue(v=sample.v, ok=sample.ok) for port, sample in ports.items()}
            for block_id, ports in self._ports.items()
        }

    async def _publish_status(
        self, *, ts: datetime, ports: dict[str, dict[str, PortValue]]
    ) -> None:
        status = FlowStatus(
            state=self._state,
            scan_ms=self._scan_ms,
            overruns=self._overruns,
            ts=ts,
            ports=ports,
        )
        try:
            await self._redis.publish(
                channel_flow_status(self._definition.flow_id), status.model_dump_json()
            )
        except Exception:
            # Telemetria não derruba laço de controle (ADR-004/009) — mesma regra que o
            # `publish_event` do bus já aplica aos eventos.
            logger.exception("Falha ao publicar flow.status do flow %s", self._definition.flow_id)

    async def _publish_transition(self) -> None:
        """Transição de estado não tem varredura atrás dela: `ports` vazio é o contrato."""
        await self._publish_status(ts=self._clock.now(), ports={})

    async def _handle_loop_failure(self) -> None:
        """Exceção não tratada: este flow vai a `failed` e a task encerra. Só este (RF-402)."""
        detail = traceback.format_exc()
        logger.error("Flow %s falhou no laço de varredura:\n%s", self._definition.flow_id, detail)
        self._state = "failed"
        await self._publish_transition()
        await self._emit_failed(
            reason="unhandled_exception",
            message=(
                f"Flow {self._definition.flow_id} em falha:"
                " exceção não tratada no laço de varredura"
            ),
            detail=detail,
        )

    async def _emit_failed(self, *, reason: str, message: str, detail: str | None = None) -> None:
        payload: dict[str, object] = {"flow_id": self._definition.flow_id, "reason": reason}
        if detail is not None:
            payload["traceback"] = detail
        await publish_event(
            self._redis,
            severity="alarm",
            origin=self._origin,
            message=message,
            kind=KIND_FLOW_FAILED,
            payload=payload,
        )

    async def _cancel_task(self) -> None:
        task, self._task = self._task, None
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    @property
    def _origin(self) -> str:
        """`origin` de evento de flow (§6.1 filtra por ele); o `user` viaja no payload."""
        return f"flow:{self._definition.flow_id}"
