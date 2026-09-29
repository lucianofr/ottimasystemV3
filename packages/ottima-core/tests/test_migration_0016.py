"""0016: flows SISO gravados com `fuzzy_loop` sobrevivem ao redesenho multicanal.

Ida: portas `in`/`out` viram `pv_1`/`out_1`, modos remotos saem de permitted/normal, arestas
em portas extintas (intertravamento `lo_in_d`) ficam — o flow é rejeitado alto, não mutilado.
Volta: aborta com bloco multicanal; sem ele, desfaz a conversão e apaga SPs de canal > 0.
Síncrono, mesma disciplina de `test_downgrade_0005_*` (não aninha o loop async do env.py).
"""

import asyncio
import json
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ottima_core.flowgraph.parse import FuzzyLoopConfig

_GRAFO_SISO = {
    "nodes": [
        {"id": "r", "type": "opc_read", "data": {"exec_order": 1, "tag_id": 1}},
        {"id": "il", "type": "opc_read", "data": {"exec_order": 2, "tag_id": 2}},
        {
            "id": "fm",
            "type": "fuzzy_loop",
            "data": {
                "exec_order": 3,
                "ke": 0.05,
                "ku": 2.0,
                "sp_lo_lim": 0.0,
                "sp_hi_lim": 100.0,
                "permitted": ["oos", "man", "auto", "cas"],
                "normal": "cas",
            },
        },
    ],
    "edges": [
        {"id": "e1", "source": "r", "target": "fm", "sourceHandle": "out", "targetHandle": "in"},
        {"id": "e2", "source": "fm", "target": "w", "sourceHandle": "out", "targetHandle": "in"},
        {
            "id": "e3",
            "source": "il",
            "target": "fm",
            "sourceHandle": "out",
            "targetHandle": "lo_in_d",
        },
    ],
}


def _sql(url: str, *stmts: tuple[str, dict[str, Any]]) -> list[Any]:
    async def rodar() -> list[Any]:
        engine = create_async_engine(url)
        saida: list[Any] = []
        async with engine.begin() as conn:
            for sql, params in stmts:
                r = await conn.execute(text(sql), params)
                saida.append(r.fetchall() if r.returns_rows else None)
        await engine.dispose()
        return saida

    return asyncio.run(rodar())


def _grafo(url: str, flow_id: int) -> dict[str, Any]:
    [[(g,)]] = _sql(url, ("SELECT graph_json FROM flows WHERE id = :f", {"f": flow_id}))
    return g


def _handles(g: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return {e["id"]: (e["sourceHandle"], e["targetHandle"]) for e in g["edges"]}


def test_0016_migra_fuzzy_loop_siso_e_volta(migrated_database_url):
    url = migrated_database_url
    cfg = Config("packages/ottima-core/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    flow_id: int | None = None
    try:
        command.downgrade(cfg, "0015_loop_tables")
        [_, [(flow_id,)], _] = _sql(
            url,
            ("INSERT INTO projects (name) VALUES ('mig0016') RETURNING id", {}),
            (
                "INSERT INTO flows (project_id, name, ts_seconds, graph_json)"
                " VALUES ((SELECT id FROM projects WHERE name = 'mig0016'), 'f', 1,"
                " CAST(:g AS jsonb)) RETURNING id",
                {"g": json.dumps(_GRAFO_SISO)},
            ),
            (
                "INSERT INTO loop_setpoints (flow_id, block_id, sp)"
                " VALUES ((SELECT max(id) FROM flows), 'fm', 42)",
                {},
            ),
        )

        command.upgrade(cfg, "0016_loop_setpoints_channel")
        g = _grafo(url, flow_id)
        data = next(n for n in g["nodes"] if n["id"] == "fm")["data"]
        assert data["permitted"] == ["oos", "man", "auto"] and data["normal"] == "auto"
        assert _handles(g) == {
            "e1": ("out", "pv_1"),
            "e2": ("out_1", "in"),  # `in` do opc_write não é do fuzzy_loop: intocado
            "e3": ("out", "lo_in_d"),  # intertravamento não some em silêncio
        }
        # Config agora valida no v2 (o erro remanescente é o handle extinto, alto e explícito).
        FuzzyLoopConfig.model_validate({k: v for k, v in data.items() if k != "exec_order"})
        [[(canal, sp)]] = _sql(url, ("SELECT channel, sp FROM loop_setpoints", {}))
        assert (canal, sp) == (0, 42)

        # Bloco multicanal não tem forma SISO: downgrade aborta sem mutar nada.
        data_mimo = {**data, "n_loops": 2}
        nos = [n if n["id"] != "fm" else {**n, "data": data_mimo} for n in g["nodes"]]
        _sql(
            url,
            (
                "UPDATE flows SET graph_json = CAST(:g AS jsonb) WHERE id = :f",
                {"g": json.dumps({**g, "nodes": nos}), "f": flow_id},
            ),
            (
                "INSERT INTO loop_setpoints (flow_id, block_id, channel, sp)"
                " VALUES (:f, 'fm', 1, 7)",
                {"f": flow_id},
            ),
        )
        with pytest.raises(RuntimeError, match="n_loops > 1"):
            command.downgrade(cfg, "0015_loop_tables")

        # De volta a 1 canal (n_loops explícito): downgrade limpa e reverte as portas.
        data_um = {**data, "n_loops": 1}
        nos = [n if n["id"] != "fm" else {**n, "data": data_um} for n in g["nodes"]]
        _sql(
            url,
            (
                "UPDATE flows SET graph_json = CAST(:g AS jsonb) WHERE id = :f",
                {"g": json.dumps({**g, "nodes": nos}), "f": flow_id},
            ),
        )
        command.downgrade(cfg, "0015_loop_tables")
        g = _grafo(url, flow_id)
        assert "n_loops" not in next(n for n in g["nodes"] if n["id"] == "fm")["data"]
        assert _handles(g)["e1"] == ("out", "in") and _handles(g)["e2"] == ("out", "in")
        [linhas] = _sql(url, ("SELECT block_id, sp FROM loop_setpoints", {}))
        assert [tuple(r) for r in linhas] == [("fm", 42)]
    finally:
        command.upgrade(cfg, "head")
        _sql(
            url,
            (
                "DELETE FROM flows WHERE name = 'f' AND project_id IN"
                " (SELECT id FROM projects WHERE name = 'mig0016')",
                {},
            ),
            ("DELETE FROM projects WHERE name = 'mig0016'", {}),
        )
