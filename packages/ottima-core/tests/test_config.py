from ottima_core.config import Settings


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
