"""`mpc_arming.watch_arm` — shed (spec §4.5, RF-604): reset do contador de misses em qualquer
match (achado da revisão ampla F4: o caminho "2 execuções CONSECUTIVAS" está coberto em
`test_supervisor_mpc.py`, mas nada no fio da meada prova que um `mode_read` que bate uma vez
no meio NÃO acumula rumo ao shed — um off-by-one que tornasse o contador cumulativo, em vez
de resetar a cada match, passaria por toda a suíte hoje).

Unit puro no helper: `watch_arm` só depende de duck typing (`block.pid_bindings`/`.ts_mpc`,
`snapshot.get`), então dispensa `MpcBlock`/Redis reais — mesmo espírito de `test_mpc_block.py`
(dublês para determinismo, sem pagar o custo do stack real)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ottima_core.flowgraph import ModeValues, PidBinding
from ottima_flow_runtime.mpc_arming import watch_arm
from ottima_flow_runtime.snapshot import TagValue

_TARGET = 1
_AUTO = 0
_TS_MPC = 0.01  # tick minúsculo — só a mecânica do contador está sob teste, não o tempo real.

_PID = PidBinding(
    write_tag_id=1,
    target_mode="rcas",
    mode_cmd_tag_id=2,
    mode_read_tag_id=3,
    readback_tag_id=4,
    mode_values=ModeValues(auto=_AUTO, target=_TARGET),
)


@dataclass
class _FakeBlock:
    """Só o que `watch_arm` lê do bloco de verdade (`MpcBlock.pid_bindings`/`.ts_mpc`)."""

    ts_mpc: float
    pid_bindings: tuple[tuple[str, PidBinding], ...] = field(
        default_factory=lambda: (("mv_a", _PID),)
    )


class _ScriptedSnapshot:
    """`mode_read` roteirizado por tick: cada `get()` consome o próximo bool da lista
    (`True`=bate o `target`, `False`=diverge) e trava no último valor se a lista acabar."""

    def __init__(self, matches: list[bool]) -> None:
        self._matches = matches
        self._i = 0

    def get(self, tag_id: int) -> TagValue:
        assert tag_id == _PID.mode_read_tag_id
        matched = self._matches[min(self._i, len(self._matches) - 1)]
        self._i += 1
        value = float(_TARGET) if matched else float(_AUTO)
        return TagValue(value=value, quality=0, ts=datetime.now(UTC))


def _watchers() -> tuple[dict[str, int], object, object]:
    """Callbacks contadores compartilhados pelos dois runners abaixo."""
    counts = {"no_confirm": 0, "shed": 0}

    async def _on_no_confirm() -> None:
        counts["no_confirm"] += 1

    async def _on_shed() -> None:
        counts["shed"] += 1

    return counts, _on_no_confirm, _on_shed


async def _run_to_completion(matches: list[bool], *, timeout_s: float = 2.0) -> tuple[int, int]:
    """Sobe `watch_arm` com o roteiro dado e ESPERA a task terminar sozinha (`on_no_confirm`
    ou `on_shed` disparou, ambos retornam). Só serve quando o roteiro TERMINA num shed/
    no_confirm — a última entrada da lista se repete pra sempre (`_ScriptedSnapshot`), então
    um roteiro que não termina em divergência trava aqui (use `_run_n_ticks_then_cancel`)."""
    counts, on_no_confirm, on_shed = _watchers()
    block = _FakeBlock(ts_mpc=_TS_MPC)
    snapshot = _ScriptedSnapshot(matches)
    await asyncio.wait_for(
        watch_arm(
            block=block,  # type: ignore[arg-type]
            snapshot=snapshot,  # type: ignore[arg-type]
            on_no_confirm=on_no_confirm,
            on_shed=on_shed,
        ),
        timeout=timeout_s,
    )
    return counts["no_confirm"], counts["shed"]


async def _run_n_ticks_then_cancel(matches: list[bool]) -> tuple[int, int]:
    """Sobe `watch_arm` em background, deixa rodar exatamente `len(matches)` ticks (a última
    entrada da lista repetiria pra sempre e disfarçaria um shed tardio como "nenhum shed"),
    cancela e devolve as contagens até ali."""
    counts, on_no_confirm, on_shed = _watchers()
    block = _FakeBlock(ts_mpc=_TS_MPC)
    snapshot = _ScriptedSnapshot(matches)
    task = asyncio.create_task(
        watch_arm(
            block=block,  # type: ignore[arg-type]
            snapshot=snapshot,  # type: ignore[arg-type]
            on_no_confirm=on_no_confirm,
            on_shed=on_shed,
        )
    )
    await asyncio.sleep(_TS_MPC * (len(matches) + 0.5))
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return counts["no_confirm"], counts["shed"]


async def test_shed_reseta_o_contador_em_qualquer_match_miss_match_miss_nao_sheda() -> None:
    # tick0 confirma (match); depois, na fase de shed: miss, match (reseta!), miss — só 1
    # divergência consecutiva no fim, nunca 2: sem shed, sem no_confirm.
    no_confirm, shed = await _run_n_ticks_then_cancel([True, False, True, False])
    assert (no_confirm, shed) == (0, 0)


async def test_shed_dispara_em_2_misses_consecutivos_apos_reset() -> None:
    # Mesmo roteiro acima, seguido de mais 1 miss: agora são 2 CONSECUTIVOS pós-reset ⇒ sheda.
    no_confirm, shed = await _run_to_completion([True, False, True, False, False])
    assert (no_confirm, shed) == (0, 1)


async def test_shed_dispara_em_2_misses_consecutivos_sem_reset_previo() -> None:
    # Confirma e diverge 2x seguidas, de cara — o caminho já coberto em test_supervisor_mpc.py,
    # replicado aqui no nível unitário para ancorar o contraste com o teste de reset acima.
    no_confirm, shed = await _run_to_completion([True, False, False])
    assert (no_confirm, shed) == (0, 1)
