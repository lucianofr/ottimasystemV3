"""Logging estruturado JSON em stdout (RNF-07; spec F1 §7.1)."""

import json
import logging
import sys
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class JsonFormatter(logging.Formatter):
    """Serializa cada registro como uma linha JSON com timestamp UTC."""

    def __init__(self, service: str = "unknown") -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": self._service,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: str = "INFO", service: str = "unknown") -> None:
    """Substitui os handlers do logger raiz por um único handler JSON em stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service=service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


async def watch_log_level(
    session_factory: async_sessionmaker[AsyncSession], *, interval_s: float = 10.0
) -> None:
    """Aplica `system_settings.log_level` ao root logger em runtime (RF-805).

    Poll simples em vez de canal novo no barramento (bus.py exige ADR para canal): a
    mudança propaga aos 4 serviços em até `interval_s`. Linha ausente ⇒ mantém o nível
    do boot; falha de leitura ⇒ loga e tenta de novo na próxima passada.
    """
    import asyncio

    logger = logging.getLogger(__name__)
    while True:
        await asyncio.sleep(interval_s)
        try:
            from ottima_core.models.system_settings import SystemSettings

            async with session_factory() as session:
                row = await session.get(SystemSettings, 1)
            if row is None:
                continue
            alvo = row.log_level.upper()
            root = logging.getLogger()
            if logging.getLevelName(root.getEffectiveLevel()) != alvo:
                root.setLevel(alvo)
                logger.info("Nível de log aplicado em runtime: %s", alvo)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha ao aplicar log_level de system_settings")
