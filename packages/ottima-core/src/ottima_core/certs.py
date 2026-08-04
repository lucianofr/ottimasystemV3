"""Certificado de instância de aplicação OPC-UA e trust de certificados de servidor.

Layout do volume `certs` (spec F2 §5.4):

    <certs_dir>/app/ottima.pem          certificado da aplicação (PEM)
    <certs_dir>/app/ottima.key          chave privada PKCS#8 sem passphrase (ADR-023)
    <certs_dir>/app/ottima.der          o mesmo certificado em DER, para exportar ao servidor
    <certs_dir>/trusted/conn-<id>.der   certificado do servidor OPC-UA confiado

Chaves privadas nunca vão para o banco: a coluna `server_cert_file` guarda apenas o nome
do arquivo em `trusted/`.

Todas as funções são síncronas de propósito. São leituras e gravações de poucos KB, cujo
custo não é relevante perto de uma troca de contexto do event loop; chamá-las de dentro de
handlers async (tarefa 4.4) é aceito e não caracteriza bloqueio.
"""

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

logger = logging.getLogger(__name__)

# ApplicationUri usado pelo Client asyncua (tarefa 2.4). Precisa casar byte a byte com a
# SAN URI do certificado, senão o servidor recusa o handshake com BadCertificateUriInvalid.
APPLICATION_URI = "urn:ottima:opc-worker"
APP_CERT_COMMON_NAME = "OttimaSystem opc-worker"
APP_CERT_KEY_SIZE = 2048
APP_CERT_VALIDITY_DAYS = 3650  # 10 anos
APP_DIR_NAME = "app"
TRUSTED_DIR_NAME = "trusted"
APP_CERT_PEM_NAME = "ottima.pem"
APP_CERT_KEY_NAME = "ottima.key"
APP_CERT_DER_NAME = "ottima.der"

_DIR_MODE = 0o700
_KEY_MODE = 0o600
_CERT_MODE = 0o644
# Folga de relógio: servidores atrasados recusariam um certificado ainda não válido.
_CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True)
class AppCertPaths:
    """Caminhos dos três arquivos do certificado de aplicação."""

    pem: Path
    key: Path
    der: Path


@dataclass(frozen=True)
class AppCertificateInfo:
    """Metadados do certificado de aplicação lido do disco."""

    exists: bool
    subject: str | None = None
    fingerprint_sha256: str | None = None
    not_before: datetime | None = None
    not_after: datetime | None = None
    application_uri: str | None = None


def app_cert_paths(certs_dir: Path) -> AppCertPaths:
    """Monta os caminhos do certificado de aplicação, sem tocar no disco."""
    app_dir = certs_dir / APP_DIR_NAME
    return AppCertPaths(
        pem=app_dir / APP_CERT_PEM_NAME,
        key=app_dir / APP_CERT_KEY_NAME,
        der=app_dir / APP_CERT_DER_NAME,
    )


def trusted_cert_path(certs_dir: Path, conn_id: int) -> Path:
    """Caminho do certificado confiado de um servidor OPC-UA.

    Valida `conn_id` em runtime: ele vem de um path param HTTP na tarefa 4.4, e um valor
    fora do contrato de tipos viraria um nome de arquivo arbitrário fora de `trusted/`.
    """
    if isinstance(conn_id, bool) or not isinstance(conn_id, int) or conn_id < 0:
        raise ValueError(f"Identificador de conexão inválido: {conn_id!r} (esperado inteiro >= 0).")
    return certs_dir / TRUSTED_DIR_NAME / f"conn-{conn_id}.der"


def read_app_certificate(certs_dir: Path) -> AppCertificateInfo:
    """Lê os metadados do certificado de aplicação.

    Devolve `exists=False` quando o certificado ainda não foi gerado. Levanta ValueError
    se o arquivo existir mas não for um certificado legível.
    """
    pem_path = app_cert_paths(certs_dir).pem
    if not pem_path.exists():
        return AppCertificateInfo(exists=False)
    try:
        cert = x509.load_pem_x509_certificate(pem_path.read_bytes())
    except Exception as exc:
        raise ValueError(
            f"Certificado de aplicação ilegível ou corrompido em {pem_path}: {exc}"
        ) from exc
    return _info_from_certificate(cert)


def generate_app_certificate(certs_dir: Path, *, force: bool = False) -> AppCertificateInfo:
    """Gera o certificado autoassinado de instância de aplicação (spec F2 §5.3).

    Regenerar invalida os trusts já estabelecidos nos servidores OPC-UA: eles precisam
    confiar no novo certificado manualmente (spec F2 §5.7).

    Levanta FileExistsError se o certificado já existir e `force` for False.
    """
    paths = app_cert_paths(certs_dir)
    if paths.pem.exists() and not force:
        raise FileExistsError(
            f"Certificado de aplicação já existe em {paths.pem}. "
            "Use force=true para regenerá-lo (os servidores precisarão confiar no novo)."
        )

    _ensure_dir(certs_dir / APP_DIR_NAME)
    _ensure_dir(certs_dir / TRUSTED_DIR_NAME)

    key = rsa.generate_private_key(public_exponent=65537, key_size=APP_CERT_KEY_SIZE)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, APP_CERT_COMMON_NAME)])
    not_before = datetime.now(UTC) - _CLOCK_SKEW
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_before + timedelta(days=APP_CERT_VALIDITY_DAYS))
        .add_extension(
            x509.SubjectAlternativeName([x509.UniformResourceIdentifier(APPLICATION_URI)]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,  # nonRepudiation
                key_encipherment=True,
                data_encipherment=True,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            # clientAuth + serverAuth: praxe de interoperabilidade OPC-UA.
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH]
            ),
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )

    _write_all_atomically(
        [
            (paths.pem, cert.public_bytes(serialization.Encoding.PEM), _CERT_MODE),
            (paths.der, cert.public_bytes(serialization.Encoding.DER), _CERT_MODE),
            (
                paths.key,
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                ),
                _KEY_MODE,
            ),
        ]
    )
    return _info_from_certificate(cert)


def store_server_certificate(certs_dir: Path, conn_id: int, data: bytes) -> str:
    """Confia no certificado de um servidor OPC-UA, normalizando PEM ou DER para DER.

    Aceita exatamente um certificado: o pinning de ADR-021 é de "seu certificado",
    singular, e escolher silenciosamente um de vários seria ambíguo demais para um
    arquivo de confiança.

    Devolve o nome do arquivo gravado (`conn-<id>.der`), que é o valor da coluna
    `server_cert_file`. Levanta ValueError se `data` não for um único certificado.
    """
    path = trusted_cert_path(certs_dir, conn_id)  # valida conn_id antes de qualquer I/O
    cert = _load_certificate(data)
    _ensure_dir(certs_dir / TRUSTED_DIR_NAME)
    _write_file(path, cert.public_bytes(serialization.Encoding.DER), _CERT_MODE)
    return path.name


def remove_server_certificate(certs_dir: Path, conn_id: int) -> bool:
    """Remove o certificado confiado do servidor. Devolve False se não havia arquivo."""
    try:
        trusted_cert_path(certs_dir, conn_id).unlink()
    except FileNotFoundError:
        return False
    return True


def _load_certificate(data: bytes) -> x509.Certificate:
    try:
        return x509.load_der_x509_certificate(data)
    except Exception:
        pass
    try:
        certificates = x509.load_pem_x509_certificates(data)
    except Exception as exc:
        raise ValueError(
            "Conteúdo enviado não é um certificado X.509 válido em formato PEM ou DER."
        ) from exc
    if len(certificates) != 1:
        raise ValueError(
            f"Conteúdo enviado tem {len(certificates)} certificados; informe um único certificado."
        )
    return certificates[0]


def _info_from_certificate(cert: x509.Certificate) -> AppCertificateInfo:
    der = cert.public_bytes(serialization.Encoding.DER)
    return AppCertificateInfo(
        exists=True,
        subject=cert.subject.rfc4514_string(),
        fingerprint_sha256=hashlib.sha256(der).hexdigest(),
        not_before=cert.not_valid_before_utc,
        not_after=cert.not_valid_after_utc,
        application_uri=_application_uri_of(cert),
    )


def _application_uri_of(cert: x509.Certificate) -> str | None:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return None
    uris = san.get_values_for_type(x509.UniformResourceIdentifier)
    return uris[0] if uris else None


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(_DIR_MODE)


def _write_file(path: Path, data: bytes, mode: int) -> None:
    # O modo do os.open só vale na criação; o chmod garante a permissão também no force.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    path.chmod(mode)


def _write_all_atomically(entries: list[tuple[Path, bytes, int]]) -> None:
    """Grava um conjunto de arquivos em tudo-ou-nada.

    Certificado e chave só valem em par: uma falha no meio da gravação deixaria o volume
    com um par incompatível, e o worker falharia o handshake OPC-UA com um erro que não
    aponta para a causa. Grava tudo em temporários no mesmo diretório e só promove com
    os.replace depois que todos estiverem no disco.
    """
    # Os temporários entram na lista de limpeza ANTES da escrita: um write interrompido no
    # meio (ENOSPC) deixa o arquivo criado e parcial, e ele também precisa ser removido.
    targets = [(path.with_name(f".{path.name}.tmp"), path) for path, _, _ in entries]
    try:
        for (tmp, _), (_, data, mode) in zip(targets, entries, strict=True):
            _write_file(tmp, data, mode)
    except BaseException:
        _discard(targets)
        raise

    for index, (tmp, path) in enumerate(targets):
        try:
            os.replace(tmp, path)
        except OSError:
            # os.replace é atômico por arquivo, mas não como grupo: se o segundo ou o
            # terceiro rename falhar, o volume fica com um par misto. Rollback de três
            # arquivos não é confiável em POSIX (a reversão pode falhar pelo mesmo motivo),
            # então a decisão é não tentar rollback e sim gritar no log com a remediação.
            logger.critical(
                "Falha ao promover os arquivos do certificado de aplicação em %s: %s. "
                "O volume pode ter ficado com certificado e chave de gerações diferentes, "
                "o que faz o handshake OPC-UA falhar. Regenere o certificado com "
                "force=true e refaça o trust nos servidores.",
                path.parent,
                ", ".join(destino.name for _, destino in targets),
            )
            _discard(targets[index:])
            raise


def _discard(targets: list[tuple[Path, Path]]) -> None:
    for tmp, _ in targets:
        tmp.unlink(missing_ok=True)
