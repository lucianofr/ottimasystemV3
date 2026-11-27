"""Treino e otimização do sensor virtual na API (RF-587, RF-588, RF-581; spec SENSOR_VIRTUAL §8):
`POST /api/softsensor/jobs` (kind `train`/`tune`), `DELETE /api/softsensor/models/{id}`, o filtro
`dataset_id` de `GET /jobs` e os campos novos de `GET /blocks` e `GET /models`.

O ml-worker não roda aqui: a API só enfileira. Conjuntos, modelos, flows e vínculos entram
direto no banco (a sessão de teste é a da API, então as asserções leem COLUNAS, não entidades).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ottima_core.bus import KIND_SOFT_SENSOR_JOB_QUEUED, KIND_SOFT_SENSOR_MODEL_DELETED
from ottima_core.models import (
    Flow,
    LabVariable,
    MlJob,
    SoftSensorBinding,
    SoftSensorDataset,
    SoftSensorModel,
)
from ottima_core.softsensor import synthetic

JOBS = "/api/softsensor/jobs"
MODELS = "/api/softsensor/models"
BLOCKS = "/api/softsensor/blocks"
TAGS = [101, 102]  # `input_tag_ids` é array sem FK: o enfileirador não consulta a tag


# -------------------------------------------------------------------------------- cenário


async def _projeto(client, admin_headers, nome: str, *, ativar: bool = True) -> int:
    r = await client.post("/api/projects", json={"name": nome}, headers=admin_headers)
    assert r.status_code == 201, r.text
    if ativar:
        a = await client.post(f"/api/projects/{r.json()['id']}/activate", headers=admin_headers)
        assert a.status_code == 200, a.text
    return r.json()["id"]


async def _variavel(db_session, project_id: int, nome: str = "pureza") -> int:
    return await db_session.scalar(
        insert(LabVariable).values(project_id=project_id, name=nome).returning(LabVariable.id)
    )


async def _conjunto(
    db_session, project_id: int, var_id: int, nome: str, *, status: str = "ready", **extra
) -> int:
    colunas = {"input_tag_ids": TAGS, "period_s": 60.0} | extra
    ds_id = await db_session.scalar(
        insert(SoftSensorDataset)
        .values(
            project_id=project_id,
            name=nome,
            lab_variable_id=var_id,
            start_ts=datetime(2026, 1, 1, tzinfo=UTC),
            status=status,
            created_by="teste",
            **colunas,
        )
        .returning(SoftSensorDataset.id)
    )
    await db_session.commit()
    return ds_id


async def _cenario(client, admin_headers, db_session, nome: str = "proj-treino") -> dict:
    """Projeto ativo com uma variável de laboratório e um conjunto `ready`."""
    pid = await _projeto(client, admin_headers, nome)
    var_id = await _variavel(db_session, pid)
    return {"pid": pid, "var_id": var_id, "ds": await _conjunto(db_session, pid, var_id, "ds-1")}


async def _modelo(db_session, project_id: int, nome: str, artefato: tuple | None = None) -> int:
    meta, blob = artefato or synthetic.pls([1.0, 2.0], 0.0, period_s=1.0)
    modelo = SoftSensorModel(
        project_id=project_id,
        name=nome,
        method=meta.method,
        period_s=meta.period_s,
        n_inputs=len(meta.inputs),
        input_tag_ids=[],
        meta=meta.model_dump(mode="json"),
        weights=blob,
        created_by="user:1",
    )
    db_session.add(modelo)
    await db_session.commit()
    return modelo.id


def _sv(node_id: str = "sv1") -> dict:
    return {
        "id": node_id,
        "type": "soft_sensor_pls",
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": 1, "n_inputs": 2, "output_eu": "%"},
    }


async def _flow(db_session, project_id: int, nome: str = "flow-sv", ts: float = 1.0) -> int:
    flow = Flow(
        project_id=project_id,
        name=nome,
        ts_seconds=ts,
        graph_json={"nodes": [_sv()], "edges": []},
    )
    db_session.add(flow)
    await db_session.commit()
    return flow.id


async def _vincular(db_session, flow_id: int, block_id: str = "sv1", **colunas) -> None:
    db_session.add(
        SoftSensorBinding(flow_id=flow_id, block_id=block_id, updated_by="runtime", **colunas)
    )
    await db_session.commit()


def _treino(cen: dict, **extra) -> dict:
    return {
        "kind": "train",
        "method": "pls",
        "dataset_ids": [cen["ds"]],
        "name": "m1",
    } | extra


def _otimizacao(cen: dict, **extra) -> dict:
    return {
        "kind": "tune",
        "method": "pls",
        "dataset_ids": [cen["ds"]],
        "name": "m1",
    } | extra


async def _jobs(db_session):
    return (
        await db_session.execute(
            select(MlJob.id, MlJob.kind, MlJob.status, MlJob.params, MlJob.created_by).order_by(
                MlJob.id
            )
        )
    ).all()


# ---------------------------------------------------------------------- enfileirar: sucesso


async def test_enfileirar_treino_cria_job_queued(client, admin_headers, db_session, eventos):
    cen = await _cenario(client, admin_headers, db_session)
    uid = (await client.get("/api/auth/me", headers=admin_headers)).json()["id"]
    await eventos()  # descarta o que o cenário publicou

    r = await client.post(JOBS, json=_treino(cen, name="  m1  "), headers=admin_headers)

    assert r.status_code == 202, r.text
    (job,) = await _jobs(db_session)
    assert r.json() == {"job_id": job.id}
    assert (job.kind, job.status, job.created_by) == ("train", "queued", f"user:{uid}")
    # nome aparado; sem `hyperparams` a chave não existe (o handler trata como default)
    assert job.params == {"method": "pls", "dataset_ids": [cen["ds"]], "name": "m1"}
    (ev,) = await eventos()
    assert ev["origin"] == f"user:{uid}"
    # `kind` do payload é o do EVENTO (publish_event o impõe): o do job vai em `job_kind`
    assert ev["payload"] == {
        "kind": KIND_SOFT_SENSOR_JOB_QUEUED,
        "job_id": job.id,
        "job_kind": "train",
        "method": "pls",
        "name": "m1",
    }


async def test_treino_guarda_os_hiperparametros_e_deduplica_conjuntos(
    client, admin_headers, db_session
):
    cen = await _cenario(client, admin_headers, db_session)
    segundo = await _conjunto(db_session, cen["pid"], cen["var_id"], "ds-2")
    corpo = _treino(
        cen,
        method="esn",
        dataset_ids=[segundo, cen["ds"], segundo],
        hyperparams={"units": 100, "warmup": 20},
    )

    r = await client.post(JOBS, json=corpo, headers=admin_headers)

    assert r.status_code == 202, r.text
    (job,) = await _jobs(db_session)
    assert job.params == {
        "method": "esn",
        "dataset_ids": [segundo, cen["ds"]],
        "name": "m1",
        "hyperparams": {"units": 100, "warmup": 20},
    }


async def test_enfileirar_otimizacao_cria_job_tune_com_defaults(
    client, admin_headers, db_session, eventos
):
    cen = await _cenario(client, admin_headers, db_session)
    await eventos()

    r = await client.post(JOBS, json=_otimizacao(cen), headers=admin_headers)

    assert r.status_code == 202, r.text
    (job,) = await _jobs(db_session)
    assert job.kind == "tune"
    assert job.params == {
        "method": "pls",
        "dataset_ids": [cen["ds"]],
        "name": "m1",
        "n_trials": 20,
        "min_r2": 0.0,
    }
    (ev,) = await eventos()
    assert ev["payload"]["job_kind"] == "tune"


@pytest.mark.parametrize(("n_trials", "min_r2"), [(10, 0), (500, 1), (37, 0.55)])
async def test_otimizacao_aceita_os_limites(client, admin_headers, db_session, n_trials, min_r2):
    cen = await _cenario(client, admin_headers, db_session)

    r = await client.post(
        JOBS, json=_otimizacao(cen, n_trials=n_trials, min_r2=min_r2), headers=admin_headers
    )

    assert r.status_code == 202, r.text
    (job,) = await _jobs(db_session)
    assert (job.params["n_trials"], job.params["min_r2"]) == (n_trials, min_r2)


# --------------------------------------------------------------------- enfileirar: recusas


@pytest.mark.parametrize(
    "extra", [{"n_trials": 9}, {"n_trials": 501}, {"min_r2": -0.1}, {"min_r2": 1.1}]
)
async def test_enfileirar_otimizacao_valida_n_trials_e_min_r2(
    client, admin_headers, db_session, extra
):
    cen = await _cenario(client, admin_headers, db_session)

    r = await client.post(JOBS, json=_otimizacao(cen, **extra), headers=admin_headers)

    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], str)  # o frontend só mostra `detail` string
    assert await _jobs(db_session) == []


@pytest.mark.parametrize(
    ("corpo", "trecho"),
    [
        ({"kind": "treino"}, None),  # discriminador desconhecido
        ({"method": "svm"}, "Método de sensor virtual desconhecido: 'svm'"),
        ({"kind": "tune", "method": "svm"}, "Método de sensor virtual desconhecido: 'svm'"),
        ({"name": "   "}, "Nome não pode ser vazio"),
    ],
)
async def test_corpo_invalido_e_422(client, admin_headers, db_session, corpo, trecho):
    cen = await _cenario(client, admin_headers, db_session)

    r = await client.post(JOBS, json=_treino(cen) | corpo, headers=admin_headers)

    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], str)  # o frontend só mostra `detail` string
    if trecho:
        assert r.json()["detail"] == trecho
    assert await _jobs(db_session) == []


@pytest.mark.parametrize(
    ("kind", "extra", "campo"),
    [
        ("train", {"method": "esn", "hyperparams": {"units": 1000}}, "units"),  # acima do teto
        ("train", {"method": "pls", "hyperparams": {"units": 10}}, "units"),  # não existe no pls
        ("train", {"method": "lstm", "hyperparams": {"batch_size": 7}}, "batch_size"),
    ],
)
async def test_hiperparametro_fora_do_limite_e_422(
    client, admin_headers, db_session, kind, extra, campo
):
    cen = await _cenario(client, admin_headers, db_session)

    r = await client.post(JOBS, json=_treino(cen, **extra), headers=admin_headers)

    assert r.status_code == 422, r.text
    assert f"Hiperparâmetro '{campo}'" in r.json()["detail"]
    assert await _jobs(db_session) == []


@pytest.mark.parametrize("vazio", [0, [], False, "", "x"])
async def test_hiperparametros_que_nao_sao_objeto_sao_422(client, admin_headers, db_session, vazio):
    """Falsy não pode virar "defaults": `parse_hyperparams` o aceitaria, a tipagem do corpo não."""
    cen = await _cenario(client, admin_headers, db_session)

    r = await client.post(JOBS, json=_treino(cen, hyperparams=vazio), headers=admin_headers)

    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], str)
    assert await _jobs(db_session) == []


async def _ids_do_caso(client, admin_headers, db_session, cen: dict, caso: str) -> list[int]:
    """Lista de `dataset_ids` que quebra uma regra de compatibilidade; só cria o que o caso usa."""
    pid, var_id, base = cen["pid"], cen["var_id"], cen["ds"]
    match caso:
        case "vazio":
            return []
        case "inexistente":
            return [base, 999999]
        case "outro_projeto":
            alheio = await _projeto(client, admin_headers, "alheio", ativar=False)
            alheio_var = await _variavel(db_session, alheio)
            return [base, await _conjunto(db_session, alheio, alheio_var, "alheio")]
        case "nao_pronto":
            return [base, await _conjunto(db_session, pid, var_id, "x", status="building")]
        case "variavel":
            outra = await _variavel(db_session, pid, "outra")
            return [base, await _conjunto(db_session, pid, outra, "x")]
        case "entradas":
            return [base, await _conjunto(db_session, pid, var_id, "x", input_tag_ids=[102, 101])]
        case "periodo":
            return [base, await _conjunto(db_session, pid, var_id, "x", period_s=300.0)]
    raise AssertionError(caso)


@pytest.mark.parametrize(
    ("caso", "trecho"),
    [
        ("vazio", "Informe ao menos um conjunto de treino"),
        ("inexistente", "Conjunto 999999 não existe neste projeto"),
        ("outro_projeto", "não existe neste projeto"),
        ("nao_pronto", "ainda não está pronto"),
        ("variavel", "variáveis de laboratório diferentes"),
        ("entradas", "entradas diferentes"),
        ("periodo", "períodos diferentes"),
    ],
)
async def test_conjuntos_incompativeis_sao_recusados_antes_da_fila(
    client, admin_headers, db_session, caso, trecho
):
    cen = await _cenario(client, admin_headers, db_session)
    ids = await _ids_do_caso(client, admin_headers, db_session, cen, caso)

    r = await client.post(JOBS, json=_treino(cen, dataset_ids=ids), headers=admin_headers)
    t = await client.post(JOBS, json=_otimizacao(cen, dataset_ids=ids), headers=admin_headers)

    assert (r.status_code, t.status_code) == (422, 422), (r.text, t.text)
    assert trecho in r.json()["detail"]
    assert t.json() == r.json()
    assert await _jobs(db_session) == []


async def test_nome_de_modelo_ja_usado_e_409(client, admin_headers, db_session):
    cen = await _cenario(client, admin_headers, db_session)
    await _modelo(db_session, cen["pid"], "m1")

    r = await client.post(JOBS, json=_treino(cen), headers=admin_headers)
    t = await client.post(JOBS, json=_otimizacao(cen), headers=admin_headers)

    assert (r.status_code, t.status_code) == (409, 409), (r.text, t.text)
    assert r.json()["detail"] == "Já existe um modelo com o nome 'm1'"
    assert await _jobs(db_session) == []


async def test_mesmo_nome_em_outro_projeto_nao_conflita(client, admin_headers, db_session):
    alheio = await _projeto(client, admin_headers, "alheio", ativar=False)
    await _modelo(db_session, alheio, "m1")
    cen = await _cenario(client, admin_headers, db_session)

    r = await client.post(JOBS, json=_treino(cen), headers=admin_headers)

    assert r.status_code == 202, r.text


async def test_sem_projeto_ativo_e_409(client, admin_headers):
    r = await client.post(
        JOBS,
        json={"kind": "train", "method": "pls", "dataset_ids": [1], "name": "m1"},
        headers=admin_headers,
    )

    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Nenhum projeto ativo"


async def test_operador_nao_enfileira(client, operator_headers, db_session):
    r = await client.post(
        JOBS,
        json={"kind": "train", "method": "pls", "dataset_ids": [1], "name": "m1"},
        headers=operator_headers,
    )

    assert r.status_code == 403, r.text
    assert await _jobs(db_session) == []


# ---------------------------------------------------------------------- GET /jobs?dataset_id


async def _inserir_job(db_session, project_id: int, kind: str, params: dict, status="done") -> int:
    return await db_session.scalar(
        insert(MlJob)
        .values(project_id=project_id, kind=kind, status=status, params=params, created_by="t")
        .returning(MlJob.id)
    )


async def test_jobs_filtra_pelo_conjunto_de_origem(
    client, admin_headers, operator_headers, db_session
):
    cen = await _cenario(client, admin_headers, db_session)
    pid = cen["pid"]
    build = await _inserir_job(db_session, pid, "dataset_build", {"dataset_id": 5})
    train = await _inserir_job(db_session, pid, "train", {"dataset_ids": [4, 5, 6]})
    tune = await _inserir_job(db_session, pid, "tune", {"dataset_ids": [5]}, status="running")
    # nenhum destes é o conjunto 5 (55 e 15 não podem casar por prefixo ou sufixo)
    await _inserir_job(db_session, pid, "dataset_build", {"dataset_id": 55})
    await _inserir_job(db_session, pid, "train", {"dataset_ids": [15, 6]})
    await _inserir_job(db_session, pid, "train", {"dataset_ids": [6]})

    r = await client.get(f"{JOBS}?dataset_id=5", headers=operator_headers)
    ativos = await client.get(f"{JOBS}?dataset_id=5&active=true", headers=operator_headers)
    historico = await client.get(f"{JOBS}?dataset_id=5&active=false", headers=operator_headers)

    assert r.status_code == 200, r.text
    assert [j["id"] for j in r.json()] == [tune, train, build]  # mais novos primeiro
    assert [j["id"] for j in ativos.json()] == [tune]
    assert [j["id"] for j in historico.json()] == [train, build]


async def test_filtro_de_conjunto_nao_se_perde_atras_dos_100_mais_novos(
    client, admin_headers, operator_headers, db_session
):
    cen = await _cenario(client, admin_headers, db_session)
    antigo = await _inserir_job(db_session, cen["pid"], "dataset_build", {"dataset_id": 7})
    for _ in range(101):
        await _inserir_job(db_session, cen["pid"], "train", {"dataset_ids": [8]})

    sem_filtro = await client.get(JOBS, headers=operator_headers)
    filtrado = await client.get(f"{JOBS}?dataset_id=7", headers=operator_headers)

    assert antigo not in [j["id"] for j in sem_filtro.json()]  # o teto de 100 segue valendo
    assert [j["id"] for j in filtrado.json()] == [antigo]


async def test_filtro_de_conjunto_valida_o_id(client, operator_headers):
    for invalido in ("0", "-1", "abc", str(2**63)):
        r = await client.get(f"{JOBS}?dataset_id={invalido}", headers=operator_headers)
        assert r.status_code == 422, (invalido, r.text)


# ------------------------------------------------------------------------ DELETE /models/{id}


async def test_apagar_modelo_livre(client, admin_headers, db_session, eventos):
    cen = await _cenario(client, admin_headers, db_session)
    modelo = await _modelo(db_session, cen["pid"], "livre")
    outro = await _modelo(db_session, cen["pid"], "fica")
    uid = (await client.get("/api/auth/me", headers=admin_headers)).json()["id"]
    await eventos()

    r = await client.delete(f"{MODELS}/{modelo}", headers=admin_headers)

    assert r.status_code == 204, r.text
    restantes = (await db_session.scalars(select(SoftSensorModel.id))).all()
    assert restantes == [outro]
    (ev,) = await eventos()
    assert ev["origin"] == f"user:{uid}"
    assert ev["payload"] == {
        "kind": KIND_SOFT_SENSOR_MODEL_DELETED,
        "project_id": cen["pid"],
        "model_id": modelo,
        "name": "livre",
    }


@pytest.mark.parametrize("coluna", ["active_model_id", "desired_model_id"])
async def test_apagar_modelo_em_uso_e_409(client, admin_headers, db_session, eventos, coluna):
    cen = await _cenario(client, admin_headers, db_session)
    modelo = await _modelo(db_session, cen["pid"], "em-uso")
    flow_id = await _flow(db_session, cen["pid"], "Flow do forno")
    await _vincular(db_session, flow_id, "sv1", **{coluna: modelo})
    await eventos()

    r = await client.delete(f"{MODELS}/{modelo}", headers=admin_headers)

    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Modelo em uso pelo bloco 'sv1' do flow 'Flow do forno'"
    assert await db_session.scalar(select(SoftSensorModel.id).where(SoftSensorModel.id == modelo))
    assert await eventos() == []  # nada foi apagado, nada a auditar


async def test_apagar_modelo_candidato_e_409(client, admin_headers, db_session):
    """O candidato ainda não é o modelo em uso: sem a checagem, o DELETE só falharia no COMMIT
    (FK adiada), como `IntegrityError` e 500."""
    cen = await _cenario(client, admin_headers, db_session)
    ativo = await _modelo(db_session, cen["pid"], "ativo")
    candidato = await _modelo(db_session, cen["pid"], "candidato")
    flow_id = await _flow(db_session, cen["pid"], "Flow B")
    await _vincular(db_session, flow_id, "sv9", active_model_id=ativo, candidate_model_id=candidato)

    r = await client.delete(f"{MODELS}/{candidato}", headers=admin_headers)

    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Modelo em uso pelo bloco 'sv9' do flow 'Flow B'"
    assert await db_session.scalar(
        select(SoftSensorModel.id).where(SoftSensorModel.id == candidato)
    )


async def test_apagar_modelo_vinculado_entre_a_checagem_e_o_commit_e_409(
    client, admin_headers, db_session, eventos, monkeypatch
):
    """Um vínculo criado depois da checagem derruba o COMMIT (FK adiada): 409, não 500."""
    cen = await _cenario(client, admin_headers, db_session)
    modelo = await _modelo(db_session, cen["pid"], "corrida")
    await eventos()

    async def commit_recusado(self):
        raise IntegrityError("DELETE", {}, Exception("fk adiada"))

    with monkeypatch.context() as m:  # só o DELETE vê o commit recusado
        m.setattr(AsyncSession, "commit", commit_recusado)
        r = await client.delete(f"{MODELS}/{modelo}", headers=admin_headers)

    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Modelo em uso por um bloco; tente de novo"
    assert await db_session.scalar(select(SoftSensorModel.id).where(SoftSensorModel.id == modelo))
    assert await eventos() == []  # nada foi apagado, nada a auditar


async def test_apagar_modelo_inexistente_ou_de_outro_projeto_e_404(
    client, admin_headers, db_session
):
    await _cenario(client, admin_headers, db_session)
    alheio = await _projeto(client, admin_headers, "alheio", ativar=False)
    do_outro = await _modelo(db_session, alheio, "alheio")

    for model_id in (999999, do_outro):
        r = await client.delete(f"{MODELS}/{model_id}", headers=admin_headers)
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "Modelo não encontrado"


async def test_apagar_modelo_valida_o_id_e_o_papel(client, admin_headers, operator_headers):
    assert (await client.delete(f"{MODELS}/{2**63}", headers=admin_headers)).status_code == 422
    assert (await client.delete(f"{MODELS}/1", headers=operator_headers)).status_code == 403


# ------------------------------------------------------------------- campos novos do GET


async def test_blocks_traz_nomes_das_entradas_do_modelo_em_uso(
    client, admin_headers, operator_headers, db_session
):
    cen = await _cenario(client, admin_headers, db_session)
    # ESN de 2 entradas: 5 passos de aquecimento a cada 2 s
    modelo = await _modelo(db_session, cen["pid"], "esn", synthetic.esn(2, warmup=5, period_s=2.0))
    flow_id = await _flow(db_session, cen["pid"], "Flow A", ts=0.5)
    await _vincular(db_session, flow_id, "sv1", desired_model_id=modelo, active_model_id=modelo)

    r = await client.get(BLOCKS, headers=operator_headers)

    assert r.status_code == 200, r.text
    (bloco,) = r.json()
    assert bloco["ts_seconds"] == 0.5
    assert bloco["active_input_names"] == ["x0", "x1"]
    assert bloco["warmup_s"] == 10.0


async def test_blocks_sem_modelo_em_uso_nao_tem_nomes_nem_aquecimento(
    client, admin_headers, operator_headers, db_session
):
    cen = await _cenario(client, admin_headers, db_session)
    candidato = await _modelo(db_session, cen["pid"], "so-candidato")
    flow_id = await _flow(db_session, cen["pid"], ts=1.0)
    sem_vinculo = await client.get(BLOCKS, headers=operator_headers)
    await _vincular(db_session, flow_id, "sv1", candidate_model_id=candidato)
    so_candidato = await client.get(BLOCKS, headers=operator_headers)

    for r in (sem_vinculo, so_candidato):
        (bloco,) = r.json()
        assert bloco["ts_seconds"] == 1.0
        assert bloco["active_input_names"] is None
        assert bloco["warmup_s"] is None


async def test_models_traz_estado_de_uso(client, admin_headers, operator_headers, db_session):
    cen = await _cenario(client, admin_headers, db_session)
    pid = cen["pid"]
    ativo = await _modelo(db_session, pid, "ativo", synthetic.esn(2, warmup=5, period_s=2.0))
    candidato = await _modelo(db_session, pid, "candidato")
    pendente = await _modelo(db_session, pid, "pendente")
    await _modelo(db_session, pid, "livre")
    flow_id = await _flow(db_session, pid, "Flow A")
    outro_flow = await _flow(db_session, pid, "Flow B")
    # sv1: em uso + aquecendo; sv2: pedido que o runtime ainda não atendeu (sem candidato);
    # sv3: desejado == ativo (não é pendência); outro flow: o mesmo modelo em uso
    await _vincular(
        db_session,
        flow_id,
        "sv1",
        desired_model_id=candidato,
        active_model_id=ativo,
        candidate_model_id=candidato,
    )
    await _vincular(db_session, flow_id, "sv2", desired_model_id=pendente, active_model_id=ativo)
    await _vincular(db_session, flow_id, "sv3", desired_model_id=ativo, active_model_id=ativo)
    await _vincular(db_session, outro_flow, "sv1", active_model_id=ativo)

    r = await client.get(MODELS, headers=operator_headers)

    assert r.status_code == 200, r.text
    por_nome = {m["name"]: m for m in r.json()}

    def uso(fid, nome, bloco, estado):
        return {"flow_id": fid, "flow_name": nome, "block_id": bloco, "state": estado}

    assert por_nome["ativo"]["in_use"] == [
        uso(flow_id, "Flow A", "sv1", "active"),
        uso(flow_id, "Flow A", "sv2", "active"),
        uso(flow_id, "Flow A", "sv3", "active"),
        uso(outro_flow, "Flow B", "sv1", "active"),
    ]
    assert por_nome["candidato"]["in_use"] == [uso(flow_id, "Flow A", "sv1", "candidate")]
    assert por_nome["pendente"]["in_use"] == [uso(flow_id, "Flow A", "sv2", "pending")]
    assert por_nome["livre"]["in_use"] == []
    assert por_nome["ativo"]["warmup_s"] == 10.0
    assert por_nome["ativo"]["hyperparams"] == {
        "units": 20.0,
        "spectral_radius": 0.9,
        "leak_rate": 0.3,
        "warmup": 5.0,
    }
    assert por_nome["livre"]["warmup_s"] == 1.0  # PLS: 1 passo de 1 s
    assert por_nome["livre"]["hyperparams"] == {}


async def test_models_so_conta_o_uso_do_projeto_ativo(
    client, admin_headers, operator_headers, db_session
):
    cen = await _cenario(client, admin_headers, db_session)
    modelo = await _modelo(db_session, cen["pid"], "m1")
    outro = await _projeto(client, admin_headers, "outro", ativar=False)
    flow_alheio = await _flow(db_session, outro, "Flow alheio")
    await _vincular(db_session, flow_alheio, "sv1", active_model_id=modelo)

    r = await client.get(MODELS, headers=operator_headers)

    (item,) = r.json()
    assert item["in_use"] == []
