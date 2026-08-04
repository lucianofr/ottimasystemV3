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
from typing import Literal

from asyncua import Client
from redis.asyncio import Redis

from ottima_core.bus import KIND_COMM_FAILURE, KIND_COMM_RESTORED, publish_event
from ottima_core.certs import APPLICATION_URI
from ottima_core.security import decrypt_secret

from .state import ConnectionConfig, ConnectionSnapshot, ConnectionState, TagConfig
from .subscriptions import ValueSubscription

logger = logging.getLogger(__name__)

BACKOFF_INITIAL_S = 1.0
BACKOFF_MAX_S = 30.0  # teto (spec §2.2-2)
# Cadência da verificação de sessão viva: queda silenciosa não gera exceção espontânea.
SESSION_CHECK_INTERVAL_S = 1.0
# Acima disso o teto já domina o cálculo; sem o corte, 2**n estoura o float depois de
# algumas horas de conexão fora do ar.
_MAX_BACKOFF_EXPONENT = 32

SECURITY_POLICY_NONE = "none"
AUTH_ANONYMOUS = "anonymous"
AUTH_USER_PASSWORD = "user_password"

FailureReason = Literal[
    "connect_failed", "session_lost", "watchdog_timeout", "cert_mismatch", "cert_missing"
]

# Texto pt-BR para humanos; consumidores fazem match por `kind`/`reason` (spec §7.3).
_REASON_TEXT: dict[str, str] = {
    "connect_failed": "falha ao conectar",
    "session_lost": "sessão perdida",
    "watchdog_timeout": "watchdog sem alternância",
    "cert_mismatch": "certificado do servidor não confere",
    "cert_missing": "certificado do servidor ausente",
}


class SecurityNotAvailableError(RuntimeError):
    """Combinação de segurança ainda não montada (montagem completa: tarefa 2.4/§5.1)."""


class _SupersededAttemptError(RuntimeError):
    """Tentativa de conexão invalidada por um fail() concorrente."""


def backoff_delay(attempt: int, *, initial: float, maximum: float) -> float:
    """Backoff exponencial com teto e full jitter (spec §2.2-2), `attempt` 0-based."""
    top = min(maximum, initial * 2 ** min(attempt, _MAX_BACKOFF_EXPONENT))
    return random.uniform(0.0, top)


def build_client(config: ConnectionConfig, *, certs_dir: Path, fernet_key: str) -> Client:
    """Constrói o Client asyncua da conexão.

    Nesta tarefa apenas `security_policy == "none"` é montado; as políticas
    Basic256Sha256 (Sign/SignAndEncrypt) e a identidade por certificado chegam na
    tarefa 2.4 (spec §5.1) — até lá, levantam SecurityNotAvailableError, que o
    runtime trata como falha dura `connect_failed`.
    """
    if config.security_policy != SECURITY_POLICY_NONE:
        raise SecurityNotAvailableError(
            f"política de segurança {config.security_policy!r} ainda não suportada"
        )
    if config.auth_mode not in (AUTH_ANONYMOUS, AUTH_USER_PASSWORD):
        raise SecurityNotAvailableError(f"modo de autenticação {config.auth_mode!r} não suportado")

    client = Client(config.endpoint)
    # Precisa casar com a SAN URI do certificado de aplicação (tarefa 2.4/ADR-021).
    client.application_uri = APPLICATION_URI

    if config.auth_mode == AUTH_USER_PASSWORD:
        if not config.auth_username or not config.auth_password_enc:
            raise SecurityNotAvailableError("credenciais de usuário incompletas na configuração")
        client.set_user(config.auth_username)
        # A senha em claro vive só nesta variável local: nada de atributo, log ou snapshot.
        client.set_password(_decrypt_password(config.auth_password_enc, fernet_key))
    return client


def _decrypt_password(token: str, fernet_key: str) -> str:
    """Decifra a senha (spec F1 §5.4) trocando qualquer erro por mensagem fixa.

    O texto da exceção original poderia carregar token ou senha para dentro do evento.
    """
    try:
        return decrypt_secret(token, key=fernet_key)
    except Exception as exc:
        raise RuntimeError("falha ao decifrar a senha da conexão") from exc


def describe_exception(exc: BaseException) -> str:
    """Detalhe curto e sem segredo para o payload do evento."""
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


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
        # Edge-trigger dos eventos: só há `comm_restored` depois de um `comm_failure`.
        self._failure_pending = False
        # Geração da tentativa de conexão: fail() a incrementa para invalidar um connect
        # que ainda esteja em voo (ele não pode subir a conexão depois do alarme).
        self._generation = 0

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

    async def start(self) -> None:
        """Cria a task supervisora da conexão e retorna já."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._supervise(), name=f"opc-conn-{self._config.id}")

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
        await self._close_session()

    async def on_session_up(self) -> None:
        """Gancho pós-connect, antes de marcar `up`: cria a subscription de valores.

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

    async def on_session_down(self) -> None:
        """Gancho simétrico, ao sair de `up`: derruba a subscription."""
        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            await subscription.stop()

    async def apply_tags(self, tags: tuple[TagConfig, ...]) -> None:
        """Troca o conjunto de tags SEM derrubar a sessão (reconciliação, tarefa 1.4).

        Fora de `up` apenas guarda a configuração nova: a próxima subida a usa.
        """
        self._config = replace(self._config, tags=tags)
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
        """Leva a conexão a `failed` e emite `comm_failure`. Idempotente em `failed`."""
        if self._state is ConnectionState.FAILED:
            return
        self._state = ConnectionState.FAILED
        self._snapshot.state = ConnectionState.FAILED
        self._failure_pending = True
        # Invalida connect em voo: não pode ressuscitar a conexão depois do alarme.
        self._generation += 1
        await self._close_session()
        logger.warning(
            "Conexão %s (%s) em falha: %s — %s", self._config.id, self._config.name, reason, detail
        )
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

    async def mark_restored(self) -> None:
        """Emite `comm_restored` uma única vez, se havia falha pendente (spec §3.6)."""
        if not self._failure_pending:
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
                await self.fail("connect_failed", describe_exception(exc))
            else:
                attempt = 0
                await self._watch_session()
            await asyncio.sleep(
                backoff_delay(attempt, initial=self._backoff_initial_s, maximum=self._backoff_max_s)
            )
            attempt += 1

    async def _open_session(self) -> None:
        """Conecta e sobe para `up`; qualquer exceção deixa a conexão sem cliente."""
        generation = self._generation
        client = build_client(self._config, certs_dir=self._certs_dir, fernet_key=self._fernet_key)
        try:
            # auto_reconnect=False: a reconexão e o backoff são nossos (spec §2.2-2).
            await client.connect(auto_reconnect=False)
            self._raise_if_superseded(generation)
            self._client = client
            await self.on_session_up()
            self._raise_if_superseded(generation)
        except BaseException:
            self._client = None
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
