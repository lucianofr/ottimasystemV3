import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Default previsível de desenvolvimento: quem o conhece forja um JWT com role=admin.
# Usado como valor do campo e na checagem de boot — nunca duplicar a string.
INSECURE_SECRET_KEY_DEFAULT = "dev-inseguro-trocar-no-env"


class Settings(BaseSettings):
    """Configuração via variáveis OTTIMA_* (spec F1 §7.2)."""

    model_config = SettingsConfigDict(env_prefix="OTTIMA_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://ottima:ottima@localhost:5432/ottima"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = INSECURE_SECRET_KEY_DEFAULT
    fernet_key: str = ""  # OTTIMA_FERNET_KEY obrigatória para cifrar/decifrar segredos OPC
    token_ttl_hours: int = 12
    admin_username: str | None = None
    admin_password: str | None = None
    admin_name: str = "Administrador"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_secrets(settings: Settings) -> None:
    """Valida os segredos no boot: a chave de assinatura JWT é fatal, a Fernet é aviso.

    Levanta RuntimeError se OTTIMA_SECRET_KEY estiver vazia ou no default de dev — subir
    com JWT forjável derruba todo o RBAC, então não subir é o comportamento correto.
    """
    if not settings.secret_key or settings.secret_key == INSECURE_SECRET_KEY_DEFAULT:
        raise RuntimeError(
            "OTTIMA_SECRET_KEY não definida (ou mantida no default inseguro de desenvolvimento). "
            "Ela assina os tokens JWT: com o default, qualquer um forja um token de administrador. "
            "Defina uma chave própria antes de subir a aplicação, por exemplo: "
            "OTTIMA_SECRET_KEY=$(openssl rand -hex 32)"
        )
    if not settings.fernet_key:
        logger.critical(
            "OTTIMA_FERNET_KEY não definida: segredos de conexão OPC não poderão ser "
            "cifrados nem decifrados até que a variável seja configurada."
        )
