import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def test_tabelas_relacionais_existem(db_engine):
    async with db_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        names = {r[0] for r in rows}
    assert {"users", "projects", "opc_connections", "tags", "flows"} <= names


async def test_apenas_um_projeto_ativo(db_session):
    await db_session.execute(text("INSERT INTO projects (name, is_active) VALUES ('p1', true)"))
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text("INSERT INTO projects (name, is_active) VALUES ('p2', true)")
        )


async def test_ts_fora_da_lista_rejeitado(db_session):
    await db_session.execute(text("INSERT INTO projects (name) VALUES ('p3')"))
    pid = (await db_session.execute(text("SELECT id FROM projects WHERE name = 'p3'"))).scalar_one()
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text("INSERT INTO flows (project_id, name, ts_seconds) VALUES (:p, 'f1', 0.7)"),
            {"p": pid},
        )


async def test_policy_mode_incoerente_rejeitado(db_session):
    await db_session.execute(text("INSERT INTO projects (name) VALUES ('p4')"))
    pid = (await db_session.execute(text("SELECT id FROM projects WHERE name = 'p4'"))).scalar_one()
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO opc_connections (project_id, name, endpoint, security_policy,"
                " security_mode)"
                " VALUES (:p, 'c1', 'opc.tcp://x:4840', 'basic256sha256', 'none')"
            ),
            {"p": pid},
        )


async def test_username_unico_case_insensitive(db_session):
    await db_session.execute(
        text(
            "INSERT INTO users (username, name, password_hash, role)"
            " VALUES ('Admin', 'A', 'h', 'admin')"
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO users (username, name, password_hash, role)"
                " VALUES ('admin', 'B', 'h', 'admin')"
            )
        )
