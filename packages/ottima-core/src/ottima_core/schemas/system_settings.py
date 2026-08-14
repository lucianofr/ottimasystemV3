"""Schema de configurações gerais do sistema (RF-805)."""

from typing import Literal

from pydantic import BaseModel

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class SystemSettingsOut(BaseModel):
    log_level: LogLevel


class SystemSettingsUpdate(BaseModel):
    log_level: LogLevel
