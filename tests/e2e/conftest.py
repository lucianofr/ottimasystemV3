"""Fixtures da camada L2 da F2 (spec F2 §11.2): API, barramento e opcsim standalone.

Nada aqui sobe ou derruba o stack: a suíte assume o compose de pé (ADR-023). O
simulador OPC-UA não é mais serviço do compose — esta suíte o sobe como processo
standalone no host (teardown próprio) e o derruba/religa só com `parar_opcsim`/
`religar_opcsim`. `down` e `prune` são proibidos porque a máquina hospeda outros
projetos.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import redis
from asyncua import Client, ua
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from opcsim import (
    NODE_CTRL_FREEZE_WATCHDOG,
    NODE_MIRROR_FLOAT,
    NODE_MIRROR_INT,
    NODE_SINE,
    NODE_STATIC,
    NODE_W_FLOAT,
    NODE_W_INT,
    NODE_WD_FROM_SYSTEM,
    NODE_WD_TO_SYSTEM,
)
from ottima_core.bus import (
    CHANNEL_EVENTS,
    CHANNEL_OPC_WRITES,
    KIND_COMM_FAILURE,
    KIND_COMM_RESTORED,
    OpcWrite,
    channel_mpc_state,
)

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

# O simulador não é mais serviço do compose: a suíte o sobe standalone no host. O
# endpoint de cadastro da conexão é o de DENTRO da rede do compose (via gateway,
# `opcsim_standalone`); o do host serve ao cliente OPC direto dos testes.
OPCSIM_HOST = "127.0.0.1"
# A 4840 do host pode estar ocupada por outro projeto: parametrizada como a porta do
# Redis (`OTTIMA_E2E_REDIS_PORT`) — aponte para uma porta livre em deploy/.env.
OPCSIM_HOST_PORT = int(_conf("OTTIMA_E2E_OPCSIM_PORT", "4840"))
OPCSIM_HOST_URL = _conf("E2E_OPCSIM_HOST_URL", f"opc.tcp://{OPCSIM_HOST}:{OPCSIM_HOST_PORT}")
# Certificado do servidor do simulador, gerado no boot do processo standalone (pinning
# do E2E-F2-07). Override via E2E_OPCSIM_CERT para simulador externo.
OPCSIM_CERT = Path(_conf("E2E_OPCSIM_CERT", "deploy/.e2e-certs/opcsim.der"))
if not OPCSIM_CERT.is_absolute():
    OPCSIM_CERT = REPO_ROOT / OPCSIM_CERT
# Endpoint de DENTRO da rede fixado pelo usuário (simulador externo numa rede própria).
OPCSIM_URL_EXPLICITO = os.environ.get("E2E_OPCSIM_URL") or _DEPLOY.get("E2E_OPCSIM_URL")

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


def _porta_ocupada(host: str, porta: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex((host, porta)) == 0


def _gateway_da_rede_ottima() -> str:
    """Gateway da rede do compose — rota dos containers ao opcsim standalone do host."""
    ids = compose("ps", "-q").split()
    assert ids, "nenhum container do compose `ottima` de pé"
    redes = json.loads(
        subprocess.run(
            ["docker", "inspect", ids[0], "--format", "{{json .NetworkSettings.Networks}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout
    )
    for nome, dados in redes.items():
        if nome.startswith("ottima") and dados.get("Gateway"):
            return dados["Gateway"]
    raise AssertionError("rede do compose `ottima` sem gateway — opcsim inalcançável")


def _endpoint_na_rede() -> str:
    """Endpoint do opcsim de dentro da rede do compose, para o cadastro da conexão."""
    if OPCSIM_URL_EXPLICITO:
        return OPCSIM_URL_EXPLICITO
    return f"opc.tcp://{_gateway_da_rede_ottima()}:{OPCSIM_HOST_PORT}/ottima/opcsim/"


class _OpcSimProcesso:
    """opcsim standalone no host: `python -m opcsim` com Basic256Sha256 e cert-dir fixo.

    `start()` é idempotente (religa depois de `parar_opcsim`); o cert-dir é o mesmo em
    todo restart — o boot novo sobrescreve o DER antigo e o pinning do E2E-F2-07
    continua válido porque aquele cenário não religa o processo no meio.
    """

    def __init__(self, cert_dir: Path) -> None:
        self._cert_dir = cert_dir
        self._proc: subprocess.Popen[str] | None = None

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        # Certificado novo a cada boot: o par anterior é inválido assim que o servidor
        # para. Apagar antes de subir faz o `esperar_ate` do DER abaixo esperar de fato
        # pelo certificado do boot NOVO (sem o apagamento, o arquivo antigo satisfaria a
        # espera na hora e o pinning do E2E-F2-07 poderia ler um cert morto).
        for nome in ("opcsim.der", "opcsim.key.pem"):
            (self._cert_dir / nome).unlink(missing_ok=True)
        self._proc = subprocess.Popen(
            [
                ".venv/bin/python",
                "-m",
                "opcsim",
                "--host",
                "0.0.0.0",
                "--port",
                str(OPCSIM_HOST_PORT),
                "--security",
                "basic256sha256",
                "--cert-dir",
                str(self._cert_dir),
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        esperar_ate(
            lambda: True if _porta_ocupada(OPCSIM_HOST, OPCSIM_HOST_PORT) else None,
            timeout=30.0,
            intervalo=0.5,
            descricao="opcsim standalone ouvindo",
        )
        # O certificado (RSA 2048) demora ~2 s depois da porta abrir: o E2E-F2-07 faz o
        # pinning com ele logo em seguida — não pode haver janela em que ainda não exista.
        esperar_ate(
            lambda: True if (self._cert_dir / "opcsim.der").exists() else None,
            timeout=30.0,
            intervalo=0.5,
            descricao="certificado do opcsim standalone gerado",
        )

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


# Processo standalone da suíte; None quando o simulador é externo (porta já ocupada).
_SIM_PROCESSO: _OpcSimProcesso | None = None


def religar_opcsim() -> None:
    """Religa o opcsim standalone depois de uma queda proposital (F2-06, TD-04/05)."""
    if _SIM_PROCESSO is None:
        raise RuntimeError(
            f"opcsim é externo (porta {OPCSIM_HOST_PORT} já ocupada): sem processo para religar — "
            "pare o simulador externo e rode a suíte com a porta livre"
        )
    _SIM_PROCESSO.start()


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
    session_up_since_diferente_de: str | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """Espera o `/health` do worker refletir o estado pedido para a conexão.

    Watchdog não é mais checado aqui (ADR-009 revisado): virou conceito de flow, não de
    conexão — quem espera o watchdog vivo é `esperar_flow_watchdog`.
    """

    def checar() -> dict[str, Any] | None:
        conexao = conexao_health(conn_id)
        if conexao is None or conexao["state"] != estado:
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


def esperar_flow_watchdog(
    flow_id: int,
    conn_id: int,
    *,
    alive: bool = True,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """Espera o `/health` do worker refletir o watchdog do FLOW (ADR-009 revisado):
    `flow_watchdog_alive` é um dict `{flow_id: vivo}` dentro do bloco da conexão onde o
    watchdog do flow está configurado — chave string porque é JSON (`main.py` do worker)."""

    def checar() -> dict[str, Any] | None:
        conexao = conexao_health(conn_id)
        if conexao is None:
            return None
        if conexao.get("flow_watchdog_alive", {}).get(str(flow_id)) is not alive:
            return None
        return conexao

    alvo = f"watchdog do flow {flow_id} (conexão {conn_id}) em alive={alive!r}"
    return esperar_ate(checar, timeout=timeout, intervalo=1.0, descricao=alvo)


def valor_unico() -> float:
    """Double distinto a cada chamada e entre execuções.

    O espelho do opcsim sobrevive à rodada: repetir um valor faria o teste de escrita
    passar sem que escrita nenhuma tivesse acontecido.
    """
    return round(100.0 + (time.time_ns() % 100_000) / 1000.0 + next(_SEQUENCIA), 3)


def publicar_escrita(
    redis_bus: redis.Redis,
    *,
    conn_id: int,
    tag_id: int,
    flow_id: int,
    value: float,
    source: str,
) -> None:
    """Publica um `OpcWrite` verbatim em `opc.writes` (PRD §7.1).

    `flow_id` é obrigatório desde o ADR-009 revisado: o gate de escrita do opc-worker
    decide por `flow_watchdog_alive[flow_id]`, não mais por `conn_id` isolado."""
    escrita = OpcWrite(
        conn_id=conn_id,
        tag_id=tag_id,
        flow_id=flow_id,
        value=value,
        source=source,
        ts=datetime.now(UTC),
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


def revivar_watchdog_de_flow(
    conn_id: int,
    flow_id: int,
    *,
    eventos: EventStream,
    parar_opcsim: Callable[[], None],
) -> None:
    """Derruba e religa a sessão real do opcsim para forçar uma task de watchdog NOVA no
    flow (ADR-009 revisado): a task atual, se houver, pode já ter se encerrado sozinha na
    1ª detecção de congelamento (opc-worker `watchdog.py`) — só uma sessão nova volta a
    observar o bit; descongelar o rung sozinho não revive nada."""
    parar_opcsim()
    eventos.esperar(
        evento_de(KIND_COMM_FAILURE, conn_id),
        timeout=60.0,
        descricao="comm_failure da queda de sessão que força um watchdog de flow novo",
    )
    religar_opcsim()
    eventos.esperar(
        evento_de(KIND_COMM_RESTORED, conn_id),
        timeout=180.0,
        descricao="comm_restored da religada que força um watchdog de flow novo",
    )
    esperar_conexao(conn_id, timeout=60.0)
    esperar_flow_watchdog(flow_id, conn_id, timeout=60.0)


class OpcSim:
    """Cliente OPC-UA do host contra o opcsim: espelhos e nodes `sim/control/*`.

    Uma sessão curta por operação. O polling dos testes é de baixa frequência e uma
    sessão longa exigiria manter um loop de eventos vivo entre chamadas síncronas.
    """

    def __init__(self, url: str) -> None:
        self._url = url

    def read(self, node_id: str) -> Any:
        return asyncio.run(self._read(node_id))

    def write(
        self, node_id: str, value: Any, *, variant_type: ua.VariantType | None = None
    ) -> None:
        """`variant_type` força o tipo OPC-UA da escrita (spec F4 §2.1-4: `mode_cmd`/
        `mode_read` são Int32 — o cliente infere Int64 de um `int` cru sem essa dica e o
        servidor reprova com `BadTypeMismatch`); `None` preserva a inferência automática
        (double para os `float` de posição, já usada em todo o resto da suíte)."""
        asyncio.run(self._write(node_id, value, variant_type))

    async def _read(self, node_id: str) -> Any:
        async with Client(url=self._url, timeout=10) as client:
            return await client.get_node(node_id).read_value()

    async def _write(self, node_id: str, value: Any, variant_type: ua.VariantType | None) -> None:
        async with Client(url=self._url, timeout=10) as client:
            await client.get_node(node_id).write_value(value, variant_type)


@dataclass(frozen=True, slots=True)
class Ambiente:
    """Projeto ativo com uma conexão ao opcsim, as quatro tags que a suíte exercita e o
    flow cujo watchdog mantém a conexão gravável (ADR-009 revisado: watchdog é por flow,
    não por conexão)."""

    project_id: int
    conn_id: int
    flow_id: int
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
def opcsim_standalone() -> Iterator[str]:
    """Servidor opcsim standalone do host; devolve o endpoint de dentro da rede do compose.

    A stack não tem mais o serviço `opcsim` (fora do compose): o processo sobe aqui com
    teardown próprio. Porta canônica já ocupada ⇒ assume simulador externo e não
    gerencia o ciclo de vida (`parar_opcsim`/`religar_opcsim` falham com mensagem clara).
    """
    global _SIM_PROCESSO
    externo = _porta_ocupada(OPCSIM_HOST, OPCSIM_HOST_PORT)
    if not externo:
        _SIM_PROCESSO = _OpcSimProcesso(cert_dir=OPCSIM_CERT.parent)
        _SIM_PROCESSO.start()
    try:
        yield _endpoint_na_rede()
    finally:
        if _SIM_PROCESSO is not None:
            _SIM_PROCESSO.stop()
            _SIM_PROCESSO = None


@pytest.fixture(scope="session")
def opcsim_client(opcsim_standalone: str) -> OpcSim:
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
def parar_opcsim(opcsim_standalone: str) -> Iterator[Callable[[], None]]:
    """Para o opcsim standalone; o teardown religa SEMPRE, inclusive se o teste falhar."""

    def parar() -> None:
        if _SIM_PROCESSO is None:
            raise RuntimeError(
                f"opcsim é externo (porta {OPCSIM_HOST_PORT} já ocupada): sem processo para "
                "parar — pare o simulador externo e rode a suíte com a porta livre"
            )
        _SIM_PROCESSO.stop()

    try:
        yield parar
    finally:
        if _SIM_PROCESSO is not None:
            _SIM_PROCESSO.start()


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
def projeto_com_conexao(
    admin: httpx.Client, request: pytest.FixtureRequest, opcsim_standalone: str
) -> Iterator[Ambiente]:
    """Projeto ativo + conexão ao opcsim + tags + um flow com watchdog habilitado (ADR-009
    revisado: watchdog é por flow, não por conexão) no par 1 do opcsim, tudo já `up` e com
    o watchdog do flow vivo.

    Escopo de módulo: cada arquivo da suíte parte de um projeto limpo, e o teardown
    devolve a ativação à sentinela antes de excluir (excluir o ativo é 409). O flow do
    watchdog nunca é implantado (`desired_state` fica `stopped`): o opc-worker descobre
    watchdogs de flow pela tabela `flows` direto (`load_active_configuration`), não pelo
    runtime dos blocos — não precisa de grafo nem de deploy para o par de nodes ficar vivo.
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
                "endpoint": opcsim_standalone,
                "security_policy": "none",
                "security_mode": "none",
                "auth_mode": "anonymous",
            },
        )
        assert r.status_code == 201, f"criação da conexão falhou: HTTP {r.status_code} {r.text}"
        conn_id = int(r.json()["id"])
        r = admin.post(
            "/api/flows",
            json={"project_id": projeto["id"], "name": f"watchdog-{sufixo}", "ts_seconds": 1},
        )
        assert r.status_code == 201, (
            f"criação do flow do watchdog falhou: HTTP {r.status_code} {r.text}"
        )
        flow_id = int(r.json()["id"])
        r = admin.put(
            f"/api/flows/{flow_id}",
            json={
                "watchdog_enabled": True,
                "watchdog_connection_id": conn_id,
                "watchdog_read_node_id": NODE_WD_TO_SYSTEM,
                "watchdog_write_node_id": NODE_WD_FROM_SYSTEM,
                "watchdog_period_ms": 1000,
            },
        )
        assert r.status_code == 200, (
            f"habilitar watchdog do flow falhou: HTTP {r.status_code} {r.text}"
        )
        ambiente = Ambiente(
            project_id=projeto["id"],
            conn_id=conn_id,
            flow_id=flow_id,
            sine=_criar_tag(admin, conn_id, "sine", NODE_SINE, "r"),
            static=_criar_tag(admin, conn_id, "static", NODE_STATIC, "r"),
            mirror=_criar_tag(admin, conn_id, "mirror", NODE_MIRROR_FLOAT, "r"),
            w_float=_criar_tag(admin, conn_id, "w_float", NODE_W_FLOAT, "w"),
        )
        esperar_conexao(conn_id)
        esperar_flow_watchdog(flow_id, conn_id)
        yield ambiente
    finally:
        _ativar_sentinela(admin)
        admin.delete(f"/api/projects/{projeto['id']}")


# ============================================================================
# F4b — malha fechada MPC↔TFS (tarefa 4.1, spec F4 §9.2)
# ============================================================================
#
# `mv_pid` é a única MV que fecha malha física: escreve no `write_tag_id` (espelho do
# opcsim `NODE_W_FLOAT`), e a MESMA tag de `readback_tag_id` é reaproveitada como fonte do
# `opc_read` que alimenta a TFS `planta` — é assim que "o TFS fecha malha sem PLC" (ADR-022)
# sem formar ciclo no grafo: uma aresta de volta ao próprio `mpc1` seria rejeitada por
# `_check_cycles` (spec §2.2). `mv_direta` nunca sai do LOCAL/`initial_value` — entra na
# matriz `models` só pra satisfazer "cada MV com ≥1 par habilitado" (spec §2.2-3).

TS_FLOW_MPC = 0.5
"""Ts do flow dos cenários E2E-F4 — pequeno pra rodar rápido (brief da tarefa)."""
MULTIPLICADOR_MPC = 2
TS_MPC = TS_FLOW_MPC * MULTIPLICADOR_MPC  # 1.0 s

GANHO_CV = 1.0
TAU1_CV = 2.0
TAU2_CV = 0.5
"""SOPDT de `cv1` (settle ~4×(τ1+τ2)=10s) — mesmos números no `models` do MPC e na matriz
da TFS `planta`: sem mismatch deliberado de modelo, o E2E-F4-04 testa a malha fechada de
verdade, não a robustez a erro de modelo (isso é TDD, spec §9.1)."""
GANHO_INTEGRADOR_CO = 0.01
"""Ki de `co1` (IOPDT) — fraco o bastante pra `mv_pid` chegar a um SP moderado sem estourar
a faixa (E2E-F4-04), mas um SP perto do teto de `LIMITES_SP_CV` (E2E-F4-05) estoura mesmo
assim: só `mv_pid` move `co1` de verdade (`mv_direta` entra com Ki desprezível)."""

LIMITES_MV = {"min": 0.0, "max": 100.0}
DU_MAX_MV = 5.0
LIMITES_SP_CV = {"min": 0.0, "max": 100.0}
FAIXA_CO = {"low": -5.0, "high": 5.0}
VALOR_DV = 2.0
TSS_MALHA = 10.0
"""TSS de `cv1`/`co1` — `Np=ceil(10/1)=10`, `Nc=max(2,ceil(10/4))=3` (spec §2.2-5)."""


@dataclass(frozen=True, slots=True)
class AmbienteMpc:
    """Projeto+conexão do E2E-F4 e as 4 tags do `pid` de `mv_pid` (spec §2.1-3)."""

    project_id: int
    conn_id: int
    write: int
    mode_cmd: int
    readback: int
    mode_read: int


@pytest.fixture(scope="module")
def ambiente_mpc(
    admin: httpx.Client, request: pytest.FixtureRequest, opcsim_standalone: str
) -> Iterator[AmbienteMpc]:
    """Projeto ativo + conexão ao opcsim + as tags do `pid` de `mv_pid` — mesmo padrão de
    `projeto_com_conexao`, módulo à parte porque o F4b usa 4 tags diferentes das da F2 (dois
    pares w/espelho: float pra posição, int pra modo)."""
    sufixo = f"{request.module.__name__.rsplit('.', 1)[-1]}-{RUN_ID}"
    r = admin.post("/api/projects", json={"name": f"f4-{sufixo}", "description": "L2 da F4b"})
    assert r.status_code == 201, f"criação do projeto falhou: HTTP {r.status_code} {r.text}"
    projeto = r.json()
    try:
        assert admin.post(f"/api/projects/{projeto['id']}/activate").status_code == 200
        r = admin.post(
            "/api/connections",
            json={
                "project_id": projeto["id"],
                "name": f"opcsim-{sufixo}",
                "endpoint": opcsim_standalone,
                "security_policy": "none",
                "security_mode": "none",
                "auth_mode": "anonymous",
            },
        )
        assert r.status_code == 201, f"criação da conexão falhou: HTTP {r.status_code} {r.text}"
        conn_id = int(r.json()["id"])
        ambiente = AmbienteMpc(
            project_id=projeto["id"],
            conn_id=conn_id,
            write=_criar_tag(admin, conn_id, "mv-pid-write", NODE_W_FLOAT, "w"),
            mode_cmd=_criar_tag(admin, conn_id, "mv-pid-mode-cmd", NODE_W_INT, "w"),
            readback=_criar_tag(admin, conn_id, "mv-pid-readback", NODE_MIRROR_FLOAT, "r"),
            mode_read=_criar_tag(admin, conn_id, "mv-pid-mode-read", NODE_MIRROR_INT, "r"),
        )
        esperar_conexao(conn_id)
        yield ambiente
    finally:
        _ativar_sentinela(admin)
        admin.delete(f"/api/projects/{projeto['id']}")


def criar_tag_leitura_dummy(admin: httpx.Client, conn_id: int, nome: str) -> int:
    """Tag `r` genérica (aponta pro `NODE_SINE`) — só pra satisfazer "entrada obrigatória"
    em grafos de validação (E2E-F4-02) que não precisam de dinâmica real. O nome recebe um
    sufixo único por chamada: os três sub-grafos do E2E-F4-02 compartilham a mesma conexão e
    "nome de tag já em uso nesta conexão" é 409 (mesma barreira da F2)."""
    return _criar_tag(admin, conn_id, f"{nome}-{valor_unico()}", NODE_SINE, "r")


def _matriz_planta() -> list[list[dict]]:
    """`u1` (mv_pid via `mv_readback`) alimenta `y1` (cv1, self-reg) e `y2` (co1,
    integrador); `u2` fica desabilitado nas duas linhas e não precisa de aresta (mesma nota
    de `matriz_integrador`, F3 §3.4 — só a coluna com elemento habilitado é obrigatória,
    spec §3.4/`_required_input_handles`)."""
    desabilitado = {"enabled": False, "kind": "iopdt", "params": {"Ki": 0.0, "theta": 0.0}}
    y1 = [
        {
            "enabled": True,
            "kind": "sopdt",
            "params": {"K": GANHO_CV, "tau1": TAU1_CV, "tau2": TAU2_CV, "theta": 0.0},
        },
        dict(desabilitado),
    ]
    y2 = [
        {"enabled": True, "kind": "iopdt", "params": {"Ki": GANHO_INTEGRADOR_CO, "theta": 0.0}},
        dict(desabilitado),
    ]
    return [y1, y2]


def _config_mpc_malha(ambiente: AmbienteMpc, *, multiplier: int = MULTIPLICADOR_MPC) -> dict:
    """Config do bloco `mpc` do E2E-F4 (spec §2.1): `mv_pid` fecha a malha física via OPC
    (ADR-022); `mv_direta` só precisa de um par na matriz pra passar na validação (spec
    §2.2-3) — sem aresta no grafo, nunca sai do LOCAL/`initial_value`."""
    pid = {
        "write_tag_id": ambiente.write,
        "target_mode": "rcas",
        "mode_cmd_tag_id": ambiente.mode_cmd,
        "mode_read_tag_id": ambiente.mode_read,
        "readback_tag_id": ambiente.readback,
        "mode_values": {"auto": 1, "target": 3},
    }
    return {
        "name": "MPC E2E-F4",
        "multiplier": multiplier,
        "variables": {
            "mvs": [
                {
                    "id": "mv_pid",
                    "name": "MV com PID",
                    "eu": "%",
                    "limits": dict(LIMITES_MV),
                    # EU/s -> mesmo DU_MAX_MV por ciclo
                    "max_rate": DU_MAX_MV / (TS_FLOW_MPC * multiplier),
                    "initial_value": 0.0,
                    "pid": pid,
                },
                {
                    "id": "mv_direta",
                    "name": "MV direta",
                    "eu": "%",
                    "limits": dict(LIMITES_MV),
                    # EU/s -> mesmo DU_MAX_MV por ciclo
                    "max_rate": DU_MAX_MV / (TS_FLOW_MPC * multiplier),
                    "initial_value": 0.0,
                },
            ],
            "cvs": [
                {
                    "id": "cv_1",
                    "name": "CV da malha",
                    "eu": "C",
                    "kind": "selfreg",
                    "tss": TSS_MALHA,
                    "weight": 1.0,
                    "sp_limits": dict(LIMITES_SP_CV),
                }
            ],
            "constraints": [
                {
                    "id": "co_1",
                    "name": "Restrição da malha",
                    "eu": "%",
                    "kind": "integrating",
                    "tss": TSS_MALHA,
                    "range": dict(FAIXA_CO),
                    "priority": 1,
                }
            ],
            "dvs": [{"id": "dv_1", "name": "DV constante", "eu": "m3/h"}],
        },
        "models": {
            "cv_1": {
                "mv_pid": {
                    "enabled": True,
                    "params": {"K": GANHO_CV, "tau1": TAU1_CV, "tau2": TAU2_CV, "theta": 0.0},
                },
                "dv_1": {
                    "enabled": True,
                    "params": {"K": 0.05, "tau1": TAU1_CV, "tau2": TAU2_CV, "theta": 0.0},
                },
            },
            "co_1": {
                "mv_pid": {
                    "enabled": True,
                    "params": {"Ki": GANHO_INTEGRADOR_CO, "theta": 0.0},
                },
                "mv_direta": {"enabled": True, "params": {"Ki": 1e-4, "theta": 0.0}},
            },
        },
    }


def grafo_mpc_tfs(
    ambiente: AmbienteMpc, *, valor_dv: float = VALOR_DV, mpc_id: str = "mpc1"
) -> dict:
    """Grafo E2E-F4 (spec §9.2): `mv_readback` (`opc_read` do espelho de `mv_pid`) alimenta a
    TFS `planta`; `planta` fecha em `cv1`/`co1` do MPC. `mv_pid` fecha a malha só pelo OPC
    (ADR-022) — uma aresta de volta do `mpc1` pra `planta`/`mv_readback` formaria ciclo no
    grafo, rejeitado pela validação (`_check_cycles`)."""
    dados = _config_mpc_malha(ambiente)
    nodes = [
        {
            "id": "mv_readback",
            "type": "opc_read",
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": 1, "tag_id": ambiente.readback},
        },
        {
            "id": "dv_source",
            "type": "script",
            "position": {"x": 0.0, "y": 0.0},
            "data": {
                "exec_order": 2,
                "n_inputs": 0,
                "n_outputs": 1,
                "code": f"OUT1 = {valor_dv!r}\n",
            },
        },
        {
            "id": "planta",
            "type": "tfs",
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": 3, "matrix": _matriz_planta()},
        },
        {
            "id": mpc_id,
            "type": "mpc",
            "position": {"x": 0.0, "y": 0.0},
            "data": {"exec_order": 4, **dados},
        },
    ]
    edges = [
        {
            "id": "e1",
            "source": "mv_readback",
            "sourceHandle": "out",
            "target": "planta",
            "targetHandle": "u1",
        },
        {
            "id": "e2",
            "source": "planta",
            "sourceHandle": "y1",
            "target": mpc_id,
            "targetHandle": "cv_1",
        },
        {
            "id": "e3",
            "source": "planta",
            "sourceHandle": "y2",
            "target": mpc_id,
            "targetHandle": "co_1",
        },
        {
            "id": "e4",
            "source": "dv_source",
            "sourceHandle": "OUT1",
            "target": mpc_id,
            "targetHandle": "dv_1",
        },
    ]
    return {"nodes": nodes, "edges": edges}


def resetar_atuador_mpc(opcsim_client: OpcSim, *, timeout: float = 5.0) -> None:
    """Zera a posição física de `mv_pid` (`NODE_W_FLOAT`) e espera o espelho refletir — os 5
    cenários compartilham os mesmos nodes globais do opcsim (só há um par w/espelho float),
    então sem isso o estado físico de um cenário vazaria pro início do próximo (a TFS
    `planta` nasce zerada a cada deploy, mas `u1` seguiria lendo o valor velho até `mv_pid`
    escrever de novo)."""
    opcsim_client.write(NODE_W_FLOAT, 0.0)
    esperar_ate(
        lambda: abs(opcsim_client.read(NODE_MIRROR_FLOAT)) < 1e-6,
        timeout=timeout,
        intervalo=0.2,
        descricao="espelho de mv_pid zerar após o reset",
    )
    time.sleep(1.0)  # propagação até o `ValueSnapshot` do flow-runtime via opc-worker


def _health_do_runtime() -> dict[str, Any] | None:
    """`/health` do flow-runtime, lido de dentro do container — cópia local de
    `f3_support.runtime_health`: este `conftest` não pode importar de `f3_support.py`
    porque `f3_support.py` já importa deste módulo (ciclo)."""
    try:
        return json.loads(
            compose(
                "exec",
                "-T",
                "flow-runtime",
                "python",
                "-c",
                "import urllib.request;"
                "print(urllib.request.urlopen('http://localhost:8002/health', "
                "timeout=3).read().decode())",
            )
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return None


def _aguardar_flow_parado_mpc(flow_id: int, *, timeout: float = 60.0) -> None:
    """Espera o runtime materializar a parada antes de excluir o flow — evita que uma
    varredura órfã continue escrevendo em `mv_pid` (tag global do opcsim) depois que o
    teste já seguiu para o próximo cenário."""

    def parado() -> bool:
        saude = _health_do_runtime()
        if saude is None:
            return True
        flow = saude.get("flows", {}).get(str(flow_id))
        return flow is None or flow["state"] != "running"

    esperar_ate(parado, timeout=timeout, intervalo=1.0, descricao=f"flow {flow_id} deixar de rodar")


def deploy_flow(admin: httpx.Client, flow_id: int) -> None:
    r = admin.post(f"/api/flows/{flow_id}/deploy")
    assert r.status_code == 202, f"deploy do flow {flow_id}: HTTP {r.status_code} {r.text}"


@pytest.fixture
def criar_flow_mpc(admin: httpx.Client, ambiente_mpc: AmbienteMpc) -> Iterator[Callable[..., int]]:
    """Cria flows no projeto do `ambiente_mpc`; teardown para, espera e exclui — mesmo padrão
    de `fabrica_de_flows` (F3), cópia local pela mesma razão de import cíclico."""
    criados: list[int] = []

    def criar(nome: str, *, ts_seconds: float = TS_FLOW_MPC, grafo: dict | None = None) -> int:
        r = admin.post(
            "/api/flows",
            json={
                "project_id": ambiente_mpc.project_id,
                "name": f"{nome}-{RUN_ID}",
                "ts_seconds": ts_seconds,
            },
        )
        assert r.status_code == 201, f"criação do flow {nome}: HTTP {r.status_code} {r.text}"
        flow_id = int(r.json()["id"])
        criados.append(flow_id)
        if grafo is not None:
            r = admin.put(f"/api/flows/{flow_id}", json={"graph_json": grafo})
            assert r.status_code == 200, f"PUT do grafo de {nome}: HTTP {r.status_code} {r.text}"
        # ADR-009 revisado: watchdog é por flow. Todo flow MPC escreve MVs em OPC — sem
        # watchdog próprio, o gate recusa como `no_watchdog` e a malha nunca fecha.
        admin.put(
            f"/api/flows/{flow_id}",
            json={
                "watchdog_enabled": True,
                "watchdog_connection_id": ambiente_mpc.conn_id,
                "watchdog_read_node_id": NODE_WD_TO_SYSTEM,
                "watchdog_write_node_id": NODE_WD_FROM_SYSTEM,
                "watchdog_period_ms": 1000,
            },
        )
        esperar_flow_watchdog(flow_id, ambiente_mpc.conn_id)
        return flow_id

    try:
        yield criar
    finally:
        for flow_id in reversed(criados):
            admin.post(f"/api/flows/{flow_id}/stop")
            _aguardar_flow_parado_mpc(flow_id)
            admin.delete(f"/api/flows/{flow_id}")


def operar_modo(admin: httpx.Client, flow_id: int, block_id: str, axis: str, value: str) -> None:
    r = admin.post(f"/api/operate/{flow_id}/{block_id}/mode", json={"axis": axis, "value": value})
    assert r.status_code == 202, f"POST /operate mode: HTTP {r.status_code} {r.text}"


def operar_sp(admin: httpx.Client, flow_id: int, block_id: str, var_id: str, value: float) -> None:
    r = admin.post(f"/api/operate/{flow_id}/{block_id}/sp", json={"var_id": var_id, "value": value})
    assert r.status_code == 202, f"POST /operate sp: HTTP {r.status_code} {r.text}"


def operar_mv(admin: httpx.Client, flow_id: int, block_id: str, var_id: str, value: float) -> None:
    r = admin.post(f"/api/operate/{flow_id}/{block_id}/mv", json={"var_id": var_id, "value": value})
    assert r.status_code == 202, f"POST /operate mv: HTTP {r.status_code} {r.text}"


class EstadoMpcStream:
    """Leitor de `mpc.state.<flow_id>.<block_id>` pelo `/ws` real (spec §6.2) — assinatura
    aberta ANTES do gatilho, mesmo estilo de `EventStream`/`StatusStream` (F3), mas em cima
    de um WebSocket de verdade: a tarefa pede API + WS + opcsim reais, não o barramento
    direto."""

    def __init__(self, ws: Any, canal: str) -> None:
        self._ws = ws
        self._canal = canal

    def proxima(self, *, timeout: float, descricao: str) -> dict[str, Any]:
        limite = time.monotonic() + timeout
        while True:
            restante = limite - time.monotonic()
            if restante <= 0:
                raise AssertionError(f"{descricao}: nenhum mpc.state em {timeout:.0f}s")
            try:
                quadro = json.loads(self._ws.recv(timeout=restante))
            except TimeoutError:
                continue
            if quadro.get("channel") == self._canal:
                return quadro["data"]

    def esperar(
        self, pred: Callable[[dict[str, Any]], bool], *, timeout: float, descricao: str
    ) -> dict[str, Any]:
        limite = time.monotonic() + timeout
        while True:
            restante = limite - time.monotonic()
            if restante <= 0:
                raise AssertionError(
                    f"{descricao}: nenhum mpc.state correspondente em {timeout:.0f}s"
                )
            estado = self.proxima(timeout=restante, descricao=descricao)
            if pred(estado):
                return estado

    def coletar(self, *, quantidade: int, timeout: float, descricao: str) -> list[dict[str, Any]]:
        limite = time.monotonic() + timeout
        amostras: list[dict[str, Any]] = []
        while len(amostras) < quantidade:
            restante = limite - time.monotonic()
            if restante <= 0:
                raise AssertionError(
                    f"{descricao}: {len(amostras)} de {quantidade} amostras em {timeout:.0f}s"
                )
            amostras.append(self.proxima(timeout=restante, descricao=descricao))
        return amostras


@contextmanager
def assinar_mpc_state(
    admin: httpx.Client, flow_id: int, block_id: str
) -> Iterator[EstadoMpcStream]:
    """Abre o `/ws` real, autentica com o token do `admin` e assina `mpc_state` do bloco —
    mesmo `abrir_ws` da F3 (`test_f3_lifecycle.py`), cópia local pela mesma razão de ciclo."""
    url = f"{BASE.replace('http://', 'ws://').rstrip('/')}/ws"
    token = admin.headers["Authorization"].removeprefix("Bearer ")
    try:
        ws = connect(f"{url}?token={token}", open_timeout=15)
    except InvalidStatus as erro:
        raise AssertionError(
            f"o nginx recusou o upgrade do /ws com HTTP {erro.response.status_code}"
        ) from None
    try:
        ws.send(json.dumps({"subscribe": {"mpc_state": [f"{flow_id}/{block_id}"]}}))
        yield EstadoMpcStream(ws, channel_mpc_state(flow_id, block_id))
    finally:
        ws.close()


# ============================================================================
# F4b — falhas, /operate, WS e hot-swap (tarefa 4.2, spec F4 §9.2 E2E-F4-06..10)
# ============================================================================


def evento_mpc(kind: str, flow_id: int, block_id: str) -> Callable[[dict[str, Any]], bool]:
    """Predicado de evento do canal `events` por `kind` e origem de bloco MPC (spec §5.3) —
    mesmo padrão de `evento_de` (F2), mas por `origin` (`flow:<fid>/block:<bid>`) em vez de
    `conn_id`: os eventos do MPC não carregam `conn_id` no payload."""
    origem = f"flow:{flow_id}/block:{block_id}"

    def casa(evento: dict[str, Any]) -> bool:
        return evento.get("origin") == origem and evento.get("payload", {}).get("kind") == kind

    return casa


def mpc_block_health(flow_id: int, block_id: str) -> dict[str, Any] | None:
    """`flows.<flow_id>.mpc.<block_id>` do `/health` do flow-runtime (spec §4.10) — `None`
    enquanto o runtime não conhece o flow ou o bloco (ainda não deployado, ou não é `mpc`)."""
    saude = _health_do_runtime()
    if saude is None:
        return None
    flow = saude.get("flows", {}).get(str(flow_id))
    if flow is None:
        return None
    return flow.get("mpc", {}).get(block_id)


def armar_ate_remoto(
    admin: httpx.Client, fluxo: EstadoMpcStream, flow_id: int, block_id: str
) -> None:
    """LOCAL→REMOTO(MAN) com confirmação (spec §4.4) — pra blocos com MV(s) `pid` cujo
    `mode_read` alimenta o watchdog de armar/shed (`mpc_arming.watch_arm`): espera a
    transição aparecer no `mpc.state` e depois confere que ela NÃO reverte dentro da
    janela de confirmação (2×Ts_mpc) — reverter seria `mpc_arm_failed{reason:no_confirm}`,
    o oposto do que este helper afirma. Mesmo padrão de `_armar_ate_remoto` em
    `test_f4_mpc.py` (tarefa 4.1), aqui compartilhado entre os arquivos da tarefa 4.2."""
    # Precondição (tarefa 4.1): aguardar host pronto antes de armar
    fluxo.esperar(
        lambda e: e.get("status", {}).get("solver") != "building",
        timeout=60.0,
        descricao=f"{block_id} host ready (não building)",
    )
    operar_modo(admin, flow_id, block_id, "local_remote", "remote")
    fluxo.esperar(
        lambda e: e["modes"]["local_remote"] == "remote",
        timeout=10.0,
        descricao=f"{block_id} pra REMOTO",
    )
    janela = fluxo.coletar(
        quantidade=3,
        timeout=TS_MPC * 3 + 5.0,
        descricao=f"{block_id} janela de confirmação do arme",
    )
    assert all(e["modes"]["local_remote"] == "remote" for e in janela), (
        f"{block_id} reverteu pra LOCAL durante a janela de confirmação — "
        f"mpc_arm_failed(no_confirm)? "
        f"série: {[e['modes']['local_remote'] for e in janela]}"
    )


def armar_remoto_direto(
    admin: httpx.Client, fluxo: EstadoMpcStream, flow_id: int, block_id: str
) -> None:
    """LOCAL→REMOTO(MAN) para um bloco sem nenhuma MV com `pid`+`mode_read`: sem alvo pra
    confirmar, `watch_arm` devolve na hora (spec §4.4/§4.5 — "sem mode_read, sem shed") e a
    transição nunca reverte, então não há janela de confirmação a esperar aqui."""
    # Precondição (tarefa 4.1): aguardar host pronto antes de armar
    fluxo.esperar(
        lambda e: e.get("status", {}).get("solver") != "building",
        timeout=60.0,
        descricao=f"{block_id} host ready (não building)",
    )
    operar_modo(admin, flow_id, block_id, "local_remote", "remote")
    fluxo.esperar(
        lambda e: e["modes"]["local_remote"] == "remote",
        timeout=10.0,
        descricao=f"{block_id} pra REMOTO",
    )


def armar_auto_com_retentativa(
    admin: httpx.Client,
    fluxo: EstadoMpcStream,
    flow_id: int,
    block_id: str,
    *,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """MAN→AUTO reenviando o comando até o `mpc.state` confirmar (spec §4.4): o gate
    `host.ready` pode não estar pronto na 1ª tentativa (build do do-mpc em segundo plano,
    spec §4.1) — a API não sabe quando o worker termina, então o cliente reenvia, igual a
    um operador de verdade clicando de novo depois do `mpc_arm_failed{reason:worker_not_ready}`."""
    limite = time.monotonic() + timeout
    while True:
        operar_modo(admin, flow_id, block_id, "man_auto", "auto")
        try:
            return fluxo.esperar(
                lambda e: e["modes"]["man_auto"] == "auto",
                timeout=5.0,
                descricao=f"{block_id} pra AUTO",
            )
        except AssertionError:
            if time.monotonic() >= limite:
                raise
