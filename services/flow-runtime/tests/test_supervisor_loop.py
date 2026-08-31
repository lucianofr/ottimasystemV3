"""Comandos loop_mode/loop_sp/loop_out chegam ao BlockShell (espelho do MPC)."""

from datetime import UTC, datetime

from shell_harness import cfg_padrao

from ottima_core.bus import FlowCommand
from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.kernel import StubKernel
from ottima_flow_runtime.supervisor_loop import loop_command_dispatch


class _RuntimeFake:
    def __init__(self, block):
        self.blocks = {"m": ({}, block)}
        self.task = type("T", (), {"state": "running"})()


def _cmd(value: float) -> FlowCommand:
    return FlowCommand(
        flow_id=1,
        cmd="loop_sp",
        args={"block_id": "m", "value": value},
        user="user:9",
        ts=datetime.now(UTC),
    )


async def test_dispatch_entrega_ao_blockshell_certo() -> None:
    b = BlockShell("m", kernel=StubKernel(), cfg=cfg_padrao())
    await loop_command_dispatch({1: _RuntimeFake(b)}, _cmd(33.0))
    assert b.sp_op == 33.0


async def test_dispatch_ignora_fluxo_parado() -> None:
    b = BlockShell("m", kernel=StubKernel(), cfg=cfg_padrao())
    fake = _RuntimeFake(b)
    fake.task.state = "stopped"
    await loop_command_dispatch({1: fake}, _cmd(33.0))
    assert b.sp_op != 33.0


async def test_dispatch_ignora_bloco_que_nao_e_malha() -> None:
    await loop_command_dispatch({1: _RuntimeFake(object())}, _cmd(33.0))  # nao explode


async def test_dispatch_ignora_flow_inexistente() -> None:
    await loop_command_dispatch({}, _cmd(33.0))  # nao explode
