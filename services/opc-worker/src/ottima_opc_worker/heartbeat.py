"""Heartbeat de valor de uma conexão: report-by-exception + republicação (spec F2 §2.2-6).

Pertence ao runtime da conexão, não à sessão: continua batendo com a conexão em falha,
publicando `quality=2` para que a UI distinga "sem dado" de "dado ruim".
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import replace

from redis.asyncio import Redis

from .polling import QUALITY_BAD, publish_value
from .state import ConnectionConfig, ConnectionSnapshot, ConnectionState, TagConfig

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 10.0  # spec §2.2-6; constante de código, não knob de env
TICK_DIVISOR = 10  # o loop acorda HEARTBEAT_INTERVAL_S / TICK_DIVISOR


class ValueHeartbeat:
    """Republicação periódica de valor por conexão (report-by-exception + heartbeat)."""

    def __init__(
        self,
        config: ConnectionConfig,
        redis_client: Redis,
        snapshot: ConnectionSnapshot,
        *,
        interval_s: float = HEARTBEAT_INTERVAL_S,
    ) -> None:
        self._config = config
        self._redis = redis_client
        self._snapshot = snapshot
        self._interval_s = interval_s
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Cria a task do heartbeat e retorna já."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name=f"opc-heartbeat-{self._config.id}")

    async def stop(self) -> None:
        """Cancela a task. Idempotente."""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def burst_bad(self) -> None:
        """Rajada imediata de quality=2 para TODAS as tags com série da conexão.

        Chamada na transição para `failed` (a ligação é da tarefa 2.2). Sem dedupe: duas
        chamadas publicam duas rajadas — o dado cíclico quer o ponto.
        """
        for tag in self._series_tags():
            await self._republish(tag, quality=QUALITY_BAD)

    def apply_tags(self, tags: tuple[TagConfig, ...]) -> None:
        """Acompanha a reconciliação de tags do runtime (tarefa 1.4)."""
        self._config = replace(self._config, tags=tags)

    async def _loop(self) -> None:
        tick = self._interval_s / TICK_DIVISOR
        while True:
            await asyncio.sleep(tick)
            try:
                await self._beat()
            except Exception:
                # Uma batida ruim não pode matar a série inteira; a próxima é em 1 s.
                logger.exception("Erro na batida do heartbeat da conexão %s", self._config.id)

    async def _beat(self) -> None:
        # Decurso medido no relógio monotônico: ajuste de NTP para trás no servidor
        # industrial não pode travar a republicação (o `ts` do payload segue sendo parede).
        now = time.monotonic()
        session_up = self._snapshot.state is ConnectionState.UP
        for tag in self._series_tags():
            last = self._snapshot.last_values.get(tag.id)
            # Tag que nunca publicou conta como publicada há muito tempo: entra na batida.
            if last is not None and now - last.published_monotonic < self._interval_s:
                continue
            # Fora de `up` o dado é ruim por definição; sem último valor não há qualidade
            # boa a repetir.
            quality = last.quality if session_up and last is not None else QUALITY_BAD
            await self._republish(tag, quality=quality)

    async def _republish(self, tag: TagConfig, *, quality: int) -> None:
        """Publica o último valor conhecido (ou 0.0) com `ts` novo, pelo ponto único."""
        last = self._snapshot.last_values.get(tag.id)
        await publish_value(
            self._redis,
            self._config.id,
            self._snapshot,
            tag_id=tag.id,
            value=last.value if last is not None else 0.0,
            quality=quality,
        )

    def _series_tags(self) -> Iterator[TagConfig]:
        """Tags com série própria em `opc.values`.

        Tag `r` sempre: a série dela é obrigatória por cadastro, e uma que nunca publicou
        precisa aparecer como bad em vez de emudecer. Tag `w` só depois de uma leitura boa —
        antes disso o node pode ser write-only (fora do ciclo, `polling.py`), e publicar
        0.0 sob bad inventaria série inexistente: quem consome mostraria "ruim 0" onde o
        honesto é "sem dado".
        """
        return (
            tag
            for tag in self._config.tags
            if tag.direction == "r" or tag.id in self._snapshot.last_values
        )
