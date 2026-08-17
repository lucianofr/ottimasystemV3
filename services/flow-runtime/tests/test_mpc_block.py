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

Carimbo real de `ts`/`prediction.ts` (spec F5 §2.1/§3.5, F5R-01, tarefa 1.2): clock
controlado (`FakeClock`) substitui os 3 sítios `datetime.now(UTC)` interinos da 1.1 —
`ts` crescente, `prediction.ts` ancorado na fronteira do `host.dispatch()` (nunca o ts do
quadro que consome o resultado) e publicação imediata (mudança de modo) carimbando o
próprio instante.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

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
from ottima_core.snapshot import TagValue
from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.mpc import MpcBlock
from ottima_flow_runtime.mpc.worker import SolveRequest, SolveResult

TS_FLOW = 1.0
OPERADOR = "user:7"
FLOW_ID = 1


def _config(
    *, multiplier: int = 1, readback_direto: int | None = None, mode_read: int | None = None
) -> MpcConfig:
    """1 CV + 2 MVs (uma com `pid`, outra direta) — cobre a tabela de modos inteira.

    `readback_direto`: tag de posição real da MV DIRETA (sem `pid`). `None` mantém o
    comportamento de hold do `initial_value`, que é o dos demais testes deste arquivo.

    `mode_read`: tag de modo real do PID. `None` (default) mantém a MV sem observabilidade
    de modo — é o que os testes deste arquivo assumem; quem exercita o ADR-028 pede a tag
    (`test_mpc_mv_status.py`)."""
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
                        "max_rate": 5.0,
                        "initial_value": 10.0,
                        "pid": {
                            "write_tag_id": 501,
                            "target_mode": "rcas",
                            "mode_cmd_tag_id": 502,
                            "mode_read_tag_id": mode_read,
                            "readback_tag_id": 503,
                            "mode_values": {"auto": 0, "target": 1},
                        },
                    },
                    {
                        "id": "mv_direto",
                        "name": "MV direta",
                        "eu": "%",
                        "limits": {"min": -10.0, "max": 10.0},
                        "max_rate": 2.0,
                        "initial_value": 1.5,
                        "readback_tag_id": readback_direto,
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
    """Duplo de `ValueSnapshot` — só o `.get()` síncrono que o bloco usa."""

    def __init__(self) -> None:
        self._values: dict[int, TagValue] = {}

    def set(self, tag_id: int, value: float, *, quality: int = 0) -> None:
        self._values[tag_id] = TagValue(value=value, quality=quality, ts=datetime.now(UTC))

    def get(self, tag_id: int) -> TagValue | None:
        return self._values.get(tag_id)


class FakeClock:
    """Clock controlado (spec F5 §2.1, tarefa 1.2): cada chamada devolve o próximo
    instante de uma sequência fixa e crescente — os testes de `ts`/`prediction.ts` não
    podem depender de tempo real (§9.1)."""

    def __init__(self, start: datetime, step: timedelta) -> None:
        self._next = start
        self._step = step

    def __call__(self) -> datetime:
        ts = self._next
        self._next = self._next + self._step
        return ts


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
    *,
    multiplier: int = 1,
    now: Callable[[], datetime] | None = None,
    readback_direto: int | None = None,
    mode_read: int | None = None,
    escreve_sem_watchdog: bool = False,
) -> tuple[MpcBlock, FakeHost, FakeSnapshot, Publishes, Writes, Events]:
    host = FakeHost()
    snapshot = FakeSnapshot()
    publish = Publishes()
    write_opc = Writes()
    emit_event = Events()
    block = MpcBlock(
        "m1",
        config=_config(multiplier=multiplier, readback_direto=readback_direto, mode_read=mode_read),
        ts_flow=TS_FLOW,
        snapshot=snapshot,
        host=host,
        flow_id=FLOW_ID,
        publish=publish,
        write_opc=write_opc,
        emit_event=emit_event,
        now=now,
        escreve_sem_watchdog=escreve_sem_watchdog,
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


async def test_local_com_readback_configurado_e_sem_valor_sai_frio() -> None:
    """Tag de readback configurada e ainda sem nenhum valor publicado: a saída sai FRIA, não
    com o `initial_value`. Em LOCAL quem manda no atuador é a planta — o `opc_write` a
    jusante escreveria um degrau que ninguém comandou (é o que aconteceria a cada redeploy,
    na janela entre subir o flow e a primeira amostra da tag chegar). É o mesmo estado que
    `auto_arm_blocked_reason()` já classifica como `cold_input`: a porta agora concorda."""
    block, *_ = _block()
    saida = await block.step(entradas(20.0))
    assert saida["mv_pid"] == PortSample(None, False)


async def test_local_sem_tag_de_readback_segura_o_initial_value() -> None:
    """Sem tag de readback configurada não há o que esperar — vale o hold de sempre. É a MV
    direta "cega", que não tem como saber a posição real."""
    block, *_ = _block()
    saida = await block.step(entradas(20.0))
    assert saida["mv_direto"] == PortSample(1.5, True)


async def test_local_mv_direta_com_readback_configurado_e_sem_valor_sai_fria() -> None:
    """Mesma regra na MV direta — e aqui ela é a que importa de verdade: a porta da MV
    direta alimenta um `opc_write`, que escreve em TODOS os modos. Sair fria é o que faz o
    `opc_write` suprimir a escrita (`write_suppressed`) em vez de mandar o `initial_value`
    para a planta."""
    block, *_ = _block(readback_direto=601)

    saida = await block.step(entradas(20.0))

    assert saida["mv_direto"] == PortSample(None, False)


async def test_local_sem_pid_segue_o_readback_configurado() -> None:
    """MV direta com `readback_tag_id`: em LOCAL a saída acompanha a variável OPC-UA à qual
    a MV está ligada, não um `initial_value` de config. Sem isso o `opc_write` a jusante
    escreve na planta, em LOCAL, um valor que ninguém comandou — e a passagem para REMOTO
    dá um degrau do tamanho da diferença."""
    block, _, snapshot, *_ = _block(readback_direto=601)
    snapshot.set(601, 4.25)

    saida = await block.step(entradas(20.0))

    assert saida["mv_direto"] == PortSample(4.25, True)


async def test_readback_com_qualidade_ruim_nao_e_posicao() -> None:
    """`quality != 0` invalida a leitura (mesma regra do `opc_read`, spec F3 §3.1): uma
    amostra ruim NÃO é medição de posição. Adotá-la faria a MV seguir lixo em LOCAL e, pior,
    semear `_mv_manual` com ele na entrada em REMOTO+MAN.

    Caso real: durante um restart da planta as tags de readback voltaram com 0,0 e
    `quality=2`; com a leitura ruim tratada como verdade, a transferência para MAN parte de
    zero e o clamp em `limits` manda o atuador para o batente mínimo."""
    block, _, snapshot, *_ = _block(readback_direto=601)
    snapshot.set(601, 4.25)
    await block.step(entradas(20.0))
    snapshot.set(601, 0.0, quality=2)  # planta reiniciando: valor ruim
    saida = await block.step(entradas(20.0))

    assert saida["mv_direto"] == PortSample(None, False), (
        "sem posição confiável a porta sai fria — o `opc_write` a jusante suprime a escrita"
    )

    # O que de fato protege o atuador: a amostra ruim não vira o valor vigente, então a
    # entrada em REMOTO+MAN parte da última posição BOA (4,25) e não de 0,0 — que o clamp
    # em `limits` transformaria no batente mínimo da MV.
    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    saida = await block.step(entradas(20.0))

    assert saida["mv_direto"] == PortSample(4.25, True)


async def test_local_para_remoto_man_parte_do_readback_sem_degrau() -> None:
    """LOCAL -> REMOTO entra em MAN com a MV manual := valor vigente (spec §4.4). Vigente é
    a posição real lida da planta, então a primeira saída em REMOTO repete exatamente a
    última saída em LOCAL — é a transferência bumpless do eixo LOCAL/REMOTO."""
    block, _, snapshot, *_ = _block(readback_direto=601)
    snapshot.set(601, 4.25)
    await block.step(entradas(20.0))

    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    saida = await block.step(entradas(20.0))

    assert saida["mv_direto"] == PortSample(4.25, True)


async def test_auto_arm_blocked_reason_exige_readback_da_mv_direta() -> None:
    """Mesma regra já vigente para o `pid` (`cold_input`): configurada a tag de posição, o
    bloco não pode armar antes de ela chegar — `u_applied` e o init bumpless partiriam do
    `initial_value`, uma ficção."""
    block, _, snapshot, *_ = _block(readback_direto=601)
    snapshot.set(503, 42.0)  # readback do PID presente; o da MV direta ainda não
    await block.step(entradas(20.0))

    assert block.auto_arm_blocked_reason() == "cold_input"

    snapshot.set(601, 4.25)
    assert block.auto_arm_blocked_reason() is None


async def test_remoto_man_e_o_valor_manual_clampado_em_limits() -> None:
    block, *_ = _block()
    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    await block.command("mpc_mv", {"var_id": "mv_direto", "value": 999.0}, OPERADOR)
    saida = await block.step(entradas(20.0))
    assert saida["mv_direto"] == PortSample(10.0, True)  # clamp em limits.max=10.0


async def test_remoto_auto_aplica_o_ultimo_plano() -> None:
    block, host, snapshot, *_ = _block()
    # Readback publicado: sem ele a MV é `out_of_service` (ADR-028) e sai congelada — estado
    # que o gate de arme já impede em produção (`cold_input`), mas que um teste que chama
    # `command()` direto alcança. Publicar deixa o cenário reproduzir um bloco REALMENTE
    # armável, que é o que este teste quer exercitar.
    snapshot.set(503, 10.0)
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


async def test_reentrar_em_auto_nao_reaplica_o_plano_velho() -> None:
    """MAN->AUTO tem que partir do ÚLTIMO VALOR DA MV EM MAN (spec §4.4) — nunca de um
    plano calculado antes de o operador assumir. O `_plan` guardado é de outra condição de
    planta e de outro `u_prev`; reaplicá-lo é um degrau instantâneo, sem passar pelo Δu, no
    exato instante em que o operador devolve o controle ao MPC.

    Visto em planta: MV recolocada em 52 % no MAN, e a volta para AUTO jogou o atuador para
    7 % (o plano de uma condição anterior) antes de qualquer solve novo — o oposto de
    transferência sem salto. Só o primeiro `SolveResult` NOVO pode mover a MV."""
    block, host, snapshot, *_ = _block()
    # MV observável (ADR-028) — ver nota em `test_remoto_auto_aplica_o_ultimo_plano`
    snapshot.set(503, 10.0)
    await _entra_remoto_auto(block)
    host.pending = _resultado_ok({"mv_pid": 33.0, "mv_direto": -4.0})
    await block.step(entradas(20.0))
    assert (await block.step(entradas(20.0)))["mv_pid"] == PortSample(33.0, True)

    # Operador assume e reposiciona a MV
    await block.command("mpc_mode", {"axis": "man_auto", "value": "man"}, OPERADOR)
    await block.command("mpc_mv", {"var_id": "mv_pid", "value": 60.0}, OPERADOR)
    assert (await block.step(entradas(20.0)))["mv_pid"] == PortSample(60.0, True)

    # Devolve para AUTO: sem plano novo ainda, a saída segura os 60 % do MAN
    await block.command("mpc_mode", {"axis": "man_auto", "value": "auto"}, OPERADOR)
    saida = await block.step(entradas(20.0))

    assert saida["mv_pid"] == PortSample(60.0, True), (
        "voltar para AUTO reaplicou o plano velho em vez de segurar o valor do MAN"
    )


# --------------------------------------------------------------------------------------
# 1b. status.solver honesto: nunca "ok" antes do primeiro resultado real (spec §5.2)
# --------------------------------------------------------------------------------------


async def test_solver_status_nao_e_ok_antes_do_primeiro_resultado_real() -> None:
    """Entrar em AUTO com host pronto e zero solves concluídos: `status.solver` publicado
    não pode ser "ok" — não há `SolveResult` genuíno aplicado ainda (achado da tarefa 4.2,
    E2E F4b). Só um resultado "ok" real aplicado muda o rótulo."""
    block, host, _, publish, _, _ = _block()
    await _entra_remoto_auto(block)  # host pronto, zero solves — a janela do defeito
    assert publish.states[-1].status.solver == "idle"

    await block.step(entradas(20.0))  # fronteira: dispara o solve, ainda sem resultado
    assert publish.states[-1].status.solver == "idle"

    host.pending = _resultado_ok({"mv_pid": 33.0, "mv_direto": -4.0})
    await block.step(entradas(20.0))  # fronteira seguinte: consome o resultado real
    assert publish.states[-1].status.solver == "ok"


# --------------------------------------------------------------------------------------
# 1c. `building` publicado em QUALQUER modo, precedendo `idle` (tarefa 4.1, F5a; spec F5
#     §6.2 — emenda F4 §4.2/§5.1). Antes desta tarefa, `_build_state` forçava `idle` fora
#     de AUTO sem checar `host.ready` — o operador não tinha nenhum estado publicado que
#     explicasse a janela de boot do worker em LOCAL/REMOTO+MAN (deploy nasce sempre LOCAL,
#     RNF-03).
# --------------------------------------------------------------------------------------


async def test_building_publicado_em_local_quando_host_ainda_nao_esta_pronto() -> None:
    block, host, _, publish, _, _ = _block()
    host.ready = False
    await block.step(entradas(20.0))
    assert publish.states[-1].status.solver == "building"


async def test_transicao_building_para_idle_em_local_quando_host_fica_pronto() -> None:
    block, host, _, publish, _, _ = _block()
    host.ready = False
    await block.step(entradas(20.0))
    assert publish.states[-1].status.solver == "building"

    host.ready = True
    await block.step(entradas(20.0))
    assert publish.states[-1].status.solver == "idle"


async def test_transicao_building_para_ok_em_auto_quando_host_fica_pronto() -> None:
    """A mesma emenda vale em AUTO — este caminho já funcionava antes da tarefa (reforço
    de não-regressão do reordenamento em `_build_state`): `building` enquanto o host não
    está pronto mesmo já armado REMOTO+AUTO, `idle` sem plano aplicado, `ok` só depois do
    primeiro `SolveResult` genuíno (espelha `test_solver_status_nao_e_ok_antes_do_
    primeiro_resultado_real`, partindo de um host ainda não pronto)."""
    block, host, _, publish, _, _ = _block()
    host.ready = False
    host.accept = False  # `MpcHost.dispatch()` real recusa sem `ready` — espelha o double
    await _entra_remoto_auto(block)
    assert publish.states[-1].status.solver == "building"

    await block.step(entradas(20.0))  # fronteira: host ainda não pronto, dispatch recusado
    assert publish.states[-1].status.solver == "building"

    host.ready = True
    host.accept = True
    await block.step(entradas(20.0))  # fronteira: host pronto, dispara o solve sem resultado
    assert publish.states[-1].status.solver == "idle"

    host.pending = _resultado_ok({"mv_pid": 33.0, "mv_direto": -4.0})
    await block.step(entradas(20.0))  # fronteira seguinte: consome o resultado real
    assert publish.states[-1].status.solver == "ok"


# --------------------------------------------------------------------------------------
# 2. Aplicar-na-fronteira: resultado NUNCA muda porta no meio da varredura (RF-401)
# --------------------------------------------------------------------------------------


async def test_resultado_entre_fronteiras_so_muda_a_porta_na_fronteira_seguinte() -> None:
    block, host, snapshot, *_ = _block(multiplier=3)
    # MV observável (ADR-028) — ver nota em `test_remoto_auto_aplica_o_ultimo_plano`
    snapshot.set(503, 10.0)
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
    assert events.of_kind(KIND_MPC_OVERRUN)[-1]["payload"] == {"overruns": 1}

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
    assert events.of_kind(KIND_MPC_OVERRUN)[-1]["payload"] == {"overruns": 3}, (
        "cada período novo publica o contador CORRENTE, não reinicia do zero — é o que "
        "distingue duas publicações consecutivas com o MESMO valor (overrun parou) de "
        "duas com valor crescente (overrun contínuo)"
    )


async def test_reset_zera_overruns_e_proximo_evento_reflete_o_contador_resomado() -> None:
    """`reset()` (hot-swap/stop) zera `self._overruns` (blocks/mpc.py:234) — o evento do
    próximo overrun tem que carregar o contador RESOMADO desde zero, não o acumulado
    anterior ao reset. Sem isso, a cessação de alarme do frontend (duas publicações
    consecutivas com valor igual) confundiria um hot-swap com um overrun contínuo."""
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
    await block.step(entradas(20.0))
    assert block.health()["overruns"] == 1
    assert events.of_kind(KIND_MPC_OVERRUN)[-1]["payload"] == {"overruns": 1}

    block.reset()
    assert block.health()["overruns"] == 0

    await _entra_remoto_auto(block)
    host.pending = overrun
    await block.step(entradas(20.0))
    assert block.health()["overruns"] == 1
    assert events.of_kind(KIND_MPC_OVERRUN)[-1]["payload"] == {"overruns": 1}, (
        "após reset(), o contador resoma do zero — o evento novo carrega o valor zerado, "
        "não o valor acumulado antes do reset"
    )


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
    block, _, snapshot, _, writes, events = _block()
    snapshot.set(503, 10.0)  # MV observável (ADR-028) — sem readback a escrita dela é suprimida

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
    assert saida == {
        "mv_pid": PortSample(None, False),
        "mv_direto": PortSample(None, False),
        "local": PortSample(None, False),
        "auto": PortSample(None, False),
    }


# --------------------------------------------------------------------------------------
# Portas fixas `local`/`auto` (decisão A-10 revista, spec F4 §2.1-5): eixos de modo do
# bloco, SEMPRE presentes em output_ports — numéricas 1.0/0.0, nunca uma variável do
# usuário.
# --------------------------------------------------------------------------------------


def test_output_ports_inclui_as_2_portas_fixas_apos_as_mvs() -> None:
    block, *_ = _block()
    assert set(block.output_ports) == {"mv_pid", "mv_direto", "local", "auto"}
    assert block.output_ports[-2:] == ("local", "auto")


async def test_boot_local_man_publica_local_1_e_auto_0() -> None:
    """Deploy nasce sempre LOCAL/MAN (RF-621, RNF-03) — sem nenhum command()."""
    block, *_ = _block()
    saida = await block.step(entradas(20.0))
    assert saida["local"] == PortSample(1.0, True)
    assert saida["auto"] == PortSample(0.0, True)


async def test_remoto_man_publica_local_0_e_auto_0() -> None:
    block, *_ = _block()
    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    saida = await block.step(entradas(20.0))
    assert saida["local"] == PortSample(0.0, True)
    assert saida["auto"] == PortSample(0.0, True)


async def test_remoto_auto_publica_local_0_e_auto_1() -> None:
    block, *_ = _block()
    await _entra_remoto_auto(block)
    saida = await block.step(entradas(20.0))
    assert saida["local"] == PortSample(0.0, True)
    assert saida["auto"] == PortSample(1.0, True)


async def test_entrada_invalida_propaga_ok_false_tambem_em_local_e_auto() -> None:
    """Decisão A-6: uma invalidez, uma flag, em TODA porta do bloco — as fixas não são
    exceção só porque o valor não depende da CV/Restrição/DV."""
    block, *_ = _block()
    saida = await block.step(entradas(20.0, ok=False))
    assert saida["local"] == PortSample(1.0, False)
    assert saida["auto"] == PortSample(0.0, False)


async def test_mv_last_e_mv_manual_nunca_herdam_local_ou_auto() -> None:
    """Regressão: `_compute_outputs` inclui `local`/`auto` no dict de saída desde a decisão
    A-10 revista; `_mv_last` (contrato: só MV — `EstadoMpcTransplante.mv_last`/`reset()`) e
    `_mv_manual` (copiado de `_mv_last` nas transições `local_remote`/`man_auto`) não podem
    herdar essas 2 chaves."""
    block, *_ = _block()
    await block.step(entradas(20.0))
    await _entra_remoto_auto(block)  # exercita as 2 trocas `mv_manual := dict(mv_last)`
    await block.step(entradas(20.0))
    estado = block.snapshot_estado()
    assert set(estado.mv_last) == {"mv_pid", "mv_direto"}
    assert set(estado.mv_manual) == {"mv_pid", "mv_direto"}


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
    assert all(e["origin"] == f"flow:{FLOW_ID}/block:m1" for e in events.events)


# --------------------------------------------------------------------------------------
# Fix-final item 1 (achado F-1): "crash" só quando o worker de fato respawnou; detail
# do worker (ou do host, no crash sintético) chega na mensagem do evento
# --------------------------------------------------------------------------------------


async def test_status_error_sem_respawn_nao_e_crash_e_carrega_o_detail() -> None:
    """`worker.py::_handle` isola uma exceção de UM pedido e devolve `status="error"` com o
    processo VIVO (nenhum respawn) — o bloco não pode gritar "crash" nessa hora, nem
    engolir o `detail` diagnóstico (achado F-1)."""
    block, host, _, _, _, events = _block()
    await _entra_remoto_auto(block)

    host.pending = SolveResult(
        u_plan={"mv_pid": 999.0, "mv_direto": 999.0},
        prediction_t=[],
        prediction_cv=[],
        prediction_mv=[],
        cost=0.0,
        status="error",
        wall_ms=8.0,
        detail="ValueError: NaN na matriz de estados",
    )
    saida = await block.step(entradas(20.0))
    assert saida["mv_pid"] == PortSample(10.0, True)  # MV mantida (RF-624)

    erros = events.of_kind(KIND_MPC_SOLVER_ERROR)
    assert len(erros) == 1
    assert erros[0]["payload"]["reason"] != "crash", (
        "sem respawn, o worker não crashou — reason falso derruba a confiança no alarme"
    )
    assert erros[0]["payload"].keys() == {"reason"}, "payload segue o shape do §5.3"
    assert "NaN na matriz de estados" in erros[0]["message"], (
        "o detail diagnóstico do worker não pode ser descartado (achado F-1)"
    )
    assert block.health()["overruns"] == 0, "falha de solver != overrun (RF-624)"


async def test_status_error_com_respawn_avancado_e_crash_real() -> None:
    """O MESMO `status="error"` — mas desta vez `host.stats()["respawns"]` avançou: é o
    crash literal do §4.9 (pipe morreu, host já agendou reposição)."""
    block, host, _, _, _, events = _block()
    await _entra_remoto_auto(block)

    host.respawns = 1  # host já repôs o worker antes de entregar este resultado
    host.pending = SolveResult(
        u_plan={},
        prediction_t=[],
        prediction_cv=[],
        prediction_mv=[],
        cost=0.0,
        status="error",
        wall_ms=0.0,
        detail="crash",
    )
    await block.step(entradas(20.0))

    erros = events.of_kind(KIND_MPC_SOLVER_ERROR)
    assert len(erros) == 1
    assert erros[0]["payload"] == {"reason": "crash"}


# --------------------------------------------------------------------------------------
# Fix-final item 2 (achado do arquiteto F-5): publish() na fronteira reflete ESTA
# varredura (MV e CV), e cold start ainda publica um frame
# --------------------------------------------------------------------------------------


async def test_publish_de_fronteira_usa_a_mv_desta_mesma_varredura() -> None:
    """Publish acontecia ANTES de `_compute_outputs`/`_mv_last`: `vars.<mv_id>.v` saía com
    a MV da varredura ANTERIOR enquanto `vars.<cv_id>.v` já saía com a atual — skew de uma
    varredura que corrompe o overlay de trend do F5 (achado F-5)."""
    block, _, snapshot, publish, _, _ = _block()

    snapshot.set(503, 10.0)  # readback da MV com pid nesta 1a varredura
    await block.step(entradas(50.0))

    snapshot.set(503, 20.0)  # readback muda ANTES da 2a varredura
    await block.step(entradas(60.0))

    ultimo = publish.states[-1]
    assert ultimo.vars["cv_a"].v == pytest.approx(60.0)
    assert ultimo.vars["mv_pid"].v == pytest.approx(20.0), (
        "MV publicada precisa vir do readback DESTA varredura, não da anterior"
    )


async def test_cold_start_publica_frame_com_input_valid_false_na_fronteira() -> None:
    """`step()` retornava antes de qualquer publish durante cold start — um flow recém-
    implantado ficava mudo em `mpc.state.*` até a 1a varredura quente; §5.2 pede
    publicação a cada execução, inclusive fora de AUTO (achado F-5)."""
    block, *_, publish, _, _ = _block()

    saida = await block.step({"cv_a": PortSample(None, False)})

    assert saida == {
        "mv_pid": PortSample(None, False),
        "mv_direto": PortSample(None, False),
        "local": PortSample(None, False),
        "auto": PortSample(None, False),
    }
    assert len(publish.states) == 1, "fronteira em cold start precisa publicar um frame"
    estado = publish.states[0]
    assert estado.status.input_valid is False
    assert estado.prediction.t == []


# --------------------------------------------------------------------------------------
# Fix-final item 3 (contrato com o supervisor, achado do arquiteto F-4):
# `auto_arm_blocked_reason()` também exige readback de PID publicado
# --------------------------------------------------------------------------------------


async def test_auto_arm_blocked_reason_exige_readback_do_pid() -> None:
    """Sem o readback (tag 503) publicado no snapshot, `_effective_value` cai no
    `initial_value` — armar sobre essa ficção quebraria `u_applied` e o init bumpless
    (§3.6). O predicado único (contrato com `MpcOrchestrator`) tem que barrar isso ANTES
    de o supervisor sequer tentar `local_remote -> remote` ou `MAN -> AUTO`."""
    block, _, snapshot, *_ = _block()
    await block.step(entradas(20.0))  # aquenta a única entrada (cv_a)

    assert block.auto_arm_blocked_reason() == "cold_input", (
        "mv_pid tem `pid` mas o readback (tag 503) nunca chegou"
    )

    snapshot.set(503, 42.0)  # readback chega
    assert block.auto_arm_blocked_reason() is None


# --------------------------------------------------------------------------------------
# TD-004: `auto_arm_blocked_reason()` barra o arme quando o bloco escreve numa conexão
# sem watchdog — a causa é estática (config da conexão), então o gate é a defesa: o
# `writes.py` do opc-worker recusaria a escrita de qualquer forma (somente leitura de
# fato), e armar sobre isso seria uma ilusão de controle.
# --------------------------------------------------------------------------------------


async def test_auto_arm_blocked_reason_bloqueia_quando_escreve_sem_watchdog() -> None:
    block, _, snapshot, *_ = _block(escreve_sem_watchdog=True, readback_direto=601)
    await block.step(entradas(20.0))
    snapshot.set(503, 42.0)
    snapshot.set(601, 4.25)  # entradas quentes: sem a flag, o bloco armaria normalmente

    assert block.auto_arm_blocked_reason() == "write_target_sem_watchdog"


async def test_auto_arm_blocked_reason_sem_a_flag_e_inalterado() -> None:
    """`escreve_sem_watchdog=False` (padrão) reproduz exatamente o gate de antes desta
    tarefa — guard de não-regressão."""
    block, _, snapshot, *_ = _block(escreve_sem_watchdog=False, readback_direto=601)
    await block.step(entradas(20.0))
    snapshot.set(503, 42.0)
    snapshot.set(601, 4.25)

    assert block.auto_arm_blocked_reason() is None


async def test_auto_arm_blocked_reason_com_a_flag_precede_cold_input() -> None:
    """Entrada fria E flag ligada: o motivo novo ganha — erro de configuração precede
    condição transiente (a entrada pode esquentar; a conexão sem watchdog, não)."""
    block, *_ = _block(escreve_sem_watchdog=True)

    assert block.auto_arm_blocked_reason() == "write_target_sem_watchdog"


# --------------------------------------------------------------------------------------
# Tarefa 1.2: carimbo real de ts/prediction.ts no runtime (spec F5 §2.1/§3.5, F5R-01)
# --------------------------------------------------------------------------------------


def _resultado_com_predicao(
    u_plan: dict[str, float], *, prediction_mv: list[list[float]]
) -> SolveResult:
    """Como `_resultado_ok`, mas com `prediction_mv` populado — os testes de ts precisam
    do valor real que `prediction.mv[i][0]` carrega, não só o formato vazio."""
    return SolveResult(
        u_plan=u_plan,
        prediction_t=[0.0],
        prediction_cv=[],
        prediction_mv=prediction_mv,
        cost=1.0,
        status="ok",
        wall_ms=5.0,
    )


async def test_ts_do_quadro_e_crescente_entre_fronteiras() -> None:
    """Clock controlado (spec F5 §2.1-1): `ts` publicado em cada fronteira vem do relógio
    injetado — não mais o `datetime.now(UTC)` interino da 1.1 — e cresce a cada varredura,
    espaçado exatamente pelo `Ts_mpc` (prova de que é o clock controlado que governa, não
    qualquer fonte monotônica)."""
    inicio = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FakeClock(inicio, timedelta(seconds=1.0))
    block, *_, publish, _, _ = _block(now=clock)

    for _ in range(3):
        await block.step(entradas(20.0))

    tss = [estado.ts for estado in publish.states]
    assert tss == sorted(tss) and len(set(tss)) == len(tss), "ts precisa crescer a cada fronteira"
    passo = timedelta(seconds=block.ts_mpc)
    assert tss[1] - tss[0] == passo
    assert tss[2] - tss[1] == passo


async def test_publicacao_imediata_carimba_o_instante_da_propria_publicacao() -> None:
    """Mudança de modo publica fora da fronteira (spec F4 §5.2): `ts` é o instante da
    PRÓPRIA publicação — cada chamada consome um tick novo do relógio, nunca reaproveita
    o carimbo da última varredura (spec F5 §2.1-1)."""
    inicio = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FakeClock(inicio, timedelta(seconds=1.0))
    block, *_, publish, _, _ = _block(now=clock)

    await block.command("mpc_mode", {"axis": "local_remote", "value": "remote"}, OPERADOR)
    ts_publicacao_imediata = publish.states[-1].ts

    await block.step(entradas(20.0))  # 1a fronteira: consome o PRÓXIMO tick do clock
    ts_fronteira = publish.states[-1].ts

    passo = timedelta(seconds=block.ts_mpc)
    assert ts_fronteira - ts_publicacao_imediata == passo, (
        "cada publicação consome seu próprio tick do relógio — nunca reaproveita ts alheio"
    )
    assert ts_publicacao_imediata != ts_fronteira


async def test_fora_de_auto_prediction_ts_e_igual_ao_ts_do_quadro() -> None:
    """Fora de AUTO, `prediction` é vazia e ancorada no PRÓPRIO `ts` do quadro — nunca a
    fronteira de um dispatch que não existe (spec F5 §2.1-2, já correto desde a 1.1;
    travado aqui com o clock controlado da 1.2)."""
    inicio = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FakeClock(inicio, timedelta(seconds=1.0))
    block, *_, publish, _, _ = _block(now=clock)

    await block.step(entradas(20.0))

    estado = publish.states[-1]
    assert estado.prediction.ts == estado.ts
    assert estado.prediction.t == []


async def test_prediction_ancora_no_dispatch_e_mv0_bate_com_o_quadro_anterior() -> None:
    """`prediction.ts` é a fronteira em que `host.dispatch()` foi chamado — nunca o `ts`
    do quadro que está consumindo o resultado (spec §3.5, F5R-01). Em regime,
    `prediction.ts == ts - Ts_mpc` E o primeiro ponto da predição de cada MV bate com
    `vars.<mv_id>.v` do quadro anterior a essa fronteira: sem este teste, um overlay
    deslocado de uma fronteira fica invisível (§9.1)."""
    inicio = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FakeClock(inicio, timedelta(seconds=1.0))
    block, host, _, publish, _, _ = _block(now=clock)
    await _entra_remoto_auto(block)
    ts_mpc = timedelta(seconds=block.ts_mpc)
    mv_index = block.output_ports.index("mv_direto")

    await block.step(entradas(20.0))  # frame 0: dispara o 1o solve

    host.pending = _resultado_com_predicao(
        {"mv_pid": 33.0, "mv_direto": -4.0},
        prediction_mv=[[999.0], [host.requests[0].u_applied["mv_direto"]]],
    )
    await block.step(entradas(20.0))  # frame 1: consome o resultado 0, dispara o 2o

    host.pending = _resultado_com_predicao(
        {"mv_pid": 35.0, "mv_direto": -6.0},
        prediction_mv=[[999.0], [host.requests[1].u_applied["mv_direto"]]],
    )
    await block.step(entradas(20.0))  # frame 2 ("regime"): consome o resultado 1

    vars_por_ts = {estado.ts: estado.vars["mv_direto"].v for estado in publish.states}
    estado = publish.states[-1]
    assert estado.prediction.ts == estado.ts - ts_mpc
    quadro_anterior_ts = estado.prediction.ts - ts_mpc
    assert estado.prediction.mv[mv_index][0] == vars_por_ts[quadro_anterior_ts]


async def test_dispatch_ocupado_nao_atualiza_o_instante_guardado() -> None:
    """`host.dispatch()` recusando (worker ocupado/morto, spec §3.5) não pode mover a
    âncora: o instante guardado tem de continuar sendo o da última dispatch ACEITA, senão
    o resultado dela — quando finalmente chegar — carimba `prediction.ts` com a fronteira
    errada."""
    inicio = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FakeClock(inicio, timedelta(seconds=1.0))
    block, host, _, publish, _, _ = _block(now=clock)
    await _entra_remoto_auto(block)

    await block.step(entradas(20.0))  # frame 0: dispatch aceito, guarda este ts
    ts_dispatch_aceito = publish.states[-1].ts

    host.accept = False
    await block.step(entradas(20.0))  # frame 1: recusado, não pode sobrescrever a guarda

    host.accept = True
    host.pending = _resultado_com_predicao(
        {"mv_pid": 33.0, "mv_direto": -4.0},
        prediction_mv=[[999.0], [host.requests[0].u_applied["mv_direto"]]],
    )
    await block.step(entradas(20.0))  # frame 2: consome o resultado disparado em frame 0

    assert publish.states[-1].prediction.ts == ts_dispatch_aceito, (
        "a fronteira recusada (frame 1) não pode ter sobrescrito o instante guardado"
    )
