"""Grade de tempo sobre `samples` do sensor virtual (SPEC_SENSOR_VIRTUAL §5.7 e §7.3).

Cada ponto é a ÚLTIMA amostra da tag com `ts <= instante` e `ts > instante - limite`; amostra
BAD (gravada como NULL) ou ausente vira `nan` com BAD, sem olhar para trás.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
from runtime_test_helpers import create_connection, create_project, create_tag
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.models.timeseries import samples_table
from ottima_core.signal import Quality
from ottima_core.softsensor.grid import grid_instants, load_grid, staleness_limit_s

Sessions = async_sessionmaker[AsyncSession]
END = datetime.now(UTC).replace(microsecond=0)


async def _tags(factory: Sessions, n: int) -> list[int]:
    project_id = await create_project(factory)
    connection_id = await create_connection(factory, project_id)
    return [await create_tag(factory, connection_id, name=f"t{i}") for i in range(n)]


async def _samples(factory: Sessions, rows: list[tuple[int, float, float | None, int]]) -> None:
    """`(tag_id, segundos antes de END, valor, qualidade OPC)`."""
    async with factory() as session:
        await session.execute(
            insert(samples_table),
            [
                {"ts": END - timedelta(seconds=dt), "tag_id": t, "value": v, "quality": q}
                for t, dt, v, q in rows
            ],
        )
        await session.commit()


async def _grid(factory: Sessions, tag_ids: list[int], *, period_s: float = 1.0, steps: int = 1):
    async with factory() as session:
        return await load_grid(session, tag_ids, end=END, period_s=period_s, steps=steps)


def test_limite_de_idade():
    assert staleness_limit_s(1) == 180.0 and staleness_limit_s(600) == 1800.0


def test_instantes_do_mais_antigo_ao_mais_novo():
    assert grid_instants(END, 10.0, 3) == [
        END - timedelta(seconds=20),
        END - timedelta(seconds=10),
        END,
    ]


async def test_ponto_usa_a_ultima_amostra_em_ou_antes_do_instante(session_factory):
    (tag,) = await _tags(session_factory, 1)
    await _samples(session_factory, [(tag, 30, 1.0, 0), (tag, 20, 2.0, 0), (tag, 10, 3.0, 0)])
    await _samples(session_factory, [(tag, 0, 4.0, 0)])  # exatamente no instante: entra

    values, qualities = await _grid(session_factory, [tag], period_s=10.0, steps=3)

    np.testing.assert_array_equal(values, [[2.0], [3.0], [4.0]])
    assert qualities == [Quality.GOOD] * 3


async def test_amostra_posterior_ao_instante_nunca_entra(session_factory):
    (tag,) = await _tags(session_factory, 1)
    await _samples(session_factory, [(tag, 5, 2.0, 0), (tag, -1, 9.0, 0)])

    values, qualities = await _grid(session_factory, [tag])

    np.testing.assert_array_equal(values, [[2.0]])
    assert qualities == [Quality.GOOD]


async def test_amostra_mais_velha_que_o_limite_e_lacuna(session_factory):
    a, b = await _tags(session_factory, 2)
    await _samples(session_factory, [(a, 181, 1.0, 0), (b, 180, 1.0, 0)])  # limite é exclusivo

    values, qualities = await _grid(session_factory, [a, b])

    assert np.isnan(values).all()
    assert qualities == [Quality.BAD]


async def test_ultima_amostra_bad_e_lacuna_mesmo_com_boa_anterior(session_factory):
    (tag,) = await _tags(session_factory, 1)
    await _samples(session_factory, [(tag, 10, 5.0, 0), (tag, 2, None, 2)])

    values, qualities = await _grid(session_factory, [tag])

    assert np.isnan(values[0, 0])
    assert qualities == [Quality.BAD]


async def test_amostra_uncertain_mantem_valor_e_rebaixa_a_linha(session_factory):
    (tag,) = await _tags(session_factory, 1)
    await _samples(session_factory, [(tag, 1, 4.0, 1)])

    values, qualities = await _grid(session_factory, [tag])

    np.testing.assert_array_equal(values, [[4.0]])
    assert qualities == [Quality.UNCERTAIN]


async def test_qualidade_da_linha_e_a_pior_entre_as_tags(session_factory):
    a, b, c = await _tags(session_factory, 3)
    await _samples(session_factory, [(a, 1, 1.0, 0), (b, 1, 2.0, 1), (c, 1, 3.0, 0)])

    values, qualities = await _grid(session_factory, [a, b, c])

    np.testing.assert_array_equal(values, [[1.0, 2.0, 3.0]])
    assert qualities == [Quality.UNCERTAIN]


async def test_ordem_das_colunas_segue_tag_ids(session_factory):
    a, b = await _tags(session_factory, 2)
    await _samples(session_factory, [(a, 1, 1.0, 0), (b, 1, 2.0, 0)])

    values, _ = await _grid(session_factory, [b, a, b])

    np.testing.assert_array_equal(values, [[2.0, 1.0, 2.0]])
