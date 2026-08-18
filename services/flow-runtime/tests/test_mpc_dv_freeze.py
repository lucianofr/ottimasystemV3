"""Congelamento interno de DV com qualidade ruim (ADR-038): a DV BAD NÃO invalida o bloco.

Regra nova (pedido direto do operador): DV com amostra ruim congela internamente — o MPC
segue resolvendo com o último valor bom da DV (feedforward parado não impacta o algoritmo).
Não é `fail_action` configurável: é a ação default fixa, sem campo novo em `DvVar`.

Espelha os duplos de `test_mpc_block.py` (host/snapshot falsos, callbacks coletores) para
determinismo em processo, sem Redis nem worker real.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from ottima_core.bus import KIND_MPC_INPUT_INVALID, MpcState, OpcWrite
from ottima_core.flowgraph import MpcConfig
from ottima_core.snapshot import TagValue
from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.mpc import MpcBlock
from ottima_flow_runtime.mpc.worker import SolveRequest, SolveResult

TS_FLOW = 1.0
OPERADOR = "user:7"
FLOW_ID = 1


def _config() -> MpcConfig:
    """1 MV direta (sempre RCAS_OK), 1 CV self-reg e 1 DV — cenário mínimo do defeito."""
    return MpcConfig.model_validate(
        {
            "name": "bloco_dv",
            "multiplier": 1,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_1",
                        "name": "MV direta",
                        "eu": "%",
                        "limits": {"min": 0.0, "max": 100.0},
                        "max_rate": 5.0,
                        "initial_value": 0.0,
                    }
                ],
                "cvs": [
                    {
                        "id": "cv_a",
                        "name": "CV a",
                        "eu": "C",
                        "kind": "selfreg",
                        "tss": 30.0,
                        "weight": 1.0,
                        "sp_limits": {"min": 0.0, "max": 200.0},
                    }
                ],
                "constraints": [],
                "dvs": [
                    {"id": "dv_1", "name": "Vazão de carga", "eu": "m3/h"},
                ],
            },
            "models": {
                "cv_a": {
                    "mv_1": {
                        "enabled": True,
                        "params": {"K": 1.0, "tau1": 10.0, "tau2": 0.0, "theta": 0.0},
                    },
                    "dv_1": {
                        "enabled": True,
                        "params": {"K": 0.5, "tau1": 5.0, "tau2": 0.0, "theta": 0.0},
                    },
                }
            },
        }
    )


# --------------------------------------------------------------------------------------
# Duplos: host/snapshot falsos + coletores dos 3 callbacks injetados (mesmo padrão de
# test_mpc_block.py)
# --------------------------------------------------------------------------------------


@dataclass
class FakeHost:
    ready: bool = True
    accept: bool = True
    pending: SolveResult | None = None
    requests: list[SolveRequest] = field(default_factory=list)
    last_solve_ms: float | None = None
    respawns: int = 0

    def dispatch(self, request: SolveRequest) -> bool:
        self.requests.append(request)
        return self.accept

    def poll(self) -> SolveResult | None:
        result, self.pending = self.pending, None
        return result

    def stats(self) -> dict:
        return {"alive": True, "respawns": self.respawns, "last_solve_ms": self.last_solve_ms}


class FakeSnapshot:
    def __init__(self) -> None:
        self._values: dict[int, TagValue] = {}

    def set(self, tag_id: int, value: float, *, quality: int = 0) -> None:
        self._values[tag_id] = TagValue(value=value, quality=quality, ts=datetime.now(UTC))

    def get(self, tag_id: int) -> TagValue | None:
        return self._values.get(tag_id)


class Publishes:
    def __init__(self) -> None:
        self.states: list[MpcState] = []

    async def __call__(self, state: MpcState) -> None:
        self.states.append(state)


class Writes:
    def __init__(self) -> None:
        self.writes: list[OpcWrite] = []

    async def __call__(self, write: OpcWrite) -> None:
        self.writes.append(write)


class Events:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, **kwargs: object) -> None:
        self.events.append(kwargs)

    def of_kind(self, kind: str) -> list[dict]:
        return [e for e in self.events if e["kind"] == kind]


def _block(
    now: Callable[[], datetime] | None = None,
) -> tuple[MpcBlock, FakeHost, Publishes, Events]:
    host = FakeHost()
    publish = Publishes()
    write_opc = Writes()
    emit_event = Events()
    block = MpcBlock(
        "m1",
        config=_config(),
        ts_flow=TS_FLOW,
        snapshot=FakeSnapshot(),
        host=host,
        flow_id=FLOW_ID,
        publish=publish,
        write_opc=write_opc,
        emit_event=emit_event,
        now=now,
    )
    return block, host, publish, emit_event


def entradas(
    cv_a: float, *, dv: float | None = 7.0, dv_ok: bool = True
) -> dict[str, PortSample]:
    return {"cv_a": PortSample(cv_a, True), "dv_1": PortSample(dv, dv_ok)}


async def _entra_remoto_auto(block: MpcBlock) -> None:
    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    await block.command("mpc_mode", {"axis": "man_auto", "value": "auto"}, OPERADOR)


# --------------------------------------------------------------------------------------
# Congelamento interno da DV (ADR-038)
# --------------------------------------------------------------------------------------


async def test_dv_bad_nao_invalida_o_bloco_e_solve_usa_o_ultimo_valor_bom() -> None:
    """DV BAD: `input_valid` segue true, o solve continua (MV NÃO congela por causa da DV) e
    o `d` despachado ao worker é o último valor bom da DV."""
    block, host, publish, _ = _block()
    await _entra_remoto_auto(block)
    await block.step(entradas(20.0, dv=7.0))
    await block.step(entradas(20.0, dv=9.0))
    assert host.requests[-1].d["dv_1"] == pytest.approx(9.0)

    antes = len(host.requests)
    saida = await block.step(entradas(20.0, dv=0.0, dv_ok=False))

    assert saida["mv_1"].ok is True, "DV ruim não pode invalidar as portas do bloco"
    assert publish.states[-1].status.input_valid is True, "DV ruim não pode invalidar o bloco"
    assert len(host.requests) == antes + 1, "solve precisa continuar rodando com DV ruim"
    assert host.requests[-1].d["dv_1"] == pytest.approx(9.0), (
        "d enviado ao solver deve ser o último valor bom da DV (freeze interno)"
    )


async def test_dv_volta_good_e_o_valor_novo_flui_para_o_solve() -> None:
    """Recuperação: DV volta a GOOD e o valor novo volta a alimentar o `d` do solve."""
    block, host, *_ = _block()
    await _entra_remoto_auto(block)
    await block.step(entradas(20.0, dv=7.0))
    await block.step(entradas(20.0, dv=0.0, dv_ok=False))
    assert len(host.requests) == 2, "solve continua rodando com a DV ruim (congelada)"
    assert host.requests[-1].d["dv_1"] == pytest.approx(7.0), "congelada no último bom"

    await block.step(entradas(20.0, dv=11.5))
    assert host.requests[-1].d["dv_1"] == pytest.approx(11.5), "DV curada volta a fluir"


async def test_dv_bad_nao_emite_mpc_input_invalid_nem_dispara_fail_action() -> None:
    """DV BAD é dado cíclico degradado: sem evento `mpc_input_invalid` e sem fail action
    (DV nunca entra em `_avaliar_fail_actions` — não tem `fail_action` no config)."""
    block, host, publish, events = _block()
    await _entra_remoto_auto(block)
    await block.step(entradas(20.0, dv=7.0))
    await block.step(entradas(20.0, dv=0.0, dv_ok=False))
    await block.step(entradas(20.0, dv=0.0, dv_ok=False))  # 2ª fronteira ruim: debounce

    assert events.of_kind(KIND_MPC_INPUT_INVALID) == [], "DV ruim não é invalidez de entrada"
    assert publish.states[-1].status.input_valid is True
    assert block.fail_pending == {}, "DV não dispara fail action"
    assert len(host.requests) == 3, "solver seguiu rodando nas duas varreduras com DV ruim"


async def test_dv_bad_antes_da_primeira_amostra_boa_nao_derruba_o_solve() -> None:
    """Edge: DV BAD desde a primeira amostra (nunca houve valor bom). O `d` cai no default
    existente de `_last_measured` (0.0, o mesmo que `_build_state` reporta) — sem KeyError,
    sem invalidez."""
    block, host, publish, _ = _block()
    await _entra_remoto_auto(block)
    saida = await block.step(entradas(20.0, dv=5.0, dv_ok=False))

    assert saida["mv_1"].ok is True
    assert publish.states[-1].status.input_valid is True
    assert host.requests[-1].d["dv_1"] == pytest.approx(0.0), (
        "DV nunca medida: default 0.0 (comportamento existente de _last_measured)"
    )


async def test_dv_que_nunca_chegou_continua_sendo_cold_input() -> None:
    """Edge: DV com `v=None` (porta ainda sem valor) segue o gate universal de cold start —
    saídas nulas, nenhum solve, nada mais avaliado nessa varredura."""
    block, host, *_ = _block()
    await _entra_remoto_auto(block)
    saida = await block.step({"cv_a": PortSample(20.0, True), "dv_1": PortSample(None, False)})

    assert saida["mv_1"] == PortSample(None, False), "varredura fria sai nula"
    assert host.requests == [], "cold start não dispara solve"
