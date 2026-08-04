"""Camada L2 do gate E2E da F1 (docs/specs/F1-testes-e2e.md): API contra o compose real."""

import os
import time
from collections.abc import Iterator

import httpx
import pytest

pytestmark = pytest.mark.e2e

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8080")
ADMIN_USER = os.environ.get("E2E_ADMIN_USERNAME", "admin")
ADMIN_PASS = os.environ.get("E2E_ADMIN_PASSWORD", "")

# Sufixo único por execução: o banco do stack é persistente, nada pode colidir com o run anterior
RUN_ID = f"{time.time_ns():x}"

# Projeto estável que recebe a ativação no fim dos testes (mesmo nome usado no E2E-16 do L3)
SENTINELA = "E2E sentinela (não excluir)"


@pytest.fixture(scope="module")
def admin() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BASE, timeout=10) as c:
        r = c.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        assert r.status_code == 200, "login do admin do seed falhou — confira deploy/.env"
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c


def _novo_nome(prefixo: str) -> str:
    return f"{prefixo}-{RUN_ID}-{time.monotonic_ns():x}"


def _ativo(admin: httpx.Client) -> dict | None:
    return next((p for p in admin.get("/api/projects").json() if p["is_active"]), None)


def _garantir_sentinela(admin: httpx.Client) -> dict:
    """A API não expõe "desativar" e excluir o ativo dá 409: um projeto sentinela estável recebe a
    ativação no fim do teste, em vez de deixar um projeto novo ativo a cada execução."""
    r = admin.post("/api/projects", json={"name": SENTINELA})
    if r.status_code == 201:
        return r.json()
    assert r.status_code == 409, f"criação da sentinela falhou: HTTP {r.status_code}"
    achado = next((p for p in admin.get("/api/projects").json() if p["name"] == SENTINELA), None)
    assert achado is not None, "sentinela reportada como duplicada mas ausente na listagem"
    return achado


def test_e2e11_rbac_e_sem_token(admin: httpx.Client):
    r = admin.post(
        "/api/users",
        json={
            "username": "operador-e2e",
            "name": "Operador E2E",
            "password": "operador-12345",
            "role": "operator",
        },
    )
    assert r.status_code in (201, 409)  # idempotente entre execuções
    with httpx.Client(base_url=BASE, timeout=10) as op:
        lr = op.post(
            "/api/auth/login", json={"username": "operador-e2e", "password": "operador-12345"}
        )
        assert lr.status_code == 200
        op.headers["Authorization"] = f"Bearer {lr.json()['access_token']}"
        assert op.get("/api/projects").status_code == 200  # operador enxerga tudo
        assert op.post("/api/projects", json={"name": _novo_nome("x")}).status_code == 403
        assert op.get("/api/users").status_code == 403  # gestão de usuários é admin
    assert httpx.get(f"{BASE}/api/projects", timeout=10).status_code == 401  # RF-003


def test_e2e12_guardas_de_usuario(admin: httpx.Client):
    me = admin.get("/api/auth/me").json()
    # auto-exclusão: sempre 409, independentemente de haver outros admins (spec §5.5)
    assert admin.delete(f"/api/users/{me['id']}").status_code == 409
    # com um segundo admin ativo no banco, o guarda de auto-gestão continua valendo:
    # a regra é "sobre o próprio usuário", não "sobre o último admin"
    extra = admin.post(
        "/api/users",
        json={
            "username": _novo_nome("adm"),
            "name": "Adm Extra",
            "password": "senha-12345678",
            "role": "admin",
        },
    )
    assert extra.status_code == 201
    extra_id = extra.json()["id"]
    try:
        assert admin.patch(f"/api/users/{me['id']}", json={"role": "operator"}).status_code == 409
        assert admin.patch(f"/api/users/{me['id']}", json={"is_active": False}).status_code == 409
    finally:
        assert admin.delete(f"/api/users/{extra_id}").status_code == 204  # limpeza


def test_e2e13_projetos_ativacao_unica(admin: httpx.Client):
    anterior = _ativo(admin)
    a = admin.post("/api/projects", json={"name": _novo_nome("proj-a")}).json()
    b = admin.post("/api/projects", json={"name": _novo_nome("proj-b")}).json()
    assert admin.post(f"/api/projects/{a['id']}/activate").status_code == 200
    assert admin.post(f"/api/projects/{b['id']}/activate").status_code == 200
    ativos = [p for p in admin.get("/api/projects").json() if p["is_active"]]
    assert len(ativos) == 1 and ativos[0]["id"] == b["id"]
    assert admin.delete(f"/api/projects/{b['id']}").status_code == 409  # ativo não se exclui
    assert admin.delete(f"/api/projects/{a['id']}").status_code == 204
    # limpeza: devolve a ativação a quem a tinha (ou à sentinela) para poder excluir b
    restaurar = anterior or _garantir_sentinela(admin)
    assert admin.post(f"/api/projects/{restaurar['id']}/activate").status_code == 200
    assert admin.delete(f"/api/projects/{b['id']}").status_code == 204


def test_e2e14_conexoes_segredo_e_limite(admin: httpx.Client):
    p = admin.post("/api/projects", json={"name": _novo_nome("proj-conn")}).json()
    corpo = {
        "project_id": p["id"],
        "name": "plc1",
        "endpoint": "opc.tcp://10.0.0.5:4840",
        "auth_mode": "user_password",
        "auth_username": "u",
        "auth_password": "senha-plc",
    }
    criado = admin.post("/api/connections", json=corpo)
    assert criado.status_code == 201
    body = criado.json()
    assert body["has_password"] is True
    assert "auth_password" not in body and "auth_password_enc" not in body
    for i in range(2, 6):
        assert (
            admin.post(
                "/api/connections",
                json={"project_id": p["id"], "name": f"plc{i}", "endpoint": "opc.tcp://x:4840"},
            ).status_code
            == 201
        )
    assert (
        admin.post(
            "/api/connections",
            json={"project_id": p["id"], "name": "plc6", "endpoint": "opc.tcp://x:4840"},
        ).status_code
        == 409
    )
    assert admin.delete(f"/api/projects/{p['id']}").status_code == 204  # limpeza (CASCADE)


def test_e2e15_tags_crud_e_filtro(admin: httpx.Client):
    p = admin.post("/api/projects", json={"name": _novo_nome("proj-tag")}).json()
    c = admin.post(
        "/api/connections",
        json={"project_id": p["id"], "name": "plc", "endpoint": "opc.tcp://x:4840"},
    ).json()
    for nome, direcao in [("FT-101", "r"), ("FV-101", "w")]:
        assert (
            admin.post(
                "/api/tags",
                json={
                    "connection_id": c["id"],
                    "name": nome,
                    "node_id": f"ns=2;s={nome}",
                    "direction": direcao,
                    "data_type": "float",
                    "eu": "m3/h",
                },
            ).status_code
            == 201
        )
    so_leitura = admin.get(f"/api/tags?connection_id={c['id']}&direction=r").json()
    assert [t["name"] for t in so_leitura] == ["FT-101"]
    assert admin.delete(f"/api/projects/{p['id']}").status_code == 204
