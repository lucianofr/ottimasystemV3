"""Partição dos flows em processos (ADR-004: "um event loop por núcleo").

Por que existe. Todo flow de um projeto ativo roda como `asyncio.Task` no MESMO event loop
(`FlowTask.start`, scheduler.py), e um bloco que gasta CPU inline dentro do `step` rouba a
fronteira de varredura dos demais — `blocks/base.py` proíbe isso por contrato, mas nada o
impede estruturalmente. Medido no repo: um flow em `Ts=0,1 s` varre 5x em vez de 15 quando
outro flow segura o loop por 1,0 s (`tests/test_isolamento_temporal.py`); o `engine.process()`
de um Fuzzy de 125 regras custa 17 ms inline. Partição por PROCESSO é o único isolamento real:
thread não serve porque os blocos inline são Python puro e não soltam o GIL.

O que a partição garante, e o que NÃO garante:
    - GARANTE que flows de partições DIFERENTES não disputam event loop nem GIL: são processos
      distintos, cada um com sua grade de varredura.
    - NÃO garante nada entre flows da MESMA partição — eles continuam dividindo um loop. A
      partição divide o raio de alcance do defeito por `count`, não o elimina. É por isso que
      `test_isolamento_temporal.py` segue `xfail`: o invariante que ele afirma (nenhum bloco
      bloqueia o loop) continua valendo por convenção, não por construção.

Topologia (decisão desta tarefa, "C2" — um container, N processos):
    O processo que o compose sobe (`uvicorn ottima_flow_runtime.main:app`) vira PAI quando
    `OTTIMA_FLOW_PARTITIONS > 1`: ele não instancia `Supervisor` nenhum, dá `spawn` em `count`
    filhos e reexpõe na MESMA porta 8002 um `/health` agregado, no MESMO formato de sempre.
    Isso mantém intactos os três lugares onde a suposição "existe UM flow-runtime" está
    codificada e que uma topologia de N containers quebraria: a URL fixa
    `health_url_flow_runtime` (`ottima_core.config`), o `Record<WorkerId, ...>` de chave única
    do frontend (`useWorkersHealth.ts`) e a contagem fixa de serviços do `deploy/smoke.sh`.

Posse de um flow. `flow_id % count == index`, e é só isso: sem lease, sem eleição, sem
coordenação. O que torna isso seguro é o pai ser a ÚNICA autoridade que distribui índice —
`0..count-1`, um por filho — e ADR-017 ("boot parado é lei"): nenhum caminho sobe flow por
estado desejado, só o comando `deploy`, e cada comando cai em exatamente um índice. Não há
janela em que dois processos disputem o mesmo flow, que seria escrita duplicada em planta.

`count == 1` é o caminho de sempre: nenhum processo novo, nenhuma porta nova, `owns()` sempre
verdadeiro. A partição é opt-in por variável de ambiente porque o número certo depende do
hardware do site (RNF-01 fala de um único host on-prem), ao contrário de `SCRIPT_POOL_SIZE`,
que é constante de código.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import urllib.error
import urllib.request
from dataclasses import dataclass
from multiprocessing.context import SpawnContext, SpawnProcess
from typing import Any, Final

logger = logging.getLogger(__name__)

CHILD_PORT_BASE: Final[int] = 8100
"""Porta do filho `i` = `CHILD_PORT_BASE + i`, em 127.0.0.1 e só dentro do container: quem
atende de fora é sempre o pai, na 8002 do compose. Base acima das portas de serviço do projeto
(8001..8004) para nunca colidir com elas."""

HEALTH_TIMEOUT_S: Final[float] = 2.0
"""Orçamento por filho no `/health` agregado. O agregador da API tem seu próprio prazo e o
frontend repete a cada 5 s: filho lento tem de virar `degraded` rápido, não pendurar a resposta."""

MONITOR_INTERVAL_S: Final[float] = 5.0
"""Cadência do laço que reergue filho morto."""


@dataclass(frozen=True, slots=True)
class Partition:
    """Qual fatia dos flows este processo executa.

    `count == 1`/`index == 0` é o runtime não particionado — `owns` devolve `True` para todo
    flow, e nenhum código de partição entra no caminho.
    """

    index: int = 0
    count: int = 1

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError(f"count de partição precisa ser >= 1 (recebido: {self.count})")
        if not 0 <= self.index < self.count:
            raise ValueError(
                f"index de partição precisa estar em 0..{self.count - 1} (recebido: {self.index})"
            )

    @property
    def enabled(self) -> bool:
        """`True` quando há partição de verdade — usado para decidir o modo do processo."""
        return self.count > 1

    @property
    def label(self) -> str:
        """Sufixo de identificação em log e no `/health`. Vazio quando não há partição, para o
        campo `service` seguir exatamente igual ao de sempre no caminho de `count == 1`."""
        return "" if self.count == 1 else f"[{self.index}/{self.count}]"

    def owns(self, flow_id: int) -> bool:
        """Único critério de posse. Ver docstring do módulo para por que basta."""
        return flow_id % self.count == self.index


UNPARTITIONED: Final[Partition] = Partition()
"""Singleton do runtime de um processo. Existe para servir de default de argumento sem chamada
em assinatura (B008): `Partition` é imutável, mas o linter não tem como saber."""


def _fetch_health(port: int) -> dict[str, Any]:
    """`GET /health` de um filho. Roda numa thread: `urlopen` é bloqueante (ADR-004).

    Nunca levanta — filho morto ou lento é `degraded` no corpo, não erro do agregador. Usa
    `urllib` da stdlib em vez de `httpx` de propósito: o pai não justifica dependência nova, e
    o healthcheck do compose já fala HTTP com a stdlib do mesmo jeito.
    """
    import json

    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT_S) as resposta:  # noqa: S310
            return json.loads(resposta.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as erro:
        return {"status": "degraded", "erro": f"{type(erro).__name__}: {erro}"}


class PartitionParent:
    """Dono dos processos filhos e do `/health` agregado.

    Padrão de processo reaproveitado de `script_pool.py`/`mpc/host.py`: `spawn` (nunca `fork`,
    que herdaria estado de um processo com event loop), alvo no nível do módulo, criação e
    espera de processo sempre fora do event loop.
    """

    def __init__(self, count: int, *, target: Any = None) -> None:
        if count < 2:
            raise ValueError("PartitionParent só existe com count >= 2")
        self._count = count
        self._ctx: SpawnContext = mp.get_context("spawn")
        self._target = target if target is not None else _child_main
        self._children: dict[int, SpawnProcess] = {}
        self._monitor: asyncio.Task[None] | None = None
        self._stopped = False

    @property
    def child_pids(self) -> dict[int, int | None]:
        """Índice -> pid. Diagnóstico e verificação de reposição."""
        return {index: proc.pid for index, proc in self._children.items()}

    async def start(self) -> None:
        """Sobe o laço de reposição e os `count` filhos. Idempotente.

        O monitor vem ANTES dos filhos, e a falha de um `spawn` não aborta os outros: é ele quem
        repõe o que não subiu aqui. Fazer o contrário — subir os filhos primeiro e propagar na
        primeira falha — deixava o serviço sem monitor nenhum, e como a idempotência olhava
        `self._children`, um `start()` de novo saía na hora com o runtime pela metade.
        """
        if self._monitor is not None or self._stopped:
            return
        self._monitor = asyncio.create_task(self._monitor_loop(), name="partition-monitor")
        for index in range(self._count):
            try:
                await self._spawn(index)
            except Exception:
                logger.exception(
                    "Partição %d não subiu; o laço de reposição tenta de novo em %ss",
                    index,
                    MONITOR_INTERVAL_S,
                )
        logger.info("Runtime particionado em %d processos: %s", self._count, self.child_pids)

    async def stop(self) -> None:
        """Encerra o laço e todos os filhos. Idempotente e nunca levanta (ADR-009)."""
        if self._stopped:
            return
        self._stopped = True
        monitor, self._monitor = self._monitor, None
        if monitor is not None:
            monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Falha no laço de reposição de partição durante a parada")
        # Em PARALELO, não em série: cada filho tem até `_TERMINATE_TIMEOUT_S` para o desmonte
        # ordenado do lifespan dele, e em série o pior caso seria `count ×` isso — mais do que
        # a janela que o `stop_grace_period` do compose concede antes do SIGKILL, o que mataria
        # as últimas partições ANTES de elas pararem flow e desarmarem MPC (ADR-009). São
        # processos independentes: não há ordem a respeitar entre eles.
        await asyncio.gather(
            *(self._terminate_owned(index) for index in list(self._children)),
            return_exceptions=True,
        )

    async def _terminate_owned(self, index: int) -> None:
        """Encerra o filho `index` — se este chamador for o dono dele.

        O `pop` é o que estabelece a posse, e ele acontece sem `await` no meio: quem tirou a
        entrada do mapa é quem encerra. Sem isso, o `cancel()` de `stop()` pode interromper o
        monitor DENTRO do `to_thread` de um encerramento (a thread não morre com o cancel) e o
        laço de `stop()` encerraria o mesmo `SpawnProcess` em paralelo — dois `proc.close()`
        concorrentes levantam `AttributeError`, que escapa do `except (OSError, ValueError)` de
        `_terminate_child` e faria `stop()` levantar, o que a ADR-009 proíbe. Mesmo defeito que
        a revisão do executor de threads encontrou em `ScriptPool._do_replace`.
        """
        proc = self._children.pop(index, None)
        if proc is None:
            return
        await asyncio.to_thread(_terminate_child, index, proc)

    async def health(self) -> dict[str, Any]:
        """Corpo do `/health` do pai, no MESMO formato de um runtime não particionado.

        `flows` é a união das fatias (as chaves são `flow_id`, disjuntas por construção) e
        `script_pool` é a soma das três chaves de sempre (`size`/`busy`/`respawns`) — o
        agregador da API, o `deploy/smoke.sh` (que exige exatamente essas três) e o frontend
        continuam lendo o que sempre leram. O que é novo aparece em `partitions`, chave
        adicional: consumidor antigo a ignora, operador ganha a visão por processo.
        """
        portas = [CHILD_PORT_BASE + index for index in range(self._count)]
        corpos = await asyncio.gather(
            *(asyncio.to_thread(_fetch_health, porta) for porta in portas)
        )

        flows: dict[str, Any] = {}
        parciais: dict[str, Any] = {}
        pool = {"size": 0, "busy": 0, "respawns": 0}
        degradado = False
        for index, corpo in enumerate(corpos):
            proc = self._children.get(index)
            vivo = proc is not None and proc.is_alive()
            saudavel = vivo and corpo.get("status") == "ok"
            degradado = degradado or not saudavel
            flows.update(corpo.get("flows") or {})
            pool_filho = corpo.get("script_pool") or {}
            for chave in pool:
                valor = pool_filho.get(chave)
                if isinstance(valor, int):
                    pool[chave] += valor
            parciais[str(index)] = {
                "alive": vivo,
                "pid": None if proc is None else proc.pid,
                "status": corpo.get("status", "degraded"),
                "flows": len(corpo.get("flows") or {}),
                "script_pool": pool_filho,
            }
        return {
            "status": "degraded" if degradado else "ok",
            "flows": flows,
            "script_pool": pool,
            "partitions": parciais,
        }

    async def _spawn(self, index: int) -> None:
        proc = await asyncio.to_thread(self._start_child, index)
        self._children[index] = proc

    def _start_child(self, index: int) -> SpawnProcess:
        """Roda numa thread: `Process.start()` é syscall de custo variável (ADR-004)."""
        proc = self._ctx.Process(
            target=self._target,
            args=(index, self._count, CHILD_PORT_BASE + index),
            name=f"flow-runtime-{index}",
            daemon=False,
        )
        proc.start()
        return proc

    async def _monitor_loop(self) -> None:
        """Repõe filho morto. Sem isso, uma partição caída ficaria surda a `deploy` para
        sempre e o operador só descobriria pelo `/health` — o container segue vivo, ao
        contrário do runtime de um processo só, onde o `restart` do compose resolvia.

        Absorve toda exceção por volta, mesmo idioma do `Supervisor._pass`: um `proc.start()`
        que falhe (recurso do SO esgotado, por exemplo) não pode matar a task de reposição —
        seria uma falha transitória deixando TODAS as partições futuras sem quem as reergesse,
        e o serviço só descobriria no próximo `stop()`.
        """
        while True:
            await asyncio.sleep(MONITOR_INTERVAL_S)
            try:
                await self._repor_mortos()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Falha na passada de reposição de partição")

    async def _repor_mortos(self) -> None:
        """Uma passada de reposição sobre TODOS os índices.

        Itera `range(count)`, e não `self._children`: índice AUSENTE é o caso em que um `spawn`
        anterior falhou (`_terminate_owned` tira a entrada do mapa antes de repor). Iterando só
        o mapa, essa partição nunca voltaria a ser considerada e ficaria morta para sempre —
        exatamente o desfecho que o `try/except` do laço acima NÃO resolve, porque ele salva a
        task, não a partição.
        """
        for index in range(self._count):
            proc = self._children.get(index)
            if proc is not None and proc.is_alive():
                continue
            if proc is None:
                logger.error("Partição %d ausente (spawn anterior falhou); repondo.", index)
            else:
                logger.error(
                    "Partição %d morreu (pid=%s, exitcode=%s); repondo. Os flows que ela "
                    "executava ficam PARADOS até um deploy manual (ADR-017).",
                    index,
                    proc.pid,
                    proc.exitcode,
                )
                await self._terminate_owned(index)
            if self._stopped:
                # `stop()` venceu a corrida enquanto o encerramento estava em voo: repor aqui
                # deixaria um filho vivo depois do desmonte do serviço.
                return
            await self._spawn(index)


def _terminate_child(index: int, proc: SpawnProcess) -> None:
    """Encerra um filho. Roda numa thread; nunca levanta — mesmo padrão de
    `script_pool._shutdown`. `terminate` antes de `kill`: o filho tem lifespan de uvicorn a
    executar (parar flows, devolver PID de MPC armado, fechar sessões), e matar direto pularia
    o desmonte ordenado que a ADR-009 exige."""
    try:
        if proc.is_alive():
            proc.terminate()
            proc.join(_TERMINATE_TIMEOUT_S)
        if proc.is_alive():
            logger.warning("Partição %d não saiu em %ss; kill", index, _TERMINATE_TIMEOUT_S)
            proc.kill()
            proc.join()
    except (OSError, ValueError):
        pass
    finally:
        try:
            proc.close()
        except (OSError, ValueError):
            pass


_TERMINATE_TIMEOUT_S: Final[float] = 15.0
"""Prazo do desmonte ordenado de um filho. Generoso de propósito: o lifespan dele para flows,
desarma MPC e devolve PID — cortar isso na metade é o que a ADR-009 proíbe."""


def _child_main(index: int, count: int, port: int) -> None:
    """Alvo do `spawn`, no nível do módulo porque `spawn` precisa importá-lo (mesmo idioma de
    `script_pool._worker_main`). Nada de asyncio aqui: `uvicorn.run` monta o loop do filho.

    O índice chega por ARGUMENTO, não por variável de ambiente: `get_settings()` é `lru_cache`
    e mexer em `os.environ` do filho para furar esse cache seria a versão frágil da mesma
    coisa.
    """
    import uvicorn

    from ottima_flow_runtime.main import build_app

    app = build_app(Partition(index=index, count=count))
    uvicorn.run(app, host="127.0.0.1", port=port, log_config=None)
