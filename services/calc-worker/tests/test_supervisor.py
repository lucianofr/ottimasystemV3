"""Testes do supervisor do calc-worker (ADR-033): reconciliação banco -> `CalcTagRunner`.

Timescale e Redis reais via `conftest.py` — o supervisor lê o banco de verdade e publica
no barramento de verdade; um dublê de sessão não provaria que o diff sobrevive a um commit
alheio (a mesma razão do `test_supervisor.py` do opc-worker).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ottima_calc_worker.runner import CalcTagRunner
from ottima_calc_worker.supervisor import Supervisor
from ottima_core.models import CalculatedTag, CalculatedTagInput, OpcConnection, Project, Tag
from ottima_core.script_pool import ScriptPool
from ottima_core.snapshot import ValueSnapshot
from testkit.await_until import await_until

# Poll curto: a reconciliação dos testes vem do loop, não de chamada direta.
TEST_POLL_INTERVAL_S = 0.2
# Janela para provar que algo NÃO acontece (vários ciclos do poll curto).
QUIET_WINDOW_S = 1.0


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
        # CASCADE alcança calculated_tags/calculated_tag_inputs via FK em `tags`.
        await session.execute(text("TRUNCATE tags, projects CASCADE"))
        await session.commit()


@pytest.fixture
async def pool() -> AsyncIterator[ScriptPool]:
    p = ScriptPool(size=2)
    await p.start()
    yield p
    await p.stop()


@pytest.fixture
async def snapshot(redis_client: Redis) -> AsyncIterator[ValueSnapshot]:
    s = ValueSnapshot(redis_client)
    await s.start()
    yield s
    await s.stop()


async def create_project(
    factory: async_sessionmaker[AsyncSession], *, name: str = "Projeto", is_active: bool = True
) -> int:
    async with factory() as session:
        project = Project(name=name, description="", is_active=is_active)
        session.add(project)
        await session.commit()
        return project.id


async def create_opc_tag(
    factory: async_sessionmaker[AsyncSession], project_id: int, *, name: str
) -> int:
    """Tag OPC serve de fonte para as entradas: precisa de conexão, ao contrário da calculada."""
    async with factory() as session:
        conn = OpcConnection(
            project_id=project_id,
            name=f"conexao-{name}",
            endpoint="opc.tcp://localhost:4840",
        )
        session.add(conn)
        await session.flush()
        tag = Tag(
            connection_id=conn.id,
            project_id=None,
            name=name,
            node_id=f"ns=2;s={name}",
            direction="r",
            data_type="float",
            eu="",
            description="",
        )
        session.add(tag)
        await session.commit()
        return tag.id


async def create_calc_tag(
    factory: async_sessionmaker[AsyncSession],
    project_id: int,
    *,
    name: str,
    code: str = "OUT = 1.0\n",
    period_seconds: int = 1,
    input_tag_ids: Sequence[int] = (),
) -> int:
    async with factory() as session:
        tag = Tag(
            connection_id=None,
            project_id=project_id,
            name=name,
            node_id=None,
            direction="r",
            data_type="float",
            eu="",
            description="",
        )
        session.add(tag)
        await session.flush()
        session.add(CalculatedTag(tag_id=tag.id, code=code, period_seconds=period_seconds))
        for position, source_tag_id in enumerate(input_tag_ids, start=1):
            session.add(
                CalculatedTagInput(
                    calc_tag_id=tag.id, position=position, source_tag_id=source_tag_id
                )
            )
        await session.commit()
        return tag.id


async def update_calc_tag(
    factory: async_sessionmaker[AsyncSession], tag_id: int, **changes: object
) -> None:
    async with factory() as session:
        calc_tag = await session.get(CalculatedTag, tag_id)
        for key, value in changes.items():
            setattr(calc_tag, key, value)
        await session.commit()


async def delete_tag(factory: async_sessionmaker[AsyncSession], tag_id: int) -> None:
    async with factory() as session:
        tag = await session.get(Tag, tag_id)
        await session.delete(tag)
        await session.commit()


def make_supervisor(
    factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    pool: ScriptPool,
    snapshot: ValueSnapshot,
    *,
    poll_interval_s: float = TEST_POLL_INTERVAL_S,
) -> Supervisor:
    return Supervisor(
        factory, redis_client, pool=pool, snapshot=snapshot, poll_interval_s=poll_interval_s
    )


@asynccontextmanager
async def started(supervisor: Supervisor) -> AsyncIterator[Supervisor]:
    await supervisor.start()
    try:
        yield supervisor
    finally:
        await supervisor.stop()


def _tasks_do_worker() -> list[asyncio.Task]:
    """Tasks vivas do calc-worker: nenhuma pode sobrar depois de um `stop()`."""
    return [
        task
        for task in asyncio.all_tasks()
        if task.get_name().startswith(("calc-tag-", "calc-supervisor-")) and not task.done()
    ]


async def test_uma_task_por_tag_calculada_com_nomes_esperados(
    session_factory, redis_client, pool, snapshot
):
    project_id = await create_project(session_factory)
    tag_a = await create_calc_tag(session_factory, project_id, name="a")
    tag_b = await create_calc_tag(session_factory, project_id, name="b")

    supervisor = make_supervisor(session_factory, redis_client, pool, snapshot)
    async with started(supervisor):
        await await_until(lambda: tag_a in supervisor.runners and tag_b in supervisor.runners)
        nomes = {task.get_name() for task in _tasks_do_worker()}
        assert f"calc-tag-{tag_a}" in nomes
        assert f"calc-tag-{tag_b}" in nomes


async def test_tag_de_projeto_inativo_nao_roda(session_factory, redis_client, pool, snapshot):
    project_id = await create_project(session_factory, is_active=False)
    tag_id = await create_calc_tag(session_factory, project_id, name="a")

    supervisor = make_supervisor(session_factory, redis_client, pool, snapshot)
    async with started(supervisor):
        await asyncio.sleep(QUIET_WINDOW_S)
        assert tag_id not in supervisor.runners
        assert f"calc-tag-{tag_id}" not in {task.get_name() for task in _tasks_do_worker()}


async def test_criar_tag_spawna_a_task_dentro_do_reconcile(
    session_factory, redis_client, pool, snapshot
):
    project_id = await create_project(session_factory)

    supervisor = make_supervisor(session_factory, redis_client, pool, snapshot)
    async with started(supervisor):
        tag_id = await create_calc_tag(session_factory, project_id, name="nova")
        await await_until(lambda: tag_id in supervisor.runners)
        assert f"calc-tag-{tag_id}" in {task.get_name() for task in _tasks_do_worker()}


async def test_apagar_tag_desmonta_a_task_sem_vazar(session_factory, redis_client, pool, snapshot):
    project_id = await create_project(session_factory)
    tag_id = await create_calc_tag(session_factory, project_id, name="efêmera")

    supervisor = make_supervisor(session_factory, redis_client, pool, snapshot)
    async with started(supervisor):
        await await_until(lambda: tag_id in supervisor.runners)

        await delete_tag(session_factory, tag_id)

        await await_until(lambda: tag_id not in supervisor.runners)
        assert f"calc-tag-{tag_id}" not in {task.get_name() for task in _tasks_do_worker()}


async def test_mudar_periodo_reinicia_apenas_aquela_tag(
    session_factory, redis_client, pool, snapshot
):
    project_id = await create_project(session_factory)
    tag_a = await create_calc_tag(session_factory, project_id, name="a", period_seconds=1)
    tag_b = await create_calc_tag(session_factory, project_id, name="b", period_seconds=1)

    supervisor = make_supervisor(session_factory, redis_client, pool, snapshot)
    async with started(supervisor):
        await await_until(lambda: tag_a in supervisor.runners and tag_b in supervisor.runners)
        runner_a_antes = supervisor.runners[tag_a]
        runner_b_antes = supervisor.runners[tag_b]

        await update_calc_tag(session_factory, tag_a, period_seconds=2)

        await await_until(lambda: supervisor.runners.get(tag_a) is not runner_a_antes)
        assert supervisor.runners[tag_b] is runner_b_antes, "a tag não editada não pode reiniciar"


async def reordenar_entradas(
    factory: async_sessionmaker[AsyncSession], tag_id: int, ordem: Sequence[int]
) -> None:
    """Reescreve as entradas na ordem dada, como faz o PATCH da API: apaga tudo e reinsere.

    Não toca em `calculated_tags` — é justamente o caso que uma contagem no watermark perde.
    """
    async with factory() as session:
        await session.execute(
            delete(CalculatedTagInput).where(CalculatedTagInput.calc_tag_id == tag_id)
        )
        await session.flush()
        for position, source_tag_id in enumerate(ordem, start=1):
            session.add(
                CalculatedTagInput(
                    calc_tag_id=tag_id, position=position, source_tag_id=source_tag_id
                )
            )
        await session.commit()


async def test_reordenar_entradas_reinicia_o_runner(session_factory, redis_client, pool, snapshot):
    """Trocar IN1 por IN2 muda o cálculo sem mudar contagem nem `calculated_tags.updated_at`.

    Com contagem no watermark a passada de reconciliação não via diferença nenhuma e o runner
    seguia calculando na ordem velha — silenciosamente, até uma outra edição qualquer.
    """
    project_id = await create_project(session_factory)
    fonte_a = await create_opc_tag(session_factory, project_id, name="fonte_a")
    fonte_b = await create_opc_tag(session_factory, project_id, name="fonte_b")
    tag_id = await create_calc_tag(
        session_factory,
        project_id,
        name="dividida",
        code="OUT = IN1 - IN2\n",
        input_tag_ids=(fonte_a, fonte_b),
    )

    supervisor = make_supervisor(session_factory, redis_client, pool, snapshot)
    async with started(supervisor):
        await await_until(lambda: tag_id in supervisor.runners)
        runner_antes = supervisor.runners[tag_id]

        await reordenar_entradas(session_factory, tag_id, (fonte_b, fonte_a))

        await await_until(lambda: supervisor.runners.get(tag_id) is not runner_antes)
        _code, _period, entradas = supervisor.runners[tag_id].restart_key
        assert entradas == (fonte_b, fonte_a)


async def test_runner_que_explode_nao_para_a_supervisao_nem_a_irma(
    session_factory, redis_client, pool, snapshot, monkeypatch
):
    """Um bug real (não erro de script — esse já é tratado por `_report_failure`) dentro do
    ciclo não pode matar a `asyncio.Task`: ela seguiria supervisionada, só sem produzir
    valor, e a tag irmã tem de continuar publicando normalmente."""
    project_id = await create_project(session_factory)
    quebrada_id = await create_calc_tag(session_factory, project_id, name="quebrada")
    boa_id = await create_calc_tag(session_factory, project_id, name="boa")

    original = CalcTagRunner._collect_inputs

    def _collect_inputs_quebrado(self: CalcTagRunner):
        if self._tag_id == quebrada_id:
            raise RuntimeError("bug interno, não erro de script")
        return original(self)

    monkeypatch.setattr(CalcTagRunner, "_collect_inputs", _collect_inputs_quebrado)

    supervisor = make_supervisor(session_factory, redis_client, pool, snapshot)
    async with started(supervisor):
        await await_until(
            lambda: quebrada_id in supervisor.runners and boa_id in supervisor.runners
        )
        await await_until(lambda: supervisor.runners[boa_id].health.last_status == "ok")

        nomes = {task.get_name() for task in _tasks_do_worker()}
        assert f"calc-tag-{quebrada_id}" in nomes, "a task quebrada não pode ter morrido"
        assert f"calc-tag-{boa_id}" in nomes


async def test_stop_e_idempotente_e_nao_deixa_task_calc_tag_viva(
    session_factory, redis_client, pool, snapshot
):
    project_id = await create_project(session_factory)
    tag_a = await create_calc_tag(session_factory, project_id, name="a")
    tag_b = await create_calc_tag(session_factory, project_id, name="b")

    supervisor = make_supervisor(session_factory, redis_client, pool, snapshot)
    await supervisor.start()
    await await_until(lambda: tag_a in supervisor.runners and tag_b in supervisor.runners)

    await supervisor.stop()
    await supervisor.stop()  # idempotente

    assert supervisor.runners == {}
    assert _tasks_do_worker() == []
