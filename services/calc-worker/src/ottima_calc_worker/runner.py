"""Runner de UMA tag calculada: script do usuário na cadência do período (ADR-033).

Mesma semântica do bloco Script do flow-runtime (`ScriptBlock`): o runner é o dono do
`state` — o pool é sem estado, e a cópia-mestre só é substituída em retorno `ok`, então
timeout e exceção nunca deixam o `state` pela metade. Falha mantém o último valor bom
publicado (nunca republica com `ts` novo — isso forjaria um dado que não existe) e o
evento de falha é deduplicado por transição (latch): uma tag de 1 s em falha permanente
publica UM `calc_tag_timeout`/`calc_tag_error`, não um por varredura (ADR-020) — e só
depois de o Redis confirmar a entrega do evento, senão uma queda bem na hora da falha
travaria o latch com o alarme nunca publicado.

A cadência vem de um relógio monotônico próprio, não de `sleep(period)` encadeado: um
ciclo que estoura o período pula para o próximo slot livre em vez de acumular atraso.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Literal

from redis.asyncio import Redis

from ottima_core.bus import (
    CHANNEL_CALC_VALUES,
    CHANNEL_EVENTS,
    KIND_CALC_TAG_ERROR,
    KIND_CALC_TAG_RECOVERED,
    KIND_CALC_TAG_TIMEOUT,
    EventMessage,
    OpcValue,
)
from ottima_core.script_pool import ScriptPool, ScriptResult
from ottima_core.snapshot import ValueSnapshot

from .state import RunnerHealth

logger = logging.getLogger(__name__)


class CalcTagRunner:
    """Uma `asyncio.Task` (`calc-tag-<id>`) por tag calculada; falha e cadência isoladas."""

    def __init__(
        self,
        *,
        tag_id: int,
        code: str,
        period_seconds: int,
        input_tag_ids: Sequence[int],
        pool: ScriptPool,
        snapshot: ValueSnapshot,
        redis_client: Redis,
    ) -> None:
        self._tag_id = tag_id
        self._code = code
        self._period_seconds = period_seconds
        self._period_s = float(period_seconds)
        self._input_tag_ids = tuple(input_tag_ids)
        self._pool = pool
        self._snapshot = snapshot
        self._redis = redis_client
        self._source = f"tag:{tag_id}"
        self._timeout_s = 0.7 * self._period_s  # mesma política do ADR-018 (bloco Script)
        self._state: Any = {}
        self._reported_kind: str | None = None
        self._health = RunnerHealth()
        self._task: asyncio.Task[None] | None = None

    @property
    def restart_key(self) -> tuple[str, int, tuple[int, ...]]:
        """Tudo que exige reiniciar o runner — e perder o `state` — quando muda."""
        return (self._code, self._period_seconds, self._input_tag_ids)

    @property
    def health(self) -> RunnerHealth:
        return self._health

    async def start(self) -> None:
        """Sobe a task de cadência. Idempotente."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name=f"calc-tag-{self._tag_id}")

    async def stop(self) -> None:
        """Cancela a task e espera. Idempotente e nunca levanta: é caminho de desmonte."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Falha ao encerrar a tag calculada %s", self._tag_id)

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            delay = next_tick - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Bug inesperado no ciclo não pode matar a task: uma tag quebrada não pode
                # levar as demais junto (ADR-033 D3 — isolamento por task).
                logger.exception(
                    "Ciclo da tag calculada %s falhou de forma inesperada", self._tag_id
                )

            next_tick += self._period_s
            now = loop.time()
            if next_tick <= now:
                # Overrun: o ciclo (ou os anteriores) consumiu o período inteiro. Reagenda
                # para o próximo slot livre em vez de enfileirar atraso — a cadência nunca
                # acumula backlog.
                self._health = replace(self._health, overrun_count=self._health.overrun_count + 1)
                logger.warning(
                    "Tag calculada %s: ciclo estourou o período de %.1fs",
                    self._tag_id,
                    self._period_s,
                )
                slots_perdidos = int((now - next_tick) // self._period_s) + 1
                next_tick += slots_perdidos * self._period_s

    async def _run_cycle(self) -> None:
        collected = self._collect_inputs()
        if collected is None:
            # Entrada fria: ciclo pulado, nunca substitui por 0.0 nem publica (mesmo
            # portão de cold start do bloco OPC-Read/ScriptBlock).
            return
        values, quality = collected

        result = await self._pool.run(
            code=self._code,
            inputs=values,
            state=self._state,
            n_outputs=1,
            timeout_s=self._timeout_s,
            output_names=("OUT",),
        )

        if result.status == "ok" and not math.isfinite(result.outputs["OUT"]):
            # Não-finito é falha, não valor (mesmo espírito do RF-542 no bloco Fuzzy):
            # nunca publicado, e o `state` não avança.
            result = ScriptResult("error", None, None, "OUT não é um número finito (nan/inf)")

        if result.status != "ok":
            await self._report_failure(result)
            return

        self._state = result.state
        ts = datetime.now(UTC)
        payload = OpcValue(tag_id=self._tag_id, ts=ts, value=result.outputs["OUT"], quality=quality)
        try:
            await self._redis.publish(CHANNEL_CALC_VALUES, payload.model_dump_json())
        except Exception:
            # Falha de transporte, não de execução: o `state` já avançou (o script rodou
            # certo, o problema é só o Redis na hora de publicar). Não pode virar
            # `calc_tag_error` — essa trilha é para falha de EXECUÇÃO (ADR-018) — nem
            # deixar o /health repetir o status do ciclo anterior como se nada tivesse
            # acontecido: registra um `last_status` distinto para o operador enxergar que
            # o dado computado não saiu.
            logger.exception(
                "Falha ao publicar valor da tag calculada %s no canal %s",
                self._tag_id,
                CHANNEL_CALC_VALUES,
            )
            self._health = replace(
                self._health,
                last_status="publish_failed",
                consecutive_failures=self._health.consecutive_failures + 1,
            )
            return
        self._health = replace(
            self._health, last_publish_ts=ts, last_status="ok", consecutive_failures=0
        )

        houve_falha_latchada = self._reported_kind is not None
        if houve_falha_latchada:
            entregue = await self._publish_alarm_event(
                severity="info",
                message=f"Tag calculada {self._tag_id} recuperada após falha",
                kind=KIND_CALC_TAG_RECOVERED,
                payload={"tag_id": self._tag_id},
            )
            if entregue:
                self._reported_kind = None

    def _collect_inputs(self) -> tuple[dict[str, float], int] | None:
        """IN1..INn na ordem de `input_tag_ids`; `None` se alguma entrada nunca publicou.

        Qualidade publicada é a PIOR entre as entradas (0 quando não há nenhuma): uma tag
        calculada que depende de uma leitura incerta nunca pode ser anunciada como boa.
        """
        values: dict[str, float] = {}
        quality = 0
        for position, source_tag_id in enumerate(self._input_tag_ids, start=1):
            tag_value = self._snapshot.get(source_tag_id)
            if tag_value is None:
                return None
            values[f"IN{position}"] = tag_value.value
            quality = max(quality, tag_value.quality)
        return values, quality

    async def _publish_alarm_event(
        self,
        *,
        severity: Literal["alarm", "info"],
        message: str,
        kind: str,
        payload: dict[str, Any],
    ) -> bool:
        """Publica um evento de alarme/recuperação da tag calculada com confirmação local
        de entrega e devolve se ele saiu.

        `publish_event` engole toda falha de publish por contrato — evento é telemetria e
        não pode derrubar um loop de controle (ADR-004/009) — mas para estes eventos
        alarme-críticos isso vira um buraco: é a entrega confirmada que autoriza o latch
        (`_reported_kind`) avançar. Se uma queda do Redis coincidisse com a PRIMEIRA falha
        de uma transição e o latch avançasse do mesmo jeito, o alarme nunca mais seria
        retransmitido (o latch só publica de novo em transição), mesmo com o Redis já
        recuperado. Por isso publica direto — sem passar por `publish_event` — e propaga a
        falha para o chamador decidir se avança o latch ou tenta de novo na próxima
        varredura.
        """
        event = EventMessage(
            ts=datetime.now(UTC),
            severity=severity,
            origin=self._source,
            message=message,
            payload={"kind": kind, **payload},
        )
        try:
            await self._redis.publish(CHANNEL_EVENTS, event.model_dump_json())
        except Exception:
            logger.exception(
                "Falha ao publicar evento de alarme %s da tag calculada %s", kind, self._tag_id
            )
            return False
        return True

    async def _report_failure(self, result: ScriptResult) -> None:
        if result.status == "timeout":
            kind = KIND_CALC_TAG_TIMEOUT
            message = (
                f"Tag calculada {self._tag_id} excedeu o tempo limite de {self._timeout_s:.2f}s"
            )
            payload: dict[str, Any] = {"tag_id": self._tag_id, "timeout_s": self._timeout_s}
        else:
            kind = KIND_CALC_TAG_ERROR
            message = f"Tag calculada {self._tag_id} falhou"
            payload = {"tag_id": self._tag_id, "detail": result.detail}

        self._health = replace(
            self._health,
            last_status=result.status,
            consecutive_failures=self._health.consecutive_failures + 1,
        )

        if kind == self._reported_kind:
            return
        entregue = await self._publish_alarm_event(
            severity="alarm", message=message, kind=kind, payload=payload
        )
        if entregue:
            self._reported_kind = kind
