"""Health check público (sem token) e agregador de workers (spec F5 §4.2, decisão A-8).

`/health` reflete Redis/Postgres por heartbeat de fundo (spec F6 §3.3, RNF-07). O cliente
de teste (`ASGITransport`) nunca dispara o `lifespan`, então a maioria dos testes abaixo
popula `app.state` diretamente para simular o heartbeat já ter rodado; os dois testes de
ciclo de vida (`test_lifespan_*`/`test_heartbeat_loop_*`) disparam o `lifespan` de verdade ou
o `heartbeat_loop` de verdade, com dublês no lugar de Redis/banco — sem container nem rede."""

import asyncio
import json
import urllib.error
from contextlib import suppress

from ottima_api import app as app_module
from ottima_api.routers import health as health_module


async def test_health_forma_completa_com_defaults_antes_do_heartbeat(client):
    """App cru (sem lifespan): degraded, os dois flags em False, forma completa com as 5
    chaves."""
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "status": "degraded",
        "service": "api",
        "version": "0.1.0",
        "redis_ok": False,
        "db_ok": False,
    }


async def test_health_ok_quando_os_dois_flags_verdadeiros(client, app):
    app.state.redis_ok = True
    app.state.db_ok = True

    r = await client.get("/api/health")

    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "service": "api",
        "version": "0.1.0",
        "redis_ok": True,
        "db_ok": True,
    }


async def test_health_degraded_quando_um_flag_falso(client, app):
    app.state.redis_ok = True
    app.state.db_ok = False

    r = await client.get("/api/health")

    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


class _ClienteQueLevantaSeChamado:
    """Qualquer atributo acessado, ou a própria instância chamada, indica que o handler
    tentou I/O — o que `/health` não pode fazer (spec F6 §3.3-2: handler sem I/O, só lê o
    estado gravado pelo heartbeat). Serve tanto de cliente Redis quanto de dublê de
    `session_factory`/engine (que o handler chamaria diretamente, sem passar por atributo)."""

    def __getattr__(self, _name: str):
        def _boom(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("handler de /health não pode tocar em Redis/banco")

        return _boom

    def __call__(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("handler de /health não pode tocar em Redis/banco")


async def test_health_handler_nao_faz_io(client, app):
    """app.state já populado pelo heartbeat (simulado aqui); substituir Redis, session
    factory e engine por dublês que levantam em qualquer uso prova que o handler nunca os
    toca — nenhum dos três é I/O permitido dentro do handler."""
    app.state.redis_ok = True
    app.state.db_ok = True
    app.state.redis = _ClienteQueLevantaSeChamado()
    app.state.session_factory = _ClienteQueLevantaSeChamado()
    app.state.engine = _ClienteQueLevantaSeChamado()

    r = await client.get("/api/health")

    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "service": "api",
        "version": "0.1.0",
        "redis_ok": True,
        "db_ok": True,
    }


class _RedisFalso:
    def __init__(self, *, falha: bool) -> None:
        self._falha = falha

    async def ping(self) -> bool:
        if self._falha:
            raise ConnectionError("sem redis")
        return True

    async def aclose(self) -> None:
        """Chamado no shutdown do `lifespan` real (app.py); não faz nada aqui."""
        return None


class _SessionFactoryFalsa:
    """Dublê de `async_sessionmaker`: o `SELECT 1` é executado ou explode, como no real."""

    def __init__(self, *, falha: bool) -> None:
        self._falha = falha

    def __call__(self) -> "_SessionFactoryFalsa":
        return self

    async def __aenter__(self) -> "_SessionFactoryFalsa":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def execute(self, _statement: object) -> None:
        if self._falha:
            raise ConnectionError("sem banco")


async def test_check_redis_marca_app_state(app):
    await health_module.check_redis(_RedisFalso(falha=False), app)
    assert app.state.redis_ok is True

    await health_module.check_redis(_RedisFalso(falha=True), app)
    assert app.state.redis_ok is False


async def test_check_database_marca_app_state(app):
    await health_module.check_database(_SessionFactoryFalsa(falha=False), app)
    assert app.state.db_ok is True

    await health_module.check_database(_SessionFactoryFalsa(falha=True), app)
    assert app.state.db_ok is False


class _EngineFalso:
    """Dublê do `AsyncEngine`: só precisa saber morrer no shutdown do `lifespan`."""

    async def dispose(self) -> None:
        return None


class _HubFalso:
    """Substitui `FlowStatusHub` no teste do `lifespan` real: sem pubsub/Redis de verdade,
    só marca que `start`/`stop` foram chamados na ordem certa."""

    def __init__(self, _redis_client: object) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


async def test_lifespan_cria_e_cancela_o_heartbeat_sem_vazar(monkeypatch, app):
    """Cobre o ciclo create/cancel/await do heartbeat dentro do `lifespan` real de `app.py`
    (spec F6 §3.3: ciclo de vida normativo) — nada mais na suíte o exercita, já que
    `ASGITransport` nunca dispara `lifespan`. Redis, engine, session factory e o hub de `/ws`
    são dublês (sem container nem rede); `HEARTBEAT_INTERVAL_S` é encurtado para o teste não
    esperar 5 s reais."""
    monkeypatch.setattr(health_module, "HEARTBEAT_INTERVAL_S", 0.01)
    redis_falso = _RedisFalso(falha=False)
    monkeypatch.setattr(app_module, "create_engine", lambda _url: _EngineFalso())
    monkeypatch.setattr(
        app_module, "create_session_factory", lambda _engine: _SessionFactoryFalsa(falha=False)
    )
    monkeypatch.setattr(app_module.redis, "from_url", lambda *_a, **_kw: redis_falso)
    monkeypatch.setattr(app_module, "FlowStatusHub", _HubFalso)

    tasks_antes = asyncio.all_tasks()

    async with app.router.lifespan_context(app):
        tasks_novas = asyncio.all_tasks() - tasks_antes
        assert len(tasks_novas) == 2, (
            "lifespan deveria criar a task do heartbeat e a do watch de log level"
        )
        heartbeat_task = next(t for t in tasks_novas if "heartbeat" in repr(t.get_coro()))
        assert not heartbeat_task.done()

        await asyncio.sleep(0.05)  # alguns ciclos de HEARTBEAT_INTERVAL_S=0.01

        assert app.state.redis_ok is True
        assert app.state.db_ok is True

    # Saída do `async with` sem levantar: nenhum `CancelledError` escapou do shutdown. As tasks
    # foram canceladas e aguardadas, e não sobrou nada rodando.
    assert heartbeat_task.done()
    assert heartbeat_task.cancelled()
    assert asyncio.all_tasks() - tasks_antes == set()


async def test_heartbeat_loop_sobrevive_a_falha_e_atualiza_no_proximo_ciclo(monkeypatch, app):
    """Uma falha do Redis dentro do laço não pode matá-lo (spec F6 §3.3-2): o ciclo seguinte
    ainda roda e volta a refletir o estado real quando a falha passa. Sem isso, um engasgo
    passageiro do Redis deixaria `/health` travado em `degraded` para sempre, mesmo com o
    Redis de volta — só um reinício do processo resolveria."""
    monkeypatch.setattr(health_module, "HEARTBEAT_INTERVAL_S", 0.01)
    redis_controlavel = _RedisFalso(falha=True)
    session_factory = _SessionFactoryFalsa(falha=False)

    task = asyncio.create_task(
        health_module.heartbeat_loop(redis_controlavel, session_factory, app)
    )
    try:
        await asyncio.sleep(0.03)
        assert app.state.redis_ok is False  # 1o ciclo: Redis falhando
        assert app.state.db_ok is True  # banco não é afetado pela falha do Redis

        redis_controlavel._falha = False  # Redis "volta"
        await asyncio.sleep(0.03)
        assert app.state.redis_ok is True  # o ciclo seguinte reflete a recuperação sozinho
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


class _RespostaFalsa:
    """Simula o context manager devolvido por `urllib.request.urlopen`."""

    def __init__(self, corpo: object) -> None:
        self._bytes = json.dumps(corpo).encode()

    def __enter__(self) -> "_RespostaFalsa":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._bytes


def _monkeypatch_urlopen(monkeypatch, respostas: dict[str, object]) -> None:
    """`respostas[url]` é um dict (sucesso) ou uma exceção (erro/timeout) a levantar."""

    def _fake_urlopen(url: str, timeout: float | None = None) -> _RespostaFalsa:
        alvo = respostas[url]
        if isinstance(alvo, Exception):
            raise alvo
        return _RespostaFalsa(alvo)

    monkeypatch.setattr(health_module.urllib.request, "urlopen", _fake_urlopen)


async def test_workers_agrega_os_quatro_sempre_200(
    client, operator_headers, monkeypatch, test_settings
):
    corpo_opc = {"status": "ok", "service": "opc-worker", "version": "0.1.0", "connections": {}}
    corpo_flow = {"status": "ok", "service": "flow-runtime", "version": "0.1.0"}
    corpo_rec = {"status": "degraded", "service": "recorder", "version": "0.1.0"}
    corpo_calc = {"status": "ok", "service": "calc-worker", "version": "0.1.0", "tags": {}}
    _monkeypatch_urlopen(
        monkeypatch,
        {
            test_settings.health_url_opc_worker: corpo_opc,
            test_settings.health_url_flow_runtime: corpo_flow,
            test_settings.health_url_recorder: corpo_rec,
            test_settings.health_url_calc_worker: corpo_calc,
        },
    )

    r = await client.get("/api/health/workers", headers=operator_headers)

    assert r.status_code == 200
    body = r.json()
    assert body["opc_worker"] == {"up": True, **corpo_opc}
    assert body["flow_runtime"] == {"up": True, **corpo_flow}
    assert body["recorder"] == {"up": True, **corpo_rec}
    assert body["calc_worker"] == {"up": True, **corpo_calc}


async def test_workers_erro_e_timeout_viram_up_false_sem_derrubar_o_200(
    client, operator_headers, monkeypatch, test_settings
):
    corpo_opc = {"status": "ok", "service": "opc-worker", "version": "0.1.0"}
    _monkeypatch_urlopen(
        monkeypatch,
        {
            test_settings.health_url_opc_worker: corpo_opc,
            test_settings.health_url_flow_runtime: urllib.error.URLError("conexão recusada"),
            test_settings.health_url_recorder: TimeoutError("tempo esgotado"),
            test_settings.health_url_calc_worker: urllib.error.URLError("conexão recusada"),
        },
    )

    r = await client.get("/api/health/workers", headers=operator_headers)

    assert r.status_code == 200
    body = r.json()
    assert body["opc_worker"] == {"up": True, **corpo_opc}
    assert body["flow_runtime"] == {"up": False}
    assert body["recorder"] == {"up": False}
    assert body["calc_worker"] == {"up": False}


async def test_workers_corpo_json_nao_objeto_vira_up_false_sem_derrubar_o_200(
    client, operator_headers, monkeypatch, test_settings
):
    """`json.loads` de um corpo válido mas não-objeto (lista/string/bool/null) não pode
    estourar o merge `{"up": True, **corpo}` com TypeError; assim como erro/timeout, vira
    `{"up": False}` sem derrubar o 200 do agregador (spec F5 §4.2, decisão A-8)."""
    corpo_opc = {"status": "ok", "service": "opc-worker", "version": "0.1.0"}
    _monkeypatch_urlopen(
        monkeypatch,
        {
            test_settings.health_url_opc_worker: corpo_opc,
            test_settings.health_url_flow_runtime: [1, 2, 3],
            test_settings.health_url_recorder: "ok",
            test_settings.health_url_calc_worker: False,
        },
    )

    r = await client.get("/api/health/workers", headers=operator_headers)

    assert r.status_code == 200
    body = r.json()
    assert body["opc_worker"] == {"up": True, **corpo_opc}
    assert body["flow_runtime"] == {"up": False}
    assert body["recorder"] == {"up": False}
    assert body["calc_worker"] == {"up": False}


async def test_workers_anonimo_401(client):
    """Sem token, `require_operator` reprova antes de qualquer chamada aos workers."""
    r = await client.get("/api/health/workers")
    assert r.status_code == 401


async def test_health_publico_continua_sem_auth_apos_rota_de_workers(client):
    """A rota nova é `require_operator` por rota: `/health` público não ganhou dependência."""
    r = await client.get("/api/health")
    assert r.status_code == 200
