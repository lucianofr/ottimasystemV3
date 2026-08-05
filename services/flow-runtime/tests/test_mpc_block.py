"""Contratos do bloco MPC — cadência, modos, aplicar-na-fronteira e write-back (spec F4
§4.2/§4.3/§4.6/§4.9/§5; plano F4b, brief da tarefa 2.1: TDD estrito, host/snapshot falsos
para determinismo — nenhum destes testes paga o custo de um `do_mpc.controller.MPC` real
nem de Redis, mesmo espírito de `worker_target=` na tarefa 1.2).

Lista da brief (tarefa 2.1): tabela de modos completa (LOCAL tracking/hold, MAN clampado,
AUTO plano) · aplicar-na-fronteira (resultado entre varreduras não muda porta até a
fronteira seguinte) · overrun mantém MV + dedupe + contador · `no_convergence` emite
`mpc_solver_error` sem kill do host · tracking segue readback / writes suprimidos em LOCAL
e sob invalidez · SP congela ao entrar em AUTO. Mais alguns testes de reforço, direto do
próprio comportamento §4.8/§4.2 descrito na brief: `command()` idempotente e
`man_auto` ignorado em LOCAL, worker indisponível conta overrun sem novo evento, cold start
produz saídas nulas (padrão F3 §3.0).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from ottima_core.bus import (
    KIND_MPC_INPUT_INVALID,
    KIND_MPC_MODE_CHANGED,
    KIND_MPC_OVERRUN,
    KIND_MPC_SOLVER_ERROR,
    KIND_MPC_SP_WRITTEN,
    MpcState,
    OpcWrite,
)
from ottima_core.flowgraph import MpcConfig
from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.mpc import MpcBlock
from ottima_flow_runtime.mpc.worker import SolveRequest, SolveResult
from ottima_flow_runtime.snapshot import TagValue

TS_FLOW = 1.0
OPERADOR = "user:7"


def _config(*, multiplier: int = 1) -> MpcConfig:
    """1 CV + 2 MVs (uma com `pid`, outra direta) — cobre a tabela de modos inteira."""
    return MpcConfig.model_validate(
        {
            "name": "bloco_teste",
            "multiplier": multiplier,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_pid",
                        "name": "MV com pid",
                        "eu": "m3/h",
                        "limits": {"min": 0.0, "max": 100.0},
                        "du_max": 5.0,
                        "initial_value": 10.0,
                        "pid": {
                            "write_tag_id": 501,
                            "target_mode": "rcas",
                            "mode_cmd_tag_id": 502,
                            "readback_tag_id": 503,
                            "mode_values": {"auto": 0, "target": 1},
                        },
                    },
                    {
                        "id": "mv_direto",
                        "name": "MV direta",
                        "eu": "%",
                        "limits": {"min": -10.0, "max": 10.0},
                        "du_max": 2.0,
                        "initial_value": 1.5,
                        "pid": None,
                    },
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
                "dvs": [],
            },
            "models": {
                "cv_a": {
                    "mv_pid": {
                        "enabled": True,
                        "params": {"K": 1.0, "tau1": 10.0, "tau2": 0.0, "theta": 0.0},
                    },
                    "mv_direto": {
                        "enabled": True,
                        "params": {"K": 1.0, "tau1": 10.0, "tau2": 0.0, "theta": 0.0},
                    },
                }
            },
        }
    )


# --------------------------------------------------------------------------------------
# Duplos: host/snapshot falsos + coletores dos 3 callbacks injetados
# --------------------------------------------------------------------------------------


@dataclass
class FakeHost:
    """Duplo de `MpcHost` — mesmo protocolo (`ready`/`dispatch`/`poll`/`stats`), sem
    processo nenhum: o teste controla exatamente quando um resultado "chega" via `pending`.
    """

    ready: bool = True
    accept: bool = True
    pending: SolveResult | None = None
    requests: list[SolveRequest] = field(default_factory=list)
    last_solve_ms: float | None = None

    def dispatch(self, request: SolveRequest) -> bool:
        self.requests.append(request)
        return self.accept

    def poll(self) -> SolveResult | None:
        result, self.pending = self.pending, None
        return result

    def stats(self) -> dict:
        return {"alive": True, "respawns": 0, "last_solve_ms": self.last_solve_ms}


class FakeSnapshot:
    """Duplo de `ValueSnapshot` — só o `.get()` síncrono que o bloco usa."""

    def __init__(self) -> None:
        self._values: dict[int, TagValue] = {}

    def set(self, tag_id: int, value: float) -> None:
        self._values[tag_id] = TagValue(value=value, quality=0, ts=datetime.now(UTC))

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
    *, multiplier: int = 1
) -> tuple[MpcBlock, FakeHost, FakeSnapshot, Publishes, Writes, Events]:
    host = FakeHost()
    snapshot = FakeSnapshot()
    publish = Publishes()
    write_opc = Writes()
    emit_event = Events()
    block = MpcBlock(
        "m1",
        config=_config(multiplier=multiplier),
        ts_flow=TS_FLOW,
        snapshot=snapshot,
        host=host,
        publish=publish,
        write_opc=write_opc,
        emit_event=emit_event,
    )
    return block, host, snapshot, publish, write_opc, emit_event


def entradas(cv_a: float | None, *, ok: bool = True) -> dict[str, PortSample]:
    return {"cv_a": PortSample(cv_a, ok)}


async def _entra_remoto_auto(block: MpcBlock) -> None:
    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    await block.command("mpc_mode", {"axis": "man_auto", "value": "auto"}, OPERADOR)


def _resultado_ok(u_plan: dict[str, float]) -> SolveResult:
    return SolveResult(
        u_plan=u_plan,
        prediction_t=[],
        prediction_cv=[],
        prediction_mv=[],
        cost=1.0,
        status="ok",
        wall_ms=5.0,
    )


# --------------------------------------------------------------------------------------
# 1. Tabela de modos completa (spec §4.3)
# --------------------------------------------------------------------------------------


async def test_local_com_pid_segue_o_readback_do_snapshot() -> None:
    block, _, snapshot, *_ = _block()
    snapshot.set(503, 42.0)
    saida = await block.step(entradas(20.0))
    assert saida["mv_pid"] == PortSample(42.0, True)


async def test_local_sem_readback_ainda_segura_o_initial_value() -> None:
    """`pid` presente mas sem nenhum readback publicado ainda: hold do `initial_value`."""
    block, *_ = _block()
    saida = await block.step(entradas(20.0))
    assert saida["mv_pid"] == PortSample(10.0, True)


async def test_local_sem_pid_segura_o_initial_value() -> None:
    block, *_ = _block()
    saida = await block.step(entradas(20.0))
    assert saida["mv_direto"] == PortSample(1.5, True)


async def test_remoto_man_e_o_valor_manual_clampado_em_limits() -> None:
    block, *_ = _block()
    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    await block.command("mpc_mv", {"var_id": "mv_direto", "value": 999.0}, OPERADOR)
    saida = await block.step(entradas(20.0))
    assert saida["mv_direto"] == PortSample(10.0, True)  # clamp em limits.max=10.0


async def test_remoto_auto_aplica_o_ultimo_plano() -> None:
    block, host, *_ = _block()
    await _entra_remoto_auto(block)
    host.pending = _resultado_ok({"mv_pid": 33.0, "mv_direto": -4.0})
    saida = await block.step(entradas(20.0))
    assert saida["mv_pid"] == PortSample(33.0, True)
    assert saida["mv_direto"] == PortSample(-4.0, True)


async def test_remoto_auto_sem_plano_ainda_segura_o_valor_vigente() -> None:
    block, *_ = _block()
    await _entra_remoto_auto(block)
    saida = await block.step(entradas(20.0))
    assert saida["mv_pid"] == PortSample(10.0, True)


# --------------------------------------------------------------------------------------
# 2. Aplicar-na-fronteira: resultado NUNCA muda porta no meio da varredura (RF-401)
# --------------------------------------------------------------------------------------


async def test_resultado_entre_fronteiras_so_muda_a_porta_na_fronteira_seguinte() -> None:
    block, host, *_ = _block(multiplier=3)
    await _entra_remoto_auto(block)

    primeira = await block.step(entradas(20.0))  # n=0: fronteira, dispara o solve
    assert primeira["mv_pid"] == PortSample(10.0, True)

    # o worker "termina" entre fronteiras: fica só no buffer do host até ser consumido
    host.pending = _resultado_ok({"mv_pid": 77.0, "mv_direto": 2.0})

    segunda = await block.step(entradas(20.0))  # n=1: não é fronteira
    assert segunda["mv_pid"] == PortSample(10.0, True)

    terceira = await block.step(entradas(20.0))  # n=2: não é fronteira
    assert terceira["mv_pid"] == PortSample(10.0, True)

    quarta = await block.step(entradas(20.0))  # n=3: fronteira seguinte -> aplica agora
    assert quarta["mv_pid"] == PortSample(77.0, True)
    assert quarta["mv_direto"] == PortSample(2.0, True)

    assert len(host.requests) == 2, "só as duas fronteiras (n=0 e n=3) disparam solve"
    assert host.requests[0].reinit is True, "MAN->AUTO exige reinit na 1a dispatch (bumpless)"
    assert host.requests[1].reinit is False


# --------------------------------------------------------------------------------------
# 3. Overrun: mantém MV, soma contador, dedupe do evento por período
# --------------------------------------------------------------------------------------


async def test_overrun_mantem_mv_soma_contador_e_dedupe_do_evento() -> None:
    block, host, _, _, _, events = _block()
    await _entra_remoto_auto(block)

    overrun = SolveResult(
        u_plan={},
        prediction_t=[],
        prediction_cv=[],
        prediction_mv=[],
        cost=0.0,
        status="overrun",
        wall_ms=210.0,
        detail="orçamento de 70% do Ts_mpc excedido",
    )

    host.pending = overrun
    primeira = await block.step(entradas(20.0))
    assert primeira["mv_pid"] == PortSample(10.0, True)  # MV mantida
    assert block.health()["overruns"] == 1

    host.pending = overrun
    await block.step(entradas(20.0))
    assert block.health()["overruns"] == 2
    assert len(events.of_kind(KIND_MPC_OVERRUN)) == 1, "dedupe: só o 1o overrun do período emite"

    # o solve volta a convergir: a próxima falha reabre um período novo
    host.pending = _resultado_ok({"mv_pid": 10.0, "mv_direto": 1.5})
    await block.step(entradas(20.0))
    host.pending = overrun
    await block.step(entradas(20.0))
    assert block.health()["overruns"] == 3
    assert len(events.of_kind(KIND_MPC_OVERRUN)) == 2


async def test_worker_indisponivel_na_fronteira_conta_overrun_sem_emitir_evento() -> None:
    """spec §4.2: "worker indisponível -> conta e pula sem acumular fila" — SEM novo evento
    (o `mpc_overrun` já cobre o episódio pelo caminho de `poll()`, não este)."""
    block, host, _, _, _, events = _block()
    host.accept = False
    await _entra_remoto_auto(block)
    antes = len(events.events)  # a entrada em AUTO já audita 2 `mpc_mode_changed`

    await block.step(entradas(20.0))
    assert block.health()["overruns"] == 1
    assert len(events.events) == antes, "worker indisponível não deve emitir evento novo"


# --------------------------------------------------------------------------------------
# 4. `no_convergence`: alarme, MV mantida, host segue vivo (sem kill)
# --------------------------------------------------------------------------------------


async def test_no_convergence_emite_solver_error_e_nao_move_a_mv() -> None:
    block, host, _, _, _, events = _block()
    await _entra_remoto_auto(block)

    host.pending = SolveResult(
        u_plan={"mv_pid": 999.0, "mv_direto": 999.0},  # populado (carryover 1.1), NUNCA aplicado
        prediction_t=[0.0],
        prediction_cv=[[1.0]],
        prediction_mv=[[999.0]],
        cost=3.0,
        status="no_convergence",
        wall_ms=100.0,
        detail="iterate not converged",
    )
    saida = await block.step(entradas(20.0))
    assert saida["mv_pid"] == PortSample(10.0, True)
    assert saida["mv_direto"] == PortSample(1.5, True)

    erros = events.of_kind(KIND_MPC_SOLVER_ERROR)
    assert len(erros) == 1
    assert erros[0]["payload"] == {"reason": "no_convergence"}
    assert block.health()["overruns"] == 0, "falha de solver != overrun (RF-624)"

    # host segue "vivo": o bloco não desiste, tenta despachar de novo na fronteira seguinte
    host.pending = None
    await block.step(entradas(20.0))
    assert len(host.requests) == 2


# --------------------------------------------------------------------------------------
# 5. Tracking / supressão de escrita em LOCAL e sob invalidez (spec §4.3/§4.6)
# --------------------------------------------------------------------------------------


async def test_writes_a_cada_varredura_em_remoto_suprimidos_em_local_e_sob_invalidez() -> None:
    block, _, _, _, writes, events = _block()

    await block.step(entradas(20.0))  # LOCAL (padrão de boot, RNF-03): sem escrita nenhuma
    assert writes.writes == []

    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    await block.step(entradas(20.0))  # REMOTO+MAN, entrada válida: escreve
    assert len(writes.writes) == 1
    assert writes.writes[0].tag_id == 501

    await block.step(entradas(20.0, ok=False))  # entrada inválida: suprime
    assert len(writes.writes) == 1
    assert len(events.of_kind(KIND_MPC_INPUT_INVALID)) == 1

    await block.step(entradas(20.0, ok=False))  # continua inválida: dedupe, sem novo evento
    assert len(events.of_kind(KIND_MPC_INPUT_INVALID)) == 1

    await block.step(entradas(20.0))  # volta a válida: escreve de novo
    assert len(writes.writes) == 2


# --------------------------------------------------------------------------------------
# 6. SP: PV-tracking fora de AUTO, congela ao entrar (decisão A-4)
# --------------------------------------------------------------------------------------


async def test_sp_rastreia_a_cv_medida_fora_de_auto_e_congela_ao_entrar() -> None:
    block, *_, publish, _, _ = _block()

    await block.step(entradas(20.0))
    await block.step(entradas(25.0))
    assert publish.states[-1].vars["cv_a"].sp == pytest.approx(25.0)

    await _entra_remoto_auto(block)
    await block.step(entradas(90.0))  # CV medida muda muito depois de AUTO
    assert publish.states[-1].vars["cv_a"].sp == pytest.approx(25.0), "SP deve ficar congelado"
    assert publish.states[-1].vars["cv_a"].v == pytest.approx(90.0), "a medida em si segue viva"


# --------------------------------------------------------------------------------------
# Reforço: `command()` idempotente, `man_auto` ignorado em LOCAL (spec §4.8)
# --------------------------------------------------------------------------------------


async def test_command_man_auto_em_local_e_ignorado() -> None:
    block, *_, events = _block()
    await block.command("mpc_mode", {"axis": "man_auto", "value": "auto"}, OPERADOR)
    assert events.events == []


async def test_command_mpc_mode_e_idempotente_e_audita_com_user() -> None:
    block, *_, events = _block()
    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)

    mudancas = events.of_kind(KIND_MPC_MODE_CHANGED)
    assert len(mudancas) == 1
    assert mudancas[0]["payload"] == {
        "axis": "local_remote",
        "from": "local",
        "to": "remote",
        "user": OPERADOR,
    }


async def test_command_mpc_sp_so_materializa_em_auto_com_clamp_em_sp_limits() -> None:
    block, *_, events = _block()
    await block.command("mpc_sp", {"var_id": "cv_a", "value": 50.0}, OPERADOR)
    assert events.of_kind(KIND_MPC_SP_WRITTEN) == []

    await _entra_remoto_auto(block)
    await block.command("mpc_sp", {"var_id": "cv_a", "value": 999.0}, OPERADOR)
    escritas = events.of_kind(KIND_MPC_SP_WRITTEN)
    assert escritas[-1]["payload"] == {"var_id": "cv_a", "value": 200.0, "user": OPERADOR}


# --------------------------------------------------------------------------------------
# Cold start (padrão universal F3 §3.0): saídas nulas
# --------------------------------------------------------------------------------------


async def test_cold_start_produz_saidas_nulas() -> None:
    block, *_ = _block()
    saida = await block.step({"cv_a": PortSample(None, False)})
    assert saida == {"mv_pid": PortSample(None, False), "mv_direto": PortSample(None, False)}


# --------------------------------------------------------------------------------------
# Fix round 1 (review): u_applied usa o READBACK, não o comandado (spec §3.3)
# --------------------------------------------------------------------------------------


async def test_u_applied_no_solve_usa_o_readback_quando_diverge_do_comandado() -> None:
    """A realimentação por bias precisa do `u` FISICAMENTE aplicado — a posição real do PID,
    nunca o plano/manual que o bloco comandou (achado da revisão de fix round 1)."""
    block, host, snapshot, *_ = _block()
    await _entra_remoto_auto(block)
    host.pending = _resultado_ok({"mv_pid": 50.0, "mv_direto": 3.0})
    await block.step(entradas(20.0))  # aplica o plano acima -> mv_pid comandado = 50.0

    snapshot.set(503, 12.5)  # readback real diverge do comandado (posição física do PID)
    await block.step(entradas(20.0))  # nova fronteira: dispara outro solve

    ultimo = host.requests[-1]
    assert ultimo.u_applied["mv_pid"] == pytest.approx(12.5), (
        "u_applied precisa ser o READBACK, não o plano comandado"
    )
    assert ultimo.u_applied["mv_direto"] == pytest.approx(3.0), (
        "sem pid: o próprio valor mantido pelo bloco já é a posição real"
    )


# --------------------------------------------------------------------------------------
# Fix round 1 (review): publish() continua a cada fronteira mesmo com entrada inválida
# --------------------------------------------------------------------------------------


async def test_publish_continua_a_cada_fronteira_mesmo_com_entrada_invalida() -> None:
    block, _, _, publish, _, _ = _block()
    antes = len(publish.states)

    await block.step(entradas(20.0, ok=False))
    await block.step(entradas(20.0, ok=False))

    assert len(publish.states) == antes + 2, "cada fronteira publica, mesmo com entrada ruim"
    assert publish.states[-1].status.input_valid is False


# --------------------------------------------------------------------------------------
# Fix round 1 (review): SP retoma o PV-tracking ao sair de AUTO direto para LOCAL
# --------------------------------------------------------------------------------------


async def test_sp_retoma_tracking_ao_sair_de_auto_direto_para_local() -> None:
    block, *_, publish, _, _ = _block()
    await block.step(entradas(20.0))
    await _entra_remoto_auto(block)
    await block.step(entradas(50.0))  # em AUTO: SP congelado no valor de antes (20.0)
    assert publish.states[-1].vars["cv_a"].sp == pytest.approx(20.0)

    await block.command("mpc_mode", {"axis": "local_remote", "value": "local"}, OPERADOR)
    await block.step(entradas(77.0))  # de volta a LOCAL: o tracking precisa retomar
    assert publish.states[-1].vars["cv_a"].sp == pytest.approx(77.0), (
        "sair de AUTO direto para LOCAL precisa reativar o PV-tracking do SP"
    )


# --------------------------------------------------------------------------------------
# Fix round 1 (review): todo emit_event carrega o origin do bloco
# --------------------------------------------------------------------------------------


async def test_todos_os_eventos_carregam_o_origin_do_bloco() -> None:
    block, *_, events = _block()
    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    await block.command("mpc_mode", {"axis": "man_auto", "value": "auto"}, OPERADOR)
    await block.command("mpc_sp", {"var_id": "cv_a", "value": 50.0}, OPERADOR)
    await block.step(entradas(20.0, ok=False))  # dispara mpc_input_invalid

    assert events.events, "pré-condição: precisa haver eventos para checar"
    assert all(e["origin"] == "block:m1" for e in events.events)
