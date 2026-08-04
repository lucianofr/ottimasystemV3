"""Testes da segurança do opc-worker: 3 modos, identidade e pinning (RF-201, spec F2 §5).

Tudo roda contra o opcsim in-process em modo `basic256sha256` — ele expõe, no mesmo
endpoint, o canal sem segurança e os modos Sign e SignAndEncrypt — e contra o Redis real
da fixture da raiz. Os certificados de aplicação vêm de `ottima_core.certs`, nunca de
material fixo no repositório.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from asyncua import Client, ua
from asyncua.ua.uaerrors import BadCertificateInvalid
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.serialization import Encoding
from redis.asyncio import Redis

from conftest import await_until, collecting
from opcsim import OpcSimServer, free_port
from ottima_core.bus import CHANNEL_EVENTS, KIND_COMM_FAILURE
from ottima_core.certs import (
    APPLICATION_URI,
    app_cert_paths,
    generate_app_certificate,
    store_server_certificate,
)
from ottima_core.security import encrypt_secret
from ottima_opc_worker.connection import ConnectionRuntime
from ottima_opc_worker.security import (
    CertMismatchError,
    CertMissingError,
    configure_client,
    map_connect_exception,
)
from ottima_opc_worker.state import ConnectionConfig, ConnectionSnapshot, ConnectionState

CONN_ID = 24

# Backoff curto: o que se prova aqui é a reconexão insistindo sem re-emitir alarme.
TEST_BACKOFF_INITIAL_S = 0.05
TEST_BACKOFF_MAX_S = 0.2
# Janela para provar que o alarme NÃO se repete durante o backoff.
QUIET_WINDOW_S = 1.0
# Heartbeat fora do caminho: estes ensaios observam só o canal `events`.
QUIET_HEARTBEAT_S = 30.0


@pytest.fixture
def certs_dir(tmp_path: Path) -> Path:
    """Diretório de certificados com o par do app já gerado (tarefa 0.4)."""
    path = tmp_path / "certs"
    generate_app_certificate(path)
    return path


@pytest.fixture
def certs_dir_vazio(tmp_path: Path) -> Path:
    """Diretório de certificados sem o par do app: o pinning não pode ser satisfeito."""
    return tmp_path / "sem-certs"


@pytest.fixture
async def secure_sim(tmp_path: Path) -> AsyncIterator[OpcSimServer]:
    """opcsim em `basic256sha256`: canal sem segurança, Sign e SignAndEncrypt no mesmo endpoint."""
    server = OpcSimServer(
        port=free_port(), security="basic256sha256", cert_dir=tmp_path / "opcsim-certs"
    )
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


def make_config(
    endpoint: str,
    *,
    security_policy: str = "none",
    security_mode: str = "none",
    auth_mode: str = "anonymous",
    auth_username: str | None = None,
    auth_password_enc: str | None = None,
    server_cert_file: str | None = None,
) -> ConnectionConfig:
    return ConnectionConfig(
        id=CONN_ID,
        project_id=1,
        name="Forno 1",
        endpoint=endpoint,
        security_policy=security_policy,
        security_mode=security_mode,
        auth_mode=auth_mode,
        auth_username=auth_username,
        auth_password_enc=auth_password_enc,
        server_cert_file=server_cert_file,
        watchdog_read_node_id=None,
        watchdog_write_node_id=None,
        watchdog_period_ms=1000,
        tags=(),
    )


def pin_server_certificate(certs_dir: Path, sim: OpcSimServer) -> str:
    """Confia no certificado que o opcsim gerou no boot e devolve `server_cert_file`."""
    assert sim.cert_der_path is not None
    return store_server_certificate(certs_dir, CONN_ID, sim.cert_der_path.read_bytes())


@asynccontextmanager
async def running(
    config: ConnectionConfig,
    redis_client: Redis,
    snapshot: ConnectionSnapshot,
    *,
    certs_dir: Path,
    fernet_key: str = "",
) -> AsyncIterator[ConnectionRuntime]:
    runtime = ConnectionRuntime(
        config,
        redis_client,
        snapshot,
        certs_dir=certs_dir,
        fernet_key=fernet_key,
        backoff_initial_s=TEST_BACKOFF_INITIAL_S,
        backoff_max_s=TEST_BACKOFF_MAX_S,
        heartbeat_interval_s=QUIET_HEARTBEAT_S,
    )
    await runtime.start()
    try:
        yield runtime
    finally:
        await runtime.stop()


def failures(events: list[dict]) -> list[dict]:
    return [event for event in events if event["payload"]["kind"] == KIND_COMM_FAILURE]


async def falha_unica(
    config: ConnectionConfig,
    redis_client: Redis,
    *,
    certs_dir: Path,
    fernet_key: str = "",
) -> dict:
    """Sobe o runtime, espera `failed` e devolve o único `comm_failure` da janela.

    A janela quieta cobre várias tentativas de reconexão em backoff: falha de
    configuração não re-emite alarme enquanto insiste (spec §3.6).
    """
    snapshot = ConnectionSnapshot(name=config.name)
    async with collecting(redis_client, CHANNEL_EVENTS) as events:
        async with running(
            config, redis_client, snapshot, certs_dir=certs_dir, fernet_key=fernet_key
        ) as runtime:
            await await_until(lambda: runtime.state is ConnectionState.FAILED)
            await asyncio.sleep(QUIET_WINDOW_S)
            assert len(failures(events)) == 1
            assert snapshot.state is ConnectionState.FAILED
            return failures(events)[0]


async def test_modo_none_conecta_e_anuncia_a_application_uri(
    secure_sim: OpcSimServer, certs_dir: Path, redis_client: Redis
) -> None:
    """`none`/`none` sobe sem set_security, mas com a ApplicationUri da SAN (spec §5.1/§5.3)."""
    config = make_config(secure_sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    async with running(config, redis_client, snapshot, certs_dir=certs_dir) as runtime:
        await await_until(lambda: runtime.state is ConnectionState.UP)
        client = runtime.client
        assert client is not None
        assert client.application_uri == APPLICATION_URI
        assert client.security_policy.Mode == ua.MessageSecurityMode.None_


@pytest.mark.parametrize(
    ("security_mode", "expected_mode"),
    [
        ("sign", ua.MessageSecurityMode.Sign),
        ("sign_and_encrypt", ua.MessageSecurityMode.SignAndEncrypt),
    ],
)
async def test_canal_basic256sha256_conecta_com_cert_pinado(
    secure_sim: OpcSimServer,
    certs_dir: Path,
    redis_client: Redis,
    security_mode: str,
    expected_mode: ua.MessageSecurityMode,
) -> None:
    """Sign e SignAndEncrypt sobem com o certificado do servidor pinado (spec §5.1)."""
    config = make_config(
        secure_sim.endpoint,
        security_policy="basic256sha256",
        security_mode=security_mode,
        server_cert_file=pin_server_certificate(certs_dir, secure_sim),
    )
    snapshot = ConnectionSnapshot(name=config.name)
    async with running(config, redis_client, snapshot, certs_dir=certs_dir) as runtime:
        await await_until(lambda: runtime.state is ConnectionState.UP)
        client = runtime.client
        assert client is not None
        assert client.security_policy.URI.endswith("Basic256Sha256")
        assert client.security_policy.Mode == expected_mode


async def test_sem_server_cert_file_falha_com_cert_missing(
    secure_sim: OpcSimServer, certs_dir: Path, redis_client: Redis
) -> None:
    """Policy≠none sem certificado pinado não sobe a conexão (spec §5.6)."""
    config = make_config(
        secure_sim.endpoint,
        security_policy="basic256sha256",
        security_mode="sign",
        server_cert_file=None,
    )
    falha = await falha_unica(config, redis_client, certs_dir=certs_dir)
    assert falha["payload"]["reason"] == "cert_missing"
    assert falha["severity"] == "alarm"


async def test_server_cert_file_inexistente_falha_com_cert_missing(
    secure_sim: OpcSimServer, certs_dir: Path, redis_client: Redis
) -> None:
    """Nome preenchido mas arquivo ausente em `trusted/` também é `cert_missing` (spec §5.6)."""
    config = make_config(
        secure_sim.endpoint,
        security_policy="basic256sha256",
        security_mode="sign",
        server_cert_file=f"conn-{CONN_ID}.der",
    )
    falha = await falha_unica(config, redis_client, certs_dir=certs_dir)
    assert falha["payload"]["reason"] == "cert_missing"


async def test_app_cert_nao_gerado_falha_com_cert_missing(
    secure_sim: OpcSimServer, certs_dir_vazio: Path, redis_client: Redis
) -> None:
    """Sem o par do app não há canal seguro possível (spec §5.3/§5.6)."""
    config = make_config(
        secure_sim.endpoint,
        security_policy="basic256sha256",
        security_mode="sign_and_encrypt",
        server_cert_file=f"conn-{CONN_ID}.der",
    )
    falha = await falha_unica(config, redis_client, certs_dir=certs_dir_vazio)
    assert falha["payload"]["reason"] == "cert_missing"
    assert "aplicação" in falha["payload"]["detail"]


async def test_cert_do_servidor_divergente_falha_com_cert_mismatch(
    secure_sim: OpcSimServer, certs_dir: Path, tmp_path: Path, redis_client: Redis
) -> None:
    """Handshake contra certificado que não é o pinado ⇒ `cert_mismatch` (spec §5.6)."""
    outro = tmp_path / "outro-cert"
    generate_app_certificate(outro)
    cert_file = store_server_certificate(certs_dir, CONN_ID, app_cert_paths(outro).der.read_bytes())
    config = make_config(
        secure_sim.endpoint,
        security_policy="basic256sha256",
        security_mode="sign",
        server_cert_file=cert_file,
    )
    falha = await falha_unica(config, redis_client, certs_dir=certs_dir)
    assert falha["payload"]["reason"] == "cert_mismatch"


async def test_user_password_monta_identidade_e_nunca_vaza_o_segredo(
    secure_sim: OpcSimServer, certs_dir: Path, redis_client: Redis
) -> None:
    """A senha Fernet é decifrada na montagem e não reaparece em evento nem snapshot (§5.2)."""
    fernet_key = Fernet.generate_key().decode()
    senha = "senha-secreta-do-plc"
    token = encrypt_secret(senha, key=fernet_key)
    config = make_config(
        secure_sim.endpoint,
        security_policy="basic256sha256",
        security_mode="sign_and_encrypt",
        auth_mode="user_password",
        auth_username="operador",
        auth_password_enc=token,
        server_cert_file=pin_server_certificate(certs_dir, secure_sim),
    )

    client = Client(config.endpoint)
    await configure_client(client, config, certs_dir=certs_dir, fernet_key=fernet_key)
    # Só o asyncua fica com a senha em claro, e ela vem decifrada da configuração.
    assert client._username == "operador"
    assert client._password == senha

    snapshot = ConnectionSnapshot(name=config.name)
    async with running(
        config, redis_client, snapshot, certs_dir=certs_dir, fernet_key=fernet_key
    ) as runtime:
        await await_until(lambda: runtime.state is ConnectionState.UP)

    # A mesma identidade num caminho de falha: o detail do evento não pode ecoar o segredo.
    sem_pinning = make_config(
        secure_sim.endpoint,
        security_policy="basic256sha256",
        security_mode="sign_and_encrypt",
        auth_mode="user_password",
        auth_username="operador",
        auth_password_enc=token,
    )
    falha = await falha_unica(sem_pinning, redis_client, certs_dir=certs_dir, fernet_key=fernet_key)
    assert falha["payload"]["reason"] == "cert_missing"
    texto = json.dumps(falha, ensure_ascii=False) + repr(snapshot)
    assert senha not in texto
    assert token not in texto


async def test_identidade_por_certificado_reusa_o_par_do_app(
    secure_sim: OpcSimServer, certs_dir: Path, redis_client: Redis
) -> None:
    """`certificate` monta o token X.509 com o próprio certificado de aplicação (§5.2)."""
    config = make_config(secure_sim.endpoint, auth_mode="certificate")
    snapshot = ConnectionSnapshot(name=config.name)
    async with running(config, redis_client, snapshot, certs_dir=certs_dir) as runtime:
        await await_until(lambda: runtime.state is ConnectionState.UP)
        client = runtime.client
        assert client is not None
        assert client.user_private_key is not None
        assert client.user_certificate is not None
        assert (
            client.user_certificate.public_bytes(Encoding.DER)
            == app_cert_paths(certs_dir).der.read_bytes()
        )


def test_map_connect_exception_classifica_sem_tocar_a_rede() -> None:
    """Classificação pura das exceções de connect (spec §3.6)."""
    assert map_connect_exception(CertMismatchError("divergiu"))[0] == "cert_mismatch"
    assert map_connect_exception(BadCertificateInvalid())[0] == "cert_mismatch"
    # O opcsim (e servidores que só derrubam o canal) não devolvem status: sobra o timeout.
    assert map_connect_exception(TimeoutError())[0] == "cert_mismatch"
    assert map_connect_exception(CertMissingError("faltou"))[0] == "cert_missing"

    reason, detail = map_connect_exception(ConnectionRefusedError("conexão recusada"))
    assert reason == "connect_failed"
    assert detail == "ConnectionRefusedError: conexão recusada"
