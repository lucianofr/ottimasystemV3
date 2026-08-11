"""Shed do bloco vs. modo degradado por MV (ADR-028, D1).

Antes do ADR-028 o shed era tudo-ou-nada: `mode_read` divergente em QUALQUER MV por 2
execuções derrubava o MPC inteiro para LOCAL (spec F4 §4.5, RF-604). Com a reclassificação
por MV, divergência parcial vira modo degradado — as MVs que sobraram continuam controlando
— e o shed fica reservado ao caso em que NENHUMA MV está disponível.

A fase de CONFIRMAÇÃO do arme não muda: entrar em REMOTO continua exigindo que todas as MVs
monitoradas confirmem o `target` (armar é transição deliberada; ADR-028 relaxa o conjunto
ativo durante a operação, nunca a régua de entrada).

Duplos e roteiro de ticks vêm de `test_mpc_arming.py` — o mesmo `watch_arm` está sob teste
nos dois arquivos e eles não podem divergir sobre como ele é exercitado.
"""

from __future__ import annotations

import asyncio

from test_mpc_arming import _TS_MPC, _FakeBlock, _ScriptedSnapshot, _watchers

from ottima_flow_runtime.mpc.availability import MvAvailability
from ottima_flow_runtime.mpc_arming import watch_arm


async def _run(matches: list[bool], mv_status: dict[str, MvAvailability]) -> tuple[int, int]:
    """Roda `watch_arm` por `len(matches)` ticks com um mapa de disponibilidade fixo e
    devolve `(no_confirm, shed)`. Cancela ao fim: um roteiro que NÃO termina em shed
    rodaria para sempre (a última entrada do roteiro se repete)."""
    counts, on_no_confirm, on_shed = _watchers()
    block = _FakeBlock(ts_mpc=_TS_MPC)
    block.mv_status = mv_status
    task = asyncio.create_task(
        watch_arm(
            block=block,  # type: ignore[arg-type]
            snapshot=_ScriptedSnapshot(matches),  # type: ignore[arg-type]
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


async def test_divergencia_parcial_nao_sheda_o_bloco() -> None:
    """Uma MV saiu de RCAS, outra continua disponível: modo degradado, o MPC segue em
    REMOTO/AUTO com o conjunto reduzido (ADR-028 D1)."""
    no_confirm, shed = await _run(
        [True, False, False, False],
        {"mv_a": MvAvailability.LOCAL_OVERRIDE, "mv_b": MvAvailability.RCAS_OK},
    )
    assert (no_confirm, shed) == (0, 0)


async def test_sem_nenhuma_mv_disponivel_sheda_como_antes() -> None:
    """Nenhuma alavanca sobrou: o comportamento herdado (RF-604) vale integralmente — o
    bloco volta a LOCAL e o PID assume."""
    no_confirm, shed = await _run(
        [True, False, False],
        {"mv_a": MvAvailability.LOCAL_OVERRIDE, "mv_b": MvAvailability.BAD_QUALITY},
    )
    assert (no_confirm, shed) == (0, 1)


async def test_mv_indisponivel_por_qualidade_tambem_conta_para_o_shed() -> None:
    """A conta do shed é "MV disponível", não "mode_read bateu": uma MV cuja posição real
    parou de prestar não está sob comando do MPC, mesmo que o PID continue dizendo RCAS —
    o bloco já suprime a escrita dela."""
    no_confirm, shed = await _run(
        [True, False, False],
        {"mv_a": MvAvailability.BAD_QUALITY, "mv_b": MvAvailability.OUT_OF_SERVICE},
    )
    assert (no_confirm, shed) == (0, 1)


async def test_confirmacao_do_arme_continua_exigindo_todas_as_mvs() -> None:
    """Fase de confirmação: `mode_read` que nunca bate derruba o arme com `no_confirm`,
    independentemente de haver MV disponível — ADR-028 não afrouxa a entrada em REMOTO."""
    no_confirm, shed = await _run(
        [False, False],
        {"mv_a": MvAvailability.RCAS_OK, "mv_b": MvAvailability.RCAS_OK},
    )
    assert (no_confirm, shed) == (1, 0)
