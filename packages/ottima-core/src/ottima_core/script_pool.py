"""ProcessPool para código Python do usuário (RF-511..514, ADR-018/004, spec F3 §3.3, decisão A-4).

Dois consumidores compartilham este pool, e por isso ele mora no core: o bloco Script de um
flow (`OUT1..OUTn`, orçamento de 0,7 × Ts) e a tag calculada (`OUT`, orçamento de 0,7 × período
— ADR-033). Cada serviço instancia o SEU pool: uma tag calculada nunca disputa worker com a
varredura de um flow.

Por que um pool próprio e não `ProcessPoolExecutor`: ele não interrompe uma tarefa já em
execução. Um `while True` no código do engenheiro ficaria girando para sempre e o executor
nunca devolveria o worker — e "timeout mata o worker e re-sobe" é requisito duro (RF-514).
Aqui cada worker é um processo de vida longa com um `Pipe` duplex; no estouro do orçamento é
`kill()` + `join()` + respawn.

Contexto `spawn`: `fork` num processo que já tem event loop e threads é armadilha conhecida
(estado de locks herdado pela metade). O custo de partida é pago uma vez por worker, porque
eles vivem enquanto o serviço viver.

O pool é **sem estado**: recebe `state`, devolve `state`. A cópia-mestre vive no bloco, que
só a substitui em retorno `ok` — timeout ou exceção nunca corrompem estado (spec §3.3).

Threads: todo I/O bloqueante do `Pipe` sai do event loop num executor **próprio do pool**, não
no default do asyncio (`asyncio.to_thread`). O default tem `min(32, cpu+4)` threads e é dividido
com quem mais chamar `to_thread` no processo — no flow-runtime, com `MpcHost._await_response`,
que prende uma thread por solve em voo durante todo o deadline de 0,7×Ts_mpc. Saturado o default,
o `send`/`_receive` de `run()` esperava na FILA enquanto o orçamento corria, e o flow recebia
`timeout` (ou, pior, um `ok` fora do prazo) sem ter script lento nenhum — acoplamento entre
flows por um recurso que nem o pool nem o host contabilizavam.
"""

import asyncio
import logging
import math
import multiprocessing as mp
import os
import pickle
import traceback
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from multiprocessing.connection import Connection
from multiprocessing.context import SpawnContext, SpawnProcess
from typing import Any, Final, Literal

import numpy

SCRIPT_POOL_SIZE: Final[int] = 4
"""Tamanho do pool, constante de código e não knob de env (padrão spec F2 §10.1).

Dimensionamento RNF-01 é da ordem de 10 flows, e dentro de uma varredura os blocos rodam em
série por `exec_order` — só a concorrência *entre* flows disputa worker. Cada worker é um
processo Python com numpy carregado (~100 MB), então 4 equilibra vazão e memória.
"""

ALLOWED_BUILTINS: Final[dict[str, Any]] = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "len": len,
    "range": range,
    "float": float,
    "int": int,
    "bool": bool,
}
"""Lista fechada e exaustiva (ADR-018, spec §3.3). Sem `__import__`, `import` não resolve
dentro do script; modelo de ameaça é admin autenticado, então não há sandbox adicional."""

_READY: Final[str] = "ready"
_JOIN_TIMEOUT_S: Final[float] = 2.0
_BOOT_TIMEOUT_S: Final[float] = 30.0
"""Partida de um worker `spawn` com numpy: sub-segundo na prática; 30 s é rede de segurança."""

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScriptResult:
    status: Literal["ok", "timeout", "error"]
    outputs: dict[str, float] | None
    state: Any | None
    detail: str | None


# --------------------------------------------------------------------------------------
# Worker (processo filho)
# --------------------------------------------------------------------------------------


def _run_script(
    code: str, inputs: dict[str, float], state: Any, output_names: tuple[str, ...]
) -> ScriptResult:
    """Executa o código do usuário no escopo fechado e valida o que ele produziu.

    Os nomes das saídas chegam prontos do pai: `n_outputs` seria estado redundante aqui, e
    quem chama já sabe se a convenção é `OUT1..OUTn` (bloco Script) ou `OUT` (tag calculada).
    """
    scope: dict[str, Any] = {
        # Cópia por execução: um script que mexesse em `__builtins__` não contamina o próximo
        # job do mesmo worker.
        "__builtins__": dict(ALLOWED_BUILTINS),
        "math": math,
        "numpy": numpy,
        "np": numpy,
        "state": state,
        **inputs,
    }
    try:
        exec(code, scope)  # noqa: S102 - exec de código de usuário é normativo (ADR-018)
    except Exception:
        return ScriptResult("error", None, None, traceback.format_exc())

    outputs: dict[str, float] = {}
    for port in output_names:
        if port not in scope:
            return ScriptResult("error", None, None, f"o script não atribuiu a saída {port}")
        try:
            outputs[port] = float(scope[port])
        except (TypeError, ValueError):
            return ScriptResult(
                "error", None, None, f"a saída {port} do script não é um número: {scope[port]!r}"
            )

    new_state = scope.get("state")
    try:
        # Testar aqui, e não no envio: um erro de pickle no `send` deixaria o pai esperando
        # um resultado que nunca chega, ou um worker vivo com o pipe sujo.
        pickle.dumps(new_state)
    except Exception as exc:
        return ScriptResult(
            "error", None, None, f"o `state` devolvido pelo script não é serializável: {exc}"
        )
    return ScriptResult("ok", outputs, new_state, None)


def _worker_main(conn: Connection) -> None:
    """Alvo do `spawn`: laço de jobs. Nível de módulo porque `spawn` precisa importá-lo."""
    # TD-001: o filho herda OTTIMA_DATABASE_URL/OTTIMA_REDIS_URL do pai (únicas variáveis
    # que o compose injeta no flow-runtime) — essas URLs carregam credencial. Depois do
    # clear, uma eventual fuga do sandbox do Script não encontra segredo nenhum no
    # ambiente. `numpy` já foi importado no import do módulo, então nada depende de
    # variável de ambiente daqui em diante.
    os.environ.clear()
    conn.send(_READY)
    try:
        while True:
            job = conn.recv()
            if job is None:
                return
            conn.send(_run_script(*job))
    except (EOFError, OSError, KeyboardInterrupt):
        return
    finally:
        conn.close()


# --------------------------------------------------------------------------------------
# Pool (processo pai)
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Worker:
    proc: SpawnProcess
    conn: Connection


@dataclass(slots=True)
class _PoolState:
    workers: list[_Worker] = field(default_factory=list)
    booting: set[asyncio.Task[None]] = field(default_factory=set)
    replacing: set[asyncio.Task[None]] = field(default_factory=set)


def _spawn_worker(ctx: SpawnContext) -> _Worker:
    """Sobe um worker. Roda **numa thread** — nunca no event loop (ADR-004)."""
    parent_conn, child_conn = ctx.Pipe(duplex=True)
    proc = ctx.Process(target=_worker_main, args=(child_conn,), daemon=True)
    proc.start()
    # A ponta do filho tem de ser fechada aqui: enquanto o pai a mantiver aberta, a morte do
    # worker nunca vira EOF neste lado.
    child_conn.close()
    return _Worker(proc, parent_conn)


def _receive(conn: Connection, timeout_s: float) -> Any:
    """Espera um resultado no pipe. Roda **numa thread** — nunca no event loop (ADR-004).

    `poll` e `recv` na mesma thread: `poll` só garante que há bytes, não a mensagem inteira,
    então deixar o `recv` para o event loop reintroduziria o bloqueio que se quer evitar.
    """
    if not conn.poll(timeout_s):
        return None
    return conn.recv()


def _shutdown(worker: _Worker, *, hard: bool) -> None:
    """Encerra o processo e fecha o pipe. Roda numa thread; nunca levanta."""
    proc = worker.proc
    try:
        if proc.is_alive():
            proc.kill() if hard else proc.terminate()
            proc.join(_JOIN_TIMEOUT_S)
        if proc.is_alive():
            proc.kill()
            proc.join()
    except (OSError, ValueError):
        pass
    finally:
        try:
            worker.conn.close()
            proc.close()
        except (OSError, ValueError):
            pass


class ScriptPool:
    """Pool de processos de vida longa para o código do usuário."""

    def __init__(self, size: int = SCRIPT_POOL_SIZE) -> None:
        self._size = size
        self._ctx: SpawnContext = mp.get_context("spawn")
        self._state = _PoolState()
        self._idle: asyncio.Queue[_Worker] = asyncio.Queue()
        self._running = False
        self._respawns = 0
        self._executor: ThreadPoolExecutor | None = None

    def _off_loop[T](self, work: Callable[[], T]) -> asyncio.Future[T]:
        """`asyncio.to_thread` do pool: mesma semântica, executor próprio (ver módulo).

        Recebe um invocável sem argumentos porque `run_in_executor` não repassa keywords —
        `partial` no call-site deixa cada chamada legível e uniforme.
        """
        if self._executor is None:
            raise RuntimeError("ScriptPool não está em execução")
        return asyncio.get_running_loop().run_in_executor(self._executor, work)

    @property
    def worker_pids(self) -> tuple[int, ...]:
        """Pids vivos do pool — diagnóstico e verificação de respawn."""
        return tuple(w.proc.pid for w in self._state.workers if w.proc.pid is not None)

    def stats(self) -> dict:
        """Fonte de dados do futuro `/health` (F4b tarefa 2.3): tamanho, ocupação, respawns.

        `busy` conta workers fora da fila de livres (em execução ou ainda subindo o boot);
        `respawns` acumula desde o `start()`, sem contar os spawns iniciais (só reposições
        feitas por `_replace`).
        """
        return {
            "size": self._size,
            "busy": len(self._state.workers) - self._idle.qsize(),
            "respawns": self._respawns,
        }

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # `size + 1` threads, e a conta fecha exata: cada `run()` ocupa no máximo UMA thread
        # por vez (o `send` e o `_receive` são sequenciais) e há no máximo `size` `run()`
        # simultâneos, porque `_idle` só entrega `size` workers; `_spawn`/`_do_replace`/
        # `_enqueue_when_ready` também são sequenciais e cabem no lugar do `run()` do worker
        # que estão repondo. O `+1` cobre o único caso de sobreposição real: o laço de
        # `_shutdown` de `stop()`, que não espera os `run()` em voo.
        self._executor = ThreadPoolExecutor(
            max_workers=self._size + 1, thread_name_prefix="script-pool"
        )
        await asyncio.gather(*(self._spawn() for _ in range(self._size)))
        # Devolver com o pool quente: senão a primeira varredura pagaria o boot dentro do
        # próprio orçamento de 0,7xTs e viraria um timeout espúrio.
        await asyncio.gather(*self._state.booting)

    async def stop(self) -> None:
        """Idempotente e silencioso: parar o runtime não pode levantar (ADR-009)."""
        self._running = False
        # Laço até o ponto fixo, não uma única espera: um `_replace` em voo (capturado em
        # `_state.replacing`) pode terminar E criar uma nova task de boot em
        # `_state.booting` (via `_spawn`) DEPOIS do instantâneo de `pendentes` já ter sido
        # tirado — sem repetir a checagem, essa task nova escapa da espera e `stop()`
        # tentaria desligar o worker dela ao mesmo tempo que o próprio boot (vendo
        # `self._running == False`) já estaria se autodesligando, um `_shutdown` em
        # duplicata no mesmo processo (`proc.close()` chamado duas vezes). Como nenhum
        # `_replace` novo começa depois do `self._running = False` acima, o laço converge
        # em no máximo 2 voltas.
        while True:
            pendentes = tuple(self._state.booting) + tuple(self._state.replacing)
            if not pendentes:
                break
            # Esperar o handshake/replace em vez de cancelar: cancelar a tarefa não
            # interrompe a thread do `poll`/`_spawn_worker`, e um worker que terminasse de
            # subir ou de ser reposto depois do encerramento ficaria órfão fora da lista.
            await asyncio.wait(pendentes, timeout=_BOOT_TIMEOUT_S)
        workers = self._state.workers
        self._state.workers = []
        self._idle = asyncio.Queue()
        for worker in workers:
            await self._off_loop(partial(_shutdown, worker, hard=False))
        # Depois dos workers, nunca antes: os `_shutdown` acima rodam NELE. `wait=False` para
        # não bloquear o event loop — as threads terminam o que já pegaram e morrem sozinhas.
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False)

    async def run(
        self,
        *,
        code: str,
        inputs: dict[str, float],
        state: Any,
        n_outputs: int,
        timeout_s: float,
        output_names: Sequence[str] | None = None,
    ) -> ScriptResult:
        """Executa o script num worker livre dentro do orçamento.

        O orçamento cobre **aquisição + execução**: esperar por worker livre até o prazo
        acabar é `timeout` igual, sem matar ninguém — a fronteira de varredura não se importa
        com o motivo do atraso.

        `output_names` sobrepõe a convenção `OUT1..OUTn` do bloco Script: a tag calculada
        (ADR-033) tem saída única chamada `OUT`, e é o nome que o engenheiro escreve no script.
        """
        if not self._running:
            raise RuntimeError("ScriptPool não está em execução")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        try:
            worker = await asyncio.wait_for(self._idle.get(), max(0.0, deadline - loop.time()))
        except TimeoutError:
            return ScriptResult("timeout", None, None, None)

        try:
            # `send` também pode bloquear (buffer do pipe cheio): a mesma regra do `_receive`
            # vale aqui — nunca no event loop (ADR-004).
            names = (
                tuple(output_names)
                if output_names is not None
                else tuple(f"OUT{index}" for index in range(1, n_outputs + 1))
            )
            # Só `self._idle.get()` acima tem `wait_for`; estas duas idas a thread NÃO — e é
            # deliberado. Um `wait_for` aqui não interromperia a thread que já começou (o
            # future do executor só cancela enquanto está na fila), então o ramo de estouro
            # seguiria para `_replace(hard=True)` e fecharia este `conn` embaixo de uma thread
            # ainda presa em `send`/`poll` — exatamente a corrida que `MpcHost.stop()`
            # documenta evitar. Quem limita o tempo aqui é o executor DEDICADO (nunca há fila:
            # ver `start()`) mais o timeout do próprio `_receive`; o único bloqueio que resta
            # sem prazo é `send` com buffer de pipe cheio, que só ocorre com worker morto ou
            # travado — caso que o `_receive` seguinte já resolve em `timeout` + kill.
            await self._off_loop(partial(worker.conn.send, (code, inputs, state, names)))
            result = await self._off_loop(
                partial(_receive, worker.conn, max(0.0, deadline - loop.time()))
            )
        except asyncio.CancelledError:
            # O worker pode estar rodando código arbitrário do usuário: devolvê-lo à fila é
            # inaceitável — kill + respawn, e o cancelamento segue propagando. `_replace`
            # (abaixo) já se blinda contra uma segunda cancelação chegando aqui — ver o
            # docstring dela para a interleaving exata que isso fecha (débito m3).
            await self._replace(worker, hard=True)
            raise
        except Exception:
            await self._replace(worker, hard=False)
            return ScriptResult("error", None, None, "o worker do pool morreu durante o script")

        if result is None:
            await self._replace(worker, hard=True)
            return ScriptResult("timeout", None, None, None)
        if not isinstance(result, ScriptResult):
            await self._replace(worker, hard=True)
            return ScriptResult("error", None, None, "o worker do pool devolveu lixo no pipe")

        self._idle.put_nowait(worker)
        return result

    async def _spawn(self) -> None:
        # A criação do processo sai do loop (ADR-004): `Process.start()` é uma syscall de
        # custo variável — e este caminho roda no respawn, ou seja, dentro da varredura de um
        # flow que acabou de estourar. Bloquear aqui atrasaria a fronteira de TODOS os flows
        # do processo, não só a do que falhou.
        worker = await self._off_loop(partial(_spawn_worker, self._ctx))
        self._state.workers.append(worker)
        task = asyncio.create_task(self._enqueue_when_ready(worker))
        self._state.booting.add(task)
        task.add_done_callback(self._state.booting.discard)

    async def _enqueue_when_ready(self, worker: _Worker) -> None:
        """Só entra na fila de livres depois do handshake — um worker ainda importando numpy
        consumiria o orçamento de quem o pegasse."""
        try:
            ready = await self._off_loop(partial(_receive, worker.conn, _BOOT_TIMEOUT_S))
        except Exception:
            ready = None
        if ready == _READY and self._running:
            self._idle.put_nowait(worker)
            return
        # Boot falho é máquina quebrada, não condição de corrida: derruba o worker em vez de
        # entrar em laço de respawn. O pool segue menor e as chamadas passam a competir.
        if worker in self._state.workers:
            self._state.workers.remove(worker)
        if ready != _READY:
            # Sem isto o encolhimento era silencioso: em planta só se via `script_timeout`.
            logger.warning(
                "Handshake de boot do worker do pool de scripts falhou; "
                "pool reduzido para %d worker(s)",
                len(self._state.workers),
            )
        await self._off_loop(partial(_shutdown, worker, hard=True))

    async def _replace(self, worker: _Worker, *, hard: bool) -> None:
        """Derruba `worker` e repõe — blindado contra cancelamento nos 4 call-sites de
        `run()` (débito m3, achados 1 e 2 da revisão da tarefa 0.6).

        A reposição de verdade (`_do_replace`) roda numa `Task` própria, rastreada em
        `_state.replacing` e blindada por `asyncio.shield`: uma cancelação chegando
        enquanto `run()` está suspenso aqui — segunda cancelação no ramo
        `except CancelledError`, ou cancelação avulsa nos outros 3 ramos (pipe morto,
        timeout do `_receive`, resultado inválido) — propaga na hora para `run()`, mas
        NÃO interrompe a sequência remove→shutdown→spawn: ela sempre termina em segundo
        plano, e `len(_state.workers) == size` volta a valer. `_state.replacing` segue o
        mesmo padrão de `_state.booting`: `stop()` espera os dois antes de fechar o pool,
        para nunca devolver com um respawn em voo (sem isso, um respawn assim sobreviveria
        a `stop()` como processo órfão).
        """
        task = asyncio.create_task(self._do_replace(worker, hard=hard))
        self._state.replacing.add(task)
        task.add_done_callback(self._state.replacing.discard)
        await asyncio.shield(task)

    async def _do_replace(self, worker: _Worker, *, hard: bool) -> None:
        # Pool já parado: `stop()` é dono de TODO worker, inclusive deste — sair de `_idle` não
        # tira o worker de `_state.workers`, então o laço de desmonte o desliga de qualquer
        # forma. Seguir aqui daria um segundo `_shutdown` CONCORRENTE no mesmo `_Worker`, e
        # `Process.close()` mexe em `_popen`/`_sentinel` sem lock: a colisão sai como
        # `AttributeError`, que escapa do `except (OSError, ValueError)` de `_shutdown` e faz
        # `stop()` levantar (proibido, ADR-009). Além disso o executor do pool já foi desligado,
        # e `_off_loop` levantaria `RuntimeError` no lugar do resultado do script. Reposição
        # tardia não tem o que desligar nem o que repor: é no-op por definição.
        #
        # Um `_do_replace` que COMEÇOU antes do `stop()` não cai aqui: `_replace` o registra em
        # `_state.replacing` antes de suspender, e o laço de ponto fixo de `stop()` o espera.
        if not self._running:
            return
        if worker in self._state.workers:
            self._state.workers.remove(worker)
        await self._off_loop(partial(_shutdown, worker, hard=hard))
        if self._running:
            await self._spawn()
            self._respawns += 1
