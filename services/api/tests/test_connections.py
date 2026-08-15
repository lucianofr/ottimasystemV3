from sqlalchemy import select

from ottima_core.models import OpcConnection
from ottima_core.security import decrypt_secret


async def _projeto(client, headers, name="Proj") -> int:
    r = await client.post("/api/projects", json={"name": name}, headers=headers)
    return r.json()["id"]


BASE = {"name": "plc1", "endpoint": "opc.tcp://10.0.0.5:4840"}


async def test_cria_com_senha_cifrada_e_nunca_devolve(
    client, admin_headers, db_session, test_settings
):
    pid = await _projeto(client, admin_headers)
    r = await client.post(
        "/api/connections",
        json={
            **BASE,
            "project_id": pid,
            "auth_mode": "user_password",
            "auth_username": "opc-user",
            "auth_password": "senha-do-plc",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["has_password"] is True
    assert "auth_password" not in body and "auth_password_enc" not in body
    stored = await db_session.scalar(select(OpcConnection).where(OpcConnection.id == body["id"]))
    assert stored.auth_password_enc != "senha-do-plc"
    assert decrypt_secret(stored.auth_password_enc, key=test_settings.fernet_key) == "senha-do-plc"


async def test_limite_de_5_conexoes_por_projeto(client, admin_headers):
    pid = await _projeto(client, admin_headers, "Cheio")
    for i in range(5):
        r = await client.post(
            "/api/connections",
            json={"project_id": pid, "name": f"c{i}", "endpoint": "opc.tcp://x:4840"},
            headers=admin_headers,
        )
        assert r.status_code == 201
    r = await client.post(
        "/api/connections",
        json={"project_id": pid, "name": "c6", "endpoint": "opc.tcp://x:4840"},
        headers=admin_headers,
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Limite de 5 conexões por projeto atingido"


async def test_coerencia_policy_mode_422(client, admin_headers):
    pid = await _projeto(client, admin_headers, "Coerencia")
    r = await client.post(
        "/api/connections",
        json={
            **BASE,
            "project_id": pid,
            "security_policy": "basic256sha256",
            "security_mode": "none",
        },
        headers=admin_headers,
    )
    assert r.status_code == 422


async def test_patch_sem_auth_password_mantem_senha(client, admin_headers):
    pid = await _projeto(client, admin_headers, "Manter")
    created = (
        await client.post(
            "/api/connections",
            json={
                **BASE,
                "project_id": pid,
                "auth_mode": "user_password",
                "auth_username": "u",
                "auth_password": "senha-original",
            },
            headers=admin_headers,
        )
    ).json()
    r = await client.patch(
        f"/api/connections/{created['id']}", json={"name": "renomeada"}, headers=admin_headers
    )
    assert r.status_code == 200
    assert r.json()["has_password"] is True


async def test_papeis_e_filtro(client, admin_headers, operator_headers):
    pid = await _projeto(client, admin_headers, "Filtro")
    await client.post("/api/connections", json={**BASE, "project_id": pid}, headers=admin_headers)
    r = await client.get(f"/api/connections?project_id={pid}", headers=operator_headers)
    assert r.status_code == 200 and len(r.json()) == 1
    assert (
        await client.post(
            "/api/connections",
            json={**BASE, "project_id": pid, "name": "n2"},
            headers=operator_headers,
        )
    ).status_code == 403


async def test_polling_period_ms_default_1000_ao_omitir(client, admin_headers):
    pid = await _projeto(client, admin_headers, "PollingDefault")
    r = await client.post(
        "/api/connections", json={**BASE, "project_id": pid}, headers=admin_headers
    )
    assert r.status_code == 201
    assert r.json()["polling_period_ms"] == 1000


async def test_polling_period_ms_expoe_valor_custom_no_out(client, admin_headers):
    pid = await _projeto(client, admin_headers, "PollingCustom")
    r = await client.post(
        "/api/connections",
        json={**BASE, "project_id": pid, "polling_period_ms": 2500},
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["polling_period_ms"] == 2500


async def test_polling_period_ms_99_e_60001_rejeitados_com_422(client, admin_headers):
    pid = await _projeto(client, admin_headers, "PollingForaDaFaixa")
    for periodo in (99, 60001):
        r = await client.post(
            "/api/connections",
            json={**BASE, "project_id": pid, "name": f"c{periodo}", "polling_period_ms": periodo},
            headers=admin_headers,
        )
        assert r.status_code == 422


async def test_polling_period_ms_100_e_60000_aceitos_com_200(client, admin_headers):
    pid = await _projeto(client, admin_headers, "PollingNaFaixa")
    for periodo in (100, 60000):
        r = await client.post(
            "/api/connections",
            json={**BASE, "project_id": pid, "name": f"c{periodo}", "polling_period_ms": periodo},
            headers=admin_headers,
        )
        assert r.status_code == 201
        assert r.json()["polling_period_ms"] == periodo


async def test_patch_altera_apenas_polling_period_ms(client, admin_headers):
    pid = await _projeto(client, admin_headers, "PollingPatch")
    created = (
        await client.post(
            "/api/connections", json={**BASE, "project_id": pid}, headers=admin_headers
        )
    ).json()
    r = await client.patch(
        f"/api/connections/{created['id']}",
        json={"polling_period_ms": 5000},
        headers=admin_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["polling_period_ms"] == 5000
    assert body["name"] == created["name"]
    assert body["endpoint"] == created["endpoint"]
