"""Pipeline barramento → hypertables (RF-801, ADR-003, spec F2 §6.1–6.3).

Engine e `session_factory` dedicados (não as fixtures em SAVEPOINT): o pipeline commita
por conta própria e o teste precisa ver o dado commitado.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Table, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ottima_core.bus import (
    KIND_COMM_FAILURE,
    KIND_PROJECT_ACTIVATED,
    KIND_TAG_CREATED,
    OpcValue,
    channel_opc_values,
    publish_event,
)
from ottima_core.models import events_table, samples_table
from ottima_core.pubsub import PatternListener
from ottima_recorder import pipeline as pipeline_module
from ottima_recorder.pipeline import RecorderPipeline
from testkit.await_until import await_until

WAIT_TIMEOUT_S = 5.0
POLL_S = 0.02
LONG_INTERVAL_S = 60.0  # nunca dispara dentro do teste: isola o flush por tamanho
HUGE_BUFFER_ROWS = 100_000  # nunca enche dentro do teste: isola o flush por tempo
BASE_TS = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def sample(tag_id: int, *, offset: int = 0, value: float = 1.5, quality: int = 0) -> OpcValue:
    return OpcValue(
        tag_id=tag_id, ts=BASE_TS + timedelta(seconds=offset), value=value, quality=quality
    )


async def purge(factory: Any) -> None:
    async with factory() as session:
        await session.execute(delete(samples_table))
        await session.execute(delete(events_table))
        await session.commit()


async def count_rows(factory: Any, table: Table) -> int:
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(table))


async def wait_rows(factory: Any, table: Table, expected: int) -> None:
    async def chegou() -> bool:
        return await count_rows(factory, table) >= expected

    await await_until(chegou)


@pytest.fixture
async def session_factory(migrated_database_url):
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await purge(factory)
    await engine.dispose()


class RecordingSession(AsyncSession):
    """Sessão que registra em `info["writes"]` a tabela de cada statement executado."""

    async def execute(self, statement, *args: Any, **kwargs: Any):
        table = getattr(statement, "table", None)
        if table is not None:
            self.info["writes"].append(table.name)
        return await super().execute(statement, *args, **kwargs)


@pytest.fixture
async def instrumented(migrated_database_url):
    """`(factory, opens, writes)`: conta sessões abertas e registra a ordem das tabelas."""
    engine = create_async_engine(migrated_database_url)
    opens: list[str] = []
    writes: list[str] = []
    inner = async_sessionmaker(
        engine, class_=RecordingSession, expire_on_commit=False, info={"writes": writes}
    )

    def factory() -> RecordingSession:
        opens.append("session")
        return inner()

    yield factory, opens, writes
    await purge(inner)
    await engine.dispose()


@pytest.fixture
async def make_pipeline(redis_client):
    """Fábrica de pipelines já iniciados; para todos no teardown."""
    started: list[RecorderPipeline] = []

    async def _make(factory: Any, **kwargs: Any) -> RecorderPipeline:
        pipeline = RecorderPipeline(redis_client, factory, **kwargs)
        await pipeline.start()
        started.append(pipeline)
        return pipeline

    yield _make
    for pipeline in started:
        await pipeline.stop()


async def test_n_samples_publicados_geram_n_linhas(redis_client, session_factory, make_pipeline):
    pipeline = await make_pipeline(session_factory)
    published = [sample(7, offset=i, value=1.5 + i, quality=i % 3) for i in range(5)]
    for value in published:
        await redis_client.publish(channel_opc_values(7), value.model_dump_json())

    await wait_rows(session_factory, samples_table, 5)
    async with session_factory() as session:
        rows = (await session.execute(select(samples_table).order_by(samples_table.c.ts))).all()

    # ts vem do payload (timestamp da fonte, spec §2.2-7), nunca do now() do recorder
    assert [(r.ts, r.tag_id, r.value, r.quality) for r in rows] == [
        (v.ts, v.tag_id, v.value, v.quality) for v in published
    ]
    assert pipeline.last_flush_ts is not None


async def test_evento_publicado_gera_linha_em_events(redis_client, session_factory, make_pipeline):
    await make_pipeline(session_factory)
    event = await publish_event(
        redis_client,
        severity="warning",
        origin="opc-worker/3",
        message="Falha de comunicação com a conexão 3",
        kind=KIND_COMM_FAILURE,
        payload={"conn_id": 3},
    )

    await wait_rows(session_factory, events_table, 1)
    async with session_factory() as session:
        row = (await session.execute(select(events_table))).one()

    assert (row.ts, row.severity, row.origin, row.message) == (
        event.ts,
        event.severity,
        event.origin,
        event.message,
    )
    assert row.payload == {"kind": KIND_COMM_FAILURE, "conn_id": 3}


async def test_flush_por_tamanho_grava_sem_esperar_o_intervalo(
    redis_client, session_factory, make_pipeline
):
    await make_pipeline(session_factory, flush_interval_s=LONG_INTERVAL_S, samples_flush_rows=10)
    for i in range(10):
        await redis_client.publish(channel_opc_values(3), sample(3, offset=i).model_dump_json())

    # WAIT_TIMEOUT_S << LONG_INTERVAL_S: se dependesse do tempo, este wait estouraria
    await wait_rows(session_factory, samples_table, 10)


async def test_flush_por_tempo_grava_uma_amostra_isolada(
    redis_client, session_factory, make_pipeline
):
    await make_pipeline(session_factory, flush_interval_s=0.2, samples_flush_rows=HUGE_BUFFER_ROWS)
    await redis_client.publish(channel_opc_values(4), sample(4).model_dump_json())

    await wait_rows(session_factory, samples_table, 1)


async def test_eventos_sao_gravados_antes_das_samples(redis_client, instrumented, make_pipeline):
    factory, _opens, writes = instrumented
    pipeline = await make_pipeline(
        factory, flush_interval_s=LONG_INTERVAL_S, samples_flush_rows=HUGE_BUFFER_ROWS
    )
    for i in range(3):
        await redis_client.publish(channel_opc_values(5), sample(5, offset=i).model_dump_json())
    await publish_event(
        redis_client,
        severity="info",
        origin="api",
        message="Projeto ativado",
        kind=KIND_PROJECT_ACTIVATED,
        payload={"project_id": 1},
    )
    await await_until(lambda: pipeline.buffered_samples == 3 and pipeline.buffered_events == 1)

    await pipeline.flush()

    assert writes == ["events", "samples"]


async def test_buffer_de_eventos_cheio_forca_o_flush(
    redis_client, session_factory, make_pipeline, monkeypatch
):
    """Auditoria não espera o intervalo: buffer de eventos cheio também dispara o ciclo."""
    monkeypatch.setattr(pipeline_module, "EVENTS_FLUSH_ROWS", 3)
    await make_pipeline(
        session_factory, flush_interval_s=LONG_INTERVAL_S, samples_flush_rows=HUGE_BUFFER_ROWS
    )
    for i in range(3):
        await publish_event(
            redis_client,
            severity="info",
            origin="api",
            message=f"Tag {i} criada",
            kind=KIND_TAG_CREATED,
            payload={"tag_id": i},
        )

    await wait_rows(session_factory, events_table, 3)


async def test_sample_de_tag_orfa_grava(redis_client, session_factory, make_pipeline):
    """Dumb pipe: `samples.tag_id` não tem FK (spec F1 §3.4-2), órfã grava igual."""
    await make_pipeline(session_factory)
    orfa = sample(987_654_321, value=42.0)
    await redis_client.publish(channel_opc_values(6), orfa.model_dump_json())

    await wait_rows(session_factory, samples_table, 1)
    async with session_factory() as session:
        row = (await session.execute(select(samples_table))).one()

    assert (row.tag_id, row.value) == (orfa.tag_id, orfa.value)


async def test_payload_malformado_nao_derruba_o_pipeline(
    redis_client, session_factory, make_pipeline
):
    await make_pipeline(session_factory)
    channel = channel_opc_values(8)
    primeira = sample(8, offset=1, value=10.0)
    await redis_client.publish(channel, "{lixo")
    await redis_client.publish(channel, primeira.model_dump_json())
    await wait_rows(session_factory, samples_table, 1)

    # o loop segue vivo depois do descarte
    segunda = sample(8, offset=2, value=20.0)
    await redis_client.publish(channel, segunda.model_dump_json())
    await wait_rows(session_factory, samples_table, 2)

    async with session_factory() as session:
        rows = (await session.execute(select(samples_table).order_by(samples_table.c.ts))).all()
    assert [r.value for r in rows] == [primeira.value, segunda.value]


async def test_padrao_casa_multiplas_conexoes(redis_client, session_factory, make_pipeline):
    await make_pipeline(session_factory)
    await redis_client.publish(channel_opc_values(1), sample(11, value=1.0).model_dump_json())
    await redis_client.publish(channel_opc_values(2), sample(22, value=2.0).model_dump_json())

    await wait_rows(session_factory, samples_table, 2)
    async with session_factory() as session:
        rows = (await session.execute(select(samples_table).order_by(samples_table.c.tag_id))).all()

    assert [(r.tag_id, r.value) for r in rows] == [(11, 1.0), (22, 2.0)]


async def test_stop_faz_flush_final_e_e_idempotente(redis_client, session_factory, make_pipeline):
    pipeline = await make_pipeline(
        session_factory, flush_interval_s=LONG_INTERVAL_S, samples_flush_rows=HUGE_BUFFER_ROWS
    )
    await redis_client.publish(channel_opc_values(9), sample(9).model_dump_json())
    await await_until(lambda: pipeline.buffered_samples == 1)

    await pipeline.stop()
    assert await count_rows(session_factory, samples_table) == 1

    await pipeline.stop()
    assert await count_rows(session_factory, samples_table) == 1


async def test_flush_com_buffer_vazio_nao_abre_sessao(instrumented, make_pipeline):
    factory, opens, writes = instrumented
    pipeline = await make_pipeline(factory, flush_interval_s=LONG_INTERVAL_S)

    await pipeline.flush()
    assert opens == []

    pipeline.ingest_sample(sample(12).model_dump_json())
    await pipeline.flush()
    assert (opens, writes) == (["session"], ["samples"])


async def test_publicacao_logo_apos_start_nao_e_perdida(
    redis_client, session_factory, make_pipeline
):
    """`start()` só retorna com as duas inscrições confirmadas: nada publicado a seguir some."""
    pipeline = await make_pipeline(session_factory)

    await redis_client.publish(channel_opc_values(1), sample(31, value=7.5).model_dump_json())
    await publish_event(
        redis_client,
        severity="info",
        origin="api",
        message="Tag criada",
        kind=KIND_TAG_CREATED,
        payload={},
    )

    await await_until(lambda: (pipeline.buffered_samples, pipeline.buffered_events) == (1, 1))


async def test_falha_ao_assinar_nao_vaza_inscricao_nem_conexao(
    redis_client, session_factory, monkeypatch
):
    """`start()` que falha numa das duas assinaturas não deixa nem a outra pendurada.

    `PatternListener` (samples) é a segunda a subir dentro de `start()`: forçá-la a falhar
    prova que a primeira (`ChannelListener` de `events`), já confirmada, também é desfeita.
    """

    async def explode(self, pubsub) -> None:
        raise TimeoutError("confirmação de inscrição não chegou")

    monkeypatch.setattr(PatternListener, "_await_confirmation", explode)
    pipeline = RecorderPipeline(redis_client, session_factory)
    numpat_antes = await redis_client.pubsub_numpat()
    canais_antes = await redis_client.pubsub_channels()

    with pytest.raises(TimeoutError):
        await pipeline.start()

    async def liberou() -> bool:
        return (
            await redis_client.pubsub_numpat() == numpat_antes
            and await redis_client.pubsub_channels() == canais_antes
        )

    await await_until(liberou)
    await pipeline.stop()  # sem task nem pubsub pendentes, o desmonte é no-op
