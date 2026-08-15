"""Runtime de uma conexão OPC-UA: máquina de estados, backoff e eventos (spec F2 §2.2-2/3).

O worker é o supervisor da sessão: o auto-reconnect do asyncua fica desligado para que
`connecting → up → failed` e os eventos de transição (spec §3.6) tenham uma única fonte.
"""

import asyncio
import logging
import random
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from asyncua import Client, ua
from redis.asyncio import Redis

from ottima_core.bus import KIND_COMM_FAILURE, KIND_COMM_RESTORED, publish_event

from .heartbeat import HEARTBEAT_INTERVAL_S, ValueHeartbeat
from .polling import ValuePoller
from .security import (
    SECURITY_POLICY_NONE,
    FailureReason,
    configure_client,
    describe_exception,
    map_connect_exception,
)
from .state import (
    ConnectionConfig,
    ConnectionSnapshot,
    ConnectionState,
    FlowWatchdogConfig,
    TagConfig,
)
from .watchdog import WatchdogTask

logger = logging.getLogger(__name__)

BACKOFF_INITIAL_S = 1.0
BACKOFF_MAX_S = 30.0  # teto (spec §2.2-2)
# Cadência da verificação de sessão viva: queda silenciosa não gera exceção espontânea.
SESSION_CHECK_INTERVAL_S = 1.0
# Acima disso o teto já domina o cálculo; sem o corte, 2**n estoura o float depois de
# algumas horas de conexão fora do ar.
_MAX_BACKOFF_EXPONENT = 32

# Texto pt-BR para humanos; consumidores fazem match por `kind`/`reason` (spec §7.3).
_REASON_TEXT: dict[str, str] = {
    "connect_failed": "falha ao conectar",
    "session_lost": "sessão perdida",
    "cert_mismatch": "certificado do servidor não confere",
    "cert_missing": "certificado ausente (aplicação ou servidor)",
}

# Fallback de codificação quando o DataType do node é ilegível (spec §4.3): o tipo
# declarado em `tags.data_type` é a intenção do engenheiro, e é o melhor palpite que
# resta quando o servidor não responde o atributo.
_FALLBACK_VARIANT_TYPES: dict[str, ua.VariantType] = {
    "float": ua.VariantType.Double,
    "int": ua.VariantType.Int32,
    "bool": ua.VariantType.Boolean,
}


class _SupersededAttemptError(RuntimeError):
    """Tentativa de conexão invalidada por um fail() concorrente."""


def backoff_delay(attempt: int, *, initial: float, maximum: float) -> float:
    """Backoff exponencial com teto e full jitter (spec §2.2-2), `attempt` 0-based."""
    top = min(maximum, initial * 2 ** min(attempt, _MAX_BACKOFF_EXPONENT))
    return random.uniform(0.0, top)


def build_client(config: ConnectionConfig) -> Client:
    """Constrói o Client asyncua da conexão; a segurança é montada por `configure_client`."""
    return Client(config.endpoint)


class ConnectionRuntime:
    """Mantém uma sessão OPC-UA viva e traduz suas transições em eventos (spec §3.6)."""

    def __init__(
        self,
        config: ConnectionConfig,
        redis_client: Redis,
        snapshot: ConnectionSnapshot,
        *,
        certs_dir: Path = Path("/certs"),
        fernet_key: str = "",
        backoff_initial_s: float = BACKOFF_INITIAL_S,
        backoff_max_s: float = BACKOFF_MAX_S,
        heartbeat_interval_s: float = HEARTBEAT_INTERVAL_S,
        watchdog_freeze_threshold_s: float | None = None,
        failure_pending: bool = False,
    ) -> None:
        self._config = config
        self._redis = redis_client
        self._snapshot = snapshot
        self._certs_dir = certs_dir
        self._fernet_key = fernet_key
        self._backoff_initial_s = backoff_initial_s
        self._backoff_max_s = backoff_max_s
        self._state = ConnectionState.CONNECTING
        self._client: Client | None = None
        self._task: asyncio.Task[None] | None = None
        # Sessão aberta com o gancho de subida já executado: garante que on_session_down
        # rode uma vez só, mesmo com stop() repetido.
        self._session_open = False
        self._poller: ValuePoller | None = None
        self._flow_watchdogs: dict[int, WatchdogTask] = {}
        self._desired_flow_watchdogs: dict[int, FlowWatchdogConfig] = {}
        self._flow_failure_pending: dict[int, bool] = {}
        self._flow_gate_generation: dict[int, int] = {}
        # Cache de codificação das tags `w`, preenchido 1× por sessão (spec §4.3).
        self._write_types: dict[int, ua.VariantType] = {}
        # Avança a cada reabertura do gate de escrita (ver `mark_restored`). O consumidor
        # de `opc.writes` (tarefa 2.3) usa isto para distinguir períodos de bloqueio.
        self._gate_generation = 0
        self._watchdog_freeze_threshold_s = watchdog_freeze_threshold_s
        # Edge-trigger dos eventos: só há `comm_restored` depois de um `comm_failure`.
        # O supervisor repassa o valor do runtime anterior ao trocar a sessão (mudança de
        # campo da conexão desmonta e remonta): o `comm_failure` publicado pelo runtime
        # antigo continua de pé no `/eventos` e na coluna "Último estado", entao a obrigacao
        # de retratá-lo é herdada. Sem isso, resolver a causa da falha por edicao — confiar
        # no certificado do servidor, reinformar a senha — subia a sessao de verdade e
        # deixava a tela vermelha para sempre (achado do gate L3, cenario B-F6-04 passo 3).
        self._failure_pending = failure_pending
        # Geração da tentativa de conexão: fail() a incrementa para invalidar um connect
        # que ainda esteja em voo (ele não pode subir a conexão depois do alarme).
        self._generation = 0
        # O heartbeat é do runtime, não da sessão: segue publicando quality=2 com a
        # conexão em falha (spec §2.2-6).
        self._heartbeat = ValueHeartbeat(
            config, redis_client, snapshot, interval_s=heartbeat_interval_s
        )

    @property
    def config(self) -> ConnectionConfig:
        return self._config

    @property
    def failure_pending(self) -> bool:
        """Há um `comm_failure` publicado e ainda não retratado por este runtime."""
        return self._failure_pending

    @property
    def snapshot(self) -> ConnectionSnapshot:
        return self._snapshot

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def client(self) -> Client | None:
        """Client asyncua vivo; None fora do estado `up`."""
        return self._client if self._state is ConnectionState.UP else None

    @property
    def gate_generation(self) -> int:
        """Conta as reaberturas do gate de escrita; muda ⇒ período de bloqueio novo."""
        return self._gate_generation

    @property
    def poller(self) -> ValuePoller | None:
        """Poller de valores vivo; None fora de `up`."""
        return self._poller

    @property
    def flow_watchdogs(self) -> Mapping[int, WatchdogTask]:
        """Tasks de watchdog vivas por `flow_id`; vazio fora de `up` ou sem flow com
        watchdog habilitado nesta conexão (ADR-009 revisado)."""
        return self._flow_watchdogs

    def flow_gate_generation(self, flow_id: int) -> int:
        """Conta as reaberturas do gate de escrita DESTE flow; muda ⇒ período de
        bloqueio novo (`watchdog_dead`). Distinto de `gate_generation` (sessão)."""
        return self._flow_gate_generation.get(flow_id, 0)

    @property
    def heartbeat(self) -> ValueHeartbeat:
        """Heartbeat de valor da conexão; vive fora da sessão (spec §2.2-6)."""
        return self._heartbeat

    async def start(self) -> None:
        """Cria a task supervisora da conexão e retorna já."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._supervise(), name=f"opc-conn-{self._config.id}")
        await self._heartbeat.start()

    async def stop(self) -> None:
        """Cancela a supervisão e desconecta. Idempotente.

        O estado permanece o último observado: quem descarta o runtime é o supervisor
        do worker (tarefa 1.4), que também remove o snapshot do `/health`.
        """
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self._heartbeat.stop()
        await self._close_session()

    async def on_session_up(self) -> None:
        """Gancho pós-connect, antes de marcar `up`: sobe poller e watchdog.

        Falha ao subir o poller inteiro é falha de sessão, não de tag: emite
        `comm_failure` com `session_lost` e devolve a exceção ao supervisor, que fecha o
        cliente e reconecta em backoff.
        """
        client = self._client  # invariante do _open_session; `self.client` só existe em `up`
        if client is None:
            return
        try:
            await self._replace_poller(client)
        except Exception as exc:
            await self.fail("session_lost", describe_exception(exc))
            raise
        await self.load_write_types()
        await self._reconcile_flow_watchdogs(client)

    async def on_session_down(self) -> None:
        """Gancho simétrico, ao sair de `up`: derruba watchdogs de flow e poller.

        Preserva as chaves de `flow_watchdog_alive` (só zera o valor): a config ainda é
        desejada, e um flow com watchdog configurado que perde a sessão deve virar
        `watchdog_dead` (bloqueio transiente), nunca `no_watchdog` (recusa permanente) —
        `_stop_flow_watchdog` (remoção de verdade, flow desabilitado) é quem apaga a
        chave. Quem escreve isso é este método; `fail()` só antecipa sincronamente.
        """
        for watchdog in self._flow_watchdogs.values():
            await watchdog.stop()
        self._flow_watchdogs.clear()
        for flow_id in self._snapshot.flow_watchdog_alive:
            self._snapshot.flow_watchdog_alive[flow_id] = False
        poller, self._poller = self._poller, None
        if poller is not None:
            await poller.stop()
        # O cache é da sessão: um servidor reconfigurado entre duas sessões pode ter
        # trocado o DataType do node. Limpar aqui, e não num caminho novo, é o que mantém
        # este gancho o único ponto de desmonte da sessão.
        self._write_types = {}

    async def load_write_types(self) -> None:
        """Lê 1× o DataType de cada node de tag `w` e monta o cache `tag_id -> VariantType`.

        `tags.data_type` valida a intenção do engenheiro; quem decide a codificação é o
        VariantType real do servidor — escrever Int64 num node Int32 dá `BadTypeMismatch`
        (spec §4.3). Node ilegível cai no fallback e NUNCA derruba a sessão: uma tag de
        escrita mal configurada não pode custar a aquisição inteira da conexão.

        As leituras vão em paralelo porque isto roda antes de `up`, dentro da janela em
        que um `fail()` concorrente ainda pode superar a tentativa: N leituras em série
        alargariam essa janela por N round-trips, em paralelo custam um.
        """
        client = self._client
        if client is None:
            return
        write_tags = [tag for tag in self._config.tags if tag.direction == "w"]
        self._write_types = dict(
            await asyncio.gather(*(self._read_write_type(client, tag) for tag in write_tags))
        )

    async def _read_write_type(self, client: Client, tag: TagConfig) -> tuple[int, ua.VariantType]:
        """DataType real do node da tag, ou o fallback declarado. Nunca levanta."""
        try:
            return tag.id, await client.get_node(tag.node_id).read_data_type_as_variant_type()
        except Exception as exc:
            logger.warning(
                "DataType da tag %s (%s) ilegível; usando o fallback de '%s': %s",
                tag.id,
                tag.node_id,
                tag.data_type,
                describe_exception(exc),
            )
            return tag.id, _FALLBACK_VARIANT_TYPES[tag.data_type]

    def variant_type_for(self, tag_id: int) -> ua.VariantType:
        """Codificação de escrita da tag: cache da sessão, senão fallback por `data_type`.

        O fallback também cobre a tag que entrou por `apply_tags` depois da subida da
        sessão: escrever pelo tipo declarado é melhor do que recusar a escrita, e um
        `BadTypeMismatch` vira evento de erro auditado (spec §4.4).
        """
        cached = self._write_types.get(tag_id)
        if cached is not None:
            return cached
        tag = next((t for t in self._config.tags if t.id == tag_id), None)
        return _FALLBACK_VARIANT_TYPES[tag.data_type] if tag is not None else ua.VariantType.Double

    async def set_flow_watchdogs(self, configs: Mapping[int, FlowWatchdogConfig]) -> None:
        """Atualiza os watchdogs de flow desta conexão (ADR-009 revisado: chamado pelo
        supervisor a cada mudança na tabela `flows`, independente de `session_key`).

        Nunca derruba a sessão nem o poller: um flow ligando/desligando o próprio
        watchdog não pode arrastar os outros flows que também usam esta conexão — é
        exatamente o isolamento que motivou mover o watchdog da conexão para o flow.
        """
        self._desired_flow_watchdogs = dict(configs)
        client = self._client
        if self._state is not ConnectionState.UP or client is None:
            return
        await self._reconcile_flow_watchdogs(client)

    async def _reconcile_flow_watchdogs(self, client: Client) -> None:
        """Cria, para ou reconfigura tasks de watchdog para bater com o desejado."""
        desired = self._desired_flow_watchdogs
        for flow_id in [fid for fid in self._flow_watchdogs if fid not in desired]:
            await self._stop_flow_watchdog(flow_id)
        for flow_id, config in desired.items():
            existing = self._flow_watchdogs.get(flow_id)
            if existing is None:
                await self._start_flow_watchdog(client, config)
            elif existing.config != config or existing.is_dead:
                # `stop()` da task, não `_stop_flow_watchdog`: a chave de
                # `flow_watchdog_alive` e a falha pendente do flow são estado da CONEXÃO e
                # sobrevivem ao rearme (task morta por freeze/hard failure precisa voltar,
                # mas o `comm_restored` pendente ainda tem de sair quando o bit alternar).
                await existing.stop()
                await self._start_flow_watchdog(client, config)

    async def _start_flow_watchdog(self, client: Client, config: FlowWatchdogConfig) -> None:
        watchdog = WatchdogTask(
            config,
            client,
            self._snapshot,
            on_freeze=lambda detail, fid=config.flow_id: self._flow_watchdog_freeze(fid, detail),
            on_alive=lambda fid=config.flow_id: self._flow_watchdog_alive(fid),
            on_hard_failure=lambda detail: self.fail("session_lost", detail),
            freeze_threshold_s=self._watchdog_freeze_threshold_s,
        )
        self._flow_watchdogs[config.flow_id] = watchdog
        await watchdog.start()

    async def _stop_flow_watchdog(self, flow_id: int) -> None:
        """Remoção DE VERDADE (flow desabilitou o watchdog ou foi excluído): apaga todo o
        estado, inclusive a chave de `flow_watchdog_alive` — daqui pra frente a escrita
        deste flow volta a ser recusada por `no_watchdog`, não bloqueada por
        `watchdog_dead` (§ ver `on_session_down`, que preserva a chave por ser transiente)."""
        watchdog = self._flow_watchdogs.pop(flow_id, None)
        if watchdog is not None:
            await watchdog.stop()
        self._snapshot.flow_watchdog_alive.pop(flow_id, None)
        self._flow_failure_pending.pop(flow_id, None)
        self._flow_gate_generation.pop(flow_id, None)

    async def _flow_watchdog_freeze(self, flow_id: int, detail: str) -> None:
        """Callback do `WatchdogTask` na falha do bit (>10s sem alternância).

        Isolado por flow (ADR-009 revisado): NÃO deriva a sessão nem os demais flows
        desta conexão — só marca este flow `watchdog_dead`. Quem reage derrubando o flow
        (LOCAL) é o flow-runtime, ao consumir `comm_failure` com `flow_id` no payload.
        """
        self._snapshot.flow_watchdog_alive[flow_id] = False
        self._flow_failure_pending[flow_id] = True
        logger.warning(
            "Watchdog do flow %s (conexão %s) sem alternância: %s",
            flow_id,
            self._config.id,
            detail,
        )
        await publish_event(
            self._redis,
            severity="alarm",
            origin=self._origin,
            message=(
                f"Falha de watchdog no flow {flow_id} (conexão '{self._config.name}'): {detail}"
            ),
            kind=KIND_COMM_FAILURE,
            payload={
                "conn_id": self._config.id,
                "flow_id": flow_id,
                "reason": "watchdog_timeout",
                "detail": detail,
            },
        )

    async def _flow_watchdog_alive(self, flow_id: int) -> None:
        """Callback do `WatchdogTask` na 1ª alternância (ou recuperação) do flow.

        Análogo por flow do `mark_restored` da sessão, mas nunca mexe em `state`/sessão —
        o watchdog de um flow não pode reviver nem derrubar a conexão inteira.
        """
        self._flow_gate_generation[flow_id] = self._flow_gate_generation.get(flow_id, 0) + 1
        if not self._flow_failure_pending.get(flow_id):
            return
        self._flow_failure_pending[flow_id] = False
        await publish_event(
            self._redis,
            severity="info",
            origin=self._origin,
            message=(
                f"Watchdog restabelecido no flow {flow_id} (conexão '{self._config.name}')"
            ),
            kind=KIND_COMM_RESTORED,
            payload={"conn_id": self._config.id, "flow_id": flow_id},
        )

    async def apply_tags(self, tags: tuple[TagConfig, ...]) -> None:
        """Troca o conjunto de tags SEM derrubar a sessão (reconciliação, tarefa 1.4).

        Fora de `up` apenas guarda a configuração nova: a próxima subida a usa.
        """
        self._config = replace(self._config, tags=tags)
        self._heartbeat.apply_tags(tags)
        client = self._client
        if self._state is not ConnectionState.UP or client is None:
            return
        try:
            await self._replace_poller(client)
        except Exception as exc:
            await self.fail("session_lost", describe_exception(exc))
            return
        # Reconfiguração pode ter trocado o `node_id` de uma tag `w`. Sem recarregar, o
        # cache devolveria o VariantType do node ANTIGO — e, se os dois tipos
        # coincidissem por acaso, a escrita iria para o node novo com a codificação do
        # velho, sem erro nenhum. Recarregar tudo custa o mesmo que a subida da sessão e
        # é a única opção que mantém o tipo REAL do servidor como autoridade (spec §4.3);
        # invalidar sem recarregar rebaixaria a tag ao tipo declarado, que é justamente o
        # que a spec manda não usar quando o servidor sabe responder.
        await self.load_write_types()

    async def apply_polling_period(self, polling_period_ms: int) -> None:
        """Retima o ciclo SEM derrubar a sessão (reconciliação, tarefa 1.4).

        `polling_period_ms` fica fora da `session_key` justamente para chegar aqui: mudar a
        varredura de 1 s para 2 s não pode custar uma reconexão ao PLC. Fora de `up` apenas
        guarda a configuração nova: a próxima subida a usa.
        """
        self._config = replace(self._config, polling_period_ms=polling_period_ms)
        client = self._client
        if self._state is not ConnectionState.UP or client is None:
            return
        try:
            await self._replace_poller(client)
        except Exception as exc:
            await self.fail("session_lost", describe_exception(exc))

    async def _replace_poller(self, client: Client) -> None:
        """Para o poller atual (se houver) e sobe outro com a configuração corrente."""
        old, self._poller = self._poller, None
        if old is not None:
            await old.stop()
        poller = ValuePoller(
            self._config,
            client,
            self._redis,
            self._snapshot,
            on_hard_failure=self._on_poll_failure,
        )
        await poller.start()
        self._poller = poller

    async def _on_poll_failure(self, detail: str) -> None:
        """Ciclo de leitura que falha em bloco é sessão morta — mesma rota do watchdog."""
        await self.fail("session_lost", detail)

    async def fail(self, reason: FailureReason, detail: str) -> None:
        """Leva a conexão a `failed`: rajada bad, alarme e só então queda da sessão.

        Idempotente em `failed` — tentativa de reconexão em backoff não re-emite alarme
        (spec §3.6). A ordem é normativa (spec §2.2-6/§3.8):

        1. o bloqueio de escrita é simultâneo à detecção, então `state`/`flow_watchdog_alive`
           caem antes de qualquer `await`;
        2. a rajada de `quality=2` vai ao barramento ANTES do alarme, para que quem
           reage ao alarme já leia dado coerente;
        3. a sessão só é derrubada depois do evento: um `disconnect` contra um servidor
           que sumiu pode arrastar segundos, e o orçamento do aceite (<12 s) é medido da
           detecção até o evento.
        """
        if self._state is ConnectionState.FAILED:
            return
        self._state = ConnectionState.FAILED
        self._snapshot.state = ConnectionState.FAILED
        for flow_id in self._snapshot.flow_watchdog_alive:
            self._snapshot.flow_watchdog_alive[flow_id] = False
        self._snapshot.session_up_since = None
        self._failure_pending = True
        # Invalida connect em voo: não pode ressuscitar a conexão depois do alarme.
        self._generation += 1
        logger.warning(
            "Conexão %s (%s) em falha: %s — %s", self._config.id, self._config.name, reason, detail
        )
        await self._heartbeat.burst_bad()
        await publish_event(
            self._redis,
            severity="alarm",
            origin=self._origin,
            message=(
                f"Falha de comunicação na conexão '{self._config.name}': "
                f"{_REASON_TEXT.get(reason, reason)}"
            ),
            kind=KIND_COMM_FAILURE,
            payload={"conn_id": self._config.id, "reason": reason, "detail": detail},
        )
        await self._close_session()

    async def mark_restored(self) -> None:
        """Emite `comm_restored` uma única vez, se havia falha pendente (spec §3.6).

        Chamado sempre que a sessão sobe (ADR-009 revisado: restauração da CONEXÃO não
        depende mais de nenhum watchdog — cada flow tem o `comm_restored` dele, separado,
        emitido por `_flow_watchdog_alive`).

        Também é a aresta de reabertura do gate de sessão (`session_down`): por isso
        `gate_generation` avança AQUI, antes de qualquer guarda — o consumidor de
        `opc.writes` precisa saber que um período de bloqueio acabou mesmo quando nenhuma
        escrita chegou na janela em que o gate esteve aberto, e mesmo na primeira subida,
        quando não há `comm_restored` a emitir (spec §3.4/§4.2-c).
        """
        self._gate_generation += 1
        if not self._failure_pending or self._state is not ConnectionState.UP:
            return
        self._failure_pending = False
        await publish_event(
            self._redis,
            severity="info",
            origin=self._origin,
            message=f"Comunicação restabelecida na conexão '{self._config.name}'",
            kind=KIND_COMM_RESTORED,
            payload={"conn_id": self._config.id},
        )

    @property
    def _origin(self) -> str:
        return f"conn:{self._config.id}"

    @property
    def _pinning_enabled(self) -> bool:
        """Conexão com canal seguro: só nela um prazo estourado pode ser cert divergente."""
        return self._config.security_policy != SECURITY_POLICY_NONE

    async def _supervise(self) -> None:
        """Laço de vida da conexão: conecta, vigia a sessão, reconecta em backoff.

        O backoff governa todo o ciclo de reconexão (spec §2.2-2), não só a falha de
        connect: sem ele, a primeira retomada depois de uma queda de sessão viva iria
        sem throttle nenhum. O contador só zera quando uma sessão chega a `up`.
        """
        attempt = 0
        while True:
            try:
                await self._open_session()
            except Exception as exc:
                await self.fail(*map_connect_exception(exc, pinning_enabled=self._pinning_enabled))
            else:
                attempt = 0
                await self._watch_session()
            await asyncio.sleep(
                backoff_delay(attempt, initial=self._backoff_initial_s, maximum=self._backoff_max_s)
            )
            attempt += 1

    async def _open_session(self) -> None:
        """Conecta e sobe para `up`; qualquer exceção deixa a conexão sem cliente nem peças."""
        generation = self._generation
        client = build_client(self._config)
        try:
            await configure_client(
                client, self._config, certs_dir=self._certs_dir, fernet_key=self._fernet_key
            )
            # auto_reconnect=False: a reconexão e o backoff são nossos (spec §2.2-2).
            await client.connect(auto_reconnect=False)
            self._raise_if_superseded(generation)
            self._client = client
            await self.on_session_up()
            self._raise_if_superseded(generation)
        except BaseException:
            self._client = None
            # `_session_open` ainda é False aqui, então nem `fail()` nem `stop()` chegam ao
            # gancho de saída por este caminho: sem parar as peças agora, a subscription e
            # a task de watchdog que `on_session_up` acabou de criar ficam vivas sem dono,
            # e a próxima tentativa sobrescreve as referências sem pará-las. Erro de
            # limpeza é engolido — o objetivo é não deixar task viva —, mas
            # `CancelledError` não, para `stop()` seguir cancelável.
            with suppress(Exception):
                await self.on_session_down()
            await _disconnect_quiet(client)
            raise
        self._session_open = True
        self._state = ConnectionState.UP
        self._snapshot.state = ConnectionState.UP
        self._snapshot.session_up_since = datetime.now(UTC)
        logger.info("Conexão %s (%s) estabelecida", self._config.id, self._config.name)
        # Watchdog agora é por flow, desacoplado da sessão (ADR-009 revisado): a sessão
        # subir É a restauração, do ponto de vista da conexão. Cada flow tem seu próprio
        # `comm_restored` (com `flow_id`), emitido por `_flow_watchdog_alive` quando (e
        # se) o bit dele armar — não depende deste `mark_restored`.
        await self.mark_restored()

    def _raise_if_superseded(self, generation: int) -> None:
        """Aborta a tentativa se um fail() ocorreu enquanto o connect estava em voo.

        Sem isso, um connect que termina depois do alarme levaria a conexão de volta a
        `up` — e ainda emitiria `comm_restored` sem nada ter se recuperado de verdade.
        """
        if generation != self._generation:
            raise _SupersededAttemptError("tentativa de conexão invalidada por falha concorrente")

    async def _watch_session(self) -> None:
        """Verifica periodicamente se a sessão continua viva; sai ao deixar de estar `up`."""
        while self._state is ConnectionState.UP:
            await asyncio.sleep(SESSION_CHECK_INTERVAL_S)
            client = self.client
            if client is None:
                return
            try:
                await client.nodes.server_state.read_value()
            except Exception as exc:
                await self.fail("session_lost", describe_exception(exc))
                return

    async def _close_session(self) -> None:
        """Desfaz a sessão: gancho de saída, disconnect e limpeza do snapshot."""
        client, self._client = self._client, None
        self._snapshot.session_up_since = None
        if self._session_open:
            self._session_open = False
            await self.on_session_down()
        if client is not None:
            await _disconnect_quiet(client)


async def _disconnect_quiet(client: Client) -> None:
    """Desconecta ignorando erro de transporte: no caminho de falha já não há sessão."""
    try:
        await client.disconnect()
    except Exception:
        logger.debug("Erro ignorado ao desconectar cliente OPC-UA", exc_info=True)
