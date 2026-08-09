"""Testes de `ottima_core.portability.pendencias` — os 3 predicados de pendência de
segredo (spec F6 §3.2-8, decisão A-4, achado F6R-14). Único lugar de verdade: a tarefa
2.3 (import) e o frontend (F6b) consomem daqui, nunca duplicam a fórmula.
"""

import itertools

from ottima_core.portability.pendencias import pendencias_da_conexao

_AUTH_MODES = ("anonymous", "user_password", "certificate")
_SECURITY_POLICIES = ("none", "basic256sha256")
_SERVER_CERT_FILES = (None, "server.pem")
_BOOLS = (True, False)


def _formula(
    auth_mode: str,
    has_password: bool,
    security_policy: str,
    server_cert_file: str | None,
    app_cert_exists: bool,
) -> tuple[bool, bool, bool]:
    """As 3 fórmulas de §3.2-8, transcritas literalmente da spec (não do código sob teste)."""
    needs_password = auth_mode == "user_password" and not has_password
    needs_server_certificate = security_policy != "none" and not server_cert_file
    needs_app_certificate = (
        security_policy != "none" or auth_mode == "certificate"
    ) and not app_cert_exists
    return needs_password, needs_server_certificate, needs_app_certificate


def test_tabela_verdade_completa_dos_tres_predicados():
    """3 auth_mode x 2 has_password x 2 security_policy x 2 server_cert_file x
    2 app_cert_exists = 48 casos; cada um conferido contra a fórmula de §3.2-8."""
    casos = list(
        itertools.product(_AUTH_MODES, _BOOLS, _SECURITY_POLICIES, _SERVER_CERT_FILES, _BOOLS)
    )
    assert len(casos) == 48
    for auth_mode, has_password, security_policy, server_cert_file, app_cert_exists in casos:
        pendencia = pendencias_da_conexao(
            connection_name="gateway-1",
            auth_mode=auth_mode,
            has_password=has_password,
            security_policy=security_policy,
            server_cert_file=server_cert_file,
            app_cert_exists=app_cert_exists,
        )
        obtido = (
            pendencia.needs_password,
            pendencia.needs_server_certificate,
            pendencia.needs_app_certificate,
        )
        esperado = _formula(
            auth_mode, has_password, security_policy, server_cert_file, app_cert_exists
        )
        assert obtido == esperado, (
            auth_mode,
            has_password,
            security_policy,
            server_cert_file,
            app_cert_exists,
        )


def test_server_cert_file_vazio_conta_como_ausente():
    """§3.2-8 fala "ausente/vazio": string vazia é tão pendente quanto None."""
    pendencia = pendencias_da_conexao(
        connection_name="gateway-1",
        auth_mode="anonymous",
        has_password=False,
        security_policy="basic256sha256",
        server_cert_file="",
        app_cert_exists=True,
    )
    assert pendencia.needs_server_certificate is True


def test_exemplo_da_spec_f6_secao_3_2_8():
    """Reproduz o exemplo literal da spec: user_password sem senha, policy segura sem
    certificado do servidor confiado, mas certificado de aplicação já existe."""
    pendencia = pendencias_da_conexao(
        connection_name="gateway-1",
        auth_mode="user_password",
        has_password=False,
        security_policy="basic256sha256",
        server_cert_file=None,
        app_cert_exists=True,
    )
    assert pendencia.needs_password is True
    assert pendencia.needs_server_certificate is True
    assert pendencia.needs_app_certificate is False


def test_terceiro_predicado_cobre_certificate_com_policy_none():
    """F6R-14: `auth_mode: certificate` com `security_policy: none` não pode passar
    despercebido — sem este predicado a conexão falharia em cert_missing sem aviso."""
    pendencia = pendencias_da_conexao(
        connection_name="gateway-1",
        auth_mode="certificate",
        has_password=False,
        security_policy="none",
        server_cert_file=None,
        app_cert_exists=False,
    )
    assert pendencia.needs_server_certificate is False
    assert pendencia.needs_app_certificate is True


def test_connection_name_preservado_no_resultado():
    pendencia = pendencias_da_conexao(
        connection_name="gateway-2",
        auth_mode="anonymous",
        has_password=False,
        security_policy="none",
        server_cert_file=None,
        app_cert_exists=True,
    )
    assert pendencia.connection_name == "gateway-2"
