import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


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
        await db_session.execute(text("INSERT INTO projects (name, is_active) VALUES ('p2', true)"))


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


def test_downgrade_0005_restaura_watchdog_em_opc_connections(migrated_database_url):
    """Downgrade simétrico da 0005: watchdog volta para `opc_connections` e sai de
    `flows` — mesma disciplina de `test_downgrade_remove_ssto_runs` (síncrono, não
    aninha o loop async de `env.py`)."""
    cfg = Config("packages/ottima-core/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", migrated_database_url)
    try:
        command.downgrade(cfg, "0004_ssto_runs")

        async def checar_colunas() -> tuple[set[str], set[str]]:
            engine = create_async_engine(migrated_database_url)
            async with engine.connect() as conn:
                conexoes = await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_name = 'opc_connections'"
                    )
                )
                flows = await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_name = 'flows'"
                    )
                )
                colunas_conexao = {r[0] for r in conexoes}
                colunas_flow = {r[0] for r in flows}
            await engine.dispose()
            return colunas_conexao, colunas_flow

        colunas_conexao, colunas_flow = asyncio.run(checar_colunas())
        assert {
            "watchdog_read_node_id",
            "watchdog_write_node_id",
            "watchdog_period_ms",
        } <= colunas_conexao
        assert not colunas_flow & {
            "watchdog_enabled",
            "watchdog_connection_id",
            "watchdog_read_node_id",
            "watchdog_write_node_id",
            "watchdog_period_ms",
        }
    finally:
        command.upgrade(cfg, "head")
