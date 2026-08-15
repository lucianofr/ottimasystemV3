"""Testes do polling do opc-worker (spec F2 §2.2-4/5/7, RF-204, ADR-032).

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

from opcsim import NODE_SINE, NODE_STATIC, NODE_W_FLOAT, NODE_W_ONLY, OpcSimServer
from ottima_core.bus import (
    CHANNEL_EVENTS,
    KIND_COMM_FAILURE,
    KIND_TAG_SUBSCRIBE_ERROR,
    OpcValue,
    channel_opc_values,
)
from ottima_opc_worker import polling
from ottima_opc_worker.connection import ConnectionRuntime
from ottima_opc_worker.polling import coerce_value, status_to_quality
from ottima_opc_worker.state import (
    ConnectionConfig,
    ConnectionSnapshot,
    ConnectionState,
    TagConfig,
)

# Severidade nos 2 bits mais altos: 11 é reservado e a spec manda tratar como Bad.
RESERVED_SEVERITY_CODE = 0xC0000000

CONN_ID = 7
# Período de varredura dos testes: rápido o bastante para não arrastar a suíte, folgado o
# bastante para o opcsim in-process responder sem competir com o event loop.
POLL_MS = 100
# Janela para provar que algo NÃO acontece; cobre várias varreduras de POLL_MS.
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
# Node gravável e ILEGÍVEL: o caso que separa "tag de escrita sem série" de "tag torta".
TAG_WRITE_ONLY = TagConfig(
    id=15, name="Comando cego", node_id=NODE_W_ONLY, direction="w", data_type="float"
)


def make_config(
    endpoint: str, *, tags: tuple[TagConfig, ...], polling_period_ms: int = POLL_MS
) -> ConnectionConfig:
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
        polling_period_ms=polling_period_ms,
    )


def collect_values(redis_client: Redis) -> AsyncIterator[list[dict]]:
    return collecting(redis_client, channel_opc_values(CONN_ID))


def collect_events(redis_client: Redis) -> AsyncIterator[list[dict]]:
    return collecting(redis_client, CHANNEL_EVENTS)


def of_tag(values: list[dict], tag_id: int) -> list[dict]:
    return [value for value in values if value["tag_id"] == tag_id]


def of_kind(events: list[dict], kind: str) -> list[dict]:
    return [event for event in events if event["payload"]["kind"] == kind]


def poll_task() -> asyncio.Task[None]:
    """A task do ciclo desta conexão, pelo nome que `ValuePoller.start()` registra."""
    tarefas = [t for t in asyncio.all_tasks() if t.get_name() == f"opc-poll-{CONN_ID}"]
    assert len(tarefas) == 1, f"esperava 1 task de polling viva, achei {len(tarefas)}"
    return tarefas[0]


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


# --- polling contra o opcsim -------------------------------------------------------


async def test_payload_no_canal_e_o_opcvalue_da_spec(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Varredura ⇒ payload §7.1 verbatim, nem uma chave a mais."""
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


async def test_primeira_varredura_entrega_o_valor_atual(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """O ciclo lê ANTES de dormir: o valor corrente sai na primeira varredura, não depois de
    um período de silêncio."""
    config = make_config(sim.endpoint, tags=(TAG_STATIC,))
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_values(redis_client) as values:
        async with running(ConnectionRuntime(config, redis_client, snapshot)):
            await await_until(lambda: bool(of_tag(values, TAG_STATIC.id)))

    assert of_tag(values, TAG_STATIC.id)[0]["value"] == 42.0


async def test_tag_estatica_republica_a_cada_varredura(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """A prova de que o mecanismo é polling, e não report-by-exception (ADR-032).

    `NODE_STATIC` nunca muda. Sob subscription ele publicava UMA vez (o datachange inicial) e
    depois emudecia até o heartbeat de 10 s. Sob polling ele publica a cada ciclo.
    """
    config = make_config(sim.endpoint, tags=(TAG_STATIC,))
    snapshot = ConnectionSnapshot(name=config.name)
    async with (
        collect_values(redis_client) as values,
        running(ConnectionRuntime(config, redis_client, snapshot)),
    ):
        await await_until(lambda: len(of_tag(values, TAG_STATIC.id)) >= 3)

    publicados = of_tag(values, TAG_STATIC.id)
    assert all(mensagem["value"] == 42.0 for mensagem in publicados)
    assert all(mensagem["quality"] == 0 for mensagem in publicados)
    # `ts` novo a cada varredura: quem grava a hypertable recebe série contínua.
    assert len({mensagem["ts"] for mensagem in publicados}) == len(publicados)


async def test_periodo_de_varredura_vem_da_conexao(sim: OpcSimServer, redis_client: Redis) -> None:
    """`opc_connections.polling_period_ms` governa a cadência do ciclo (ADR-032)."""
    config = make_config(sim.endpoint, tags=(TAG_SINE,), polling_period_ms=250)
    snapshot = ConnectionSnapshot(name=config.name)
    async with running(ConnectionRuntime(config, redis_client, snapshot)) as runtime:
        await await_until(lambda: snapshot.tags_polled == 1)
        poller = runtime.poller
        assert poller is not None
        assert poller.period_s == 0.25


async def test_apply_polling_period_retima_sem_derrubar_a_sessao(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Mudar a varredura não pode custar reconexão: `polling_period_ms` fica fora da
    `session_key` justamente por isso (spec §2.2-1, ADR-032)."""
    config = make_config(sim.endpoint, tags=(TAG_SINE,), polling_period_ms=250)
    snapshot = ConnectionSnapshot(name=config.name)
    async with (
        collect_values(redis_client) as values,
        running(ConnectionRuntime(config, redis_client, snapshot)) as runtime,
    ):
        await await_until(lambda: bool(of_tag(values, TAG_SINE.id)))
        up_since = snapshot.session_up_since

        await runtime.apply_polling_period(120)

        assert runtime.state is ConnectionState.UP
        assert snapshot.session_up_since == up_since  # a sessão asyncua não foi recriada
        poller = runtime.poller
        assert poller is not None
        assert poller.period_s == 0.12
        antes = len(of_tag(values, TAG_SINE.id))
        await await_until(lambda: len(of_tag(values, TAG_SINE.id)) > antes)


async def test_tag_de_escrita_legivel_tem_serie_como_qualquer_outra(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Node de comando legível (AccessLevel com CurrentRead) publica em `opc.values`.

    O valor de uma tag `w` é o comando EM VIGOR no servidor — grandeza distinta do readback
    (que mede a posição real, RF-604) e dado de processo por direito próprio. `direction`
    governa quem o sistema pode ESCREVER, não o que ele pode observar.
    """
    config = make_config(sim.endpoint, tags=(TAG_STATIC, TAG_WRITE))
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_values(redis_client) as values:
        async with running(ConnectionRuntime(config, redis_client, snapshot)):
            await await_until(lambda: bool(of_tag(values, TAG_WRITE.id)))
            assert snapshot.tags_polled == 2
            assert of_tag(values, TAG_WRITE.id)[0]["quality"] == 0
            assert snapshot.read_errors == 0


async def test_tag_de_escrita_ilegivel_nao_e_erro_de_cadastro(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Node gravável e sem CurrentRead: nem todo comando de PLC/gateway é legível.

    Fica fora do ciclo, não publica bad, não conta `read_errors` e não emite aviso — a tela
    mostra travessão (sem dado), que é o estado honesto. Contar isso como erro de
    configuração encheria o diagnóstico de falha esperada; a tag torta de verdade
    (`direction='r'` em node inexistente) continua avisando, no teste seguinte.
    """
    config = make_config(sim.endpoint, tags=(TAG_STATIC, TAG_WRITE_ONLY))
    snapshot = ConnectionSnapshot(name=config.name)
    async with collect_values(redis_client) as values, collect_events(redis_client) as events:
        async with running(ConnectionRuntime(config, redis_client, snapshot)) as runtime:
            await await_until(lambda: bool(of_tag(values, TAG_STATIC.id)))
            await asyncio.sleep(QUIET_WINDOW_S)
            assert snapshot.tags_polled == 1
            assert of_tag(values, TAG_WRITE_ONLY.id) == []
            assert snapshot.read_errors == 0
            assert of_kind(events, KIND_TAG_SUBSCRIBE_ERROR) == []
            assert runtime.state is ConnectionState.UP


async def test_node_invalido_marca_bad_avisa_uma_vez_e_mantem_a_conexao(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Node inexistente ⇒ bad a cada varredura, warning UMA vez, conexão de pé (§2.2-4).

    A série da tag torta continua viva como ruim (quem consome precisa distinguir "sem dado"
    de "dado ruim"), mas o alarme é por tag: sem isso, uma tag mal cadastrada viraria uma
    rajada de eventos a cada ciclo.
    """
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
        assert ruins[0]["quality"] == 2
        assert ruins[0]["value"] == 0.0
        # Node inválido continua no ciclo: o servidor responde com StatusCode Bad, e é isso
        # que mantém a série honesta em vez de emudecer a tag.
        assert snapshot.tags_polled == 2
        assert runtime.state is ConnectionState.UP

        avisos = of_kind(events, KIND_TAG_SUBSCRIBE_ERROR)
        assert len(avisos) == 1
        assert avisos[0]["severity"] == "warning"
        assert avisos[0]["origin"] == f"conn:{CONN_ID}"
        assert avisos[0]["payload"]["conn_id"] == CONN_ID
        assert avisos[0]["payload"]["tag_id"] == TAG_BAD.id
        assert avisos[0]["payload"]["node_id"] == TAG_BAD.node_id
        assert avisos[0]["payload"]["detail"]

        # Varreduras seguintes: mais bad no canal, nenhum aviso novo, contador estável em 1
        # (ele conta TAGS em falha, não ocorrências — senão cresceria sem limite no polling).
        await await_until(lambda: len(of_tag(values, TAG_BAD.id)) > len(ruins))
        await asyncio.sleep(QUIET_WINDOW_S)
        assert all(mensagem["quality"] == 2 for mensagem in of_tag(values, TAG_BAD.id))
        assert len(of_kind(events, KIND_TAG_SUBSCRIBE_ERROR)) == 1
        assert snapshot.read_errors == 1


async def test_apply_tags_troca_o_conjunto_sem_derrubar_a_sessao(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Reconciliação de tags (tarefa 1.4) recria só o poller (spec §2.2-1)."""
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
        assert snapshot.tags_polled == 1
        await asyncio.sleep(QUIET_WINDOW_S)  # deixa assentar o que já estava em trânsito
        antes = len(of_tag(values, TAG_SINE.id))
        await asyncio.sleep(QUIET_WINDOW_S)
        assert len(of_tag(values, TAG_SINE.id)) == antes


async def test_troca_de_tags_nao_publica_valor_sob_o_tag_id_errado(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """Tags e nodes nascem juntos no poller e são emparelhados por índice.

    Trocar o conjunto com a sessão de pé, repetidamente, não pode desalinhar o par: valor
    publicado sob o `tag_id` errado é corrupção silenciosa alimentando PID/MPC.
    """
    config = make_config(sim.endpoint, tags=(TAG_SINE, TAG_STATIC))
    snapshot = ConnectionSnapshot(name=config.name)
    async with (
        collect_values(redis_client) as values,
        running(ConnectionRuntime(config, redis_client, snapshot)) as runtime,
    ):
        # Termina com AS DUAS no conjunto: a prova precisa de publicação de ambas depois de
        # toda a dança de trocas, inclusive uma que inverte a ordem.
        for tags in ((TAG_STATIC,), (TAG_SINE,), (TAG_STATIC, TAG_SINE), (TAG_SINE, TAG_STATIC)):
            await runtime.apply_tags(tags)
        await await_until(lambda: len(of_tag(values, TAG_SINE.id)) >= 2)
        await await_until(lambda: len(of_tag(values, TAG_STATIC.id)) >= 2)

    # Prova do emparelhamento: `NODE_STATIC` vale sempre 42.0, então com o par torto a
    # estática receberia valor da senoide. A recíproca NÃO serve de asserção — a senoide
    # passa pela faixa do 42.0, e nos primeiros ciclos ainda está no 0.0 inicial do
    # simulador. Os `await_until` acima é que garantem que o teste não passa a vazio.
    assert all(mensagem["value"] == 42.0 for mensagem in of_tag(values, TAG_STATIC.id))


async def test_resposta_curta_do_servidor_derruba_a_sessao_sem_reentrancia(
    sim: OpcSimServer, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Servidor que devolve menos DataValues que nodes pedidos não pode truncar em silêncio.

    Sem o `strict=True` no zip, as tags do fim da lista parariam de atualizar sem erro nenhum.
    O mesmo teste cobre a reentrância de `ValuePoller.stop()`: a falha nasce DENTRO da task do
    poller e a cadeia `_loop → fail → _close_session → on_session_down → poller.stop()` volta
    nela mesma. Sem o guarda `task is asyncio.current_task()`, o `await task` levantaria
    `RuntimeError` — e o evento `comm_failure` sai ANTES disso (`connection.py:491-502`), então
    só a inspeção da task denuncia o problema.
    """
    config = make_config(sim.endpoint, tags=(TAG_SINE, TAG_STATIC))
    snapshot = ConnectionSnapshot(name=config.name)
    async with (
        collect_events(redis_client) as events,
        running(ConnectionRuntime(config, redis_client, snapshot)) as runtime,
    ):
        await await_until(lambda: snapshot.tags_polled == 2)
        client = runtime.client
        assert client is not None
        tarefa = poll_task()

        async def resposta_curta(nodes: object, attr: object = None) -> list[ua.DataValue]:
            return [ua.DataValue(ua.Variant(1.0))]

        monkeypatch.setattr(client, "read_attributes", resposta_curta)

        await await_until(lambda: bool(of_kind(events, KIND_COMM_FAILURE)))
        await await_until(lambda: tarefa.done())
        # A task encerra por `return`, não por exceção: com a reentrância desprotegida isto
        # seria `RuntimeError: Task cannot await on itself`.
        assert tarefa.exception() is None

    falhas = of_kind(events, KIND_COMM_FAILURE)
    assert falhas[0]["payload"]["reason"] == "session_lost"


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
        poller = runtime.poller
        assert poller is not None

        await poller.stop()
        await poller.stop()
        assert poller.tags == ()
        assert snapshot.tags_polled == 0

        # `stop()` AGUARDA o fim da task: nada mais sai no canal depois que ele retorna.
        antes = len(values)
        await asyncio.sleep(QUIET_WINDOW_S)
        assert len(values) == antes


async def test_valor_nao_numerico_publica_bad_e_avisa_uma_vez(
    sim: OpcSimServer, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Node de tipo incompatível com a tag não pode deixá-la muda no canal (spec §2.2-4).

    O opcsim não tem node String (e não pode ser alterado), então a incompatibilidade é
    injetada no ponto de coerção — o caminho percorrido é o ciclo real do poller.
    """

    def coerce_explode(raw: object) -> float:
        raise ValueError(f"valor não numérico: {raw!r}")

    monkeypatch.setattr(polling, "coerce_value", coerce_explode)
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
        assert ruins[0]["quality"] == 2
        assert ruins[0]["value"] == 0.0
        assert runtime.state is ConnectionState.UP

        # Varreduras seguintes: novo bad no canal, sem segundo aviso.
        await await_until(lambda: len(of_tag(values, TAG_STATIC.id)) >= 2)
        assert of_tag(values, TAG_STATIC.id)[1]["quality"] == 2
        assert of_tag(values, TAG_STATIC.id)[1]["value"] == 0.0
        await asyncio.sleep(QUIET_WINDOW_S)
        assert len(of_kind(events, KIND_TAG_SUBSCRIBE_ERROR)) == 1
        assert snapshot.read_errors == 1
        assert runtime.state is ConnectionState.UP


async def test_read_errors_conta_tags_em_falha_e_nao_edicoes_da_conexao(
    sim: OpcSimServer, redis_client: Redis
) -> None:
    """`read_errors` é quantas tags estão em falha AGORA, não quantas vezes falharam.

    Cada retimagem (ou troca de tags) cria um poller novo, que rearma o dedupe do alarme. Se
    o contador somasse em cima do valor anterior, editar o período de uma conexão com uma tag
    torta faria o `/health` mostrar flapping crescente numa conexão perfeitamente estável.
    """
    config = make_config(sim.endpoint, tags=(TAG_BAD, TAG_STATIC))
    snapshot = ConnectionSnapshot(name=config.name)
    async with (
        collect_values(redis_client) as values,
        running(ConnectionRuntime(config, redis_client, snapshot)) as runtime,
    ):
        await await_until(lambda: snapshot.read_errors == 1)

        for periodo in (150, 200, 250):
            antes = len(of_tag(values, TAG_BAD.id))
            await runtime.apply_polling_period(periodo)
            # Esperar a varredura do poller NOVO garante que ele já passou por `_alarm_once`.
            await await_until(lambda antes=antes: len(of_tag(values, TAG_BAD.id)) > antes)

        assert snapshot.read_errors == 1
        assert runtime.state is ConnectionState.UP
