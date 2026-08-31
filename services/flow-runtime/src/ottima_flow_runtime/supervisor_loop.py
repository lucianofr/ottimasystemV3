"""Dispatcher de comandos loop_* (espelho de supervisor_mpc.mpc_command)."""

from typing import TYPE_CHECKING, Any

from ottima_core.bus import FlowCommand

from .blocks.shell.block import BlockShell

if TYPE_CHECKING:
    from .supervisor import _FlowRuntime


async def loop_command_dispatch(runtimes: dict[int, "_FlowRuntime"], command: FlowCommand) -> None:
    """Entrega o comando ao BlockShell certo; ignora silenciosamente o resto (RNF-05)."""
    runtime: Any = runtimes.get(command.flow_id)
    if runtime is None or runtime.task.state != "running":
        return
    block_id = command.args.get("block_id")
    entry = runtime.blocks.get(block_id) if isinstance(block_id, str) else None
    if entry is None or not isinstance(entry[1], BlockShell):
        return
    await entry[1].command(command.cmd, command.args, command.user)
