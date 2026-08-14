"""Bloco MPC: publicação do registro do SSTO e alarme de inviabilidade (ADR-027 §10/§11).

O bloco não roda LP nenhum — o SSTO mora no worker. Aqui só se prova o transporte: o
registro que chegou no `SolveResult` sobe UMA vez, no quadro em que o resultado foi
aplicado, e o fracasso da camada econômica vira evento operacional (nunca falha silenciosa).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from ottima_core.bus import KIND_SSTO_INFEASIBLE, MpcState, OpcWrite, SstoRun
from ottima_core.flowgraph import MpcConfig
from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.mpc import MpcBlock
from ottima_flow_runtime.mpc.worker import SolveRequest, SolveResult

TS_FLOW = 1.0
FLOW_ID = 3
OPERADOR = "op1"
BASE_TS = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _config() -> MpcConfig:
    return MpcConfig.model_validate(
        {
            "name": "mpc",
            "multiplier": 1,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_a",
                        "name": "mv",
                        "eu": "%",
                        "limits": {"min": 0.0, "max": 100.0},
                        "max_rate": 10.0,
                    }
                ],
                "cvs": [
                    {
                        "id": "cv_a",
                        "name": "cv",
                        "eu": "y",
                        "kind": "selfreg",
                        "tss": 10.0,
                        "weight": 1.0,
                        "sp_limits": {"min": 0.0, "max": 100.0},
                    }
                ],
                "constraints": [],
                "dvs": [],
            },
            "models": {
                "cv_a": {
                    "mv_a": {
                        "enabled": True,
                        "params": {"K": 1.0, "tau1": 5.0, "tau2": 0.0, "theta": 0.0},
                    }
                }
            },
            "economics": {"enabled": True, "costs": {"mv_a": -1.0}},
        }
    )


def _run(status: str = "optimal", given_up: list[str] | None = None) -> SstoRun:
    return SstoRun(
        run_id="7f3c1a9e-0000-4000-8000-000000000001",
        config_hash="a" * 64,
        model_hash="b" * 64,
        status=status,
        solver="highs",
        solve_ms=0.5,
        objective=-1.0,
        mv={"mv_a": 10.0},
        cv_ss={"cv_a": 10.0},
        bias={"cv_a": 0.0},
        dv={},
        costs={"mv_a": -1.0},
        delta_mv={"mv_a": 5.0},
        mv_target={"mv_a": 15.0},
        cv_target={"cv_a": 15.0},
        given_up=given_up or [],
        active_constraints=[],
        duals={},
    )


def _resultado(*, ssto: SstoRun | None) -> SolveResult:
    return SolveResult(
        u_plan={"mv_a": 15.0},
        prediction_t=[0.0],
        prediction_cv=[[10.0]],
        prediction_mv=[[10.0]],
        cost=0.1,
        status="ok",
        wall_ms=1.0,
        ssto=ssto,
    )


@dataclass
class FakeHost:
    ready: bool = True
    accept: bool = True
    pending: SolveResult | None = None
    requests: list[SolveRequest] = field(default_factory=list)
    respawns: int = 0

    def dispatch(self, request: SolveRequest) -> bool:
        self.requests.append(request)
        return self.accept

    def poll(self) -> SolveResult | None:
        result, self.pending = self.pending, None
        return result

    def stats(self) -> dict:
        return {"alive": True, "respawns": self.respawns, "last_solve_ms": 1.0}


class FakeSnapshot:
    def get(self, tag_id: int):  # pragma: no cover - MV direta, sem readback
        return None


class Publishes:
    def __init__(self) -> None:
        self.states: list[MpcState] = []

    async def __call__(self, state: MpcState) -> None:
        self.states.append(state)


class Writes:
    async def __call__(self, write: OpcWrite) -> None:  # pragma: no cover - MV direta
        pass


class Events:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, **kwargs: object) -> None:
        self.events.append(kwargs)

    def of_kind(self, kind: str) -> list[dict]:
        return [e for e in self.events if e["kind"] == kind]


class Clock:
    def __init__(self) -> None:
        self._next = BASE_TS

    def __call__(self) -> datetime:
        ts, self._next = self._next, self._next + timedelta(seconds=TS_FLOW)
        return ts


@pytest.fixture
def bloco() -> tuple[MpcBlock, FakeHost, Publishes, Events]:
    host = FakeHost()
    publish = Publishes()
    events = Events()
    block = MpcBlock(
        "m1",
        config=_config(),
        ts_flow=TS_FLOW,
        snapshot=FakeSnapshot(),
        host=host,
        flow_id=FLOW_ID,
        publish=publish,
        write_opc=Writes(),
        emit_event=events,
        now=Clock(),
    )
    return block, host, publish, events


async def _remoto_auto(block: MpcBlock) -> None:
    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    await block.command("mpc_mode", {"axis": "man_auto", "value": "auto"}, OPERADOR)


def _entradas(v: float) -> dict[str, PortSample]:
    return {"cv_a": PortSample(v, True)}


async def test_registro_do_ssto_sobe_no_quadro_em_que_o_resultado_foi_aplicado(bloco):
    block, host, publish, _ = bloco
    await _remoto_auto(block)
    await block.step(_entradas(10.0))
    host.pending = _resultado(ssto=_run())

    await block.step(_entradas(10.0))

    assert publish.states[-1].ssto is not None
    assert publish.states[-1].ssto.run_id == "7f3c1a9e-0000-4000-8000-000000000001"


async def test_registro_nao_se_repete_no_quadro_seguinte(bloco):
    """Uma execução do SSTO, um registro: republicá-lo duplicaria linha na auditoria."""
    block, host, publish, _ = bloco
    await _remoto_auto(block)
    await block.step(_entradas(10.0))
    host.pending = _resultado(ssto=_run())
    await block.step(_entradas(10.0))

    await block.step(_entradas(10.0))

    assert publish.states[-1].ssto is None


async def test_resultado_sem_ssto_publica_quadro_sem_registro(bloco):
    block, host, publish, _ = bloco
    await _remoto_auto(block)
    await block.step(_entradas(10.0))
    host.pending = _resultado(ssto=None)

    await block.step(_entradas(10.0))

    assert publish.states[-1].ssto is None


async def test_ssto_inviavel_gera_evento_de_alarme(bloco):
    block, host, _, events = bloco
    await _remoto_auto(block)
    await block.step(_entradas(10.0))
    host.pending = _resultado(ssto=_run(status="infeasible"))

    await block.step(_entradas(10.0))

    emitidos = events.of_kind(KIND_SSTO_INFEASIBLE)
    assert len(emitidos) == 1
    assert emitidos[0]["severity"] == "warning"


async def test_evento_de_inviabilidade_e_deduplicado(bloco):
    """Inviabilidade persiste por muitos ciclos: um evento por episódio, não por varredura
    (mesmo padrão de `mpc_overrun`/`write_suppressed`)."""
    block, host, _, events = bloco
    await _remoto_auto(block)
    await block.step(_entradas(10.0))
    for _ in range(3):
        host.pending = _resultado(ssto=_run(status="infeasible"))
        await block.step(_entradas(10.0))

    assert len(events.of_kind(KIND_SSTO_INFEASIBLE)) == 1


async def test_ssto_que_volta_a_fechar_rearma_o_evento(bloco):
    block, host, _, events = bloco
    await _remoto_auto(block)
    await block.step(_entradas(10.0))
    host.pending = _resultado(ssto=_run(status="infeasible"))
    await block.step(_entradas(10.0))
    host.pending = _resultado(ssto=_run(status="optimal"))
    await block.step(_entradas(10.0))
    host.pending = _resultado(ssto=_run(status="infeasible"))

    await block.step(_entradas(10.0))

    assert len(events.of_kind(KIND_SSTO_INFEASIBLE)) == 2


async def test_relaxamento_nao_gera_evento(bloco):
    """Desistir de uma linha de baixa prioridade é operação normal do SSTO — fica na
    auditoria (`given_up`), não vira alarme por varredura."""
    block, host, _, events = bloco
    await _remoto_auto(block)
    await block.step(_entradas(10.0))
    host.pending = _resultado(ssto=_run(status="relaxed", given_up=["co_x"]))

    await block.step(_entradas(10.0))

    assert events.of_kind(KIND_SSTO_INFEASIBLE) == []
