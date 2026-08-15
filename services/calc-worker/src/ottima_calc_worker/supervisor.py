"""Supervisor do calc-worker: reconciliação banco -> `CalcTagRunner` (ADR-033).

Fonte da verdade é o banco, lido via `ottima-core`. O supervisor compara um watermark
barato (contagens + `max(updated_at)` do projeto ativo) com o último visto e, quando muda,
carrega a configuração completa das tags calculadas e ajusta os runners: cria, derruba ou
reinicia. O canal `events` só serve de dica para antecipar a passada; perda de mensagem é
inofensiva porque o poll de 10 s corrige (mesmo contrato do opc-worker, ADR-017).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime

from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_CALC_TAG_CREATED,
    KIND_CALC_TAG_DELETED,
    KIND_CALC_TAG_UPDATED,
    KIND_PROJECT_ACTIVATED,
    KIND_TAG_DELETED,
    KIND_TAG_UPDATED,
    EventMessage,
)
from ottima_core.models import CalculatedTag, CalculatedTagInput, Project, Tag
from ottima_core.script_pool import ScriptPool
from ottima_core.snapshot import ValueSnapshot

from .runner import CalcTagRunner
from .state import RunnerConfig

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 10.0  # constante de código, não knob de env — mesmo padrão do opc-worker
# Espera antes de reassinar o canal de eventos depois de uma queda do Redis.
HINT_RETRY_S = 1.0

# Kinds de auditoria (API + opc-worker) que antecipam a reconciliação.
HINT_KINDS: frozenset[str] = frozenset(
    {
        KIND_PROJECT_ACTIVATED,
        KIND_CALC_TAG_CREATED,
        KIND_CALC_TAG_UPDATED,
        KIND_CALC_TAG_DELETED,
        KIND_TAG_UPDATED,
        KIND_TAG_DELETED,
    }
)


@dataclass(frozen=True, slots=True)
class Watermark:
    """Assinatura barata da configuração de tags calculadas do projeto ativo."""

    project_id: int | None
    calc_tags_count: int
    calc_tags_max_updated_at: datetime | None
    calc_tag_inputs_signature: str
    tags_count: int
    tags_max_updated_at: datetime | None


_NO_PROJECT = Watermark(
    project_id=None,
    calc_tags_count=0,
    calc_tags_max_updated_at=None,
    calc_tag_inputs_signature="",
    tags_count=0,
    tags_max_updated_at=None,
)


async def read_watermark(session: AsyncSession) -> Watermark:
    """Assinatura do projeto ativo por agregados: nunca carrega linhas de configuração."""
    project_id = await session.scalar(select(Project.id).where(Project.is_active))
    if project_id is None:
        return _NO_PROJECT

    calc_tags_count, calc_tags_max = (
        await session.execute(
            select(func.count(), func.max(CalculatedTag.updated_at))
            .select_from(CalculatedTag)
            .join(Tag, Tag.id == CalculatedTag.tag_id)
            .where(Tag.project_id == project_id)
        )
    ).one()
    # Assinatura de CONTEÚDO, não contagem: `position` É o índice do `IN`, então trocar IN1
    # por IN2 muda o cálculo sem mudar a contagem nem tocar `calculated_tags.updated_at`
    # (as linhas de entrada são recriadas inteiras, e a tabela não tem `updated_at`). Com
    # contagem, uma reordenação passaria batida e o runner seguiria com a ordem velha.
    # Barato: no máximo 8 linhas por tag calculada.
    calc_tag_inputs_signature = await session.scalar(
        select(
            func.md5(
                func.coalesce(
                    func.string_agg(
                        func.concat_ws(
                            ":",
                            CalculatedTagInput.calc_tag_id,
                            CalculatedTagInput.position,
                            CalculatedTagInput.source_tag_id,
                        ),
                        aggregate_order_by(
                            literal(","),
                            CalculatedTagInput.calc_tag_id,
                            CalculatedTagInput.position,
                        ),
                    ),
                    "",
                )
            )
        )
        .select_from(CalculatedTagInput)
        .join(Tag, Tag.id == CalculatedTagInput.calc_tag_id)
        .where(Tag.project_id == project_id)
    )
    tags_count, tags_max = (
        await session.execute(
            select(func.count(), func.max(Tag.updated_at)).where(Tag.project_id == project_id)
        )
    ).one()
    return Watermark(
        project_id=project_id,
        calc_tags_count=calc_tags_count,
        calc_tags_max_updated_at=calc_tags_max,
        calc_tag_inputs_signature=calc_tag_inputs_signature or "",
        tags_count=tags_count,
        tags_max_updated_at=tags_max,
    )


async def load_active_configuration(session: AsyncSession) -> tuple[RunnerConfig, ...]:
    """Configuração completa das tags calculadas do projeto ativo, numa só transação.

    `input_tag_ids` sai ordenado por `position`: sem ordem estável o `restart_key` mudaria
    sozinho e o diff reiniciaria o runner a cada passada.
    """
    project_id = await session.scalar(select(Project.id).where(Project.is_active))
    if project_id is None:
        return ()
    rows = (
        await session.execute(
            select(CalculatedTag.tag_id, CalculatedTag.code, CalculatedTag.period_seconds)
            .join(Tag, Tag.id == CalculatedTag.tag_id)
            .where(Tag.project_id == project_id)
            .order_by(CalculatedTag.tag_id)
        )
    ).all()
    if not rows:
        return ()

    inputs: dict[int, list[int]] = {tag_id: [] for tag_id, _, _ in rows}
    input_rows = await session.execute(
        select(CalculatedTagInput.calc_tag_id, CalculatedTagInput.source_tag_id)
        .where(CalculatedTagInput.calc_tag_id.in_(list(inputs)))
        .order_by(CalculatedTagInput.calc_tag_id, CalculatedTagInput.position)
    )
    for calc_tag_id, source_tag_id in input_rows:
        inputs[calc_tag_id].append(source_tag_id)

    return tuple(
        RunnerConfig(
            tag_id=tag_id,
            code=code,
            period_seconds=period_seconds,
            input_tag_ids=tuple(inputs[tag_id]),
        )
        for tag_id, code, period_seconds in rows
    )


class Supervisor:
    """Mantém os `CalcTagRunner` alinhados com as tags calculadas do projeto ativo."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        *,
        pool: ScriptPool,
        snapshot: ValueSnapshot,
        poll_interval_s: float = POLL_INTERVAL_S,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._pool = pool
        self._snapshot = snapshot
        self._poll_interval_s = poll_interval_s
        self._runners: dict[int, CalcTagRunner] = {}
        # None antes da primeira passada: nenhum Watermark é igual a None, então o
        # primeiro ciclo sempre reconcilia.
        self._watermark: Watermark | None = None
        self._hint = asyncio.Event()
        # Nunca dois reconciles em voo: dica e poll competem pelo mesmo estado.
        self._lock = asyncio.Lock()
        self._poll_task: asyncio.Task[None] | None = None
        self._hint_task: asyncio.Task[None] | None = None
        self._pubsub: PubSub | None = None

    @property
    def runners(self) -> Mapping[int, CalcTagRunner]:
        """Runners vivos por `tag_id`; o `/health` monta o corpo por tag daqui."""
        return self._runners

    def script_pool_stats(self) -> dict:
        return self._pool.stats()

    async def start(self) -> None:
        """Sobe o assinante de `events` e o loop de poll. Idempotente."""
        if self._poll_task is not None:
            return
        # SUBSCRIBE antes de retornar: uma dica publicada logo após o start() não se perde.
        await self._subscribe_events()
        self._hint_task = asyncio.create_task(self._listen_hints(), name="calc-supervisor-hints")
        self._poll_task = asyncio.create_task(self._poll_loop(), name="calc-supervisor-poll")

    async def stop(self) -> None:
        """Derruba assinante, loop e todos os runners. Idempotente.

        Cada desmonte é isolado: falha em um runner não pode abortar o desmonte dos
        outros, senão uma tag quebrada deixaria as demais `calc-tag-*` vazando.
        """
        await _cancel(self._poll_task, "loop de poll do supervisor")
        await _cancel(self._hint_task, "assinante do canal de eventos")
        self._poll_task = None
        self._hint_task = None
        await self._drop_pubsub()
        tag_ids = list(self._runners)
        resultados = await asyncio.gather(
            *(self._teardown(tag_id) for tag_id in tag_ids),
            return_exceptions=True,
        )
        _log_teardown_results(tag_ids, resultados)
        self._watermark = None

    async def reconcile(self) -> None:
        """Uma passada de reconciliação, independente do watermark. Nunca levanta."""
        await self._pass(force=True)

    async def _poll_loop(self) -> None:
        while True:
            await self._pass(force=False)
            # A dica encurta a espera; o timeout é o poll de 10 s.
            with suppress(TimeoutError):
                await asyncio.wait_for(self._hint.wait(), timeout=self._poll_interval_s)
            self._hint.clear()

    async def _pass(self, *, force: bool) -> None:
        """Lê watermark, carrega config se mudou e aplica o diff. Absorve toda exceção."""
        async with self._lock:
            try:
                async with self._session_factory() as session:
                    watermark = await read_watermark(session)
                    if not force and watermark == self._watermark:
                        return
                    configs = await load_active_configuration(session)
                await self._apply(configs)
            except Exception:
                # Watermark não avança: a próxima passada tenta de novo.
                logger.exception("Falha na reconciliação do calc-worker; watermark preservado")
                return
            self._watermark = watermark

    async def _apply(self, configs: tuple[RunnerConfig, ...]) -> None:
        wanted = {config.tag_id: config for config in configs}
        for tag_id in [tag_id for tag_id in self._runners if tag_id not in wanted]:
            await self._teardown(tag_id)
        for tag_id, config in wanted.items():
            runner = self._runners.get(tag_id)
            if runner is None:
                await self._spawn(config)
                continue
            if runner.restart_key != config.restart_key:
                # Código, período ou entradas mudaram: reinicia do zero. O `state` do
                # script se perde de propósito — mesma regra do stop de um flow limpando
                # o state do bloco Script (`ScriptBlock.reset()`).
                await self._teardown(tag_id)
                await self._spawn(config)

    async def _spawn(self, config: RunnerConfig) -> None:
        runner = CalcTagRunner(
            tag_id=config.tag_id,
            code=config.code,
            period_seconds=config.period_seconds,
            input_tag_ids=config.input_tag_ids,
            pool=self._pool,
            snapshot=self._snapshot,
            redis_client=self._redis,
        )
        self._runners[config.tag_id] = runner
        await runner.start()
        logger.info(
            "Tag calculada %s supervisionada (período %ds)", config.tag_id, config.period_seconds
        )

    async def _teardown(self, tag_id: int) -> None:
        runner = self._runners.pop(tag_id, None)
        if runner is None:
            return
        await runner.stop()
        logger.info("Tag calculada %s desmontada", tag_id)

    async def _listen_hints(self) -> None:
        """Traduz evento de auditoria em sinal; o reconcile é sempre do loop de poll.

        Perder uma dica é inofensivo por contrato (o poll corrige), mas a morte silenciosa
        desta task não é: o sistema degradaria para o poll de 10 s sem ninguém saber. Por
        isso o laço reassina o canal depois de qualquer queda do Redis.
        """
        while True:
            try:
                pubsub = self._pubsub
                if pubsub is None:
                    pubsub = await self._subscribe_events()
                async for message in pubsub.listen():
                    if message["type"] == "message" and _is_hint(message["data"]):
                        self._hint.set()
                logger.warning(
                    "Escuta do canal %s terminou sem erro; reassinando em %.1fs",
                    CHANNEL_EVENTS,
                    HINT_RETRY_S,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Assinante do canal %s caiu; reassinando em %.1fs",
                    CHANNEL_EVENTS,
                    HINT_RETRY_S,
                    exc_info=True,
                )
            # O freio vale para TODO recomeço, não só para o caminho de exceção: sem ele
            # um listen() que retorna na hora vira rajada de reassinatura queimando CPU.
            await self._drop_pubsub()
            await asyncio.sleep(HINT_RETRY_S)

    async def _subscribe_events(self) -> PubSub:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(CHANNEL_EVENTS)
        self._pubsub = pubsub
        return pubsub

    async def _drop_pubsub(self) -> None:
        """Fecha o assinante atual sem nunca levantar: é caminho de desmonte."""
        pubsub, self._pubsub = self._pubsub, None
        if pubsub is None:
            return
        try:
            await pubsub.aclose()
        except Exception:
            logger.warning("Falha ao fechar o assinante do canal %s", CHANNEL_EVENTS, exc_info=True)


def _is_hint(data: str) -> bool:
    try:
        kind = EventMessage.model_validate_json(data).payload["kind"]
    except Exception:
        logger.debug("Mensagem descartada no canal %s", CHANNEL_EVENTS, exc_info=True)
        return False
    return kind in HINT_KINDS


def _log_teardown_results(tag_ids: list[int], resultados: list[object]) -> None:
    """Registra o que o gather engoliu: desmonte silencioso esconde task `calc-tag-*` viva."""
    for tag_id, resultado in zip(tag_ids, resultados, strict=True):
        if not isinstance(resultado, BaseException):
            continue
        if isinstance(resultado, asyncio.CancelledError):
            logger.warning("Desmonte da tag calculada %s foi cancelado por fora", tag_id)
        else:
            logger.exception(
                "Falha inesperada ao desmontar a tag calculada %s", tag_id, exc_info=resultado
            )


async def _cancel(task: asyncio.Task[None] | None, what: str) -> None:
    """Cancela e aguarda a task; erro dela não pode impedir o resto do desmonte."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Falha ao encerrar %s", what)
