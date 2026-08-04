"""Schema de leitura do log de eventos (RF-803): as mesmas 5 chaves do canal `events`."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class EventOut(BaseModel):
    ts: datetime
    severity: Literal["info", "warning", "alarm"]
    origin: str
    message: str
    payload: dict[str, Any]
