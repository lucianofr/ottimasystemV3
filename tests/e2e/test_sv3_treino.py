"""Camada L2 do treino e da otimização do sensor virtual da SV-3 (ADR-046; plano da SV-3,
Task 8): E2E-SV3-01..04.

Atravessa o que os testes de unidade não atravessam: análises de laboratório -> conjunto `ready`
-> fila `ml_jobs` -> ml-worker (processo filho, sklearn/optuna/torch) -> modelo gravado ->
ativação num flow em execução -> `flow.status`; e o sensor virtual como CV de um MPC.

Um projeto só para o módulo (`projeto_com_conexao`: ativo, conexão ao opcsim `up`, tags `sine`,
`static` e `mirror`) e UM conjunto de treino para os quatro cenários (`conjunto`), porque ele só
fica pronto depois de ~2 min de histórico gravado pelo recorder.

A "terceira variável" do conjunto é uma combinação linear das duas entradas,
`0,5·sine + 0,1·static + 2`, medida aqui como análise de laboratório: o valor de cada análise é
calculado do MESMO histórico (`/api/history`) que o congelamento do conjunto lê (último ponto em
ou antes do instante, mesma grade da RF-591). Uma tag calculada pelo calc-worker seria defasada
de até ~2 s da entrada, e uma defasagem de 1 s numa senoide de 60 s já derruba o R² do trecho de
teste (os 6 últimos pontos) perto de um pico; o cenário mediria a defasagem, não o treino.

`static` é constante no opcsim, e o PLS com mais componentes que o posto dos dados (o default é 3)
quebra no scikit-learn com `slice 0 has a NaN entry`: o treino pede `n_components = 1`.
"""

import bisect
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import redis

from opcsim import NODE_STATIC, NODE_WD_FROM_SYSTEM_2, NODE_WD_TO_SYSTEM_2
from ottima_core.bus import KIND_MPC_FAIL_ACTION_TRIGGERED, KIND_MPC_INPUT_INVALID
from ottima_core.signal import Quality

from .conftest import (
    RUN_ID,
    Ambiente,
    EventStream,
    armar_auto_com_retentativa,
    armar_remoto_direto,
    assinar_mpc_state,
    esperar_ate,
    evento_mpc,
)
from .f3_support import (
    LAB,
    aresta,
    assinantes_de_status,
    bloco,
    bloco_softsensor,
    config_mpc_minimo,
    criar_variavel_lab,
    csv_de_analises,
    de_varredura,
    deploy,
    escrever_status,
    esperar_historico,
    esperar_saida_boa,
    esperar_todos,
    fabrica_de_flows,
    importar_csv_lab,
    job_ml,
    montar_grafo,
    porta,
    porta_valida,
    valor,
)

pytestmark = pytest.mark.e2e

BLOCO = "sv"
MPC = "mpc_qe"
TS_FLOW = 1.0  # Ts dos flows (s); o período do conjunto e dos modelos é o mesmo

N_ANALISES = 30
PASSO_S = 3  # 30 análises x 3 s = 87 s: mais que um período inteiro (60 s) da senoide do opcsim,
# senão a faixa vista no treino não cobre a senoide e o bloco rebaixa `out` a UNCERTAIN
HISTORICO_S = 115.0  # 87 s das análises + ~23 s de processo antes da 1a: janelas de até ~50
# passos do LSTM do E2E-SV3-03 têm linhas suficientes (MIN_TRAIN_ROWS = 20) para o estudo rodar
MARGEM_S = 5  # a análise mais nova fica 5 s no passado: o recorder já gravou tudo até ela
W_SINE, W_STATIC, B_LAB = 0.5, 0.1, 2.0

PLS_HP = {"n_components": 1}


@dataclass(frozen=True, slots=True)
class Conjunto:
    id: int
    nome: str


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


@pytest.fixture
def assinar_status(redis_bus: redis.Redis) -> Iterator[Any]:
    yield from assinantes_de_status(redis_bus)


@pytest.fixture
def criar_flow(admin: httpx.Client, projeto_com_conexao: Ambiente) -> Iterator[Any]:
    # Par 2 do watchdog: o par 1 é do flow que o `projeto_com_conexao` mantém vivo.
    yield from fabrica_de_flows(
        admin,
        projeto_com_conexao,
        par_watchdog=(NODE_WD_TO_SYSTEM_2, NODE_WD_FROM_SYSTEM_2),
    )


def _ultimo_valor(serie: dict[str, Any], instante: datetime) -> float:
    """Último ponto GOOD em ou antes de `instante`: a regra da grade do conjunto (RF-591)."""
    instantes = [datetime.fromisoformat(t) for t in serie["t"]]
    i = bisect.bisect_right(instantes, instante) - 1
    assert i >= 0, f"tag {serie['tag_id']} sem amostra até {instante}"
    assert serie["q"][i] == 0 and serie["v"][i] is not None, (
        f"tag {serie['tag_id']} sem amostra GOOD em {instante}: q={serie['q'][i]}"
    )
    return float(serie["v"][i])


@pytest.fixture(scope="module")
def conjunto(admin: httpx.Client, projeto_com_conexao: Ambiente) -> Conjunto:
    """Espera o histórico, importa as 30 análises, congela o conjunto e confere o pareamento."""
    tags = [projeto_com_conexao.sine, projeto_com_conexao.static]
    esperar_historico(admin, tags, span_s=HISTORICO_S)
    agora = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=MARGEM_S)
    r = admin.get("/api/history", params={"tag_ids": ",".join(str(t) for t in tags)})
    assert r.status_code == 200, f"GET /api/history: HTTP {r.status_code} {r.text}"
    sine, static = r.json()["series"]
    assert (sine["tag_id"], static["tag_id"]) == tuple(tags)

    analises = [
        (
            instante,
            W_SINE * _ultimo_valor(sine, instante)
            + W_STATIC * _ultimo_valor(static, instante)
            + B_LAB,
        )
        for instante in (agora - timedelta(seconds=PASSO_S * k) for k in range(N_ANALISES))
    ]
    variavel = criar_variavel_lab(admin, f"lab-sv3-{RUN_ID}")
    r = importar_csv_lab(admin, csv_de_analises(variavel["name"], analises))
    assert r.status_code == 200, f"import do CSV: HTTP {r.status_code} {r.text}"
    assert r.json()["imported"] == N_ANALISES, r.json()

    nome = f"ds-sv3-{RUN_ID}"
    r = admin.post(
        f"{LAB}/datasets",
        json={
            "name": nome,
            "lab_variable_id": variavel["id"],
            "input_tag_ids": tags,
            "period_s": 1,
            "start_ts": (agora - timedelta(minutes=5)).isoformat(),
        },
    )
    assert r.status_code == 201, f"POST datasets: HTTP {r.status_code} {r.text}"
    dataset_id = r.json()["id"]
    r = admin.post(f"{LAB}/datasets/{dataset_id}/finalize")
    assert r.status_code == 202, f"finalize: HTTP {r.status_code} {r.text}"
    _esperar_job(admin, r.json()["job_id"], timeout=90.0)

    pronto = next(d for d in admin.get(f"{LAB}/datasets").json() if d["id"] == dataset_id)
    assert pronto["status"] == "ready", pronto
    assert pronto["stats"]["paired"] == N_ANALISES, pronto["stats"]
    return Conjunto(id=dataset_id, nome=nome)


# --------------------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------------------


def _enfileirar(admin: httpx.Client, corpo: dict[str, Any]) -> int:
    r = admin.post(f"{LAB}/jobs", json=corpo)
    assert r.status_code == 202, f"POST jobs: HTTP {r.status_code} {r.text}"
    return int(r.json()["job_id"])


def _esperar_job(admin: httpx.Client, job_id: int, *, timeout: float) -> dict[str, Any]:
    def terminou() -> dict[str, Any] | None:
        job = job_ml(admin, job_id)
        assert job["status"] not in ("failed", "cancelled"), f"job {job_id}: {job}"
        return job if job["status"] == "done" else None

    return esperar_ate(terminou, timeout=timeout, intervalo=1.0, descricao=f"job {job_id} done")


def _treinar_pls(admin: httpx.Client, conjunto: Conjunto, nome: str) -> dict[str, Any]:
    job_id = _enfileirar(
        admin,
        {
            "kind": "train",
            "method": "pls",
            "dataset_ids": [conjunto.id],
            "name": nome,
            "hyperparams": PLS_HP,
        },
    )
    return _esperar_job(admin, job_id, timeout=120.0)


def _nomes_dos_modelos(admin: httpx.Client) -> set[str]:
    r = admin.get(f"{LAB}/models")
    assert r.status_code == 200, f"GET models: HTTP {r.status_code} {r.text}"
    return {m["name"] for m in r.json()}


def _ativar(admin: httpx.Client, flow_id: int, model_id: int) -> None:
    r = admin.post(f"/api/operate/{flow_id}/{BLOCO}/model", json={"model_id": model_id})
    assert r.status_code == 202, f"POST /operate model: HTTP {r.status_code} {r.text}"


# --------------------------------------------------------------------------------------
# Cenários
# --------------------------------------------------------------------------------------


def test_e2e_sv3_01_do_conjunto_ao_bloco(
    admin: httpx.Client,
    projeto_com_conexao: Ambiente,
    conjunto: Conjunto,
    criar_flow: Any,
    assinar_status: Any,
) -> None:
    """RF-584/587: PLS treinado sobre o conjunto fica `done` com R² de teste > 0,9; ativado no
    bloco de um flow JÁ em execução (sem modelo, `out` não é GOOD), vira o `active_model_id` e
    `out` sai GOOD igual à combinação linear que gerou as análises."""
    job = _treinar_pls(admin, conjunto, f"pls01-{RUN_ID}")
    modelo_id = job["result"]["model_id"]
    assert job["result"]["metrics"]["r2"] > 0.9, job["result"]

    ambiente = projeto_com_conexao
    flow_id = criar_flow(
        "sv3-01",
        ts_seconds=TS_FLOW,
        grafo=montar_grafo(
            [
                bloco("r1", "opc_read", 1, tag_id=ambiente.sine),
                bloco("r2", "opc_read", 2, tag_id=ambiente.static),
                bloco(BLOCO, "soft_sensor_pls", 3, n_inputs=2),
            ],
            [aresta("r1", "out", BLOCO, "IN1"), aresta("r2", "out", BLOCO, "IN2")],
        ),
    )
    estado = assinar_status(flow_id)
    deploy(admin, flow_id)

    sem_modelo = estado.esperar(de_varredura, timeout=30.0, descricao="1a varredura do flow")
    assert not porta_valida(sem_modelo, BLOCO, "out"), porta(sem_modelo, BLOCO, "out")

    _ativar(admin, flow_id, modelo_id)

    status = esperar_saida_boa(estado, BLOCO, ate=20)
    x1, x2 = valor(status, "r1", "out"), valor(status, "r2", "out")
    assert x1 is not None and x2 is not None
    assert porta(status, BLOCO, "out")["v"] == pytest.approx(
        W_SINE * float(x1) + W_STATIC * float(x2) + B_LAB, abs=0.01
    )

    def em_uso() -> dict[str, Any] | None:
        vinculo = bloco_softsensor(admin, flow_id, BLOCO)
        return vinculo if vinculo["active_model_id"] == modelo_id else None

    vinculo = esperar_ate(
        em_uso, timeout=10.0, descricao="active_model_id igual ao modelo treinado"
    )
    assert vinculo["candidate_model_id"] is None


def test_e2e_sv3_02_otimizacao(admin: httpx.Client, conjunto: Conjunto) -> None:
    """RF-588: `tune` de PLS com 10 tentativas termina `done` com `trials_run == 10` e grava o
    modelo com o nome pedido."""
    nome = f"tune02-{RUN_ID}"
    job_id = _enfileirar(
        admin,
        {
            "kind": "tune",
            "method": "pls",
            "dataset_ids": [conjunto.id],
            "name": nome,
            "n_trials": 10,
        },
    )

    job = _esperar_job(admin, job_id, timeout=180.0)

    assert job["result"]["trials_run"] == 10, job["result"]
    assert job["result"]["best_cv_r2"] > 0.9, job["result"]
    assert nome in _nomes_dos_modelos(admin)


def test_e2e_sv3_03_cancelamento_da_otimizacao(admin: httpx.Client, conjunto: Conjunto) -> None:
    """RF-588: `tune` de LSTM com 500 tentativas, cancelado depois da 1a tentativa aparecer no
    progresso, fica `cancelled` em até 10 s e não grava nenhum modelo com o nome pedido."""
    nome = f"lstm03-{RUN_ID}"
    job_id = _enfileirar(
        admin,
        {
            "kind": "tune",
            "method": "lstm",
            "dataset_ids": [conjunto.id],
            "name": nome,
            "n_trials": 500,
        },
    )
    try:

        def primeira_tentativa() -> dict[str, Any] | None:
            job = job_ml(admin, job_id)
            assert job["status"] in ("queued", "running"), f"job {job_id}: {job}"
            return job if job["progress"].get("trial", 0) >= 1 else None

        # Generoso: o filho importa o torch e a 1a tentativa ajusta de verdade. O limite de 10 s
        # abaixo é só do cancelamento.
        esperar_ate(
            primeira_tentativa, timeout=180.0, intervalo=1.0, descricao="1a tentativa no progresso"
        )

        r = admin.post(f"{LAB}/jobs/{job_id}/cancel")
        assert r.status_code == 202, f"cancel: HTTP {r.status_code} {r.text}"

        esperar_ate(
            lambda: job_ml(admin, job_id)["status"] == "cancelled",
            timeout=10.0,
            intervalo=0.5,
            descricao=f"job {job_id} cancelled",
        )
    finally:
        admin.post(f"{LAB}/jobs/{job_id}/cancel")  # no-op com o job terminado

    assert nome not in _nomes_dos_modelos(admin)


def test_e2e_sv3_04_malha_com_mpc(
    admin: httpx.Client,
    projeto_com_conexao: Ambiente,
    conjunto: Conjunto,
    criar_flow: Any,
    assinar_status: Any,
    eventos: EventStream,
) -> None:
    """Spec §11 (adiado da SV-1): `opc_read` -> `soft_sensor_pls` -> CV de um MPC com
    `fail_action = manual`, em REMOTO e AUTO. `static` (entrada do sensor) em Bad faz `out`
    ficar BAD COM o último valor (nunca `None`), o MPC reportar a CV inválida e APLICAR a ação de
    falha (evento + `man_auto = man`). Se `out` fosse `None`, o portão frio devolveria saídas
    nulas e `fail_action` nunca correria."""
    modelo_id = _treinar_pls(admin, conjunto, f"pls04-{RUN_ID}")["result"]["model_id"]
    ambiente = projeto_com_conexao
    flow_id = criar_flow(
        "sv3-04",
        ts_seconds=TS_FLOW,
        grafo=montar_grafo(
            [
                bloco("r1", "opc_read", 1, tag_id=ambiente.sine),
                bloco("r2", "opc_read", 2, tag_id=ambiente.static),
                bloco("dv_leitura", "opc_read", 3, tag_id=ambiente.mirror),
                bloco(BLOCO, "soft_sensor_pls", 4, n_inputs=2),
                bloco(MPC, "mpc", 5, **config_mpc_minimo(fail_action="manual")),
            ],
            [
                aresta("r1", "out", BLOCO, "IN1"),
                aresta("r2", "out", BLOCO, "IN2"),
                aresta(BLOCO, "out", MPC, "cv_1"),
                aresta("dv_leitura", "out", MPC, "dv_1"),
            ],
        ),
    )
    _ativar(admin, flow_id, modelo_id)
    estado = assinar_status(flow_id)
    try:
        deploy(admin, flow_id)
        esperar_saida_boa(estado, BLOCO, ate=20)

        with assinar_mpc_state(admin, flow_id, MPC) as fluxo:
            armar_remoto_direto(admin, fluxo, flow_id, MPC)
            armar_auto_com_retentativa(admin, fluxo, flow_id, MPC)
            fluxo.esperar(
                lambda e: e["modes"]["man_auto"] == "auto" and e["status"]["input_valid"],
                timeout=30.0,
                descricao="MPC em AUTO com a estimativa como CV válida",
            )

            escrever_status(NODE_STATIC, valor=0.0, ruim=True)

            achados = esperar_todos(
                eventos,
                {
                    "invalida": evento_mpc(KIND_MPC_INPUT_INVALID, flow_id, MPC),
                    "acao": evento_mpc(KIND_MPC_FAIL_ACTION_TRIGGERED, flow_id, MPC),
                },
                timeout=60.0,
                descricao="mpc_input_invalid e mpc_fail_action_triggered",
            )
            acao = achados["acao"]["payload"]
            assert (acao["var_id"], acao["action"], acao["reason"]) == (
                "cv_1",
                "manual",
                "bad_quality",
            ), acao

            em_manual = fluxo.esperar(
                lambda e: e["modes"]["man_auto"] == "man",
                timeout=30.0,
                descricao="MPC em MAN pela fail action",
            )
            assert em_manual["status"]["input_valid"] is False, em_manual["status"]

        # O sensor segurou o último valor, só a qualidade caiu; e o MPC entrega a MV (não é o
        # portão frio, que anularia as saídas do bloco inteiro).
        ruim = estado.esperar(
            lambda s: de_varredura(s) and not porta_valida(s, BLOCO, "out"),
            timeout=30.0,
            descricao="varredura com `out` do sensor fora de GOOD",
        )
        saida = porta(ruim, BLOCO, "out")
        assert saida["v"] is not None and saida["quality"] == Quality.BAD, saida
        assert porta(ruim, MPC, "mv_1")["v"] is not None, porta(ruim, MPC, "mv_1")
    finally:
        escrever_status(NODE_STATIC, valor=42.0, ruim=False)  # o opcsim é da sessão inteira
