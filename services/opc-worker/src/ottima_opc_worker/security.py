"""Montagem de segurança do Client asyncua: canal, identidade e pinning (spec F2 §5.1/5.2/5.6).

O worker não usa trust store de sistema: o certificado do servidor é pinado por conexão
(ADR-021) e, sem ele, uma política diferente de `none` não sobe — a conexão vai a `failed`
com `cert_missing` em vez de aceitar qualquer interlocutor.
"""

from pathlib import Path
from typing import Literal

from asyncua import Client, ua
from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256
from asyncua.crypto.uacrypto import CertProperties
from asyncua.ua.uaerrors import UaStatusCodeError

from ottima_core.certs import (
    APPLICATION_URI,
    AppCertPaths,
    app_cert_paths,
    read_app_certificate,
    trusted_cert_path,
)
from ottima_core.security import decrypt_secret

from .state import ConnectionConfig

SECURITY_POLICY_NONE = "none"
SECURITY_POLICY_BASIC256SHA256 = "basic256sha256"

AUTH_ANONYMOUS = "anonymous"
AUTH_USER_PASSWORD = "user_password"
AUTH_CERTIFICATE = "certificate"

FailureReason = Literal[
    "connect_failed", "session_lost", "watchdog_timeout", "cert_mismatch", "cert_missing"
]

# Modos de canal da spec §5.1; `none` não passa por aqui (não há set_security).
_MESSAGE_SECURITY_MODES: dict[str, ua.MessageSecurityMode] = {
    "sign": ua.MessageSecurityMode.Sign,
    "sign_and_encrypt": ua.MessageSecurityMode.SignAndEncrypt,
}

# O arquivo da chave do app é `ottima.key`: o asyncua infere DER de qualquer sufixo que
# não seja `.pem`, então o formato tem de ser dito explicitamente.
_PEM = "pem"

# Status codes com que um servidor bem-comportado recusa o certificado apresentado. É o
# discriminador estruturado do OPC-UA (parte 4), não a convenção de nomes do asyncua.
_CERT_STATUS_CODES = frozenset(
    {
        ua.StatusCodes.BadCertificateChainIncomplete,
        ua.StatusCodes.BadCertificateHostNameInvalid,
        ua.StatusCodes.BadCertificateInvalid,
        ua.StatusCodes.BadCertificateIssuerRevocationUnknown,
        ua.StatusCodes.BadCertificateIssuerRevoked,
        ua.StatusCodes.BadCertificateIssuerTimeInvalid,
        ua.StatusCodes.BadCertificateIssuerUseNotAllowed,
        ua.StatusCodes.BadCertificatePolicyCheckFailed,
        ua.StatusCodes.BadCertificateRevocationUnknown,
        ua.StatusCodes.BadCertificateRevoked,
        ua.StatusCodes.BadCertificateTimeInvalid,
        ua.StatusCodes.BadCertificateUntrusted,
        ua.StatusCodes.BadCertificateUriInvalid,
        ua.StatusCodes.BadCertificateUseNotAllowed,
        ua.StatusCodes.BadNoValidCertificates,
        ua.StatusCodes.BadSecurityChecksFailed,
    }
)


class CertMissingError(RuntimeError):
    """Pinning exigido e ausente: app cert ou server cert não disponível (spec §5.6)."""


class CertMismatchError(RuntimeError):
    """Certificado apresentado pelo servidor diverge do pinado (spec §5.6)."""


async def configure_client(
    client: Client,
    config: ConnectionConfig,
    *,
    certs_dir: Path,
    fernet_key: str,
) -> None:
    """Monta canal e identidade no Client asyncua, conforme spec §5.1/§5.2.

    Levanta CertMissingError quando o pinning exigido não pode ser satisfeito.
    Não conecta — quem conecta é o ConnectionRuntime.
    """
    # Precisa casar byte a byte com a SAN URI do certificado de aplicação, inclusive no
    # modo `none`, senão o servidor recusa o handshake com BadCertificateUriInvalid (§5.3).
    client.application_uri = APPLICATION_URI
    if config.security_policy != SECURITY_POLICY_NONE:
        await _configure_channel(client, config, certs_dir=certs_dir)
    await _configure_identity(client, config, certs_dir=certs_dir, fernet_key=fernet_key)


def map_connect_exception(
    exc: BaseException, *, pinning_enabled: bool
) -> tuple[FailureReason, str]:
    """Classifica a exceção de connect em (reason, detail) da spec §3.6.

    Divergência de certificado do servidor ⇒ ("cert_mismatch", detail);
    qualquer outra ⇒ ("connect_failed", detail). O detail é sempre seguro para log
    e para o payload do evento: nunca contém senha nem material de chave.

    `pinning_enabled` diz se a conexão tem canal seguro (`security_policy != "none"`).
    Sem canal seguro não existe certificado de servidor para divergir, e um prazo
    estourado só pode ser servidor mudo — a função continua pura, a política entra como
    parâmetro em vez de ser consultada aqui.
    """
    if isinstance(exc, CertMissingError):
        return "cert_missing", describe_exception(exc)
    if isinstance(exc, CertMismatchError) or _is_certificate_status(exc):
        return "cert_mismatch", describe_exception(exc)
    if isinstance(exc, TimeoutError) and pinning_enabled:
        # Servidor que só derruba o canal (é o caso do opcsim) não devolve status: o
        # OpenSecureChannel cifrado com a chave pública errada fica sem resposta e o
        # pedido estoura o prazo. Sem status, o prazo estourado é o único sinal.
        return "cert_mismatch", (
            f"handshake sem resposta ({describe_exception(exc)}): certificado do servidor "
            "diverge do pinado ou o servidor parou de responder"
        )
    return "connect_failed", describe_exception(exc)


def describe_exception(exc: BaseException) -> str:
    """Detalhe curto e sem segredo para o payload do evento."""
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


async def _configure_channel(client: Client, config: ConnectionConfig, *, certs_dir: Path) -> None:
    """Monta o canal seguro Basic256Sha256 com o certificado do servidor pinado (§5.1/§5.6)."""
    if config.security_policy != SECURITY_POLICY_BASIC256SHA256:
        raise ValueError(f"política de segurança não suportada: {config.security_policy!r}")
    mode = _MESSAGE_SECURITY_MODES.get(config.security_mode)
    if mode is None:
        raise ValueError(f"modo de segurança não suportado: {config.security_mode!r}")

    app = _require_app_certificate(certs_dir)
    server_cert = _require_pinned_certificate(config, certs_dir)
    await client.set_security(
        SecurityPolicyBasic256Sha256,
        certificate=str(app.pem),
        private_key=CertProperties(app.key, extension=_PEM),
        server_certificate=str(server_cert),
        mode=mode,
    )


async def _configure_identity(
    client: Client, config: ConnectionConfig, *, certs_dir: Path, fernet_key: str
) -> None:
    """Monta a identidade de usuário, independente do canal (spec §5.2)."""
    if config.auth_mode == AUTH_ANONYMOUS:
        return
    if config.auth_mode == AUTH_USER_PASSWORD:
        if not config.auth_username or not config.auth_password_enc:
            raise RuntimeError("credenciais de usuário incompletas na configuração")
        client.set_user(config.auth_username)
        # A senha em claro vive só nesta chamada: nada de atributo, log ou snapshot.
        client.set_password(_decrypt_password(config.auth_password_enc, fernet_key))
        return
    if config.auth_mode == AUTH_CERTIFICATE:
        # O token X.509 de usuário reusa o par do app (spec §5.2) e é distinto do
        # certificado de canal: o asyncua o recebe por load_client_certificate.
        app = _require_app_certificate(certs_dir)
        await client.load_client_certificate(str(app.pem))
        await client.load_private_key(app.key, extension=_PEM)
        return
    raise ValueError(f"modo de autenticação não suportado: {config.auth_mode!r}")


def _require_app_certificate(certs_dir: Path) -> AppCertPaths:
    """Garante o par do certificado de aplicação em disco (spec §5.3)."""
    if not read_app_certificate(certs_dir).exists:
        raise CertMissingError(
            "certificado de aplicação não foi gerado: gere-o antes de usar canal seguro "
            "ou identidade por certificado"
        )
    paths = app_cert_paths(certs_dir)
    if not paths.key.exists():
        raise CertMissingError(f"chave privada do certificado de aplicação ausente em {paths.key}")
    return paths


def _require_pinned_certificate(config: ConnectionConfig, certs_dir: Path) -> Path:
    """Garante o certificado pinado do servidor desta conexão (spec §5.6)."""
    if not config.server_cert_file:
        raise CertMissingError(
            "conexão sem certificado de servidor pinado: envie o certificado do servidor "
            "antes de usar política de segurança"
        )
    # `Path(...).name` descarta qualquer componente de diretório: o nome vem do banco e
    # não pode escapar de `trusted/`.
    path = trusted_cert_path(certs_dir, config.id).with_name(Path(config.server_cert_file).name)
    if not path.exists():
        raise CertMissingError(f"certificado pinado do servidor não encontrado em {path}")
    return path


def _decrypt_password(token: str, fernet_key: str) -> str:
    """Decifra a senha (spec F1 §5.4) trocando qualquer erro por mensagem fixa.

    O texto da exceção original poderia carregar token ou senha para dentro do evento.
    """
    try:
        return decrypt_secret(token, key=fernet_key)
    except Exception as exc:
        raise RuntimeError("falha ao decifrar a senha da conexão") from exc


def _is_certificate_status(exc: BaseException) -> bool:
    """Servidor que rejeita o certificado com status próprio do protocolo.

    O opcsim não chega a este caminho (derruba o canal sem responder), mas PLCs reais sim.
    """
    return isinstance(exc, UaStatusCodeError) and exc.code in _CERT_STATUS_CODES
