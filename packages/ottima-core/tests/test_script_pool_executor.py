"""O orçamento de `ScriptPool.run` é do script, não da fila do ThreadPoolExecutor default.

Regressão de defeito corrigido. `run()` fala com o worker por duas idas a thread (`send` e depois
`_receive`) e elas rodavam via `asyncio.to_thread`, isto é, no executor DEFAULT do asyncio — de
`min(32, cpu+4)` threads (8 num container de 4 núcleos), dividido com quem mais chamasse
`to_thread` no processo. No flow-runtime o outro dono dessas mesmas threads é
`MpcHost._await_response`, que prende UMA thread por solve em voo durante todo o deadline de
0,7xTs_mpc, uma por bloco MPC.

Saturado o default, a ida a thread do script esperava na FILA — e aí o `timeout_s` deixava de
valer, porque só a aquisição do worker (`self._idle.get()`) está sob `wait_for`. Medido neste
cenário antes do fix (2 ocupantes, orçamento 0,35 s, ocupação 1,05 s), o resultado alternava
entre duas manifestações, ambas erradas:

  - **sucesso tardio** (2 de 3 execuções): `status="ok"` em ~1,05 s, 3x o orçamento. O guarda de
    0,7xTs não guardava nada — a varredura estourava em silêncio, contabilizada como
    `flow_overrun` sem nada apontar o script;
  - **`timeout` espúrio**: `_receive` pegava `max(0.0, deadline - loop.time()) == 0.0`, o
    `conn.poll(0)` perdia a corrida com a resposta do worker e o flow recebia `script_timeout`
    sem ter script lento nenhum.

Qual das duas saía dependia de a resposta já estar no buffer do pipe quando `_receive` finalmente
rodava — por isso os asserts cobrem status E tempo decorrido: era o mesmo defeito com duas caras.
`ScriptPool.stats()["busy"]` não denunciava nenhuma delas: o worker do pool estava livre, o que
faltava era thread — acoplamento entre flows por um recurso que nenhuma das duas pontas
contabilizava (o pool conta workers, o `MpcHost` conta processos; ninguém contava threads).

O fix é `ScriptPool._off_loop`/`MpcHost._off_loop`: executor próprio em cada um, dimensionado pela
própria demanda. Este teste fica como regressão — volta a vermelho no dia em que alguém devolver
essas chamadas ao `to_thread`.

O executor default é montado aqui com `loop.set_default_executor` (API pública) em vez de saturar
os `min(32, cpu+4)` reais: mesma fila, tamanho determinístico e independente da máquina. O teste
de controle logo abaixo roda com a MESMA montagem sem ocupantes — é ele que separa "fila cheia" de
"orçamento apertado demais para o round-trip do pipe".
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from ottima_core.script_pool import ScriptPool

CODE = "OUT1 = IN1 * 2.0\n"
BUDGET_S = 0.35
"""0,7 x Ts de 0,5 s: o orçamento que `ScriptBlock` passa no Ts de aceite da F3."""

EXECUTOR_THREADS = 2
"""Tamanho do executor default no teste. Em produção é `min(32, cpu+4)`; o que importa para o
defeito é ser finito e compartilhado, não o número."""

OCUPACAO_S = 3 * BUDGET_S
"""As threads se soltam sozinhas. Soltá-las só depois do `await pool.run(...)` travaria o teste:
`to_thread` não tem timeout, então quem entra na fila do executor espera a vaga, não o prazo."""

PARTIDA_S = 5.0
"""Prazo para as threads ocupantes entrarem. Rede de segurança contra teste pendurado."""


@pytest.fixture
async def pool():
    pool = ScriptPool(size=1)
    # Antes de saturar: o próprio `start()` sobe o worker por `to_thread`.
    await pool.start()
    yield pool
    await pool.stop()


async def _ocupar_executor(quantas: int, entrou: threading.Semaphore, liberar: threading.Event):
    """Prende `quantas` threads do executor default e só volta quando todas estão dentro.

    Mesmo idioma de quem prende thread em produção (`MpcHost._await_response`): `to_thread` de
    uma espera bloqueante. A confirmação é por semáforo não-bloqueante para o event loop seguir
    girando — dormir um tempo fixo aqui deixaria a saturação ao acaso do escalonador.
    """
    ocupantes = [
        asyncio.create_task(asyncio.to_thread(_entrar_e_esperar, entrou, liberar))
        for _ in range(quantas)
    ]
    prazo = time.monotonic() + PARTIDA_S
    for _ in range(quantas):
        while not entrou.acquire(blocking=False):
            assert time.monotonic() < prazo, "as threads do executor default não partiram"
            await asyncio.sleep(0.005)
    return ocupantes


def _entrar_e_esperar(entrou: threading.Semaphore, liberar: threading.Event) -> None:
    entrou.release()
    liberar.wait(OCUPACAO_S)


async def test_script_instantaneo_nao_estoura_por_executor_default_ocupado(pool):
    """Script trivial tem de caber no orçamento mesmo com o executor DEFAULT todo tomado.

    É o cenário de blocos MPC em solve + scripts concorrentes na mesma fronteira. Com o executor
    próprio do pool, o que acontece no default deixou de ser problema do script. Os dois asserts
    finais são um par: status certo NO PRAZO — passar só um deles não é o contrato.
    """
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=EXECUTOR_THREADS))
    entrou, liberar = threading.Semaphore(0), threading.Event()
    ocupantes = await _ocupar_executor(EXECUTOR_THREADS, entrou, liberar)

    inicio = loop.time()
    resultado = await pool.run(
        code=CODE, inputs={"IN1": 21.0}, state=None, n_outputs=1, timeout_s=BUDGET_S
    )
    decorrido = loop.time() - inicio

    # Solta as threads ANTES de qualquer assert: o `pool.stop()` da fixture também precisa delas.
    liberar.set()
    await asyncio.gather(*ocupantes)

    assert resultado.status == "ok", "script instantâneo estourou o orçamento na fila do executor"
    assert resultado.outputs == {"OUT1": 42.0}
    assert decorrido < BUDGET_S, f"{decorrido:.3f}s num script trivial de orçamento {BUDGET_S}s"


async def test_executor_livre_entrega_o_script_dentro_do_orcamento(pool):
    """Controle do teste acima: MESMO executor pequeno, nenhum ocupante.

    Verde aqui e vermelho lá é o que prova que a causa é a fila do executor, e não um orçamento
    apertado demais para o round-trip do pipe. Se este teste ficar vermelho, o problema é a
    máquina ou o pool, não a contenção de threads.
    """
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=EXECUTOR_THREADS))

    inicio = loop.time()
    resultado = await pool.run(
        code=CODE, inputs={"IN1": 21.0}, state=None, n_outputs=1, timeout_s=BUDGET_S
    )
    decorrido = loop.time() - inicio

    assert resultado.status == "ok"
    assert resultado.outputs == {"OUT1": 42.0}
    assert decorrido < BUDGET_S
