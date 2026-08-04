"""CRUD de conexões OPC-UA (RF-201, ADR-009/021): leitura para operador, escrita para admin."""

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_app_settings, get_db, get_redis, require_admin, require_operator
from ottima_core.bus import (
    KIND_CONNECTION_CREATED,
    KIND_CONNECTION_DELETED,
    KIND_CONNECTION_UPDATED,
    publish_event,
)
from ottima_core.config import Settings
from ottima_core.models import OpcConnection, Project, User
from ottima_core.schemas.connections import ConnectionCreate, ConnectionOut, ConnectionUpdate
from ottima_core.security import encrypt_secret

# Sem dependência no router: os papéis variam por rota (ADR-015)
router = APIRouter()

MAX_CONNECTIONS_PER_PROJECT = 5  # RF-201

# Mesmo texto do validator do ConnectionCreate (schemas/connections.py)
_MSG_POLICY_MODE = (
    "SecurityPolicy None exige modo None; Basic256Sha256 exige Sign ou SignAndEncrypt"
)


def _to_out(conn: OpcConnection) -> ConnectionOut:
    """Monta a saída campo a campo: `auth_password_enc` nunca pode escapar (spec §5.4)."""
    return ConnectionOut(
        id=conn.id,
        project_id=conn.project_id,
        name=conn.name,
        endpoint=conn.endpoint,
        security_policy=conn.security_policy,
        security_mode=conn.security_mode,
        auth_mode=conn.auth_mode,
        auth_username=conn.auth_username,
        server_cert_file=conn.server_cert_file,
        watchdog_read_node_id=conn.watchdog_read_node_id,
        watchdog_write_node_id=conn.watchdog_write_node_id,
        watchdog_period_ms=conn.watchdog_period_ms,
        has_password=conn.auth_password_enc is not None,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


async def _carregar(db: AsyncSession, connection_id: int) -> OpcConnection:
    conn = await db.get(OpcConnection, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    return conn


async def _publicar(
    redis_client: Redis, user: User, conn: OpcConnection, kind: str, acao: str
) -> None:
    """Auditoria da mutação (ADR-020) — sempre depois do commit, nunca antes."""
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Conexão '{conn.name}' {acao}",
        kind=kind,
        payload={"conn_id": conn.id, "project_id": conn.project_id, "name": conn.name},
    )


@router.get("", response_model=list[ConnectionOut], dependencies=[Depends(require_operator)])
async def list_connections(
    project_id: int | None = None, db: AsyncSession = Depends(get_db)
) -> list[ConnectionOut]:
    stmt = select(OpcConnection).order_by(OpcConnection.name)
    if project_id is not None:
        stmt = stmt.where(OpcConnection.project_id == project_id)
    return [_to_out(c) for c in await db.scalars(stmt)]


@router.post("", response_model=ConnectionOut, status_code=201)
async def create_connection(
    body: ConnectionCreate,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> ConnectionOut:
    if await db.get(Project, body.project_id) is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    n = await db.scalar(
        select(func.count())
        .select_from(OpcConnection)
        .where(OpcConnection.project_id == body.project_id)
    )
    if n >= MAX_CONNECTIONS_PER_PROJECT:
        raise HTTPException(status_code=409, detail="Limite de 5 conexões por projeto atingido")
    conn = OpcConnection(
        project_id=body.project_id,
        name=body.name,
        endpoint=body.endpoint,
        security_policy=body.security_policy,
        security_mode=body.security_mode,
        auth_mode=body.auth_mode,
        auth_username=body.auth_username,
        auth_password_enc=(
            encrypt_secret(body.auth_password, key=settings.fernet_key)
            if body.auth_password
            else None
        ),
        server_cert_file=body.server_cert_file,
        watchdog_read_node_id=body.watchdog_read_node_id,
        watchdog_write_node_id=body.watchdog_write_node_id,
        watchdog_period_ms=body.watchdog_period_ms,
    )
    db.add(conn)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Nome de conexão já em uso neste projeto"
        ) from None
    await db.refresh(conn)
    await _publicar(redis_client, user, conn, KIND_CONNECTION_CREATED, "criada")
    return _to_out(conn)


@router.get(
    "/{connection_id}", response_model=ConnectionOut, dependencies=[Depends(require_operator)]
)
async def get_connection(connection_id: int, db: AsyncSession = Depends(get_db)) -> ConnectionOut:
    return _to_out(await _carregar(db, connection_id))


@router.patch("/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: int,
    body: ConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> ConnectionOut:
    conn = await _carregar(db, connection_id)
    # auth_password fora do dump: ausente ou None significa manter a senha atual
    data = body.model_dump(exclude_unset=True, exclude={"auth_password"})
    for campo, valor in data.items():
        setattr(conn, campo, valor)
    if body.auth_password is not None:
        conn.auth_password_enc = encrypt_secret(body.auth_password, key=settings.fernet_key)
    if (conn.security_policy == "none") != (conn.security_mode == "none"):
        raise HTTPException(status_code=422, detail=_MSG_POLICY_MODE)
    if (conn.watchdog_read_node_id is None) != (conn.watchdog_write_node_id is None):
        raise HTTPException(
            status_code=422, detail="Watchdog exige os dois node_ids (leitura e escrita) ou nenhum"
        )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Nome de conexão já em uso neste projeto"
        ) from None
    await db.refresh(conn)
    await _publicar(redis_client, user, conn, KIND_CONNECTION_UPDATED, "atualizada")
    return _to_out(conn)


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> None:
    conn = await _carregar(db, connection_id)
    # Identidade capturada antes do delete: depois o objeto não é mais legível
    project_id, name = conn.project_id, conn.name
    await db.delete(conn)
    await db.commit()
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Conexão '{name}' excluída",
        kind=KIND_CONNECTION_DELETED,
        payload={"conn_id": connection_id, "project_id": project_id, "name": name},
    )
