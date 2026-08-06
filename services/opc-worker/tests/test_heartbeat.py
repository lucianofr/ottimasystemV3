"""Testes do heartbeat de valor do opc-worker (spec F2 §2.2-6, RF-204).

Tudo contra o opcsim in-process e o Redis real da fixture da raiz, com assinante no canal
`opc.values.<conn_id>`. O intervalo do heartbeat é injetado curto para o teste não esperar
tempo real.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from worker_test_helpers import await_until, collecting

from opcsim import NODE_SINE, NODE_STATIC, NODE_W_FLOAT, OpcSimServer, free_port
from ottima_core.bus import channel_opc_values
from ottima_opc_worker import heartbeat as heartbeat_module
from ottima_opc_worker import subscriptions
from ottima_opc_worker.connection import ConnectionRuntime
from ottima_opc_worker.heartbeat import ValueHeartbeat
from ottima_opc_worker.state import (
    ConnectionConfig,
    ConnectionSnapshot,
    ConnectionState,
    TagConfig,
)
from ottima_opc_worker.subscriptions import QUALITY_BAD, QUALITY_GOOD

CONN_ID = 9
# Janela para provar que algo NÃO acontece; cobre várias batidas do heartbeat de teste.
QUIET_WINDOW_S = 0.6

# Batida rápida: 0.3 s ⇒ tick de 30 ms.
FAST_INTERVAL_S = 0.3
# Folga sobre a cadência de 250 ms da subscription: tag que muda nunca chega nesta janela.
SLACK_INTERVAL_S = 1.0
# Longo o bastante para o laço não bater durante o teste da rajada.
IDLE_INTERVAL_S = 30.0

# Backoff curto: os testes não podem esperar o 1→2→4 s de produção.
TEST_BACKOFF_INITIAL_S = 0.05
TEST_BACKOFF_MAX_S = 0.2

# Relógio de parede fixo no passado: prova que a decisão do heartbeat não depende dele.
RELOGIO_PARA_TRAS = datetime(2020, 1, 1, tzinfo=UTC)

TAG_STATIC = TagConfig(
    id=21, name="Nível fixo", node_id=NODE_STATIC, direction="r", data_type="float"
)
TAG_SINE = TagConfig(id=22, name="Temperatura", node_id=NODE_SINE, direction="r", data_type="float")
TAG_WRITE = TagConfig(
    id=23, name="Setpoint", node_id=NODE_W_FLOAT, direction="w", data_type="float"
)


def make_config(endpoint: str, *, tags: tuple[TagConfig, ...]) -> ConnectionConfig:
    return ConnectionConfig(
        id=CONN_ID,
        project_id=1,
        name="Forno 1",
        endpoint=endpoint,
        security_policy="none",
        security_mode="none",
        auth_mode="anonymous",
        auth_username=None,
        auth_password_enc=None,
        server_cert_file=None,
        watchdog_read_node_id=None,
        watchdog_write_node_id=None,
        watchdog_period_ms=1000,
        tags=tags,
    )


def make_runtime(
    config: ConnectionConfig,
    redis_client: Redis,
    snapshot: ConnectionSnapshot,
    *,
    heartbeat_interval_s: float,
) -> ConnectionRuntime:
    return ConnectionRuntime(
        config,
        redis_client,
        snapshot,
        backoff_initial_s=TEST_BACKOFF_INITIAL_S,
        backoff_max_s=TEST_BACKOFF_MAX_S,
        heartbeat_interval_s=heartbeat_interval_s,
    )


def collect_values(redis_client: Redis) -> AsyncIterator[list[dict]]:
    return collecting(redis_client, channel_opc_values(CONN_ID))


def of_tag(values: list[dict], tag_id: int) -> list[dict]:
    return [value for value in values if value["tag_id"] == tag_id]


@asynccontextmanager
async def running(runtime: ConnectionRuntime) -> AsyncIterator[ConnectionRuntime]:
    await runtime.start()
    try:
        yield runtime
    finally:
        await runtime.stop()


@asynccontextmanager
async def beating(hb: ValueHeartbeat) -> AsyncIterator[ValueHeartbeat]:
    await hb.start()
    try:
        yield hb
    finally:
        await hb.stop()


@pytest.fixture
def heartbeat_tags(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Ids das tags publicadas PELO heartbeat; o canal não distingue a origem."""
    published: list[int] = []
    original = heartbeat_module.publish_value

    async def spy(*args, **kwargs) -> None:
        published.append(kwargs["tag_id"])
        await original(*args, **kwargs)

    monkeypatch.setattr(heartbeat_module, "publish_value", spy)
    return published


# --- heartbeat com a sessão viva ----------------------------------------------------


async def test_tag_estatica_e_republicada_com_ts_novo(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Tag que nunca muda mantém a série viva: mesmo valor/qualidade, ts novo (§2.2-6)."""
    config = make_config(sim.endpoint, tags=(TAG_STATIC,))
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = make_runtime(config, redis_client, snapshot, heartbeat_interval_s=FAST_INTERVAL_S)
    async with collect_values(redis_client) as values:
        async with running(runtime):
            # Antes da sessão subir a tag não tem valor conhecido e a batida publica bad
            # (§2.2-6); a prova da republicação começa na primeira publicação boa.
            await await_until(lambda: any(item["quality"] == QUALITY_GOOD for item in values))
            inicio = next(i for i, item in enumerate(values) if item["quality"] == QUALITY_GOOD)
            await await_until(lambda: len(of_tag(values[inicio:], TAG_STATIC.id)) >= 3)

    publicacoes = of_tag(values[inicio:], TAG_STATIC.id)
    assert [item["value"] for item in publicacoes] == [42.0] * len(publicacoes)
    assert {item["quality"] for item in publicacoes} == {QUALITY_GOOD}
    timestamps = [item["ts"] for item in publicacoes]
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == len(timestamps)


async def test_tag_que_muda_nao_e_republicada_pelo_heartbeat(
    sim: OpcSimServer, redis_client: Redis, heartbeat_tags: list[int]
) -> None:
    """Report-by-exception: com a subscription entregando a 250 ms, o heartbeat cala."""
    config = make_config(sim.endpoint, tags=(TAG_SINE,))
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = make_runtime(config, redis_client, snapshot, heartbeat_interval_s=SLACK_INTERVAL_S)
    async with collect_values(redis_client) as values:
        async with running(runtime):
            await await_until(
                lambda: runtime.state is ConnectionState.UP and bool(of_tag(values, TAG_SINE.id))
            )
            # A batida anterior à sessão publica bad (tag sem valor conhecido): só conta o
            # que o heartbeat faz depois que a subscription começou a entregar.
            heartbeat_tags.clear()
            observadas = len(of_tag(values, TAG_SINE.id))
            await await_until(lambda: len(of_tag(values, TAG_SINE.id)) >= observadas + 8)

    assert heartbeat_tags == []


async def test_burst_bad_publica_na_hora_fora_da_janela(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """A rajada da transição de falha (tarefa 2.2) ignora `published_at` (§2.2-6)."""
    config = make_config(sim.endpoint, tags=(TAG_STATIC, TAG_SINE))
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = make_runtime(config, redis_client, snapshot, heartbeat_interval_s=IDLE_INTERVAL_S)
    async with collect_values(redis_client) as values:
        async with running(runtime):
            await await_until(lambda: all(of_tag(values, tag.id) for tag in (TAG_STATIC, TAG_SINE)))
            # Congela as variáveis para que só a rajada produza publicações daqui em diante.
            await sim.set_freeze_values(True)
            await asyncio.sleep(QUIET_WINDOW_S)
            antes = len(values)
            ultimos = {tag_id: snap.value for tag_id, snap in snapshot.last_values.items()}

            await runtime.heartbeat.burst_bad()
            await await_until(lambda: len(values) - antes >= 2)
            await asyncio.sleep(QUIET_WINDOW_S)

    rajada = values[antes:]
    assert len(rajada) == 2
    assert {item["quality"] for item in rajada} == {QUALITY_BAD}
    assert {item["tag_id"]: item["value"] for item in rajada} == ultimos


async def test_tag_de_escrita_nunca_entra_no_heartbeat(
    redis_client: Redis, heartbeat_tags: list[int]
) -> None:
    """Heartbeat é dado de processo lido; tag `w` não tem série própria (spec §2.2-4)."""
    config = make_config("opc.tcp://127.0.0.1:1/x", tags=(TAG_STATIC, TAG_WRITE))
    snapshot = ConnectionSnapshot(name=config.name, state=ConnectionState.FAILED)
    hb = ValueHeartbeat(config, redis_client, snapshot, interval_s=FAST_INTERVAL_S)
    async with collect_values(redis_client) as values:
        async with beating(hb):
            await await_until(lambda: len(of_tag(values, TAG_STATIC.id)) >= 2)
            await hb.burst_bad()
            await asyncio.sleep(QUIET_WINDOW_S)

    assert set(heartbeat_tags) == {TAG_STATIC.id}
    assert of_tag(values, TAG_WRITE.id) == []


# --- heartbeat com a conexão em falha -----------------------------------------------


async def test_falha_republica_todas_as_tags_com_quality_bad(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Conexão caída não emudece a série: quality=2 com o último valor conhecido."""
    config = make_config(sim.endpoint, tags=(TAG_STATIC, TAG_SINE))
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = make_runtime(config, redis_client, snapshot, heartbeat_interval_s=FAST_INTERVAL_S)
    async with collect_values(redis_client) as values:
        async with running(runtime):
            await await_until(lambda: all(of_tag(values, tag.id) for tag in (TAG_STATIC, TAG_SINE)))
            await sim.stop()
            await await_until(lambda: runtime.state is ConnectionState.FAILED)

            conhecidos = {tag_id: snap.value for tag_id, snap in snapshot.last_values.items()}
            antes = len(values)
            await await_until(
                lambda: all(of_tag(values[antes:], tag.id) for tag in (TAG_STATIC, TAG_SINE))
            )

    depois = values[antes:]
    assert {item["quality"] for item in depois} == {QUALITY_BAD}
    assert {item["value"] for item in of_tag(depois, TAG_STATIC.id)} == {conhecidos[TAG_STATIC.id]}
    assert {item["value"] for item in of_tag(depois, TAG_SINE.id)} == {conhecidos[TAG_SINE.id]}
    assert conhecidos[TAG_STATIC.id] == 42.0


async def test_conexao_que_nunca_subiu_publica_zero_com_quality_bad(redis_client: Redis) -> None:
    """Sem último valor o heartbeat publica 0.0 sob bad — irrelevante, mas presente."""
    config = make_config(
        f"opc.tcp://127.0.0.1:{free_port()}/nao/existe", tags=(TAG_STATIC, TAG_SINE)
    )
    snapshot = ConnectionSnapshot(name=config.name)
    runtime = make_runtime(config, redis_client, snapshot, heartbeat_interval_s=FAST_INTERVAL_S)
    async with collect_values(redis_client) as values:
        async with running(runtime):
            await await_until(lambda: all(of_tag(values, tag.id) for tag in (TAG_STATIC, TAG_SINE)))

    assert {item["value"] for item in values} == {0.0}
    assert {item["quality"] for item in values} == {QUALITY_BAD}
    assert runtime.state is ConnectionState.FAILED


async def test_stop_e_idempotente_e_cessa_as_publicacoes(redis_client: Redis) -> None:
    config = make_config("opc.tcp://127.0.0.1:1/x", tags=(TAG_STATIC,))
    snapshot = ConnectionSnapshot(name=config.name, state=ConnectionState.FAILED)
    hb = ValueHeartbeat(config, redis_client, snapshot, interval_s=FAST_INTERVAL_S)
    async with collect_values(redis_client) as values:
        await hb.start()
        await await_until(lambda: len(values) >= 1)
        await hb.stop()
        await hb.stop()
        antes = len(values)
        await asyncio.sleep(QUIET_WINDOW_S)

        assert len(values) == antes


async def test_republica_com_o_relogio_de_parede_andando_para_tras(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ajuste de NTP para trás não pode calar a série: a decisão é monotônica.

    O relógio de parede fica travado no passado; `time.monotonic()` segue real.
    """

    class _RelogioTravado:
        """Substitui `datetime` em `publish_value`: só `now()` importa aqui."""

        @staticmethod
        def now(tz: object = None) -> datetime:
            return RELOGIO_PARA_TRAS

    monkeypatch.setattr(subscriptions, "datetime", _RelogioTravado)

    config = make_config("opc.tcp://127.0.0.1:1/x", tags=(TAG_STATIC,))
    snapshot = ConnectionSnapshot(name=config.name, state=ConnectionState.FAILED)
    hb = ValueHeartbeat(config, redis_client, snapshot, interval_s=FAST_INTERVAL_S)
    async with collect_values(redis_client) as values:
        async with beating(hb):
            await await_until(lambda: len(of_tag(values, TAG_STATIC.id)) >= 3)

    # O `ts` do payload continua sendo o relógio de parede (PRD §7.1 não muda); o que
    # deixou de depender dele é a decisão de republicar.
    assert {datetime.fromisoformat(item["ts"]) for item in values} == {RELOGIO_PARA_TRAS}
