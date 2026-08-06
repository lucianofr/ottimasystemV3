"""Health check público (sem token) e agregador de workers (spec F5 §4.2, decisão A-8)."""

import json
import urllib.error

from ottima_api.routers import health as health_module


async def test_health_publico(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "api"
    assert body["version"] == "0.1.0"


class _RespostaFalsa:
    """Simula o context manager devolvido por `urllib.request.urlopen`."""

    def __init__(self, corpo: dict) -> None:
        self._bytes = json.dumps(corpo).encode()

    def __enter__(self) -> "_RespostaFalsa":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._bytes


def _monkeypatch_urlopen(monkeypatch, respostas: dict) -> None:
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


async def test_workers_anonimo_401(client):
    """Sem token, `require_operator` reprova antes de qualquer chamada aos workers."""
    r = await client.get("/api/health/workers")
    assert r.status_code == 401


async def test_health_publico_continua_sem_auth_apos_rota_de_workers(client):
    """A rota nova é `require_operator` por rota: `/health` público não ganhou dependência."""
    r = await client.get("/api/health")
    assert r.status_code == 200
