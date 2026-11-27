"""Otimização de hiperparâmetros com Optuna (RF-588, SPEC_SENSOR_VIRTUAL §8.2): cada tentativa é
validada em dobras em ordem de tempo sobre as análises anteriores ao corte do teste final (o mesmo
do `train`), e o R² sai do `predict` compartilhado
aplicado ao artefato exportado, nunca do `predict` da biblioteca de treino."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

import numpy as np
import optuna
from pydantic import BaseModel
from sklearn.model_selection import TimeSeriesSplit

from ottima_core.softsensor import (
    SEARCH_SPACE,
    InputMeta,
    LoadedModel,
    ModelMeta,
    load_model,
    pack_weights,
    predict,
    window_of,
)

from .data import TrainData, TrainingError, metrics, split_rows
from .train import fit

MIN_TRIALS, MAX_TRIALS = 10, 500
INVALID = -1e9  # valor finito de uma tentativa inutilizável: ela conta e o estudo segue
FOLDS = 3
MIN_VALIDATION_ROWS = (
    2  # com uma só o R² não existe; mais que isso reprovaria conjuntos de 20 linhas
)
NO_VALID_TRIAL = "Nenhuma tentativa produziu um modelo válido; reveja o conjunto ou reduza a janela"

logger = logging.getLogger(__name__)


def _suggest(trial: optuna.Trial, name: str, spec: dict):
    match spec["kind"]:
        case "int":
            return trial.suggest_int(name, spec["low"], spec["high"])
        case "float":
            return trial.suggest_float(name, spec["low"], spec["high"])
        case "log":
            return trial.suggest_float(name, spec["low"], spec["high"], log=True)
        case _:  # "choice"
            return trial.suggest_categorical(name, spec["choices"])


def _space(method: str, data: TrainData) -> dict[str, dict]:
    space = SEARCH_SPACE[method]
    if method == "pls":  # o ajuste não passa de `min(entradas, linhas - 1)` componentes
        n_fit = split_rows(data, 1)[2]
        spec = space["n_components"]
        cap = max(1, min(data.x.shape[2], n_fit - 1, spec["high"]))
        space = {**space, "n_components": {**spec, "high": cap}}
    return space


def _with(base: BaseModel, params: dict) -> BaseModel:
    """`base` com os campos do estudo por cima; o que não está no espaço de busca (a `seed` do
    ESN) fica como veio."""
    return type(base).model_validate({**base.model_dump(), **params})


def _candidate(method: str, hp: BaseModel, weights: dict, d: int, k: int) -> LoadedModel:
    """Artefato de trabalho: só os pesos e a janela importam ao `predict`."""
    meta = ModelMeta(
        schema_version=1,
        method=method,
        period_s=1.0,
        inputs=[InputMeta(name=f"x{j}", min=0.0, max=0.0) for j in range(d)],
        output_name="y",
        hyperparams=hp.model_dump(),
        warmup_steps=k,
        trained_at=datetime.now(UTC),
    )
    return load_model(0, meta.model_dump(mode="json"), pack_weights(weights))


def tune(
    method: str,
    data: TrainData,
    *,
    n_trials: int,
    min_r2: float,
    base: BaseModel,
    on_trial: Callable[[dict], None] | None = None,
) -> BaseModel:
    """Melhores hiperparâmetros de `method` como instância do schema do método. `on_trial` recebe
    `{"number", "r2", "state", "params"}` ao fim de cada tentativa (`r2` é `None` se podada).

    Levanta `TrainingError` se nenhuma tentativa produziu um modelo válido ou, no PLS (janela fixa
    em 1 passo), se `split_rows` recusa o conjunto: nenhuma tentativa poderia ser válida."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    space = _space(method, data)
    d = data.x.shape[2]

    def objective(trial: optuna.Trial) -> float:
        hp = _with(base, {name: _suggest(trial, name, spec) for name, spec in space.items()})
        k = window_of(method, hp)
        try:
            x, y, n_fit = split_rows(data, k)
        except TrainingError:  # o `train` final recusaria esta janela
            return INVALID
        x, y = x[:n_fit], y[:n_fit]  # o teste do `train` fica fora da validação

        def prune(epoch: int, loss: float) -> None:
            trial.report(-loss, epoch)
            if trial.should_prune():
                raise optuna.TrialPruned

        scores = []
        for fold, (fit_idx, val_idx) in enumerate(TimeSeriesSplit(n_splits=FOLDS).split(x)):
            if len(val_idx) < MIN_VALIDATION_ROWS:
                return INVALID
            try:
                # Só a 1ª dobra poda: as épocas de dobras seguintes repetiriam os mesmos passos.
                weights = fit(
                    method,
                    x[fit_idx],
                    y[fit_idx],
                    hp,
                    epoch_cb=prune if fold == 0 else None,
                )
                model = _candidate(method, hp, weights, d, k)
                predicted = np.array([predict(model, window) for window in x[val_idx]])
            except optuna.TrialPruned:
                raise
            except Exception:
                logger.warning("tentativa %d: ajuste falhou", trial.number, exc_info=True)
                return INVALID
            if not np.isfinite(predicted).all():
                return INVALID
            scores.append(metrics(y[val_idx], predicted)["r2"])
        return float(np.mean(scores))

    def notify(_study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        if on_trial is not None:
            done = trial.state == optuna.trial.TrialState.COMPLETE
            on_trial(
                {
                    "number": trial.number,
                    "r2": trial.value if done else None,  # podada: `value` seria a perda
                    "state": trial.state.name,
                    "params": trial.params,
                }
            )

    def stop_at_min_r2(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        if (
            min_r2 > 0
            and trial.state == optuna.trial.TrialState.COMPLETE
            and study.best_value >= min_r2
        ):
            study.stop()

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=(
            optuna.pruners.MedianPruner(n_startup_trials=3, n_warmup_steps=10)
            if method == "lstm"
            else optuna.pruners.NopPruner()
        ),
    )
    study.optimize(objective, n_trials=n_trials, callbacks=[notify, stop_at_min_r2])

    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if not completed or study.best_value <= INVALID:
        raise TrainingError(NO_VALID_TRIAL)
    return _with(base, study.best_params)
