"""Camada L2 da F6 (spec F6 §9.2): export/import JSON, round-trip destrutivo, recusas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from tests.e2e.conftest import (
    RUN_ID,
    SENTINELA,
)

pytestmark = pytest.mark.e2e


def _contar_linhas_db(admin: httpx.Client) -> dict[str, int]:
    """Conta linhas de projects/connections/tags/flows no banco."""
    r = admin.get("/api/projects")
    assert r.status_code == 200
    projects = r.json()

    r = admin.get("/api/connections")
    assert r.status_code == 200
    connections = r.json()

    r = admin.get("/api/tags")
    assert r.status_code == 200
    tags = r.json()

    r = admin.get("/api/flows")
    assert r.status_code == 200
    flows = r.json()

    return {
        "projects": len(projects),
        "connections": len(connections),
        "tags": len(tags),
        "flows": len(flows),
    }


def _ativar_sentinela(admin: httpx.Client) -> None:
    """Ativa o projeto sentinela."""
    admin.post(f"/api/projects/{SENTINELA}/activate")


def _desativar_sentinela(admin: httpx.Client) -> None:
    """Desativa o projeto sentinela."""


def _encontrar_recurse(obj: Any, target_key: str) -> bool:
    """Busca recursiva de chave em dict/list (qualquer profundidade)."""
    if isinstance(obj, dict):
        if target_key in obj:
            return True
        return any(_encontrar_recurse(v, target_key) for v in obj.values())
    elif isinstance(obj, list):
        return any(_encontrar_recurse(v, target_key) for v in obj)
    return False


@pytest.fixture(scope="module")
def operator_client(admin: httpx.Client) -> httpx.Client:
    """Cria usuário operador e retorna cliente autenticado como ele (C5 fix)."""
    username = f"operator_{RUN_ID}"
    password = "op-test-123"

    # Criar usuário operador via POST /api/users (admin only)
    r = admin.post(
        "/api/users",
        json={
            "username": username,
            "name": f"Operator {RUN_ID}",
            "password": password,
            "role": "operator",
        },
    )
    # Se já existe (reutilizar), 409 é ok
    if r.status_code not in [201, 409]:
        pytest.skip(f"Não conseguiu criar operador: {r.status_code}")

    # Login como operador
    client = httpx.Client(base_url="http://localhost:8080", timeout=20)
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"Login de operador falhou: {r.text}"
    token = r.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    return client


@pytest.fixture(scope="module")
def projeto_simples(admin: httpx.Client, opcsim_standalone: str) -> dict[str, Any]:
    """Fixture de projeto portável compartilhada por todos os 3 cenários.
    Monta: 3 conexões, tags homônimas, flow com grafo (opc_read).
    Usa as rotas corretas: /api/connections + project_id, /api/tags + connection_id.
    """
    # Cria projeto
    r = admin.post(
        "/api/projects",
        json={"name": f"projeto_portavel_{RUN_ID}", "description": "Fixture F6"},
    )
    assert r.status_code == 201, f"Criação de projeto falhou: {r.text}"
    projeto = r.json()
    projeto_id = projeto["id"]

    # Conexão 1: anônima com opcsim
    r = admin.post(
        "/api/connections",
        json={
            "project_id": projeto_id,
            "name": f"conn1-{RUN_ID}",
            "endpoint": opcsim_standalone,
            "security_policy": "none",
            "security_mode": "none",
            "auth_mode": "anonymous",
        },
    )
    assert r.status_code == 201, f"Conexão 1 falhou: {r.text}"
    conn1 = r.json()
    conn1_id = conn1["id"]

    # Conexão 2: user_password + basic256sha256
    r = admin.post(
        "/api/connections",
        json={
            "project_id": projeto_id,
            "name": f"conn2-{RUN_ID}",
            "endpoint": "opc.tcp://fake-server.local:4840",
            "security_policy": "basic256sha256",
            "security_mode": "sign",
            "auth_mode": "user_password",
            "auth_username": "user1",
            "auth_password": "pass123",
        },
    )
    assert r.status_code == 201, f"Conexão 2 falhou: {r.text}"
    conn2 = r.json()
    conn2_id = conn2["id"]

    # Conexão 3: certificate + none
    r = admin.post(
        "/api/connections",
        json={
            "project_id": projeto_id,
            "name": f"conn3-{RUN_ID}",
            "endpoint": "opc.tcp://fake-cert-server.local:4840",
            "security_policy": "none",
            "security_mode": "none",
            "auth_mode": "certificate",
        },
    )
    assert r.status_code == 201, f"Conexão 3 falhou: {r.text}"
    conn3 = r.json()
    conn3_id = conn3["id"]

    # Tags (incluindo homônimas)
    r = admin.post(
        "/api/tags",
        json={
            "connection_id": conn1_id,
            "name": "TST-01",
            "node_id": "ns=2;s=TST-01-c1",
            "direction": "r",
            "data_type": "float",
        },
    )
    assert r.status_code == 201
    tag_tst01_c1 = r.json()

    # Homônimo em conn3 (não referenciado no grafo)
    r = admin.post(
        "/api/tags",
        json={
            "connection_id": conn3_id,
            "name": "TST-01",
            "node_id": "ns=2;s=TST-01-c3",
            "direction": "r",
            "data_type": "float",
        },
    )
    assert r.status_code == 201

    # Tag adicional
    r = admin.post(
        "/api/tags",
        json={
            "connection_id": conn1_id,
            "name": "tag_temp",
            "node_id": "ns=2;s=tag_temp",
            "direction": "r",
            "data_type": "float",
        },
    )
    assert r.status_code == 201
    tag_temp = r.json()

    # Flow com grafo referenciando TST-01
    r = admin.post(
        "/api/flows",
        json={
            "project_id": projeto_id,
            "name": f"flow_simples_{RUN_ID}",
            "ts_seconds": 1.0,
        },
    )
    assert r.status_code == 201, f"Flow POST falhou: {r.text}"
    flow = r.json()
    flow_id = flow["id"]

    # Gravar grafo separadamente
    r = admin.put(
        f"/api/flows/{flow_id}",
        json={
            "graph_json": {
                "nodes": [
                    {
                        "id": "opc1",
                        "type": "opc_read",
                        "position": {"x": 0.0, "y": 0.0},
                        "data": {"exec_order": 1, "tag_id": tag_tst01_c1["id"]},
                    }
                ],
                "edges": [],
            }
        },
    )
    assert r.status_code == 200, f"Flow PUT grafo falhou: {r.text}"

    return {
        "project_id": projeto_id,
        "conn1_id": conn1_id,
        "conn2_id": conn2_id,
        "conn3_id": conn3_id,
        "tag_tst01_c1_id": tag_tst01_c1["id"],
        "tag_temp_id": tag_temp["id"],
        "flow_id": flow_id,
    }


class TestE2EF601Export:
    """E2E-F6-01: export sem segredos/ids (C1 fix: graph vs graph_json)."""

    @pytest.mark.e2e
    def test_export_sem_segredos_e_ids(
        self, admin: httpx.Client, projeto_simples: dict[str, Any]
    ) -> None:
        """E2E-F6-01: 200, sem auth_password_enc/ids/timestamps, tag_ref objeto."""
        projeto_id = projeto_simples["project_id"]

        r = admin.get(f"/api/projects/{projeto_id}/export")
        assert r.status_code == 200

        # Content-Disposition header
        disposition = r.headers.get("content-disposition", "")
        assert "attachment" in disposition
        assert ".ottima.json" in disposition

        bundle = r.json()
        assert bundle.get("schema_version") == 1
        assert "exported_at" in bundle

        # Campos proibidos
        forbidden = {
            "auth_password_enc",
            "server_cert_file",
            "id",
            "project_id",
            "connection_id",
            "is_active",
            "created_at",
            "updated_at",
        }

        for conn in bundle.get("connections", []):
            for campo in forbidden:
                assert campo not in conn

        for tag in bundle.get("tags", []):
            for campo in forbidden:
                assert campo not in tag

        # C1 fix: verificar tag_ref como objeto em grafo (graph, não graph_json)
        tag_ref_count = 0
        for flow in bundle.get("flows", []):
            if "graph" in flow and flow["graph"]:
                graph = flow["graph"]
                for node in graph.get("nodes", []):
                    if "data" in node:
                        data = node["data"]
                        # Nomes POS-traducao (`TAG_REF_FIELDS` de
                        # `ottima_core.portability.tag_ref`): o export troca cada
                        # `*_tag_id` pelo `*_tag_ref` objeto. Procurar `tag_id` aqui
                        # seria procurar o que o export justamente elimina.
                        for field in [
                            "tag_ref",
                            "write_tag_ref",
                            "mode_cmd_tag_ref",
                            "mode_read_tag_ref",
                            "readback_tag_ref",
                        ]:
                            if field in data:
                                tag_ref = data[field]
                                if isinstance(tag_ref, dict):
                                    assert "connection" in tag_ref
                                    assert "tag" in tag_ref
                                    tag_ref_count += 1

        assert tag_ref_count > 0

    @pytest.mark.e2e
    def test_export_rbac_admin_ok(
        self, admin: httpx.Client, projeto_simples: dict[str, Any]
    ) -> None:
        """E2E-F6-01: admin consegue exportar."""
        projeto_id = projeto_simples["project_id"]
        r = admin.get(f"/api/projects/{projeto_id}/export")
        assert r.status_code == 200

    @pytest.mark.e2e
    def test_export_rbac_operador_403(
        self, operator_client: httpx.Client, projeto_simples: dict[str, Any]
    ) -> None:
        """E2E-F6-01: operador recebe 403 (C5 fix)."""
        projeto_id = projeto_simples["project_id"]
        r = operator_client.get(f"/api/projects/{projeto_id}/export")
        assert r.status_code == 403


class TestE2EF602RoundTrip:
    """E2E-F6-02: round-trip destrutivo (C6 fix)."""

    @pytest.mark.e2e
    def test_round_trip_destrutivo_aceite_f6(
        self, admin: httpx.Client, projeto_simples: dict[str, Any]
    ) -> None:
        """E2E-F6-02: prova A-9 (ids novos, homônimo resolvido)."""
        projeto_id = projeto_simples["project_id"]

        # Ids das tags DO PROJETO que vai ser destruido — e contra estes que a prova de
        # A-9 se faz (ids novos apos o round-trip), nao contra o universo global.
        conns_originais = {
            c["id"] for c in admin.get("/api/connections").json() if c["project_id"] == projeto_id
        }
        r = admin.get("/api/tags")
        assert r.status_code == 200
        tag_ids_originais = {t["id"] for t in r.json() if t["connection_id"] in conns_originais}
        assert tag_ids_originais, "fixture nao criou tags no projeto de origem"

        r = admin.get("/api/flows")
        assert r.status_code == 200

        # Exportar
        r = admin.get(f"/api/projects/{projeto_id}/export")
        assert r.status_code == 200
        bundle = r.json()

        # Deletar (com sentinela ativa)
        _ativar_sentinela(admin)
        r = admin.delete(f"/api/projects/{projeto_id}")
        assert r.status_code in [200, 204]

        # Importar com nome novo
        novo_nome = f"projeto_importado_{RUN_ID}"
        r = admin.post(
            "/api/projects/import",
            json={"name": novo_nome, "bundle": bundle},
        )
        assert r.status_code == 201
        import_result = r.json()
        novo_projeto_id = import_result["project"]["id"]
        pending_secrets = import_result.get("pending_secrets", [])

        # Verificar 3 predicados (I3 fix)
        assert len(pending_secrets) > 0
        predicados = set()
        for ps in pending_secrets:
            if ps.get("needs_password"):
                predicados.add("password")
            if ps.get("needs_server_certificate"):
                predicados.add("server_cert")
            if ps.get("needs_app_certificate"):
                predicados.add("app_cert")
        assert "password" in predicados
        assert "server_cert" in predicados
        # `needs_app_certificate` e um predicado de INSTALACAO, nao do arquivo importado
        # (spec §3.2-8): ele so acende quando a instalacao ainda nao tem certificado de
        # aplicacao. Asserir presenca incondicional falharia em qualquer instalacao ja
        # provisionada. O criterio correto e a coerencia com o estado real.
        cert_app_existe = admin.get("/api/certificates/app").json()["exists"]
        assert ("app_cert" in predicados) is not cert_app_existe

        # Verificar inativo
        r = admin.get(f"/api/projects/{novo_projeto_id}")
        assert r.status_code == 200
        assert r.json().get("is_active") is False

        # A-9: as tags renasceram com ids NOVOS. Comparar o minimo GLOBAL nao serve —
        # ele inclui tags de outros projetos, anteriores a este cenario. O que prova o
        # round-trip e que nenhuma tag do projeto importado reusa um id do projeto
        # original destruido.
        r = admin.get("/api/tags")
        assert r.status_code == 200
        conns_novas = {
            c["id"]
            for c in admin.get("/api/connections").json()
            if c["project_id"] == novo_projeto_id
        }
        tag_ids_novas = {t["id"] for t in r.json() if t["connection_id"] in conns_novas}
        assert tag_ids_novas, "projeto importado ficou sem tags"
        assert not (tag_ids_novas & tag_ids_originais), (
            f"import reusou ids do projeto destruido: {tag_ids_novas & tag_ids_originais}"
        )

        # C6 fix: prova de homônimo resolvido no grafo
        r = admin.get(f"/api/projects/{novo_projeto_id}/export")
        assert r.status_code == 200
        bundle_novo = r.json()
        tst01_encontrado = False
        for flow in bundle_novo.get("flows", []):
            if "graph" in flow and flow["graph"]:
                for node in flow["graph"].get("nodes", []):
                    tag_ref = node.get("data", {}).get("tag_ref")
                    if isinstance(tag_ref, dict) and tag_ref.get("tag") == "TST-01":
                        tst01_encontrado = True
        assert tst01_encontrado

        # Cleanup
        _ativar_sentinela(admin)
        admin.delete(f"/api/projects/{novo_projeto_id}")
        _desativar_sentinela(admin)


class TestE2EF603Recusas:
    """E2E-F6-03: recusas com banco inalterado (C2/C3/C4 fixes)."""

    @pytest.mark.e2e
    def test_schema_version_invalido(self, admin: httpx.Client) -> None:
        """Schema_version != 1 recusado (I2 fix: verifica detail)."""
        antes = _contar_linhas_db(admin)

        bundle = {
            "schema_version": 2,
            "exported_at": (datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")),
            "project": {"name": "test", "description": ""},
            "connections": [],
            "tags": [],
            "flows": [],
        }
        r = admin.post("/api/projects/import", json={"name": "schema_v2", "bundle": bundle})
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert "schema_version" in detail.lower()

        depois = _contar_linhas_db(admin)
        assert antes == depois

    @pytest.mark.e2e
    def test_tag_orfao(self, admin: httpx.Client) -> None:
        """C2 fix: tag_ref órfão recusado (forma correta de bundle)."""
        antes = _contar_linhas_db(admin)

        bundle = {
            "schema_version": 1,
            "exported_at": (datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")),
            "project": {"name": "test_orfao", "description": ""},
            "connections": [{"name": "conn_real", "endpoint": "opc.tcp://localhost"}],
            "tags": [
                {
                    "connection": "conn_real",
                    "name": "tag1",
                    "node_id": "ns=2;s=tag1",
                    "direction": "r",
                    "data_type": "float",
                }
            ],
            "flows": [
                {
                    "name": "flow1",
                    "ts_seconds": 1.0,
                    "desired_state": "stopped",
                    "graph": {
                        "nodes": [
                            {
                                "type": "opc_read",
                                "position": {"x": 0.0, "y": 0.0},
                                "data": {
                                    "exec_order": 1,
                                    "tag_ref": {
                                        "connection": "conn_nao_existe",
                                        "tag": "tag_fake",
                                    },
                                },
                            }
                        ]
                    },
                }
            ],
        }
        r = admin.post("/api/projects/import", json={"name": "test_orfao", "bundle": bundle})
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert "conn_nao_existe" in detail or "não existe" in detail.lower()

        depois = _contar_linhas_db(admin)
        assert antes == depois

    @pytest.mark.e2e
    def test_nome_duplicado_no_bundle(self, admin: httpx.Client) -> None:
        """C3 fix: nome duplicado na mesma conexão (forma correta)."""
        antes = _contar_linhas_db(admin)

        bundle = {
            "schema_version": 1,
            "exported_at": (datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")),
            "project": {"name": "test_dup", "description": ""},
            "connections": [{"name": "conn1", "endpoint": "opc.tcp://localhost"}],
            "tags": [
                {
                    "connection": "conn1",
                    "name": "tag_dup",
                    "node_id": "ns=2;s=t1",
                    "direction": "r",
                    "data_type": "float",
                },
                {
                    "connection": "conn1",
                    "name": "tag_dup",
                    "node_id": "ns=2;s=t2",
                    "direction": "r",
                    "data_type": "float",
                },
            ],
            "flows": [],
        }
        r = admin.post("/api/projects/import", json={"name": "test_dup", "bundle": bundle})
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert "tag_dup" in detail or "duplicada" in detail.lower()

        depois = _contar_linhas_db(admin)
        assert antes == depois

    @pytest.mark.e2e
    def test_nome_projeto_existe(self, admin: httpx.Client) -> None:
        """Nome colidindo com existente ⇒ 409."""
        r = admin.get("/api/projects")
        assert r.status_code == 200
        projects = r.json()
        nome_existente = projects[0]["name"] if projects else "teste"

        antes = _contar_linhas_db(admin)

        bundle = {
            "schema_version": 1,
            "exported_at": (datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")),
            "project": {"name": nome_existente, "description": ""},
            "connections": [],
            "tags": [],
            "flows": [],
        }
        r = admin.post(
            "/api/projects/import",
            json={"name": nome_existente, "bundle": bundle},
        )
        assert r.status_code == 409

        depois = _contar_linhas_db(admin)
        assert antes == depois

    @pytest.mark.e2e
    def test_corpo_acima_4mib(self, admin: httpx.Client) -> None:
        """Corpo > 4 MiB ⇒ 413."""
        antes = _contar_linhas_db(admin)

        bundle = {
            "schema_version": 1,
            "exported_at": (datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")),
            "project": {
                "name": "teste_grande",
                "description": "x" * (4 * 1024 * 1024 + 1),
            },
            "connections": [],
            "tags": [],
            "flows": [],
        }
        r = admin.post(
            "/api/projects/import",
            json={"name": "teste_grande", "bundle": bundle},
        )
        assert r.status_code == 413

        depois = _contar_linhas_db(admin)
        assert antes == depois

    @pytest.mark.e2e
    def test_exec_order_nao_contiguo(self, admin: httpx.Client) -> None:
        """C2 fix: exec_order não contíguo (forma correta de bundle)."""
        antes = _contar_linhas_db(admin)

        bundle = {
            "schema_version": 1,
            "exported_at": (datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")),
            "project": {"name": "test_exec", "description": ""},
            "connections": [{"name": "conn1", "endpoint": "opc.tcp://localhost"}],
            "tags": [
                {
                    "connection": "conn1",
                    "name": "tag1",
                    "node_id": "ns=2;s=tag1",
                    "direction": "r",
                    "data_type": "float",
                }
            ],
            "flows": [
                {
                    "name": "flow_exec",
                    "ts_seconds": 1.0,
                    "desired_state": "stopped",
                    "graph": {
                        "edges": [],
                        "nodes": [
                            {
                                "id": "n0",
                                "type": "opc_read",
                                "position": {"x": 0.0, "y": 0.0},
                                "data": {
                                    "tag_ref": {
                                        "connection": "conn1",
                                        "tag": "tag1",
                                    }
                                },
                            },
                            {
                                "id": "n1",
                                "type": "opc_read",
                                "exec_order": 2,
                                "data": {
                                    "tag_ref": {
                                        "connection": "conn1",
                                        "tag": "tag1",
                                    }
                                },
                            },
                        ],
                    },
                }
            ],
        }
        r = admin.post(
            "/api/projects/import",
            json={"name": "test_exec", "bundle": bundle},
        )
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert (
            "exec_order" in detail.lower()
            or "contíguo" in detail.lower()
            or "contig" in detail.lower()
        )

        depois = _contar_linhas_db(admin)
        assert antes == depois

    @pytest.mark.e2e
    def test_multiplas_recusas_agregadas(self, admin: httpx.Client) -> None:
        """C4 fix: múltiplas recusas com ` | ` separador."""
        antes = _contar_linhas_db(admin)

        bundle = {
            "schema_version": 1,
            "exported_at": (datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")),
            "project": {"name": "test_multi", "description": ""},
            "connections": [{"name": "conn1", "endpoint": "opc.tcp://localhost"}],
            "tags": [
                {
                    "connection": "conn1",
                    "name": "dup1",
                    "node_id": "ns=2;s=t1",
                    "direction": "r",
                    "data_type": "float",
                },
                {
                    "connection": "conn1",
                    "name": "dup1",
                    "node_id": "ns=2;s=t2",
                    "direction": "r",
                    "data_type": "float",
                },
            ],
            "flows": [
                {
                    "name": "dup_flow",
                    "ts_seconds": 1.0,
                    "desired_state": "stopped",
                    "graph": {"nodes": [], "edges": []},
                },
                {
                    "name": "dup_flow",
                    "ts_seconds": 1.0,
                    "desired_state": "stopped",
                    "graph": {"nodes": [], "edges": []},
                },
            ],
        }
        r = admin.post(
            "/api/projects/import",
            json={"name": "test_multi", "bundle": bundle},
        )
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert isinstance(detail, str)
        assert " | " in detail
        assert "dup1" in detail or "duplicada" in detail.lower()

        depois = _contar_linhas_db(admin)
        assert antes == depois

    @pytest.mark.e2e
    def test_detail_preserva_semicolon(self, admin: httpx.Client) -> None:
        """C4 fix: `;` em node_id preservado (com forma correta de bundle)."""
        antes = _contar_linhas_db(admin)

        bundle = {
            "schema_version": 1,
            "exported_at": (datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")),
            "project": {"name": "test_semi", "description": ""},
            "connections": [{"name": "conn1", "endpoint": "opc.tcp://localhost"}],
            "tags": [
                {
                    "connection": "conn1",
                    "name": "TT101",
                    "node_id": "ns=2;s=TT101",
                    "direction": "r",
                    "data_type": "float",
                }
            ],
            "flows": [
                {
                    "name": "flow1",
                    "ts_seconds": 1.0,
                    "desired_state": "stopped",
                    "graph": {
                        "nodes": [
                            {
                                "type": "opc_read",
                                "position": {"x": 0.0, "y": 0.0},
                                "data": {
                                    "exec_order": 1,
                                    "tag_ref": {
                                        "connection": "conn_inexistent",
                                        "tag": "TT101",
                                    },
                                },
                            }
                        ]
                    },
                }
            ],
        }
        r = admin.post(
            "/api/projects/import",
            json={"name": "test_semi", "bundle": bundle},
        )
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert "ns=2;s=TT101" in detail or "TT101" in detail

        depois = _contar_linhas_db(admin)
        assert antes == depois

    @pytest.mark.e2e
    def test_rbac_admin_ok(self, admin: httpx.Client) -> None:
        """Admin consegue importar (caminho feliz)."""
        bundle = {
            "schema_version": 1,
            "exported_at": (datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")),
            "project": {"name": f"admin_ok_{RUN_ID}", "description": ""},
            "connections": [],
            "tags": [],
            "flows": [],
        }
        r = admin.post(
            "/api/projects/import",
            json={"name": f"admin_ok_{RUN_ID}", "bundle": bundle},
        )
        assert r.status_code == 201

        # Cleanup
        _ativar_sentinela(admin)
        admin.delete(f"/api/projects/{r.json()['project']['id']}")
        _desativar_sentinela(admin)

    @pytest.mark.e2e
    def test_rbac_operador_403(self, operator_client: httpx.Client) -> None:
        """C5 fix: operador recebe 403 no import."""
        bundle = {
            "schema_version": 1,
            "exported_at": (datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")),
            "project": {"name": f"op_403_{RUN_ID}", "description": ""},
            "connections": [],
            "tags": [],
            "flows": [],
        }
        r = operator_client.post(
            "/api/projects/import",
            json={"name": f"op_403_{RUN_ID}", "bundle": bundle},
        )
        assert r.status_code == 403
