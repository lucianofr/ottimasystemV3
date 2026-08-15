"""Polling OPC-UA do worker: leitura cíclica em lote → `opc.values.<conn_id>` (spec F2
§2.2-4/5/7, ADR-032).

Uma task por conexão. Cada ciclo faz UM `read_attributes` com todos os nodes com série e
publica todas as tags — não é mais report-by-exception (ADR-032). A publicação tem um ponto
único (`publish_value`) porque o heartbeat de valor e a rajada de quality=bad publicam com a
sessão CAÍDA, quando não existe poller.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from asyncua import Client, ua
from asyncua.common.node import Node
from redis.asyncio import Redis

from ottima_core.bus import (
    KIND_TAG_SUBSCRIBE_ERROR,
    OpcValue,
    channel_opc_values,
    publish_event,
)

from .state import ConnectionConfig, ConnectionSnapshot, TagConfig, TagSnapshot

logger = logging.getLogger(__name__)

QUALITY_GOOD = 0
QUALITY_UNCERTAIN = 1
QUALITY_BAD = 2

# Folga mínima entre ciclos, mesmo quando a leitura já estourou o período (piso igual ao da
# amostragem do watchdog): emendar requisições back-to-back num servidor lento só piora.
_MIN_IDLE_S = 0.05

# A severidade da StatusCode vive nos 2 bits mais altos (OPC-UA Part 4 §7.34).
_SEVERITY_SHIFT = 30
_SEVERITY_TO_QUALITY = {0: QUALITY_GOOD, 1: QUALITY_UNCERTAIN}

# Bit CurrentRead do AccessLevel (OPC-UA Part 3 §5.6.2). `ua.AccessLevel.CurrentRead` é a
# POSIÇÃO do bit, não a máscara.
_CURRENT_READ_MASK = 1 << int(ua.AccessLevel.CurrentRead)


def status_to_quality(status_code: ua.StatusCode | None) -> int:
    """StatusCode OPC-UA → quality 0/1/2 (spec F1 §3.4-4).

    A severidade está nos 2 bits mais altos do código: 0=Good, 1=Uncertain, 2=Bad,
    3=reservado (tratado como Bad). Ausência de status também é Bad: sem qualidade
    declarada o valor não pode ser dado bom.
    """
    if status_code is None:
        return QUALITY_BAD
    severity = (int(status_code.value) >> _SEVERITY_SHIFT) & 0b11
    return _SEVERITY_TO_QUALITY.get(severity, QUALITY_BAD)


def coerce_value(raw: Any) -> float:
    """Valor OPC → float (bool→0.0/1.0, int→float; None ⇒ 0.0 sob quality bad).

    `samples.value` é DOUBLE PRECISION (spec F1 §3.2): o barramento já trafega float.
    """
    if raw is None:
        return 0.0
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    return float(raw)


async def publish_value(
    redis_client: Redis,
    conn_id: int,
    snapshot: ConnectionSnapshot,
    *,
    tag_id: int,
    value: float,
    quality: int,
    ts: datetime | None = None,
) -> None:
    """Ponto único de publicação em `opc.values.<conn_id>` (payload §7.1 verbatim).

    É função de módulo, não método, porque o heartbeat de valor (tarefa 1.3) e a rajada de
    quality=bad (tarefa 2.2) publicam com a sessão CAÍDA, quando não existe poller. A
    publicação registra dois relógios: `published_at` (parede, para exibição e diagnóstico) e
    `published_monotonic`, o único que mede decurso — o heartbeat decide por ele, imune a
    servidor adiantado e a ajuste de NTP para trás.
    """
    ts = _as_utc(ts) if ts is not None else datetime.now(UTC)
    published_at = datetime.now(UTC)
    published_monotonic = time.monotonic()
    payload = OpcValue(tag_id=tag_id, ts=ts, value=value, quality=quality)
    await redis_client.publish(channel_opc_values(conn_id), payload.model_dump_json())
    snapshot.last_values[tag_id] = TagSnapshot(
        ts=ts,
        value=value,
        quality=quality,
        published_at=published_at,
        published_monotonic=published_monotonic,
    )
    snapshot.last_publish_ts = published_at


def _as_utc(moment: datetime) -> datetime:
    """Timestamp do servidor em UTC aware; naive é tratado como UTC (spec §2.2-7)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _describe(exc: Exception) -> str:
    """Detalhe curto para o payload do evento, no mesmo idioma de `watchdog.py`."""
    return f"{type(exc).__name__}: {exc}".strip()


# `_data_value_ts` (SourceTimestamp → ServerTimestamp) morreu com a subscription: ver o
# comentário de `_publish` sobre o eixo de tempo da amostra (spec §2.2-7, ADR-032).


def _raw_value(data_value: ua.DataValue | None) -> Any:
    """Valor bruto do DataValue; ausência de Variant é `None` (vira 0.0 sob bad)."""
    if data_value is None or data_value.Value is None:
        return None
    return data_value.Value.Value


def _declares_read_access(data_value: ua.DataValue | None) -> bool:
    """O AccessLevel lido declara o bit CurrentRead?

    Otimista de propósito: atributo ilegível (servidor que não o expõe) conta como legível —
    perder a série de um comando legível por causa de um atributo ausente seria pior que uma
    leitura bad, que o caminho da quality já trata.
    """
    try:
        if data_value is None or status_to_quality(data_value.StatusCode) != QUALITY_GOOD:
            return True
        return bool(int(_raw_value(data_value)) & _CURRENT_READ_MASK)
    except (TypeError, ValueError):
        return True


class ValuePoller:
    """Leitura cíclica em lote das tags com série de uma conexão (ADR-032).

    `direction` governa quem o sistema pode ESCREVER, não o que ele pode observar: o valor de
    uma tag `w` é o comando em vigor no servidor, grandeza distinta do readback de posição
    real (RF-604) e dado de processo por direito próprio. Node de comando ilegível
    (write-only) é caso legítimo e fica fora do ciclo, sem erro — ver `_select_series_tags`.

    Tags e nodes nascem JUNTOS, da mesma iteração, e são emparelhados com
    `zip(..., strict=True)`: o índice é a única ligação entre a resposta do servidor e a tag,
    então desalinhar publicaria valor sob o `tag_id` errado — corrupção silenciosa alimentando
    PID/MPC. `strict` também derruba resposta curta do servidor, que o `zip` normal truncaria
    em silêncio (tags parariam de atualizar sem erro nenhum).
    """

    def __init__(
        self,
        config: ConnectionConfig,
        client: Client,
        redis_client: Redis,
        snapshot: ConnectionSnapshot,
        *,
        on_hard_failure: Callable[[str], Awaitable[None]],
    ) -> None:
        self._config = config
        self._client = client
        self._redis = redis_client
        self._snapshot = snapshot
        self._on_hard_failure = on_hard_failure
        self._period_s = config.polling_period_ms / 1000
        # Leitura travada não pode congelar a task para sempre (mesmo achado do watchdog: uma
        # sessão zumbi deixa o read pendurado e a task morre calada). Leitura que não completa
        # nisto é sessão morta, e o `on_hard_failure` reconecta.
        self._io_timeout_s = max(10.0, 3 * self._period_s)
        self._tags: tuple[TagConfig, ...] = ()
        self._nodes: list[Node] = []
        self._task: asyncio.Task[None] | None = None
        # Dedupe do evento por tag: uma tag mal configurada não vira rajada de warning. Um
        # poller novo (nova sessão ou troca de tags) rearma o dedupe.
        self._reported_errors: set[int] = set()

    @property
    def tags(self) -> tuple[TagConfig, ...]:
        """Tags efetivamente no ciclo, na ordem em que são lidas."""
        return self._tags

    @property
    def period_s(self) -> float:
        """Período de varredura em segundos (`opc_connections.polling_period_ms`)."""
        return self._period_s

    async def start(self) -> None:
        """Escolhe o conjunto com série e sobe a task do ciclo.

        Falha aqui propaga (é falha de sessão, não de tag): quem chama derruba a sessão e
        reconecta em backoff.
        """
        if self._task is not None and not self._task.done():
            return
        await self._select_series_tags()
        self._snapshot.tags_polled = len(self._tags)
        self._task = asyncio.create_task(self._loop(), name=f"opc-poll-{self._config.id}")

    async def stop(self) -> None:
        """Cancela a task e AGUARDA o fim. Idempotente.

        Aguardar é o ponto: sem isso o poller velho ainda publicaria durante a troca de
        conjunto de tags, concorrendo com o novo no mesmo canal.
        """
        task, self._task = self._task, None
        self._tags = ()
        self._nodes = []
        self._snapshot.tags_polled = 0
        if task is None or task.done():
            return
        if task is asyncio.current_task():
            # Reentrância: o `on_hard_failure` do próprio ciclo leva o runtime a derrubar a
            # sessão, que chama este stop() de dentro da task do poller. Ela já está
            # encerrando — cancelar-se e se aguardar levantaria RuntimeError. Mesmo guarda
            # de `WatchdogTask.stop()`, mesma cadeia (`_loop` → `fail` → `on_session_down`).
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _select_series_tags(self) -> None:
        """Monta, na MESMA iteração, a lista de tags com série e a de nodes correspondente.

        Tag `r` entra sempre — a série dela é obrigatória por cadastro, e node torto precisa
        aparecer como bad em vez de emudecer. Tag `w` entra só se o servidor declarar
        CurrentRead: assinar o que ele diz ilegível só renderia bad, e quem consome
        `opc.values` mostraria "ruim 0" onde o honesto é "sem dado".
        """
        candidatas: list[tuple[TagConfig, Node]] = []
        for tag in self._config.tags:
            try:
                node = self._client.get_node(tag.node_id)
            except Exception as exc:
                if tag.direction == "w":
                    # Nem todo comando de PLC/gateway é endereçável como node de leitura.
                    logger.info(
                        "Tag de escrita %s (%s) da conexão %s não é legível, segue sem série: %s",
                        tag.id,
                        tag.node_id,
                        self._config.id,
                        _describe(exc),
                    )
                    continue
                await self._alarm_once(tag, "node inválido ou inexistente", _describe(exc))
                continue
            candidatas.append((tag, node))

        legiveis = await self._readable_write_tags(
            [(tag, node) for tag, node in candidatas if tag.direction == "w"]
        )
        tags: list[TagConfig] = []
        nodes: list[Node] = []
        for tag, node in candidatas:
            if tag.direction == "w" and tag.id not in legiveis:
                logger.info(
                    "Tag de escrita %s (%s) da conexão %s é write-only, segue sem série",
                    tag.id,
                    tag.node_id,
                    self._config.id,
                )
                continue
            tags.append(tag)
            nodes.append(node)
        self._tags = tuple(tags)
        self._nodes = nodes

    async def _readable_write_tags(
        self, candidatas: list[tuple[TagConfig, Node]]
    ) -> frozenset[int]:
        """Quais tags `w` declaram CurrentRead — um único round trip para todas."""
        if not candidatas:
            return frozenset()
        try:
            data_values = await self._client.read_attributes(
                [node for _, node in candidatas], ua.AttributeIds.AccessLevel
            )
        except Exception:
            # Servidor que recusa o atributo em bloco não condena comando nenhum: otimista,
            # como na leitura individual. Uma leitura bad depois é tratada pela quality.
            logger.debug("AccessLevel indisponível na conexão %s", self._config.id, exc_info=True)
            return frozenset(tag.id for tag, _ in candidatas)
        return frozenset(
            tag.id
            for (tag, _), data_value in zip(candidatas, data_values, strict=True)
            if _declares_read_access(data_value)
        )

    async def _loop(self) -> None:
        overrun_avisado = False
        while True:
            started = time.monotonic()
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Leitura que falha EM BLOCO é sessão morta, não tag torta — inclusive o
                # ValueError do `zip(strict=True)`: servidor que devolve menos valores que
                # nodes pedidos não merece confiança para o resto do ciclo.
                await self._on_hard_failure(_describe(exc))
                return
            # Sleep compensado pelo tempo da leitura: sem isto o período real seria
            # `período + latência` e a cadência derivaria a cada ciclo.
            decorrido = time.monotonic() - started
            if decorrido > self._period_s and not overrun_avisado:
                # Uma vez por poller: o operador pediu N ms e está recebendo mais que isso.
                # Sem este aviso o sintoma é só "o trend tem menos pontos do que configurei",
                # sem causa visível em lugar nenhum.
                overrun_avisado = True
                logger.warning(
                    "Varredura da conexão %s levou %.0f ms, acima do período de %.0f ms: "
                    "a cadência real será a do servidor",
                    self._config.id,
                    decorrido * 1000,
                    self._period_s * 1000,
                )
            # Piso de folga (mesmo motivo do `max(0.05, ...)` do watchdog): leitura mais
            # lenta que o período zeraria o sleep e emendaria requisições back-to-back num
            # servidor que JÁ está sofrendo, piorando o que se quer medir.
            await asyncio.sleep(max(_MIN_IDLE_S, self._period_s - decorrido))

    async def _cycle(self) -> None:
        """Um round trip para todas as tags com série, depois uma publicação por tag."""
        if not self._nodes:
            return
        data_values = await asyncio.wait_for(
            self._client.read_attributes(self._nodes, ua.AttributeIds.Value),
            timeout=self._io_timeout_s,
        )
        for tag, data_value in zip(self._tags, data_values, strict=True):
            await self._publish(tag, data_value)

    async def _publish(self, tag: TagConfig, data_value: ua.DataValue | None) -> None:
        quality = status_to_quality(data_value.StatusCode if data_value else None)
        motivo: str | None = None
        detalhe = ""
        try:
            value = coerce_value(_raw_value(data_value))
        except (TypeError, ValueError) as exc:
            # Node de tipo incompatível com a tag é erro de cadastro: publica bad e avisa,
            # em vez de deixar a tag muda no canal.
            value, quality = 0.0, QUALITY_BAD
            motivo, detalhe = "valor do node não é numérico", _describe(exc)
        else:
            if quality != QUALITY_GOOD:
                motivo, detalhe = (
                    "leitura do node falhou",
                    str(data_value.StatusCode if data_value else None),
                )
        if quality != QUALITY_GOOD and not self._has_series(tag):
            # Comando que nunca leu bem ainda não tem série: "sem dado" é mais honesto que
            # "ruim 0" (mesma regra de `ValueHeartbeat._series_tags`).
            return
        if motivo is not None and tag.direction == "r":
            await self._alarm_once(tag, motivo, detalhe)
        # SEM `ts=`: o publisher carimba `now()`. Sob subscription cada notificação ERA uma
        # mudança, então o SourceTimestamp do servidor era o eixo de tempo certo. Sob polling
        # cada ciclo é uma OBSERVAÇÃO: o SourceTimestamp de um node estático não avança nunca,
        # e usá-lo empilharia todas as amostras no mesmo x do trend (e inflaria `n_samples` no
        # CAgg `samples_1m`). Um node parado também pareceria eternamente velho para qualquer
        # checagem de frescor. Mesmo carimbo que `ValueHeartbeat._republish` já usa.
        await publish_value(
            self._redis,
            self._config.id,
            self._snapshot,
            tag_id=tag.id,
            value=value,
            quality=quality,
        )

    def _has_series(self, tag: TagConfig) -> bool:
        """Mesma regra de `ValueHeartbeat._series_tags`: tag `r` sempre; tag `w` só depois de
        uma leitura boa, senão publicar bad inventaria série inexistente (RF-604)."""
        return tag.direction == "r" or tag.id in self._snapshot.last_values

    async def _alarm_once(self, tag: TagConfig, reason: str, detail: str) -> None:
        """1ª falha desta tag no poller: conta, loga e emite o warning uma única vez.

        A publicação de bad NÃO passa por aqui — ela é por ciclo (a série precisa continuar
        viva como ruim, spec §2.2-4); o alarme é por tag, senão uma tag torta viraria uma
        rajada de eventos a cada varredura.
        """
        if tag.id in self._reported_errors:
            return
        self._reported_errors.add(tag.id)
        # Atribuição, não incremento: `read_errors` conta as TAGS em falha deste poller. Um
        # poller novo (retimagem, troca de tags) rearma `_reported_errors`, e somar em cima
        # do valor antigo faria o contador subir a cada edição de conexão com a mesma tag
        # torta — conexão estável pareceria em flapping crescente no `/health`.
        self._snapshot.read_errors = len(self._reported_errors)
        logger.warning(
            "Tag %s (%s) da conexão %s em falha: %s — %s",
            tag.id,
            tag.node_id,
            self._config.id,
            reason,
            detail,
        )
        await publish_event(
            self._redis,
            severity="warning",
            origin=f"conn:{self._config.id}",
            message=(f"Falha na tag '{tag.name}' da conexão '{self._config.name}': {reason}"),
            # `kind` mantido: é contrato do canal `events` (spec §7.3) e renomear quebraria
            # consumidores, ainda que "subscribe" já não descreva o mecanismo.
            kind=KIND_TAG_SUBSCRIBE_ERROR,
            payload={
                "conn_id": self._config.id,
                "tag_id": tag.id,
                "node_id": tag.node_id,
                "detail": detail,
            },
        )
