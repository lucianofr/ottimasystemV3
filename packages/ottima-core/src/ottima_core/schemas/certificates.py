"""Schemas de certificados: app cert de instância e trust por conexão (RF-202, ADR-021)."""

from datetime import datetime

from pydantic import BaseModel


class AppCertificateOut(BaseModel):
    exists: bool
    subject: str | None = None
    fingerprint_sha256: str | None = None
    not_before: datetime | None = None
    not_after: datetime | None = None
    application_uri: str | None = None


class AppCertificateGenerateIn(BaseModel):
    force: bool = False


class AppCertificateGenerateOut(AppCertificateOut):
    warning: str | None = None  # aviso de re-trust quando force=True (spec F2 §5.7)


class ServerCertificateOut(BaseModel):
    conn_id: int
    server_cert_file: str  # nome do arquivo, ex.: "conn-3.der"
    fingerprint_sha256: str


class ServerCertificateInfoOut(BaseModel):
    """Metadados + PEM de um certificado de servidor gravado em disco (trusted ou received)."""

    subject: str
    issuer: str
    fingerprint_sha256: str
    not_before: datetime
    not_after: datetime
    pem: str


class ServerCertificatesOut(BaseModel):
    """Estado do certificado do servidor por conexão: o que está confiado e o que o
    servidor enviou (captura do opc-worker em staging, ainda não confiada)."""

    conn_id: int
    trusted: ServerCertificateInfoOut | None = None
    received: ServerCertificateInfoOut | None = None


class ServerCertificateTrustIn(BaseModel):
    """Corpo do aceite: o fingerprint que o admin inspecionou na UI (ADR-021).

    Obrigatório de propósito: o staging é reescrito pelo worker a cada retry, então
    confiar "no que estiver lá agora" seria TOFU cego — o aceite é do certificado
    exibido, não do arquivo. Divergência no servidor ⇒ 409.
    """

    fingerprint_sha256: str
