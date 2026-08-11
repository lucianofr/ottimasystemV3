"""Confirmação de armar e shed do bloco MPC (spec F4 §4.4/§4.5, plano F4b tarefa 2.2).

`MpcBlock.step()` (tarefa 2.1) não sabe nada de `mode_cmd`/`mode_read`: escrever o comando
de modo no PID, esperar a confirmação em até 2×Ts_mpc e monitorar o shed (`mode_read`
divergente por 2 execuções consecutivas) olham o PID por FORA do bloco, e viram do
supervisor porque só ele decide o que fazer com uma falha (reverter modo, emitir alarme).
Mora num módulo próprio — não dentro de `supervisor.py` — para não estourar o teto de
linhas do arquivo (débito herdado do F4a, `supervisor.py` já grande) e porque a mecânica é
pura o bastante para não precisar de nenhum estado do `Supervisor`: recebe o bloco, o
snapshot e dois callbacks (`on_no_confirm`/`on_shed`) e não sabe nada de `flow_id`, Redis ou
banco — quem decide COMO reagir (escrever `mode_cmd=auto`, publicar o evento certo) é sempre
quem injeta os callbacks.

Relógio: um tick a cada `Ts_mpc` (a mesma cadência do solve, spec §4.2) — não a cada
varredura do flow (`Ts_flow`), porque tanto "2×Ts_mpc" (confirmação) quanto "2 execuções"
(shed, RF-604) são termos da spec medidos em execuções do MPC, não do flow. As duas fases
(confirmação, depois shed) usam o MESMO contador de "misses" porque são o mesmo dado
(`mode_read` bateu com `target`?) em dois momentos do ciclo de vida de REMOTO — nunca as
duas ao mesmo tempo, então `mpc_arm_failed` e `mpc_shed` nunca disputam o mesmo evento.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from ottima_core.bus import OpcWrite
from ottima_core.flowgraph import PidBinding

from .blocks.mpc import MpcBlock
from .mpc.availability import MvAvailability
from .snapshot import ValueSnapshot

CONFIRM_MISSES_LIMIT = 2
"""2×Ts_mpc sem confirmação ⇒ `no_confirm` (spec §4.4): cada "miss" é um tick de Ts_mpc."""
SHED_MISSES_LIMIT = 2
"""2 execuções consecutivas com `mode_read` divergente ⇒ shed (spec §4.5, RF-604)."""


def pid_targets(bindings: tuple[tuple[str, PidBinding], ...]) -> tuple[PidBinding, ...]:
    """Só as MVs cujo `pid` tem `mode_read_tag_id` — sem ele não há como confirmar nem
    shedar (spec §4.4/§4.5: "sem mode_read, sem shed")."""
    return tuple(pid for _, pid in bindings if pid.mode_read_tag_id is not None)


def tem_mv_disponivel(block: MpcBlock) -> bool:
    """`True` se ao menos uma MV do bloco está sob comando do MPC (ADR-028).

    Lê a classificação que o PRÓPRIO bloco apurou na última varredura em vez de reclassificar
    aqui: quem congela a MV no `SolveRequest` e suprime a escrita dela é o bloco, e o shed
    não pode discordar dessa leitura. Mapa vazio (bloco ainda não varreu) conta como "nenhuma
    disponível" — conservador, no espírito do RNF-03.
    """
    return any(status is MvAvailability.RCAS_OK for status in block.mv_status.values())


def mode_read_matches(snapshot: ValueSnapshot, targets: tuple[PidBinding, ...]) -> bool:
    """`True` só se TODAS as MVs monitoradas confirmam `target` no `mode_read` agora."""
    for pid in targets:
        tag = snapshot.get(pid.mode_read_tag_id)  # type: ignore[arg-type]
        if tag is None or float(tag.value) != float(pid.mode_values.target):
            return False
    return True


async def write_mode_cmd(
    write_opc: Callable[[OpcWrite], Awaitable[None]],
    bindings: tuple[tuple[str, PidBinding], ...],
    which: str,
    *,
    source: str,
) -> None:
    """Escreve `mode_cmd` em toda MV com `pid` (com ou sem `mode_read` — a escrita em si
    vale para qualquer `pid`, spec §4.4: "por MV com pid"; confirmação é só quem HABILITA
    o gate de espera)."""
    for _, pid in bindings:
        value = pid.mode_values.target if which == "target" else pid.mode_values.auto
        await write_opc(
            OpcWrite(
                conn_id=0,
                tag_id=pid.mode_cmd_tag_id,
                value=float(value),
                source=source,
                ts=datetime.now(UTC),
            )
        )


async def watch_arm(
    *,
    block: MpcBlock,
    snapshot: ValueSnapshot,
    on_no_confirm: Callable[[], Awaitable[None]],
    on_shed: Callable[[], Awaitable[None]],
) -> None:
    """Task de fundo por bloco armado: confirma em até `CONFIRM_MISSES_LIMIT` ticks de
    `Ts_mpc`, depois monitora shed enquanto ninguém cancelar esta task de fora — sair de
    REMOTO por qualquer caminho (comando explícito, stop gracioso, hot-swap) SEMPRE cancela
    a task ativa antes de mexer no bloco; esta função nunca decide isso sozinha, só observa
    e devolve o controle via `on_no_confirm`/`on_shed` quando o prazo estoura.

    Sem nenhuma MV com `mode_read` no config, devolve na hora: nada a confirmar, nada a
    shedar (spec §4.4/§4.5)."""
    targets = pid_targets(block.pid_bindings)
    if not targets:
        return
    ts_mpc = block.ts_mpc
    confirmed = False
    misses = 0
    while True:
        await asyncio.sleep(ts_mpc)
        matched = mode_read_matches(snapshot, targets)
        if not confirmed:
            if matched:
                confirmed = True
                misses = 0
                continue
            misses += 1
            if misses >= CONFIRM_MISSES_LIMIT:
                await on_no_confirm()
                return
            continue
        if matched:
            misses = 0
            continue
        if tem_mv_disponivel(block):
            # ADR-028 — divergência PARCIAL não derruba o bloco: as MVs que continuam em
            # RCAS seguem controlando (modo degradado) e as que saíram já estão congeladas
            # e sem escrita, por decisão do próprio bloco. O shed volta a ser tudo-ou-nada
            # só quando não sobra alavanca nenhuma. Reseta o contador: enquanto houver MV
            # disponível, a contagem de "2 execuções consecutivas" nem começa.
            misses = 0
            continue
        misses += 1
        if misses >= SHED_MISSES_LIMIT:
            await on_shed()
            return
