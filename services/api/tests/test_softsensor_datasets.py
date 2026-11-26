"""Conjuntos de treino e fila de jobs do sensor virtual (RF-586, spec SENSOR_VIRTUAL §7.3-7.5).

Rotas sob `/api/softsensor`. O ml-worker não roda aqui: os estados que ele produziria (`running`,
`done`, `failed`) são gravados direto no banco. A sessão de teste é a mesma da API, então as
asserções de banco leem COLUNAS (o `select` de entidade devolveria o objeto já em memória).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select, update

from ottima_core.bus import (
    KIND_SOFT_SENSOR_DATASET_CREATED,
    KIND_SOFT_SENSOR_DATASET_DELETED,
    KIND_SOFT_SENSOR_DATASET_FINALIZED,
)
from ottima_core.models import LabVariable, MlJob, SoftSensorDataset

DATASETS = "/api/softsensor/datasets"
JOBS = "/api/softsensor/jobs"
MSG_JA_FINALIZADO = "Conjunto já finalizado"
MSG_EM_MONTAGEM = "Conjunto em montagem; cancele o job antes"


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


async def _projeto(client, admin_headers, nome: str, *, ativar: bool = False) -> int:
    r = await client.post("/api/projects", json={"name": nome}, headers=admin_headers)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    if ativar:
        r = await client.post(f"/api/projects/{pid}/activate", headers=admin_headers)
        assert r.status_code == 200, r.text
    return pid


async def _tag(client, admin_headers, project_id: int, nome: str) -> int:
    r = await client.post(
        "/api/connections",
        json={"project_id": project_id, "name": f"c-{nome}", "endpoint": "opc.tcp://x:4840"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/tags",
        json={
            "connection_id": r.json()["id"],
            "name": nome,
            "node_id": f"ns=2;s={nome}",
            "direction": "r",
            "data_type": "float",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _cenario(client, admin_headers, db_session) -> dict:
    """Projeto ativo com variável de laboratório e duas tags; mais uma tag e uma variável de
    OUTRO projeto, para os casos de escopo."""
    outro = await _projeto(client, admin_headers, "outro")
    db_session.add(LabVariable(project_id=outro, name="alheia"))
    await db_session.commit()
    outra_var = await db_session.scalar(
        select(LabVariable.id).where(LabVariable.project_id == outro)
    )
    outra_tag = await _tag(client, admin_headers, outro, "TI-OUTRO")

    pid = await _projeto(client, admin_headers, "proj-ds", ativar=True)
    r = await client.post(
        "/api/softsensor/lab-variables", json={"name": "pureza"}, headers=admin_headers
    )
    assert r.status_code == 201, r.text
    return {
        "pid": pid,
        "var_id": r.json()["id"],
        "tags": [await _tag(client, admin_headers, pid, f"TI-{i}") for i in (1, 2)],
        "outro": outro,
        "outra_var": outra_var,
        "outra_tag": outra_tag,
    }


def _corpo(cen: dict, **extra) -> dict:
    return {
        "name": "conjunto-A",
        "lab_variable_id": cen["var_id"],
        "input_tag_ids": cen["tags"],
        "period_s": 60,
        "start_ts": _iso(-timedelta(hours=2)),
    } | extra


async def _criar(client, admin_headers, cen: dict, **extra) -> dict:
    r = await client.post(DATASETS, json=_corpo(cen, **extra), headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _finalizar(client, admin_headers, dataset_id: int):
    return await client.post(f"{DATASETS}/{dataset_id}/finalize", headers=admin_headers)


async def _conjunto(db_session, dataset_id: int):
    return (
        await db_session.execute(
            select(SoftSensorDataset.status, SoftSensorDataset.end_ts).where(
                SoftSensorDataset.id == dataset_id
            )
        )
    ).one()


async def _job(db_session, job_id: int):
    return (
        await db_session.execute(
            select(
                MlJob.kind,
                MlJob.status,
                MlJob.params,
                MlJob.cancel_requested,
                MlJob.finished_at,
                MlJob.created_by,
            ).where(MlJob.id == job_id)
        )
    ).one()


async def _inserir_job(db_session, project_id: int, status: str, kind: str = "train") -> int:
    return await db_session.scalar(
        insert(MlJob)
        .values(project_id=project_id, kind=kind, status=status, params={}, created_by="teste")
        .returning(MlJob.id)
    )


async def _forcar_status(db_session, dataset_id: int, status: str, **colunas) -> None:
    await db_session.execute(
        update(SoftSensorDataset)
        .where(SoftSensorDataset.id == dataset_id)
        .values(status=status, **colunas)
    )
    await db_session.commit()


# ------------------------------------------------------------------------------ criação


async def test_criar_conjunto_devolve_o_conjunto_e_audita(
    client, admin_headers, db_session, eventos
):
    cen = await _cenario(client, admin_headers, db_session)
    uid = (await client.get("/api/auth/me", headers=admin_headers)).json()["id"]
    await eventos()  # descarta o que o cenário publicou

    ds = await _criar(client, admin_headers, cen)

    assert ds | {"id": 0, "start_ts": None} == {
        "id": 0,
        "name": "conjunto-A",
        "lab_variable_id": cen["var_id"],
        "lab_variable_name": "pureza",
        "input_tag_ids": cen["tags"],
        "inputs_meta": [],
        "period_s": 60.0,
        "start_ts": None,
        "end_ts": None,
        "status": "collecting",
        "stats": {},
        "warnings": [],
    }
    (ev,) = await eventos()
    assert ev["origin"] == f"user:{uid}"
    assert ev["payload"] == {
        "kind": KIND_SOFT_SENSOR_DATASET_CREATED,
        "project_id": cen["pid"],
        "dataset_id": ds["id"],
        "name": "conjunto-A",
    }


@pytest.mark.parametrize(
    ("extra", "status", "trecho"),
    [
        (lambda c: {"input_tag_ids": []}, 422, "1 a 32"),
        (lambda c: {"input_tag_ids": list(range(1, 34))}, 422, "1 a 32"),
        (lambda c: {"input_tag_ids": [c["tags"][0], c["tags"][0]]}, 422, "repetid"),
        (
            lambda c: {"input_tag_ids": [999999]},
            422,
            "Tag(s) de entrada inexistente(s) ou de outro projeto: 999999",
        ),
        (
            lambda c: {"input_tag_ids": [c["tags"][0], c["outra_tag"]]},
            422,
            "outro projeto: {outra_tag}",
        ),
        (lambda c: {"period_s": 7}, 422, "Período inválido"),
        (lambda c: {"start_ts": "2025-03-01T10:00:00"}, 422, "fuso"),
        (lambda c: {"start_ts": _iso(timedelta(hours=1))}, 422, "futuro"),
        (lambda c: {"lab_variable_id": 999999}, 422, "Variável de laboratório"),
        (lambda c: {"lab_variable_id": c["outra_var"]}, 422, "Variável de laboratório"),
        (lambda c: {"name": "   "}, 422, "Nome"),
    ],
    ids=[
        "sem-tags",
        "tags-demais",
        "tags-repetidas",
        "tag-inexistente",
        "tag-de-outro-projeto",
        "periodo-fora-da-lista",
        "inicio-sem-fuso",
        "inicio-futuro",
        "variavel-inexistente",
        "variavel-de-outro-projeto",
        "nome-vazio",
    ],
)
async def test_criar_conjunto_valida_entradas_periodo_e_variavel(
    client, admin_headers, db_session, extra, status, trecho
):
    cen = await _cenario(client, admin_headers, db_session)

    r = await client.post(DATASETS, json=_corpo(cen, **extra(cen)), headers=admin_headers)

    assert r.status_code == status, r.text
    assert trecho.format(outra_tag=cen["outra_tag"]) in r.json()["detail"]
    assert (await client.get(DATASETS, headers=admin_headers)).json() == []


async def test_nome_repetido_e_409(client, admin_headers, db_session):
    cen = await _cenario(client, admin_headers, db_session)
    await _criar(client, admin_headers, cen)

    r = await client.post(DATASETS, json=_corpo(cen), headers=admin_headers)

    assert (r.status_code, r.json()["detail"]) == (409, "Já existe um conjunto com esse nome")


async def test_sem_projeto_ativo_lista_vazia_e_escrita_409(client, admin_headers, operator_headers):
    assert (await client.get(DATASETS, headers=operator_headers)).json() == []
    assert (await client.get(JOBS, headers=operator_headers)).json() == []
    corpo = {
        "name": "x",
        "lab_variable_id": 1,
        "input_tag_ids": [1],
        "period_s": 60,
        "start_ts": _iso(-timedelta(hours=1)),
    }
    r = await client.post(DATASETS, json=corpo, headers=admin_headers)
    assert (r.status_code, r.json()["detail"]) == (409, "Nenhum projeto ativo")


async def test_inicio_anterior_a_retencao_devolve_aviso(client, admin_headers, db_session):
    cen = await _cenario(client, admin_headers, db_session)  # retenção padrão: 30 dias

    ds = await _criar(client, admin_headers, cen, start_ts=_iso(-timedelta(days=31)))

    assert ds["warnings"] == [
        "O início é anterior à retenção do histórico (30 dias): "
        "parte do período não terá dado de processo"
    ]


# ------------------------------------------------------------------- finalizar e apagar


async def test_finalizar_enfileira_dataset_build_e_marca_building(
    client, admin_headers, db_session, eventos
):
    cen = await _cenario(client, admin_headers, db_session)
    uid = (await client.get("/api/auth/me", headers=admin_headers)).json()["id"]
    ds = await _criar(client, admin_headers, cen)
    await eventos()

    r = await _finalizar(client, admin_headers, ds["id"])

    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    status, end_ts = await _conjunto(db_session, ds["id"])
    assert status == "building"
    assert abs(datetime.now(UTC) - end_ts) < timedelta(minutes=1)
    kind, job_status, params, cancel, _, autor = await _job(db_session, job_id)
    assert (kind, job_status, params, cancel, autor) == (
        "dataset_build",
        "queued",
        {"dataset_id": ds["id"]},
        False,
        f"user:{uid}",
    )
    (ev,) = await eventos()
    assert ev["payload"] == {
        "kind": KIND_SOFT_SENSOR_DATASET_FINALIZED,
        "project_id": cen["pid"],
        "dataset_id": ds["id"],
        "name": "conjunto-A",
        "job_id": job_id,
    }


async def test_finalizar_duas_vezes_e_409(client, admin_headers, db_session):
    cen = await _cenario(client, admin_headers, db_session)
    ds = await _criar(client, admin_headers, cen)
    assert (await _finalizar(client, admin_headers, ds["id"])).status_code == 202

    r = await _finalizar(client, admin_headers, ds["id"])
    assert (r.status_code, r.json()["detail"]) == (409, MSG_JA_FINALIZADO)

    await _forcar_status(db_session, ds["id"], "ready")  # pronto também não finaliza de novo
    r = await _finalizar(client, admin_headers, ds["id"])
    assert (r.status_code, r.json()["detail"]) == (409, MSG_JA_FINALIZADO)


async def test_conjunto_failed_pode_ser_finalizado_de_novo_com_o_mesmo_end_ts(
    client, admin_headers, db_session
):
    cen = await _cenario(client, admin_headers, db_session)
    ds = await _criar(client, admin_headers, cen)
    primeiro = (await _finalizar(client, admin_headers, ds["id"])).json()["job_id"]
    _, end_ts = await _conjunto(db_session, ds["id"])
    await _forcar_status(db_session, ds["id"], "failed")

    r = await _finalizar(client, admin_headers, ds["id"])

    assert r.status_code == 202, r.text
    assert r.json()["job_id"] != primeiro
    assert await _conjunto(db_session, ds["id"]) == ("building", end_ts)
    assert (await _job(db_session, r.json()["job_id"]))[:3] == (
        "dataset_build",
        "queued",
        {"dataset_id": ds["id"]},
    )


async def test_lista_de_conjuntos_nunca_traz_data(
    client, admin_headers, operator_headers, db_session
):
    cen = await _cenario(client, admin_headers, db_session)
    ds = await _criar(client, admin_headers, cen)
    await _forcar_status(
        db_session,
        ds["id"],
        "ready",
        data=b"x" * 1024,
        stats={"n_samples": 3},
        inputs_meta=[{"tag_id": cen["tags"][0], "name": "TI-1", "eu": ""}],
    )

    r = await client.get(DATASETS, headers=operator_headers)

    assert r.status_code == 200, r.text
    (linha,) = r.json()
    assert set(linha) == {
        "id",
        "name",
        "lab_variable_id",
        "lab_variable_name",
        "input_tag_ids",
        "inputs_meta",
        "period_s",
        "start_ts",
        "end_ts",
        "status",
        "stats",
    }
    assert (linha["status"], linha["stats"]) == ("ready", {"n_samples": 3})


async def test_apagar_conjunto_em_montagem_e_409(client, admin_headers, db_session, eventos):
    cen = await _cenario(client, admin_headers, db_session)
    ds = await _criar(client, admin_headers, cen)
    await _finalizar(client, admin_headers, ds["id"])

    r = await client.delete(f"{DATASETS}/{ds['id']}", headers=admin_headers)

    assert (r.status_code, r.json()["detail"]) == (409, MSG_EM_MONTAGEM)
    assert (await _conjunto(db_session, ds["id"]))[0] == "building"

    await _forcar_status(db_session, ds["id"], "collecting")
    await eventos()
    assert (await client.delete(f"{DATASETS}/{ds['id']}", headers=admin_headers)).status_code == 204
    (ev,) = await eventos()
    assert ev["payload"] == {
        "kind": KIND_SOFT_SENSOR_DATASET_DELETED,
        "project_id": cen["pid"],
        "dataset_id": ds["id"],
        "name": "conjunto-A",
    }


async def test_conjunto_failed_pode_ser_apagado(client, admin_headers, db_session):
    cen = await _cenario(client, admin_headers, db_session)
    ds = await _criar(client, admin_headers, cen)
    await _finalizar(client, admin_headers, ds["id"])
    await _forcar_status(db_session, ds["id"], "failed")

    assert (await client.delete(f"{DATASETS}/{ds['id']}", headers=admin_headers)).status_code == 204

    assert (await client.get(DATASETS, headers=admin_headers)).json() == []


# ----------------------------------------------------------------------------------- jobs


async def test_cancelar_job_na_fila_vira_cancelled_na_hora(client, admin_headers, db_session):
    cen = await _cenario(client, admin_headers, db_session)
    job_id = await _inserir_job(db_session, cen["pid"], "queued")

    r = await client.post(f"{JOBS}/{job_id}/cancel", headers=admin_headers)

    assert r.status_code == 202, r.text
    _, status, _, cancel, finished_at, _ = await _job(db_session, job_id)
    assert (status, cancel) == ("cancelled", True)
    assert finished_at is not None


async def test_cancelar_dataset_build_na_fila_marca_o_conjunto_failed(
    client, admin_headers, db_session
):
    cen = await _cenario(client, admin_headers, db_session)
    ds = await _criar(client, admin_headers, cen)
    job_id = (await _finalizar(client, admin_headers, ds["id"])).json()["job_id"]

    r = await client.post(f"{JOBS}/{job_id}/cancel", headers=admin_headers)

    assert r.status_code == 202, r.text
    assert (await _job(db_session, job_id))[1] == "cancelled"
    assert (await _conjunto(db_session, ds["id"]))[0] == "failed"  # senão ficaria building
    # e o conjunto, agora failed, pode ser apagado
    assert (await client.delete(f"{DATASETS}/{ds['id']}", headers=admin_headers)).status_code == 204


async def test_cancelar_job_rodando_so_liga_a_flag(client, admin_headers, db_session):
    cen = await _cenario(client, admin_headers, db_session)
    ds = await _criar(client, admin_headers, cen)
    job_id = (await _finalizar(client, admin_headers, ds["id"])).json()["job_id"]
    await db_session.execute(update(MlJob).where(MlJob.id == job_id).values(status="running"))
    await db_session.commit()

    r = await client.post(f"{JOBS}/{job_id}/cancel", headers=admin_headers)

    assert r.status_code == 202, r.text
    _, status, _, cancel, finished_at, _ = await _job(db_session, job_id)
    assert (status, cancel, finished_at) == ("running", True, None)
    # quem fecha o job (e o conjunto) é o ml-worker, ao ver a flag
    assert (await _conjunto(db_session, ds["id"]))[0] == "building"


async def test_cancelar_job_terminado_nao_muda_o_estado(client, admin_headers, db_session):
    cen = await _cenario(client, admin_headers, db_session)
    ids = {
        s: await _inserir_job(db_session, cen["pid"], s) for s in ("done", "failed", "cancelled")
    }

    for status, job_id in ids.items():
        r = await client.post(f"{JOBS}/{job_id}/cancel", headers=admin_headers)
        assert r.status_code == 202, r.text
        _, atual, _, cancel, _, _ = await _job(db_session, job_id)
        assert (atual, cancel) == (status, False)


async def test_cancelar_job_inexistente_ou_de_outro_projeto_e_404(
    client, admin_headers, db_session
):
    cen = await _cenario(client, admin_headers, db_session)
    alheio = await _inserir_job(db_session, cen["outro"], "queued")

    for job_id in (999999, alheio):
        r = await client.post(f"{JOBS}/{job_id}/cancel", headers=admin_headers)
        assert (r.status_code, r.json()["detail"]) == (404, "Job não encontrado")
    assert (await _job(db_session, alheio))[1] == "queued"
    # id acima de bigint é recusado na borda, não estoura no driver
    r = await client.post(f"{JOBS}/{10**20}/cancel", headers=admin_headers)
    assert r.status_code == 422, r.text


async def test_jobs_active_filtra_queued_e_running(
    client, admin_headers, operator_headers, db_session
):
    cen = await _cenario(client, admin_headers, db_session)
    ids = {
        s: await _inserir_job(db_session, cen["pid"], s)
        for s in ("done", "queued", "failed", "running", "cancelled")
    }
    await _inserir_job(db_session, cen["outro"], "queued")  # de outro projeto: nunca aparece

    async def listar(**params) -> list[int]:
        r = await client.get(JOBS, params=params, headers=operator_headers)
        assert r.status_code == 200, r.text
        return [j["id"] for j in r.json()]

    assert await listar(active="true") == [ids["running"], ids["queued"]]
    assert await listar(active="false") == [ids["cancelled"], ids["failed"], ids["done"]]
    assert await listar() == sorted(ids.values(), reverse=True)  # mais novos primeiro

    r = await client.get(f"{JOBS}/{ids['queued']}", headers=operator_headers)
    assert r.status_code == 200, r.text
    assert set(r.json()) == {
        "id",
        "kind",
        "status",
        "params",
        "progress",
        "result",
        "error",
        "created_at",
        "started_at",
        "finished_at",
    }
    assert (await client.get(f"{JOBS}/999999", headers=operator_headers)).status_code == 404


async def test_operador_nao_cria_nem_finaliza_nem_apaga_nem_cancela(
    client, admin_headers, operator_headers, db_session
):
    cen = await _cenario(client, admin_headers, db_session)
    ds = await _criar(client, admin_headers, cen)
    job_id = await _inserir_job(db_session, cen["pid"], "queued")

    respostas = [
        await client.post(DATASETS, json=_corpo(cen, name="outro"), headers=operator_headers),
        await client.post(f"{DATASETS}/{ds['id']}/finalize", headers=operator_headers),
        await client.delete(f"{DATASETS}/{ds['id']}", headers=operator_headers),
        await client.post(f"{JOBS}/{job_id}/cancel", headers=operator_headers),
    ]

    assert [r.status_code for r in respostas] == [403, 403, 403, 403]
    assert (await _conjunto(db_session, ds["id"]))[0] == "collecting"
    assert (await _job(db_session, job_id))[1] == "queued"
