"""Serviço flow-runtime: lifespan com supervisor e `/health` por flow (RNF-07, spec F3 §2.2-10).

Substitui o esqueleto da F1. O supervisor (§2.2-1) é o dono das `FlowTask`; o `RuntimeState`
que ele alimenta é a fonte única do `/health`.

Duas regras herdadas do opc-worker, e as duas existem por causa do compose:

- **`status` reflete só as dependências do serviço** (Redis/banco). Flow em falha é condição
  operacional — alarme, não unhealth: o healthcheck não pode reiniciar o processo por causa de
  um flow (§2.2-10).
- **A subida do runtime não derruba o serviço.** Com Redis ou banco fora, o `/health` precisa
  responder `degraded` em lugar de o processo entrar em crash-loop. Por isso o `start()` é
  absorvido aqui: o `ValueSnapshot.start()` (tarefa 1.1) propaga falha de assinatura de
  propósito, e quem absorve é este módulo.
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
from ottima_flow_runtime.events import build_event_listener
from ottima_flow_runtime.script_pool import ScriptPool
from ottima_flow_runtime.snapshot import ValueSnapshot
from ottima_flow_runtime.state import RuntimeState
from ottima_flow_runtime.supervisor import Supervisor

logger = logging.getLogger(__name__)

SERVICE_NAME = "flow-runtime"
VERSION = "0.1.0"
HEARTBEAT_INTERVAL_S = 5.0


async def check_redis(client, app: FastAPI) -> None:
    """Faz ping no Redis e registra o resultado em app.state.redis_ok."""
    try:
        await client.ping()
        app.state.redis_ok = True
    except Exception:
        # Captura ampla proposital: nenhuma falha do heartbeat pode derrubar o runtime.
        app.state.redis_ok = False


async def check_database(session_factory, app: FastAPI) -> None:
    """Faz um SELECT 1 no banco e registra o resultado em app.state.db_ok."""
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        app.state.db_ok = True
    except Exception:
        # Captura ampla proposital: nenhuma falha do heartbeat pode derrubar o runtime.
        app.state.db_ok = False


async def _heartbeat_loop(client, session_factory, app: FastAPI) -> None:
    """Repete as checagens de dependência a cada HEARTBEAT_INTERVAL_S segundos."""
    while True:
        await check_redis(client, app)
        await check_database(session_factory, app)
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Sobe Redis, banco, espelho, pool, supervisor e heartbeat; encerra na ordem inversa."""
    settings = get_settings()
    setup_logging(settings.log_level)
    # decode_responses=True é contrato do barramento desde a F2: consumidor recebe str.
    client = redis.from_url(settings.redis_url, decode_responses=True)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    runtime_state = RuntimeState()
    app.state.runtime_state = runtime_state
    snapshot = ValueSnapshot(client)
    supervisor = Supervisor(
        session_factory,
        client,
        runtime_state,
        snapshot=snapshot,
        pool=ScriptPool(),
    )
    app.state.supervisor = supervisor
    events = build_event_listener(
        client,
        on_comm_failure=supervisor.on_comm_failure,
        on_project_activated=supervisor.on_project_activated,
    )
    app.state.events = events
    try:
        # O espelho antes do supervisor: bloco OPC-Read instanciado por um deploy já encontra
        # a assinatura de `opc.values.*` em pé.
        await snapshot.start()
        await supervisor.start()
        await events.start()
    except Exception:
        logger.exception("falha ao iniciar o runtime; o serviço sobe sem flows")
    task = asyncio.create_task(_heartbeat_loop(client, session_factory, app))
    yield
    # Assinante de eventos primeiro: vivo depois do supervisor, tentaria derrubar flow já
    # desmontado. O `ScriptPool` é encerrado dentro do `supervisor.stop()`, depois das
    # varreduras (achado da tarefa 1.3), e o espelho só depois de ninguém mais o ler.
    await events.stop()
    await supervisor.stop()
    await snapshot.stop()
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
    """Sempre 200: a degradação vai no corpo (spec §2.2-10).

    Sem lifespan (app cru dos testes de unidade), os campos caem nos defaults do `getattr` e
    `flows` fica vazio.
    """
    redis_ok = getattr(app.state, "redis_ok", False)
    db_ok = getattr(app.state, "db_ok", False)
    runtime_state = getattr(app.state, "runtime_state", None)
    flows = {} if runtime_state is None else runtime_state.flows
    return {
        "status": "ok" if redis_ok and db_ok else "degraded",
        "service": SERVICE_NAME,
        "version": VERSION,
        # Chave string porque JSON não tem chave inteira; o corpo por flow vem inteiro do
        # snapshot, sem remontagem aqui.
        "flows": {str(flow_id): snapshot.to_health() for flow_id, snapshot in flows.items()},
    }
