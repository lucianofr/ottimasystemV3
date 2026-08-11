"""Schema colunar do histórico (RF-802): formato consumido direto pelo uPlot no trend."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from ottima_core.bus import SstoRun

MAX_TAGS = 6
MAX_WINDOW_DAYS = 31
RAW_WINDOW_HOURS = 2
MAX_MPC_VARS = 14  # 4 MV + 6 CV/Restrição + 4 DV (spec F5 §2.4)


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


class MpcHistorySeries(BaseModel):
    """Mesma forma de `HistorySeries`, com `var_id` no lugar de `tag_id`; `sp`/`auto`
    alinhados a `t` (spec F5 §2.4) — sem `q`, que não existe em `mpc_samples`."""

    var_id: str
    t: list[datetime]
    v: list[float]
    sp: list[float | None]
    auto: list[bool]
    v_min: list[float] | None = None  # só em mode="1m"
    v_max: list[float] | None = None  # só em mode="1m"


class MpcHistoryResponse(BaseModel):
    mode: Literal["raw", "1m"]
    start: datetime
    end: datetime
    series: list[MpcHistorySeries]


class SstoLastOut(BaseModel):
    """Última execução do SSTO de um bloco (`GET /api/history/ssto/last`) — cold-start do
    sumário do otimizador na Operação, sem esperar o próximo ciclo do MPC."""

    ts: datetime
    run: SstoRun
