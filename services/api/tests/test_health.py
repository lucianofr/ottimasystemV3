"""Health check público: sem token, sem banco (spec F1 §7.1)."""


async def test_health_publico(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "api"
    assert body["version"] == "0.1.0"
