"""Fixtures da camada L2 da F2 (spec F2 §11.2): API, barramento e opcsim do compose real.

Nada aqui sobe ou derruba o stack: a suíte assume o compose de pé (`OTTIMA_E2E=1 bash
deploy/smoke.sh`). O único serviço que os testes mexem é o `opcsim`, e só com
`stop`/`start` — `down` e `prune` são proibidos porque a máquina hospeda outros projetos.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import redis
from asyncua import Client

from opcsim import (
    NODE_CTRL_FREEZE_WATCHDOG,
    NODE_MIRROR_FLOAT,
    NODE_SINE,
    NODE_STATIC,
    NODE_W_FLOAT,
    NODE_WD_FROM_SYSTEM,
    NODE_WD_TO_SYSTEM,
)
from ottima_core.bus import CHANNEL_EVENTS, CHANNEL_OPC_WRITES, OpcWrite

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "deploy"

# Sufixo único por execução: o banco do stack é persistente e nada pode colidir com a
# rodada anterior (mesmo padrão da L2 da F1).
RUN_ID = f"{time.time_ns():x}"

# Projeto estável que recebe a ativação nos teardowns: excluir o projeto ativo dá 409, e
# a API não expõe "desativar". Mesmo nome usado pela L2 da F1.
SENTINELA = "E2E sentinela (não excluir)"


def _deploy_env() -> dict[str, str]:
    """Pares do `deploy/.env`, para a suíte rodar sem exportar nada à mão."""
    valores: dict[str, str] = {}
    arquivo = DEPLOY_DIR / ".env"
    if not arquivo.exists():
        return valores
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        limpa = linha.strip()
        if not limpa or limpa.startswith("#") or "=" not in limpa:
            continue
        chave, _, valor = limpa.partition("=")
        valores[chave.strip()] = valor.strip()
    return valores


_DEPLOY = _deploy_env()


def _conf(nome: str, default: str) -> str:
    """Ambiente do processo vence; `deploy/.env` é o fallback; depois o default."""
    return os.environ.get(nome) or _DEPLOY.get(nome) or default


BASE = _conf("E2E_BASE_URL", "http://localhost:8080")
ADMIN_USER = _conf("E2E_ADMIN_USERNAME", _conf("OTTIMA_ADMIN_USERNAME", "admin"))
ADMIN_PASS = _conf("E2E_ADMIN_PASSWORD", _conf("OTTIMA_ADMIN_PASSWORD", ""))

# A porta publicada do Redis é parametrizada no override e2e (`OTTIMA_E2E_REDIS_PORT`):
# a 6379 do host pode estar ocupada por outro projeto. Nunca fixe o número aqui.
REDIS_PORT = _conf("OTTIMA_E2E_REDIS_PORT", "6379")
REDIS_URL = _conf("E2E_REDIS_URL", f"redis://127.0.0.1:{REDIS_PORT}/0")

# Endpoint de DENTRO da rede do compose: é o que vai no cadastro da conexão.
OPCSIM_URL = _conf("E2E_OPCSIM_URL", "opc.tcp://opcsim:4840")
# Endpoint do HOST: é por onde o teste fala OPC direto com o simulador.
OPCSIM_HOST_URL = _conf("E2E_OPCSIM_HOST_URL", "opc.tcp://127.0.0.1:4840")
OPCSIM_CERT = Path(_conf("E2E_OPCSIM_CERT", "deploy/e2e-certs/opcsim.der"))
if not OPCSIM_CERT.is_absolute():
    OPCSIM_CERT = REPO_ROOT / OPCSIM_CERT

COMPOSE = ("docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.e2e.yml")

# O `/health` do opc-worker não é publicado (ADR-023: só a porta do frontend sai): a
# consulta do host é por `exec`, como o `deploy/smoke.sh` já faz.
_HEALTH_SNIPPET = (
    "import urllib.request;"
    "print(urllib.request.urlopen('http://localhost:8001/health', timeout=3).read().decode())"
)

_SEQUENCIA = itertools.count(1)


def compose(*args: str, timeout: float = 90.0) -> str:
    """Roda `docker compose` do stack e2e no diretório do deploy.

    Escopo deliberadamente estreito: os testes só usam `exec`, `stop` e `start`. Nada
    aqui pode virar `down` ou `prune` — a máquina hospeda outros projetos.
    """
    proc = subprocess.run(
        [*COMPOSE, *args],
        cwd=DEPLOY_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return proc.stdout


def worker_health() -> dict[str, Any]:
    """`/health` do opc-worker, lido de dentro do container."""
    return json.loads(compose("exec", "-T", "opc-worker", "python", "-c", _HEALTH_SNIPPET))


def conexao_health(conn_id: int) -> dict[str, Any] | None:
    """Bloco da conexão no `/health` do worker; `None` enquanto o worker não a conhece."""
    try:
        saude = worker_health()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        # Worker reiniciando ou exec recusado: é estado transitório de espera, não erro.
        return None
    return saude.get("connections", {}).get(str(conn_id))


def esperar_ate[T](
    cond: Callable[[], T | None],
    *,
    timeout: float,
    intervalo: float = 0.5,
    descricao: str,
) -> T:
    """Espera por condição, nunca por `sleep` cego. Devolve o valor que a satisfez."""
    limite = time.monotonic() + timeout
    while True:
        valor = cond()
        if valor:
            return valor
        if time.monotonic() >= limite:
            raise AssertionError(f"{descricao}: não ocorreu em {timeout:.0f}s")
        time.sleep(intervalo)


def esperar_conexao(
    conn_id: int,
    *,
    estado: str = "up",
    watchdog_alive: bool | None = True,
    session_up_since_diferente_de: str | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """Espera o `/health` do worker refletir o estado pedido para a conexão."""

    def checar() -> dict[str, Any] | None:
        conexao = conexao_health(conn_id)
        if conexao is None or conexao["state"] != estado:
            return None
        if watchdog_alive is not None and conexao["watchdog_alive"] is not watchdog_alive:
            return None
        if (
            session_up_since_diferente_de is not None
            and conexao["session_up_since"] == session_up_since_diferente_de
        ):
            return None
        return conexao

    alvo = f"conexão {conn_id} em state={estado!r}"
    if session_up_since_diferente_de is not None:
        alvo += " com sessão nova"
    return esperar_ate(checar, timeout=timeout, intervalo=1.0, descricao=alvo)


def valor_unico() -> float:
    """Double distinto a cada chamada e entre execuções.

    O espelho do opcsim sobrevive à rodada: repetir um valor faria o teste de escrita
    passar sem que escrita nenhuma tivesse acontecido.
    """
    return round(100.0 + (time.time_ns() % 100_000) / 1000.0 + next(_SEQUENCIA), 3)


def publicar_escrita(
    redis_bus: redis.Redis, *, conn_id: int, tag_id: int, value: float, source: str
) -> None:
    """Publica um `OpcWrite` verbatim em `opc.writes` (PRD §7.1)."""
    escrita = OpcWrite(
        conn_id=conn_id, tag_id=tag_id, value=value, source=source, ts=datetime.now(UTC)
    )
    redis_bus.publish(CHANNEL_OPC_WRITES, escrita.model_dump_json())


def evento_de(kind: str, conn_id: int) -> Callable[[dict[str, Any]], bool]:
    """Predicado de evento do canal `events` por `kind` e `conn_id` (spec §7.3)."""

    def casa(evento: dict[str, Any]) -> bool:
        payload = evento.get("payload", {})
        return payload.get("kind") == kind and payload.get("conn_id") == conn_id

    return casa


class EventStream:
    """Assinatura do canal `events` aberta ANTES do gatilho.

    A inscrição é aberta na fixture, não na espera: entre o ato que dispara o evento e a
    chamada de espera não pode existir janela em que a mensagem se perca. É também o que
    permite medir o Δt do aceite (PRD §8-F2) sem somar a latência de gravação no banco.
    """

    def __init__(self, pubsub: redis.client.PubSub) -> None:
        self._pubsub = pubsub

    def esperar(
        self, pred: Callable[[dict[str, Any]], bool], *, timeout: float, descricao: str
    ) -> dict[str, Any]:
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            mensagem = self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if mensagem is None or mensagem.get("type") != "message":
                continue
            evento = json.loads(mensagem["data"])
            if pred(evento):
                return evento
        raise AssertionError(f"{descricao}: nenhum evento correspondente em {timeout:.0f}s")


class OpcSim:
    """Cliente OPC-UA do host contra o opcsim: espelhos e nodes `sim/control/*`.

    Uma sessão curta por operação. O polling dos testes é de baixa frequência e uma
    sessão longa exigiria manter um loop de eventos vivo entre chamadas síncronas.
    """

    def __init__(self, url: str) -> None:
        self._url = url

    def read(self, node_id: str) -> Any:
        return asyncio.run(self._read(node_id))

    def write(self, node_id: str, value: Any) -> None:
        asyncio.run(self._write(node_id, value))

    async def _read(self, node_id: str) -> Any:
        async with Client(url=self._url, timeout=10) as client:
            return await client.get_node(node_id).read_value()

    async def _write(self, node_id: str, value: Any) -> None:
        async with Client(url=self._url, timeout=10) as client:
            await client.get_node(node_id).write_value(value)


@dataclass(frozen=True, slots=True)
class Ambiente:
    """Projeto ativo com uma conexão ao opcsim e as quatro tags que a suíte exercita."""

    project_id: int
    conn_id: int
    sine: int
    static: int
    mirror: int
    w_float: int


@pytest.fixture(scope="session")
def admin() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BASE, timeout=20) as cliente:
        r = cliente.post("/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        assert r.status_code == 200, "login do admin do seed falhou — confira deploy/.env"
        cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield cliente


@pytest.fixture(scope="session")
def redis_bus() -> Iterator[redis.Redis]:
    cliente = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        assert cliente.ping(), f"Redis do stack inacessível em {REDIS_URL}"
        yield cliente
    finally:
        cliente.close()


@pytest.fixture
def eventos(redis_bus: redis.Redis) -> Iterator[EventStream]:
    pubsub = redis_bus.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(CHANNEL_EVENTS)
    try:
        yield EventStream(pubsub)
    finally:
        pubsub.close()


@pytest.fixture(scope="session")
def opcsim_client() -> OpcSim:
    return OpcSim(OPCSIM_HOST_URL)


@pytest.fixture
def congelar_watchdog(opcsim_client: OpcSim) -> Iterator[Callable[[bool], None]]:
    """Aciona `sim.control.freeze_watchdog`; o teardown descongela mesmo se o teste falhar."""

    def acionar(valor: bool) -> None:
        opcsim_client.write(NODE_CTRL_FREEZE_WATCHDOG, valor)

    try:
        yield acionar
    finally:
        acionar(False)


@pytest.fixture
def parar_opcsim() -> Iterator[Callable[[], None]]:
    """Para o opcsim; o teardown religa SEMPRE, inclusive se o teste falhar no meio."""

    def parar() -> None:
        compose("stop", "opcsim")

    try:
        yield parar
    finally:
        compose("start", "opcsim")


def _ativar_sentinela(admin: httpx.Client) -> None:
    r = admin.post("/api/projects", json={"name": SENTINELA})
    if r.status_code == 201:
        alvo = r.json()
    else:
        projetos = admin.get("/api/projects").json()
        alvo = next(p for p in projetos if p["name"] == SENTINELA)
    admin.post(f"/api/projects/{alvo['id']}/activate")


def _criar_tag(admin: httpx.Client, conn_id: int, nome: str, node_id: str, direcao: str) -> int:
    r = admin.post(
        "/api/tags",
        json={
            "connection_id": conn_id,
            "name": nome,
            "node_id": node_id,
            "direction": direcao,
            "data_type": "float",
        },
    )
    assert r.status_code == 201, f"criação da tag {nome} falhou: HTTP {r.status_code} {r.text}"
    return int(r.json()["id"])


@pytest.fixture(scope="module")
def projeto_com_conexao(admin: httpx.Client, request: pytest.FixtureRequest) -> Iterator[Ambiente]:
    """Projeto ativo + conexão ao opcsim + tags, com a conexão já `up` e watchdog vivo.

    Escopo de módulo: cada arquivo da suíte parte de um projeto limpo, e o teardown
    devolve a ativação à sentinela antes de excluir (excluir o ativo é 409).
    """
    sufixo = f"{request.module.__name__.rsplit('.', 1)[-1]}-{RUN_ID}"
    r = admin.post("/api/projects", json={"name": f"f2-{sufixo}", "description": "L2 da F2"})
    assert r.status_code == 201, f"criação do projeto falhou: HTTP {r.status_code} {r.text}"
    projeto = r.json()
    try:
        assert admin.post(f"/api/projects/{projeto['id']}/activate").status_code == 200
        r = admin.post(
            "/api/connections",
            json={
                "project_id": projeto["id"],
                "name": f"opcsim-{sufixo}",
                "endpoint": OPCSIM_URL,
                "security_policy": "none",
                "security_mode": "none",
                "auth_mode": "anonymous",
                "watchdog_read_node_id": NODE_WD_TO_SYSTEM,
                "watchdog_write_node_id": NODE_WD_FROM_SYSTEM,
                "watchdog_period_ms": 1000,
            },
        )
        assert r.status_code == 201, f"criação da conexão falhou: HTTP {r.status_code} {r.text}"
        conn_id = int(r.json()["id"])
        ambiente = Ambiente(
            project_id=projeto["id"],
            conn_id=conn_id,
            sine=_criar_tag(admin, conn_id, "sine", NODE_SINE, "r"),
            static=_criar_tag(admin, conn_id, "static", NODE_STATIC, "r"),
            mirror=_criar_tag(admin, conn_id, "mirror", NODE_MIRROR_FLOAT, "r"),
            w_float=_criar_tag(admin, conn_id, "w_float", NODE_W_FLOAT, "w"),
        )
        esperar_conexao(conn_id)
        yield ambiente
    finally:
        _ativar_sentinela(admin)
        admin.delete(f"/api/projects/{projeto['id']}")
