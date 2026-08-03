from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração via variáveis OTTIMA_* (spec F1 §7.2)."""

    model_config = SettingsConfigDict(env_prefix="OTTIMA_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://ottima:ottima@localhost:5432/ottima"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "dev-inseguro-trocar-no-env"  # default de dev: troque via OTTIMA_SECRET_KEY
    fernet_key: str = ""  # OTTIMA_FERNET_KEY obrigatória para cifrar/decifrar segredos OPC
    token_ttl_hours: int = 12
    admin_username: str | None = None
    admin_password: str | None = None
    admin_name: str = "Administrador"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
