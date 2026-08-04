"""Histórico colunar com downsampling automático (RF-802): bruto até 2 h, CAgg 1 min acima."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Row, column, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_api.deps import get_db, require_operator
from ottima_core.models import samples_table
from ottima_core.schemas.history import (
    MAX_TAGS,
    MAX_WINDOW_DAYS,
    RAW_WINDOW_HOURS,
    HistoryResponse,
    HistorySeries,
)

# O CAgg é view materializada criada em SQL cru na migration 0002 e não tem handle no core:
# um Table() em qualquer MetaData o exporia ao autogenerate do Alembic. Aqui basta o
# construto leve `table()/column()`, que só sabe emitir SELECT e não participa de DDL.
samples_1m = table(
    "samples_1m",
    column("bucket"),
    column("tag_id"),
    column("avg_value"),
    column("min_value"),
    column("max_value"),
    column("worst_quality"),
)

MAX_TAG_ID = 2**63 - 1  # tag_id é BIGINT no banco

ERRO_VAZIO = "tag_ids não pode ser vazio"
ERRO_NAO_INTEIRO = "tag_ids deve conter apenas inteiros separados por vírgula"

router = APIRouter()


def _as_utc(value: datetime | None) -> datetime | None:
    """ISO-8601 sem offset vale como UTC; a coluna é timestamptz e não aceita naive."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _e_tag_id(bruto: str) -> bool:
    """Nenhuma entrada de tag_ids pode virar 5xx: o que o banco não aceitaria é 422 aqui.

    `isdecimal` e não `isdigit` porque "²"/"①" são isdigit mas `int()` os rejeita
    (ValueError ⇒ 500). O teto é o do BIGINT: um decimal maior passa pelo `int()` do Python
    e só estoura no bind do asyncpg (⇒ 500). O piso é 1 porque a coluna é BIGSERIAL.
    """
    return bruto.isdecimal() and 1 <= int(bruto) <= MAX_TAG_ID


def _parse_tag_ids(bruto: str) -> list[int]:
    """Lista separada por vírgula, deduplicada preservando a ordem de entrada."""
    if not bruto.strip():
        raise HTTPException(status_code=422, detail=ERRO_VAZIO)
    # sem descartar itens vazios: "1," e "1,,2" são entrada malformada, não lista de um id
    itens = [p.strip() for p in bruto.split(",")]
    if any(not _e_tag_id(p) for p in itens):
        raise HTTPException(status_code=422, detail=ERRO_NAO_INTEIRO)
    ids = list(dict.fromkeys(int(p) for p in itens))
    if len(ids) > MAX_TAGS:
        raise HTTPException(status_code=422, detail=f"no máximo {MAX_TAGS} tags por consulta")
    return ids


@router.get(
    "",
    response_model=HistoryResponse,
    response_model_exclude_none=True,  # v_min/v_max somem do JSON no modo raw
    dependencies=[Depends(require_operator)],
)
async def get_history(
    tag_ids: str,
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    """Uma série por tag pedida, sempre; ordem temporal crescente (uPlot exige x monotônico)."""
    ids = _parse_tag_ids(tag_ids)
    end = _as_utc(end) or datetime.now(UTC)
    start = _as_utc(start) or end - timedelta(hours=1)
    if start >= end:
        raise HTTPException(status_code=422, detail="start deve ser anterior a end")
    if end - start > timedelta(days=MAX_WINDOW_DAYS):
        raise HTTPException(
            status_code=422, detail=f"janela não pode exceder {MAX_WINDOW_DAYS} dias"
        )

    downsample = end - start > timedelta(hours=RAW_WINDOW_HOURS)
    if downsample:
        tag_col, ts_col = samples_1m.c.tag_id, samples_1m.c.bucket
        colunas = [
            tag_col,
            ts_col.label("ts"),  # "t" colidiria com Row.t (acessor de tupla do SQLAlchemy)
            samples_1m.c.avg_value.label("v"),
            samples_1m.c.worst_quality.label("q"),
            samples_1m.c.min_value.label("v_min"),
            samples_1m.c.max_value.label("v_max"),
        ]
    else:
        tag_col, ts_col = samples_table.c.tag_id, samples_table.c.ts
        colunas = [
            tag_col,
            ts_col.label("ts"),
            samples_table.c.value.label("v"),
            samples_table.c.quality.label("q"),
        ]

    # Uma única query para todas as tags; o agrupamento por tag é feito em memória.
    stmt = (
        select(*colunas)
        .where(tag_col.in_(ids), ts_col >= start, ts_col <= end)
        .order_by(tag_col, ts_col)
    )
    por_tag: dict[int, list[Row[Any]]] = {tag_id: [] for tag_id in ids}
    for linha in (await db.execute(stmt)).all():
        por_tag[linha.tag_id].append(linha)

    return HistoryResponse(
        mode="1m" if downsample else "raw",
        start=start,
        end=end,
        series=[
            HistorySeries(
                tag_id=tag_id,
                t=[linha.ts for linha in linhas],
                v=[linha.v for linha in linhas],
                q=[linha.q for linha in linhas],
                v_min=[linha.v_min for linha in linhas] if downsample else None,
                v_max=[linha.v_max for linha in linhas] if downsample else None,
            )
            for tag_id, linhas in por_tag.items()
        ],
    )
