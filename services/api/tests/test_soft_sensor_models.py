"""Tabelas de modelo e vínculo do sensor virtual (ADR-046 D6, spec §7.4): unicidade, FK sem
cascata do modelo, cascata de flow/projeto, vocabulário de método e `weights` diferido."""

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from ottima_core.models import Flow, Project, SoftSensorBinding, SoftSensorModel


async def _projeto(session, nome: str = "p-sv") -> Project:
    projeto = Project(name=nome)
    session.add(projeto)
    await session.commit()
    return projeto


async def _flow(session, projeto: Project, nome: str = "f-sv") -> Flow:
    flow = Flow(project_id=projeto.id, name=nome, ts_seconds=1)
    session.add(flow)
    await session.commit()
    return flow


def _modelo(projeto: Project, nome: str = "m1", metodo: str = "pls") -> SoftSensorModel:
    return SoftSensorModel(
        project_id=projeto.id,
        name=nome,
        method=metodo,
        period_s=60.0,
        n_inputs=2,
        meta={"k": 1},
        weights=b"\x00\x01",
        created_by="user:1",
    )


async def _contar(session, tabela) -> int:
    return await session.scalar(select(func.count()).select_from(tabela))


async def _cascata_dos_modelos_antes_da_dos_flows(session) -> None:
    """Fixa a ordem de disparo dos triggers de RI em `projects`: o Postgres os dispara por ordem
    alfabetica do nome (`RI_ConstraintTrigger_a_<oid>`), e o oid de um banco longevo (6 digitos)
    ordena ANTES do de um banco recem-criado (5 digitos). Num banco novo, como o dos testes, a
    ordem natural poupa o bug; renomear os dois triggers reproduz o pior caso, de forma
    deterministica (o rename e DDL transacional: o rollback da fixture desfaz)."""
    for tabela, novo in (
        ("soft_sensor_models", "RI_ConstraintTrigger_a_000001"),
        ("flows", "RI_ConstraintTrigger_a_000002"),
    ):
        nome = await session.scalar(
            text(
                "SELECT t.tgname FROM pg_trigger t JOIN pg_constraint c ON c.oid = t.tgconstraint"
                " WHERE t.tgrelid = 'projects'::regclass AND c.conrelid = to_regclass(:tabela)"
                " AND t.tgfoid = '\"RI_FKey_cascade_del\"'::regproc"
            ),
            {"tabela": tabela},
        )
        assert nome is not None
        await session.execute(text(f'ALTER TRIGGER "{nome}" ON projects RENAME TO "{novo}"'))


async def test_nome_de_modelo_e_unico_por_projeto(db_session):
    projeto = await _projeto(db_session)
    db_session.add(_modelo(projeto))
    await db_session.commit()
    db_session.add(_modelo(projeto))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.parametrize("coluna", ["desired_model_id", "active_model_id", "candidate_model_id"])
async def test_modelo_vinculado_nao_pode_ser_apagado(db_session, coluna):
    projeto = await _projeto(db_session)
    flow = await _flow(db_session, projeto)
    modelo = _modelo(projeto)
    db_session.add(modelo)
    await db_session.commit()
    db_session.add(
        SoftSensorBinding(
            flow_id=flow.id, block_id="b1", updated_by="user:1", **{coluna: modelo.id}
        )
    )
    await db_session.commit()
    # As FKs sao DEFERRABLE INITIALLY DEFERRED: fora de teste a recusa vem no COMMIT; a fixture
    # nunca comita a transacao externa, entao forca-se a checagem imediata.
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await db_session.delete(modelo)
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_apagar_o_flow_apaga_o_vinculo(db_session):
    projeto = await _projeto(db_session)
    flow = await _flow(db_session, projeto)
    modelo = _modelo(projeto)
    db_session.add(modelo)
    await db_session.commit()
    db_session.add(
        SoftSensorBinding(
            flow_id=flow.id, block_id="b1", desired_model_id=modelo.id, updated_by="user:1"
        )
    )
    await db_session.commit()
    await db_session.delete(flow)
    await db_session.commit()
    assert await _contar(db_session, SoftSensorBinding) == 0
    assert await _contar(db_session, SoftSensorModel) == 1


async def test_apagar_projeto_com_modelo_vinculado(db_session):
    """A cascata do projeto apaga flows (e vinculos) e modelos no mesmo comando, e a ordem entre
    as duas cascatas e a dos triggers de RI, nao a do SQL. Com a cascata dos modelos primeiro, uma
    FK checada na hora ve o vinculo ainda de pe e recusa o delete; adiada ate o COMMIT, ela so
    olha o estado final, depois das duas cascatas."""
    projeto = await _projeto(db_session)
    flow = await _flow(db_session, projeto)
    modelo = _modelo(projeto)
    db_session.add(modelo)
    await db_session.commit()
    db_session.add(
        SoftSensorBinding(
            flow_id=flow.id,
            block_id="b1",
            desired_model_id=modelo.id,
            active_model_id=modelo.id,
            candidate_model_id=modelo.id,
            updated_by="user:1",
        )
    )
    await db_session.commit()
    await _cascata_dos_modelos_antes_da_dos_flows(db_session)

    await db_session.delete(projeto)
    await db_session.commit()
    # A fixture nunca comita a transacao externa: forca as checagens adiadas a rodar agora.
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    assert await _contar(db_session, SoftSensorModel) == 0
    assert await _contar(db_session, SoftSensorBinding) == 0


async def test_metodo_fora_do_vocabulario_e_recusado(db_session):
    projeto = await _projeto(db_session)
    db_session.add(_modelo(projeto, metodo="svm"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_select_do_modelo_nao_carrega_os_pesos(db_session):
    projeto = await _projeto(db_session)
    modelo = _modelo(projeto)
    db_session.add(modelo)
    await db_session.commit()
    db_session.expunge_all()  # sem isto o identity map devolve o objeto com `weights` já preenchido

    obtido = (await db_session.execute(select(SoftSensorModel))).scalar_one()

    assert "weights" in inspect(obtido).unloaded
    assert obtido.input_tag_ids == []  # default `'{}'` do banco


def test_downgrade_remove_as_tabelas_e_o_upgrade_as_recria(migrated_database_url):
    """Mesma disciplina de `test_downgrade_0005_*`: síncrono, não aninha o loop async do env.py."""
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

    alvo = {"soft_sensor_models", "soft_sensor_bindings"}
    try:
        command.downgrade(cfg, "0017_loop_setpoints_channel")
        assert not alvo & tabelas()
    finally:
        command.upgrade(cfg, "head")
    assert alvo <= tabelas()
