"""Contratos de `mpc.worker` — processo filho do MPC (spec F4 §3.3/§3.6/§4.9/§5.1; TDD
estrito, processo REAL via `multiprocessing` spawn, ADR-004).

Lista da brief da tarefa 1.1: `ready` chega com a dimensão correta; round-trip solve com
`status="ok"`, `u_plan` dentro dos limites e predição com formatos coerentes; `reinit=True`
faz a primeira MV ficar a <= `du_max` do `u_applied` (bumpless); exceção provocada devolve
`status="error"` e o worker responde a um SEGUNDO pedido (não morreu).

Modelo 1x1 SOPDT pequeno (Np=5, `multiplier=2`, `ts_flow=1.0` -> `Ts_mpc=2.0`) para a suíte
ficar rápida mesmo gastando um processo `spawn` real por teste.
"""

from __future__ import annotations

import multiprocessing as mp
from collections.abc import Callable, Iterator
from multiprocessing.connection import Connection
from multiprocessing.context import SpawnProcess

import pytest

from ottima_core.flowgraph import MpcConfig, mpc_state_dimension
from ottima_flow_runtime.mpc.worker import SolveRequest, SolveResult, worker_main

TS_FLOW = 1.0
MULTIPLIER = 2
TS_MPC = MULTIPLIER * TS_FLOW  # 2.0
TSS = 10.0
N_P = 5  # ceil(TSS / TS_MPC)

_BOOT_TIMEOUT_S = 30.0
"""Partida de um worker `spawn` com casadi/do-mpc: sub-segundos na prática; rede de
segurança generosa (mesma constante de `script_pool._BOOT_TIMEOUT_S`)."""
_RECV_TIMEOUT_S = 10.0
_JOIN_TIMEOUT_S = 2.0

# --------------------------------------------------------------------------------------
# Fixtures — mesmo idioma de test_mpc_bumpless.py/test_mpc_builder.py
# --------------------------------------------------------------------------------------


def _mv(
    id_: str,
    *,
    limits: tuple[float, float] = (0.0, 1000.0),
    max_rate: float = 2.5,
    du_min: float = 0.0,
) -> dict:
    return {
        "id": id_,
        "name": id_,
        "eu": "u",
        "limits": {"min": limits[0], "max": limits[1]},
        # span = largura de `limits`: reproduz a normalização de custo anterior (os
        # testes de du_min têm constantes derivadas dela).
        "span": limits[1] - limits[0],
        "max_rate": max_rate,  # 2.5 EU/s x Ts_mpc=2 s = 5 EU/ciclo
        "du_min": du_min,
        "initial_value": 0.0,
        "pid": None,
    }


def _cv(id_: str, *, sp_limits: tuple[float, float] = (0.0, 2000.0), tss: float = TSS) -> dict:
    return {
        "id": id_,
        "name": id_,
        "eu": "y",
        "kind": "selfreg",
        "tss": tss,
        "weight": 1.0,
        # span = largura de `sp_limits`: idem MV — normalização de custo anterior.
        "span": sp_limits[1] - sp_limits[0],
        "sp_limits": {"min": sp_limits[0], "max": sp_limits[1]},
    }


def _par(K: float, tau1: float, tau2: float, theta: float) -> dict:
    """Par SOPDT bem acima do limiar `Ts/10` — nunca degenera (mesma nota de
    test_mpc_builder.py/test_mpc_bumpless.py)."""
    return {"enabled": True, "params": {"K": K, "tau1": tau1, "tau2": tau2, "theta": theta}}


def _config(
    *, max_rate: float = 2.5, limits: tuple[float, float] = (0.0, 1000.0), du_min: float = 0.0
) -> MpcConfig:
    return MpcConfig.model_validate(
        {
            "name": "worker_1x1",
            "multiplier": MULTIPLIER,
            "variables": {
                "mvs": [_mv("mv_1", limits=limits, max_rate=max_rate, du_min=du_min)],
                "cvs": [_cv("cv_1")],
                "constraints": [],
                "dvs": [],
            },
            # K=1.0 %/% (RF-602 revisado): com span_cv=2000 e span_mv=1000, o ganho
            # efetivo segue 2.0 EU/EU — idêntico ao K cru de antes do zero/span, então as
            # constantes dos testes de du_min continuam bit a bit.
            "models": {"cv_1": {"mv_1": _par(1.0, 5.0, 2.0, 0.0)}},
        }
    )


def _spawn(config: MpcConfig, ts_flow: float) -> tuple[SpawnProcess, Connection]:
    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=True)
    proc = ctx.Process(
        target=worker_main, args=(child_conn, config.model_dump_json(), ts_flow), daemon=True
    )
    proc.start()
    # A ponta do filho tem de ser fechada aqui: enquanto o pai a mantiver aberta, a morte do
    # worker nunca vira EOF neste lado (mesma nota de `script_pool._spawn_worker`).
    child_conn.close()
    return proc, parent_conn


def _shutdown(proc: SpawnProcess, conn: Connection) -> None:
    """Mata + junta — sem processo órfão ao fim do teste (mesmo padrão de
    `script_pool._shutdown`)."""
    try:
        conn.close()
    except OSError:
        pass
    if proc.is_alive():
        proc.kill()
    proc.join(_JOIN_TIMEOUT_S)
    assert not proc.is_alive(), "processo do worker sobreviveu ao kill+join"


def _recv(conn: Connection, *, timeout_s: float = _RECV_TIMEOUT_S) -> object:
    assert conn.poll(timeout_s), "worker não respondeu dentro do timeout"
    return conn.recv()


@pytest.fixture
def spawn_worker() -> Iterator[Callable[[MpcConfig], tuple[SpawnProcess, Connection]]]:
    """Fábrica de workers reais — cada um é morto+esperado no teardown (sem órfãos)."""
    spawned: list[tuple[SpawnProcess, Connection]] = []

    def _factory(config: MpcConfig) -> tuple[SpawnProcess, Connection]:
        proc, conn = _spawn(config, TS_FLOW)
        spawned.append((proc, conn))
        return proc, conn

    yield _factory

    for proc, conn in spawned:
        _shutdown(proc, conn)


def _wait_ready(conn: Connection) -> int:
    kind, dimension = _recv(conn, timeout_s=_BOOT_TIMEOUT_S)
    assert kind == "ready"
    return dimension


# --------------------------------------------------------------------------------------
# `ready` chega com a dimensão correta
# --------------------------------------------------------------------------------------


def test_ready_chega_com_a_dimensao_correta(
    spawn_worker: Callable[[MpcConfig], tuple[SpawnProcess, Connection]],
) -> None:
    config = _config()
    proc, conn = spawn_worker(config)

    dimension = _wait_ready(conn)

    assert dimension == mpc_state_dimension(config, ts_mpc=TS_MPC)
    assert proc.is_alive()


# --------------------------------------------------------------------------------------
# Round-trip: status ok, u_plan dentro dos limites, predição com formatos coerentes
# --------------------------------------------------------------------------------------


def test_round_trip_solve_status_ok_e_predicao_coerente(
    spawn_worker: Callable[[MpcConfig], tuple[SpawnProcess, Connection]],
) -> None:
    limits = (0.0, 1000.0)
    config = _config(limits=limits)
    proc, conn = spawn_worker(config)
    _wait_ready(conn)

    request = SolveRequest(
        y={"cv_1": 60.0}, u_applied={"mv_1": 30.0}, d={}, sp={"cv_1": 60.0}, reinit=True
    )
    conn.send(request)
    result = _recv(conn)

    assert isinstance(result, SolveResult)
    assert result.status == "ok"
    assert result.detail == ""
    assert limits[0] - 1e-6 <= result.u_plan["mv_1"] <= limits[1] + 1e-6

    assert len(result.prediction_t) == N_P + 1
    assert result.prediction_t[0] == pytest.approx(0.0)
    assert result.prediction_t[1] == pytest.approx(TS_MPC)
    assert result.prediction_t[-1] == pytest.approx(N_P * TS_MPC)

    assert len(result.prediction_cv) == 1  # 1 CV, sem Restrição
    assert len(result.prediction_cv[0]) == N_P + 1

    assert len(result.prediction_mv) == 1  # 1 MV
    assert len(result.prediction_mv[0]) == N_P + 1

    assert result.wall_ms >= 0.0
    assert proc.is_alive()


# --------------------------------------------------------------------------------------
# reinit=True -> primeira MV dista <= du_max do u_applied (bumpless, spec §3.6)
# --------------------------------------------------------------------------------------


def test_reinit_bumpless_primeira_mv_perto_do_u_aplicado(
    spawn_worker: Callable[[MpcConfig], tuple[SpawnProcess, Connection]],
) -> None:
    du_max = 5.0  # EU/ciclo (max_rate 2.5 x Ts_mpc=2)
    config = _config()
    proc, conn = spawn_worker(config)
    _wait_ready(conn)

    u_vigente = 30.0
    request = SolveRequest(
        y={"cv_1": 60.0}, u_applied={"mv_1": u_vigente}, d={}, sp={"cv_1": 60.0}, reinit=True
    )
    conn.send(request)
    result = _recv(conn)

    assert result.status == "ok"
    assert abs(result.u_plan["mv_1"] - u_vigente) <= du_max + 1e-4


# --------------------------------------------------------------------------------------
# Exceção provocada -> status="error" e o worker responde a um SEGUNDO pedido (não morreu)
# --------------------------------------------------------------------------------------


def test_excecao_provocada_status_error_e_worker_segue_vivo(
    spawn_worker: Callable[[MpcConfig], tuple[SpawnProcess, Connection]],
) -> None:
    config = _config()
    proc, conn = spawn_worker(config)
    _wait_ready(conn)

    # `u_applied` sem a MV declarada -- KeyError dentro do worker antes/durante o solve.
    bad_request = SolveRequest(y={"cv_1": 60.0}, u_applied={}, d={}, sp={"cv_1": 60.0}, reinit=True)
    conn.send(bad_request)
    bad_result = _recv(conn)

    assert isinstance(bad_result, SolveResult)
    assert bad_result.status == "error"
    assert bad_result.detail != ""
    assert proc.is_alive()

    good_request = SolveRequest(
        y={"cv_1": 60.0}, u_applied={"mv_1": 30.0}, d={}, sp={"cv_1": 60.0}, reinit=True
    )
    conn.send(good_request)
    good_result = _recv(conn)

    assert good_result.status == "ok"
    assert proc.is_alive()


# --------------------------------------------------------------------------------------
# du_min (TD-007) — banda morta descarta movimento fantasma e não deriva entre solves
# --------------------------------------------------------------------------------------


def test_du_min_descarta_movimento_fantasma_e_nao_deriva_entre_solves(
    spawn_worker: Callable[[MpcConfig], tuple[SpawnProcess, Connection]],
) -> None:
    """Δu natural (sem banda morta) para este SP é ~0.43 (abaixo de `du_min=0.5`): o
    primeiro solve tem que devolver `u0 == u_prev` (movimento fantasma descartado). O
    SEGUNDO solve, com o MESMO `u_applied`/`y` (a válvula de fato não se moveu), tem que
    partir do MESMO `u_prev` — nada de drift acumulado no registrador interno entre
    execuções sucessivas."""
    du_min = 0.5
    u_vigente = 30.0
    config = _config(du_min=du_min)
    proc, conn = spawn_worker(config)
    _wait_ready(conn)

    primeiro = SolveRequest(
        y={"cv_1": 60.0}, u_applied={"mv_1": u_vigente}, d={}, sp={"cv_1": 60.5}, reinit=True
    )
    conn.send(primeiro)
    resultado_1 = _recv(conn)
    assert resultado_1.status == "ok"
    assert resultado_1.u_plan["mv_1"] == pytest.approx(u_vigente, abs=1e-6)
    assert resultado_1.prediction_mv[0][1] == pytest.approx(u_vigente, abs=1e-6)

    segundo = SolveRequest(
        y={"cv_1": 60.0}, u_applied={"mv_1": u_vigente}, d={}, sp={"cv_1": 60.5}, reinit=False
    )
    conn.send(segundo)
    resultado_2 = _recv(conn)
    assert resultado_2.status == "ok"
    assert resultado_2.u_plan["mv_1"] == pytest.approx(u_vigente, abs=1e-6)

    assert proc.is_alive()


# --------------------------------------------------------------------------------------
# Guard de não-regressão — du_min=0/move_weight=1 (defaults) reproduzem o resultado atual
# --------------------------------------------------------------------------------------


def test_du_min_zero_reproduz_o_resultado_atual_sem_quantizar(
    spawn_worker: Callable[[MpcConfig], tuple[SpawnProcess, Connection]],
) -> None:
    """Guard de não-regressão (TD-007): `du_min=0.0`/`move_weight=1.0` são os defaults de
    `MvVar` — sem quantização nenhuma, o resultado bate byte-a-byte com o valor fixado
    ANTES desta tarefa (capturado do build sem banda morta nem ponderação de movimento)."""
    config = _config()  # du_min=0.0 (default) -> _aplicar_banda_morta nunca quantiza
    proc, conn = spawn_worker(config)
    _wait_ready(conn)

    request = SolveRequest(
        y={"cv_1": 60.0}, u_applied={"mv_1": 30.0}, d={}, sp={"cv_1": 60.5}, reinit=True
    )
    conn.send(request)
    resultado = _recv(conn)

    assert resultado.status == "ok"
    assert resultado.u_plan["mv_1"] == pytest.approx(30.43001689428463, abs=1e-6)
    assert proc.is_alive()
