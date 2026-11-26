"""Congelamento do conjunto de treino do sensor virtual (RF-586, SPEC_SENSOR_VIRTUAL §7.3).

Cada análise de laboratório vira uma janela de `DATASET_STEPS` passos terminando em `sampled_at`,
lida pela mesma grade do pré-aquecimento (`load_grid`). Só vale a linha GOOD; as demais viram
`nan` na linha inteira. Análise cuja última linha é lacuna é descartada: nenhum método a usa.
O blob é um `.npz` lido SEMPRE com `allow_pickle=False` (ADR-046).
"""

import asyncio
import io
import zipfile
from collections.abc import Callable, Sequence
from datetime import datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.models import SoftSensorDataset
from ottima_core.signal import Quality
from ottima_core.softsensor.grid import load_grid

PERIODS_S: tuple[int, ...] = (1, 2, 5, 10, 30, 60, 300, 600)
DATASET_STEPS = 256
MAX_DATASET_BYTES = 64 * 1024 * 1024  # teto do blob e do descomprimido: contém zip bomb

_DTYPES = {"x": np.float32, "y": np.float64, "ts": np.float64}


class DatasetError(ValueError):
    """Conjunto fora do contrato, fora do teto ou blob ilegível."""


def _check_contract(x: np.ndarray, y: np.ndarray, ts: np.ndarray) -> None:
    if x.ndim != 3 or x.shape[1] != DATASET_STEPS:
        raise DatasetError(f"x com forma {x.shape}, esperado [n, {DATASET_STEPS}, n_inputs]")
    if y.shape != (x.shape[0],) or ts.shape != (x.shape[0],):
        raise DatasetError(f"y {y.shape} e ts {ts.shape} devem ter forma [{x.shape[0]}]")


def _check_limits(blob: bytes) -> None:
    """Rejeição precoce pelo tamanho do blob e pelo tamanho DECLARADO das entradas.

    O `file_size` do zip é dado pelo autor e pode mentir: isto só recusa cedo o blob honesto e
    grande. O que limita a leitura de verdade é `unpack_dataset` ler por `zf.open` em blocos.
    """
    if len(blob) > MAX_DATASET_BYTES:
        raise DatasetError(f"conjunto de {len(blob)} bytes passa do teto de {MAX_DATASET_BYTES}")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        unpacked = sum(info.file_size for info in zf.infolist())
    if unpacked > MAX_DATASET_BYTES:
        raise DatasetError(
            f"conjunto descomprimido de {unpacked} bytes passa do teto de {MAX_DATASET_BYTES}"
        )


def pack_dataset(x: np.ndarray, y: np.ndarray, ts: np.ndarray) -> bytes:
    arrays = {k: np.asarray(v, dtype=_DTYPES[k]) for k, v in (("x", x), ("y", y), ("ts", ts))}
    _check_contract(**arrays)
    raw = sum(a.nbytes for a in arrays.values())
    if raw > MAX_DATASET_BYTES:  # antes de comprimir centenas de MB à toa
        raise DatasetError(f"conjunto de {raw} bytes passa do teto de {MAX_DATASET_BYTES}")
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    blob = buf.getvalue()
    _check_limits(blob)  # nunca grava o que unpack_dataset recusaria (cabeçalhos .npy incluídos)
    return blob


def unpack_dataset(blob: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    try:
        _check_limits(blob)
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for info in zf.infolist():
                # Não usar np.load: com magic ruim ele cai em `zip.read`, que descomprime a
                # entrada inteira ignorando o `file_size`. `zf.open` + `read_array` lê em blocos.
                with zf.open(info) as fh:
                    arrays[info.filename.removesuffix(".npy")] = np.lib.format.read_array(
                        fh, allow_pickle=False
                    )
    except DatasetError:
        raise
    except Exception as exc:  # zip truncado, não-npz, magic ruim, pickle recusado, CRC
        raise DatasetError(f"conjunto ilegível: {exc}") from exc
    if arrays.keys() != _DTYPES.keys():
        raise DatasetError(f"conjunto com entradas {sorted(arrays)}, esperado {sorted(_DTYPES)}")
    wrong = [k for k, dtype in _DTYPES.items() if arrays[k].dtype != dtype]
    if wrong:
        raise DatasetError(f"conjunto com dtype incorreto em {wrong}")
    _check_contract(**arrays)
    return arrays["x"], arrays["y"], arrays["ts"]


async def build_dataset(
    session: AsyncSession,
    *,
    tag_ids: Sequence[int],
    period_s: float,
    analyses: Sequence[tuple[datetime, float]],
    report: Callable[[int, int], None] | None = None,
) -> tuple[bytes, dict[str, int]]:
    """Congela `analyses` (`(sampled_at, valor)`) em um `.npz` e devolve as estatísticas (§7.3)."""
    ordered = sorted(analyses, key=lambda a: a[0])
    total = len(ordered)
    # Limite superior do blob (as descartadas não entram): recusa ANTES de ler um mês de grade.
    # O `pack_dataset` segue como a guarda exata.
    sizes = {k: np.dtype(t).itemsize for k, t in _DTYPES.items()}
    per_analysis = DATASET_STEPS * len(tag_ids) * sizes["x"] + sizes["y"] + sizes["ts"]
    if total * per_analysis > MAX_DATASET_BYTES:
        raise DatasetError(
            f"O conjunto teria {total} análises com {len(tag_ids)} entradas, acima do máximo de "
            f"{MAX_DATASET_BYTES // per_analysis} para esse número de entradas; "
            "encurte o período ou reduza as entradas."
        )
    xs: list[np.ndarray] = []
    ys: list[float] = []
    stamps: list[float] = []
    full_window = 0
    for i, (sampled_at, value) in enumerate(ordered, 1):
        grid, worst = await load_grid(
            session, tag_ids, end=sampled_at, period_s=period_s, steps=DATASET_STEPS
        )
        good = np.array([q is Quality.GOOD for q in worst])
        if good[-1]:
            grid[~good] = np.nan  # linha UNCERTAIN ou BAD vira lacuna inteira
            xs.append(grid.astype(np.float32))
            ys.append(value)
            stamps.append(sampled_at.timestamp())
            full_window += int(good.all())
        if report is not None:
            report(i, total)
    x = np.stack(xs) if xs else np.empty((0, DATASET_STEPS, len(tag_ids)), dtype=np.float32)
    blob = await asyncio.to_thread(pack_dataset, x, np.array(ys), np.array(stamps))
    dropped = total - len(xs)
    stats = {
        "analyses": total,
        "dropped_no_process": dropped,
        "paired": len(xs),
        "full_window": full_window,
    }
    return blob, stats


async def load_compatible_datasets(
    session: AsyncSession, project_id: int, dataset_ids: Sequence[int]
) -> list[SoftSensorDataset]:
    """Conjuntos de um treino (RF-586): `ready`, do projeto, com a mesma variável, as mesmas
    entradas na mesma ordem e o mesmo período. Sem o `data` (deferred); repetido conta uma vez."""
    ids = list(dict.fromkeys(dataset_ids))
    if not ids:
        raise DatasetError("Informe ao menos um conjunto de treino")
    found = {
        ds.id: ds
        for ds in await session.scalars(
            select(SoftSensorDataset).where(
                SoftSensorDataset.project_id == project_id, SoftSensorDataset.id.in_(ids)
            )
        )
    }
    datasets = []
    for dataset_id in ids:
        if dataset_id not in found:
            raise DatasetError(f"Conjunto {dataset_id} não existe neste projeto")
        if found[dataset_id].status != "ready":
            raise DatasetError(f"Conjunto '{found[dataset_id].name}' ainda não está pronto")
        datasets.append(found[dataset_id])
    first = datasets[0]
    if any(ds.lab_variable_id != first.lab_variable_id for ds in datasets):
        raise DatasetError("Conjuntos com variáveis de laboratório diferentes")
    if any(ds.input_tag_ids != first.input_tag_ids for ds in datasets):
        raise DatasetError("Conjuntos com entradas diferentes")
    if any(ds.period_s != first.period_s for ds in datasets):
        raise DatasetError("Conjuntos com períodos diferentes")
    return datasets
