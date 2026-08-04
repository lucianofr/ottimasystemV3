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


async def test_health_sem_supervisor_nao_responde_ok():
    """Runtime que não subiu o supervisor está surdo a todo `deploy`: nunca `status=ok`.

    Redis e banco sãos não bastam — o heartbeat os repõe depois de uma falha de subida e o
    corpo continuaria `ok` com `flows={}`, indistinguível do boot parado legítimo (ADR-017).
    """
    app.state.redis_ok = True
    app.state.db_ok = True
    app.state.runtime_up = False
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            degradado = (await c.get("/health")).json()
            app.state.runtime_up = True
            saudavel = (await c.get("/health")).json()
    finally:
        # O app é compartilhado no módulo: devolve o estado aos defaults do `getattr`.
        del app.state.redis_ok, app.state.db_ok, app.state.runtime_up

    assert degradado["status"] == "degraded"
    assert saudavel["status"] == "ok"
