from sqlalchemy import text

from ottima_core.connections import conexoes_sem_watchdog


async def test_traz_so_conexoes_do_projeto_sem_watchdog_completo(db_session):
    """TD-004: falta um dos dois node_ids (ou os dois) já conta como sem watchdog; a
    conexão com o par completo, e a de outro projeto, ficam de fora."""
    await db_session.execute(text("INSERT INTO projects (name) VALUES ('p1'), ('p2')"))
    p1, p2 = (await db_session.execute(text("SELECT id FROM projects ORDER BY name"))).scalars()

    await db_session.execute(
        text(
            "INSERT INTO opc_connections"
            " (project_id, name, endpoint, watchdog_read_node_id, watchdog_write_node_id)"
            " VALUES"
            " (:p1, 'sem-nenhum', 'opc.tcp://a:4840', NULL, NULL),"
            " (:p1, 'sem-leitura', 'opc.tcp://b:4840', NULL, 'ns=2;s=WD_W'),"
            " (:p1, 'completa', 'opc.tcp://c:4840', 'ns=2;s=WD_R', 'ns=2;s=WD_W'),"
            " (:p2, 'outro-projeto', 'opc.tcp://d:4840', NULL, NULL)"
        ),
        {"p1": p1, "p2": p2},
    )
    linhas = await db_session.execute(
        text("SELECT id, name FROM opc_connections WHERE project_id = :p1 ORDER BY name"),
        {"p1": p1},
    )
    id_por_nome = {nome: conn_id for conn_id, nome in linhas}

    resultado = await conexoes_sem_watchdog(db_session, p1)

    assert resultado == {
        id_por_nome["sem-nenhum"]: "sem-nenhum",
        id_por_nome["sem-leitura"]: "sem-leitura",
    }
