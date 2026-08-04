from httpx import ASGITransport, AsyncClient

from ottima_flow_runtime.main import app, check_redis


class StubRedis:
    def __init__(self, fail: bool):
        self.fail = fail

    async def ping(self):
        if self.fail:
            raise ConnectionError("sem redis")
        return True


async def test_health_responde_200_com_nome_do_servico():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "flow-runtime"
    assert body["status"] in {"ok", "degraded"}


async def test_check_redis_marca_estado():
    await check_redis(StubRedis(fail=False), app)
    assert app.state.redis_ok is True
    await check_redis(StubRedis(fail=True), app)
    assert app.state.redis_ok is False
