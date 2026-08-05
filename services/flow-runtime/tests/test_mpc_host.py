"""Contratos de `mpc.host` — `MpcHost`, dono do processo do worker MPC no lado do runtime
(spec F4 §4.2/§4.9; TDD estrito, `worker_target` injetável para determinismo, ADR-004).

Lista da brief da tarefa 1.2: worker lento injetado -> kill no deadline (0.7xTs_mpc),
`stats()["respawns"]` incrementa, `poll()` entrega o resultado sintético de overrun;
dispatch durante rebuild -> `False`; worker morto à força -> respawn sozinho no próximo
ciclo, `alive` volta `True`; `stop()` duplo sem erro e processo encerrado. Mais um teste do
contrato de `needs_reinit` (linha 30 da brief): o primeiro dispatch pós-boot/pós-respawn
sempre força `reinit=True`, mesmo que o chamador tenha montado o `SolveRequest` com
`reinit=False`.

Workers falsos (`mpc_host_echo_worker`/`mpc_host_sleeper_worker`/
`mpc_host_reinit_capturing_worker`) substituem o worker real via `worker_target=` — nenhum
destes testes paga o custo de montar um `do_mpc.controller.MPC` de verdade (isso já está
coberto por `test_mpc_worker.py`). Vivem em `runtime_test_helpers.py`, não neste arquivo:
`spawn` precisa reimportá-los por nome qualificado num interpretador novo, e um módulo de
teste sob `--import-mode=importlib` não tem um nome pontilhado resolvível de fora do pytest
(mesma razão de `worker_main` viver em `ottima_flow_runtime` e não dentro de
`test_mpc_worker.py`) — ver a nota no topo daquela seção do helper.

`Ts_mpc=0.3s` (`multiplier=1`, `ts_flow=0.3`) -> deadline de host = `0.7*0.3 = 0.21s`:
suficiente para não confundir jitter de agendamento de thread com estouro real, mas curto
o bastante para manter a suíte rápida.
"""

from __future__ import annotations

import os
import signal
from collections.abc import AsyncIterator, Callable

import pytest
from runtime_test_helpers import (
    mpc_host_dying_on_request_worker,
    mpc_host_echo_worker,
    mpc_host_reinit_capturing_worker,
    mpc_host_sleeper_worker,
)

from ottima_core.flowgraph import MpcConfig
from ottima_flow_runtime.mpc.host import MpcHost
from ottima_flow_runtime.mpc.worker import SolveRequest, SolveResult
from testkit.await_until import await_until

TS_FLOW = 0.3
MULTIPLIER = 1
TS_MPC = MULTIPLIER * TS_FLOW  # 0.3
DEADLINE_S = 0.7 * TS_MPC  # 0.21

_EMPTY_REQUEST = SolveRequest(y={}, u_applied={}, d={}, sp={}, reinit=False)


# --------------------------------------------------------------------------------------
# Config mínima válida (mesmo idioma de test_mpc_worker.py) — conteúdo não importa para
# nenhum destes testes, os workers falsos nunca chegam a montar um `do_mpc.controller.MPC`.
# --------------------------------------------------------------------------------------


def _config() -> MpcConfig:
    return MpcConfig.model_validate(
        {
            "name": "host_1x1",
            "multiplier": MULTIPLIER,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_1",
                        "name": "mv_1",
                        "eu": "u",
                        "limits": {"min": 0.0, "max": 1000.0},
                        "du_max": 5.0,
                        "initial_value": 0.0,
                        "pid": None,
                    }
                ],
                "cvs": [
                    {
                        "id": "cv_1",
                        "name": "cv_1",
                        "eu": "y",
                        "kind": "selfreg",
                        "tss": 10.0,
                        "weight": 1.0,
                        "sp_limits": {"min": 0.0, "max": 2000.0},
                    }
                ],
                "constraints": [],
                "dvs": [],
            },
            "models": {
                "cv_1": {
                    "mv_1": {
                        "enabled": True,
                        "params": {"K": 2.0, "tau1": 5.0, "tau2": 2.0, "theta": 0.0},
                    }
                }
            },
        }
    )


# --------------------------------------------------------------------------------------
# Fixture: hosts sempre parados no teardown, mesmo se o teste falhar no meio (sem órfão)
# --------------------------------------------------------------------------------------


@pytest.fixture
async def make_host() -> AsyncIterator[Callable[[Callable], MpcHost]]:
    hosts: list[MpcHost] = []

    def _factory(worker_target: Callable) -> MpcHost:
        host = MpcHost("m1", _config(), TS_FLOW, worker_target=worker_target)
        hosts.append(host)
        return host

    yield _factory

    for host in hosts:
        await host.stop()


async def _wait_poll(host: MpcHost, timeout_s: float = 5.0) -> SolveResult:
    """Espera o próximo `poll()` não-`None` e o devolve — consome uma vez só (contrato)."""
    box: list[SolveResult] = []

    async def _try() -> bool:
        outcome = host.poll()
        if outcome is not None:
            box.append(outcome)
            return True
        return False

    await await_until(_try, timeout_s=timeout_s)
    return box[0]


# --------------------------------------------------------------------------------------
# Antes de start(): nunca pronto, dispatch nunca aceita
# --------------------------------------------------------------------------------------


async def test_antes_de_start_nao_esta_pronto_e_dispatch_recusa(
    make_host: Callable[[Callable], MpcHost],
) -> None:
    host = make_host(mpc_host_echo_worker)
    assert host.ready is False
    assert host.dispatch(_EMPTY_REQUEST) is False


# --------------------------------------------------------------------------------------
# Deadline de 0.7xTs_mpc: kill do processo + respawn em background + overrun sintético
# --------------------------------------------------------------------------------------


async def test_kill_no_deadline_mata_processo_respawna_e_entrega_overrun_sintetico(
    make_host: Callable[[Callable], MpcHost],
) -> None:
    host = make_host(mpc_host_sleeper_worker)
    await host.start()
    assert host.ready is True
    old_pid = host._proc.pid  # noqa: SLF001 - gray-box: prova que É outro processo depois

    assert host.dispatch(_EMPTY_REQUEST) is True

    result = await _wait_poll(host, timeout_s=DEADLINE_S + 5.0)
    assert result.status == "overrun"
    assert result.u_plan == {}
    assert result.wall_ms >= DEADLINE_S * 1000.0

    await await_until(lambda: host.stats()["respawns"] == 1, timeout_s=10.0)
    await await_until(lambda: host.stats()["alive"] is True, timeout_s=10.0)
    assert host._proc.pid != old_pid  # noqa: SLF001
    assert host.stats()["last_solve_ms"] is None  # nunca chegou um solve real


# --------------------------------------------------------------------------------------
# Dispatch durante o rebuild em background (logo após o overrun acima) -> False
# --------------------------------------------------------------------------------------


async def test_dispatch_durante_rebuild_retorna_false(
    make_host: Callable[[Callable], MpcHost],
) -> None:
    host = make_host(mpc_host_sleeper_worker)
    await host.start()

    assert host.dispatch(_EMPTY_REQUEST) is True
    await _wait_poll(host, timeout_s=DEADLINE_S + 5.0)

    # O respawn foi agendado em background no instante do overrun (síncrono, dentro do
    # mesmo evento que processou o timeout) — a esta altura o rebuild ainda não terminou
    # (spawn de um processo `spawn` real leva bem mais que os poucos µs até aqui).
    assert host.ready is False
    assert host.dispatch(_EMPTY_REQUEST) is False

    await await_until(lambda: host.ready is True, timeout_s=10.0)


# --------------------------------------------------------------------------------------
# Crash espontâneo (worker morto à força) -> respawn sozinho no próximo ciclo
# --------------------------------------------------------------------------------------


async def test_crash_espontaneo_respawna_sozinho_no_proximo_ciclo(
    make_host: Callable[[Callable], MpcHost],
) -> None:
    host = make_host(mpc_host_echo_worker)
    await host.start()
    old_pid = host._proc.pid  # noqa: SLF001 - gray-box: única forma de matar "de fora"

    os.kill(old_pid, signal.SIGKILL)
    await await_until(lambda: not host._proc.is_alive(), timeout_s=5.0)  # noqa: SLF001

    # "Próximo ciclo": a chamada seguinte de dispatch() nota o processo morto, agenda o
    # respawn e devolve False nesse ciclo (spec §4.2: worker indisponível -> conta e pula).
    assert host.dispatch(_EMPTY_REQUEST) is False

    await await_until(lambda: host.stats()["alive"] is True, timeout_s=10.0)
    assert host.stats()["respawns"] == 1
    assert host._proc.pid != old_pid  # noqa: SLF001


# --------------------------------------------------------------------------------------
# Crash EM VOO (worker morre respondendo a um dispatch pendente) -> status="error"/"crash"
# --------------------------------------------------------------------------------------


async def test_crash_em_voo_durante_dispatch_entrega_error_crash_e_respawna(
    make_host: Callable[[Callable], MpcHost],
) -> None:
    host = make_host(mpc_host_dying_on_request_worker)
    await host.start()
    old_pid = host._proc.pid  # noqa: SLF001

    # Diferente do teste de crash espontâneo acima (processo morto IDLE, sem pedido em
    # voo): aqui o worker morre respondendo a ESTE dispatch — o caminho que `_receive`
    # detecta sozinho como EOF/erro de SO no meio da espera (spec §4.9), não o
    # `proc.is_alive()` do topo de `dispatch()`.
    assert host.dispatch(_EMPTY_REQUEST) is True

    result = await _wait_poll(host, timeout_s=DEADLINE_S + 5.0)
    assert result.status == "error"
    assert result.detail == "crash"

    await await_until(lambda: host.stats()["respawns"] == 1, timeout_s=10.0)
    await await_until(lambda: host.ready is True, timeout_s=10.0)
    assert host._proc.pid != old_pid  # noqa: SLF001


# --------------------------------------------------------------------------------------
# needs_reinit: primeiro dispatch pós-boot E pós-respawn força reinit=True (brief linha 30)
# --------------------------------------------------------------------------------------


async def test_primeiro_dispatch_apos_boot_e_apos_respawn_forca_reinit(
    make_host: Callable[[Callable], MpcHost],
) -> None:
    host = make_host(mpc_host_reinit_capturing_worker)
    await host.start()

    assert host.dispatch(_EMPTY_REQUEST) is True  # reinit=False pedido pelo chamador
    first = await _wait_poll(host)
    assert first.detail == "True", "primeiro dispatch pós-boot precisa forçar reinit"

    old_pid = host._proc.pid  # noqa: SLF001
    os.kill(old_pid, signal.SIGKILL)
    await await_until(lambda: not host._proc.is_alive(), timeout_s=5.0)  # noqa: SLF001
    assert host.dispatch(_EMPTY_REQUEST) is False
    await await_until(lambda: host.ready is True, timeout_s=10.0)

    assert host.dispatch(_EMPTY_REQUEST) is True  # de novo reinit=False pedido
    second = await _wait_poll(host)
    assert second.detail == "True", "primeiro dispatch pós-respawn precisa forçar reinit"


# --------------------------------------------------------------------------------------
# stop() idempotente, sem processo órfão
# --------------------------------------------------------------------------------------


async def test_stop_idempotente_sem_processo_orfao(
    make_host: Callable[[Callable], MpcHost],
) -> None:
    host = make_host(mpc_host_echo_worker)
    await host.start()
    pid = host._proc.pid  # noqa: SLF001 - gray-box: pid precisa sobreviver ao `stop()`

    await host.stop()
    await host.stop()  # idempotente: não levanta, não faz nada de novo

    # `stop()` fecha o `Process` (`proc.close()`, mesmo padrão de `script_pool._shutdown`):
    # `is_alive()` num processo fechado levanta `ValueError`, então a prova de "sem processo
    # órfão" é a mesma da spec/SO — nenhum processo vivo responde mais a esse pid.
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert host.stats()["alive"] is False
    assert host.ready is False
