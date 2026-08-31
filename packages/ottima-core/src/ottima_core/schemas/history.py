"""Schema colunar do histórico (RF-802): formato consumido direto pelo uPlot no trend."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from ottima_core.bus import SstoRun

MAX_TAGS = 6
MAX_WINDOW_DAYS = 31
RAW_WINDOW_HOURS = 2
MAX_MPC_VARS = 14  # 4 MV + 6 CV/Restrição + 4 DV (spec F5 §2.4)
MAX_FUZZY_VARS = 16  # IN1..IN8 + OUT1..OUT8 (ADR-030, ADR-029)


class HistorySeries(BaseModel):
    tag_id: int
    t: list[datetime]
    v: list[float | None]  # None onde quality==2 (BAD) gravou NULL no lugar do valor (ADR-037)
    q: list[int]
    v_min: list[float | None] | None = None  # só em mode="1m"; None por item: bucket sem
    v_max: list[float | None] | None = None  # amostra finita (avg/min/max ignoram NULL no SQL)


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


class FuzzyHistorySeries(BaseModel):
    """Mesma forma de `HistorySeries`, com `var_id` no lugar de `tag_id` (porta IN1..OUT8,
    ADR-029) — sem `q`/`sp`/`auto`, que não existem em `fuzzy_samples`."""

    var_id: str
    t: list[datetime]
    v: list[float]
    v_min: list[float] | None = None  # só em mode="1m"
    v_max: list[float] | None = None  # só em mode="1m"


class FuzzyHistoryResponse(BaseModel):
    mode: Literal["raw", "1m"]
    start: datetime
    end: datetime
    series: list[FuzzyHistorySeries]


class LoopHistorySeries(BaseModel):
    """Mesma forma de `FuzzyHistorySeries` (ADR-039 4.10): `var_id` em pv|sp|out|mode;
    `v` nullavel — PV com qualidade ruim grava NULL (mesmo idiom de samples, ADR-037)."""

    var_id: str
    t: list[datetime]
    v: list[float | None]
    v_min: list[float | None] | None = None  # so em mode="1m"
    v_max: list[float | None] | None = None  # so em mode="1m"


class LoopHistoryResponse(BaseModel):
    mode: Literal["raw", "1m"]
    start: datetime
    end: datetime
    series: list[LoopHistorySeries]


class SstoLastOut(BaseModel):
    """Última execução do SSTO de um bloco (`GET /api/history/ssto/last`) — cold-start do
    sumário do otimizador na Operação, sem esperar o próximo ciclo do MPC."""

    ts: datetime
    run: SstoRun
