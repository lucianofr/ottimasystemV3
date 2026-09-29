"""CRUD de conexões OPC-UA (RF-201, ADR-009/021): leitura para operador, escrita para admin."""

import hashlib
import logging
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ottima_api.deps import get_app_settings, get_db, get_redis, require_admin, require_operator
from ottima_api.messages import MSG_PROJETO_NAO_ENCONTRADO
from ottima_core.bus import (
    KIND_CONNECTION_CREATED,
    KIND_CONNECTION_DELETED,
    KIND_CONNECTION_UPDATED,
    publish_event,
)
from ottima_core.certs import (
    MAX_SERVER_CERT_BYTES,
    read_server_certificate_info,
    received_cert_path,
    remove_server_certificate,
    store_server_certificate,
    trusted_cert_path,
)
from ottima_core.config import Settings
from ottima_core.models import OpcConnection, Project, User
from ottima_core.schemas.certificates import (
    ServerCertificateInfoOut,
    ServerCertificateOut,
    ServerCertificatesOut,
    ServerCertificateTrustIn,
)
from ottima_core.schemas.connections import ConnectionCreate, ConnectionOut, ConnectionUpdate
from ottima_core.security import encrypt_secret

logger = logging.getLogger(__name__)

# Sem dependência no router: os papéis variam por rota (ADR-015)
router = APIRouter()

MAX_CONNECTIONS_PER_PROJECT = 5  # RF-201

# Mesmo texto do validator do ConnectionCreate (schemas/connections.py)
_MSG_POLICY_MODE = (
    "SecurityPolicy None exige modo None; Basic256Sha256 exige Sign ou SignAndEncrypt"
)

# O teto de 64 KiB vive em `ottima_core.certs`: o upload e a captura do worker compartilham
# a mesma barreira; sem teto, qualquer corpo enviado viraria gravação em disco.
_MAX_DIGITOS_TETO = len(str(MAX_SERVER_CERT_BYTES))
_MSG_CERT_GRANDE = "Certificado enviado excede o limite de 64 KiB."
_MSG_SEM_RECEBIDO = (
    "Nenhum certificado recebido deste servidor ainda: a captura acontece quando o "
    "opc-worker tenta conectar — confira se o servidor está acessível e aguarde a próxima "
    "tentativa."
)
_MSG_FINGERPRINT_DIVERGE = (
    "O certificado recebido mudou desde a visualização (rotação ou captura nova): "
    "recarregue a visualização e confirme o fingerprint antes de confiar."
)
_MSG_CERT_ILEGIVEL = "Certificado gravado em disco está ilegível; recapture-o ou reenvie-o."


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
        polling_period_ms=conn.polling_period_ms,
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
    redis_client: Redis,
    user: User,
    conn: OpcConnection,
    kind: str,
    acao: str,
    *,
    fingerprint: str | None = None,
) -> None:
    """Auditoria da mutação (ADR-020) — sempre depois do commit, nunca antes.

    `fingerprint` viaja no payload só nas rotas que pinam certificado: QUAL certificado
    foi confiado é parte da decisão auditada (ADR-021).
    """
    payload = {"conn_id": conn.id, "project_id": conn.project_id, "name": conn.name}
    if fingerprint is not None:
        payload["fingerprint_sha256"] = fingerprint
    await publish_event(
        redis_client,
        severity="info",
        origin=f"user:{user.id}",
        message=f"Conexão '{conn.name}' {acao}",
        kind=kind,
        payload=payload,
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
        raise HTTPException(status_code=404, detail=MSG_PROJETO_NAO_ENCONTRADO)
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
        polling_period_ms=body.polling_period_ms,
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


def _cert_info(path: Path) -> ServerCertificateInfoOut | None:
    """Info de um certificado em disco (None = ausente); ValueError vira 500 mapeado."""
    try:
        info = read_server_certificate_info(path)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=_MSG_CERT_ILEGIVEL) from exc
    return None if info is None else ServerCertificateInfoOut(**asdict(info))


def _cert_info_degradavel(path: Path) -> ServerCertificateInfoOut | None:
    """`received` ilegível não derruba o GET inteiro: degrada para None com warning.

    Diferente do `trusted` (falha de infra real: 500), o staging é reescrito pelo worker a
    qualquer momento — esconder o lado confiado por causa dele seria perder a informação
    que importa por um arquivo transitório.
    """
    try:
        return _cert_info(path)
    except HTTPException:
        logger.warning("Certificado recebido em %s ilegível; omitido da resposta", path.name)
        return None


@router.get(
    "/{connection_id}/server-certificate",
    response_model=ServerCertificatesOut,
    dependencies=[Depends(require_operator)],
)
async def get_server_certificate(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ServerCertificatesOut:
    """O certificado confiado e o certificado que o servidor enviou (staging da captura).

    `trusted` só aparece quando a coluna `server_cert_file` está preenchida: um arquivo
    órfão em `trusted/` (ex.: trust desfeito por outra rota) não é certificado confiado.
    `received` vem do volume gravado pelo opc-worker na falha de pin — a UI o usa para
    "Visualizar" e para habilitar o aceite sem upload.
    """
    conn = await _carregar(db, connection_id)
    trusted = (
        _cert_info(trusted_cert_path(settings.certs_dir, connection_id))
        if conn.server_cert_file
        else None
    )
    received = _cert_info_degradavel(received_cert_path(settings.received_certs_dir, connection_id))
    return ServerCertificatesOut(conn_id=connection_id, trusted=trusted, received=received)


@router.post("/{connection_id}/server-certificate/trust", response_model=ServerCertificateOut)
async def trust_received_server_certificate(
    connection_id: int,
    body: ServerCertificateTrustIn,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    user: User = Depends(require_admin),
    redis_client: Redis = Depends(get_redis),
) -> ServerCertificateOut:
    """Confia no certificado que o servidor enviou (captura do opc-worker), sem upload.

    É o "aceite" da UI: promove o arquivo do staging para `trusted/` com a mesma validação
    X.509 do upload. O `fingerprint_sha256` do corpo é o do certificado que o admin
    inspecionou (ADR-021): se o worker recapturou desde a visualização (rotação, captura
    nova), 409 — o aceite é do certificado EXIBIDO, não do que estiver no staging. Aceite
    repetido dos mesmos bytes é no-op: sem watermark, sem evento, sem reconcile inútil de
    uma sessão saudável.
    """
    conn = await _carregar(db, connection_id)
    origem = received_cert_path(settings.received_certs_dir, connection_id)
    if not origem.exists():
        raise HTTPException(status_code=409, detail=_MSG_SEM_RECEBIDO)
    data = origem.read_bytes()
    if hashlib.sha256(data).hexdigest() != body.fingerprint_sha256:
        raise HTTPException(status_code=409, detail=_MSG_FINGERPRINT_DIVERGE)
    confiado = trusted_cert_path(settings.certs_dir, connection_id)
    substituindo = conn.server_cert_file is not None
    if substituindo and confiado.exists() and confiado.read_bytes() == data:
        return ServerCertificateOut(
            conn_id=connection_id,
            server_cert_file=conn.server_cert_file,
            fingerprint_sha256=body.fingerprint_sha256,
        )
    # Síncrono e de poucos KB, como todo o ottima_core.certs (spec §5.3, decisão 0.4).
    try:
        nome = store_server_certificate(settings.certs_dir, connection_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    conn.server_cert_file = nome
    # Bump do watermark: o nome é sempre `conn-<id>.der`, então re-confiar depois de uma
    # rotação não suja o atributo — ver o comentário em `set_server_certificate`.
    flag_modified(conn, "server_cert_file")
    await db.commit()
    await _publicar(
        redis_client,
        user,
        conn,
        KIND_CONNECTION_UPDATED,
        "com o certificado recebido do servidor confirmado"
        + (" (substituindo o pin anterior)" if substituindo else ""),
        fingerprint=body.fingerprint_sha256,
    )
    return ServerCertificateOut(
        conn_id=connection_id,
        server_cert_file=nome,
        fingerprint_sha256=body.fingerprint_sha256,
    )
