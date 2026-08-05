"""Testes do runtime de conexão do opc-worker (spec F2 §2.2-2/3, §3.6).

Tudo roda contra o opcsim in-process (nunca contra PLC real) e contra o Redis real da
fixture da raiz, com assinante de teste no canal `events`.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from asyncua import Client
from asyncua.client.ua_client import UaClientState
from cryptography.fernet import Fernet
from redis.asyncio import Redis

from opcsim import NODE_WD_FROM_SYSTEM, NODE_WD_TO_SYSTEM, OpcSimServer, free_port
from ottima_core.bus import CHANNEL_EVENTS, KIND_COMM_FAILURE, KIND_COMM_RESTORED
from ottima_core.security import encrypt_secret
from ottima_opc_worker.connection import ConnectionRuntime, backoff_delay
from ottima_opc_worker.state import (
    ConnectionConfig,
    ConnectionSnapshot,
    ConnectionState,
    TagConfig,
)
from worker_test_helpers import await_until, collecting

# Backoff curto: os testes não podem esperar o 1→2→4 s de produção.
TEST_BACKOFF_INITIAL_S = 0.05
TEST_BACKOFF_MAX_S = 0.2
# Janela para provar que algo NÃO acontece (várias tentativas de reconexão em backoff).
QUIET_WINDOW_S = 1.0


def make_config(
    endpoint: str,
    *,
    conn_id: int = 7,
    with_watchdog: bool = False,
    auth_mode: str = "anonymous",
    auth_username: str | None = None,
    auth_password_enc: str | None = None,
) -> ConnectionConfig:
    return ConnectionConfig(
        id=conn_id,
        project_id=1,
        name="Forno 1",
        endpoint=endpoint,
        security_policy="none",
        security_mode="none",
        auth_mode=auth_mode,
        auth_username=auth_username,
        auth_password_enc=auth_password_enc,
        server_cert_file=None,
        watchdog_read_node_id=NODE_WD_TO_SYSTEM if with_watchdog else None,
        watchdog_write_node_id=NODE_WD_FROM_SYSTEM if with_watchdog else None,
        watchdog_period_ms=1000,
        tags=(),
    )


def make_runtime(
    config: ConnectionConfig, redis_client: Redis, snapshot: ConnectionSnapshot, **kwargs
) -> ConnectionRuntime:
    return ConnectionRuntime(
        config,
        redis_client,
        snapshot,
        backoff_initial_s=TEST_BACKOFF_INITIAL_S,
        backoff_max_s=TEST_BACKOFF_MAX_S,
        **kwargs,
    )


def collect_events(redis_client: Redis) -> AsyncIterator[list[dict]]:
    return collecting(redis_client, CHANNEL_EVENTS)


def of_kind(events: list[dict], kind: str) -> list[dict]:
    return [event for event in events if event["payload"]["kind"] == kind]


@asynccontextmanager
async def running(runtime: ConnectionRuntime) -> AsyncIterator[ConnectionRuntime]:
    await runtime.start()
    try:
        yield runtime
    finally:
        await runtime.stop()


# --- lógica pura -------------------------------------------------------------------


def test_backoff_cresce_exponencialmente_e_satura_no_teto(monkeypatch: pytest.MonkeyPatch) -> None:
    """O topo do sorteio dobra a cada tentativa e para no teto (spec §2.2-2)."""
    monkeypatch.setattr(random, "uniform", lambda _low, high: high)
    tops = [backoff_delay(n, initial=1.0, maximum=30.0) for n in range(7)]
    assert tops == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


def test_backoff_tem_full_jitter_dentro_do_intervalo() -> None:
    """Full jitter: o valor sorteado nunca sai de [0, topo] (spec §2.2-2)."""
    random.seed(20260803)
    for attempt in range(12):
        top = min(30.0, 1.0 * 2**attempt)
        for _ in range(20):
            assert 0.0 <= backoff_delay(attempt, initial=1.0, maximum=30.0) <= top


def test_backoff_nao_estoura_com_muitas_tentativas() -> None:
    """Conexão fora do ar por horas acumula centenas de tentativas sem quebrar o float."""
    assert backoff_delay(5000, initial=1.0, maximum=30.0) <= 30.0


def test_has_watchdog_exige_os_dois_node_ids() -> None:
    completo = make_config("opc.tcp://x", with_watchdog=True)
    assert completo.has_watchdog is True
    assert make_config("opc.tcp://x").has_watchdog is False
    assert replace(completo, watchdog_write_node_id=None).has_watchdog is False


def test_session_key_ignora_tags_e_tags_key_ordena_por_id() -> None:
    """A 1.4 recria a sessão só quando muda a conexão; tag nova mexe só na subscription."""
    tag_a = TagConfig(id=2, name="a", node_id="ns=2;s=a", direction="r", data_type="float")
    tag_b = TagConfig(id=1, name="b", node_id="ns=2;s=b", direction="w", data_type="bool")
    base = make_config("opc.tcp://x")
    com_tags = replace(base, tags=(tag_a, tag_b))
    assert com_tags.session_key == base.session_key
    assert com_tags.tags_key == (tag_b, tag_a)
    assert replace(base, endpoint="opc.tcp://y").session_key != base.session_key


def test_to_health_tem_as_chaves_da_spec_em_ordem() -> None:
    momento = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    snapshot = ConnectionSnapshot(name="Forno 1", session_up_since=momento, tags_subscribed=3)
    health = snapshot.to_health()
    assert list(health) == [
        "name",
        "state",
        "watchdog_alive",
        "session_up_since",
        "last_publish_ts",
        "tags_subscribed",
        "monitored_errors",
        "write_errors",
    ]
    assert health["state"] == "connecting"
    assert health["session_up_since"] == "2026-08-03T12:00:00+00:00"
    assert health["last_publish_ts"] is None
    assert json.dumps(health)  # o /health serializa direto: nada de datetime cru


# --- máquina de estados contra o opcsim --------------------------------------------


async def test_conecta_e_sobe_sem_emitir_restored(sim: OpcSimServer, redis_client: Redis) -> None:
    """Primeira subida é edge-triggered: não houve falha antes, então nada de restored."""
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_events(redis_client) as events:
        async with running(make_runtime(config, redis_client, snapshot)) as runtime:
            await await_until(lambda: runtime.state is ConnectionState.UP)
            assert runtime.client is not None
            assert snapshot.state is ConnectionState.UP
            assert snapshot.session_up_since is not None
        assert of_kind(events, KIND_COMM_RESTORED) == []
        assert of_kind(events, KIND_COMM_FAILURE) == []


async def test_porta_errada_falha_uma_vez_e_retries_nao_reemitem(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transição para `failed` emite 1 evento; tentativas em backoff não re-emitem."""
    from ottima_opc_worker import connection as connection_module

    tentativas = 0
    real_build_client = connection_module.build_client

    def contando(*args, **kwargs):
        nonlocal tentativas
        tentativas += 1
        return real_build_client(*args, **kwargs)

    monkeypatch.setattr(connection_module, "build_client", contando)

    config = make_config(f"opc.tcp://127.0.0.1:{free_port()}/ottima/opcsim/", conn_id=42)
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_events(redis_client) as events:
        async with running(make_runtime(config, redis_client, snapshot)) as runtime:
            await await_until(lambda: runtime.state is ConnectionState.FAILED)
            falhas = of_kind(events, KIND_COMM_FAILURE)
            assert len(falhas) == 1
            assert falhas[0]["severity"] == "alarm"
            assert falhas[0]["origin"] == "conn:42"
            assert falhas[0]["payload"]["reason"] == "connect_failed"
            assert falhas[0]["payload"]["conn_id"] == 42

            await await_until(lambda: tentativas >= 4)
            await asyncio.sleep(QUIET_WINDOW_S)
            assert len(of_kind(events, KIND_COMM_FAILURE)) == 1
            assert runtime.state is ConnectionState.FAILED
            assert runtime.client is None


async def test_queda_do_servidor_gera_session_lost(sim: OpcSimServer, redis_client: Redis) -> None:
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_events(redis_client) as events:
        async with running(make_runtime(config, redis_client, snapshot)) as runtime:
            await await_until(lambda: runtime.state is ConnectionState.UP)
            await sim.stop()
            await await_until(lambda: runtime.state is ConnectionState.FAILED)
            falhas = of_kind(events, KIND_COMM_FAILURE)
            assert len(falhas) == 1
            assert falhas[0]["payload"]["reason"] == "session_lost"
            assert snapshot.state is ConnectionState.FAILED
            assert snapshot.session_up_since is None


async def test_religar_emite_comm_restored_sem_watchdog(redis_client: Redis) -> None:
    """Conexão sem watchdog: a própria volta da sessão restabelece a comunicação."""
    port = free_port()
    sim = OpcSimServer(port=port)
    await sim.start()
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_events(redis_client) as events:
        async with running(make_runtime(config, redis_client, snapshot)) as runtime:
            await await_until(lambda: runtime.state is ConnectionState.UP)
            await sim.stop()
            await await_until(lambda: runtime.state is ConnectionState.FAILED)

            sim = OpcSimServer(port=port)
            await sim.start()
            try:
                await await_until(lambda: runtime.state is ConnectionState.UP)
                await await_until(lambda: len(of_kind(events, KIND_COMM_RESTORED)) == 1)
                restaurado = of_kind(events, KIND_COMM_RESTORED)[0]
                assert restaurado["severity"] == "info"
                assert restaurado["origin"] == f"conn:{config.id}"
                assert restaurado["payload"]["conn_id"] == config.id
                await asyncio.sleep(QUIET_WINDOW_S)
                assert len(of_kind(events, KIND_COMM_RESTORED)) == 1
            finally:
                await sim.stop()


async def test_com_watchdog_nao_emite_restored_nesta_camada(redis_client: Redis) -> None:
    """Com watchdog quem emite `comm_restored` é a alternância do bit (tarefa 2.1)."""
    port = free_port()
    sim = OpcSimServer(port=port)
    await sim.start()
    config = make_config(sim.endpoint, with_watchdog=True)
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_events(redis_client) as events:
        async with running(make_runtime(config, redis_client, snapshot)) as runtime:
            await await_until(lambda: runtime.state is ConnectionState.UP)
            await sim.stop()
            await await_until(lambda: runtime.state is ConnectionState.FAILED)

            sim = OpcSimServer(port=port)
            await sim.start()
            try:
                await await_until(lambda: runtime.state is ConnectionState.UP)
                await asyncio.sleep(QUIET_WINDOW_S)
                assert of_kind(events, KIND_COMM_RESTORED) == []
            finally:
                await sim.stop()


async def test_senha_nunca_vaza_no_evento_nem_no_snapshot(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Token cifrado com outra chave: falha dura genérica, sem eco do segredo."""
    senha = "senha-secreta-do-plc"
    token = encrypt_secret(senha, key=Fernet.generate_key().decode())
    config = make_config(
        sim.endpoint,
        auth_mode="user_password",
        auth_username="operador",
        auth_password_enc=token,
    )
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = make_runtime(
        config, redis_client, snapshot, fernet_key=Fernet.generate_key().decode()
    )
    async with collect_events(redis_client) as events:
        async with running(runtime):
            await await_until(lambda: runtime.state is ConnectionState.FAILED)
            falha = of_kind(events, KIND_COMM_FAILURE)[0]
            assert falha["payload"]["reason"] == "connect_failed"
            texto = json.dumps(falha, ensure_ascii=False)
            assert senha not in texto
            assert token not in texto
    snapshot_texto = repr(snapshot)
    assert senha not in snapshot_texto
    assert token not in snapshot_texto


async def test_stop_e_idempotente_e_nao_deixa_task(sim: OpcSimServer, redis_client: Redis) -> None:
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = make_runtime(config, redis_client, snapshot)
    await runtime.start()
    await await_until(lambda: runtime.state is ConnectionState.UP)
    await runtime.stop()
    await runtime.stop()
    assert runtime.client is None
    pendentes = [t for t in asyncio.all_tasks() if t.get_name() == f"opc-conn-{config.id}"]
    assert pendentes == []


async def test_fail_e_idempotente(sim: OpcSimServer, redis_client: Redis) -> None:
    """O watchdog (2.1) e o loop de sessão podem chamar fail() concorrentemente."""
    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = make_runtime(config, redis_client, snapshot)
    async with collect_events(redis_client) as events:
        await runtime.fail("session_lost", "primeira")
        await runtime.fail("session_lost", "segunda")
        await await_until(lambda: len(of_kind(events, KIND_COMM_FAILURE)) == 1)
        await asyncio.sleep(0.2)
        assert len(of_kind(events, KIND_COMM_FAILURE)) == 1
        assert runtime.state is ConnectionState.FAILED


async def test_reconexao_apos_session_lost_respeita_o_backoff(
    sim: OpcSimServer, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O backoff vale para o ciclo inteiro (spec §2.2-2), não só para falha de connect."""
    from ottima_opc_worker import connection as connection_module

    # uniform devolvendo o topo torna o atraso determinístico: initial == max == 0.4 s.
    monkeypatch.setattr(random, "uniform", lambda _low, high: high)
    atraso_s = 0.4
    linha_do_tempo: list[tuple[str, float]] = []
    real_build_client = connection_module.build_client
    real_backoff_delay = connection_module.backoff_delay

    def build_marcado(*args, **kwargs):
        linha_do_tempo.append(("connect", asyncio.get_running_loop().time()))
        return real_build_client(*args, **kwargs)

    def backoff_marcado(attempt: int, **kwargs) -> float:
        linha_do_tempo.append(("backoff", asyncio.get_running_loop().time()))
        return real_backoff_delay(attempt, **kwargs)

    monkeypatch.setattr(connection_module, "build_client", build_marcado)
    monkeypatch.setattr(connection_module, "backoff_delay", backoff_marcado)

    config = make_config(sim.endpoint)
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = ConnectionRuntime(
        config,
        redis_client,
        snapshot,
        backoff_initial_s=atraso_s,
        backoff_max_s=atraso_s,
    )
    async with running(runtime):
        await await_until(lambda: runtime.state is ConnectionState.UP)
        assert [passo for passo, _ in linha_do_tempo] == ["connect"]
        await sim.stop()
        await await_until(lambda: len(linha_do_tempo) >= 3)

    # Sem o backoff no caminho da queda a ordem seria connect, connect, backoff.
    assert [passo for passo, _ in linha_do_tempo[:3]] == ["connect", "backoff", "connect"]
    intervalo = linha_do_tempo[2][1] - linha_do_tempo[1][1]
    assert intervalo >= atraso_s * 0.9, f"reconexão sem throttle: {intervalo:.3f}s"


async def test_fail_concorrente_aborta_o_connect_em_voo(
    sim: OpcSimServer, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Connect que termina depois do alarme não pode ressuscitar a conexão (spec §3.6)."""
    from ottima_opc_worker import connection as connection_module

    real_build_client = connection_module.build_client
    clientes: list[Client] = []
    conectando = asyncio.Event()
    liberar = asyncio.Event()
    segunda_tentativa = asyncio.Event()

    def build_lento(*args, **kwargs) -> Client:
        client = real_build_client(*args, **kwargs)
        clientes.append(client)
        primeira = len(clientes) == 1
        real_connect = client.connect

        async def connect_lento(**connect_kwargs) -> None:
            if not primeira:
                # A reconexão legítima não interessa aqui: travá-la mantém a janela de
                # observação estável até o stop() cancelar a supervisão.
                segunda_tentativa.set()
                await asyncio.sleep(3600)
            conectando.set()
            await liberar.wait()
            await real_connect(**connect_kwargs)

        client.connect = connect_lento
        return client

    monkeypatch.setattr(connection_module, "build_client", build_lento)

    config = make_config(sim.endpoint)  # sem watchdog: seria o caso que emite restored
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = make_runtime(config, redis_client, snapshot)
    async with collect_events(redis_client) as events:
        async with running(runtime):
            await asyncio.wait_for(conectando.wait(), timeout=5.0)
            await runtime.fail("watchdog_timeout", "alarme durante o connect")
            liberar.set()
            # Sai também se a conexão subir: aí o assert seguinte aponta o defeito.
            await await_until(
                lambda: segunda_tentativa.is_set() or runtime.state is ConnectionState.UP
            )

            assert runtime.state is ConnectionState.FAILED
            assert runtime.client is None
            assert clientes[0].uaclient.state is UaClientState.DISCONNECTED
            assert len(of_kind(events, KIND_COMM_FAILURE)) == 1
            assert of_kind(events, KIND_COMM_RESTORED) == []
