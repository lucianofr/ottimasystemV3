"""Contratos do ProcessPool de scripts e do bloco Script (RF-511..514, ADR-018/004, spec F3 §3.3).

O pool é **real** em toda esta bateria. As duas propriedades que justificam o pool — timeout
que mata de verdade e busy-loop que não trava o event loop — não sobrevivem a um duplo de
subprocesso: um mock devolveria "timeout" sem nunca provar que existe um processo morto nem
que o laço continuou girando.
"""

import asyncio
import json
import logging
import os
import re
import signal
import threading
import time
from multiprocessing.connection import Connection

import pytest
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from conftest import AWAIT_TIMEOUT_S, await_until
from ottima_core.bus import CHANNEL_EVENTS, KIND_SCRIPT_ERROR, KIND_SCRIPT_TIMEOUT
from ottima_flow_runtime import script_pool
from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.script import ScriptBlock
from ottima_flow_runtime.script_pool import ScriptPool

DRAIN_TIMEOUT_S = 5.0
SENTINEL_CHANNEL = "tests.sentinel.script"

BUSY_FOREVER = "while True:\n    pass\n"
"""Laço infinito: só morre se alguém matar o processo."""

BUSY_LONGO = "for _ in range(200000000):\n    pass\n"
"""Laço longo (segundos), porém finito.

Usado no teste de liveness do event loop: com uma implementação que bloqueasse o loop em
`conn.recv()`, o laço termina sozinho e o teste **falha** na asserção dos ticks, em vez de
pendurar a suíte para sempre.
"""

TS_CURTO = 0.3
"""Ts dos testes de timeout do bloco: orçamento de 0,21 s, folgado para IPC e curto para a suíte."""

TS_FOLGADO = 1.0
"""Ts dos testes sem timeout esperado: 0,7 s absorve jitter de máquina carregada."""


def processo_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
async def pool():
    """Pool de 2 workers.

    Dois e não um: quando um teste mata um worker por timeout, a varredura seguinte precisa
    de um worker já pronto — senão ela mediria o tempo de boot do respawn, não o contrato.
    """
    script_pool = ScriptPool(size=2)
    await script_pool.start()
    yield script_pool
    await script_pool.stop()


@pytest.fixture
async def bus(redis_client: Redis):
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_EVENTS, SENTINEL_CHANNEL)
    for _ in range(2):
        message = await pubsub.get_message(timeout=DRAIN_TIMEOUT_S)
        assert message is not None and message["type"] == "subscribe"
    yield pubsub
    await pubsub.aclose()


async def eventos(pubsub: PubSub, redis_client: Redis) -> list[dict]:
    """Eventos já publicados, terminando no sentinela — a ordem de entrega numa conexão é a
    ordem de publicação, então a chegada do sentinela prova que nada ficou pendente."""
    await redis_client.publish(SENTINEL_CHANNEL, "eof")
    collected: list[dict] = []
    while True:
        message = await pubsub.get_message(timeout=DRAIN_TIMEOUT_S)
        assert message is not None, "sentinela não chegou: assinatura ou Redis inconsistente"
        if message["type"] != "message":
            continue
        if message["channel"] == SENTINEL_CHANNEL:
            return collected
        collected.append(json.loads(message["data"]))


def bloco(
    code: str,
    redis_client: Redis,
    pool: ScriptPool,
    *,
    n_inputs: int = 1,
    n_outputs: int = 1,
    ts_seconds: float = TS_FOLGADO,
) -> ScriptBlock:
    return ScriptBlock(
        "b9",
        code=code,
        n_inputs=n_inputs,
        n_outputs=n_outputs,
        flow_id=7,
        ts_seconds=ts_seconds,
        pool=pool,
        redis_client=redis_client,
    )


# --------------------------------------------------------------------------------------
# ScriptPool
# --------------------------------------------------------------------------------------


async def test_pool_executa_script_e_devolve_as_saidas(pool):
    result = await pool.run(
        code="OUT1 = IN1 * 2\n", inputs={"IN1": 21.0}, state=None, n_outputs=1, timeout_s=5.0
    )

    assert result.status == "ok"
    assert result.outputs == {"OUT1": 42.0}
    assert result.detail is None


async def test_pool_timeout_mata_o_worker_e_re_sobe(pool):
    """RF-514: o orçamento estourado mata o processo e o pool volta ao tamanho nominal."""
    antes = set(pool.worker_pids)
    loop = asyncio.get_running_loop()

    inicio = loop.time()
    result = await pool.run(code=BUSY_FOREVER, inputs={}, state=None, n_outputs=0, timeout_s=0.3)
    decorrido = loop.time() - inicio

    assert result.status == "timeout"
    assert decorrido < 2.0, "o timeout não respeitou o orçamento"

    mortos = antes - set(pool.worker_pids)
    assert len(mortos) == 1
    await await_until(lambda: not processo_vivo(next(iter(mortos))))
    assert len(pool.worker_pids) == 2

    depois = await pool.run(code="OUT1 = 7.0\n", inputs={}, state=None, n_outputs=1, timeout_s=10.0)
    assert depois.status == "ok" and depois.outputs == {"OUT1": 7.0}


async def test_busy_loop_nao_trava_o_event_loop(pool):
    """ADR-004: a espera pelo worker é feita fora do loop, então o serviço continua girando.

    Com `conn.recv()` direto no loop os ticks ficariam parados e `await_until` estouraria o
    prazo — o laço do script é longo mas finito justamente para o teste falhar em vez de
    pendurar nesse cenário.
    """
    ticks = 0
    parar = False

    async def ticker() -> None:
        nonlocal ticks
        while not parar:
            ticks += 1
            await asyncio.sleep(0)

    tarefa_ticker = asyncio.create_task(ticker())
    corrida = asyncio.create_task(
        pool.run(code=BUSY_LONGO, inputs={}, state=None, n_outputs=0, timeout_s=0.5)
    )
    try:
        await await_until(lambda: ticks > 500, timeout_s=2.0)
        assert not corrida.done(), "o run terminou antes: o teste não observou o bloqueio"
        assert (await corrida).status == "timeout"
    finally:
        parar = True
        await tarefa_ticker


async def test_respawn_nao_trava_o_event_loop(pool, monkeypatch):
    """ADR-004: a subida do processo do respawn também roda fora do loop.

    `Process.start()` custa ~0,6 ms nesta máquina (medido), curto demais para um teste de
    folga distinguir do ruído do escalonador. Por isso o custo é **amplificado**: o
    `_spawn_worker` real continua criando o processo de verdade — o pool segue real, o
    worker é morto de verdade — e só é embrulhado num atraso conhecido. Se a subida rodasse
    no event loop, esse atraso apareceria inteiro como uma lacuna entre dois ticks.
    """
    atraso_s = 0.2
    original = script_pool._spawn_worker
    subidas = 0

    def subida_lenta(ctx):
        nonlocal subidas
        subidas += 1
        time.sleep(atraso_s)
        return original(ctx)

    monkeypatch.setattr(script_pool, "_spawn_worker", subida_lenta)

    maior_lacuna = 0.0
    parar = False

    async def ticker() -> None:
        nonlocal maior_lacuna
        loop = asyncio.get_running_loop()
        anterior = loop.time()
        while not parar:
            await asyncio.sleep(0)
            agora = loop.time()
            maior_lacuna = max(maior_lacuna, agora - anterior)
            anterior = agora

    tarefa_ticker = asyncio.create_task(ticker())
    try:
        result = await pool.run(
            code=BUSY_FOREVER, inputs={}, state=None, n_outputs=0, timeout_s=0.3
        )
    finally:
        parar = True
        await tarefa_ticker

    assert result.status == "timeout"
    assert subidas == 1, "não houve respawn: o teste não mediu o que promete"
    assert maior_lacuna < atraso_s / 2, (
        f"o event loop ficou parado {maior_lacuna:.3f} s durante o respawn"
    )


async def test_import_esta_bloqueado_no_escopo(pool):
    """ADR-018: sem `__import__` no dict de builtins, `import` não compila em runtime."""
    result = await pool.run(
        code="import os\nOUT1 = 1.0\n", inputs={}, state=None, n_outputs=1, timeout_s=5.0
    )

    assert result.status == "error"
    assert "__import__" in result.detail


async def test_builtins_fora_da_lista_nao_existem(pool):
    result = await pool.run(
        code="OUT1 = float(len(open('/etc/passwd').read()))\n",
        inputs={},
        state=None,
        n_outputs=1,
        timeout_s=5.0,
    )

    assert result.status == "error"
    assert "open" in result.detail


async def test_math_numpy_e_alias_np_disponiveis(pool):
    code = "OUT1 = math.sqrt(IN1)\nOUT2 = float(np.mean(numpy.array([1.0, 3.0])))\n"

    result = await pool.run(code=code, inputs={"IN1": 9.0}, state=None, n_outputs=2, timeout_s=5.0)

    assert result.status == "ok"
    assert result.outputs == {"OUT1": 3.0, "OUT2": 2.0}


async def test_saida_nao_atribuida_e_erro_de_script(pool):
    """Determinismo (spec §3.3): OUTx ausente é erro, não 0.0 sintético."""
    result = await pool.run(code="OUT1 = 1.0\n", inputs={}, state=None, n_outputs=2, timeout_s=5.0)

    assert result.status == "error"
    assert "OUT2" in result.detail


async def test_state_nao_picklavel_e_erro_e_o_pool_sobrevive(pool):
    result = await pool.run(
        code="state = lambda x: x\nOUT1 = 1.0\n",
        inputs={},
        state={},
        n_outputs=1,
        timeout_s=5.0,
    )

    assert result.status == "error"
    assert result.detail

    seguinte = await pool.run(
        code="OUT1 = 2.0\n", inputs={}, state=None, n_outputs=1, timeout_s=5.0
    )
    assert seguinte.status == "ok"


async def test_state_faz_round_trip_entre_chamadas(pool):
    code = "state['n'] = state['n'] + 1\nOUT1 = float(state['n'])\n"

    primeiro = await pool.run(code=code, inputs={}, state={"n": 0}, n_outputs=1, timeout_s=5.0)
    segundo = await pool.run(code=code, inputs={}, state=primeiro.state, n_outputs=1, timeout_s=5.0)

    assert primeiro.outputs == {"OUT1": 1.0}
    assert segundo.outputs == {"OUT1": 2.0}
    assert segundo.state == {"n": 2}


async def test_stop_e_idempotente_e_run_depois_de_stop_levanta(pool):
    await pool.stop()
    await pool.stop()

    with pytest.raises(RuntimeError):
        await pool.run(code="OUT1 = 1.0\n", inputs={}, state=None, n_outputs=1, timeout_s=5.0)


async def test_mais_chamadas_simultaneas_que_workers_completam_todas(pool):
    chamadas = [
        pool.run(
            code="OUT1 = IN1 * 2\n",
            inputs={"IN1": float(i)},
            state=None,
            n_outputs=1,
            timeout_s=10.0,
        )
        for i in range(6)
    ]

    resultados = await asyncio.gather(*chamadas)

    assert [r.outputs["OUT1"] for r in resultados] == [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
    assert len(pool.worker_pids) == 2
    assert all(processo_vivo(pid) for pid in pool.worker_pids)


async def test_cancelamento_no_meio_do_script_mata_o_worker_e_re_poe_o_pool(pool, monkeypatch):
    """Achado C2 da revisão F3: `FlowTask.stop()` cancela a varredura no `to_thread`.

    O worker cancelado pode estar rodando código arbitrário do usuário: ele NUNCA volta à
    fila — kill + respawn, e o `CancelledError` segue propagando. Antes da correção o
    worker ficava órfão (vivo, fora da fila) e o pool encolhia a cada cancelamento, então
    este teste falha nas asserções (a) e (b). O espião no `_receive` garante que o
    cancelamento cai exatamente no ponto do `to_thread`, sem sleep cego.
    """
    entrou_no_receive = threading.Event()
    conexao_usada: list[Connection] = []
    receive_real = script_pool._receive

    def espiao_receive(conn, timeout_s):
        conexao_usada.append(conn)
        entrou_no_receive.set()
        return receive_real(conn, timeout_s)

    monkeypatch.setattr(script_pool, "_receive", espiao_receive)

    corrida = asyncio.create_task(
        pool.run(code=BUSY_FOREVER, inputs={}, state=None, n_outputs=0, timeout_s=30.0)
    )
    assert await asyncio.to_thread(entrou_no_receive.wait, AWAIT_TIMEOUT_S)
    # Neste instante o worker ocupado consta no estado em qualquer versão do código: é assim
    # que o seu pid é identificado sem depender do desfecho.
    pid_alvo = next(w.proc.pid for w in pool._state.workers if w.conn is conexao_usada[0])
    assert pid_alvo is not None

    corrida.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await corrida
        # (c) o cancelamento não foi engolido pelo tratamento.
        assert corrida.cancelled()
        # (b) o órfão morreu de verdade (kill + join do `_replace`, hard).
        await await_until(lambda: not processo_vivo(pid_alvo))
        # (a) o pool voltou ao tamanho cheio de workers LIVRES (respawn + handshake).
        await await_until(lambda: pool._idle.qsize() == 2)
        assert len(pool.worker_pids) == 2
        assert pid_alvo not in pool.worker_pids

        depois = await pool.run(
            code="OUT1 = 7.0\n", inputs={}, state=None, n_outputs=1, timeout_s=10.0
        )
        assert depois.status == "ok" and depois.outputs == {"OUT1": 7.0}
    finally:
        # No estado vermelho o órfão sobrevive: não deixar um `while True` queimando CPU
        # pelo resto da sessão de testes.
        try:
            os.kill(pid_alvo, signal.SIGKILL)
        except ProcessLookupError:
            pass


async def test_dupla_cancelacao_durante_replace_nao_encolhe_o_pool(pool, monkeypatch):
    """Débito m3: uma SEGUNDA `CancelledError` chegando enquanto `run()` já está dentro do
    `except CancelledError: await self._replace(...)` (ex.: dois `asyncio.timeout`
    aninhados estourando em sequência antes do respawn terminar) não pode encolher o
    pool. Sem a blindagem (`asyncio.shield`), essa segunda cancelação interrompe
    `_replace` exatamente entre o `remove` (síncrono) e o `await self._spawn()`, e o
    worker derrubado nunca é reposto — o pool perde 1 worker para sempre. O espião em
    `_shutdown` trava o `_replace` bem no `to_thread` do desligamento: o ponto exato onde
    a segunda cancelação precisa pousar para reproduzir a falha, sem sleep cego.
    """
    entrou_no_receive = threading.Event()
    entrou_no_shutdown = threading.Event()
    liberar_shutdown = threading.Event()
    receive_real = script_pool._receive
    shutdown_real = script_pool._shutdown

    def espiao_receive(conn, timeout_s):
        entrou_no_receive.set()
        return receive_real(conn, timeout_s)

    def espiao_shutdown(worker, *, hard):
        entrou_no_shutdown.set()
        liberar_shutdown.wait(AWAIT_TIMEOUT_S)
        shutdown_real(worker, hard=hard)

    monkeypatch.setattr(script_pool, "_receive", espiao_receive)
    monkeypatch.setattr(script_pool, "_shutdown", espiao_shutdown)

    tamanho = pool.stats()["size"]
    corrida = asyncio.create_task(
        pool.run(code=BUSY_FOREVER, inputs={}, state=None, n_outputs=0, timeout_s=30.0)
    )
    assert await asyncio.to_thread(entrou_no_receive.wait, AWAIT_TIMEOUT_S)
    corrida.cancel()  # 1a cancelação: pousa no to_thread(_receive), cai no `except`

    assert await asyncio.to_thread(entrou_no_shutdown.wait, AWAIT_TIMEOUT_S)
    # `_replace` está suspenso aqui em `await asyncio.to_thread(_shutdown, ...)`, travado
    # em `liberar_shutdown`: ponto exato para a 2a cancelação testar a blindagem.
    corrida.cancel()  # 2a cancelação: pousa dentro do `_replace` já em andamento
    liberar_shutdown.set()

    with pytest.raises(asyncio.CancelledError):
        await corrida
    assert corrida.cancelled()

    # Sem a blindagem o `_replace` foi interrompido entre o `remove` e o `_spawn`: o
    # déficit é permanente e este `await_until` estoura. Com a blindagem, o respawn
    # completa em segundo plano assim que `liberar_shutdown` libera a thread.
    await await_until(lambda: len(pool._state.workers) == tamanho)
    assert pool.stats()["size"] == len(pool._state.workers) == tamanho

    depois = await pool.run(
        code="OUT1 = 7.0\n", inputs={}, state=None, n_outputs=1, timeout_s=10.0
    )
    assert depois.status == "ok" and depois.outputs == {"OUT1": 7.0}


async def test_dez_ciclos_de_cancelamento_preservam_o_tamanho_do_pool(pool, monkeypatch):
    """Regressão do teto (débito m3): mesmo sob N cancelamentos em sequência, ciclo após
    ciclo, o pool nunca sai do tamanho configurado e continua servindo scripts com
    sucesso — sem drift acumulado."""
    entrou_no_receive = threading.Event()
    receive_real = script_pool._receive

    def espiao_receive(conn, timeout_s):
        entrou_no_receive.set()
        return receive_real(conn, timeout_s)

    monkeypatch.setattr(script_pool, "_receive", espiao_receive)
    tamanho = pool.stats()["size"]

    for ciclo in range(10):
        entrou_no_receive.clear()
        corrida = asyncio.create_task(
            pool.run(code=BUSY_FOREVER, inputs={}, state=None, n_outputs=0, timeout_s=30.0)
        )
        assert await asyncio.to_thread(entrou_no_receive.wait, AWAIT_TIMEOUT_S), (
            f"ciclo {ciclo}: cancelamento não pousou dentro do script"
        )
        corrida.cancel()
        with pytest.raises(asyncio.CancelledError):
            await corrida
        await await_until(lambda: len(pool._state.workers) == tamanho)
        assert pool.stats()["size"] == len(pool._state.workers) == tamanho, f"ciclo {ciclo}"

    resultado = await pool.run(
        code="OUT1 = 9.0\n", inputs={}, state=None, n_outputs=1, timeout_s=10.0
    )
    assert resultado.status == "ok" and resultado.outputs == {"OUT1": 9.0}


async def test_stats_conta_respawns_e_reflete_ocupacao(pool, monkeypatch):
    """`stats()` é a fonte do futuro `/health` (F4b 2.3): `size` fixo, `busy` reflete
    workers fora da fila livre, `respawns` cresce exatamente com as reposições reais
    (não com o `start()` inicial)."""
    assert pool.stats() == {"size": 2, "busy": 0, "respawns": 0}

    entrou_no_receive = threading.Event()
    receive_real = script_pool._receive

    def espiao_receive(conn, timeout_s):
        entrou_no_receive.set()
        return receive_real(conn, timeout_s)

    monkeypatch.setattr(script_pool, "_receive", espiao_receive)

    for ciclo_esperado in (1, 2):
        entrou_no_receive.clear()
        corrida = asyncio.create_task(
            pool.run(code=BUSY_FOREVER, inputs={}, state=None, n_outputs=0, timeout_s=30.0)
        )
        assert await asyncio.to_thread(entrou_no_receive.wait, AWAIT_TIMEOUT_S)
        assert pool.stats()["busy"] == 1  # worker em execução: fora da fila livre

        corrida.cancel()
        with pytest.raises(asyncio.CancelledError):
            await corrida
        await await_until(
            lambda esperado=ciclo_esperado: pool.stats()
            == {"size": 2, "busy": 0, "respawns": esperado}
        )
        assert pool.stats() == {"size": 2, "busy": 0, "respawns": ciclo_esperado}


async def test_envio_do_job_roda_fora_do_event_loop(pool, monkeypatch):
    """ADR-004: `conn.send` pode bloquear com o buffer do pipe cheio — vai para thread.

    Identidade de thread é o observável honesto: antes da correção o `send` rodava no
    próprio event loop e a asserção final falhava. O espião é na classe `Connection`, não
    no pool: os `send` dos workers rodam em outros processos e não poluem a medição.
    """
    thread_do_loop = threading.get_ident()
    threads_do_send: list[int] = []
    send_real = Connection.send

    def espiao_send(self, obj):
        threads_do_send.append(threading.get_ident())
        send_real(self, obj)

    monkeypatch.setattr(Connection, "send", espiao_send)

    result = await pool.run(code="OUT1 = 1.0\n", inputs={}, state=None, n_outputs=1, timeout_s=5.0)

    assert result.status == "ok"
    assert threads_do_send, "o send não foi observado: o teste não mediu o que promete"
    assert thread_do_loop not in threads_do_send


async def test_handshake_de_boot_falho_loga_o_tamanho_do_pool_que_sobrou(monkeypatch, caplog):
    """Boot falho derruba o worker e o pool segue menor — agora com rastro em warning.

    Antes da correção o encolhimento era silencioso: em planta o único sintoma era
    `script_timeout`, sem nada que apontasse a causa.
    """
    monkeypatch.setattr(script_pool, "_receive", lambda conn, timeout_s: None)
    pool_local = ScriptPool(size=2)

    with caplog.at_level(logging.WARNING, logger="ottima_flow_runtime.script_pool"):
        await pool_local.start()

    try:
        assert pool_local.worker_pids == ()
        # O tamanho exato em cada aviso depende do interleaving entre os dois boots (o
        # primeiro pode falhar antes de o segundo worker entrar na lista); o contrato é
        # nomear a falha e o tamanho que sobrou, seja ele qual for.
        avisos = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert len(avisos) == 2
        padrao = re.compile(r"Handshake de boot.*pool reduzido para \d+ worker\(s\)")
        assert all(padrao.search(aviso) for aviso in avisos)
    finally:
        await pool_local.stop()


# --------------------------------------------------------------------------------------
# ScriptBlock
# --------------------------------------------------------------------------------------


async def test_timeout_mantem_as_saidas_e_nao_move_o_state(redis_client, bus, pool):
    """RF-514: saídas verbatim da última varredura boa e cópia-mestre intacta.

    A terceira varredura prova o `state`: se o timeout tivesse avançado a cópia-mestre para
    2, o script sairia do ramo do laço infinito e devolveria um valor.
    """
    code = """
n = state.get('n', 0)
if n == 1:
    while True:
        pass
state['n'] = n + 1
OUT1 = float(n + 10)
"""
    block = bloco(code, redis_client, pool, n_inputs=0, ts_seconds=TS_CURTO)

    sucesso = await block.step({})
    primeiro_timeout = await block.step({})
    segundo_timeout = await block.step({})

    assert sucesso == {"OUT1": PortSample(10.0, True)}
    assert primeiro_timeout == sucesso
    assert segundo_timeout == sucesso


async def test_erro_desde_a_primeira_varredura_deixa_saidas_nulas(redis_client, bus, pool):
    """E2E-F3-10 em unidade: antes do 1º sucesso não há saída para manter."""
    block = bloco("OUT1 = 1 / 0\n", redis_client, pool, n_inputs=0)

    assert await block.step({}) == {"OUT1": PortSample(None, False)}

    publicados = await eventos(bus, redis_client)
    assert len(publicados) == 1
    assert publicados[0]["payload"]["kind"] == KIND_SCRIPT_ERROR
    assert publicados[0]["severity"] == "alarm"
    assert publicados[0]["origin"] == "flow:7/block:b9"
    assert "ZeroDivisionError" in publicados[0]["payload"]["detail"]


async def test_dedupe_de_script_error_por_periodo_de_falha(redis_client, bus, pool):
    code = "if IN1 > 0:\n    OUT1 = 1.0\nelse:\n    OUT1 = 1 / 0\n"
    block = bloco(code, redis_client, pool)
    ruim = {"IN1": PortSample(-1.0, True)}
    bom = {"IN1": PortSample(1.0, True)}

    for _ in range(3):
        await block.step(ruim)
    await block.step(bom)
    await block.step(ruim)

    publicados = await eventos(bus, redis_client)
    assert [e["payload"]["kind"] for e in publicados] == [KIND_SCRIPT_ERROR, KIND_SCRIPT_ERROR]


async def test_transicao_erro_para_timeout_emite_os_dois_eventos(redis_client, bus, pool):
    code = "if IN1 > 0:\n    while True:\n        pass\nOUT1 = 1 / 0\n"
    block = bloco(code, redis_client, pool, ts_seconds=TS_CURTO)

    await block.step({"IN1": PortSample(-1.0, True)})
    await block.step({"IN1": PortSample(1.0, True)})

    publicados = await eventos(bus, redis_client)
    assert [e["payload"]["kind"] for e in publicados] == [KIND_SCRIPT_ERROR, KIND_SCRIPT_TIMEOUT]
    assert publicados[1]["payload"]["timeout_s"] == pytest.approx(0.7 * TS_CURTO)


async def test_entrada_booleana_chega_como_float(redis_client, bus, pool):
    """Decisão A-5: `True` vira 1.0 antes do IPC.

    `IN1 is True` é a única checagem de tipo possível dentro do escopo fechado (não há
    `type` nem `isinstance` na lista de builtins) — e é suficiente aqui.
    """
    block = bloco("OUT1 = 0.0 if IN1 is True else IN1\n", redis_client, pool)

    assert await block.step({"IN1": PortSample(True, True)}) == {"OUT1": PortSample(1.0, True)}


async def test_invalidez_propaga_para_as_saidas(redis_client, bus, pool):
    """Decisão A-6: valor conhecido com flag ruim executa o script e contamina a saída."""
    block = bloco("OUT1 = IN1 * 3\n", redis_client, pool)

    assert await block.step({"IN1": PortSample(2.0, False)}) == {"OUT1": PortSample(6.0, False)}


async def test_cold_start_nao_chama_o_script(redis_client, bus, pool):
    """Spec §3.0: entrada sem valor não executa — provado pelo contador no `state`."""
    code = "state['n'] = state.get('n', 0) + 1\nOUT1 = float(state['n'])\n"
    block = bloco(code, redis_client, pool)

    frio = await block.step({"IN1": PortSample(None, True)})
    quente = await block.step({"IN1": PortSample(1.0, True)})

    assert frio == {"OUT1": PortSample(None, False)}
    assert quente == {"OUT1": PortSample(1.0, True)}
    assert await eventos(bus, redis_client) == []


async def test_reset_zera_state_e_ultimas_saidas(redis_client, bus, pool):
    """RF-512: parar o flow zera o estado; as saídas voltam a `null`."""
    code = """
if IN1 < 0:
    OUT1 = 1 / 0
state['n'] = state.get('n', 0) + 1
OUT1 = float(state['n'])
"""
    block = bloco(code, redis_client, pool)
    bom = {"IN1": PortSample(1.0, True)}

    assert await block.step(bom) == {"OUT1": PortSample(1.0, True)}
    block.reset()

    assert await block.step({"IN1": PortSample(-1.0, True)}) == {"OUT1": PortSample(None, False)}
    assert await block.step(bom) == {"OUT1": PortSample(1.0, True)}
