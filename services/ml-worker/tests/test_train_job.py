"""Handler `train` (RF-587, SPEC_SENSOR_VIRTUAL §8.1): lê os conjuntos `ready`, treina e grava o
modelo como último passo. Os conjuntos são gravados prontos, com o blob montado em memória: a
construção do conjunto já é coberta por `test_dataset_build`."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import undefer

from ottima_core.models import LabVariable, MlJob, Project, SoftSensorDataset, SoftSensorModel
from ottima_core.softsensor import DATASET_STEPS, DatasetError, load_model, pack_dataset, predict
from ottima_ml_worker import runner
from ottima_ml_worker.handlers import HANDLERS, JobContext
from ottima_ml_worker.jobs import ClaimedJob
from ottima_ml_worker.runner import run_job
from ottima_ml_worker.training import TrainingError

END = datetime.now(UTC).replace(microsecond=0)
TAGS = [11, 12]
PLS = {"method": "pls", "hyperparams": {"n_components": 2}, "name": "modelo"}


@pytest.fixture(autouse=True)
def restaura_threads_de_blas(monkeypatch):
    """`run_job` escreve estas variáveis no os.environ do pai; o monkeypatch as restaura."""
    for name in runner.BLAS_THREADS_ENV:
        monkeypatch.setenv(name, "1")


def _blob(n: int = 30, d: int = 2, seed: int = 0, t0: float = 0.0) -> bytes:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, DATASET_STEPS, d)).astype(np.float32)
    y = 2.0 * x[:, -1, 0] - x[:, -1, 1] + 3.0 + rng.normal(size=n) * 0.1
    return pack_dataset(x, y, t0 + np.arange(n, dtype=float))


async def _add(factory, row) -> int:
    async with factory() as session:
        session.add(row)
        await session.commit()
        return row.id


async def _dataset(
    factory,
    project_id: int,
    lab_variable_id: int,
    name: str,
    *,
    tags: list[int] = TAGS,
    status: str = "ready",
    period_s: float = 1.0,
    blob: bytes | None = None,
    end_ts: datetime = END,
) -> int:
    return await _add(
        factory,
        SoftSensorDataset(
            project_id=project_id,
            name=name,
            lab_variable_id=lab_variable_id,
            input_tag_ids=tags,
            period_s=period_s,
            start_ts=end_ts - timedelta(hours=1),
            end_ts=end_ts,
            status=status,
            inputs_meta=[{"tag_id": t, "name": f"T{t}", "eu": "°C"} for t in tags],
            data=blob if status == "ready" else None,
            created_by="teste",
        ),
    )


async def _train(factory, make_job, params: dict) -> tuple[dict, list[dict]]:
    job_id = await make_job("train", status="running", params=params)
    reports: list[dict] = []
    ctx = JobContext(job_id=job_id, params=params, session_factory=factory, report=reports.append)
    return await HANDLERS["train"](ctx), reports


async def _models(factory) -> list[SoftSensorModel]:
    async with factory() as session:
        rows = await session.scalars(
            select(SoftSensorModel)
            .options(undefer(SoftSensorModel.weights))
            .order_by(SoftSensorModel.id)
        )
        return list(rows)


async def test_treino_pls_grava_modelo_com_metricas_e_tags_de_entrada(
    session_factory, make_job, project_id, lab_variable_id
):
    async with session_factory() as session:
        (await session.get(LabVariable, lab_variable_id)).eu = "cP"
        await session.commit()
    dataset_id = await _dataset(session_factory, project_id, lab_variable_id, "d1", blob=_blob())

    result, reports = await _train(session_factory, make_job, {**PLS, "dataset_ids": [dataset_id]})

    (model,) = await _models(session_factory)
    assert result["model_id"] == model.id
    assert (result["rows_used"], result["rows_test"]) == (30, 6)
    assert set(result["metrics"]) == {"r2", "rmse", "mae"}
    assert result["metrics"]["r2"] > 0.95  # y é linear nas entradas, com ruído pequeno
    assert (model.project_id, model.name, model.method) == (project_id, "modelo", "pls")
    assert (model.period_s, model.n_inputs, model.input_tag_ids) == (1.0, 2, TAGS)
    assert model.created_by == "teste"  # quem enfileirou o job
    assert model.meta["metrics"] == result["metrics"]
    assert model.meta["dataset_ids"] == [dataset_id]
    assert (model.meta["output_name"], model.meta["output_eu"]) == ("Viscosidade", "cP")
    assert [(i["name"], i["eu"]) for i in model.meta["inputs"]] == [("T11", "°C"), ("T12", "°C")]
    loaded = load_model(model.id, model.meta, model.weights)  # o artefato gravado é utilizável
    assert abs(predict(loaded, np.ones((model.meta["warmup_steps"], 2))) - 4.0) < 0.5
    assert [r["stage"] for r in reports] == ["loading", "training", "saving"]


async def test_dois_conjuntos_compativeis_sao_concatenados(
    session_factory, make_job, project_id, lab_variable_id
):
    a = await _dataset(session_factory, project_id, lab_variable_id, "a", blob=_blob(30, seed=1))
    b = await _dataset(
        session_factory, project_id, lab_variable_id, "b", blob=_blob(25, seed=2, t0=100.0)
    )

    result, _ = await _train(session_factory, make_job, {**PLS, "dataset_ids": [a, b]})

    assert result["rows_used"] == 55
    (model,) = await _models(session_factory)
    assert model.meta["dataset_ids"] == [a, b]


@pytest.mark.parametrize(
    "defeito",
    ["variavel", "entradas", "ordem_das_entradas", "periodo", "nao_ready", "outro_projeto"],
)
async def test_conjuntos_incompativeis_falham_com_o_motivo(
    session_factory, make_job, project_id, lab_variable_id, defeito
):
    boa = await _dataset(session_factory, project_id, lab_variable_id, "boa", blob=_blob())
    outra_variavel = await _add(session_factory, LabVariable(project_id=project_id, name="Dens"))
    outro_projeto = await _add(session_factory, Project(name="Outro", description=""))
    variavel_alheia = await _add(
        session_factory, LabVariable(project_id=outro_projeto, name="Viscosidade")
    )
    blob = _blob(seed=3)
    ruim_args = {
        "variavel": (project_id, outra_variavel, {"blob": blob}),
        "entradas": (project_id, lab_variable_id, {"tags": [11, 13], "blob": blob}),
        "ordem_das_entradas": (project_id, lab_variable_id, {"tags": [12, 11], "blob": blob}),
        "periodo": (project_id, lab_variable_id, {"period_s": 5.0, "blob": blob}),
        "nao_ready": (project_id, lab_variable_id, {"status": "building"}),
        "outro_projeto": (outro_projeto, variavel_alheia, {"blob": blob}),
    }[defeito]
    ruim = await _dataset(session_factory, ruim_args[0], ruim_args[1], "ruim", **ruim_args[2])
    esperado = {
        "variavel": "Conjuntos com variáveis de laboratório diferentes",
        "entradas": "Conjuntos com entradas diferentes",
        "ordem_das_entradas": "Conjuntos com entradas diferentes",
        "periodo": "Conjuntos com períodos diferentes",
        "nao_ready": "Conjunto 'ruim' ainda não está pronto",
        "outro_projeto": f"Conjunto {ruim} não existe neste projeto",
    }[defeito]

    with pytest.raises(DatasetError) as raised:
        await _train(session_factory, make_job, {**PLS, "dataset_ids": [boa, ruim]})

    assert str(raised.value) == esperado
    assert await _models(session_factory) == []


async def test_nenhum_conjunto_falha_com_mensagem(session_factory, make_job):
    with pytest.raises(DatasetError, match="ao menos um conjunto"):
        await _train(session_factory, make_job, {**PLS, "dataset_ids": []})


async def test_nome_de_modelo_repetido_falha_o_segundo_job(
    session_factory, make_job, project_id, lab_variable_id, migrated_database_url
):
    dataset_id = await _dataset(session_factory, project_id, lab_variable_id, "d1", blob=_blob())
    params = {**PLS, "dataset_ids": [dataset_id]}
    ids = [await make_job("train", status="running", params=params) for _ in range(2)]

    for job_id in ids:  # pelo runner de verdade: o filho `spawn` abre a própria conexão
        await run_job(
            session_factory,
            ClaimedJob(id=job_id, kind="train", params=params),
            database_url=migrated_database_url,
        )

    async with session_factory() as session:
        primeiro, segundo = [await session.get(MlJob, job_id) for job_id in ids]
    (model,) = await _models(session_factory)
    assert (primeiro.status, primeiro.result["model_id"]) == ("done", model.id)
    assert (segundo.status, segundo.error) == ("failed", "Já existe um modelo com o nome 'modelo'")


async def test_hiperparametro_invalido_falha_com_mensagem(
    session_factory, make_job, project_id, lab_variable_id
):
    dataset_id = await _dataset(session_factory, project_id, lab_variable_id, "d1", blob=_blob())

    with pytest.raises(ValueError) as raised:
        await _train(
            session_factory,
            make_job,
            {**PLS, "hyperparams": {"n_components": 0}, "dataset_ids": [dataset_id]},
        )

    assert str(raised.value) == "Hiperparâmetro 'n_components' do método pls: deve ser no mínimo 1"
    assert await _models(session_factory) == []


async def test_conjunto_com_numero_de_entradas_diferente_do_blob_falha_com_mensagem(
    session_factory, make_job, project_id, lab_variable_id
):
    """O blob tem 3 entradas, mas o conjunto descreve 2: erro de validação, não 'inesperado'."""
    dataset_id = await _dataset(session_factory, project_id, lab_variable_id, "d1", blob=_blob(d=3))

    with pytest.raises(
        TrainingError, match=r"O conjunto tem 3 entrada\(s\), mas foram informados 2"
    ):
        await _train(session_factory, make_job, {**PLS, "dataset_ids": [dataset_id]})


async def test_progresso_do_lstm_informa_a_epoca(
    session_factory, make_job, project_id, lab_variable_id
):
    dataset_id = await _dataset(session_factory, project_id, lab_variable_id, "d1", blob=_blob())
    lstm = {
        "units": 8,
        "layers": 1,
        "epochs": 3,
        "batch_size": 16,
        "sequence_length": 5,
        "lr": 0.05,
    }

    result, reports = await _train(
        session_factory,
        make_job,
        {"method": "lstm", "hyperparams": lstm, "name": "lstm", "dataset_ids": [dataset_id]},
    )

    epochs = [r for r in reports if "epoch" in r]
    assert all(r == {"stage": "training", "epoch": r["epoch"], "epochs": 3} for r in epochs)
    # o contador reinicia uma vez: ajuste nos 80% e, depois, reajuste sobre 100%
    assert [r["epoch"] for r in epochs] == [1, 2, 3, 1, 2, 3]
    assert reports[0] == {"stage": "loading"} and reports[-1] == {"stage": "saving"}
    assert (await _models(session_factory))[0].id == result["model_id"]
