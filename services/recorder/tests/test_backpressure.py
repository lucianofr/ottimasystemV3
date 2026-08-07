"""Backpressure, resiliência e /health do recorder (RF-801, RNF-05/07, spec F2 §6.4–6.6).

Engine e `session_factory` dedicados (não as fixtures em SAVEPOINT): o pipeline commita
por conta própria e o teste precisa ver o dado commitado.
"""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Table, delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_RECORDER_BACKPRESSURE,
    KIND_TAG_CREATED,
    EventMessage,
    MpcModes,
    MpcPrediction,
    MpcState,
    MpcStatus,
    MpcVarState,
    OpcValue,
    channel_mpc_state,
    channel_opc_values,
    publish_event,
)
from ottima_core.models import events_table, mpc_samples_table, samples_table
from ottima_recorder import main as main_module
from ottima_recorder.pipeline import RecorderPipeline
from testkit.await_until import await_until

WAIT_TIMEOUT_S = 5.0
POLL_S = 0.02
FAST_INTERVAL_S = 0.05
RETRY_HOLD_S = 0.01  # backoff neutralizado: o teste 2 é quem mede o valor calculado
BASE_TS = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
HEALTH_KEYS = {
    "status",
    "service",
    "version",
    "buffered_samples",
    "buffered_events",
    "buffered_mpc_samples",
    "dropped_total",
    "last_flush_ts",
    "db_ok",
}


def sample(tag_id: int, *, offset: int = 0, value: float = 1.5, quality: int = 0) -> OpcValue:
    return OpcValue(
        tag_id=tag_id, ts=BASE_TS + timedelta(seconds=offset), value=value, quality=quality
    )


def mpc_state(*, offset: int = 0, v: float = 1.5) -> MpcState:
    ts = BASE_TS + timedelta(seconds=offset)
    return MpcState(
        ts=ts,
        modes=MpcModes(local_remote="remote", man_auto="auto"),
        status=MpcStatus(solver="ok", overruns=0, last_solve_ms=0.0, armed=True, input_valid=True),
        vars={"mv_a": MpcVarState(v=v)},
        cost=0.0,
        prediction=MpcPrediction(ts=ts, t=[], cv=[], mv=[]),
    )


async def count_rows(factory: Any, table: Table) -> int:
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(table))


async def wait_rows(factory: Any, table: Table, expected: int) -> None:
    async def chegou() -> bool:
        return await count_rows(factory, table) >= expected

    await await_until(chegou)


async def sample_values(factory: Any) -> list[float]:
    async with factory() as session:
        rows = (await session.execute(select(samples_table).order_by(samples_table.c.ts))).all()
    return [row.value for row in rows]


async def mpc_values(factory: Any) -> list[float]:
    async with factory() as session:
        rows = (
            await session.execute(select(mpc_samples_table).order_by(mpc_samples_table.c.ts))
        ).all()
    return [row.v for row in rows]


async def event_payloads(factory: Any, kind: str) -> list[dict[str, Any]]:
    async with factory() as session:
        rows = (await session.execute(select(events_table).order_by(events_table.c.ts))).all()
    return [row.payload for row in rows if row.payload.get("kind") == kind]


def backpressure(seen: list[EventMessage]) -> list[EventMessage]:
    return [e for e in seen if e.payload.get("kind") == KIND_RECORDER_BACKPRESSURE]


def spy_retry_delay(monkeypatch: pytest.MonkeyPatch, hold: float = RETRY_HOLD_S) -> list[float]:
    """Registra o atraso calculado a cada retry e espera um valor fixo curto no lugar dele."""
    delays: list[float] = []
    real = RecorderPipeline._retry_delay

    def spy(self: RecorderPipeline) -> float:
        delays.append(real(self))
        return hold

    monkeypatch.setattr(RecorderPipeline, "_retry_delay", spy)
    return delays


class SwitchableFactory:
    """`session_factory` que dá para desligar: simula o banco fora do ar."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.up = True

    def __call__(self) -> Any:
        if not self.up:
            raise ConnectionError("banco indisponível")
        return self._real()


class StubPipeline:
    """Só as propriedades que o /health lê."""

    def __init__(
        self,
        *,
        buffered_samples: int = 0,
        buffered_events: int = 0,
        buffered_mpc_samples: int = 0,
        dropped_total: int = 0,
        last_flush_ts: datetime | None = None,
        db_ok: bool = True,
    ) -> None:
        self.buffered_samples = buffered_samples
        self.buffered_events = buffered_events
        self.buffered_mpc_samples = buffered_mpc_samples
        self.dropped_total = dropped_total
        self.last_flush_ts = last_flush_ts
        self.db_ok = db_ok


@pytest.fixture
async def factory(migrated_database_url):
    engine = create_async_engine(migrated_database_url)
    real = async_sessionmaker(engine, expire_on_commit=False)
    yield SwitchableFactory(real)
    async with real() as session:
        await session.execute(delete(samples_table))
        await session.execute(delete(events_table))
        await session.execute(delete(mpc_samples_table))
        await session.commit()
    await engine.dispose()


@pytest.fixture
async def make_pipeline(redis_client):
    """Fábrica de pipelines já iniciados; para todos no teardown."""
    started: list[RecorderPipeline] = []

    async def _make(session_factory: Any, **kwargs: Any) -> RecorderPipeline:
        pipeline = RecorderPipeline(redis_client, session_factory, **kwargs)
        await pipeline.start()
        started.append(pipeline)
        return pipeline

    yield _make
    for pipeline in started:
        await pipeline.stop()


@pytest.fixture
async def events_seen(redis_client):
    """Coleta os `EventMessage` que passam pelo canal `events` durante o teste."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_EVENTS)
    async with asyncio.timeout(WAIT_TIMEOUT_S):
        while True:
            message = await pubsub.get_message(timeout=WAIT_TIMEOUT_S)
            if message is not None and message["type"] == "subscribe":
                break
    seen: list[EventMessage] = []

    async def reader() -> None:
        async for message in pubsub.listen():
            if message["type"] == "message":
                seen.append(EventMessage.model_validate_json(message["data"]))

    task = asyncio.create_task(reader())
    yield seen
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    await pubsub.aclose()


async def publish_samples(redis_client: Any, count: int, *, tag_id: int = 7) -> None:
    for i in range(count):
        await redis_client.publish(
            channel_opc_values(1), sample(tag_id, offset=i, value=float(i)).model_dump_json()
        )


async def test_banco_parado_segura_o_buffer_e_grava_na_volta(
    redis_client, factory, make_pipeline, monkeypatch
):
    spy_retry_delay(monkeypatch)
    pipeline = await make_pipeline(factory, flush_interval_s=FAST_INTERVAL_S)
    factory.up = False

    await publish_samples(redis_client, 20)
    await await_until(lambda: pipeline.buffered_samples == 20)
    await await_until(lambda: pipeline.db_ok is False)
    assert pipeline.buffered_samples == 20  # nada perdido enquanto o banco está fora
    assert pipeline.dropped_total == 0

    factory.up = True
    await wait_rows(factory, samples_table, 20)
    assert pipeline.db_ok is True
    assert pipeline.buffered_samples == 0
    assert await sample_values(factory) == [float(i) for i in range(20)]


async def test_backoff_do_flush_cresce_e_satura(redis_client, factory, make_pipeline, monkeypatch):
    delays = spy_retry_delay(monkeypatch)
    await make_pipeline(factory, flush_interval_s=FAST_INTERVAL_S)
    factory.up = False

    await publish_samples(redis_client, 1)
    await await_until(lambda: len(delays) >= 7)
    factory.up = True

    assert delays[:7] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


async def test_overflow_de_samples_descarta_o_mais_antigo_e_conta(
    redis_client, factory, make_pipeline, monkeypatch
):
    spy_retry_delay(monkeypatch)
    pipeline = await make_pipeline(factory, flush_interval_s=FAST_INTERVAL_S, samples_queue_max=10)
    factory.up = False

    await publish_samples(redis_client, 15)
    await await_until(lambda: pipeline.dropped_total == 5)
    assert pipeline.buffered_samples == 10

    factory.up = True
    await wait_rows(factory, samples_table, 10)
    # As 5 mais antigas sumiram: sobraram exatamente as 10 mais frescas.
    assert await sample_values(factory) == [float(i) for i in range(5, 15)]


async def test_overflow_de_mpc_samples_descarta_o_mais_antigo_e_conta(
    redis_client, factory, make_pipeline, monkeypatch
):
    spy_retry_delay(monkeypatch)
    pipeline = await make_pipeline(factory, flush_interval_s=FAST_INTERVAL_S, mpc_queue_max=10)
    factory.up = False

    channel = channel_mpc_state(1, "b1")
    for i in range(15):
        await redis_client.publish(channel, mpc_state(offset=i, v=float(i)).model_dump_json())
    await await_until(lambda: pipeline.dropped_total == 5)
    assert pipeline.buffered_mpc_samples == 10

    factory.up = True
    await wait_rows(factory, mpc_samples_table, 10)
    # As 5 mais antigas sumiram: sobraram exatamente as 10 mais frescas.
    assert await mpc_values(factory) == [float(i) for i in range(5, 15)]


async def test_recuperacao_emite_um_unico_evento_de_backpressure(
    redis_client, factory, make_pipeline, events_seen, monkeypatch
):
    spy_retry_delay(monkeypatch)
    pipeline = await make_pipeline(factory, flush_interval_s=FAST_INTERVAL_S, samples_queue_max=10)
    factory.up = False
    await publish_samples(redis_client, 15)
    await await_until(lambda: pipeline.dropped_total == 5)

    factory.up = True
    await await_until(lambda: len(backpressure(events_seen)) == 1)
    evento = backpressure(events_seen)[0]
    assert evento.severity == "warning"
    assert evento.origin == "recorder"
    assert evento.payload["dropped_total"] == 5
    assert evento.payload["dropped_since_last"] == 5

    await redis_client.publish(
        channel_opc_values(1), sample(9, offset=99, value=99.0).model_dump_json()
    )
    await wait_rows(factory, samples_table, 11)
    assert len(backpressure(events_seen)) == 1  # flush bom sem novo descarte não reemite


async def test_nada_e_emitido_durante_a_indisponibilidade(
    redis_client, factory, make_pipeline, events_seen, monkeypatch
):
    delays = spy_retry_delay(monkeypatch)
    pipeline = await make_pipeline(factory, flush_interval_s=FAST_INTERVAL_S, samples_queue_max=10)
    factory.up = False

    await publish_samples(redis_client, 15)
    await await_until(lambda: pipeline.dropped_total == 5)
    await await_until(lambda: len(delays) >= 3)  # três tentativas de flush já falharam

    assert backpressure(events_seen) == []


async def test_lote_maior_que_o_teto_de_binds_do_asyncpg_grava_inteiro(redis_client, factory):
    """Buffer segurado por muito tempo estoura os 32767 binds do asyncpg num INSERT só."""
    pipeline = RecorderPipeline(redis_client, factory)
    rows = 9000  # samples tem 4 colunas: 9000 linhas passam de 32767 parâmetros
    for i in range(rows):
        pipeline.ingest_sample(sample(7, offset=i, value=float(i)).model_dump_json())

    await pipeline.flush()

    assert await count_rows(factory, samples_table) == rows
    assert pipeline.buffered_samples == 0


async def test_overflow_de_eventos_descarta_o_mais_antigo_e_conta(
    redis_client, factory, make_pipeline, monkeypatch
):
    spy_retry_delay(monkeypatch)
    pipeline = await make_pipeline(factory, flush_interval_s=FAST_INTERVAL_S, events_queue_max=3)
    factory.up = False

    for i in range(5):
        await publish_event(
            redis_client,
            severity="info",
            origin="teste",
            message=f"evento {i}",
            kind=KIND_TAG_CREATED,
            payload={"n": i},
            ts=BASE_TS + timedelta(seconds=i),
        )
    await await_until(lambda: pipeline.dropped_total == 2)
    assert pipeline.buffered_events == 3

    factory.up = True
    await wait_rows(factory, events_table, 3)
    payloads = await event_payloads(factory, KIND_TAG_CREATED)
    assert [p["n"] for p in payloads] == [2, 3, 4]


async def test_malformado_conta_separado_do_descarte_por_pressao(
    redis_client, factory, make_pipeline
):
    pipeline = await make_pipeline(factory, flush_interval_s=FAST_INTERVAL_S)

    await redis_client.publish(channel_opc_values(1), "{isso não é json}")
    await await_until(lambda: pipeline.malformed_total == 1)

    assert pipeline.dropped_total == 0  # lixo no canal não é pressão
    assert pipeline.buffered_samples == 0


async def test_stop_duas_vezes_nao_levanta_nem_grava_de_novo(redis_client, factory):
    pipeline = RecorderPipeline(redis_client, factory, flush_interval_s=FAST_INTERVAL_S)
    await pipeline.start()
    events_task = pipeline._events_listener._task
    samples_task = pipeline._samples_listener._task
    flush_task = pipeline._flush_task
    pipeline.ingest_sample(sample(7, value=1.0).model_dump_json())

    await pipeline.stop()
    await pipeline.stop()  # segundo desmonte não levanta e não reflusha

    assert await count_rows(factory, samples_table) == 1
    assert (events_task.cancelled(), samples_task.cancelled(), flush_task.cancelled()) == (
        True,
        True,
        True,
    )


async def test_stop_loga_a_etapa_que_falha_e_conclui_o_desmonte(
    redis_client, factory, monkeypatch, caplog
):
    """Rede de segurança do desmonte não pode ser cega: falha vai para o log, não some."""
    pipeline = RecorderPipeline(redis_client, factory, flush_interval_s=FAST_INTERVAL_S)
    await pipeline.start()
    pipeline.ingest_sample(sample(7, value=2.0).model_dump_json())

    async def aclose_quebrado() -> None:
        raise ConnectionError("redis sumiu durante o desmonte")

    monkeypatch.setattr(pipeline._samples_listener._pubsub, "aclose", aclose_quebrado)

    with caplog.at_level(logging.WARNING, logger="ottima_core.pubsub"):
        await pipeline.stop()

    assert any("assinante" in r.getMessage() for r in caplog.records)
    assert await count_rows(factory, samples_table) == 1  # flush final aconteceu mesmo assim
    assert pipeline._samples_listener._pubsub is None


async def test_stop_loga_task_morta_por_excecao_e_segue(redis_client, factory, caplog):
    pipeline = RecorderPipeline(redis_client, factory, flush_interval_s=FAST_INTERVAL_S)
    await pipeline.start()
    pipeline._flush_task.cancel()
    with suppress(asyncio.CancelledError):
        await pipeline._flush_task

    async def morre() -> None:
        raise RuntimeError("desmonte quebrado")

    pipeline._flush_task = asyncio.create_task(morre())
    await asyncio.sleep(0)  # deixa a task morrer antes do desmonte
    pipeline.ingest_sample(sample(7, value=3.0).model_dump_json())

    with caplog.at_level(logging.ERROR, logger="ottima_recorder.pipeline"):
        await pipeline.stop()

    assert any("task de flush" in r.getMessage() for r in caplog.records)
    assert await count_rows(factory, samples_table) == 1
    assert pipeline._flush_task is None
    assert (pipeline._events_listener._task, pipeline._samples_listener._task) == (None, None)


@pytest.fixture
def health_app():
    """Devolve o app ao estado cru: `main.app` é global e compartilhado entre testes."""
    yield main_module.app
    for attr in ("pipeline", "redis_ok"):
        if hasattr(main_module.app.state, attr):
            delattr(main_module.app.state, attr)


async def get_health(app: Any) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.get("/health")


async def test_health_sem_pipeline_usa_defaults(health_app):
    response = await get_health(health_app)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == HEALTH_KEYS
    assert body["service"] == "recorder"
    assert (
        body["buffered_samples"],
        body["buffered_events"],
        body["buffered_mpc_samples"],
        body["dropped_total"],
    ) == (0, 0, 0, 0)
    assert body["last_flush_ts"] is None
    assert body["db_ok"] is False
    assert body["status"] == "degraded"


async def test_health_ok_exige_redis_e_banco(health_app):
    health_app.state.redis_ok = True
    health_app.state.pipeline = StubPipeline(
        buffered_samples=7,
        buffered_events=2,
        buffered_mpc_samples=4,
        dropped_total=5,
        last_flush_ts=BASE_TS,
        db_ok=True,
    )

    body = (await get_health(health_app)).json()

    assert set(body) == HEALTH_KEYS
    assert body["status"] == "ok"
    assert body["buffered_samples"] == 7
    assert body["buffered_events"] == 2
    assert body["buffered_mpc_samples"] == 4
    assert body["dropped_total"] == 5
    assert body["last_flush_ts"] == BASE_TS.isoformat()
    assert body["db_ok"] is True


async def test_health_degrada_com_banco_fora(health_app):
    health_app.state.redis_ok = True
    health_app.state.pipeline = StubPipeline(db_ok=False)

    response = await get_health(health_app)

    assert response.status_code == 200  # degradação vai no corpo, nunca no status HTTP
    assert response.json()["status"] == "degraded"


async def test_health_degrada_com_redis_fora(health_app):
    health_app.state.redis_ok = False
    health_app.state.pipeline = StubPipeline(db_ok=True)

    assert (await get_health(health_app)).json()["status"] == "degraded"
