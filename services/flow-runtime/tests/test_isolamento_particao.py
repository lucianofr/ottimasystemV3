"""Isolamento temporal ENTRE partições: a alegação central da partição por processo (ADR-004).

Par direto de `test_isolamento_temporal.py`, com um único fator mudado — os dois flows deixam de
dividir um event loop:

    | cenário                          | varreduras do flow rápido em 1,5 s | resultado |
    |----------------------------------|-----------------------------------|-----------|
    | um processo (`test_isolamento_temporal.py`) | 5 de 15                  | xfail     |
    | dois processos (este arquivo)    | ~15 de 15                         | passa     |

É essa diferença, e só ela, que justifica a partição existir: o custo síncrono inline de um bloco
deixa de alcançar a fronteira de varredura de quem está noutra partição. Thread não produziria
este resultado — os blocos inline são Python puro e não soltam o GIL; por isso a partição é por
PROCESSO.

Roda no run DEFAULT, sem o marcador `slow`, mesmo custando spawn de dois processos e 1,5 s de
tempo de parede: são ~1,3% do tempo da suíte, e o repositório não tem CI — a suíte local é o único
portão que existe, então um marcador que a tirasse do default a tiraria de toda execução real.

Não usa `PartitionParent` de propósito. O que está sob teste é a garantia FÍSICA (um event loop por
processo), não o encanamento do pai — que `test_partition.py` cobre em `owns()`, no filtro de
comando e na forma do `/health`. Injetar uvicorn, banco e supervisor aqui só acrescentaria formas
de o teste falhar por motivo alheio ao que ele afirma.
"""

import asyncio
import multiprocessing as mp

from runtime_test_helpers import varrer_em_processo

TS_S = 0.1
CUSTO_S = 1.0
JANELA_S = 1.5
FRONTEIRAS_IDEAIS = int(JANELA_S / TS_S)
MINIMO_ACEITO = 12
"""Mesmos números do irmão de um processo só, para as duas medidas serem comparáveis."""

RECV_TIMEOUT_S = 30.0
"""Teto para o filho responder: spawn reimporta o mundo, e a máquina pode estar carregada."""



async def test_flow_lento_numa_particao_nao_atrasa_o_flow_de_outra(redis_url: str):
    """O flow rápido mantém sua grade enquanto o flow lento gasta 1,0 s numa varredura.

    Os dois sobem ao mesmo tempo, em processos separados, com o mesmo `Ts`. Se a contagem do
    rápido cair para o patamar do teste de um processo (~5), a partição não está isolando nada.
    """
    ctx = mp.get_context("spawn")
    lento_pai, lento_filho = ctx.Pipe()
    rapido_pai, rapido_filho = ctx.Pipe()
    processos = [
        ctx.Process(
            target=varrer_em_processo,
            args=(lento_filho, redis_url, TS_S, CUSTO_S, JANELA_S),
            name="particao-lenta",
        ),
        ctx.Process(
            target=varrer_em_processo,
            args=(rapido_filho, redis_url, TS_S, 0.0, JANELA_S),
            name="particao-rapida",
        ),
    ]
    try:
        for proc in processos:
            proc.start()
        # A ponta do filho tem de fechar aqui: enquanto o pai a mantiver aberta, a morte do filho
        # nunca vira EOF neste lado (mesma nota de `script_pool._spawn_worker`).
        lento_filho.close()
        rapido_filho.close()

        lentas = await asyncio.to_thread(_receber, lento_pai)
        rapidas = await asyncio.to_thread(_receber, rapido_pai)
    finally:
        for proc in processos:
            await asyncio.to_thread(_encerrar, proc)
        lento_pai.close()
        rapido_pai.close()

    assert lentas >= 1, "a partição lenta não chegou a varrer: o cenário não se montou"
    assert rapidas >= MINIMO_ACEITO, (
        f"a partição rápida varreu {rapidas}x em {JANELA_S}s com Ts={TS_S}s"
        f" ({FRONTEIRAS_IDEAIS} fronteiras na grade) enquanto a outra partição bloqueava"
        f" {CUSTO_S}s — a partição não isolou o tempo de varredura"
    )


def _receber(conn) -> int:
    """Espera a contagem do filho. Roda numa thread: `poll`/`recv` bloqueiam (ADR-004)."""
    if not conn.poll(RECV_TIMEOUT_S):
        raise AssertionError(f"partição não respondeu em {RECV_TIMEOUT_S}s")
    return int(conn.recv())


def _encerrar(proc) -> None:
    """Desmonte que nunca levanta, no mesmo padrão de `partition._terminate_child`."""
    try:
        if proc.is_alive():
            proc.terminate()
            proc.join(5.0)
        if proc.is_alive():
            proc.kill()
            proc.join()
    except (OSError, ValueError):
        pass
    finally:
        try:
            proc.close()
        except (OSError, ValueError):
            pass
