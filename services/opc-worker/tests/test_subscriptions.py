"""Testes das subscriptions do opc-worker (spec F2 §2.2-4/5/7, RF-204).

Lógica pura (mapeamento de StatusCode e coerção de valor) sem servidor; o resto contra o
opcsim in-process e o Redis real da fixture da raiz, com assinante no canal
`opc.values.<conn_id>`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from asyncua import ua
from redis.asyncio import Redis
from worker_test_helpers import await_until, collecting

from opcsim import NODE_SINE, NODE_STATIC, NODE_W_FLOAT, OpcSimServer
from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_TAG_SUBSCRIBE_ERROR,
    OpcValue,
    channel_opc_values,
)
from ottima_opc_worker import subscriptions
from ottima_opc_worker.connection import ConnectionRuntime
from ottima_opc_worker.state import (
    ConnectionConfig,
    ConnectionSnapshot,
    ConnectionState,
    TagConfig,
)
from ottima_opc_worker.subscriptions import (
    PUBLISHING_INTERVAL_MS,
    QUEUE_SIZE,
    SAMPLING_INTERVAL_MS,
    coerce_value,
    status_to_quality,
)

# Severidade nos 2 bits mais altos: 11 é reservado e a spec manda tratar como Bad.
RESERVED_SEVERITY_CODE = 0xC0000000

CONN_ID = 7
# Janela para provar que algo NÃO acontece; a senoide muda a cada 200 ms, então uma tag
# ainda subscrita publicaria mais de uma vez aqui dentro.
QUIET_WINDOW_S = 0.6

TAG_SINE = TagConfig(id=11, name="Temperatura", node_id=NODE_SINE, direction="r", data_type="float")
TAG_STATIC = TagConfig(
    id=12, name="Nível fixo", node_id=NODE_STATIC, direction="r", data_type="float"
)
TAG_WRITE = TagConfig(
    id=13, name="Setpoint", node_id=NODE_W_FLOAT, direction="w", data_type="float"
)
TAG_BAD = TagConfig(
    id=14, name="Tag torta", node_id="ns=2;s=nao.existe", direction="r", data_type="float"
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
        tags=tags,
    )


def collect_values(redis_client: Redis) -> AsyncIterator[list[dict]]:
    return collecting(redis_client, channel_opc_values(CONN_ID))


def collect_events(redis_client: Redis) -> AsyncIterator[list[dict]]:
    return collecting(redis_client, CHANNEL_EVENTS)


def of_tag(values: list[dict], tag_id: int) -> list[dict]:
    return [value for value in values if value["tag_id"] == tag_id]


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


def test_status_to_quality_mapeia_severidade_do_status_code() -> None:
    """Good⇒0, Uncertain⇒1, Bad⇒2, reservado⇒2 (spec F1 §3.4-4)."""
    assert status_to_quality(ua.StatusCode(ua.StatusCodes.Good)) == 0
    assert status_to_quality(ua.StatusCode(ua.StatusCodes.UncertainInitialValue)) == 1
    assert status_to_quality(ua.StatusCode(ua.StatusCodes.BadNodeIdUnknown)) == 2
    assert status_to_quality(ua.StatusCode(RESERVED_SEVERITY_CODE)) == 2


def test_status_to_quality_sem_status_code_e_bad() -> None:
    """DataValue.StatusCode é opcional no asyncua: ausência de status não é dado bom."""
    assert status_to_quality(None) == 2


def test_coerce_value_normaliza_para_float() -> None:
    """`samples.value` é DOUBLE PRECISION: bool⇒0/1, int⇒float (spec F1 §3.2)."""
    assert coerce_value(True) == 1.0
    assert coerce_value(False) == 0.0
    assert coerce_value(7) == 7.0
    assert coerce_value(1.5) == 1.5
    assert coerce_value(None) == 0.0
    assert all(isinstance(coerce_value(raw), float) for raw in (True, False, 7, 1.5, None))


def test_coerce_value_recusa_valor_nao_numerico() -> None:
    """Node de tipo incompatível não vira float silenciosamente: quem chama trata."""
    with pytest.raises(ValueError):
        coerce_value("texto")


# --- subscriptions contra o opcsim -------------------------------------------------


async def test_payload_no_canal_e_o_opcvalue_da_spec(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Mudança no opcsim ⇒ payload §7.1 verbatim, nem uma chave a mais."""
    config = make_config(sim.endpoint, tags=(TAG_SINE,))
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_values(redis_client) as values:
        async with running(ConnectionRuntime(config, redis_client, snapshot)) as runtime:
            await await_until(lambda: runtime.state is ConnectionState.UP)
            await await_until(lambda: len(values) >= 1)

    mensagem = values[0]
    assert set(mensagem) == {"tag_id", "ts", "value", "quality"}
    assert mensagem["tag_id"] == TAG_SINE.id
    assert mensagem["quality"] == 0
    decodificado = OpcValue.model_validate(mensagem)
    assert decodificado.ts.utcoffset() == timedelta(0)
    assert snapshot.last_values[TAG_SINE.id].published_at is not None
    assert snapshot.last_publish_ts is not None


async def test_datachange_inicial_entrega_o_valor_atual(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Tag nunca atualizada publica o valor corrente logo na criação do monitored item."""
    config = make_config(sim.endpoint, tags=(TAG_STATIC,))
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_values(redis_client) as values:
        async with running(ConnectionRuntime(config, redis_client, snapshot)):
            await await_until(lambda: bool(of_tag(values, TAG_STATIC.id)))

    assert of_tag(values, TAG_STATIC.id)[0]["value"] == 42.0


async def test_tag_de_escrita_nao_gera_monitored_item(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Monitored item é leitura: o readback de uma tag W é tag R própria (spec §2.2-4)."""
    config = make_config(sim.endpoint, tags=(TAG_STATIC, TAG_WRITE))
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_values(redis_client) as values:
        async with running(ConnectionRuntime(config, redis_client, snapshot)):
            await await_until(lambda: bool(of_tag(values, TAG_STATIC.id)))
            await asyncio.sleep(QUIET_WINDOW_S)
            assert snapshot.tags_subscribed == 1
            assert of_tag(values, TAG_WRITE.id) == []


async def test_node_invalido_marca_bad_avisa_uma_vez_e_mantem_a_conexao(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Node inexistente ⇒ bad + warning na 1ª ocorrência, sem derrubar a conexão (§2.2-4)."""
    config = make_config(sim.endpoint, tags=(TAG_BAD, TAG_STATIC))
    snapshot = ConnectionSnapshot(name=config.name)
    async with (
        collect_events(redis_client) as events,
        collect_values(redis_client) as values,
        running(ConnectionRuntime(config, redis_client, snapshot)) as runtime,
    ):
        await await_until(lambda: bool(of_tag(values, TAG_STATIC.id)))
        await await_until(lambda: bool(of_kind(events, KIND_TAG_SUBSCRIBE_ERROR)))

        ruins = of_tag(values, TAG_BAD.id)
        assert len(ruins) == 1
        assert ruins[0]["quality"] == 2
        assert ruins[0]["value"] == 0.0
        assert snapshot.monitored_errors == 1
        assert snapshot.tags_subscribed == 1
        assert runtime.state is ConnectionState.UP

        avisos = of_kind(events, KIND_TAG_SUBSCRIBE_ERROR)
        assert len(avisos) == 1
        assert avisos[0]["severity"] == "warning"
        assert avisos[0]["origin"] == f"conn:{CONN_ID}"
        assert avisos[0]["payload"]["conn_id"] == CONN_ID
        assert avisos[0]["payload"]["tag_id"] == TAG_BAD.id
        assert avisos[0]["payload"]["node_id"] == TAG_BAD.node_id
        assert avisos[0]["payload"]["detail"]

        # Segundo ciclo de falha da mesma tag: continua bad, mas sem segundo aviso.
        subscription = runtime.subscription
        assert subscription is not None
        await subscription.stop()
        await subscription.start()
        await await_until(lambda: snapshot.monitored_errors == 2)
        await asyncio.sleep(QUIET_WINDOW_S)
        assert len(of_kind(events, KIND_TAG_SUBSCRIBE_ERROR)) == 1


async def test_apply_tags_troca_o_conjunto_sem_derrubar_a_sessao(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Reconciliação de tags (tarefa 1.4) recria só a subscription (spec §2.2-1)."""
    config = make_config(sim.endpoint, tags=(TAG_SINE,))
    snapshot = ConnectionSnapshot(name=config.name)
    async with (
        collect_values(redis_client) as values,
        running(ConnectionRuntime(config, redis_client, snapshot)) as runtime,
    ):
        await await_until(lambda: len(of_tag(values, TAG_SINE.id)) >= 2)
        up_since = snapshot.session_up_since

        await runtime.apply_tags((TAG_STATIC,))
        assert runtime.state is ConnectionState.UP
        assert snapshot.session_up_since == up_since
        assert runtime.config.tags == (TAG_STATIC,)

        await await_until(lambda: bool(of_tag(values, TAG_STATIC.id)))
        assert snapshot.tags_subscribed == 1
        await asyncio.sleep(QUIET_WINDOW_S)  # deixa assentar o que já estava em trânsito
        antes = len(of_tag(values, TAG_SINE.id))
        await asyncio.sleep(QUIET_WINDOW_S)
        assert len(of_tag(values, TAG_SINE.id)) == antes


async def test_stop_e_idempotente_e_cessa_as_publicacoes(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    config = make_config(sim.endpoint, tags=(TAG_SINE,))
    snapshot = ConnectionSnapshot(name=config.name)
    async with (
        collect_values(redis_client) as values,
        running(ConnectionRuntime(config, redis_client, snapshot)) as runtime,
    ):
        await await_until(lambda: len(of_tag(values, TAG_SINE.id)) >= 2)
        subscription = runtime.subscription
        assert subscription is not None

        await subscription.stop()
        await subscription.stop()
        assert subscription.asyncua_subscription is None
        assert snapshot.tags_subscribed == 0

        await asyncio.sleep(QUIET_WINDOW_S)
        antes = len(values)
        await asyncio.sleep(QUIET_WINDOW_S)
        assert len(values) == antes


async def test_cadencia_da_subscription_e_dos_monitored_items(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """250 ms de publishing/sampling e queue_size 1 nos objetos criados (spec §2.2-5)."""
    config = make_config(sim.endpoint, tags=(TAG_SINE, TAG_STATIC))
    snapshot = ConnectionSnapshot(name=config.name)
    async with running(ConnectionRuntime(config, redis_client, snapshot)) as runtime:
        await await_until(lambda: snapshot.tags_subscribed == 2)
        subscription = runtime.subscription
        assert subscription is not None
        asyncua_subscription = subscription.asyncua_subscription
        assert asyncua_subscription is not None

        # Literais de propósito: comparar com as constantes do módulo seria tautologia.
        assert (PUBLISHING_INTERVAL_MS, SAMPLING_INTERVAL_MS, QUEUE_SIZE) == (250, 250, 1)
        assert asyncua_subscription.parameters.RequestedPublishingInterval == 250
        # `_monitored_items` é o registro que o asyncua monta a partir dos requests
        # realmente enviados ao servidor: é a prova da cadência, não a documentação.
        itens = list(asyncua_subscription._monitored_items.values())
        assert len(itens) == 2
        assert [item.sampling_interval for item in itens] == [250, 250]
        assert [item.queuesize for item in itens] == [1, 1]


async def test_valor_nao_numerico_publica_bad_e_avisa_uma_vez(
    sim: OpcSimServer, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Node de tipo incompatível com a tag não pode deixá-la muda no canal (spec §2.2-4).

    O opcsim não tem node String (e não pode ser alterado), então a incompatibilidade é
    injetada no ponto de coerção — o caminho percorrido é o handler real da subscription.
    """

    def coerce_explode(raw: object) -> float:
        raise ValueError(f"valor não numérico: {raw!r}")

    monkeypatch.setattr(subscriptions, "coerce_value", coerce_explode)
    config = make_config(sim.endpoint, tags=(TAG_STATIC,))
    snapshot = ConnectionSnapshot(name=config.name)
    async with (
        collect_events(redis_client) as events,
        collect_values(redis_client) as values,
        running(ConnectionRuntime(config, redis_client, snapshot)) as runtime,
    ):
        await await_until(lambda: bool(of_tag(values, TAG_STATIC.id)))
        await await_until(lambda: bool(of_kind(events, KIND_TAG_SUBSCRIBE_ERROR)))

        ruins = of_tag(values, TAG_STATIC.id)
        assert len(ruins) == 1
        assert ruins[0]["quality"] == 2
        assert ruins[0]["value"] == 0.0
        assert snapshot.monitored_errors == 1
        assert runtime.state is ConnectionState.UP
        assert len(of_kind(events, KIND_TAG_SUBSCRIBE_ERROR)) == 1

        # Segunda ocorrência na mesma tag: novo bad no canal, sem segundo aviso.
        await sim.write(NODE_STATIC, 43.0)
        await await_until(lambda: len(of_tag(values, TAG_STATIC.id)) == 2)
        assert of_tag(values, TAG_STATIC.id)[1]["quality"] == 2
        assert of_tag(values, TAG_STATIC.id)[1]["value"] == 0.0
        assert snapshot.monitored_errors == 2
        await asyncio.sleep(QUIET_WINDOW_S)
        assert len(of_kind(events, KIND_TAG_SUBSCRIBE_ERROR)) == 1
        assert runtime.state is ConnectionState.UP
