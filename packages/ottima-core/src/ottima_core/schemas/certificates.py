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
