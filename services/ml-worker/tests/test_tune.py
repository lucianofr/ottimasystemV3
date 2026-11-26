"""Otimização de hiperparâmetros (RF-588, SPEC_SENSOR_VIRTUAL §8.2): estudo Optuna com validação
cruzada em ordem de tempo e handler `tune`. As tentativas de PLS/ESN são minúsculas: o que se
prova aqui é a mecânica do estudo, não a qualidade do modelo."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import undefer

from ottima_core.models import MlJob, SoftSensorDataset, SoftSensorModel
from ottima_core.softsensor import (
    DATASET_STEPS,
    SEARCH_SPACE,
    EsnHyperparams,
    LstmHyperparams,
    PlsHyperparams,
    pack_dataset,
)
from ottima_ml_worker import runner
from ottima_ml_worker.handlers import HANDLERS, JobContext
from ottima_ml_worker.jobs import ClaimedJob
from ottima_ml_worker.runner import run_job
from ottima_ml_worker.training import TrainData, TrainingError
from ottima_ml_worker.training import tune as tune_module
from ottima_ml_worker.training.lstm import Net, export_weights

INVALID = -1e9
SEM_TENTATIVA_VALIDA = "Nenhuma tentativa produziu um modelo válido"


@pytest.fixture(autouse=True)
def restaura_threads_de_blas(monkeypatch):
    """`run_job` escreve estas variáveis no os.environ do pai; o monkeypatch as restaura."""
    for name in runner.BLAS_THREADS_ENV:
        monkeypatch.setenv(name, "1")


def _data(n: int = 60, d: int = 2, seed: int = 0, noise: float = 0.1) -> TrainData:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, DATASET_STEPS, d)).astype(np.float32)
    y = 2.0 * x[:, -1, 0] - x[:, -1, 1] + 3.0 + rng.normal(size=n) * noise
    return TrainData(x=x, y=y, ts=np.arange(n, dtype=float))


def _run(data: TrainData, *, n_trials: int = 10, min_r2: float = 0.0, base=None, method="pls"):
    trials: list[dict] = []
    best = tune_module.tune(
        method,
        data,
        n_trials=n_trials,
        min_r2=min_r2,
        base=base or PlsHyperparams(),
        on_trial=trials.append,
    )
    return best, trials


def test_pls_encontra_n_components_melhor_que_o_default():
    """Seis colunas geradas por três fatores latentes, com y soma dos fatores: com 1 ou 2
    componentes o R² fica abaixo do de 3 ou mais."""
    rng = np.random.default_rng(0)
    z = rng.normal(size=(80, 3))
    x = rng.normal(size=(80, DATASET_STEPS, 6)).astype(np.float32)
    x[:, -1, :] = z @ rng.normal(size=(3, 6)) + rng.normal(size=(80, 6)) * 0.01
    data = TrainData(x=x, y=z.sum(axis=1), ts=np.arange(80, dtype=float))

    best, _ = _run(data, n_trials=20)

    assert isinstance(best, PlsHyperparams)
    assert best.n_components >= 3


def test_validacao_e_em_ordem_de_tempo(monkeypatch):
    """O índice da linha viaja na primeira entrada: o treino de cada dobra vem inteiro antes da
    validação, e nada além dos 80% iniciais (48 de 60 linhas) é usado."""
    data = _data(60)
    data.x[:, :, 0] = np.arange(60, dtype=np.float32)[:, None]
    folds: list[dict] = []
    real_fit, real_predict = tune_module.fit, tune_module.predict

    def spy_fit(method, x_k, y, hp, **kw):
        folds.append({"train": x_k[:, -1, 0].copy(), "val": []})
        return real_fit(method, x_k, y, hp, **kw)

    def spy_predict(model, window):
        folds[-1]["val"].append(window[-1, 0])
        return real_predict(model, window)

    monkeypatch.setattr(tune_module, "fit", spy_fit)
    monkeypatch.setattr(tune_module, "predict", spy_predict)

    _run(data, n_trials=3)

    assert len(folds) == 3 * 3  # três dobras por tentativa
    for fold in folds:
        assert fold["val"]
        assert max(fold["train"]) < min(fold["val"])
        assert max(fold["val"]) < 48


def test_r2_minimo_para_o_estudo_cedo():
    _, trials = _run(_data(60, noise=0.0), n_trials=50, min_r2=0.9)

    assert len(trials) < 50


def test_r2_minimo_zero_roda_todas_as_tentativas():
    _, trials = _run(_data(60, noise=0.0), n_trials=10, min_r2=0.0)

    assert len(trials) == 10


def test_tentativa_que_diverge_nao_derruba_o_estudo(monkeypatch):
    real_fit = tune_module.fit

    def flaky(method, x_k, y, hp, **kw):
        if hp.n_components % 2 == 0:  # metade das tentativas (n_components 2) diverge
            raise RuntimeError("divergiu")
        return real_fit(method, x_k, y, hp, **kw)

    monkeypatch.setattr(tune_module, "fit", flaky)

    best, trials = _run(_data(60, d=3), n_trials=10)

    scores = [t["r2"] for t in trials]
    assert INVALID in scores and max(scores) > INVALID
    assert len(trials) == 10  # a tentativa que falha conta e o estudo segue
    assert best.n_components in (1, 3)


def test_conjunto_minimo_de_20_linhas_ainda_produz_tentativas_validas():
    """20 linhas deixam 16 no treino e dobras de validação de 4: nenhuma tentativa é reprovada."""
    _, trials = _run(_data(20), n_trials=10)

    assert all(t["r2"] > INVALID for t in trials)


def test_estudo_sem_tentativa_valida_falha_e_nao_devolve_parametros(monkeypatch):
    def always_fails(*_args, **_kw):
        raise RuntimeError("divergiu")

    monkeypatch.setattr(tune_module, "fit", always_fails)

    with pytest.raises(TrainingError, match=SEM_TENTATIVA_VALIDA):
        _run(_data(60), n_trials=10)


def test_on_trial_recebe_numero_r2_estado_e_parametros():
    _, trials = _run(_data(60), n_trials=10)

    assert [t["number"] for t in trials] == list(range(10))
    assert all(isinstance(t["r2"], float) and t["state"] == "COMPLETE" for t in trials)
    assert all(set(t["params"]) == {"n_components"} for t in trials)
    assert all(1 <= t["params"]["n_components"] <= 2 for t in trials)  # teto: as 2 entradas


def test_parametros_fora_do_espaco_de_busca_vem_da_base(monkeypatch):
    """Faixas minúsculas só para o teste ser rápido; `seed` não está no espaço de busca."""
    monkeypatch.setitem(SEARCH_SPACE["esn"], "units", {"kind": "int", "low": 10, "high": 20})
    monkeypatch.setitem(SEARCH_SPACE["esn"], "warmup", {"kind": "int", "low": 5, "high": 8})

    best, _ = _run(_data(30), n_trials=3, base=EsnHyperparams(seed=7), method="esn")

    assert isinstance(best, EsnHyperparams)
    assert best.seed == 7
    assert 10 <= best.units <= 20 and 5 <= best.warmup <= 8


def test_mesma_semente_repete_o_resultado():
    data = _data(60, d=4, noise=1.0)

    first, _ = _run(data, n_trials=10)
    second, _ = _run(data, n_trials=10)

    assert first == second


def _lstm_space(monkeypatch) -> None:
    """LSTM minúsculo, com `lr` espalhado em três décadas para as perdas se separarem."""
    monkeypatch.setitem(
        SEARCH_SPACE,
        "lstm",
        {
            "units": {"kind": "int", "low": 8, "high": 16},
            "layers": {"kind": "int", "low": 1, "high": 2},
            "epochs": {"kind": "int", "low": 30, "high": 40},
            "batch_size": {"kind": "choice", "choices": [8, 16]},
            "sequence_length": {"kind": "int", "low": 3, "high": 5},
            "lr": {"kind": "log", "low": 1e-4, "high": 1e-1},
        },
    )


def test_poda_nao_e_engolida_pela_tolerancia_a_falha_do_ajuste(monkeypatch):
    """`fit` falso: reporta 12 épocas com perda crescente em `lr` e devolve pesos LSTM válidos
    (rede sem treino). Poda tem de sair como PRUNED, não como tentativa de -1e9."""
    _lstm_space(monkeypatch)

    def fake_fit(method, x_k, y, hp, *, epoch_cb=None):
        for epoch in range(1, 13):
            if epoch_cb is not None:
                epoch_cb(epoch, hp.lr * 1000.0)
        d = x_k.shape[-1]
        return export_weights(Net(d, hp.units, hp.layers), np.zeros(d), np.ones(d), 0.0, 1.0)

    monkeypatch.setattr(tune_module, "fit", fake_fit)

    _, trials = _run(_data(40), n_trials=10, base=LstmHyperparams(), method="lstm")

    assert {"PRUNED", "COMPLETE"} <= {t["state"] for t in trials}
    assert all(t["r2"] is None for t in trials if t["state"] == "PRUNED")
    assert all(t["r2"] is not None for t in trials if t["state"] == "COMPLETE")


@pytest.mark.slow
def test_lstm_poda_tentativas_ruins(monkeypatch):
    _lstm_space(monkeypatch)

    _, trials = _run(_data(40), n_trials=10, base=LstmHyperparams(), method="lstm")

    assert "PRUNED" in {t["state"] for t in trials}


# --- handler `tune` -----------------------------------------------------------------------------

END = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
async def dataset_id(session_factory, project_id, lab_variable_id, make_tag) -> int:
    """Conjunto `ready` de 2 entradas, y linear nelas com ruído pequeno (30 análises)."""
    tags = [await make_tag(f"T{i}", eu="°C") for i in (1, 2)]
    data = _data(30)
    row = SoftSensorDataset(
        project_id=project_id,
        name="d1",
        lab_variable_id=lab_variable_id,
        input_tag_ids=tags,
        period_s=1.0,
        start_ts=END - timedelta(hours=1),
        end_ts=END,
        status="ready",
        inputs_meta=[{"tag_id": t, "name": f"F{t}", "eu": "°C"} for t in tags],
        data=pack_dataset(data.x, data.y, data.ts),
        created_by="teste",
    )
    async with session_factory() as session:
        session.add(row)
        await session.commit()
        return row.id


def _params(dataset_id: int, **extra) -> dict:
    return {
        "method": "pls",
        "dataset_ids": [dataset_id],
        "n_trials": 10,
        "min_r2": 0.0,
        "name": "otimizado",
    } | extra


async def _tune(factory, make_job, params: dict) -> tuple[dict, list[dict]]:
    job_id = await make_job("tune", status="running", params=params)
    reports: list[dict] = []
    ctx = JobContext(job_id=job_id, params=params, session_factory=factory, report=reports.append)
    return await HANDLERS["tune"](ctx), reports


async def test_job_tune_grava_o_modelo_final(session_factory, make_job, dataset_id):
    result, reports = await _tune(session_factory, make_job, _params(dataset_id))

    async with session_factory() as session:
        (model,) = await session.scalars(
            select(SoftSensorModel).options(undefer(SoftSensorModel.weights))
        )
    assert result["model_id"] == model.id
    assert (model.name, model.method, model.created_by) == ("otimizado", "pls", "teste")
    assert set(result["metrics"]) == {"r2", "rmse", "mae"}
    assert (result["rows_used"], result["rows_test"]) == (30, 6)
    assert result["trials_run"] == 10
    assert result["best_cv_r2"] > 0.9  # y é linear nas entradas
    assert result["best_params"]["n_components"] == model.meta["hyperparams"]["n_components"]
    assert model.meta["metrics"] == result["metrics"]

    stages = [r.get("stage") for r in reports]
    assert stages[0] == "loading" and stages[-1] == "saving"
    tuning = [r for r in reports if "stage" not in r]  # progresso do estudo
    assert [r["trial"] for r in tuning] == list(range(0, 11))  # 0 inicial + 10 tentativas
    assert tuning[-1]["n_trials"] == 10 and len(tuning[-1]["trials"]) == 10
    assert tuning[-1]["best_r2"] == result["best_cv_r2"]
    assert set(tuning[-1]["trials"][0]) == {"number", "r2", "state", "params"}
    # a tabela de tentativas sobrevive às fases de treino e gravação
    assert reports[-1]["trial"] == 10 and len(reports[-1]["trials"]) == 10


@pytest.mark.parametrize(
    ("extra", "mensagem"),
    [
        ({"n_trials": 9}, "O número de tentativas deve ser um inteiro entre 10 e 500"),
        ({"n_trials": 501}, "O número de tentativas deve ser um inteiro entre 10 e 500"),
        ({"n_trials": 10.5}, "O número de tentativas deve ser um inteiro entre 10 e 500"),
        ({"min_r2": -0.1}, "O R² mínimo deve estar entre 0 e 1"),
        ({"min_r2": 1.1}, "O R² mínimo deve estar entre 0 e 1"),
    ],
)
async def test_job_tune_recusa_tentativas_e_r2_fora_da_faixa(
    session_factory, make_job, dataset_id, extra, mensagem
):
    with pytest.raises(TrainingError) as raised:
        await _tune(session_factory, make_job, _params(dataset_id, **extra))

    assert str(raised.value) == mensagem
    async with session_factory() as session:
        assert (await session.scalars(select(SoftSensorModel))).first() is None


async def test_job_tune_sem_tentativa_valida_nao_grava_modelo(
    session_factory, make_job, dataset_id, monkeypatch
):
    def always_fails(*_args, **_kw):
        raise RuntimeError("divergiu")

    monkeypatch.setattr(tune_module, "fit", always_fails)
    params = _params(dataset_id)
    reports: list[dict] = []
    ctx = JobContext(
        job_id=await make_job("tune", status="running", params=params),
        params=params,
        session_factory=session_factory,
        report=reports.append,
    )

    with pytest.raises(TrainingError, match=SEM_TENTATIVA_VALIDA):
        await HANDLERS["tune"](ctx)

    async with session_factory() as session:
        assert (await session.scalars(select(SoftSensorModel))).first() is None
    # tentativas inválidas aparecem na tabela, mas não valem como "melhor R²"
    assert reports[-1]["best_r2"] is None
    assert [t["r2"] for t in reports[-1]["trials"]] == [INVALID] * 10


async def test_job_tune_pelo_runner_deixa_progresso_e_resultado_serializaveis(
    session_factory, make_job, dataset_id, migrated_database_url
):
    """Pelo filho `spawn`: o progresso e o resultado atravessam o Pipe e viram JSON no banco."""
    params = _params(dataset_id)
    job_id = await make_job("tune", status="running", params=params)

    await run_job(
        session_factory,
        ClaimedJob(id=job_id, kind="tune", params=params),
        database_url=migrated_database_url,
    )

    async with session_factory() as session:
        job = await session.get(MlJob, job_id)
    assert (job.status, job.error) == ("done", None)
    assert job.result["trials_run"] == 10 and job.result["best_params"]["n_components"] >= 1
    assert job.progress["stage"] == "saving" and job.progress["trial"] == 10
    assert len(job.progress["trials"]) == 10
