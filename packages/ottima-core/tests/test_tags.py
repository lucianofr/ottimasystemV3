from sqlalchemy import text

from ottima_core.flowgraph import TagRef
from ottima_core.tags import project_tags


async def test_so_traz_tags_das_conexoes_do_projeto(db_session):
    """Duas conexões, dois projetos: `project_tags` não pode vazar tag de outro projeto."""
    await db_session.execute(text("INSERT INTO projects (name) VALUES ('p1'), ('p2')"))
    p1, p2 = (
        await db_session.execute(text("SELECT id FROM projects ORDER BY name"))
    ).scalars()

    await db_session.execute(
        text(
            "INSERT INTO opc_connections (project_id, name, endpoint)"
            " VALUES (:p1, 'c1', 'opc.tcp://x:4840'), (:p2, 'c2', 'opc.tcp://y:4840')"
        ),
        {"p1": p1, "p2": p2},
    )
    c1, c2 = (
        await db_session.execute(text("SELECT id FROM opc_connections ORDER BY name"))
    ).scalars()

    await db_session.execute(
        text(
            "INSERT INTO tags (connection_id, name, node_id, direction, data_type)"
            " VALUES"
            " (:c1, 't1', 'ns=1;s=t1', 'r', 'float'),"
            " (:c2, 't2', 'ns=1;s=t2', 'w', 'int')"
        ),
        {"c1": c1, "c2": c2},
    )
    tag1_id = (
        await db_session.execute(text("SELECT id FROM tags WHERE name = 't1'"))
    ).scalar_one()

    tags = await project_tags(db_session, p1)

    assert tags == {
        tag1_id: TagRef(id=tag1_id, conn_id=c1, direction="r", data_type="float"),
    }
