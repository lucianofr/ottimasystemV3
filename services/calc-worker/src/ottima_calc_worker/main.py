"""Serviço calc-worker: lifespan com supervisor e `/health` por tag calculada (ADR-033).

O supervisor é o dono dos `CalcTagRunner`; `runner.health` é a fonte do corpo por tag do
`/health`. `status` reflete só as dependências do serviço (Redis/banco): um script de
usuário travado ou em erro é condição operacional da tag, não unhealth do worker — o
healthcheck do compose não pode reiniciar o processo por causa disso (mesma regra do
opc-worker para um PLC desligado).
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from sqlalchemy import text

from ottima_calc_worker.supervisor import Supervisor
from ottima_core.bus import CHANNEL_CALC_VALUES
from ottima_core.config import get_settings
from ottima_core.db import create_engine, create_session_factory
from ottima_core.logging import setup_logging, watch_log_level
from ottima_core.script_pool import ScriptPool
from ottima_core.snapshot import VALUES_PATTERN, ValueSnapshot

logger = logging.getLogger(__name__)

SERVICE_NAME = "calc-worker"
VERSION = "0.1.0"
HEARTBEAT_INTERVAL_S = 5.0


async def check_redis(client, app: FastAPI) -> None:
    """Faz ping no Redis e registra o resultado em app.state.redis_ok."""
    try:
        await client.ping()
        app.state.redis_ok = True
    except Exception:
        # Captura ampla proposital: nenhuma falha do heartbeat pode derrubar o worker.
        app.state.redis_ok = False


async def check_database(session_factory, app: FastAPI) -> None:
    """Faz um SELECT 1 no banco e registra o resultado em app.state.db_ok."""
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        app.state.db_ok = True
    except Exception:
        # Captura ampla proposital: nenhuma falha do heartbeat pode derrubar o worker.
        app.state.db_ok = False


async def _heartbeat_loop(client, session_factory, app: FastAPI) -> None:
    """Repete as checagens de dependência a cada HEARTBEAT_INTERVAL_S segundos."""
    while True:
        await check_redis(client, app)
        await check_database(session_factory, app)
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Sobe Redis, banco, espelho, pool e supervisor; encerra na ordem inversa."""
    settings = get_settings()
    setup_logging(settings.log_level, SERVICE_NAME)
    # decode_responses=True é contrato do barramento na F2: consumidor recebe str
    client = redis.from_url(settings.redis_url, decode_responses=True)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    # Os dois padrões: `opc.values.*` para tags OPC e `calc.values` (canal fixo, sem
    # sufixo) para que uma tag calculada possa entrar como INn de outra (ADR-033 D5).
    snapshot = ValueSnapshot(client, patterns=(VALUES_PATTERN, CHANNEL_CALC_VALUES))
    pool = ScriptPool(size=settings.calc_pool_size)
    supervisor = Supervisor(session_factory, client, pool=pool, snapshot=snapshot)
    app.state.supervisor = supervisor
    await snapshot.start()
    await pool.start()
    try:
        await supervisor.start()
    except Exception:
        # Banco fora na subida não pode impedir o app de responder /health degradado ao
        # compose; o loop de poll do supervisor reconcilia quando o banco voltar.
        logger.exception("falha ao iniciar o supervisor; o calc-worker sobe sem tags calculadas")
    task = asyncio.create_task(_heartbeat_loop(client, session_factory, app))
    log_task = asyncio.create_task(watch_log_level(session_factory))
    yield
    # Supervisor primeiro: cancela as tasks `calc-tag-*` antes de derrubar o pool e o
    # espelho que elas usam, para nenhum runner chamar `pool.run()`/`snapshot.get()` num
    # recurso já fechado.
    await supervisor.stop()
    await pool.stop()
    await snapshot.stop()
    task.cancel()
    log_task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    try:
        await log_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()
    await client.aclose()


app = FastAPI(title=f"OttimaSystem {SERVICE_NAME}", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Sempre 200: a degradação vai no corpo.

    Sem lifespan (app cru dos testes de unidade), os campos caem nos defaults do
    `getattr` e `tags`/`script_pool` ficam vazios. Uma tag em erro/timeout NÃO degrada
    `status`: é condição operacional da tag, exatamente como um PLC desligado não degrada
    o opc-worker — só Redis/banco indisponíveis degradam o serviço.
    """
    redis_ok = getattr(app.state, "redis_ok", False)
    db_ok = getattr(app.state, "db_ok", False)
    supervisor = getattr(app.state, "supervisor", None)
    runners = {} if supervisor is None else supervisor.runners
    return {
        "status": "ok" if redis_ok and db_ok else "degraded",
        "service": SERVICE_NAME,
        "version": VERSION,
        # Chave string porque JSON não tem chave inteira; o corpo por tag vem inteiro do
        # snapshot do runner, sem remontagem aqui.
        "tags": {str(tag_id): runner.health.to_health() for tag_id, runner in runners.items()},
        "script_pool": {} if supervisor is None else supervisor.script_pool_stats(),
    }
