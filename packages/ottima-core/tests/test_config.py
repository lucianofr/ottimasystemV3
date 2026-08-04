import logging

import pytest

from ottima_core.config import INSECURE_SECRET_KEY_DEFAULT, Settings, validate_secrets


def test_settings_le_env_com_prefixo(monkeypatch):
    monkeypatch.setenv("OTTIMA_DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/db")
    monkeypatch.setenv("OTTIMA_TOKEN_TTL_HOURS", "3")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/db"
    assert s.token_ttl_hours == 3


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.token_ttl_hours == 12
    assert s.admin_name == "Administrador"
    assert s.log_level == "INFO"


def test_validate_secrets_rejeita_default_inseguro(monkeypatch):
    monkeypatch.delenv("OTTIMA_SECRET_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.secret_key == INSECURE_SECRET_KEY_DEFAULT
    with pytest.raises(RuntimeError, match="OTTIMA_SECRET_KEY"):
        validate_secrets(s)


def test_validate_secrets_rejeita_segredo_vazio():
    s = Settings(_env_file=None, secret_key="")
    with pytest.raises(RuntimeError, match="OTTIMA_SECRET_KEY"):
        validate_secrets(s)


def test_validate_secrets_aceita_segredo_proprio():
    s = Settings(_env_file=None, secret_key="segredo-proprio", fernet_key="k")
    validate_secrets(s)


def test_validate_secrets_apenas_alerta_sem_fernet_key(caplog):
    # Chamado direto (sem create_app): setup_logging zera root.handlers e cega o caplog.
    s = Settings(_env_file=None, secret_key="segredo-proprio", fernet_key="")
    with caplog.at_level(logging.CRITICAL):
        validate_secrets(s)
    assert any(
        r.levelno == logging.CRITICAL and "OTTIMA_FERNET_KEY" in r.getMessage()
        for r in caplog.records
    )
