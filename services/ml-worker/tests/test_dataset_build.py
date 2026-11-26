"""Handler `dataset_build` (SPEC_SENSOR_VIRTUAL §7.3, RF-586): congela o conjunto `building`."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import insert
from sqlalchemy.orm import undefer

from ottima_core.models import LabSample, SoftSensorDataset
from ottima_core.models.timeseries import samples_table
from ottima_core.softsensor import DATASET_STEPS, unpack_dataset
from ottima_ml_worker.handlers import HANDLERS, JobContext

T = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)


async def _samples(factory, tag_id: int, value: float, start: datetime, end: datetime) -> None:
    """Amostra GOOD a cada segundo em `[start, end]`."""
    n = int((end - start).total_seconds()) + 1
    async with factory() as session:
        await session.execute(
            insert(samples_table),
            [
                {"ts": start + timedelta(seconds=k), "tag_id": tag_id, "value": value, "quality": 0}
                for k in range(n)
            ],
        )
        await session.commit()


async def _analyses(factory, lab_variable_id: int, rows: list[tuple[datetime, float]]) -> None:
    async with factory() as session:
        session.add_all(
            LabSample(
                lab_variable_id=lab_variable_id,
                sampled_at=at,
                value=v,
                source="manual",
                created_by="teste",
            )
            for at, v in rows
        )
        await session.commit()


async def _build(factory, dataset_id: int) -> tuple[dict, list[dict]]:
    reports: list[dict] = []
    ctx = JobContext(
        job_id=1, params={"dataset_id": dataset_id}, session_factory=factory, report=reports.append
    )
    return await HANDLERS["dataset_build"](ctx), reports


async def _dataset(factory, dataset_id: int) -> SoftSensorDataset:
    async with factory() as session:
        return await session.get(
            SoftSensorDataset, dataset_id, options=[undefer(SoftSensorDataset.data)]
        )


async def test_conjunto_building_vira_ready_com_stats(
    session_factory, make_tag, make_dataset, lab_variable_id
):
    a = await make_tag("a", eu="kg/h")
    b = await make_tag("b", eu="°C")
    await _samples(session_factory, a, 10.0, T - timedelta(seconds=400), T)
    await _samples(session_factory, b, 20.0, T - timedelta(seconds=400), T)
    await _analyses(
        session_factory,
        lab_variable_id,
        [
            (T - timedelta(seconds=100), 1.0),
            (T - timedelta(seconds=50), 2.0),
            (T - timedelta(seconds=10), 9.0),  # depois do end_ts: fora
        ],
    )
    dataset_id = await make_dataset(
        [b, a], start_ts=T - timedelta(seconds=200), end_ts=T - timedelta(seconds=20)
    )

    stats, reports = await _build(session_factory, dataset_id)

    assert stats == {"analyses": 2, "dropped_no_process": 0, "paired": 2, "full_window": 2}
    assert reports[-1] == {"done": 2, "total": 2}
    ds = await _dataset(session_factory, dataset_id)
    assert ds.status == "ready"
    assert ds.stats == stats
    assert ds.inputs_meta == [
        {"tag_id": b, "name": "b", "eu": "°C"},
        {"tag_id": a, "name": "a", "eu": "kg/h"},
    ]
    x, y, _ = unpack_dataset(ds.data)
    assert x.shape == (2, DATASET_STEPS, 2)
    np.testing.assert_array_equal(x[0, -1], [20.0, 10.0])  # colunas na ordem de input_tag_ids
    np.testing.assert_array_equal(y, [1.0, 2.0])


async def test_conjunto_sem_analises_fica_ready_vazio(session_factory, make_tag, make_dataset):
    dataset_id = await make_dataset([await make_tag("a")])

    stats, _ = await _build(session_factory, dataset_id)

    assert stats["analyses"] == 0
    ds = await _dataset(session_factory, dataset_id)
    assert ds.status == "ready"
    assert unpack_dataset(ds.data)[0].shape == (0, DATASET_STEPS, 1)


async def test_tag_de_entrada_apagada_falha_com_mensagem(session_factory, make_tag, make_dataset):
    a = await make_tag("a")
    dataset_id = await make_dataset([a, a + 999])

    with pytest.raises(Exception, match=f"Tag de entrada {a + 999} não existe mais no projeto"):
        await _build(session_factory, dataset_id)

    assert (await _dataset(session_factory, dataset_id)).status == "building"


async def test_conjunto_fora_de_building_nao_e_construido(session_factory, make_tag, make_dataset):
    dataset_id = await make_dataset([await make_tag("a")], status="ready")

    with pytest.raises(Exception, match="building"):
        await _build(session_factory, dataset_id)


async def test_analise_antes_do_start_ts_fica_fora_mas_a_janela_le_o_processo_anterior(
    session_factory, make_tag, make_dataset, lab_variable_id
):
    a = await make_tag("a")
    await _samples(session_factory, a, 5.0, T - timedelta(seconds=300), T + timedelta(seconds=60))
    dentro = T + timedelta(seconds=10)
    await _analyses(
        session_factory, lab_variable_id, [(T - timedelta(seconds=5), 1.0), (dentro, 2.0)]
    )
    dataset_id = await make_dataset([a], start_ts=T, end_ts=T + timedelta(seconds=60))

    stats, _ = await _build(session_factory, dataset_id)

    assert (stats["analyses"], stats["paired"]) == (1, 1)
    x, y, ts = unpack_dataset((await _dataset(session_factory, dataset_id)).data)
    # A janela termina em T+10 e começa 255 s antes: a maior parte é processo anterior ao start_ts.
    assert not np.isnan(x[0]).any()
    np.testing.assert_array_equal(y, [2.0])
    np.testing.assert_array_equal(ts, [dentro.timestamp()])
