"""Supervisor/definition — bloco MPC no stage, comandos, tabela de transições §4.4, shed
§4.5, stop gracioso e hot-swap §4.7 (plano F4b, tarefa 2.2; TDD estrito, Redis real).

Usa `mpc_host_echo_worker`/`mpc_host_echo_plan_worker`/`mpc_host_never_ready_worker`
(`runtime_test_helpers.py`) via `harness_factory(mpc_worker_target=...)`: `MpcHost` sobe um
processo de verdade (spawn real), mas sem pagar o custo de um solve `do-mpc`/`casadi` real —
mesmo espírito de `test_mpc_host.py`. `mpc_host_echo_plan_worker` é o único dos três que
entrega `u_plan` não-vazio (ecoa `u_applied`): é o exigido para deixar o bloco entrar em
AUTO de verdade sem `MpcBlock._compute_outputs` estourar `KeyError` (achado desta tarefa,
`u_plan={}` do `mpc_host_echo_worker` original só era seguro nos testes de `test_mpc_host.py`,
que nunca chegam à saída por modo do bloco).

`TS_SECONDS` é o piso do CHECK do banco (0,5 s, ADR-007); com `multiplier=1`,
`Ts_mpc == Ts_flow`, então a janela de confirmação (2×Ts_mpc) e o shed (2 execuções) somam
~1 s cada — dentro do orçamento de `AWAIT_TIMEOUT_S` (5 s) sem precisar encolher o piso.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from runtime_test_helpers import (
    AWAIT_TIMEOUT_S,
    MPC_SLOW_BUILD_DELAY_S,
    QUIET_WINDOW_S,
    TS_SECONDS,
    USER,
    Collector,
    Harness,
    await_until,
    create_connection,
    create_flow,
    create_project,
    create_tag,
    edge,
    graph,
    mpc_host_echo_plan_worker,
    mpc_host_echo_worker,
    mpc_host_never_ready_worker,
    mpc_host_slow_build_worker,
    node,
    publish_tag_value,
    read_node,
    read_only_graph,
    save_graph,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ottima_core.bus import (
    CHANNEL_EVENTS,
    CHANNEL_OPC_WRITES,
    KIND_MPC_ARM_FAILED,
    KIND_MPC_MODE_CHANGED,
    KIND_MPC_MV_WRITTEN,
    KIND_MPC_SHED,
    KIND_MPC_SP_WRITTEN,
    FlowStatus,
    MpcState,
    OpcWrite,
    channel_flow_status,
    channel_mpc_state,
)

Factory = Callable[..., Awaitable[Harness]]
Collect = Callable[[str], Awaitable[Collector]]
Sessions = async_sessionmaker[AsyncSession]

_MODE_AUTO = 0
_MODE_TARGET = 1
DEPLOY_TIMEOUT_S = 15.0
"""`AWAIT_TIMEOUT_S` (5s) basta pra reação do supervisor, mas `deploy` aqui paga
`MpcHost.start()` — um `spawn` real reimportando `casadi`/`do-mpc` do zero no processo
filho (custo de import a frio, não do solve): sob carga da máquina, esse boot pode passar
de 5s mesmo com o worker falso (`mpc_host_echo_worker`), que não usa nenhum dos dois."""


def mpc_graph_com_pid(
    *,
    cv_tag_id: int,
    write_tag_id: int,
    mode_cmd_tag_id: int,
    readback_tag_id: int,
    mode_read_tag_id: int | None,
    multiplier: int = 1,
    du_max: float = 5.0,
    node_id: str = "m1",
) -> dict:
    """1 CV (via OPC-Read) + 1 MV com `pid` COMPLETO — o esqueleto que exercita a tabela de
    transições §4.4 inteira (mode_cmd/mode_read reais). `mpc_graph_valido`
    (`runtime_test_helpers.py`) tem MV "direta" só para a ponte F4a; não serve aqui."""
    pid: dict = {
        "write_tag_id": write_tag_id,
        "target_mode": "rcas",
        "mode_cmd_tag_id": mode_cmd_tag_id,
        "readback_tag_id": readback_tag_id,
        "mode_values": {"auto": _MODE_AUTO, "target": _MODE_TARGET},
    }
    if mode_read_tag_id is not None:
        pid["mode_read_tag_id"] = mode_read_tag_id
    mpc_node = node(
        node_id,
        "mpc",
        2,
        {
            "name": "MPC com pid",
            "multiplier": multiplier,
            "variables": {
                "mvs": [
                    {
                        "id": "mv_a",
                        "name": "MV a",
                        "eu": "m3/h",
                        "limits": {"min": 0.0, "max": 100.0},
                        "du_max": du_max,
                        "initial_value": 10.0,
                        "pid": pid,
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
                "dvs": [],
            },
            "models": {
                "cv_a": {
                    "mv_a": {
                        "enabled": True,
                        "params": {"K": 1.2, "tau1": 10.0, "tau2": 2.0, "theta": 15.0},
                    }
                }
            },
        },
    )
    return graph([read_node("r1", 1, cv_tag_id), mpc_node], [edge("r1", "out", node_id, "cv_a")])


async def _scenario(session_factory: Sessions, *, with_mode_read: bool = True) -> dict:
    """Projeto + conexão + as tags do `pid` + flow com `mpc_graph_com_pid`. Devolve os ids
    que os testes precisam — evita repetir a mesma sequência de `create_*` uma dúzia de
    vezes."""
    project_id = await create_project(session_factory)
    connection_id = await create_connection(session_factory, project_id)
    cv_tag_id = await create_tag(session_factory, connection_id, name="cv", direction="r")
    write_tag_id = await create_tag(session_factory, connection_id, name="write", direction="w")
    mode_cmd_tag_id = await create_tag(
        session_factory, connection_id, name="mode_cmd", direction="w"
    )
    readback_tag_id = await create_tag(
        session_factory, connection_id, name="readback", direction="r"
    )
    mode_read_tag_id = (
        await create_tag(session_factory, connection_id, name="mode_read", direction="r")
        if with_mode_read
        else None
    )
    flow_id = await create_flow(
        session_factory,
        project_id,
        graph=mpc_graph_com_pid(
            cv_tag_id=cv_tag_id,
            write_tag_id=write_tag_id,
            mode_cmd_tag_id=mode_cmd_tag_id,
            readback_tag_id=readback_tag_id,
            mode_read_tag_id=mode_read_tag_id,
        ),
        ts_seconds=TS_SECONDS,
    )
    return {
        "project_id": project_id,
        "connection_id": connection_id,
        "cv_tag_id": cv_tag_id,
        "write_tag_id": write_tag_id,
        "mode_cmd_tag_id": mode_cmd_tag_id,
        "readback_tag_id": readback_tag_id,
        "mode_read_tag_id": mode_read_tag_id,
        "flow_id": flow_id,
    }


def writes_of(collector: Collector, *, tag_id: int) -> list[OpcWrite]:
    return [
        write
        for write in (OpcWrite.model_validate_json(raw) for raw in collector.received)
        if write.tag_id == tag_id
    ]


def _last_mpc_state(collector: Collector) -> MpcState:
    return MpcState.model_validate_json(collector.received[-1])


def _arm_args(block_id: str = "m1") -> dict:
    return {"block_id": block_id, "axis": "local_remote", "value": "remote"}


async def _deploy_and_warm(harness: Harness, collect: Collect, scenario: dict) -> Collector:
    """Sobe o flow e garante ao menos uma varredura com CV válida ("entrada quente"), o
    readback do `pid` no snapshot e o host MPC pronto antes de qualquer comando de modo —
    o gate de MAN->AUTO e o de LOCAL->REMOTO (`auto_arm_blocked_reason()`, achado 2 da
    revisão F4) partem de um flow já rodando com dado real, não de um deploy ainda frio.

    F-1 (spec F5 §6.1, tarefa 4.1 F5a): o boot do host roda em segundo plano — `deploy`
    não garante mais `host.ready` como garantia antes (`blocks/mpc.py::_build_state`
    publica `building` até o boot terminar, spec F5 §6.2). Os testes que armam REMOTO/
    AUTO logo depois precisam da MESMA garantia que o deploy síncrono dava antes."""
    mpc_states = await collect(channel_mpc_state(scenario["flow_id"], "m1"))
    await harness.command("deploy", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)
    runtime = harness.supervisor._runtimes[scenario["flow_id"]]  # noqa: SLF001
    await await_until(lambda: runtime.blocks["m1"][1].host.ready, timeout_s=DEPLOY_TIMEOUT_S)
    await publish_tag_value(harness.redis, scenario["connection_id"], scenario["cv_tag_id"], 90.0)
    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["readback_tag_id"], 10.0
    )
    await await_until(
        lambda: bool(mpc_states.received) and _last_mpc_state(mpc_states).status.input_valid,
        timeout_s=AWAIT_TIMEOUT_S,
    )
    return mpc_states


# --------------------------------------------------------------------------------------
# 0: deploy de flow com mpc agora succeede (a ponte F4a morreu nesta tarefa) — reforço
#    local; a atualização OFICIAL dos dois testes da ponte mora em test_supervisor.py e
#    test_hotswap.py, per a brief.
# --------------------------------------------------------------------------------------


async def test_deploy_de_flow_com_mpc_succeede(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)

    await harness.command("deploy", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)

    assert events.events("deploy_rejected") == []
    assert harness.flow_state(scenario["flow_id"]) == "running"


# --------------------------------------------------------------------------------------
# 0b: fix round 1 (achado 1) — MpcState.ts de execução é EXATAMENTE o ts publicado em
#     flow.status da mesma varredura (mesmo relogio do scheduler, spec F5 SS2.1)
# --------------------------------------------------------------------------------------


async def test_mpc_state_ts_de_execucao_bate_bit_a_bit_com_flow_status(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """spec F5 SS2.1: `ts` do quadro do MPC nas execucoes e a fronteira de varredura —
    "mesmo relogio do ts de flow.status". Fix round 1 threou o `fired_ts` do scheduler
    (`FlowTask._scan`) ate `MpcBlock.step(inputs, ts=...)`; antes desse fix o bloco usava
    um clock proprio desacoplado, entao os dois `ts` so coincidiam por sorte de timing."""
    scenario = await _scenario(session_factory)
    flow_status = await collect(channel_flow_status(scenario["flow_id"]))
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    mpc_states = await _deploy_and_warm(harness, collect, scenario)

    await await_until(lambda: len(flow_status.received) >= 1, timeout_s=AWAIT_TIMEOUT_S)

    execucao = _last_mpc_state(mpc_states)
    tss_de_varredura = {
        FlowStatus.model_validate_json(raw).ts
        for raw in flow_status.received
        if FlowStatus.model_validate_json(raw).ports  # so varreduras reais, nao transicao
    }
    assert execucao.ts in tss_de_varredura, (
        "MpcState.ts de uma execucao de fronteira precisa bater bit a bit com o ts de "
        "ALGUMA varredura publicada em flow.status — mesmo relogio (spec F5 SS2.1)"
    )


# --------------------------------------------------------------------------------------
# 1: LOCAL->REMOTO — sucesso (escreve mode_cmd=target com conn_id resolvido, confirma)
# --------------------------------------------------------------------------------------


async def test_local_para_remoto_escreve_mode_cmd_alvo_com_conn_id_resolvido_e_confirma(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    writes = await collect(CHANNEL_OPC_WRITES)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await _deploy_and_warm(harness, collect, scenario)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)

    changed = events.events(KIND_MPC_MODE_CHANGED)[0]
    assert changed.payload["axis"] == "local_remote"
    assert changed.payload["from"] == "local"
    assert changed.payload["to"] == "remote"
    assert changed.payload["user"] == USER

    mode_cmd = writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])
    assert len(mode_cmd) == 1
    assert mode_cmd[0].value == float(_MODE_TARGET)
    # carryover 2.1->2.2: conn_id chega 0 do bloco, quem resolve é definition.py — nunca 0.
    assert mode_cmd[0].conn_id == scenario["connection_id"]
    assert mode_cmd[0].conn_id != 0
    assert mode_cmd[0].source == f"flow:{scenario['flow_id']}/block:m1"

    # confirma: publica mode_read == target e prova que NENHUM mpc_arm_failed sai depois
    # de esperar além da janela de confirmação (2×Ts_mpc == 2×Ts_flow aqui).
    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["mode_read_tag_id"], float(_MODE_TARGET)
    )
    await asyncio.sleep(2.2 * TS_SECONDS)
    assert events.events(KIND_MPC_ARM_FAILED) == []


# --------------------------------------------------------------------------------------
# 2: LOCAL->REMOTO — falha (sem confirmação em 2×Ts_mpc: volta LOCAL, mpc_arm_failed)
# --------------------------------------------------------------------------------------


async def test_local_para_remoto_sem_confirmacao_em_2xtsmpc_reverte_e_arm_failed(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    writes = await collect(CHANNEL_OPC_WRITES)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    mpc_states_collector = await _deploy_and_warm(harness, collect, scenario)

    # nunca publica mode_read == target: a confirmação nunca bate.
    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())

    await await_until(
        lambda: len(events.events(KIND_MPC_ARM_FAILED)) == 1, timeout_s=AWAIT_TIMEOUT_S
    )
    falha = events.events(KIND_MPC_ARM_FAILED)[0]
    assert falha.severity == "warning"
    assert falha.payload["axis"] == "local_remote"
    assert falha.payload["reason"] == "no_confirm"

    # devolveu o PID: mode_cmd=target (armar) seguido de mode_cmd=auto (a reversão).
    await await_until(lambda: len(writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])) == 2)
    mode_cmd = writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])
    assert [w.value for w in mode_cmd] == [float(_MODE_TARGET), float(_MODE_AUTO)]

    await await_until(lambda: _last_mpc_state(mpc_states_collector).modes.local_remote == "local")


# --------------------------------------------------------------------------------------
# 2b: reversão automática não pisa num rearme concorrente (fix round 1, review Main)
# --------------------------------------------------------------------------------------


async def test_auto_revert_nao_sobrescreve_rearme_concorrente_na_janela(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """`_auto_revert` faz `await block.command(...,"local",...)`; se um `mpc_mode` do
    operador chegar e rearmar o bloco ENQUANTO esse await ainda está em voo, a escrita de
    `mode_cmd=auto` que viria a seguir não pode pisar no `mode_cmd=target` fresco do rearme.
    Simula a janela interceptando `block.command`: a PRIMEIRA vez que a reversão automática
    chama `command(...,"local",...)`, o duplo injeta o rearme concorrente (via o supervisor
    de verdade, `flow.commands`) ANTES de devolver o controle — determinístico, sem depender
    de timing de verdade."""
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    writes = await collect(CHANNEL_OPC_WRITES)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await _deploy_and_warm(harness, collect, scenario)

    runtime = harness.supervisor._runtimes[scenario["flow_id"]]  # noqa: SLF001
    block = runtime.blocks["m1"][1]
    original_command = block.command
    rearmed = asyncio.Event()

    async def intercepted_command(cmd: str, args: dict, user: str | None) -> None:
        await original_command(cmd, args, user)
        if cmd == "mpc_mode" and args.get("value") == "local" and not rearmed.is_set():
            rearmed.set()
            block.command = original_command  # evita recursão no rearme injetado abaixo
            await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
            await await_until(lambda: block.local_remote == "remote")

    block.command = intercepted_command

    # nunca publica mode_read == target: garante que o watchdog do armar ORIGINAL dispare
    # `_auto_revert` por `no_confirm` — é essa reversão que a interceptação acima atrasa.
    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: rearmed.is_set(), timeout_s=AWAIT_TIMEOUT_S)

    # Sem o fix, um 3o write (auto, obsoleto) sairia aqui. Com o fix, só os dois `target`
    # (armar original + rearme concorrente) — a reversão detecta o rearme e desiste.
    await await_until(lambda: len(writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])) >= 2)
    await asyncio.sleep(QUIET_WINDOW_S)
    mode_cmd = writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])
    assert [w.value for w in mode_cmd] == [float(_MODE_TARGET), float(_MODE_TARGET)]
    assert block.local_remote == "remote", (
        "o rearme concorrente tem de vencer, não a reversão obsoleta"
    )
    # A reversão obsoleta desiste ANTES de publicar qualquer evento (não só a escrita):
    # nenhum `mpc_arm_failed` além do que o fluxo normal já não teria motivo pra emitir.
    assert events.events(KIND_MPC_ARM_FAILED) == []


# --------------------------------------------------------------------------------------
# 3: MAN->AUTO — sucesso (host pronto + entrada quente e válida)
# --------------------------------------------------------------------------------------


async def test_man_para_auto_sucesso_com_host_pronto_e_entrada_quente_valida(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_plan_worker)
    mpc_states_collector = await _deploy_and_warm(harness, collect, scenario)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)

    await harness.command(
        "mpc_mode",
        scenario["flow_id"],
        args={"block_id": "m1", "axis": "man_auto", "value": "auto"},
    )
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 2)

    assert events.events(KIND_MPC_ARM_FAILED) == []
    changed = events.events(KIND_MPC_MODE_CHANGED)[1]
    assert changed.payload["axis"] == "man_auto"
    assert changed.payload["from"] == "man"
    assert changed.payload["to"] == "auto"

    await await_until(lambda: _last_mpc_state(mpc_states_collector).modes.man_auto == "auto")


# --------------------------------------------------------------------------------------
# 4-6: MAN->AUTO — falhas (worker_not_ready / cold_input / invalid_input)
# --------------------------------------------------------------------------------------


async def test_man_para_auto_falha_worker_not_ready(
    harness_factory: Factory,
    collect: Collect,
    session_factory: Sessions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Achado 2 da revisão F4: `worker_not_ready` bloqueia o PRÓPRIO armar REMOTO (mesmo
    predicado das duas transições) — não dá mais pra chegar em REMOTO com o host sem
    responder pra só então testar o gate de `man_auto`; quem falha agora é o axis
    `local_remote`."""
    import ottima_flow_runtime.mpc.host as host_module

    # Sem isto o teste pagaria os 30s de `_BOOT_TIMEOUT_S` esperando um handshake que o
    # worker falso nunca manda (de propósito: é assim que `host.ready` fica `False`).
    monkeypatch.setattr(host_module, "_BOOT_TIMEOUT_S", 0.3)

    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(mpc_worker_target=mpc_host_never_ready_worker)
    await harness.command("deploy", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)
    await publish_tag_value(harness.redis, scenario["connection_id"], scenario["cv_tag_id"], 90.0)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())

    await await_until(
        lambda: len(events.events(KIND_MPC_ARM_FAILED)) == 1, timeout_s=AWAIT_TIMEOUT_S
    )
    falha = events.events(KIND_MPC_ARM_FAILED)[0]
    assert falha.payload["axis"] == "local_remote"
    assert falha.payload["reason"] == "worker_not_ready"
    assert events.events(KIND_MPC_MODE_CHANGED) == []


async def test_man_para_auto_falha_cold_input(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """Achado 2 da revisão F4: entrada fria bloqueia o PRÓPRIO armar REMOTO — não dá mais
    pra chegar lá com a CV nunca publicada. `man_auto` some depois, ignorado de verdade
    (ADR-010, sub-modo só existe em REMOTO, e o bloco nunca saiu de LOCAL)."""
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await harness.command("deploy", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)
    # CV NUNCA publicada: entrada fria pra sempre (`_last_measured` nunca populado).
    runtime = harness.supervisor._runtimes[scenario["flow_id"]]  # noqa: SLF001
    await await_until(lambda: runtime.blocks["m1"][1].host.ready, timeout_s=DEPLOY_TIMEOUT_S)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())

    await await_until(
        lambda: len(events.events(KIND_MPC_ARM_FAILED)) == 1, timeout_s=AWAIT_TIMEOUT_S
    )
    falha = events.events(KIND_MPC_ARM_FAILED)[0]
    assert falha.payload["axis"] == "local_remote"
    assert falha.payload["reason"] == "cold_input"

    await harness.command(
        "mpc_mode",
        scenario["flow_id"],
        args={"block_id": "m1", "axis": "man_auto", "value": "auto"},
    )
    await asyncio.sleep(QUIET_WINDOW_S)
    assert len(events.events(KIND_MPC_ARM_FAILED)) == 1  # man_auto não gera um 2o falhado
    assert events.events(KIND_MPC_MODE_CHANGED) == []


async def test_man_para_auto_falha_invalid_input(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    mpc_states_collector = await _deploy_and_warm(harness, collect, scenario)

    # Arma REMOTO enquanto a entrada ainda está válida — depois do fix (achado 2 da
    # revisão F4) o próprio armar compartilha o gate com `man_auto`, então isto tem de vir
    # ANTES de invalidar a entrada, senão o armar em si já falharia.
    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)

    # Quente (já mediu antes), mas a MEDIDA MAIS RECENTE é inválida.
    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["cv_tag_id"], 90.0, quality=2
    )
    await await_until(lambda: _last_mpc_state(mpc_states_collector).status.input_valid is False)

    await harness.command(
        "mpc_mode",
        scenario["flow_id"],
        args={"block_id": "m1", "axis": "man_auto", "value": "auto"},
    )

    await await_until(
        lambda: len(events.events(KIND_MPC_ARM_FAILED)) == 1, timeout_s=AWAIT_TIMEOUT_S
    )
    assert events.events(KIND_MPC_ARM_FAILED)[0].payload["reason"] == "invalid_input"


# --------------------------------------------------------------------------------------
# 7: AUTO->MAN — materializa a transição (MV manual := vigente é regra do bloco, 2.1)
# --------------------------------------------------------------------------------------


async def test_auto_para_man_materializa_a_transicao(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_plan_worker)
    await _deploy_and_warm(harness, collect, scenario)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)
    await harness.command(
        "mpc_mode",
        scenario["flow_id"],
        args={"block_id": "m1", "axis": "man_auto", "value": "auto"},
    )
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 2)

    await harness.command(
        "mpc_mode",
        scenario["flow_id"],
        args={"block_id": "m1", "axis": "man_auto", "value": "man"},
    )
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 3)

    changed = events.events(KIND_MPC_MODE_CHANGED)[2]
    assert changed.payload["axis"] == "man_auto"
    assert changed.payload["from"] == "auto"
    assert changed.payload["to"] == "man"


# --------------------------------------------------------------------------------------
# 8: REMOTO->LOCAL — comando explícito devolve o PID (mode_cmd=auto)
# --------------------------------------------------------------------------------------


async def test_remoto_para_local_escreve_mode_cmd_auto_devolve_o_pid(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    writes = await collect(CHANNEL_OPC_WRITES)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await _deploy_and_warm(harness, collect, scenario)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)

    await harness.command(
        "mpc_mode",
        scenario["flow_id"],
        args={"block_id": "m1", "axis": "local_remote", "value": "local"},
    )
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 2)

    changed = events.events(KIND_MPC_MODE_CHANGED)[1]
    assert changed.payload["axis"] == "local_remote"
    assert changed.payload["from"] == "remote"
    assert changed.payload["to"] == "local"
    assert changed.payload["user"] == USER

    mode_cmd = writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])
    assert [w.value for w in mode_cmd] == [float(_MODE_TARGET), float(_MODE_AUTO)]


# --------------------------------------------------------------------------------------
# 9: stop gracioso em REMOTO — devolve mode_cmd=auto ANTES do fim (§4.4)
# --------------------------------------------------------------------------------------


async def test_stop_gracioso_em_remoto_publica_mode_cmd_auto_antes_do_fim(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    writes = await collect(CHANNEL_OPC_WRITES)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await _deploy_and_warm(harness, collect, scenario)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)

    await harness.command("stop", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "stopped")

    mode_cmd = writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])
    assert [w.value for w in mode_cmd] == [float(_MODE_TARGET), float(_MODE_AUTO)]


# --------------------------------------------------------------------------------------
# 10: shed (§4.5) — mode_read diverge por EXATAMENTE 2 execuções consecutivas
# --------------------------------------------------------------------------------------


async def test_shed_em_exatamente_2_execucoes_consecutivas_de_mode_read_divergente(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    writes = await collect(CHANNEL_OPC_WRITES)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await _deploy_and_warm(harness, collect, scenario)

    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["mode_read_tag_id"], float(_MODE_TARGET)
    )
    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())

    # Confirma no 1o tick do watchdog (Ts_mpc == Ts_flow == TS_SECONDS aqui); espera passar
    # dele sem sobrar no relógio de confirmação — só então o miss seguinte conta para SHED,
    # não para `no_confirm`.
    await asyncio.sleep(1.3 * TS_SECONDS)
    assert events.events(KIND_MPC_ARM_FAILED) == []

    # Diverge e nunca mais corrige.
    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["mode_read_tag_id"], float(_MODE_AUTO)
    )

    # Depois de só 1 execução divergente, ainda NÃO sheda (limite é 2).
    with pytest.raises(AssertionError):
        await await_until(
            lambda: len(events.events(KIND_MPC_SHED)) == 1, timeout_s=1.15 * TS_SECONDS
        )
    assert events.events(KIND_MPC_SHED) == []

    # Na 2a execução consecutiva divergente, sheda.
    await await_until(lambda: len(events.events(KIND_MPC_SHED)) == 1, timeout_s=AWAIT_TIMEOUT_S)
    shed = events.events(KIND_MPC_SHED)[0]
    assert shed.severity == "alarm"

    mode_cmd = writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])
    assert [w.value for w in mode_cmd] == [float(_MODE_TARGET), float(_MODE_AUTO)]


# --------------------------------------------------------------------------------------
# 11-12: idempotência e man_auto ignorado em LOCAL (spec §4.8, ADR-010)
# --------------------------------------------------------------------------------------


async def test_comando_local_remote_idempotente_nao_reescreve_nem_rearma(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    writes = await collect(CHANNEL_OPC_WRITES)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await _deploy_and_warm(harness, collect, scenario)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await asyncio.sleep(QUIET_WINDOW_S)

    assert len(events.events(KIND_MPC_MODE_CHANGED)) == 1
    assert len(writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])) == 1


async def test_man_auto_em_local_e_ignorado(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await harness.command("deploy", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)
    # NUNCA arma REMOTO — o bloco começa (e fica) em LOCAL.

    await harness.command(
        "mpc_mode",
        scenario["flow_id"],
        args={"block_id": "m1", "axis": "man_auto", "value": "auto"},
    )
    await asyncio.sleep(QUIET_WINDOW_S)

    # Ignorado de verdade: nem materializa, nem falha com `mpc_arm_failed` (ADR-010, o
    # sub-modo não existe em LOCAL — não é "auto bloqueado", é "auto não existe aqui").
    assert events.events(KIND_MPC_ARM_FAILED) == []
    assert events.events(KIND_MPC_MODE_CHANGED) == []


# --------------------------------------------------------------------------------------
# 13-14: clamps de mpc_sp/mpc_mv (spec §4.8)
# --------------------------------------------------------------------------------------


async def test_mpc_sp_clamp_em_sp_limits(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_plan_worker)
    await _deploy_and_warm(harness, collect, scenario)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)
    await harness.command(
        "mpc_mode",
        scenario["flow_id"],
        args={"block_id": "m1", "axis": "man_auto", "value": "auto"},
    )
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 2)

    await harness.command(
        "mpc_sp",
        scenario["flow_id"],
        args={"block_id": "m1", "var_id": "cv_a", "value": 9999.0},
    )
    await await_until(lambda: len(events.events(KIND_MPC_SP_WRITTEN)) == 1)

    escrita = events.events(KIND_MPC_SP_WRITTEN)[0]
    assert escrita.payload == {
        "kind": KIND_MPC_SP_WRITTEN,
        "var_id": "cv_a",
        "value": 200.0,  # sp_limits.max
        "user": USER,
    }


async def test_mpc_mv_clamp_em_limits(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await _deploy_and_warm(harness, collect, scenario)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)

    await harness.command(
        "mpc_mv",
        scenario["flow_id"],
        args={"block_id": "m1", "var_id": "mv_a", "value": -9999.0},
    )
    await await_until(lambda: len(events.events(KIND_MPC_MV_WRITTEN)) == 1)

    escrita = events.events(KIND_MPC_MV_WRITTEN)[0]
    assert escrita.payload == {
        "kind": KIND_MPC_MV_WRITTEN,
        "var_id": "mv_a",
        "value": 0.0,  # limits.min
        "user": USER,
    }


# --------------------------------------------------------------------------------------
# 15: hot-swap (§4.7) — config alterada com flow rodando: host novo + shed a LOCAL +
#     mpc_mode_changed{reason: hot_swap}; flow segue rodando (§4.1-5)
# --------------------------------------------------------------------------------------


async def test_hot_swap_config_alterado_com_flow_rodando_zera_worker_e_sheda_a_local(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    writes = await collect(CHANNEL_OPC_WRITES)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await _deploy_and_warm(harness, collect, scenario)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)
    # Confirma: sem isso o próprio watchdog reverteria por `no_confirm` e competiria com o
    # hot-swap por um 2o `mpc_mode_changed` — este teste quer SÓ o evento do hot-swap.
    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["mode_read_tag_id"], float(_MODE_TARGET)
    )
    await asyncio.sleep(1.3 * TS_SECONDS)

    host_before = harness.supervisor._runtimes[scenario["flow_id"]].hosts["m1"]  # noqa: SLF001

    changed_graph = mpc_graph_com_pid(
        cv_tag_id=scenario["cv_tag_id"],
        write_tag_id=scenario["write_tag_id"],
        mode_cmd_tag_id=scenario["mode_cmd_tag_id"],
        readback_tag_id=scenario["readback_tag_id"],
        mode_read_tag_id=scenario["mode_read_tag_id"],
        du_max=6.0,  # config funcional muda (§4.1-3) sem afetar horizontes/validação
    )
    await save_graph(session_factory, scenario["flow_id"], changed_graph)
    await harness.command("reload", scenario["flow_id"])

    await await_until(
        lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 2, timeout_s=AWAIT_TIMEOUT_S
    )
    hot_swap_event = events.events(KIND_MPC_MODE_CHANGED)[1]
    assert hot_swap_event.payload == {"kind": KIND_MPC_MODE_CHANGED, "reason": "hot_swap"}
    assert hot_swap_event.origin == f"flow:{scenario['flow_id']}/block:m1"

    mode_cmd = writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])
    assert [w.value for w in mode_cmd] == [float(_MODE_TARGET), float(_MODE_AUTO)]

    host_after = harness.supervisor._runtimes[scenario["flow_id"]].hosts["m1"]  # noqa: SLF001
    assert host_after is not host_before, "hot-swap tem de trocar o MpcHost por um novo"

    assert harness.flow_state(scenario["flow_id"]) == "running", (
        "hot-swap nunca derruba flow (§4.1-5)"
    )


# --------------------------------------------------------------------------------------
# 16: comando mpc_* para flow/bloco desconhecido — log e ignora (F3 §2.2-7)
# --------------------------------------------------------------------------------------


async def test_comando_mpc_para_flow_ou_bloco_desconhecido_e_ignorado(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await _deploy_and_warm(harness, collect, scenario)

    await harness.command(
        "mpc_mode",
        scenario["flow_id"],
        args={"block_id": "nao_existe", "axis": "local_remote", "value": "remote"},
    )
    await harness.command(
        "mpc_mode",
        987_654,
        args={"block_id": "m1", "axis": "local_remote", "value": "remote"},
    )
    await asyncio.sleep(QUIET_WINDOW_S)
    assert events.events(KIND_MPC_MODE_CHANGED) == []
    assert events.events(KIND_MPC_ARM_FAILED) == []

    # O consumidor de comandos segue vivo depois dos dois comandos órfãos.
    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)


# --------------------------------------------------------------------------------------
# 17: achado 1 da revisão F4 — flow falha por exceção não tratada num bloco QUALQUER com
#     o MPC ainda armado REMOTO: o watermark (`reconcile()`) devolve o PID sozinho, sem
#     esperar redeploy nenhum; idempotente, uma segunda passada não reescreve.
# --------------------------------------------------------------------------------------


async def test_flow_falha_com_mpc_armado_remoto_watermark_devolve_o_pid(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    writes = await collect(CHANNEL_OPC_WRITES)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await _deploy_and_warm(harness, collect, scenario)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)
    # Confirma: watchdog fica de pé (não reverte sozinho por `no_confirm`) até a explosão.
    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["mode_read_tag_id"], float(_MODE_TARGET)
    )
    await asyncio.sleep(2.2 * TS_SECONDS)
    assert events.events(KIND_MPC_ARM_FAILED) == []

    runtime = harness.supervisor._runtimes[scenario["flow_id"]]  # noqa: SLF001
    assert "m1" in runtime.mpc_watchdogs  # armado, watchdog vivo — precondição do teste
    mode_cmd_antes = writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])
    assert len(mode_cmd_antes) == 1  # só o write de armar até aqui

    # Explode um bloco QUALQUER (o OPC-Read "r1") — scheduler.py `_handle_loop_failure`
    # leva o flow a `failed` sem o supervisor ter tomado conhecimento nenhum.
    read_block = runtime.blocks["r1"][1]

    async def boom(inputs: object) -> None:
        raise RuntimeError("bloco-duplo explodiu de proposito")

    read_block.step = boom
    await harness.await_state(scenario["flow_id"], "failed", timeout_s=AWAIT_TIMEOUT_S)

    # Antes do watermark: PID ainda esquecido, watchdog ainda no dict.
    assert writes_of(writes, tag_id=scenario["mode_cmd_tag_id"]) == mode_cmd_antes
    assert "m1" in runtime.mpc_watchdogs

    await harness.supervisor.reconcile()
    await await_until(
        lambda: len(writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])) == 2,
        timeout_s=AWAIT_TIMEOUT_S,
    )
    mode_cmd = writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])
    assert [w.value for w in mode_cmd] == [float(_MODE_TARGET), float(_MODE_AUTO)]
    assert "m1" not in runtime.mpc_watchdogs

    # Idempotência: uma segunda passada não escreve `mode_cmd` de novo.
    await harness.supervisor.reconcile()
    await asyncio.sleep(QUIET_WINDOW_S)
    assert writes_of(writes, tag_id=scenario["mode_cmd_tag_id"]) == mode_cmd


# --------------------------------------------------------------------------------------
# 18: achado 2 da revisão F4 — LOCAL->REMOTO com entrada fria é bloqueado pelo MESMO
#     predicado do MAN->AUTO (`auto_arm_blocked_reason`); o gate não é permanente.
# --------------------------------------------------------------------------------------


async def test_local_para_remoto_com_entrada_fria_e_bloqueado_e_depois_aquecido_arma(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    writes = await collect(CHANNEL_OPC_WRITES)
    harness = await harness_factory(mpc_worker_target=mpc_host_echo_worker)
    await harness.command("deploy", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)
    # CV e readback NUNCA publicadas: entrada fria pra sempre.
    runtime = harness.supervisor._runtimes[scenario["flow_id"]]  # noqa: SLF001
    block = runtime.blocks["m1"][1]
    await await_until(lambda: block.host.ready, timeout_s=DEPLOY_TIMEOUT_S)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())

    await await_until(
        lambda: len(events.events(KIND_MPC_ARM_FAILED)) == 1, timeout_s=AWAIT_TIMEOUT_S
    )
    falha = events.events(KIND_MPC_ARM_FAILED)[0]
    assert falha.payload["axis"] == "local_remote"
    assert falha.payload["reason"] == "cold_input"
    assert writes_of(writes, tag_id=scenario["mode_cmd_tag_id"]) == []
    assert events.events(KIND_MPC_MODE_CHANGED) == []
    assert block.local_remote == "local"  # nunca transicionou (sem salto de MV possível)

    # Aquece e tenta de novo: o gate não é permanente.
    await publish_tag_value(harness.redis, scenario["connection_id"], scenario["cv_tag_id"], 90.0)
    await publish_tag_value(
        harness.redis, scenario["connection_id"], scenario["readback_tag_id"], 10.0
    )
    await await_until(lambda: block.auto_arm_blocked_reason() is None, timeout_s=AWAIT_TIMEOUT_S)

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(lambda: len(events.events(KIND_MPC_MODE_CHANGED)) == 1)
    assert len(writes_of(writes, tag_id=scenario["mode_cmd_tag_id"])) == 1


# --------------------------------------------------------------------------------------
# 19: tarefa 4.1 (F5a; spec F5 §6.1/§6.2/§6.4) — boot assíncrono do worker MPC. `_deploy`
#     (supervisor.py) e `reconcile_mpc_hosts` (supervisor_mpc.py, hot-swap) estagiam e
#     retornam sem pagar o build; `building` publicado em qualquer modo, precedendo
#     `idle`; as invariantes de armar (`mpc_arm_failed{worker_not_ready}`) intocadas.
# --------------------------------------------------------------------------------------


async def test_deploy_de_flow_mpc_com_build_lento_nao_bloqueia_stop_de_outro_flow(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """spec F5 §6.1 (tarefa 4.1, F-1; emenda letra F4 §4.1): `host.start()` sai do caminho
    síncrono do lock global em `_deploy` (`supervisor.py:293-294` antes da tarefa). O canal
    `flow.commands` tem um único consumidor sequencial
    (`ottima_core.pubsub._ResilientSubscriber._listen`, `async for message in pubsub.
    listen(): await self._safe_dispatch(message)`): o `stop` do flow B, publicado logo
    depois do `deploy` do flow A na MESMA fila, só é lido depois que o handler do `deploy`
    solta `self._lock`. Antes da tarefa, esse handler ficava preso em `await host.start()`
    pelo boot inteiro — aqui, `MPC_SLOW_BUILD_DELAY_S` (7s, bem além de `AWAIT_TIMEOUT_S`)
    antes do worker mandar o handshake."""
    scenario = await _scenario(session_factory)
    other_tag_id = await create_tag(
        session_factory, scenario["connection_id"], name="outro", direction="r"
    )
    flow_b_id = await create_flow(
        session_factory,
        scenario["project_id"],
        graph=read_only_graph(other_tag_id),
        name="Flow B",
        ts_seconds=TS_SECONDS,
    )
    harness = await harness_factory(mpc_worker_target=mpc_host_slow_build_worker)

    await harness.command("deploy", flow_b_id)
    await harness.await_state(flow_b_id, "running", timeout_s=DEPLOY_TIMEOUT_S)

    await harness.command("deploy", scenario["flow_id"])  # host leva MPC_SLOW_BUILD_DELAY_S
    await harness.command("stop", flow_b_id)  # mesma fila, logo depois

    await harness.await_state(flow_b_id, "stopped", timeout_s=AWAIT_TIMEOUT_S)


async def test_building_publicado_em_local_arm_failed_na_janela_e_idle_ao_ficar_pronto(
    harness_factory: Factory, collect: Collect, session_factory: Sessions
) -> None:
    """spec F5 §6.2/§6.4 (tarefa 4.1): `building` publicado em LOCAL desde a primeira
    fronteira do deploy — precede `idle` (spec F4 §4.2/§5.1 emendados, `blocks/mpc.py::
    _build_state`). Armar `local_remote` na janela de build ⇒
    `mpc_arm_failed{reason: worker_not_ready}` — invariante F4 preservada byte a byte
    (`supervisor_mpc.py:109,151-152`, mesmo predicado `auto_arm_blocked_reason()` dos dois
    eixos, intocado por esta tarefa). A transição building->idle acontece assim que
    `mpc_host_slow_build_worker` termina o boot — em LOCAL, sem exigir REMOTO/AUTO nenhum
    (ao contrário de antes da tarefa, em que só o caminho AUTO alcançava `building`)."""
    scenario = await _scenario(session_factory)
    events = await collect(CHANNEL_EVENTS)
    mpc_states = await collect(channel_mpc_state(scenario["flow_id"], "m1"))
    harness = await harness_factory(mpc_worker_target=mpc_host_slow_build_worker)

    await harness.command("deploy", scenario["flow_id"])
    await harness.await_state(scenario["flow_id"], "running", timeout_s=DEPLOY_TIMEOUT_S)
    await publish_tag_value(harness.redis, scenario["connection_id"], scenario["cv_tag_id"], 90.0)

    await await_until(lambda: len(mpc_states.received) >= 1, timeout_s=AWAIT_TIMEOUT_S)
    building_estado = _last_mpc_state(mpc_states)
    assert building_estado.modes.local_remote == "local"
    assert building_estado.status.solver == "building"

    await harness.command("mpc_mode", scenario["flow_id"], args=_arm_args())
    await await_until(
        lambda: len(events.events(KIND_MPC_ARM_FAILED)) == 1, timeout_s=AWAIT_TIMEOUT_S
    )
    falha = events.events(KIND_MPC_ARM_FAILED)[0]
    assert falha.payload["axis"] == "local_remote"
    assert falha.payload["reason"] == "worker_not_ready"
    assert events.events(KIND_MPC_MODE_CHANGED) == []

    await await_until(
        lambda: _last_mpc_state(mpc_states).status.solver == "idle",
        timeout_s=MPC_SLOW_BUILD_DELAY_S + AWAIT_TIMEOUT_S,
    )
