"""Certificado de aplicação OPC-UA: geração, metadados e export DER (RF-202, ADR-021).

O router só orquestra: toda a manipulação de X.509 e de arquivo vive em `ottima_core.certs`.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Response

from ottima_api.deps import get_app_settings, require_admin
from ottima_core.certs import (
    APP_CERT_DER_NAME,
    app_cert_paths,
    generate_app_certificate,
    read_app_certificate,
)
from ottima_core.config import Settings
from ottima_core.schemas.certificates import (
    AppCertificateGenerateIn,
    AppCertificateGenerateOut,
    AppCertificateOut,
)

# O certificado é a identidade do opc-worker: nenhuma rota aqui é para operador (ADR-015).
router = APIRouter(dependencies=[Depends(require_admin)])

_MSG_JA_EXISTE = "Certificado de aplicação já existe. Envie force=true para substituí-lo."
_MSG_RE_TRUST = (
    "Certificado de aplicação substituído. Os servidores OPC-UA que confiavam no certificado "
    "anterior precisam confiar no novo manualmente (re-trust) antes de aceitarem a conexão."
)
_MSG_SEM_CERTIFICADO = "Certificado de aplicação ainda não foi gerado."
_MSG_ILEGIVEL = (
    "Certificado de aplicação existe no volume mas está ilegível ou corrompido. "
    "Gere um novo com force=true e refaça o trust nos servidores OPC-UA."
)


@router.post("/app/generate", response_model=AppCertificateGenerateOut, status_code=201)
async def generate_app_cert(
    body: AppCertificateGenerateIn | None = None,
    settings: Settings = Depends(get_app_settings),
) -> AppCertificateGenerateOut:
    """Gera o certificado autoassinado do worker; `force` substitui o existente (spec §5.7)."""
    force = body.force if body is not None else False
    # ottima_core.certs é síncrono e move poucos KB: chamada direta no handler async é a
    # decisão registrada na tarefa 0.4 (spec §5.3), não um bloqueio relevante do loop.
    try:
        info = generate_app_certificate(settings.certs_dir, force=force)
    except FileExistsError:
        raise HTTPException(status_code=409, detail=_MSG_JA_EXISTE) from None
    return AppCertificateGenerateOut(**asdict(info), warning=_MSG_RE_TRUST if force else None)


@router.get("/app", response_model=AppCertificateOut)
async def get_app_cert(settings: Settings = Depends(get_app_settings)) -> AppCertificateOut:
    """Metadados do certificado. Ausência não é erro: devolve `exists=false`, nunca 404.

    Arquivo presente mas ilegível é outra coisa: falha de infraestrutura no volume, não
    entrada do usuário. Continua 500, mas mapeado — com mensagem em pt-BR dizendo qual é a
    saída — em vez de subir cru como erro genérico do framework.
    """
    try:
        info = read_app_certificate(settings.certs_dir)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=_MSG_ILEGIVEL) from exc
    return AppCertificateOut(**asdict(info))


@router.get("/app/export")
async def export_app_cert(settings: Settings = Depends(get_app_settings)) -> Response:
    """Download do `.der` para o operador cadastrar na trust list do servidor OPC-UA."""
    der_path = app_cert_paths(settings.certs_dir).der
    if not der_path.exists():
        raise HTTPException(status_code=404, detail=_MSG_SEM_CERTIFICADO)
    return Response(
        content=der_path.read_bytes(),
        media_type="application/pkix-cert",
        headers={"Content-Disposition": f'attachment; filename="{APP_CERT_DER_NAME}"'},
    )
