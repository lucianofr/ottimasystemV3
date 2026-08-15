"""`stop()` concorrente com um `run()` em voo: nem `stop()` nem `run()` podem levantar.

Lacuna que a revisão da correção do executor apontou: nada exercitava o desmonte do pool com um
script ainda em execução, e é a interleaving mais provável em planta — o `stop()` do runtime chega
enquanto uma varredura está no meio de um Script travado (`while True`, o caso central do RF-514).

Duas invariantes, uma por ponta, e as duas do MESMO caminho:

  - `stop()` NUNCA levanta (ADR-009, docstring de `stop`). O risco é `_shutdown` rodando duas vezes
    CONCORRENTEMENTE no mesmo `_Worker` — uma vez pelo laço de `stop()`, outra pelo `_replace` que
    o `run()` dispara quando seu `_receive` morre junto com o pipe. `Process.close()` mexe em
    `_popen`/`_sentinel` sem lock, e a colisão sai como `AttributeError`, que escapa do
    `except (OSError, ValueError)` de `_shutdown`.
  - `run()` devolve `ScriptResult`, nunca uma exceção de infraestrutura. Com o executor próprio do
    pool (que `stop()` desliga, ao contrário do default do asyncio, que ninguém desliga), um
    `_do_replace` tardio encontrava `self._executor is None` e trocava o resultado do script por
    `RuntimeError` — no ramo `except asyncio.CancelledError` ele até substituía o cancelamento
    original.

Quem fecha as duas é o portão no topo de `_do_replace`: depois de `stop()`, todo worker já é dono
do laço de desmonte — inclusive o que estava emprestado a este `run()`, porque sair de `_idle` não
tira o worker de `_state.workers`. Reposição tardia não tem o que desligar nem o que repor.
"""

import asyncio

import pytest

from ottima_core.script_pool import ScriptPool, ScriptResult

TRAVADO = "while True:\n    pass\n"
"""O caso de uso central do módulo (RF-514): o pool tem de matar o worker e repor."""

ORCAMENTO_S = 5.0
"""Folgado de propósito: quem tem de terminar este `run()` é o `stop()`, não o prazo."""

CHECKOUT_S = 5.0
"""Prazo para o worker sair de `_idle` — rede de segurança contra teste pendurado."""


async def _esperar_checkout(pool: ScriptPool) -> None:
    """Volta quando o `run()` já tomou o worker: é o que torna a corrida com `stop()` real."""
    prazo = asyncio.get_running_loop().time() + CHECKOUT_S
    while pool.stats()["busy"] == 0:
        assert asyncio.get_running_loop().time() < prazo, "o `run()` não pegou worker nenhum"
        await asyncio.sleep(0.01)


async def test_stop_com_script_travado_em_voo_nao_levanta_de_nenhum_lado():
    """Desmonte no meio de um script infinito: `stop()` calado, `run()` com resultado honesto."""
    pool = ScriptPool(size=1)
    await pool.start()
    tarefa = asyncio.create_task(
        pool.run(code=TRAVADO, inputs={}, state=None, n_outputs=1, timeout_s=ORCAMENTO_S)
    )
    await _esperar_checkout(pool)

    # Nenhum `pytest.raises`: o contrato é ausência de exceção. Uma falha aqui é o próprio
    # `AttributeError`/`RuntimeError` subindo, com traceback apontando a linha culpada.
    await pool.stop()

    resultado = await tarefa
    assert isinstance(resultado, ScriptResult), f"run() devolveu {type(resultado).__name__}"
    # `ok` é o único status impossível: o worker foi morto antes de qualquer resposta.
    assert resultado.status in ("timeout", "error"), resultado.status


async def test_stop_e_idempotente_com_script_travado_em_voo():
    """Segundo `stop()` no mesmo estado: continua silencioso e não repõe worker nenhum."""
    pool = ScriptPool(size=1)
    await pool.start()
    tarefa = asyncio.create_task(
        pool.run(code=TRAVADO, inputs={}, state=None, n_outputs=1, timeout_s=ORCAMENTO_S)
    )
    await _esperar_checkout(pool)

    await pool.stop()
    await pool.stop()
    await tarefa

    assert pool.worker_pids == (), f"worker sobrevivente: {pool.worker_pids}"
    assert pool.stats()["size"] == 1  # `size` é configuração, não contagem de vivos


@pytest.mark.parametrize("hard", [False, True])
async def test_reposicao_tardia_apos_stop_nao_levanta(hard: bool):
    """A repro mínima da revisão, pelo caminho direto: `_replace` depois de `stop()` é no-op.

    Caixa-branca de propósito — é o ponto exato onde os 4 ramos de `run()` entram, e testá-lo
    direto pina o contrato sem depender de vencer uma corrida de milissegundos.
    """
    pool = ScriptPool(size=1)
    await pool.start()
    worker = pool._state.workers[0]
    await pool.stop()

    await pool._replace(worker, hard=hard)

    assert pool.stats()["respawns"] == 0, "pool parado não repõe worker"
