"""Prova do write path de `0009_mpc_max_rate.py::_migrar` (ARCH-08/TD-019).

Decisão (avaliada e registrada aqui, não só no relatório): a migração NÃO passa a chamar
`parse_graph` internamente. Uma migração alembic é artefato histórico que roda de novo do
zero em todo ambiente novo — e o app já trata `graph_json` corrompido como dado degradável,
nunca como erro fatal (`services/api/tests/test_operate.py::test_mpcs_graph_invalido_pulado_com_log`
prova que o caminho de leitura pula o flow com log, não derruba a rota). Fazer `_migrar`
levantar dentro do `upgrade()` trocaria essa falha tolerada (um flow pulado) por uma falha
fatal nova (a cadeia de migração inteira trava em QUALQUER ambiente que já tivesse um
`graph_json` alheio inválido antes da 0009, mesmo sem relação com `du_max`/`max_rate`) — pior
que o problema que resolve. A validação mora aqui: fora da migração, sobre o resultado real
de `_migrar`, que é onde o valor está segundo a própria auditoria (seção "Superfície de teste").
"""

import importlib.util
import json
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import text

from ottima_core.flowgraph import parse_graph

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0009_mpc_max_rate.py"
)
_spec = importlib.util.spec_from_file_location("_migration_0009_mpc_max_rate", _MIGRATION_PATH)
assert _spec is not None and _spec.loader is not None
_migration_0009 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration_0009)

_FLOWS_TABLE = sa.table(
    "flows",
    sa.column("id", sa.BigInteger),
    sa.column("ts_seconds", sa.Numeric),
    sa.column("graph_json", sa.JSON),
)


def _graph_pre_rename(du_max: float) -> dict:
    """`graph_json` como gravado antes da 0009: MV com `du_max`, sem `max_rate`."""
    return {
        "nodes": [
            {
                "id": "n1",
                "type": "mpc",
                "position": {"x": 0.0, "y": 0.0},
                "data": {
                    "exec_order": 1,
                    "multiplier": 2,
                    "variables": {
                        "mvs": [
                            {
                                "id": "mv_a",
                                "name": "MV A",
                                "readback_tag_id": 1,
                                "limits": {"min": 0.0, "max": 100.0},
                                "du_max": du_max,
                                "initial_value": 0.0,
                            }
                        ],
                        "cvs": [],
                        "constraints": [],
                        "dvs": [],
                    },
                    "models": [],
                },
            }
        ],
        "edges": [],
    }


async def test_migrar_du_max_para_max_rate_parseia_limpo_e_converte_certo(db_session):
    ts_seconds = 2.0
    multiplier = 2.0
    du_max = 40.0

    await db_session.execute(text("INSERT INTO projects (name) VALUES ('p-mig-0009')"))
    pid = (
        await db_session.execute(text("SELECT id FROM projects WHERE name = 'p-mig-0009'"))
    ).scalar_one()
    await db_session.execute(
        text(
            "INSERT INTO flows (project_id, name, ts_seconds, graph_json)"
            " VALUES (:p, 'f-mig-0009', :ts, CAST(:g AS jsonb))"
        ),
        {"p": pid, "ts": ts_seconds, "g": json.dumps(_graph_pre_rename(du_max))},
    )

    conn = await db_session.connection()
    await conn.run_sync(
        lambda sync_conn: _migration_0009._migrar(_FLOWS_TABLE, sync_conn, para_max_rate=True)
    )

    resultado = (
        await db_session.execute(text("SELECT graph_json FROM flows WHERE name = 'f-mig-0009'"))
    ).scalar_one()

    mv = resultado["nodes"][0]["data"]["variables"]["mvs"][0]
    assert "du_max" not in mv
    assert mv["max_rate"] == du_max / (ts_seconds * multiplier)

    parse_graph(resultado)  # não levanta: shape do resultado é um `graph_json` válido
