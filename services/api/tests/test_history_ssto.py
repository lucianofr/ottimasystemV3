"""`GET /api/history/ssto/last` — última execução do SSTO do bloco (ADR-027 §11, RF-903).

Cold-start do sumário do otimizador na Operação: sem este endpoint o card ficaria vazio até
o próximo ciclo do MPC (Ts_mpc pode ser minutos). Mesmo esqueleto de cenário de
`test_history_mpc.py` (auto-contido no projeto, um bloco `mpc` + um `opc_read`).
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import column, insert, table
from sqlalchemy.dialects.postgresql import JSONB

BASE = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)

# Construto leve `table()/column()` — mesmo padrão do router (sem handle no core para não
# participar do autogenerate do Alembic). As colunas JSONB carregam o tipo explícito: sem
# ele o asyncpg recebe o `dict` cru e não sabe codificar (`table()` sem MetaData não herda
# o tipo da DDL).
ssto_runs = table(
    "ssto_runs",
    column("ts"),
    column("flow_id"),
    column("block_id"),
    column("run_id"),
    column("config_hash"),
    column("model_hash"),
    column("status"),
    column("solver"),
    column("solve_ms"),
    column("objective"),
    column("mv", JSONB),
    column("cv_ss", JSONB),
    column("bias", JSONB),
    column("dv", JSONB),
    column("costs", JSONB),
    column("delta_mv", JSONB),
    column("mv_target", JSONB),
    column("cv_target", JSONB),
    column("given_up", JSONB),
    column("active_constraints", JSONB),
    column("duals", JSONB),
)


# --------------------------------------------------------------- construtores do cenário MPC


async def _projeto(client, headers, nome: str) -> int:
    r = await client.post("/api/projects", json={"name": nome}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _conexao(client, headers, project_id: int, nome: str) -> int:
    r = await client.post(
        "/api/connections",
        json={"project_id": project_id, "name": nome, "endpoint": "opc.tcp://x:4840"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _tag(client, headers, conn_id: int, nome: str, direcao: str) -> int:
    r = await client.post(
        "/api/tags",
        json={
            "connection_id": conn_id,
            "name": nome,
            "node_id": f"ns=2;s={nome}",
            "direction": direcao,
            "data_type": "float",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _flow(client, headers, project_id: int, nome: str) -> dict:
    r = await client.post(
        "/api/flows",
        json={"project_id": project_id, "name": nome, "ts_seconds": 1},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _no(node_id: str, tipo: str, exec_order: int, **config) -> dict:
    return {
        "id": node_id,
        "type": tipo,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, **config},
    }


def _aresta(source: str, source_handle: str, target: str, target_handle: str, id_: str) -> dict:
    return {
        "id": id_,
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
    }


def _mpc_data() -> dict:
    """Bloco MPC mínimo válido (1 MV + 1 CV) — a rota só exige que o bloco exista e seja
    `mpc` (mesma barreira de `get_history_mpc`)."""
    mv = {
        "id": "mv_a",
        "name": "MV a",
        "eu": "m3/h",
        "limits": {"min": 0.0, "max": 100.0},
        "max_rate": 5.0,
        "initial_value": 0.0,
    }
    cv = {
        "id": "cv_a",
        "name": "CV a",
        "eu": "C",
        "kind": "selfreg",
        "tss": 30.0,
        "weight": 1.0,
        "sp_limits": {"min": 80.0, "max": 120.0},
    }
    models = {
        "cv_a": {
            "mv_a": {
                "enabled": True,
                "params": {"K": 1.2, "tau1": 10.0, "tau2": 2.0, "theta": 15.0},
            }
        }
    }
    return {
        "name": "MPC teste",
        "multiplier": 1,
        "variables": {"mvs": [mv], "cvs": [cv], "constraints": [], "dvs": []},
        "models": models,
    }


async def _cenario(client, admin_headers, nome: str) -> tuple[int, str]:
    pid = await _projeto(client, admin_headers, nome)
    cid = await _conexao(client, admin_headers, pid, f"plc-{nome}")
    flow = await _flow(client, admin_headers, pid, nome)
    tag_id = await _tag(client, admin_headers, cid, "IN-1", "r")
    graph = {
        "nodes": [_no("r1", "opc_read", 1, tag_id=tag_id), _no("m1", "mpc", 2, **_mpc_data())],
        "edges": [_aresta("r1", "out", "m1", "cv_a", "e1")],
    }
    r = await client.put(
        f"/api/flows/{flow['id']}", json={"graph_json": graph}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    return flow["id"], "m1"


def _ssto_row(
    flow_id: int, block_id: str, offset_s: int = 0, run_id: str = "run-1"
) -> dict[str, Any]:
    """Uma linha completa de `ssto_runs` — vetores JSONB pequenos mas com a forma real."""
    return {
        "ts": BASE.astimezone(UTC).replace(second=offset_s),
        "flow_id": flow_id,
        "block_id": block_id,
        "run_id": run_id,
        "config_hash": "a" * 64,
        "model_hash": "b" * 64,
        "status": "optimal",
        "solver": "highs",
        "solve_ms": 3.5,
        "objective": -12.5,
        "mv": {"mv_a": 40.0},
        "cv_ss": {"cv_a": 95.0},
        "bias": {"cv_a": 1.5},
        "dv": {},
        "costs": {"mv_a": -1.0},
        "delta_mv": {"mv_a": 5.0},
        "mv_target": {"mv_a": 45.0},
        "cv_target": {"cv_a": 100.0},
        "given_up": [],
        "active_constraints": ["cv_a:high"],
        "duals": {"cv_a:high": 0.25},
    }


# ---------------------------------------------------------------------------- testes


async def test_sem_execucao_devolve_null(client, admin_headers, operator_headers):
    """Bloco que nunca rodou o SSTO: 200 com `null` (não 404 — o recurso é a última
    execução, inexistente por enquanto)."""
    flow_id, block_id = await _cenario(client, admin_headers, "SstoLastVazio")

    r = await client.get(
        f"/api/history/ssto/last?flow_id={flow_id}&block_id={block_id}",
        headers=operator_headers,
    )

    assert r.status_code == 200, r.text
    assert r.json() is None


async def test_devolve_a_execucao_mais_recente(client, admin_headers, operator_headers, db_session):
    flow_id, block_id = await _cenario(client, admin_headers, "SstoLastRecente")
    antiga = _ssto_row(flow_id, block_id, offset_s=0, run_id="run-antiga")
    recente = _ssto_row(flow_id, block_id, offset_s=10, run_id="run-recente")
    # Outra chave (flow, block) não pode vazar na resposta.
    outra = _ssto_row(flow_id + 999, "outro", offset_s=20, run_id="run-alheia")
    await db_session.execute(insert(ssto_runs), [antiga, recente, outra])
    await db_session.commit()  # SAVEPOINT do conftest raiz — não vaza

    r = await client.get(
        f"/api/history/ssto/last?flow_id={flow_id}&block_id={block_id}",
        headers=operator_headers,
    )

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["run"]["run_id"] == "run-recente"
    assert corpo["run"]["mv_target"] == {"mv_a": 45.0}
    assert corpo["run"]["cv_target"] == {"cv_a": 100.0}
    assert corpo["run"]["status"] == "optimal"
    assert corpo["run"]["objective"] == -12.5
    assert corpo["run"]["config_hash"] == "a" * 64
    assert corpo["run"]["active_constraints"] == ["cv_a:high"]
    assert corpo["ts"].startswith("2026-08-11T12:00:10")


async def test_flow_inexistente_404(client, operator_headers):
    r = await client.get(
        "/api/history/ssto/last?flow_id=999999&block_id=m1", headers=operator_headers
    )

    assert r.status_code == 404, r.text


async def test_bloco_inexistente_422(client, admin_headers, operator_headers):
    flow_id, _block_id = await _cenario(client, admin_headers, "SstoLastBloco404")

    r = await client.get(
        f"/api/history/ssto/last?flow_id={flow_id}&block_id=nope",
        headers=operator_headers,
    )

    assert r.status_code == 422, r.text
    assert "não encontrado" in r.json()["detail"]


async def test_bloco_nao_e_mpc_422(client, admin_headers, operator_headers):
    flow_id, _block_id = await _cenario(client, admin_headers, "SstoLastNaoMpc")

    r = await client.get(
        f"/api/history/ssto/last?flow_id={flow_id}&block_id=r1",
        headers=operator_headers,
    )

    assert r.status_code == 422, r.text
    assert "não é um bloco MPC" in r.json()["detail"]


async def test_anonimo_401(client):
    r = await client.get("/api/history/ssto/last?flow_id=1&block_id=m1")

    assert r.status_code == 401, r.text
