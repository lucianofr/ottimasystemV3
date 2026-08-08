"""Predicados de pendência de segredo pós-import (spec F6 §3.2-8, decisão A-4, achado
F6R-14). Único lugar de verdade das 3 fórmulas — a tarefa 2.3 (import) e o frontend
(F6b) consomem daqui, nunca reimplementam. Puro: nenhuma função aqui toca banco, Redis
ou disco.
"""

from ottima_core.schemas.projects import PendingSecretOut


def pendencias_da_conexao(
    *,
    connection_name: str,
    auth_mode: str,
    has_password: bool,
    security_policy: str,
    server_cert_file: str | None,
    app_cert_exists: bool,
) -> PendingSecretOut:
    """Os 3 predicados de §3.2-8:

    - `needs_password`: autenticação usuário/senha sem senha armazenada.
    - `needs_server_certificate`: policy segura sem o certificado do servidor confiado
      (`server_cert_file` ausente ou vazio).
    - `needs_app_certificate`: policy segura OU autenticação por certificado, sem o par
      de certificado de aplicação da instalação (F6R-14: sem este terceiro predicado,
      uma conexão `auth_mode: certificate` com `security_policy: none` teria pendência
      vazia e falharia em `cert_missing` sem aviso nenhum).
    """
    return PendingSecretOut(
        connection_name=connection_name,
        needs_password=auth_mode == "user_password" and not has_password,
        needs_server_certificate=security_policy != "none" and not server_cert_file,
        needs_app_certificate=(security_policy != "none" or auth_mode == "certificate")
        and not app_cert_exists,
    )
