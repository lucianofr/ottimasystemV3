"""Bloco Sensor virtual: infere uma variável por um modelo treinado (RF-582/583/584, ADR-046).

Entradas `IN1..INn` (posicionais: `INk` é a k-ésima entrada do treino), saída única `out`. O
modelo não está na config do grafo; quem o entrega é o runtime (vínculo em tabela, spec §7.4).

**Slot** = modelo + buffer de amostras no período daquele modelo + divisor
`n = period_s / Ts`. O bloco tem um slot para o modelo em uso e, durante uma troca, um para o
candidato; cada um empurra a amostra e avalia nas varreduras `i % n == 0` (contador do bloco).

**Valor da saída (spec §5.4 ★):** `None` só enquanto o modelo em uso nunca calculou nada desde
a instanciação (ou o `reset`). Depois disso, avaliação sem valor mantém o último calculado com
qualidade BAD: `None` no meio da operação travaria o MPC a jusante no portão frio
(`has_cold_input`) em vez de levá-lo ao tratamento de entrada inválida.

**Troca (spec §5.6):** `set_candidate` só enfileira; o `step` aplica no início da varredura
seguinte, porque ele tem `await` (executor, `persist`) e o comando chega por outro caminho. O
candidato é promovido quando calcula valor com qualidade >= a da saída atual; vencido o prazo,
é descartado. PLS avalia inline; ESN e LSTM no executor (ADR-004).
"""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from datetime import datetime

from ottima_core.bus import (
    KIND_SOFT_SENSOR_EXTRAPOLATING,
    KIND_SOFT_SENSOR_MODEL_ACTIVATED,
    KIND_SOFT_SENSOR_MODEL_MISSING,
    KIND_SOFT_SENSOR_MODEL_REJECTED,
)
from ottima_core.signal import Quality
from ottima_core.softsensor import Evaluation, LoadedModel, SampleBuffer, evaluate

from .base import Block, Signal

logger = logging.getLogger(__name__)

OUTPUT_PORTS = ("out",)
MIN_PROMOTION_TIMEOUT_S = 60.0
_ORIGIN = "flow-runtime"


@dataclass(frozen=True)
class BindingUpdate:
    """O que o runtime grava no vínculo bloco -> modelo (spec §7.4)."""

    active_model_id: int | None
    candidate_model_id: int | None
    reset_desired_to_active: bool = False


@dataclass(eq=False)
class _Slot:
    model: LoadedModel
    buffer: SampleBuffer
    every: int  # varreduras por passo de modelo
    evaluation: Evaluation | None = None
    value: float | None = None
    age: int = 0  # varreduras desde que virou candidato


class SoftSensorBlock(Block):
    def __init__(
        self,
        block_id: str,
        *,
        n_inputs: int,
        ts_seconds: float,
        model: LoadedModel | None,
        prewarm: SampleBuffer | None,
        missing_reason: str | None,
        emit_event: Callable[..., Awaitable[None]],
        persist: Callable[[BindingUpdate], Awaitable[None]],
    ) -> None:
        super().__init__(block_id)
        self._inputs = tuple(f"IN{k}" for k in range(1, n_inputs + 1))
        self._n_inputs = n_inputs
        self._ts = ts_seconds
        self._emit = emit_event
        self._persist = persist
        self._missing_reason = missing_reason or "no_model"
        self._active = self._slot(model, prewarm) if model is not None else None
        self._candidate: _Slot | None = None
        self._pending: _Slot | None = None
        self._writes: set[asyncio.Task[None]] = set()  # referência forte até terminar
        self._scan = 0
        self._missing_reported = False
        self._extrapolating = False

    @property
    def input_ports(self) -> tuple[str, ...]:
        return self._inputs

    @property
    def output_ports(self) -> tuple[str, ...]:
        return OUTPUT_PORTS

    @property
    def active_model_id(self) -> int | None:
        return self._active.model.model_id if self._active else None

    @property
    def candidate_model_id(self) -> int | None:
        return self._candidate.model.model_id if self._candidate else None

    @property
    def intended_model_id(self) -> int | None:
        """O modelo que o bloco vai acabar rodando se nada falhar: o pedido enfileirado, o
        candidato aquecendo ou o em uso (a rejeição de um pedido devolve o desejado a ele)."""
        slot = self._pending or self._candidate or self._active
        return slot.model.model_id if slot else None

    @property
    def active_period_s(self) -> float | None:
        return self._active.model.meta.period_s if self._active else None

    def active_buffer_copy(self) -> SampleBuffer | None:
        return self._active.buffer.copy() if self._active else None

    def set_candidate(self, model: LoadedModel, buffer: SampleBuffer | None) -> None:
        # Slot montado aqui (período inválido levanta no pedido); aplicado no próximo `step`.
        self._pending = self._slot(model, buffer)  # o último pedido vence

    def reset(self) -> None:
        self._scan = 0
        if self._active is not None:
            self._active.value = None
            self._active.evaluation = None

    async def step(
        self, inputs: Mapping[str, Signal], *, ts: datetime | None = None
    ) -> dict[str, Signal]:
        if self._pending is not None:
            slot, self._pending = self._pending, None
            if self._active is None:
                await self._promote(slot)  # sem modelo em uso: assume na hora (§5.6-5)
            else:
                self._candidate = slot

        samples = [inputs.get(port) for port in self._inputs]
        values = [None if s is None else s.v for s in samples]
        worst = min(Quality.BAD if s is None or s.v is None else s.quality for s in samples)

        active = self._active
        if active is None:
            if not self._missing_reported:
                self._missing_reported = True
                await self._event(
                    "warning",
                    KIND_SOFT_SENSOR_MODEL_MISSING,
                    f"Sensor virtual '{self.block_id}': sem modelo ({self._missing_reason})",
                    reason=self._missing_reason,
                )
            self._scan += 1
            return {"out": Signal(None)}

        if await self._advance(active, values, worst):
            await self._report_extrapolation(active)
        current = self._quality(active, worst)

        candidate = self._candidate
        if candidate is not None:
            if candidate.age >= self._deadline_scans(candidate):
                await self._reject(candidate, active)
            else:
                candidate.age += 1
                stepped = await self._advance(candidate, values, worst)
                ev = candidate.evaluation
                if stepped and ev is not None and ev.value is not None and ev.quality >= current:
                    await self._promote(candidate)
                    await self._report_extrapolation(candidate)

        self._scan += 1
        active = self._active
        return {"out": Signal(active.value, quality=self._quality(active, worst))}

    def _slot(self, model: LoadedModel, buffer: SampleBuffer | None) -> _Slot:
        every = round(model.meta.period_s / self._ts)  # múltiplo inteiro: conferido no deploy
        if every < 1:
            raise ValueError(
                f"período do modelo {model.meta.period_s} s menor que o Ts {self._ts} s"
            )
        return _Slot(model, buffer if buffer is not None else SampleBuffer(self._n_inputs), every)

    def _deadline_scans(self, slot: _Slot) -> int:
        meta = slot.model.meta
        timeout_s = max(2 * meta.warmup_steps * meta.period_s, MIN_PROMOTION_TIMEOUT_S)
        return math.ceil(timeout_s / self._ts - 1e-9)  # 1e-9: 60/0.1 não pode virar 601

    @staticmethod
    def _quality(slot: _Slot, worst_port: Quality) -> Quality:
        if slot.evaluation is None:
            return Quality.BAD
        return min(slot.evaluation.quality, worst_port)

    async def _advance(self, slot: _Slot, values: list, quality: Quality) -> bool:
        """Passo de modelo do slot nesta varredura, se for a vez dele."""
        if self._scan % slot.every:
            return False
        slot.buffer.push(values, quality)
        if slot.model.meta.method == "pls":
            ev = evaluate(slot.model, slot.buffer)
        else:
            loop = asyncio.get_running_loop()
            ev = await loop.run_in_executor(None, evaluate, slot.model, slot.buffer.copy())
        slot.evaluation = ev
        if ev.value is not None:
            slot.value = ev.value
        return True

    async def _promote(self, slot: _Slot) -> None:
        previous = self.active_model_id
        self._active, self._candidate = slot, None  # estado trocado antes de qualquer await
        model_id = slot.model.model_id
        await self._durable(
            BindingUpdate(active_model_id=model_id, candidate_model_id=None),
            self._event(
                "info",
                KIND_SOFT_SENSOR_MODEL_ACTIVATED,
                f"Sensor virtual '{self.block_id}': modelo {model_id} em uso (antes {previous})",
                model_id=model_id,
                previous_model_id=previous,
            ),
        )

    async def _reject(self, candidate: _Slot, active: _Slot) -> None:
        self._candidate = None
        reason = candidate.evaluation.reason if candidate.evaluation else "incomplete"
        model_id = candidate.model.model_id
        await self._durable(
            BindingUpdate(
                active_model_id=active.model.model_id,
                candidate_model_id=None,
                reset_desired_to_active=True,
            ),
            self._event(
                "warning",
                KIND_SOFT_SENSOR_MODEL_REJECTED,
                f"Sensor virtual '{self.block_id}': modelo {model_id} descartado ({reason})",
                model_id=model_id,
                reason=reason,
            ),
        )

    async def _durable(self, update: BindingUpdate, event: Coroutine[None, None, None]) -> None:
        """Grava o vínculo e emite o evento numa task própria, protegida do cancelamento.

        `stop`/`fail` cancelam a varredura no meio do `await`; a troca em memória já foi feita,
        e perder a gravação deixaria `desired_model_id` num modelo rejeitado, que o próximo
        deploy carregaria sem validar (§5.6-5). O `CancelledError` segue para quem cancelou.
        """

        async def write() -> None:
            await self._save(update)
            await event

        task = asyncio.create_task(write())
        self._writes.add(task)
        task.add_done_callback(self._writes.discard)
        await asyncio.shield(task)

    async def _report_extrapolation(self, slot: _Slot) -> None:
        now = slot.evaluation is not None and slot.evaluation.reason == "extrapolating"
        if now == self._extrapolating:
            return
        self._extrapolating = now
        estado = "fora da faixa de treino" if now else "de volta à faixa de treino"
        await self._event(
            "warning",
            KIND_SOFT_SENSOR_EXTRAPOLATING,
            f"Sensor virtual '{self.block_id}': entradas {estado}",
            model_id=slot.model.model_id,
            active=now,
        )

    async def _save(self, update: BindingUpdate) -> None:
        try:
            await self._persist(update)
        except Exception:
            logger.exception("Sensor virtual '%s': falha ao gravar o vínculo", self.block_id)

    async def _event(self, severity: str, kind: str, message: str, **payload: object) -> None:
        try:
            await self._emit(
                severity=severity,
                origin=_ORIGIN,
                message=message,
                kind=kind,
                payload={"block_id": self.block_id, **payload},
            )
        except Exception:
            logger.exception("Sensor virtual '%s': falha ao emitir %s", self.block_id, kind)
