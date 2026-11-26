"""Tabelas de laboratório, conjunto de treino e jobs do sensor virtual (ADR-046 D1/D7, spec §7.1,
§7.3, §7.5): unicidade, chave composta da análise, FK sem cascata da variável para o conjunto,
cascata do projeto, vocabulários fechados e `data` diferido."""

import asyncio
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from ottima_core.models import (
    LabSample,
    LabVariable,
    MlJob,
    Project,
    SoftSensorDataset,
)

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def _projeto(session, nome: str = "p-lab") -> Project:
    projeto = Project(name=nome)
    session.add(projeto)
    await session.commit()
    return projeto


async def _variavel(session, projeto: Project, nome: str = "v1") -> LabVariable:
    variavel = LabVariable(project_id=projeto.id, name=nome)
    session.add(variavel)
    await session.commit()
    return variavel


def _amostra(variavel: LabVariable, fonte: str = "manual") -> LabSample:
    return LabSample(
        lab_variable_id=variavel.id, sampled_at=_T0, value=1.5, source=fonte, created_by="user:1"
    )


def _conjunto(
    projeto: Project,
    variavel: LabVariable,
    nome: str = "c1",
    period_s: float = 60.0,
    **extra,
) -> SoftSensorDataset:
    return SoftSensorDataset(
        project_id=projeto.id,
        name=nome,
        lab_variable_id=variavel.id,
        input_tag_ids=[1, 2],
        period_s=period_s,
        start_ts=_T0,
        created_by="user:1",
        **extra,
    )


def _job(projeto: Project, **extra) -> MlJob:
    campos = {"kind": "dataset_build", "params": {"dataset_id": 1}, "created_by": "user:1"}
    return MlJob(project_id=projeto.id, **(campos | extra))


async def _contar(session, tabela) -> int:
    return await session.scalar(select(func.count()).select_from(tabela))


async def test_nome_de_variavel_unico_por_projeto(db_session):
    projeto = await _projeto(db_session)
    await _variavel(db_session, projeto)
    db_session.add(LabVariable(project_id=projeto.id, name="v1"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_variavel_tem_defaults_de_unidade_e_descricao(db_session):
    projeto = await _projeto(db_session)
    variavel = await _variavel(db_session, projeto)
    await db_session.refresh(variavel)
    assert (variavel.eu, variavel.description) == ("", "")
    assert variavel.created_at is not None and variavel.updated_at is not None


async def test_mesma_variavel_e_instante_e_uma_linha_so(db_session):
    projeto = await _projeto(db_session)
    variavel = await _variavel(db_session, projeto)
    db_session.add(_amostra(variavel))
    await db_session.commit()
    db_session.add(_amostra(variavel, fonte="csv"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_variavel_usada_por_conjunto_nao_pode_ser_apagada(db_session):
    projeto = await _projeto(db_session)
    variavel = await _variavel(db_session, projeto)
    db_session.add(_conjunto(projeto, variavel))
    await db_session.commit()
    await db_session.delete(variavel)
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_apagar_variavel_apaga_as_analises(db_session):
    projeto = await _projeto(db_session)
    variavel = await _variavel(db_session, projeto)
    db_session.add(_amostra(variavel))
    await db_session.commit()
    await db_session.delete(variavel)
    await db_session.commit()
    assert await _contar(db_session, LabSample) == 0


async def test_apagar_projeto_apaga_variaveis_analises_conjuntos_e_jobs(db_session):
    """Conjunto e variavel sao filhos diretos do projeto: a FK conjunto -> variavel (sem ON DELETE)
    nao atrapalha a cascata, em qualquer ordem dos triggers de RI."""
    projeto = await _projeto(db_session)
    variavel = await _variavel(db_session, projeto)
    db_session.add_all([_amostra(variavel), _conjunto(projeto, variavel), _job(projeto)])
    await db_session.commit()

    await db_session.delete(projeto)
    await db_session.commit()

    for tabela in (LabVariable, LabSample, SoftSensorDataset, MlJob):
        assert await _contar(db_session, tabela) == 0


async def test_periodo_fora_da_lista_e_recusado(db_session):
    projeto = await _projeto(db_session)
    variavel = await _variavel(db_session, projeto)
    db_session.add(_conjunto(projeto, variavel, period_s=3.0))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.parametrize("periodo", [1, 2, 5, 10, 30, 60, 300, 600])
async def test_periodos_da_lista_fechada_sao_aceitos(db_session, periodo):
    projeto = await _projeto(db_session)
    variavel = await _variavel(db_session, projeto)
    db_session.add(_conjunto(projeto, variavel, period_s=float(periodo)))
    await db_session.commit()


@pytest.mark.parametrize(
    "construir",
    [
        pytest.param(lambda p, v: _amostra(v, fonte="ocr"), id="source"),
        pytest.param(lambda p, v: _conjunto(p, v, status="done"), id="status-do-conjunto"),
        pytest.param(lambda p, v: _job(p, kind="predict"), id="kind-do-job"),
        pytest.param(lambda p, v: _job(p, kind="train", status="ready"), id="status-do-job"),
    ],
)
async def test_status_e_kind_fora_do_vocabulario_sao_recusados(db_session, construir):
    projeto = await _projeto(db_session)
    variavel = await _variavel(db_session, projeto)
    db_session.add(construir(projeto, variavel))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_select_do_conjunto_nao_carrega_data(db_session):
    projeto = await _projeto(db_session)
    variavel = await _variavel(db_session, projeto)
    db_session.add(_conjunto(projeto, variavel, data=b"\x00\x01"))
    await db_session.commit()
    db_session.expunge_all()  # sem isto o identity map devolve o objeto com `data` já preenchido

    obtido = (await db_session.execute(select(SoftSensorDataset))).scalar_one()

    assert "data" in inspect(obtido).unloaded
    assert obtido.status == "collecting"  # default do banco
    assert (obtido.stats, obtido.inputs_meta, obtido.end_ts) == ({}, [], None)


async def test_job_nasce_na_fila_com_progresso_vazio(db_session):
    projeto = await _projeto(db_session)
    db_session.add(_job(projeto))
    await db_session.commit()
    db_session.expunge_all()

    job = (await db_session.execute(select(MlJob))).scalar_one()

    assert (job.status, job.progress, job.cancel_requested) == ("queued", {}, False)
    assert (job.result, job.error, job.started_at, job.finished_at) == (None, None, None, None)
    assert job.created_at is not None


def test_downgrade_remove_as_tabelas_e_o_upgrade_as_recria(migrated_database_url):
    """Mesma disciplina de `test_soft_sensor_models`: síncrono, sem aninhar o loop do env.py."""
    cfg = Config("packages/ottima-core/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", migrated_database_url)

    def tabelas() -> set[str]:
        async def consultar() -> set[str]:
            engine = create_async_engine(migrated_database_url)
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
                nomes = {r[0] for r in rows}
            await engine.dispose()
            return nomes

        return asyncio.run(consultar())

    alvo = {"lab_variables", "lab_samples", "soft_sensor_datasets", "ml_jobs"}
    try:
        command.downgrade(cfg, "0018_soft_sensor")
        assert not alvo & tabelas()
    finally:
        command.upgrade(cfg, "head")
    assert alvo <= tabelas()
