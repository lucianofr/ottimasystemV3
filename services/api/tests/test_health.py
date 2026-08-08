"""Health check público (sem token) e agregador de workers (spec F5 §4.2, decisão A-8).

`/health` reflete Redis/Postgres por heartbeat de fundo (spec F6 §3.3, RNF-07). O cliente
de teste (`ASGITransport`) nunca dispara o `lifespan`, então os testes abaixo populam
`app.state` diretamente para simular o heartbeat já ter rodado."""

import json
import urllib.error

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
    body = r.json()
    assert body["status"] == "ok"
    assert body["redis_ok"] is True
    assert body["db_ok"] is True


async def test_health_degraded_quando_um_flag_falso(client, app):
    app.state.redis_ok = True
    app.state.db_ok = False

    r = await client.get("/api/health")

    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


class _ClienteQueLevantaSeChamado:
    """Qualquer atributo acessado indica que o handler tentou I/O — o que `/health` não
    pode fazer (spec F6 §3.3-2: handler sem I/O, só lê o estado gravado pelo heartbeat)."""

    def __getattr__(self, _name: str):
        def _boom(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("handler de /health não pode tocar no cliente Redis")

        return _boom


async def test_health_handler_nao_faz_io(client, app):
    """app.state já populado pelo heartbeat (simulado aqui); substituir o cliente Redis por
    um que levanta em qualquer chamada prova que o handler nunca o usa."""
    app.state.redis_ok = True
    app.state.db_ok = True
    app.state.redis = _ClienteQueLevantaSeChamado()

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


async def test_workers_agrega_os_tres_sempre_200(
    client, operator_headers, monkeypatch, test_settings
):
    corpo_opc = {"status": "ok", "service": "opc-worker", "version": "0.1.0", "connections": {}}
    corpo_flow = {"status": "ok", "service": "flow-runtime", "version": "0.1.0"}
    corpo_rec = {"status": "degraded", "service": "recorder", "version": "0.1.0"}
    _monkeypatch_urlopen(
        monkeypatch,
        {
            test_settings.health_url_opc_worker: corpo_opc,
            test_settings.health_url_flow_runtime: corpo_flow,
            test_settings.health_url_recorder: corpo_rec,
        },
    )

    r = await client.get("/api/health/workers", headers=operator_headers)

    assert r.status_code == 200
    body = r.json()
    assert body["opc_worker"] == {"up": True, **corpo_opc}
    assert body["flow_runtime"] == {"up": True, **corpo_flow}
    assert body["recorder"] == {"up": True, **corpo_rec}


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
        },
    )

    r = await client.get("/api/health/workers", headers=operator_headers)

    assert r.status_code == 200
    body = r.json()
    assert body["opc_worker"] == {"up": True, **corpo_opc}
    assert body["flow_runtime"] == {"up": False}
    assert body["recorder"] == {"up": False}


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
        },
    )

    r = await client.get("/api/health/workers", headers=operator_headers)

    assert r.status_code == 200
    body = r.json()
    assert body["opc_worker"] == {"up": True, **corpo_opc}
    assert body["flow_runtime"] == {"up": False}
    assert body["recorder"] == {"up": False}


async def test_workers_anonimo_401(client):
    """Sem token, `require_operator` reprova antes de qualquer chamada aos workers."""
    r = await client.get("/api/health/workers")
    assert r.status_code == 401


async def test_health_publico_continua_sem_auth_apos_rota_de_workers(client):
    """A rota nova é `require_operator` por rota: `/health` público não ganhou dependência."""
    r = await client.get("/api/health")
    assert r.status_code == 200
