"""`du_max` (EU/ciclo) vira `max_rate` (EU/s) nos blocos MPC gravados (RF-604 revisado)

Migração de DADOS sobre `flows.graph_json`: para cada nó `type == "mpc"`, cada MV com
`du_max` ganha `max_rate = du_max / (ts_seconds × multiplier)` e perde a chave `du_max`.
Os demais campos novos do config (zero/span, fail_action etc.) NÃO são escritos — os
defaults do Pydantic os cobrem, e como todas as classes usam `extra="forbid"`, esta
migração é obrigatória antes de qualquer parse dos configs gravados.
"""

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0009_mpc_max_rate"
down_revision = "0008_system_settings"
branch_labels = None
depends_on = None


def _regravar(
    flows: sa.sql.TableClause, conn: sa.engine.Connection, flow_id: int, graph: dict[str, Any]
) -> None:
    # Coluna é JSONB: passa o dict — string aqui gravaria um JSON-string, não o objeto.
    conn.execute(flows.update().where(flows.c.id == flow_id).values(graph_json=graph))


def _migrar(flows: sa.sql.TableClause, conn: sa.engine.Connection, *, para_max_rate: bool) -> None:
    rows = conn.execute(sa.select(flows.c.id, flows.c.ts_seconds, flows.c.graph_json)).fetchall()
    for flow_id, ts_seconds, graph_json in rows:
        graph = json.loads(graph_json) if isinstance(graph_json, str) else graph_json
        sujo = False
        for node in graph.get("nodes", []):
            if node.get("type") != "mpc":
                continue
            # Forma React Flow gravada no `graph_json`: o config do bloco é o `data` do nó
            # (a tradução data→config é do parse, flowgraph/parse.py).
            config = node.get("data")
            if not isinstance(config, dict):
                continue
            multiplier = float(config.get("multiplier", 1))
            mvs = config.get("variables", {}).get("mvs", [])
            for mv in mvs:
                if para_max_rate and "du_max" in mv:
                    mv["max_rate"] = mv.pop("du_max") / (float(ts_seconds) * multiplier)
                    sujo = True
                elif not para_max_rate and "max_rate" in mv:
                    mv["du_max"] = mv.pop("max_rate") * float(ts_seconds) * multiplier
                    sujo = True
        if sujo:
            _regravar(flows, conn, flow_id, graph)


def upgrade() -> None:
    flows = sa.table(
        "flows",
        sa.column("id", sa.BigInteger),
        sa.column("ts_seconds", sa.Numeric),
        sa.column("graph_json", sa.JSON),
    )
    _migrar(flows, op.get_bind(), para_max_rate=True)


def downgrade() -> None:
    flows = sa.table(
        "flows",
        sa.column("id", sa.BigInteger),
        sa.column("ts_seconds", sa.Numeric),
        sa.column("graph_json", sa.JSON),
    )
    _migrar(flows, op.get_bind(), para_max_rate=False)
