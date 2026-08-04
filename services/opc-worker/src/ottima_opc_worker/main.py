"""Serviço opc-worker: lifespan com supervisor e `/health` por conexão (RNF-07).

O supervisor (spec F2 §2.2-1) é o dono das sessões OPC-UA; o `WorkerState` que ele
alimenta é a fonte única do `/health`. `status` reflete só as dependências do serviço
(Redis/banco): PLC desligado é condição operacional, não unhealth do worker — o
healthcheck do compose não pode reiniciar o processo por causa disso (spec F2 §2.2-8).
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from sqlalchemy import text

from ottima_core.config import get_settings
from ottima_core.db import create_engine, create_session_factory
from ottima_core.logging import setup_logging
from ottima_opc_worker.state import WorkerState
from ottima_opc_worker.supervisor import Supervisor

logger = logging.getLogger(__name__)

SERVICE_NAME = "opc-worker"
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
    """Sobe Redis, banco, supervisor e heartbeat; encerra na ordem inversa."""
    settings = get_settings()
    setup_logging(settings.log_level)
    # decode_responses=True é contrato do barramento na F2: consumidor recebe str
    client = redis.from_url(settings.redis_url, decode_responses=True)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    worker_state = WorkerState()
    app.state.worker_state = worker_state
    supervisor = Supervisor(
        session_factory,
        client,
        worker_state,
        certs_dir=settings.certs_dir,
        fernet_key=settings.fernet_key,
    )
    app.state.supervisor = supervisor
    try:
        await supervisor.start()
    except Exception:
        # Banco fora na subida não pode impedir o app de responder /health degradado ao
        # compose; o loop de poll do supervisor reconcilia quando o banco voltar.
        logger.exception("falha ao iniciar o supervisor; o worker sobe sem conexões")
    task = asyncio.create_task(_heartbeat_loop(client, session_factory, app))
    yield
    await supervisor.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await engine.dispose()
    await client.aclose()


app = FastAPI(title=f"OttimaSystem {SERVICE_NAME}", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Sempre 200: a degradação vai no corpo (spec F2 §2.2-8).

    Sem lifespan (app cru dos testes de unidade), os campos caem nos defaults do
    `getattr` e `connections` fica vazio.
    """
    redis_ok = getattr(app.state, "redis_ok", False)
    db_ok = getattr(app.state, "db_ok", False)
    worker_state = getattr(app.state, "worker_state", None)
    connections = {} if worker_state is None else worker_state.connections
    return {
        "status": "ok" if redis_ok and db_ok else "degraded",
        "service": SERVICE_NAME,
        "version": VERSION,
        # Chave string porque JSON não tem chave inteira; o corpo por conexão vem inteiro
        # do snapshot, sem remontagem aqui.
        "connections": {
            str(conn_id): snapshot.to_health() for conn_id, snapshot in connections.items()
        },
    }
