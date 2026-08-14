"""Congelamento de MV dentro do worker do MPC (ADR-028) — processo REAL, do-mpc real.

O que se prova aqui é a promessa central do ADR-028 no lado da matemática: uma MV
classificada como indisponível **não é movida pelo solve** e, ainda assim, **continua no
modelo** com o valor real medido, para a predição das CVs seguir contando com o efeito dela.
Nada disso mexe na montagem do problema (`mpc/builder.py`) nem no solver (IPOPT, ADR-004): o
congelamento é só o `_tvp` `dumax_<mv>` zerado no horizonte, que o builder já parametriza.

Fixtures de processo (`_spawn`/`_shutdown`/`_recv`) vêm de
`test_mpc_worker.py` — os dois arquivos falam com o MESMO worker e não podem divergir sobre
como subi-lo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from multiprocessing.connection import Connection
from multiprocessing.context import SpawnProcess

import pytest
from test_mpc_worker import TS_FLOW, _cv, _mv, _par, _recv, _shutdown, _spawn, _wait_ready

from ottima_core.flowgraph import MpcConfig
from ottima_flow_runtime.mpc.worker import SolveRequest, SolveResult

LIMITES = (0.0, 1000.0)
DU_MAX = 5.0  # EU/ciclo
MAX_RATE = DU_MAX / 2.0  # EU/s (Ts_mpc=2 s, mesma régua de test_mpc_worker)


def _config_2x1() -> MpcConfig:
    """2 MVs -> 1 CV, ganhos iguais: sem congelamento o solve move as DUAS para levar a CV
    ao SP. É o que torna o teste discriminante — MV parada só pode ser efeito do freeze."""
    return MpcConfig.model_validate(
        {
            "name": "worker_2x1",
            "multiplier": 2,
            "variables": {
                "mvs": [
                    _mv("mv_1", limits=LIMITES, max_rate=MAX_RATE),
                    _mv("mv_2", limits=LIMITES, max_rate=MAX_RATE),
                ],
                "cvs": [_cv("cv_1")],
                "constraints": [],
                "dvs": [],
            },
            "models": {
                "cv_1": {"mv_1": _par(2.0, 5.0, 2.0, 0.0), "mv_2": _par(2.0, 5.0, 2.0, 0.0)}
            },
        }
    )


def _pedido(
    *,
    u_applied: dict[str, float],
    frozen: frozenset[str] = frozenset(),
    sp: float = 400.0,
    reinit: bool = True,
) -> SolveRequest:
    """SP bem acima da CV medida: o solve QUER subir as duas MVs no teto de taxa inteiro."""
    return SolveRequest(
        y={"cv_1": 0.0},
        u_applied=u_applied,
        d={},
        sp={"cv_1": sp},
        reinit=reinit,
        frozen_mvs=frozen,
    )


@pytest.fixture
def worker_2x1() -> Iterator[Callable[[], tuple[SpawnProcess, Connection]]]:
    """Fábrica de workers reais do config 2×1 — cada um morto+esperado no teardown (sem
    órfãos). Mesma mecânica de `spawn_worker` em `test_mpc_worker.py`, com fixture própria
    para o nome não colidir com o parâmetro injetado nos testes."""
    spawned: list[tuple[SpawnProcess, Connection]] = []

    def _factory() -> tuple[SpawnProcess, Connection]:
        proc, conn = _spawn(_config_2x1(), TS_FLOW)
        spawned.append((proc, conn))
        return proc, conn

    yield _factory

    for proc, conn in spawned:
        _shutdown(proc, conn)


def _solve(
    worker_2x1: Callable[[], tuple[SpawnProcess, Connection]], request: SolveRequest
) -> SolveResult:
    _proc, conn = worker_2x1()
    _wait_ready(conn)
    conn.send(request)
    result = _recv(conn)
    assert isinstance(result, SolveResult)
    return result


# --------------------------------------------------------------------------------------
# Linha de base: sem congelamento, as duas MVs se movem
# --------------------------------------------------------------------------------------


def test_sem_congelamento_as_duas_mvs_se_movem(worker_2x1) -> None:
    result = _solve(worker_2x1, _pedido(u_applied={"mv_1": 10.0, "mv_2": 20.0}))
    assert result.status == "ok"
    assert result.u_plan["mv_1"] > 10.0
    assert result.u_plan["mv_2"] > 20.0


# --------------------------------------------------------------------------------------
# Congelamento (ADR-028)
# --------------------------------------------------------------------------------------


def test_mv_congelada_permanece_no_valor_medido(worker_2x1) -> None:
    """Aceite (b) do ADR-028: a MV excluída não recebe movimento nenhum do solve, mesmo com
    o SP pedindo o contrário."""
    result = _solve(
        worker_2x1,
        _pedido(u_applied={"mv_1": 10.0, "mv_2": 20.0}, frozen=frozenset({"mv_2"})),
    )
    assert result.status == "ok"
    assert result.u_plan["mv_2"] == pytest.approx(20.0, abs=1e-6)


def test_mv_saudavel_segue_se_movendo_com_a_outra_congelada(worker_2x1) -> None:
    """Aceite (c): reclassificar uma MV não interrompe as demais — o controlador degrada,
    não para."""
    result = _solve(
        worker_2x1,
        _pedido(u_applied={"mv_1": 10.0, "mv_2": 20.0}, frozen=frozenset({"mv_2"})),
    )
    assert result.u_plan["mv_1"] == pytest.approx(10.0 + DU_MAX, abs=1e-3)


def test_predicao_da_mv_congelada_e_plana_no_valor_medido(worker_2x1) -> None:
    """A MV congelada continua NO modelo (é isso que a faz valer como distúrbio medido para
    a predição das CVs) — só que constante no horizonte inteiro."""
    result = _solve(
        worker_2x1,
        _pedido(u_applied={"mv_1": 10.0, "mv_2": 20.0}, frozen=frozenset({"mv_2"})),
    )
    trilha_mv_2 = result.prediction_mv[1]
    assert trilha_mv_2 == pytest.approx([20.0] * len(trilha_mv_2), abs=1e-6)


def test_congelar_todas_as_mvs_ainda_resolve(worker_2x1) -> None:
    """Modo degradado extremo: nenhuma MV disponível não pode virar solve infactível — o
    controlador tem de continuar publicando estado e predição honestos (quem decide o shed
    do bloco é o supervisor, não o solver)."""
    result = _solve(
        worker_2x1,
        _pedido(u_applied={"mv_1": 10.0, "mv_2": 20.0}, frozen=frozenset({"mv_1", "mv_2"})),
    )
    assert result.status == "ok"
    assert result.u_plan["mv_1"] == pytest.approx(10.0, abs=1e-6)
    assert result.u_plan["mv_2"] == pytest.approx(20.0, abs=1e-6)


def test_mv_congelada_fora_dos_limites_e_clampada_e_nao_quebra_o_solve(worker_2x1) -> None:
    """Posição real fora do curso configurado (limite mudou na engenharia, ou o atuador
    reporta além da faixa): congelar no valor cru tornaria `u == uprev` incompatível com
    `mpc.bounds` e o solve sairia infactível. O worker clampa a MV congelada nos limites —
    a alternativa seria derrubar o controlador inteiro por causa de uma MV que nem está
    sendo comandada."""
    result = _solve(
        worker_2x1,
        _pedido(u_applied={"mv_1": 10.0, "mv_2": 1500.0}, frozen=frozenset({"mv_2"})),
    )
    assert result.status == "ok"
    assert result.u_plan["mv_2"] == pytest.approx(LIMITES[1], abs=1e-6)


def test_congelamento_vale_tambem_sem_reinit(worker_2x1) -> None:
    """O caminho de regime (sem `reinit`) passa pela propagação em malha aberta + bias; o
    freeze tem de valer lá também, não só no re-arme."""
    _proc, conn = worker_2x1()
    _wait_ready(conn)
    conn.send(_pedido(u_applied={"mv_1": 10.0, "mv_2": 20.0}))
    _recv(conn)
    conn.send(
        _pedido(
            u_applied={"mv_1": 12.0, "mv_2": 20.0},
            frozen=frozenset({"mv_2"}),
            reinit=False,
        )
    )
    result = _recv(conn)
    assert isinstance(result, SolveResult)
    assert result.status == "ok"
    assert result.u_plan["mv_2"] == pytest.approx(20.0, abs=1e-6)
