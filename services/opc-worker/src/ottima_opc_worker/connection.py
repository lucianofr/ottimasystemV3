"""Runtime de uma conexão OPC-UA: máquina de estados, backoff e eventos (spec F2 §2.2-2/3).

O worker é o supervisor da sessão: o auto-reconnect do asyncua fica desligado para que
`connecting → up → failed` e os eventos de transição (spec §3.6) tenham uma única fonte.
"""

import asyncio
import logging
import random
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from asyncua import Client
from redis.asyncio import Redis

from ottima_core.bus import KIND_COMM_FAILURE, KIND_COMM_RESTORED, publish_event

from .heartbeat import HEARTBEAT_INTERVAL_S, ValueHeartbeat
from .security import (
    FailureReason,
    configure_client,
    describe_exception,
    map_connect_exception,
)
from .state import ConnectionConfig, ConnectionSnapshot, ConnectionState, TagConfig
from .subscriptions import ValueSubscription
from .watchdog import FREEZE_THRESHOLD_S, WatchdogTask

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
    "watchdog_timeout": "watchdog sem alternância",
    "cert_mismatch": "certificado do servidor não confere",
    "cert_missing": "certificado do servidor ausente",
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
        watchdog_freeze_threshold_s: float = FREEZE_THRESHOLD_S,
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
        self._subscription: ValueSubscription | None = None
        self._watchdog: WatchdogTask | None = None
        self._watchdog_freeze_threshold_s = watchdog_freeze_threshold_s
        # Edge-trigger dos eventos: só há `comm_restored` depois de um `comm_failure`.
        self._failure_pending = False
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
    def subscription(self) -> ValueSubscription | None:
        """Subscription de valores viva; None fora de `up`."""
        return self._subscription

    @property
    def watchdog(self) -> WatchdogTask | None:
        """Task de watchdog viva; None fora de `up` ou em conexão sem o par de node_ids."""
        return self._watchdog

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
        """Gancho pós-connect, antes de marcar `up`: sobe subscription e watchdog.

        Falha ao criar a subscription inteira é falha de sessão, não de tag: emite
        `comm_failure` com `session_lost` e devolve a exceção ao supervisor, que fecha o
        cliente e reconecta em backoff.
        """
        client = self._client  # invariante do _open_session; `self.client` só existe em `up`
        if client is None:
            return
        try:
            await self._replace_subscription(client)
        except Exception as exc:
            await self.fail("session_lost", describe_exception(exc))
            raise
        await self._start_watchdog(client)

    async def on_session_down(self) -> None:
        """Gancho simétrico, ao sair de `up`: derruba watchdog e subscription.

        Quem zera `snapshot.watchdog_alive` é `_close_session`, único caminho até aqui.
        """
        watchdog, self._watchdog = self._watchdog, None
        if watchdog is not None:
            await watchdog.stop()
        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            await subscription.stop()

    async def _start_watchdog(self, client: Client) -> None:
        """Sobe o watchdog da sessão, se a conexão tiver o par de node_ids (spec §3.1).

        Sem watchdog a conexão é read-only de fato (spec §3.5): nenhuma task é criada e
        `watchdog_alive` fica `False` para sempre.
        """
        if not self._config.has_watchdog:
            return
        watchdog = WatchdogTask(
            self._config,
            client,
            self._snapshot,
            on_freeze=lambda detail: self.fail("watchdog_timeout", detail),
            on_alive=self.mark_restored,
            on_hard_failure=lambda detail: self.fail("session_lost", detail),
            freeze_threshold_s=self._watchdog_freeze_threshold_s,
        )
        self._watchdog = watchdog
        await watchdog.start()

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
            await self._replace_subscription(client)
        except Exception as exc:
            await self.fail("session_lost", describe_exception(exc))

    async def _replace_subscription(self, client: Client) -> None:
        """Para a subscription atual (se houver) e sobe outra com a configuração corrente."""
        old, self._subscription = self._subscription, None
        if old is not None:
            await old.stop()
        subscription = ValueSubscription(self._config, client, self._redis, self._snapshot)
        await subscription.start()
        self._subscription = subscription

    async def fail(self, reason: FailureReason, detail: str) -> None:
        """Leva a conexão a `failed`: rajada bad, alarme e só então queda da sessão.

        Idempotente em `failed` — tentativa de reconexão em backoff não re-emite alarme
        (spec §3.6). A ordem é normativa (spec §2.2-6/§3.8):

        1. o bloqueio de escrita é simultâneo à detecção, então `state`/`watchdog_alive`
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
        self._snapshot.watchdog_alive = False
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

        Exige sessão `up`: uma alternância tardia do watchdog — a que ainda chega enquanto
        `fail()` derruba a sessão — não pode "restaurar" uma conexão caída.
        """
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
                await self.fail(*map_connect_exception(exc))
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
        if not self._config.has_watchdog:
            # Com watchdog quem restabelece é a alternância do bit (tarefa 2.1, spec §3.6).
            await self.mark_restored()

    def _raise_if_superseded(self, generation: int) -> None:
        """Aborta a tentativa se um fail() ocorreu enquanto o connect estava em voo.

        Sem isso, um connect que termina depois do alarme levaria a conexão de volta a
        `up` — e, sem watchdog, ainda emitiria `comm_restored` sem nada ter se recuperado.
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
        self._snapshot.watchdog_alive = False
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
