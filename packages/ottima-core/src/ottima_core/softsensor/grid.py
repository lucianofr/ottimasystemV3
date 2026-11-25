"""Grade de tempo sobre `samples`: a mesma para pré-aquecimento e conjunto de treino.

Spec SENSOR_VIRTUAL §5.7 e §7.3: cada ponto é a ÚLTIMA amostra da tag em ou antes do
instante, não mais velha que `staleness_limit_s`. Amostra BAD (o recorder grava `value` NULL,
ADR-037) ou ausente é lacuna: `nan` com BAD, sem procurar uma boa mais antiga.
"""

import math
from collections.abc import Sequence
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.signal import Quality

STALENESS_FLOOR_S = 180.0  # fontes legítimas publicam a cada 60 s (§7.3)

# `samples.quality` tem a polaridade OPC (0 GOOD, 1 UNCERTAIN, 2 BAD); `Quality` é a inversa.
_QUALITY = {0: Quality.GOOD, 1: Quality.UNCERTAIN}

# Uma instrução só: instantes x tags, e para cada par a última amostra pelo índice
# `ix_samples_tag_ts (tag_id, ts DESC)`. A qualidade é julgada fora, nunca no WHERE.
_GRID_SQL = text(
    """
    SELECT g.ri, c.ci, s.value, s.quality
    FROM unnest(CAST(:instants AS timestamptz[])) WITH ORDINALITY AS g(instant, ri)
    CROSS JOIN unnest(CAST(:tag_ids AS bigint[])) WITH ORDINALITY AS c(tag_id, ci)
    LEFT JOIN LATERAL (
        SELECT samples.value, samples.quality
        FROM samples
        WHERE samples.tag_id = c.tag_id
          AND samples.ts <= g.instant
          AND samples.ts > g.instant - CAST(:limit_s AS double precision) * interval '1 second'
        ORDER BY samples.ts DESC
        LIMIT 1
    ) AS s ON true
    """
)


def staleness_limit_s(period_s: float) -> float:
    return max(3 * period_s, STALENESS_FLOOR_S)


def grid_instants(end: datetime, period_s: float, steps: int) -> list[datetime]:
    """`end - k * period_s`, `k = steps-1 .. 0`: o mais antigo primeiro."""
    return [end - timedelta(seconds=k * period_s) for k in range(steps - 1, -1, -1)]


async def load_grid(
    session: AsyncSession,
    tag_ids: Sequence[int],
    *,
    end: datetime,
    period_s: float,
    steps: int,
) -> tuple[np.ndarray, list[Quality]]:
    """Matriz `[steps, len(tag_ids)]` (`nan` na lacuna) e a pior qualidade de cada linha."""
    values = np.full((steps, len(tag_ids)), np.nan)
    worst = [Quality.GOOD] * steps
    result = await session.execute(
        _GRID_SQL,
        {
            "instants": grid_instants(end, period_s, steps),
            "tag_ids": list(tag_ids),
            "limit_s": staleness_limit_s(period_s),
        },
    )
    for ri, ci, value, quality in result:
        good_value = value is not None and math.isfinite(value)
        q = _QUALITY.get(quality, Quality.BAD) if good_value else Quality.BAD
        if q is not Quality.BAD:
            values[ri - 1, ci - 1] = value
        worst[ri - 1] = min(worst[ri - 1], q)
    return values, worst
