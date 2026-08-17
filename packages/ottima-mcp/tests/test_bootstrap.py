"""Bootstrap da conta `agente` (Fase 5): login como admin, POST /api/users, idempotente em
409. Sem rede — `bootstrap(transport=...)` aceita o mesmo hook de teste de `ClienteOttima`."""

from __future__ import annotations

import json

import httpx
import pytest

from ottima_mcp.bootstrap import bootstrap
from ottima_mcp.cliente import ErroOttima

_USER_OUT_BASE = {
    "is_active": True,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
}


def _envs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTTIMA_URL", "http://ottima.local")
    monkeypatch.setenv("OTTIMA_MCP_USERNAME", "agente")
    monkeypatch.setenv("OTTIMA_MCP_PASSWORD", "segredo-agente")
    monkeypatch.setenv("OTTIMA_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("OTTIMA_ADMIN_PASSWORD", "segredo-admin")


def _login_out(username: str, role: str) -> dict[str, object]:
    return {
        "access_token": f"tok-{username}",
        "token_type": "bearer",
        "expires_in": 43200,
        "user": {"id": 1, "username": username, "name": username, "role": role, **_USER_OUT_BASE},
    }


@pytest.mark.asyncio
async def test_bootstrap_cria_conta_agente(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _envs(monkeypatch)
    capturado: dict[str, object] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            corpo = json.loads(request.content)
            assert corpo == {"username": "admin", "password": "segredo-admin"}
            return httpx.Response(200, json=_login_out("admin", "admin"))
        if request.url.path == "/api/users":
            capturado["body"] = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "id": 7,
                    "username": "agente",
                    "name": "Agente MCP",
                    "role": "admin",
                    **_USER_OUT_BASE,
                },
            )
        return httpx.Response(404)

    await bootstrap(transport=httpx.MockTransport(_handler))

    assert capturado["body"] == {
        "username": "agente",
        "name": "Agente MCP",
        "password": "segredo-agente",
        "role": "admin",
    }
    assert "criada" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_bootstrap_idempotente_em_409(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _envs(monkeypatch)

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json=_login_out("admin", "admin"))
        if request.url.path == "/api/users":
            return httpx.Response(409, json={"detail": "Nome de usuário já em uso"})
        return httpx.Response(404)

    await bootstrap(transport=httpx.MockTransport(_handler))  # não deve levantar
    assert "já existe" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_bootstrap_propaga_erro_nao_409(monkeypatch: pytest.MonkeyPatch) -> None:
    _envs(monkeypatch)

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json=_login_out("admin", "admin"))
        if request.url.path == "/api/users":
            return httpx.Response(422, json={"detail": "password: mínimo 8 caracteres"})
        return httpx.Response(404)

    with pytest.raises(ErroOttima, match="mínimo 8 caracteres"):
        await bootstrap(transport=httpx.MockTransport(_handler))


@pytest.mark.asyncio
async def test_bootstrap_sem_credenciais_de_admin_sai_com_mensagem_clara(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _envs(monkeypatch)
    monkeypatch.delenv("OTTIMA_ADMIN_USERNAME", raising=False)

    with pytest.raises(SystemExit, match="OTTIMA_ADMIN_USERNAME"):
        await bootstrap()
