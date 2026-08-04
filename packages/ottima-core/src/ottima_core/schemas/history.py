"""Schema colunar do histórico (RF-802): formato consumido direto pelo uPlot no trend."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

MAX_TAGS = 6
MAX_WINDOW_DAYS = 31
RAW_WINDOW_HOURS = 2


class HistorySeries(BaseModel):
    tag_id: int
    t: list[datetime]
    v: list[float]
    q: list[int]
    v_min: list[float] | None = None  # só em mode="1m"
    v_max: list[float] | None = None  # só em mode="1m"


class HistoryResponse(BaseModel):
    mode: Literal["raw", "1m"]
    start: datetime
    end: datetime
    series: list[HistorySeries]
