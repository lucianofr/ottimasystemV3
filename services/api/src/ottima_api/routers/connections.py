"""CRUD de conexões OPC-UA (RF-201, ADR-009/021): leitura para operador, escrita para admin."""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ottima_api.deps import get_app_settings, get_db, get_redis, require_admin, require_operator
from ottima_core.bus import (
    KIND_CONNECTION_CREATED,
    KIND_CONNECTION_DELETED,
    KIND_CONNECTION_UPDATED,
    publish_event,
)
from ottima_core.certs import (
    remove_server_certificate,
    store_server_certificate,
    trusted_cert_path,
)
from ottima_core.config import Settings
from ottima_core.models import OpcConnection, Project, User
from ottima_core.schemas.certificates import ServerCertificateOut
from ottima_core.schemas.connections import ConnectionCreate, ConnectionOut, ConnectionUpdate
from ottima_core.security import encrypt_secret

# Sem dependência no router: os papéis variam por rota (ADR-015)
router = APIRouter()

MAX_CONNECTIONS_PER_PROJECT = 5  # RF-201

# Mesmo texto do validator do ConnectionCreate (schemas/connections.py)
_MSG_POLICY_MODE = (
    "SecurityPolicy None exige modo None; Basic256Sha256 exige Sign ou SignAndEncrypt"
)

# Um certificado X.509 não chega perto disso; sem teto, qualquer corpo enviado viraria
# gravação em disco.
MAX_SERVER_CERT_BYTES = 64 * 1024
_MAX_DIGITOS_TETO = len(str(MAX_SERVER_CERT_BYTES))
_MSG_CERT_GRANDE = "Certificado enviado excede o limite de 64 KiB."


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


def _excede_o_declarado(declarado: str | None) -> bool:
    """Diz se o `Content-Length` já denuncia um corpo grande demais, sem nunca levantar.

    Duas armadilhas do `int()`, as duas achadas pela 4.3 e as duas capazes de virar 500 num
    header que é entrada de usuário: `"²".isdigit()` é True mas `int("²")` levanta, e o
    CPython recusa converter string com mais de `sys.get_int_max_str_digits()` (4300) dígitos.
    Por isso: `isdecimal()` filtra o alfabeto, a contagem de dígitos significativos resolve
    sozinha o caso "grande demais", e só sobra para o `int()` o que cabe no teto.
    """
    if declarado is None or not declarado.isdecimal():
        return False  # header ausente ou malformado: quem decide é a contagem real
    significativos = declarado.lstrip("0")
    if len(significativos) > _MAX_DIGITOS_TETO:
        return True  # mais dígitos que o teto ⇒ maior que o teto, sem precisar converter
    return int(significativos or "0") > MAX_SERVER_CERT_BYTES


async def _ler_certificado(request: Request) -> bytes:
    """Corpo bruto do upload, com teto de tamanho.

    Lê em fluxo e aborta no primeiro chunk que cruza o teto: `await request.body()` bufferiza
    o corpo inteiro ANTES de qualquer comparação, então sem Content-Length honesto (ausente,
    chunked ou mentindo baixo) um corpo arbitrariamente grande já teria sido materializado
    quando o 413 saísse. Aqui nunca se acumula mais que o teto mais um chunk.

    O Content-Length continua como barreira barata de primeira linha, mas é só otimização: a
    garantia vem da contagem dos bytes efetivamente lidos.
    """
    if _excede_o_declarado(request.headers.get("content-length")):
        raise HTTPException(status_code=413, detail=_MSG_CERT_GRANDE)
    partes: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_SERVER_CERT_BYTES:
            raise HTTPException(status_code=413, detail=_MSG_CERT_GRANDE)
        partes.append(chunk)
    return b"".join(partes)


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


@router.post("/{connection_id}/server-certificate", response_model=ServerCertificateOut)
async def set_server_certificate(
    connection_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> ServerCertificateOut:
    """Confia no certificado do servidor (ADR-021): corpo bruto DER ou PEM, gravado como DER.

    O certificado vem no corpo da request (`application/octet-stream`,
    `application/x-pem-file` ou `application/pkix-cert`), não em multipart: um upload de
    campo único não justifica a dependência extra de parsing de formulário.

    Emite `connection_updated` porque `server_cert_file` também é campo do PATCH: a mesma
    mudança de estado não pode ser auditada por uma rota e silenciosa pela outra. O evento é
    ainda a dica de reconciliação do worker (spec §2.2-1), e trocar o certificado confiado é
    justamente o que derruba o canal seguro.
    """
    conn = await _carregar(db, connection_id)
    data = await _ler_certificado(request)
    # Síncrono e de poucos KB, como todo o ottima_core.certs (spec §5.3, decisão da tarefa 0.4).
    try:
        nome = store_server_certificate(settings.certs_dir, connection_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    conn.server_cert_file = nome
    # O nome é sempre `conn-<id>.der`, então SUBSTITUIR o certificado não muda o valor da
    # coluna: sem atributo sujo o ORM não emite UPDATE, o `onupdate` do TimestampMixin não
    # dispara e o watermark de reconciliação do supervisor (spec §2.2-1) fica parado — a
    # sessão OPC seguiria indefinidamente com o certificado antigo em memória. O bump é
    # forçado de propósito; não remover.
    flag_modified(conn, "server_cert_file")
    await db.commit()
    await _publicar(
        redis_client,
        user,
        conn,
        KIND_CONNECTION_UPDATED,
        "com o certificado do servidor atualizado",
    )
    # Fingerprint do que foi de fato gravado (já normalizado para DER), não do que chegou.
    der = trusted_cert_path(settings.certs_dir, connection_id).read_bytes()
    return ServerCertificateOut(
        conn_id=connection_id,
        server_cert_file=nome,
        fingerprint_sha256=hashlib.sha256(der).hexdigest(),
    )


@router.delete("/{connection_id}/server-certificate", status_code=204)
async def clear_server_certificate(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> None:
    """Deixa de confiar no certificado do servidor. Idempotente: 204 mesmo sem o arquivo.

    Só emite quando houve mudança de estado — arquivo removido ou coluna limpa. Repetir o
    DELETE numa conexão que já não confia em nada é no-op, e no-op não é evento.
    """
    conn = await _carregar(db, connection_id)
    removeu_arquivo = remove_server_certificate(settings.certs_dir, connection_id)
    limpou_coluna = conn.server_cert_file is not None
    if not (removeu_arquivo or limpou_coluna):
        return
    conn.server_cert_file = None
    await db.commit()
    await _publicar(
        redis_client, user, conn, KIND_CONNECTION_UPDATED, "sem o certificado do servidor"
    )
