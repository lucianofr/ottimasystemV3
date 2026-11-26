"""Congelamento do conjunto de treino do sensor virtual (SPEC_SENSOR_VIRTUAL §7.3, RF-586).

Cada análise vira uma janela de 256 passos terminando em `sampled_at`; linha da grade que não é
GOOD vira lacuna (`nan`); análise sem processo no instante da coleta é descartada.
"""

import io
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from runtime_test_helpers import create_connection, create_project, create_tag
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.models.timeseries import samples_table
from ottima_core.softsensor import dataset
from ottima_core.softsensor.dataset import (
    DATASET_STEPS,
    DatasetError,
    build_dataset,
    pack_dataset,
    unpack_dataset,
)

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


async def _build(
    factory: Sessions,
    tag_ids: list[int],
    analyses: list[tuple[datetime, float]],
    *,
    period_s: float = 1.0,
    report=None,
):
    async with factory() as session:
        blob, stats = await build_dataset(
            session, tag_ids=tag_ids, period_s=period_s, analyses=analyses, report=report
        )
    return unpack_dataset(blob), stats


def _npz(**arrays: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def test_pack_unpack_preserva_forma_nan_e_tipos():
    x = np.random.default_rng(0).normal(size=(2, DATASET_STEPS, 3)).astype(np.float32)
    x[1, 10, 2] = np.nan
    y = np.array([1.5, 2.5])
    ts = np.array([1_700_000_000.0, 1_700_000_600.0])

    x2, y2, ts2 = unpack_dataset(pack_dataset(x, y, ts))

    assert (x2.dtype, y2.dtype, ts2.dtype) == (np.float32, np.float64, np.float64)
    np.testing.assert_array_equal(x2, x)  # array_equal trata nan == nan como igual
    np.testing.assert_array_equal(y2, y)
    np.testing.assert_array_equal(ts2, ts)


def test_pack_recusa_acima_do_teto(monkeypatch):
    monkeypatch.setattr(dataset, "MAX_DATASET_BYTES", 1024)
    x = np.zeros((1, DATASET_STEPS, 2), dtype=np.float32)  # 2 KiB descomprimido

    with pytest.raises(DatasetError, match="teto"):
        pack_dataset(x, np.zeros(1), np.zeros(1))


def test_unpack_recusa_o_que_passa_do_teto(monkeypatch):
    blob = pack_dataset(np.zeros((1, DATASET_STEPS, 2), np.float32), np.zeros(1), np.zeros(1))
    monkeypatch.setattr(dataset, "MAX_DATASET_BYTES", 1024)

    with pytest.raises(DatasetError, match="teto"):
        unpack_dataset(blob)


def test_pack_recusa_forma_fora_do_contrato():
    with pytest.raises(DatasetError):  # janela de 100 passos, não 256
        pack_dataset(np.zeros((1, 100, 2)), np.zeros(1), np.zeros(1))
    with pytest.raises(DatasetError):  # y com tamanho diferente de n
        pack_dataset(np.zeros((2, DATASET_STEPS, 2)), np.zeros(1), np.zeros(2))


@pytest.mark.parametrize(
    "blob",
    [
        b"isto nao e um zip",
        _npz(x=np.zeros((1, DATASET_STEPS, 1), np.float32), y=np.zeros(1)),  # falta `ts`
        _npz(
            x=np.zeros((1, DATASET_STEPS, 1), np.float32),
            y=np.zeros(1),
            ts=np.zeros(1),
            extra=np.zeros(1),
        ),
        _npz(x=np.zeros((1, 100, 1), np.float32), y=np.zeros(1), ts=np.zeros(1)),  # forma
        _npz(x=np.zeros((1, DATASET_STEPS, 1)), y=np.zeros(1), ts=np.zeros(1)),  # x float64
    ],
    ids=["nao_zip", "sem_ts", "chave_extra", "forma", "dtype"],
)
def test_unpack_recusa_blob_fora_do_contrato(blob):
    with pytest.raises(DatasetError):
        unpack_dataset(blob)


_PICKLE_RAN: list[str] = []


def _pickle_side_effect() -> None:
    _PICKLE_RAN.append("executado")


class _PickleBomb:
    def __reduce__(self):  # roda ao gravar (inofensivo); `_pickle_side_effect` roda ao ABRIR
        return (_pickle_side_effect, ())


def test_unpack_nunca_abre_pickle():
    _PICKLE_RAN.clear()
    obj = np.empty(1, dtype=object)
    obj[0] = _PickleBomb()
    blob = _npz(x=obj, y=np.zeros(1), ts=np.zeros(1))
    assert _PICKLE_RAN == []  # gravar o npz não dispara o efeito: só desserializar dispara

    with pytest.raises(DatasetError, match="allow_pickle"):
        unpack_dataset(blob)

    assert _PICKLE_RAN == []  # o pickle nunca foi desserializado


async def test_janela_termina_no_instante_da_coleta(session_factory):
    (tag,) = await _tags(session_factory, 1)
    await _samples(session_factory, [(tag, 20, 1.0, 0), (tag, 10, 2.0, 0), (tag, 0, 3.0, 0)])

    (x, y, ts), stats = await _build(session_factory, [tag], [(END, 7.0)], period_s=10.0)

    np.testing.assert_array_equal(x[0, -3:, 0], [1.0, 2.0, 3.0])  # a última linha é a de `END`
    assert x.shape == (1, DATASET_STEPS, 1) and x.dtype == np.float32
    assert y.tolist() == [7.0] and ts.tolist() == [END.timestamp()]
    assert stats == {"analyses": 1, "dropped_no_process": 0, "paired": 1, "full_window": 0}


async def test_amostra_posterior_a_coleta_nunca_entra(session_factory):
    (tag,) = await _tags(session_factory, 1)
    await _samples(session_factory, [(tag, 5, 2.0, 0), (tag, -1, 9.0, 0)])

    (x, _, _), _ = await _build(session_factory, [tag], [(END, 0.0)])

    assert x[0, -1, 0] == 2.0
    assert not (x == 9.0).any()


async def test_analise_sem_processo_no_instante_e_descartada(session_factory):
    (tag,) = await _tags(session_factory, 1)
    await _samples(session_factory, [(tag, 500, 1.0, 0)])  # mais velha que o limite de 180 s

    (x, y, ts), stats = await _build(session_factory, [tag], [(END, 1.0)])

    assert stats == {"analyses": 1, "dropped_no_process": 1, "paired": 0, "full_window": 0}
    assert x.shape == (0, DATASET_STEPS, 1) and y.shape == (0,) and ts.shape == (0,)


async def test_lacuna_no_meio_da_janela_mantem_a_analise_com_nan(session_factory):
    (tag,) = await _tags(session_factory, 1)
    # Passo 1 s, limite 180 s: a amostra de 250 s cobre os instantes de 250 s a 71 s antes de END;
    # antes dela e depois dela até a amostra de END há lacuna.
    await _samples(session_factory, [(tag, 250, 5.0, 0), (tag, 0, 1.0, 0)])

    (x, y, _), stats = await _build(session_factory, [tag], [(END, 3.0)])

    assert stats == {"analyses": 1, "dropped_no_process": 0, "paired": 1, "full_window": 0}
    assert x[0, -1, 0] == 1.0
    assert x[0, DATASET_STEPS - 1 - 100, 0] == 5.0  # 100 s antes de END
    assert np.isnan(x[0, :4, 0]).all()  # 255..252 s antes: ainda sem amostra
    assert np.isnan(x[0, DATASET_STEPS - 1 - 30, 0])  # 30 s antes: a de 250 s já expirou
    assert y.tolist() == [3.0]


async def test_linha_uncertain_vira_lacuna_na_linha_inteira(session_factory):
    a, b = await _tags(session_factory, 2)
    await _samples(
        session_factory,
        [(a, 1, 1.0, 0), (a, 0, 2.0, 0), (b, 1, 10.0, 1), (b, 0, 20.0, 0)],  # b em END-1: UNCERTAIN
    )

    (x, _, _), stats = await _build(session_factory, [a, b], [(END, 0.0)])

    assert np.isnan(x[0, -2, :]).all()  # `a` estava GOOD, mas a linha inteira é descartada
    np.testing.assert_array_equal(x[0, -1, :], [2.0, 20.0])
    assert stats["paired"] == 1 and stats["full_window"] == 0


async def test_analise_com_ultima_linha_uncertain_e_descartada(session_factory):
    (tag,) = await _tags(session_factory, 1)
    await _samples(session_factory, [(tag, 0, 4.0, 1)])

    (x, _, _), stats = await _build(session_factory, [tag], [(END, 0.0)])

    assert stats == {"analyses": 1, "dropped_no_process": 1, "paired": 0, "full_window": 0}
    assert x.shape[0] == 0


async def test_ultima_linha_bad_e_descartada_mesmo_com_boa_anterior(session_factory):
    (tag,) = await _tags(session_factory, 1)
    await _samples(session_factory, [(tag, 10, 5.0, 0), (tag, 0, None, 2)])

    _, stats = await _build(session_factory, [tag], [(END, 0.0)])

    assert stats["dropped_no_process"] == 1


async def test_janela_busca_dado_anterior_ao_inicio_do_periodo(session_factory):
    (tag,) = await _tags(session_factory, 1)
    # Passo de 10 s: a janela vai a 2550 s antes de END. O período só escolhe as análises; a
    # grade lê o processo onde ele estiver, inclusive muito antes de qualquer `start_ts`.
    offsets = range(0, 2561, 10)
    await _samples(session_factory, [(tag, float(dt), float(dt), 0) for dt in offsets])

    (x, _, _), stats = await _build(session_factory, [tag], [(END, 0.0)], period_s=10.0)

    np.testing.assert_array_equal(x[0, :, 0], np.arange(2550.0, -1.0, -10.0))
    assert stats["full_window"] == 1


async def test_ordem_das_colunas_segue_tag_ids(session_factory):
    a, b = await _tags(session_factory, 2)
    await _samples(session_factory, [(a, 0, 1.0, 0), (b, 0, 2.0, 0)])

    (x, _, _), _ = await _build(session_factory, [b, a], [(END, 0.0)])

    np.testing.assert_array_equal(x[0, -1, :], [2.0, 1.0])


async def test_analises_saem_em_ordem_de_coleta(session_factory):
    (tag,) = await _tags(session_factory, 1)
    await _samples(session_factory, [(tag, 20, 1.0, 0), (tag, 0, 2.0, 0)])
    early = END - timedelta(seconds=10)

    (x, y, ts), _ = await _build(session_factory, [tag], [(END, 20.0), (early, 10.0)])

    assert y.tolist() == [10.0, 20.0]
    assert ts.tolist() == [early.timestamp(), END.timestamp()]
    assert x[0, -1, 0] == 1.0 and x[1, -1, 0] == 2.0


async def test_sem_analises_devolve_conjunto_vazio(session_factory):
    (t1,) = await _tags(session_factory, 1)

    (x, y, ts), stats = await _build(session_factory, [t1], [])

    assert x.shape == (0, DATASET_STEPS, 1) and y.shape == (0,) and ts.shape == (0,)
    assert stats == {"analyses": 0, "dropped_no_process": 0, "paired": 0, "full_window": 0}


async def test_report_e_chamado_por_analise(session_factory):
    (tag,) = await _tags(session_factory, 1)
    await _samples(session_factory, [(tag, 10, 1.0, 0), (tag, 0, 1.0, 0)])
    calls: list[tuple[int, int]] = []
    analyses = [(END - timedelta(days=1), 1.0), (END - timedelta(seconds=5), 2.0), (END, 3.0)]

    _, stats = await _build(
        session_factory, [tag], analyses, report=lambda i, total: calls.append((i, total))
    )

    assert calls == [(1, 3), (2, 3), (3, 3)]  # inclui a descartada (a de ontem não tem processo)
    assert stats["dropped_no_process"] == 1


async def test_teto_estimado_recusa_antes_de_ler_qualquer_janela(session_factory, monkeypatch):
    (tag,) = await _tags(session_factory, 1)
    por_analise = DATASET_STEPS * 4 + 8 + 8  # x float32 com 1 entrada + y e ts float64
    monkeypatch.setattr(dataset, "MAX_DATASET_BYTES", 2 * por_analise)
    lidas: list[datetime] = []

    async def load_grid_espiao(session, tag_ids, *, end, period_s, steps):
        lidas.append(end)
        raise AssertionError("o teto estimado tinha de recusar antes de ler")

    monkeypatch.setattr(dataset, "load_grid", load_grid_espiao)
    analyses = [(END - timedelta(seconds=i), 1.0) for i in range(3)]

    with pytest.raises(DatasetError, match="teria 3 análises com 1 entradas.*máximo de 2"):
        await _build(session_factory, [tag], analyses)

    assert lidas == []


async def test_teto_estimado_aceita_exatamente_o_maximo(session_factory, monkeypatch):
    (tag,) = await _tags(session_factory, 1)
    monkeypatch.setattr(dataset, "MAX_DATASET_BYTES", 2 * (DATASET_STEPS * 4 + 8 + 8))
    analyses = [(END - timedelta(seconds=i), 1.0) for i in range(2)]

    _, stats = await _build(session_factory, [tag], analyses)  # sem processo: ambas descartadas

    assert stats["analyses"] == 2
