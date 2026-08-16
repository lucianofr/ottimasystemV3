"""`MpcHost` — dono, no processo pai, do processo filho do worker MPC (spec F4 §3.6/§4.2/§4.9,
plano F4b tarefa 1.2, ADR-004).

Papel: `mpc/worker.py` (tarefa 1.1) sabe SOLVE — monta o controller e responde
`SolveRequest -> SolveResult` por um `Pipe`. Este módulo sabe PROCESSO: sobe/mata/repõe esse
processo, aplica o orçamento de cadência (spec §4.2: `0.7 x Ts_mpc` medido DO DISPARO) e
isola o resto do runtime de crash/lentidão do worker. Nenhuma lógica de solve mora aqui —
mesma separação de responsabilidade entre `script_pool._worker_main`/`ScriptPool`.

Padrão de processo reaproveitado de `script_pool.py` (achados hard-won da revisão da tarefa
0.6 do F4a):
    - `spawn` (nunca `fork`) via `multiprocessing.get_context("spawn")`: mesmo motivo do
      pool de scripts — herdar locks/estado de um processo com event loop já rodando é
      armadilha conhecida.
    - Criação de processo, `Process.kill()/join()` e I/O bloqueante do `Pipe`
      (`conn.poll()/recv()/send()`) sempre FORA do event loop (ADR-004): são syscalls de
      custo variável e NUNCA podem rodar nele. E fora dele num executor **próprio deste
      host** (`_off_loop`), não no default do asyncio: no default, a espera de um solve —
      uma thread presa pelo deadline inteiro — competia por vaga com o `ScriptPool` e com os
      outros blocos MPC, e o script de um flow sem culpa nenhuma pagava o orçamento na fila.
    - `stats()["respawns"]` só conta REPOSIÇÕES (mesma convenção de `ScriptPool._respawns`):
      o spawn inicial de `start()` não é um respawn.
    - `stop()` espera um PONTO FIXO das tasks em segundo plano antes de desligar o worker
      atual (mesma forma do laço `while pendentes` de `ScriptPool.stop()`) — sem isso, uma
      task de respawn que termine E crie uma nova depois do instantâneo já tirado escaparia
      da espera e viraria processo órfão.

    O QUE NÃO foi reaproveitado, e por quê: o `asyncio.shield` dentro de
    `ScriptPool._replace` existe porque `ScriptPool.run()` é uma corrotina que o CHAMADOR
    `await`s e pode cancelar a qualquer `await` — o shield garante que essa cancelação externa
    não interrompa a sequência kill->respawn no meio. Aqui `dispatch()`/`poll()` são
    SÍNCRONOS por contrato do plano (nunca bloqueiam, nunca são `await`ados) — não existe
    ponto de cancelamento externo atravessando o trabalho em segundo plano deste módulo, então
    o shield seria complexidade sem função. O laço de ponto fixo em `stop()` (a invariante que
    de fato importa aqui) foi mantido.

Deadline medido do disparo (spec §4.2): `dispatch()` manda o `SolveRequest` na hora (envio
síncrono — o payload é um punhado de floats, o buffer do pipe do SO nunca enche para uma
mensagem dessas; ao contrário do `ScriptPool.run()`, `dispatch()` não pode `await`, então não
há como tirar o `send` do event loop aqui sem quebrar o contrato "nunca bloqueia" da
assinatura síncrona) e imediatamente agenda uma task de fundo que espera a resposta em
`_off_loop(partial(_receive, conn, deadline_s))`. O relógio do deadline é o tempo de parede dessa
espera — não o `wall_ms` que `SolveResult` carrega (esse mede só o `make_step` do FILHO;
conflar os dois foi o erro que a revisão da tarefa 1.1 apontou). Estourou -> mata o processo
+ repõe em segundo plano + entrega via `poll()` um `SolveResult` sintético (`status="overrun"`)
uma única vez.

Crash espontâneo (spec §4.9): não há um watcher de processo rodando o tempo todo — a detecção
é preguiçosa, exatamente como a spec pede ("detectado no próximo poll/dispatch"): tanto
`_receive` (quando há um dispatch em voo — EOF/erro de SO no meio da espera vira o sentinel
`_CRASHED`) quanto o topo de `dispatch()` (quando NÃO há dispatch em voo — `proc.is_alive()`
antes de mandar qualquer coisa) alimentam o MESMO caminho de respawn.

`needs_reinit` (contrato da brief, linha 30): o plano deixava a escolha entre expor
`needs_reinit` como propriedade pública OU forçar o campo no request, "decida o mínimo".
Decisão: forçar internamente via `dataclasses.replace(req, reinit=True)` no primeiro dispatch
após qualquer boot/respawn — não abre superfície pública nova (a exata do plano fica intacta)
e não depende do bloco da tarefa 2.1 lembrar de checar uma flag a cada ciclo: o host garante
sozinho a invariante do bumpless (spec §3.6) mesmo que o `SolveRequest` montado pelo bloco
chegue com `reinit=False`.

CONTRATO VINCULANTE para quem consome `poll()` (achado da revisão da tarefa 1.1, carregado
para cá): um `SolveResult` com `status="no_convergence"` chega com `u_plan`/predição/`cost`
POPULADOS — é o iterate não convergido, mantido por valor diagnóstico (spec §5.1). A garantia
"mantém a MV" do §4.9 NÃO é auto-aplicada nesse payload: em NENHUM caso (`overrun`, `error`,
`no_convergence`) o consumidor deve aplicar `u_plan` à planta sem antes checar
`status == "ok"`. Isso é responsabilidade de quem aplica a MV (bloco MPC, tarefa 2.1) — este
host só entrega o resultado como o worker (ou o próprio host, nos casos sintéticos) o produziu.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import multiprocessing as mp
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from multiprocessing.connection import Connection
from multiprocessing.context import SpawnContext, SpawnProcess
from typing import Any, Final

from ottima_core.flowgraph import MpcConfig, derive_horizons

from .worker import SolveRequest, SolveResult, empty_result, worker_main

_READY: Final[str] = "ready"
_JOIN_TIMEOUT_S: Final[float] = 2.0
_BOOT_TIMEOUT_S: Final[float] = 30.0
"""Mesma rede de segurança de `script_pool._BOOT_TIMEOUT_S`/`test_mpc_worker._BOOT_TIMEOUT_S`:
um `spawn` com casadi/do-mpc é sub-segundo na prática."""

logger = logging.getLogger(__name__)

_CRASHED: Final[object] = object()
"""Sentinel devolvido por `_receive`: distingue 'pipe morreu no meio da espera' (crash, spec
§4.9) de 'ninguém respondeu a tempo' (`None`, deadline estourado, spec §4.2) — os dois
caminhos levam a respostas sintéticas DIFERENTES."""


def _receive(conn: Connection, timeout_s: float) -> Any:
    """Espera uma mensagem no pipe com timeout. Roda **numa thread** — nunca no event loop
    (ADR-004), mesmo padrão de `script_pool._receive`.

    Captura `Exception` (não só `EOFError, OSError`, plano 001): `recv()` também levanta
    erro de desserialização (`pickle.UnpicklingError` e parentes) num fluxo
    corrompido-mas-completo-no-header, e para o host isso é indistinguível de "o worker
    morreu" — os dois levam ao mesmo respawn. `BaseException` fica de fora de propósito:
    `CancelledError`/`KeyboardInterrupt` têm de continuar propagando."""
    try:
        if not conn.poll(timeout_s):
            return None
        return conn.recv()
    except Exception:
        return _CRASHED


def _shutdown_worker(proc: SpawnProcess, conn: Connection) -> None:
    """Mata + junta + fecha o pipe. Roda numa thread (ADR-004); nunca levanta — mesmo padrão
    de `script_pool._shutdown` (aqui sempre `kill`: o filho pode estar preso num solve, um
    `terminate()` educado não tem por que funcionar melhor, spec §4.2 já manda matar)."""
    try:
        if proc.is_alive():
            proc.kill()
            proc.join(_JOIN_TIMEOUT_S)
        if proc.is_alive():
            proc.join()
    except (OSError, ValueError):
        pass
    finally:
        try:
            conn.close()
            proc.close()
        except (OSError, ValueError):
            pass


class MpcHost:
    """Dono do processo do worker MPC de UM bloco (spec F4 §3.6/§4.2/§4.9).

    Ver docstring do módulo para o desenho completo (padrão de processo reaproveitado de
    `script_pool.py`, medição do deadline, `needs_reinit` e o contrato de gate em
    `status != "ok"` que quem consome `poll()` PRECISA respeitar).
    """

    def __init__(
        self,
        block_id: str,
        config: MpcConfig,
        ts_flow: float,
        *,
        worker_target: Callable[[Connection, str, float], None] = worker_main,
    ) -> None:
        self._block_id = block_id
        self._ts_flow = ts_flow
        self._worker_target = worker_target
        self._config_json = config.model_dump_json()
        self._ctx: SpawnContext = mp.get_context("spawn")

        tss = [v.tss for v in (*config.variables.cvs, *config.variables.constraints)]
        horizons = derive_horizons(config.multiplier, ts_flow, tss)
        self._deadline_s = 0.7 * horizons.ts_mpc

        self._proc: SpawnProcess | None = None
        self._conn: Connection | None = None
        self._ready = False
        self._busy = False
        self._needs_reinit = True
        self._stopped = False
        self._respawns = 0
        self._last_solve_ms: float | None = None
        self._pending_result: SolveResult | None = None
        self._background: set[asyncio.Task[None]] = set()
        # Executor PRÓPRIO deste host, não o default do asyncio: `_await_response` prende uma
        # thread por solve em voo durante todo o deadline de 0,7xTs_mpc, e no default isso
        # disputava vaga com o `ScriptPool` (e com os outros blocos MPC) — script de um flow
        # sem culpa nenhuma pagava o orçamento na fila. Pico real de demanda é UMA thread: o
        # gating síncrono de `_busy`/`_ready` serializa a atividade de fundo a uma por vez, e o
        # par shutdown+spawn de um respawn é sequencial. A segunda thread é margem deliberada —
        # um executor de 1 devolveria o defeito acima (espera em fila) na primeira atividade de
        # fundo que alguém puser em paralelo.
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"mpc-{block_id}")

    def _off_loop[T](self, work: Callable[[], T]) -> asyncio.Future[T]:
        """`asyncio.to_thread` deste host: mesma semântica, executor próprio.

        Invocável sem argumentos porque `run_in_executor` não repassa keywords — `partial` no
        call-site, mesmo idioma de `ScriptPool._off_loop`.
        """
        return asyncio.get_running_loop().run_in_executor(self._executor, work)

    # ------------------------------------------------------------------------------
    # Interface pública (plano F4b tarefa 1.2)
    # ------------------------------------------------------------------------------

    async def start(self) -> None:
        """Sobe o processo e espera o handshake `("ready", n_x)` — `ready` fica `False` até
        lá. O runtime segue varrendo os outros blocos enquanto isso: só ESTE `await` bloqueia
        (o chamador decide quando pagar esse tempo, não `dispatch()`).

        O boot roda numa task rastreada em `self._background` — não só `await`ada aqui
        diretamente — porque um `stop()` concorrente (chamado antes deste `await` retornar)
        precisa ENXERGAR essa task pendente no laço de ponto fixo: sem isso, `stop()` sairia
        pela espera vazia, leria `proc`/`conn` ainda `None` e retornaria, deixando o processo
        que o boot ainda está subindo vivo e nunca mais rastreado (achado da revisão)."""
        if self._stopped or self._proc is not None:
            return
        task = asyncio.get_running_loop().create_task(self._spawn_and_wait_ready())
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        await task

    @property
    def ready(self) -> bool:
        """`True` só quando há um worker vivo e pronto para receber o PRÓXIMO dispatch —
        `False` antes do primeiro `start()`, durante um rebuild em segundo plano, ou depois
        de `stop()`."""
        return self._ready

    def dispatch(self, req: SolveRequest) -> bool:
        """Manda `req` ao worker. NUNCA bloqueia — `False` cobre TODO caso em que o pedido
        não foi aceito (não pronto, ocupado com outro pedido, em rebuild, ou o processo
        morreu espontaneamente e ainda não foi reposto): quem chama conta isso como overrun
        e mantém a MV, spec §4.2 ("worker indisponível -> conta e pula sem acumular fila").

        O primeiro dispatch aceito após qualquer boot/respawn ignora `req.reinit` e força
        `True` (ver docstring do módulo, seção `needs_reinit`)."""
        if self._stopped or not self._ready or self._busy:
            return False
        proc, conn = self._proc, self._conn
        assert proc is not None and conn is not None  # `_ready` implica os dois setados

        if not proc.is_alive():
            # Crash espontâneo detectado aqui porque não havia NENHUM dispatch em voo para
            # `_receive` notar sozinho (spec §4.9: "detectado no próximo poll/dispatch").
            self._schedule_respawn()
            return False

        to_send = dataclasses.replace(req, reinit=True) if self._needs_reinit else req
        try:
            conn.send(to_send)
        except (OSError, ValueError):
            self._schedule_respawn()
            return False

        self._needs_reinit = False
        self._busy = True
        task = asyncio.get_running_loop().create_task(self._await_response(conn))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

        def _log_se_falhou(task: asyncio.Task[None]) -> None:
            # Defesa em profundidade (plano 001): depois do try/except de
            # `_await_response`, esta task não deveria mais levantar — o mesmo espírito
            # de `supervisor_mpc.py::_log_se_falhou`. Sem este callback a exceção cairia
            # no handler default do asyncio ("Task exception was never retrieved"), sem
            # `block_id` nenhum para localizar o bloco.
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.error(
                    "Task de espera de resposta do worker MPC do bloco '%s' falhou com "
                    "exceção não tratada",
                    self._block_id,
                    exc_info=exc,
                )

        task.add_done_callback(_log_se_falhou)
        return True

    def poll(self) -> SolveResult | None:
        """Consome (uma única vez) o resultado pronto mais recente — real ou sintético
        (overrun/crash). `None` enquanto nada chegou ainda."""
        result, self._pending_result = self._pending_result, None
        return result

    def stats(self) -> dict:
        """`alive`: processo do SO vivo agora (independente de já ter completado o
        handshake — um rebuild em voo pode ter processo vivo e `ready=False`).
        `respawns`: reposições desde `start()` (não conta o spawn inicial).
        `last_solve_ms`: `wall_ms` do último `SolveResult` REAL recebido do filho (nunca o
        placeholder de um overrun/crash sintético) — `None` até o primeiro chegar."""
        alive = self._proc is not None and self._proc.is_alive()
        return {"alive": alive, "respawns": self._respawns, "last_solve_ms": self._last_solve_ms}

    async def stop(self) -> None:
        """Idempotente e sem processo órfão: espera o ponto fixo do que está em segundo
        plano ANTES de desligar o worker atual — desligar (fechar o pipe) enquanto uma task
        ainda está bloqueada em `conn.poll()`/`conn.recv()` do MESMO objeto, numa thread
        diferente, seria uma corrida (mesma nota de `ScriptPool.stop()`)."""
        if self._stopped:
            return
        self._stopped = True
        self._ready = False

        while self._background:
            pending = tuple(self._background)
            await asyncio.wait(pending, timeout=_BOOT_TIMEOUT_S)

        proc, conn = self._proc, self._conn
        self._proc, self._conn = None, None
        if proc is not None and conn is not None:
            await self._off_loop(partial(_shutdown_worker, proc, conn))
        # Depois do worker, nunca antes: o `_shutdown_worker` acima roda nele. `wait=False`
        # para não bloquear o event loop; `stop()` já esperou `_background` esvaziar, então
        # nenhuma espera de solve está em voo aqui.
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------------------
    # Trabalho em segundo plano
    # ------------------------------------------------------------------------------

    async def _await_response(self, conn: Connection) -> None:
        """Task criada por `dispatch()`: espera a resposta (ou o deadline, ou um crash) do
        pedido que acabou de ser mandado por `conn` — `conn` é passado por parâmetro, não
        lido de `self._conn`, para nunca correr atrás de um respawn concorrente que troque
        o pipe embaixo desta espera.

        Defesa em profundidade (plano 001): depois do fix de `_receive`, este `await` não
        deveria mais levantar — mas se levantar mesmo assim (ex.: o executor já desligado
        embaixo de um `stop()` concorrente), o `try/except` trata como crash sintético em
        vez de deixar `self._busy` preso em `True` para sempre. `self._busy = False` roda
        em TODOS os caminhos via `finally`."""
        try:
            outcome = await self._off_loop(partial(_receive, conn, self._deadline_s))
        except Exception:
            logger.exception(
                "Espera de resposta do worker MPC do bloco '%s' levantou exceção fora do "
                "contrato de `_receive` — tratando como crash sintético",
                self._block_id,
            )
            outcome = _CRASHED
        finally:
            self._busy = False

        if outcome is None:
            # Deadline de 0.7xTs_mpc estourado, medido do dispatch (spec §4.2).
            self._pending_result = empty_result(
                status="overrun",
                detail="orçamento de 70% do Ts_mpc excedido",
                wall_ms=self._deadline_s * 1000.0,
            )
            self._schedule_respawn()
            return

        if outcome is _CRASHED:
            self._pending_result = empty_result(status="error", detail="crash", wall_ms=0.0)
            self._schedule_respawn()
            return

        self._last_solve_ms = outcome.wall_ms
        self._pending_result = outcome

    def _schedule_respawn(self) -> None:
        """Agenda `_respawn()` em segundo plano — idempotente: se já há um rebuild em voo
        (`_ready` já `False`) ou o host já está parando, não agenda outro. `_ready` é
        derrubado AQUI, de forma síncrona, e não dentro da task: entre o instante em que
        `dispatch()`/`_await_response()` decide respawnar e o instante em que a task
        realmente começa a rodar não pode haver janela em que um segundo chamador veja
        `_ready=True` e agende um respawn duplicado."""
        if self._stopped or not self._ready:
            return
        self._ready = False
        task = asyncio.get_running_loop().create_task(self._respawn())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _respawn(self) -> None:
        proc, conn = self._proc, self._conn
        # Zera ANTES de desligar: entre este ponto e `self._proc` apontar pro worker NOVO
        # (dentro de `_spawn_and_wait_ready`, só depois do custo inteiro do spawn) não pode
        # sobrar uma referência a um `Process` já fechado — `stats()["alive"]` chama
        # `proc.is_alive()`, que levanta `ValueError` num `Process` fechado; e evita
        # desligar o MESMO worker duas vezes se `stop()` também correr concorrente e ler
        # `self._proc`/`self._conn` (já `None` aqui) no seu próprio trecho de desligamento.
        self._proc, self._conn = None, None
        if proc is not None and conn is not None:
            await self._off_loop(partial(_shutdown_worker, proc, conn))
        self._respawns += 1
        self._needs_reinit = True
        if self._stopped:
            # `stop()` já pediu para encerrar (achado da revisão, mesmo gate de
            # `ScriptPool._do_replace`: `if self._running:` antes de repor) — subir um
            # worker novo aqui seria trabalho jogado fora: `stop()` só está bloqueado
            # esperando ESTA task (rastreada em `_background` por `_schedule_respawn`) e vai
            # encontrar `self._proc`/`self._conn` já `None`, sem nada a desligar de novo.
            return
        await self._spawn_and_wait_ready()

    async def _spawn_and_wait_ready(self) -> None:
        proc, conn = await self._off_loop(self._spawn_worker)
        self._proc, self._conn = proc, conn
        handshake = await self._off_loop(partial(_receive, conn, _BOOT_TIMEOUT_S))
        if self._stopped:
            # `stop()` venceu a corrida enquanto o boot estava em voo (chamado por `start()`
            # OU por `_respawn()`): `self._proc`/`self._conn` já apontam para o processo que
            # acabou de subir — `stop()` (bloqueado na mesma task via `_background`) vai
            # desligá-lo — mas `ready` NUNCA pode virar `True` depois que `stop()` já baixou
            # `_stopped`, ou a property mentiria para quem checasse `host.ready` logo após
            # `await stop()` retornar (achado da revisão).
            return
        if isinstance(handshake, tuple) and len(handshake) == 2 and handshake[0] == _READY:
            self._ready = True
            return
        # Boot falho é máquina quebrada, não condição de corrida (mesma nota de
        # `script_pool._enqueue_when_ready`): não entra em laço de respawn sozinho — fica
        # indisponível até uma intervenção externa (próxima tarefa: expor isso em /health).
        logger.warning(
            "Handshake de boot do worker MPC do bloco '%s' falhou; host segue indisponível",
            self._block_id,
        )

    def _spawn_worker(self) -> tuple[SpawnProcess, Connection]:
        """Sobe um worker novo. Roda **numa thread** — nunca no event loop (ADR-004)."""
        parent_conn, child_conn = self._ctx.Pipe(duplex=True)
        proc = self._ctx.Process(
            target=self._worker_target,
            args=(child_conn, self._config_json, self._ts_flow),
            daemon=True,
        )
        proc.start()
        # A ponta do filho tem de fechar aqui: enquanto o pai a mantiver aberta, a morte do
        # worker nunca vira EOF neste lado (mesma nota de `script_pool._spawn_worker`).
        child_conn.close()
        return proc, parent_conn
