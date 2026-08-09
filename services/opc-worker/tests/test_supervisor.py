"""Testes do supervisor do opc-worker (spec F2 §2.2-1, RF-201/204, ADR-017).

O supervisor usa um `session_factory` próprio, então estes testes commitam de verdade
contra o Timescale da fixture da raiz (engine dedicado a partir de `migrated_database_url`,
tabelas truncadas no setup e no teardown). As conexões apontam para o opcsim in-process.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from worker_test_helpers import await_until, collecting

from opcsim import NODE_SINE, NODE_STATIC, OpcSimServer
from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_COMM_RESTORED,
    KIND_CONNECTION_CREATED,
    KIND_OPC_WRITE,
    channel_opc_values,
    publish_event,
)
from ottima_core.models import OpcConnection, Project, Tag
from ottima_opc_worker import supervisor as supervisor_module
from ottima_opc_worker.state import (
    ConnectionConfig,
    ConnectionSnapshot,
    ConnectionState,
    WorkerState,
)
from ottima_opc_worker.supervisor import (
    MAX_CONNECTIONS,
    Supervisor,
    load_active_configuration,
    read_watermark,
)

# Poll curto: a reconciliação dos testes vem do loop, não de chamada direta.
TEST_POLL_INTERVAL_S = 0.2
# Poll longo o bastante para que qualquer reconciliação observada venha da dica.
SLOW_POLL_INTERVAL_S = 60.0
# Janela para provar que algo NÃO acontece (vários ciclos do poll curto).
QUIET_WINDOW_S = 1.0
# A senoide muda a cada 200 ms: uma tag subscrita publica bem dentro desta janela.
HINT_TIMEOUT_S = 5.0
# Freio de reassinatura usado nos testes, e a janela em que ele é medido.
FREIO_S = 0.1
JANELA_DO_FREIO_S = 0.6
# `conn_id` que nunca existe no banco: identifica a entrada injetada pelos testes.
MISSING_CONN_ID = 999_999


@pytest.fixture
async def session_factory(
    migrated_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Factory commitada de verdade: o supervisor não vê transação aberta de teste."""
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _truncate(factory)
    try:
        yield factory
    finally:
        await _truncate(factory)
        await engine.dispose()


async def _truncate(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        await session.execute(text("TRUNCATE tags, opc_connections, projects CASCADE"))
        await session.commit()


async def create_project(
    factory: async_sessionmaker[AsyncSession], *, name: str = "Projeto", is_active: bool = True
) -> int:
    async with factory() as session:
        project = Project(name=name, description="", is_active=is_active)
        session.add(project)
        await session.commit()
        return project.id


async def create_connection(
    factory: async_sessionmaker[AsyncSession],
    project_id: int,
    endpoint: str,
    *,
    name: str = "Forno 1",
    watchdog_period_ms: int = 1000,
) -> int:
    async with factory() as session:
        connection = OpcConnection(
            project_id=project_id,
            name=name,
            endpoint=endpoint,
            security_policy="none",
            security_mode="none",
            auth_mode="anonymous",
            watchdog_period_ms=watchdog_period_ms,
        )
        session.add(connection)
        await session.commit()
        return connection.id


async def create_tag(
    factory: async_sessionmaker[AsyncSession],
    connection_id: int,
    *,
    name: str,
    node_id: str,
    direction: str = "r",
    data_type: str = "float",
) -> int:
    async with factory() as session:
        tag = Tag(
            connection_id=connection_id,
            name=name,
            node_id=node_id,
            direction=direction,
            data_type=data_type,
            eu="",
            description="",
        )
        session.add(tag)
        await session.commit()
        return tag.id


async def update_connection(
    factory: async_sessionmaker[AsyncSession], conn_id: int, **changes: object
) -> None:
    async with factory() as session:
        connection = await session.get(OpcConnection, conn_id)
        assert connection is not None
        for field, value in changes.items():
            setattr(connection, field, value)
        await session.commit()


async def set_project_active(
    factory: async_sessionmaker[AsyncSession], project_id: int, *, is_active: bool
) -> None:
    async with factory() as session:
        project = await session.get(Project, project_id)
        assert project is not None
        project.is_active = is_active
        await session.commit()


def make_supervisor(
    factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    state: WorkerState,
    *,
    poll_interval_s: float = TEST_POLL_INTERVAL_S,
) -> Supervisor:
    return Supervisor(factory, redis_client, state, poll_interval_s=poll_interval_s)


@asynccontextmanager
async def started(supervisor: Supervisor) -> AsyncIterator[Supervisor]:
    await supervisor.start()
    try:
        yield supervisor
    finally:
        await supervisor.stop()


def only_runtime(supervisor: Supervisor):
    """Runtime único do supervisor; falha alto se o diff criou mais de um."""
    runtimes = list(supervisor.runtimes.values())
    assert len(runtimes) == 1, f"esperava 1 runtime, achei {len(supervisor.runtimes)}"
    return runtimes[0]


async def wait_up(supervisor: Supervisor, conn_id: int) -> None:
    await await_until(
        lambda: (
            conn_id in supervisor.runtimes
            and supervisor.runtimes[conn_id].state is ConnectionState.UP
        )
    )


def _tasks_do_worker() -> list[asyncio.Task]:
    """Tasks vivas do worker: nenhuma pode sobrar depois de um `stop()`."""
    return [
        task
        for task in asyncio.all_tasks()
        if task.get_name().startswith(("opc-conn-", "opc-heartbeat-", "supervisor-"))
        and not task.done()
    ]


class ExplodingRuntime:
    """Dublê de runtime que falha ao parar (ex.: disconnect travado no transporte)."""

    def __init__(self, config: ConnectionConfig) -> None:
        self.config = config
        self.stop_calls = 0

    async def stop(self) -> None:
        self.stop_calls += 1
        raise RuntimeError("stop explodiu")


class CancellingRuntime:
    """Dublê cujo `stop()` é cancelado por fora (task interna morta no meio)."""

    def __init__(self, config: ConnectionConfig) -> None:
        self.config = config
        self.stop_calls = 0

    async def stop(self) -> None:
        self.stop_calls += 1
        raise asyncio.CancelledError


class _BrokenPubSub:
    """Assinante que morre na primeira escuta, como numa queda de conexão do Redis."""

    def __init__(self, inner: PubSub, owner: FlakyRedis) -> None:
        self._inner = inner
        self._owner = owner

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def listen(self) -> AsyncIterator[dict]:
        async def _cai() -> AsyncIterator[dict]:
            self._owner.broken_listens += 1
            raise ConnectionError("queda simulada do Redis")
            yield {}  # pragma: no cover - torna a função um gerador assíncrono

        return _cai()


class FlakyRedis:
    """Cliente cujo primeiro `pubsub()` devolve um assinante que cai ao escutar."""

    def __init__(self, inner: Redis) -> None:
        self._inner = inner
        self.pubsub_calls = 0
        self.broken_listens = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def pubsub(self) -> PubSub:
        self.pubsub_calls += 1
        pubsub = self._inner.pubsub()
        if self.pubsub_calls == 1:
            return _BrokenPubSub(pubsub, self)  # type: ignore[return-value]
        return pubsub


class _EmptyPubSub:
    """Assinante cuja escuta termina limpa na hora, sem levantar nada."""

    def __init__(self, inner: PubSub) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def listen(self) -> AsyncIterator[dict]:
        async def _encerra() -> AsyncIterator[dict]:
            return
            yield {}  # pragma: no cover - torna a função um gerador assíncrono

        return _encerra()


class ClosingRedis:
    """Cliente cujo `pubsub()` sempre devolve assinante que encerra a escuta na hora."""

    def __init__(self, inner: Redis) -> None:
        self._inner = inner
        self.pubsub_calls = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def pubsub(self) -> PubSub:
        self.pubsub_calls += 1
        return _EmptyPubSub(self._inner.pubsub())  # type: ignore[return-value]


@dataclass
class Contador:
    """Contador observável, para provar (ou negar) um efeito sem esperar tempo."""

    total: int = 0


def contar_passadas(monkeypatch: pytest.MonkeyPatch) -> Contador:
    """Conta passadas de reconciliação CONCLUÍDAS, inclusive as que saem no watermark.

    Incrementar só no fim é o que torna o contador utilizável como barreira: `total >= n`
    garante que a passada terminou, não que ela começou.
    """
    contador = Contador()
    original = Supervisor._pass

    async def _contando(self: Supervisor, *, force: bool) -> None:
        await original(self, force=force)
        contador.total += 1

    monkeypatch.setattr(Supervisor, "_pass", _contando)
    return contador


def contar_mensagens_vistas(monkeypatch: pytest.MonkeyPatch) -> Contador:
    """Conta mensagens do canal já classificadas pelo assinante."""
    contador = Contador()
    original = supervisor_module._is_hint

    def _contando(data: str) -> bool:
        contador.total += 1
        return original(data)

    monkeypatch.setattr(supervisor_module, "_is_hint", _contando)
    return contador


async def publicar_dica(redis_client: Redis, kind: str, conn_id: int) -> None:
    """Publica no canal `events` um evento de auditoria com o `kind` pedido."""
    await publish_event(
        redis_client,
        severity="info",
        origin="api",
        message=f"Evento {kind}",
        kind=kind,
        payload={"conn_id": conn_id},
    )


# --- watermark ---------------------------------------------------------------------


async def test_watermark_sem_projeto_ativo_e_vazio(
    session_factory: async_sessionmaker[AsyncSession], sim: OpcSimServer
) -> None:
    """ADR-017: sem projeto ativo não há id nem contagem — nada a supervisionar."""
    project_id = await create_project(session_factory, is_active=False)
    await create_connection(session_factory, project_id, sim.endpoint)

    async with session_factory() as session:
        watermark = await read_watermark(session)
        configs = await load_active_configuration(session)

    assert watermark.project_id is None
    assert watermark.connections_count == 0
    assert watermark.tags_count == 0
    assert watermark.connections_max_updated_at is None
    assert watermark.tags_max_updated_at is None
    assert configs == ()


async def test_watermark_conta_somente_o_projeto_ativo(
    session_factory: async_sessionmaker[AsyncSession], sim: OpcSimServer
) -> None:
    """Conexões e tags de outro projeto não podem mexer no watermark do ativo."""
    ativo = await create_project(session_factory, name="Ativo", is_active=True)
    inativo = await create_project(session_factory, name="Inativo", is_active=False)
    conn_ativo = await create_connection(session_factory, ativo, sim.endpoint, name="A")
    await create_tag(session_factory, conn_ativo, name="T", node_id=NODE_STATIC)
    conn_inativo = await create_connection(session_factory, inativo, sim.endpoint, name="B")
    await create_tag(session_factory, conn_inativo, name="T", node_id=NODE_STATIC)

    async with session_factory() as session:
        watermark = await read_watermark(session)

    assert watermark.project_id == ativo
    assert watermark.connections_count == 1
    assert watermark.tags_count == 1


async def test_watermark_igual_nao_recria_nada(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sim: OpcSimServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Banco parado ⇒ nem carrega config nem toca no runtime ou na sessão (spec §2.2-1)."""
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id, sim.endpoint)
    state = WorkerState()
    supervisor = make_supervisor(session_factory, redis_client, state)

    async with started(supervisor):
        await wait_up(supervisor, conn_id)
        runtime = supervisor.runtimes[conn_id]
        subiu_em = runtime.snapshot.session_up_since

        async with session_factory() as session:
            primeiro = await read_watermark(session)
        async with session_factory() as session:
            segundo = await read_watermark(session)
        assert primeiro == segundo

        cargas = 0

        async def _contando(session: AsyncSession) -> tuple:
            nonlocal cargas
            cargas += 1
            return await load_active_configuration(session)

        monkeypatch.setattr(supervisor_module, "load_active_configuration", _contando)
        await asyncio.sleep(QUIET_WINDOW_S)  # vários ciclos do poll curto

        assert cargas == 0, "watermark igual não pode carregar a configuração"
        assert supervisor.runtimes[conn_id] is runtime
        assert runtime.snapshot.session_up_since == subiu_em
        assert state.connections[conn_id] is runtime.snapshot

        # Controle positivo: o contador está no caminho — mudança no banco carrega config.
        await create_tag(session_factory, conn_id, name="Nível", node_id=NODE_STATIC)
        await await_until(lambda: cargas >= 1)


# --- reconciliação -----------------------------------------------------------------


async def test_cria_conexao_e_o_runtime_nasce(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Redis, sim: OpcSimServer
) -> None:
    """Conexão no banco ⇒ runtime vivo, snapshot no /health e sessão `up`."""
    project_id = await create_project(session_factory)
    state = WorkerState()
    supervisor = make_supervisor(session_factory, redis_client, state)

    async with started(supervisor):
        await await_until(lambda: supervisor.runtimes == {}, timeout_s=1.0)
        conn_id = await create_connection(session_factory, project_id, sim.endpoint)
        await wait_up(supervisor, conn_id)

        assert set(supervisor.runtimes) == {conn_id}
        assert conn_id in state.connections
        assert state.connections[conn_id].name == "Forno 1"
        assert state.connections[conn_id].state is ConnectionState.UP


async def test_tag_nova_recria_apenas_a_subscription(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Redis, sim: OpcSimServer
) -> None:
    """Mudança só de tags ⇒ subscription nova, sessão preservada (spec §2.2-1)."""
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id, sim.endpoint)
    await create_tag(session_factory, conn_id, name="Nível", node_id=NODE_STATIC)
    state = WorkerState()
    supervisor = make_supervisor(session_factory, redis_client, state)

    async with started(supervisor):
        await wait_up(supervisor, conn_id)
        runtime = supervisor.runtimes[conn_id]
        await await_until(lambda: runtime.snapshot.tags_subscribed == 1)
        subiu_em = runtime.snapshot.session_up_since

        async with collecting(redis_client, channel_opc_values(conn_id)) as valores:
            tag_id = await create_tag(session_factory, conn_id, name="Temp", node_id=NODE_SINE)
            await await_until(lambda: any(v["tag_id"] == tag_id for v in valores))

        assert supervisor.runtimes[conn_id] is runtime, "a sessão não deveria ter sido recriada"
        assert runtime.snapshot.session_up_since == subiu_em
        assert runtime.snapshot.tags_subscribed == 2


async def test_campo_da_conexao_recria_a_sessao(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Redis, sim: OpcSimServer
) -> None:
    """Mudança em campo da conexão ⇒ sessão nova (session_key mudou)."""
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id, sim.endpoint)
    state = WorkerState()
    supervisor = make_supervisor(session_factory, redis_client, state)

    async with started(supervisor):
        await wait_up(supervisor, conn_id)
        antigo = supervisor.runtimes[conn_id]
        subiu_em = antigo.snapshot.session_up_since

        await update_connection(session_factory, conn_id, watchdog_period_ms=2000)
        await await_until(lambda: supervisor.runtimes.get(conn_id) is not antigo)
        await wait_up(supervisor, conn_id)

        novo = supervisor.runtimes[conn_id]
        assert novo.config.watchdog_period_ms == 2000
        assert novo.snapshot.session_up_since != subiu_em
        assert state.connections[conn_id] is novo.snapshot
        assert antigo.state is not ConnectionState.UP or antigo.client is None


async def test_falha_pendente_atravessa_a_troca_de_sessao(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Redis, sim: OpcSimServer
) -> None:
    """`comm_failure` publicado sobrevive ao remonte: quem edita a conexão para resolver a
    causa (confiar no certificado, reinformar a senha) precisa receber o `comm_restored`
    quando a sessão nova sobe. Sem herdar a aresta, o runtime novo nasce limpo, o
    `mark_restored` de `_open_session` volta cedo e o alarme antigo fica na tela para
    sempre — achado do gate L3 (cenário B-F6-04 passo 3)."""
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id, sim.endpoint)
    state = WorkerState()
    supervisor = make_supervisor(session_factory, redis_client, state)

    async with started(supervisor):
        await wait_up(supervisor, conn_id)
        antigo = supervisor.runtimes[conn_id]

        async with collecting(redis_client, CHANNEL_EVENTS) as eventos:
            await antigo.fail("cert_missing", "falha forjada pelo teste")
            assert antigo.failure_pending is True

            await update_connection(session_factory, conn_id, watchdog_period_ms=2000)
            await await_until(lambda: supervisor.runtimes.get(conn_id) is not antigo)
            novo = supervisor.runtimes[conn_id]
            assert novo is not antigo
            await wait_up(supervisor, conn_id)

            # A asserção que importa: o evento sai. `failure_pending` sozinho passaria
            await await_until(
                lambda: any(
                    (e.get("payload") or {}).get("kind") == KIND_COMM_RESTORED for e in eventos
                )
            )
        assert novo.failure_pending is False


async def test_projeto_desativado_derruba_tudo(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Redis, sim: OpcSimServer
) -> None:
    """ADR-017: sem projeto ativo ⇒ zero sessões e /health sem conexão."""
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id, sim.endpoint)
    state = WorkerState()
    supervisor = make_supervisor(session_factory, redis_client, state)

    async with started(supervisor):
        await wait_up(supervisor, conn_id)
        await set_project_active(session_factory, project_id, is_active=False)
        await await_until(lambda: supervisor.runtimes == {})
        assert state.connections == {}


async def test_teto_de_conexoes_sobe_as_cinco_primeiras(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Redis, sim: OpcSimServer
) -> None:
    """RF-201: seis conexões configuradas ⇒ exatamente cinco supervisionadas."""
    project_id = await create_project(session_factory)
    ids = [
        await create_connection(session_factory, project_id, sim.endpoint, name=f"Conexão {n}")
        for n in range(6)
    ]
    state = WorkerState()
    supervisor = make_supervisor(session_factory, redis_client, state)

    async with started(supervisor):
        await await_until(lambda: len(supervisor.runtimes) == MAX_CONNECTIONS)
        await asyncio.sleep(QUIET_WINDOW_S)  # o excedente não entra num ciclo seguinte
        assert sorted(supervisor.runtimes) == sorted(ids)[:MAX_CONNECTIONS]
        assert sorted(state.connections) == sorted(ids)[:MAX_CONNECTIONS]


async def test_stop_e_idempotente_e_derruba_os_runtimes(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Redis, sim: OpcSimServer
) -> None:
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id, sim.endpoint)
    state = WorkerState()
    supervisor = make_supervisor(session_factory, redis_client, state)

    await supervisor.start()
    await wait_up(supervisor, conn_id)
    await supervisor.stop()
    await supervisor.stop()

    assert supervisor.runtimes == {}
    assert state.connections == {}
    assert _tasks_do_worker() == []


async def test_stop_isola_falha_de_um_runtime(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Redis, sim: OpcSimServer
) -> None:
    """Runtime que explode no stop() não pode deixar os outros vivos nem travar o mapa.

    Runtime sobrevivente a um `stop()` seria sessão OPC órfã: fala com o PLC sem
    supervisor. E entrada que ficasse no mapa travaria toda reconciliação futura.
    """
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id, sim.endpoint)
    state = WorkerState()
    supervisor = make_supervisor(session_factory, redis_client, state)

    await supervisor.start()
    await wait_up(supervisor, conn_id)

    explosivo = ExplodingRuntime(supervisor.runtimes[conn_id].config)
    supervisor.runtimes[MISSING_CONN_ID] = explosivo  # type: ignore[index]
    state.connections[MISSING_CONN_ID] = ConnectionSnapshot(name="Explosiva")

    await supervisor.stop()  # não pode propagar

    assert explosivo.stop_calls == 1, "o stop() do runtime quebrado tem de ser tentado"
    assert supervisor.runtimes == {}, "a entrada quebrada sai do mapa mesmo em falha"
    assert state.connections == {}
    assert _tasks_do_worker() == [], "o runtime saudável tem de ter sido parado"

    await supervisor.stop()  # idempotente mesmo depois da falha
    assert supervisor.runtimes == {}


async def test_stop_loga_desmonte_cancelado_por_fora(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sim: OpcSimServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cancelamento de um desmonte isolado não pode sumir sem rastro no gather."""
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id, sim.endpoint)
    state = WorkerState()
    supervisor = make_supervisor(session_factory, redis_client, state)

    await supervisor.start()
    await wait_up(supervisor, conn_id)

    cancelado = CancellingRuntime(supervisor.runtimes[conn_id].config)
    supervisor.runtimes[MISSING_CONN_ID] = cancelado  # type: ignore[index]
    state.connections[MISSING_CONN_ID] = ConnectionSnapshot(name="Cancelada")

    with caplog.at_level(logging.WARNING, logger="ottima_opc_worker.supervisor"):
        await supervisor.stop()  # não pode propagar

    assert cancelado.stop_calls == 1
    assert any(
        record.levelno == logging.WARNING and str(MISSING_CONN_ID) in record.getMessage()
        for record in caplog.records
    ), "o cancelamento do desmonte tem de aparecer no log"
    assert supervisor.runtimes == {}
    assert state.connections == {}
    assert _tasks_do_worker() == [], "o runtime saudável tem de ter sido parado"


async def test_reassinatura_limpa_respeita_o_freio(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`listen()` que termina limpo não pode virar rajada de reassinatura queimando CPU."""
    monkeypatch.setattr(supervisor_module, "HINT_RETRY_S", FREIO_S)
    state = WorkerState()
    fechando = ClosingRedis(redis_client)
    supervisor = Supervisor(
        session_factory,
        fechando,  # type: ignore[arg-type]
        state,
        poll_interval_s=SLOW_POLL_INTERVAL_S,
    )

    async with started(supervisor):
        await asyncio.sleep(JANELA_DO_FREIO_S)

    # 1 assinatura do start() + no máximo uma por freio na janela (folga de 2 para o
    # escalonamento do event loop). Sem freio seriam centenas.
    teto = 1 + int(JANELA_DO_FREIO_S / FREIO_S) + 2
    assert 2 <= fechando.pubsub_calls <= teto, (
        f"reassinaturas fora do esperado: {fechando.pubsub_calls} (teto {teto})"
    )


async def test_assinante_sobrevive_a_queda_do_redis(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sim: OpcSimServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queda do Redis não pode matar a task de dicas: ela reassina e volta a disparar.

    Perder dica é inofensivo (o poll corrige), mas a morte silenciosa da task degradaria
    o sistema para o poll de 10 s sem ninguém saber.
    """
    monkeypatch.setattr(supervisor_module, "HINT_RETRY_S", 0.05)
    project_id = await create_project(session_factory)
    state = WorkerState()
    flaky = FlakyRedis(redis_client)
    supervisor = Supervisor(
        session_factory,
        flaky,  # type: ignore[arg-type]
        state,
        poll_interval_s=SLOW_POLL_INTERVAL_S,
    )

    async with started(supervisor):
        # A primeira escuta morre com erro de conexão; o laço tem de reassinar.
        await await_until(lambda: flaky.pubsub_calls >= 2, timeout_s=HINT_TIMEOUT_S)
        assert flaky.broken_listens == 1
        vivas = [task.get_name() for task in _tasks_do_worker()]
        assert "supervisor-hints" in vivas, "a task de dicas morreu na queda do Redis"

        conn_id = await create_connection(session_factory, project_id, sim.endpoint)
        # Republica a dica até a assinatura nova pegá-la: `subscribe()` do redis-py não
        # espera confirmação do servidor, e dica repetida é inofensiva por contrato.
        # Poll de 60 s: se o runtime nasce, foi a dica pela assinatura nova.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + HINT_TIMEOUT_S
        while conn_id not in supervisor.runtimes and loop.time() < deadline:
            await publish_event(
                redis_client,
                severity="info",
                origin="api",
                message="Conexão criada",
                kind=KIND_CONNECTION_CREATED,
                payload={"conn_id": conn_id},
            )
            await asyncio.sleep(0.1)
        assert conn_id in supervisor.runtimes, "a dica não voltou depois da reassinatura"


# --- dica pelo canal `events` -------------------------------------------------------


async def test_dica_dispara_reconcile_imediato(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sim: OpcSimServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kind de auditoria antecipa o reconcile, sem esperar o poll (spec §2.2-1).

    A conexão só é criada DEPOIS da passada inicial ter terminado (contador de passadas
    concluídas): com poll de 60 s, o runtime nascer prova que a dica foi o gatilho, e não
    uma passada que já estava em voo.
    """
    passadas = contar_passadas(monkeypatch)
    project_id = await create_project(session_factory)
    state = WorkerState()
    supervisor = make_supervisor(
        session_factory, redis_client, state, poll_interval_s=SLOW_POLL_INTERVAL_S
    )

    async with started(supervisor):
        await await_until(lambda: passadas.total >= 1)
        assert supervisor.runtimes == {}

        conn_id = await create_connection(session_factory, project_id, sim.endpoint, name="A")
        await publicar_dica(redis_client, KIND_CONNECTION_CREATED, conn_id)
        await await_until(lambda: conn_id in supervisor.runtimes, timeout_s=HINT_TIMEOUT_S)


async def test_kind_fora_de_hint_kinds_nao_dispara_reconcile(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    sim: OpcSimServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mensagem fora de HINT_KINDS não reconcilia — provado sem janela de tempo.

    A prova é por contadores, não por espera: `vistas` confirma que o assinante processou
    as mensagens (senão o teste não teria observado nada) e `passadas` confirma que nenhuma
    reconciliação rodou. Nenhuma dica é publicada antes disso, então não existe passada
    pendente que possa subir a conexão por outro caminho — foi exatamente essa corrida que
    avermelhou a versão anterior deste teste.
    """
    passadas = contar_passadas(monkeypatch)
    vistas = contar_mensagens_vistas(monkeypatch)
    project_id = await create_project(session_factory)
    state = WorkerState()
    supervisor = make_supervisor(
        session_factory, redis_client, state, poll_interval_s=SLOW_POLL_INTERVAL_S
    )

    async with started(supervisor):
        # Passada inicial concluída: daqui em diante só uma dica pode disparar outra.
        await await_until(lambda: passadas.total >= 1)
        conn_id = await create_connection(session_factory, project_id, sim.endpoint, name="A")
        passadas_antes = passadas.total

        await publicar_dica(redis_client, KIND_OPC_WRITE, conn_id)
        await redis_client.publish(CHANNEL_EVENTS, "isto nao e um EventMessage")
        await await_until(lambda: vistas.total >= 2)

        assert passadas.total == passadas_antes, "kind fora de HINT_KINDS não pode reconciliar"
        assert conn_id not in supervisor.runtimes
        assert state.connections == {}

        # Controle positivo: o mesmo aparato detecta o reconcile quando o kind É dica.
        await publicar_dica(redis_client, KIND_CONNECTION_CREATED, conn_id)
        await await_until(lambda: conn_id in supervisor.runtimes, timeout_s=HINT_TIMEOUT_S)
        assert passadas.total > passadas_antes


async def test_reconcile_direto_e_idempotente(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Redis, sim: OpcSimServer
) -> None:
    """`reconcile()` é chamável sem o loop e a segunda passada não recria nada."""
    project_id = await create_project(session_factory)
    conn_id = await create_connection(session_factory, project_id, sim.endpoint)
    state = WorkerState()
    supervisor = make_supervisor(session_factory, redis_client, state)

    try:
        await supervisor.reconcile()
        runtime = only_runtime(supervisor)
        await wait_up(supervisor, conn_id)
        subiu_em = runtime.snapshot.session_up_since

        await supervisor.reconcile()
        assert only_runtime(supervisor) is runtime
        assert runtime.snapshot.session_up_since == subiu_em
    finally:
        await supervisor.stop()
