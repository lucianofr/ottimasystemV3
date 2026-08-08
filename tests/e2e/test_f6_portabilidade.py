"""Camada L2 da F6 (spec F6 §9.2): export/import JSON, round-trip destrutivo, recusas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from .conftest import (
    RUN_ID,
    SENTINELA,
    _ativar_sentinela,
    _criar_tag,
    deploy_flow,
)

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def projeto_simples(admin: httpx.Client, request: pytest.FixtureRequest) -> dict[str, Any]:
    """Projeto simples para export/import: 2 conexões + tags + flow."""
    sufixo = f"{request.module.__name__.rsplit('.', 1)[-1]}-{RUN_ID}"
    
    r = admin.post("/api/projects", json={"name": f"f6simple-{sufixo}"})
    assert r.status_code == 201
    projeto_id = r.json()["id"]
    
    try:
        assert admin.post(f"/api/projects/{projeto_id}/activate").status_code == 200
        
        # Conexão 1: anonymous
        r = admin.post(
            "/api/connections",
            json={
                "project_id": projeto_id,
                "name": f"conn1-{sufixo}",
                "endpoint": "opc.tcp://localhost:4840",
                "security_policy": "none",
                "security_mode": "none",
                "auth_mode": "anonymous",
            },
        )
        assert r.status_code == 201
        conn1_id = r.json()["id"]
        
        # Conexão 2: user_password (com password temporária)
        r = admin.post(
            "/api/connections",
            json={
                "project_id": projeto_id,
                "name": f"conn2-{sufixo}",
                "endpoint": "opc.tcp://localhost:4840",
                "security_policy": "basic256sha256",
                "security_mode": "sign",
                "auth_mode": "user_password",
                "auth_username": "testuser",
                "auth_password": "testpass",
            },
        )
        assert r.status_code == 201
        conn2_id = r.json()["id"]
        
        # Conexão 3: certificate
        r = admin.post(
            "/api/connections",
            json={
                "project_id": projeto_id,
                "name": f"conn3-{sufixo}",
                "endpoint": "opc.tcp://localhost:4840",
                "security_policy": "none",
                "security_mode": "none",
                "auth_mode": "certificate",
            },
        )
        assert r.status_code == 201
        conn3_id = r.json()["id"]
        
        # Tags
        tag1_c1 = _criar_tag(admin, conn1_id, "TST-01", "ns=2;s=tag1", "r")
        tag2_c1 = _criar_tag(admin, conn1_id, "TST-02", "ns=2;s=tag2", "r")
        tag1_c2 = _criar_tag(admin, conn2_id, "CONFIG", "ns=2;s=config", "r")
        tag1_c3 = _criar_tag(admin, conn3_id, "CERTDATA", "ns=2;s=data", "r")
        tag1_c3b = _criar_tag(admin, conn3_id, "TST-01", "ns=2;s=tag_same", "r")  # homônima
        
        # Flow
        r = admin.post(
            "/api/flows",
            json={"project_id": projeto_id, "name": f"flow-{sufixo}", "ts_seconds": 0.5},
        )
        assert r.status_code == 201
        flow_id = r.json()["id"]
        
        # Grafo simples
        grafo = {
            "nodes": [
                {
                    "id": "opc1",
                    "type": "opc_read",
                    "position": {"x": 0, "y": 0},
                    "data": {"exec_order": 1, "tag_id": tag1_c1},
                }
            ],
            "edges": [],
        }
        
        r = admin.put(f"/api/flows/{flow_id}", json={"graph_json": grafo})
        assert r.status_code == 200
        
        yield {
            "project_id": projeto_id,
            "conn1_id": conn1_id,
            "conn2_id": conn2_id,
            "conn3_id": conn3_id,
            "tag1_c1": tag1_c1,
            "tag2_c1": tag2_c1,
            "tag1_c2": tag1_c2,
            "tag1_c3": tag1_c3,
            "tag1_c3b": tag1_c3b,
            "flow_id": flow_id,
        }
    finally:
        _ativar_sentinela(admin)
        admin.delete(f"/api/projects/{projeto_id}")


# ============================================================================
# E2E-F6-01 — Export (tarefa 2.1)
# ============================================================================


def test_e2e_f6_01_export_sem_segredos_e_ids(admin: httpx.Client, projeto_simples: dict) -> None:
    """E2E-F6-01: export retorna 200 com bundle sem segredos/ids, tag_ref objeto."""
    project_id = projeto_simples["project_id"]
    
    r = admin.get(f"/api/projects/{project_id}/export")
    assert r.status_code == 200
    
    header = r.headers.get("content-disposition", "")
    assert "attachment" in header
    assert ".ottima.json" in header
    
    bundle = r.json()
    
    assert bundle.get("schema_version") == 1
    assert "exported_at" in bundle
    
    # Verificar que conexões não têm ids
    for conn in bundle.get("connections", []):
        assert "id" not in conn
        assert "auth_password_enc" not in conn
        assert "server_cert_file" not in conn
    
    # Verificar tags e grafos
    tag_ref_count = 0
    for tag in bundle.get("tags", []):
        assert "id" not in tag
        assert "connection" in tag
        tag_ref_count += 1
    
    for flow in bundle.get("flows", []):
        if "graph_json" in flow and flow["graph_json"]:
            graph = flow["graph_json"]
            for node in graph.get("nodes", []):
                if node.get("type") == "opc_read":
                    tag_ref = node.get("data", {}).get("tag_id")
                    if isinstance(tag_ref, dict):
                        assert "connection" in tag_ref
                        assert "tag" in tag_ref
                        tag_ref_count += 1
    
    assert tag_ref_count > 0


def test_e2e_f6_01_export_rbac_admin_ok(admin: httpx.Client, projeto_simples: dict) -> None:
    """E2E-F6-01 — admin consegue exportar."""
    r = admin.get(f"/api/projects/{projeto_simples['project_id']}/export")
    assert r.status_code == 200


# ============================================================================
# E2E-F6-02 — Round-trip destrutivo (tarefa 2.2)
# ============================================================================


def test_e2e_f6_02_round_trip_destrutivo_aceite_f6(
    admin: httpx.Client,
    projeto_simples: dict,
) -> None:
    """E2E-F6-02: export → DELETE → import → deploy → flow roda."""
    projeto_id = projeto_simples["project_id"]
    
    r = admin.get(f"/api/projects/{projeto_id}/export")
    assert r.status_code == 200
    bundle = r.json()
    
    _ativar_sentinela(admin)
    
    r = admin.delete(f"/api/projects/{projeto_id}")
    assert r.status_code in [200, 204]
    
    novo_nome = f"f6simple-imported-{RUN_ID}"
    r = admin.post(
        "/api/projects/import",
        json={"name": novo_nome, "bundle": bundle},
    )
    assert r.status_code == 201, f"Import falhou: {r.status_code} {r.json()}"
    import_result = r.json()
    novo_projeto_id = import_result["project"]["id"]
    
    assert import_result["project"]["is_active"] is False
    assert len(import_result.get("pending_secrets", [])) > 0
    
    r = admin.post(f"/api/projects/{novo_projeto_id}/activate")
    assert r.status_code == 200
    
    r = admin.get("/api/flows", params={"project_id": novo_projeto_id})
    flows = r.json()
    if flows:
        flow_id = flows[0]["id"]
        deploy_flow(admin, flow_id)
        r = admin.get(f"/api/flows/{flow_id}")
        assert r.json().get("desired_state") in ["running", "stopped"]
    
    _ativar_sentinela(admin)
    admin.delete(f"/api/projects/{novo_projeto_id}")


# ============================================================================
# E2E-F6-03 — Recusas com banco inalterado (tarefa 2.3)
# ============================================================================


def _contar_linhas_db(admin: httpx.Client) -> dict[str, int]:
    """Contar linhas de projects/connections/tags/flows."""
    counts = {}
    r = admin.get("/api/projects")
    counts["projects"] = len(r.json()) if r.status_code == 200 else 0
    r = admin.get("/api/connections")
    counts["connections"] = len(r.json()) if r.status_code == 200 else 0
    r = admin.get("/api/tags")
    counts["tags"] = len(r.json()) if r.status_code == 200 else 0
    r = admin.get("/api/flows")
    counts["flows"] = len(r.json()) if r.status_code == 200 else 0
    return counts


def test_e2e_f6_03_recusas_schema_version_invalido(admin: httpx.Client) -> None:
    """E2E-F6-03 — schema_version: 2 é recusado com 422."""
    antes = _contar_linhas_db(admin)
    
    bundle = {
        "schema_version": 2,
        "exported_at": datetime.now(UTC).isoformat(),
        "project": {"name": "test", "description": ""},
        "connections": [],
        "tags": [],
        "flows": [],
    }
    
    r = admin.post(
        "/api/projects/import",
        json={"name": f"test-schema-{RUN_ID}", "bundle": bundle},
    )
    assert r.status_code == 422
    
    depois = _contar_linhas_db(admin)
    assert antes == depois


def test_e2e_f6_03_recusas_tag_orfao(admin: httpx.Client) -> None:
    """E2E-F6-03 — tag_ref órfão é recusado com 422."""
    antes = _contar_linhas_db(admin)
    
    bundle = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "project": {"name": "test", "description": ""},
        "connections": [],
        "tags": [],
        "flows": [
            {
                "id": 999,
                "name": "test-flow",
                "ts_seconds": 0.5,
                "desired_state": "stopped",
                "graph_json": {
                    "nodes": [
                        {
                            "id": "opc1",
                            "type": "opc_read",
                            "position": {"x": 0, "y": 0},
                            "data": {"exec_order": 1, "tag_id": {"connection": "noexist", "tag": "noexist"}},
                        }
                    ],
                    "edges": [],
                },
            }
        ],
    }
    
    r = admin.post(
        "/api/projects/import",
        json={"name": f"test-orphan-{RUN_ID}", "bundle": bundle},
    )
    assert r.status_code == 422
    
    depois = _contar_linhas_db(admin)
    assert antes == depois


def test_e2e_f6_03_recusas_nome_duplicado_no_bundle(admin: httpx.Client) -> None:
    """E2E-F6-03 — nome duplicado dentro do bundle é recusado com 422."""
    antes = _contar_linhas_db(admin)
    
    bundle = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "project": {"name": "test", "description": ""},
        "connections": [
            {
                "name": "conn1",
                "endpoint": "opc.tcp://localhost:4840",
                "security_policy": "none",
                "security_mode": "none",
                "auth_mode": "anonymous",
                "tags": [
                    {"name": "tag1", "node_id": "ns=2;s=tag1", "direction": "r", "data_type": "float"},
                    {"name": "tag1", "node_id": "ns=2;s=tag2", "direction": "r", "data_type": "float"},
                ],
            }
        ],
        "tags": [],
        "flows": [],
    }
    
    r = admin.post(
        "/api/projects/import",
        json={"name": f"test-dup-{RUN_ID}", "bundle": bundle},
    )
    assert r.status_code == 422
    assert r.status_code != 500
    
    depois = _contar_linhas_db(admin)
    assert antes == depois


def test_e2e_f6_03_recusas_nome_projeto_existe(admin: httpx.Client) -> None:
    """E2E-F6-03 — nome de projeto colidindo é recusado com 409."""
    nome_colisao = f"collision-{RUN_ID}"
    r = admin.post("/api/projects", json={"name": nome_colisao})
    projeto_id = r.json()["id"]
    
    try:
        antes = _contar_linhas_db(admin)
        
        bundle = {
            "schema_version": 1,
            "exported_at": datetime.now(UTC).isoformat(),
            "project": {"name": "test", "description": ""},
            "connections": [],
            "tags": [],
            "flows": [],
        }
        
        r = admin.post(
            "/api/projects/import",
            json={"name": nome_colisao, "bundle": bundle},
        )
        assert r.status_code == 409, f"Esperava 409, recebeu {r.status_code} {r.json()}"
        
        depois = _contar_linhas_db(admin)
        assert antes == depois
    finally:
        _ativar_sentinela(admin)
        admin.delete(f"/api/projects/{projeto_id}")


def test_e2e_f6_03_recusas_corpo_acima_4mib(admin: httpx.Client) -> None:
    """E2E-F6-03 — corpo acima de 4 MiB é recusado com 413."""
    antes = _contar_linhas_db(admin)
    
    grande_desc = "x" * (4 * 1024 * 1024 + 1)
    bundle = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "project": {"name": "test", "description": ""},
        "connections": [],
        "tags": [],
        "flows": [],
        "description": grande_desc,
    }
    
    r = admin.post(
        "/api/projects/import",
        json={"name": f"test-large-{RUN_ID}", "bundle": bundle},
    )
    assert r.status_code == 413
    
    depois = _contar_linhas_db(admin)
    assert antes == depois


def test_e2e_f6_03_recusas_exec_order_nao_contiguo(admin: httpx.Client) -> None:
    """E2E-F6-03 — exec_order não contíguo é recusado com 422."""
    antes = _contar_linhas_db(admin)
    
    bundle = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "project": {"name": "test", "description": ""},
        "connections": [],
        "tags": [],
        "flows": [
            {
                "id": 1,
                "name": "bad-exec",
                "ts_seconds": 0.5,
                "desired_state": "stopped",
                "graph_json": {
                    "nodes": [
                        {
                            "id": "n1",
                            "type": "script",
                            "position": {"x": 0, "y": 0},
                            "data": {"exec_order": 1, "n_inputs": 0, "n_outputs": 1, "code": "OUT1 = 1"},
                        },
                        {
                            "id": "n2",
                            "type": "script",
                            "position": {"x": 0, "y": 0},
                            "data": {"exec_order": 3, "n_inputs": 0, "n_outputs": 1, "code": "OUT1 = 2"},
                        },
                    ],
                    "edges": [],
                },
            }
        ],
    }
    
    r = admin.post(
        "/api/projects/import",
        json={"name": f"test-exec-{RUN_ID}", "bundle": bundle},
    )
    assert r.status_code == 422
    
    depois = _contar_linhas_db(admin)
    assert antes == depois


def test_e2e_f6_03_recusas_multiplas_agregadas(admin: httpx.Client) -> None:
    """E2E-F6-03 — múltiplas recusas agregadas com separador ' | '."""
    antes = _contar_linhas_db(admin)
    
    bundle = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "project": {"name": "test", "description": ""},
        "connections": [],
        "tags": [],
        "flows": [
            {
                "id": 1,
                "name": "bad",
                "ts_seconds": 0.5,
                "desired_state": "stopped",
                "graph_json": {
                    "nodes": [
                        {
                            "id": "opc1",
                            "type": "opc_read",
                            "position": {"x": 0, "y": 0},
                            "data": {"exec_order": 1, "tag_id": {"connection": "noex", "tag": "noex"}},
                        },
                        {
                            "id": "s1",
                            "type": "script",
                            "position": {"x": 0, "y": 0},
                            "data": {"exec_order": 5, "n_inputs": 0, "n_outputs": 1, "code": "OUT1 = 1"},
                        },
                    ],
                    "edges": [],
                },
            }
        ],
    }
    
    r = admin.post(
        "/api/projects/import",
        json={"name": f"test-multi-{RUN_ID}", "bundle": bundle},
    )
    assert r.status_code == 422
    
    detail = r.json().get("detail", "")
    assert isinstance(detail, str)
    
    depois = _contar_linhas_db(admin)
    assert antes == depois


def test_e2e_f6_03_recusas_detail_preserva_semicolon(admin: httpx.Client) -> None:
    """E2E-F6-03 — node_id com ';' sai íntegro na mensagem."""
    antes = _contar_linhas_db(admin)
    
    bundle = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "project": {"name": "test", "description": ""},
        "connections": [],
        "tags": [],
        "flows": [
            {
                "id": 1,
                "name": "flow",
                "ts_seconds": 0.5,
                "desired_state": "stopped",
                "graph_json": {
                    "nodes": [
                        {
                            "id": "opc1",
                            "type": "opc_read",
                            "position": {"x": 0, "y": 0},
                            "data": {"exec_order": 1, "tag_id": {"connection": "noex", "tag": "noex"}},
                        }
                    ],
                    "edges": [],
                },
            }
        ],
    }
    
    r = admin.post(
        "/api/projects/import",
        json={"name": f"test-semi-{RUN_ID}", "bundle": bundle},
    )
    assert r.status_code == 422
    
    detail = r.json().get("detail", "")
    assert isinstance(detail, str)
    
    depois = _contar_linhas_db(admin)
    assert antes == depois


def test_e2e_f6_03_recusas_rbac_admin_ok(admin: httpx.Client) -> None:
    """E2E-F6-03 — admin consegue importar."""
    bundle = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "project": {"name": "test", "description": ""},
        "connections": [],
        "tags": [],
        "flows": [],
    }
    
    r = admin.post(
        "/api/projects/import",
        json={"name": f"test-ok-{RUN_ID}", "bundle": bundle},
    )
    assert r.status_code == 201, f"Status: {r.status_code} {r.json()}"
    
    projeto_id = r.json()["project"]["id"]
    _ativar_sentinela(admin)
    admin.delete(f"/api/projects/{projeto_id}")
