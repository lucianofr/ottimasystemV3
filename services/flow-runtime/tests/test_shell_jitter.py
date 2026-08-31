"""S11: jitter de dt de +-30% nao muda o regime (ADR-039 D7)."""

import random

from shell_harness import amostra, bloco, passo

from ottima_flow_runtime.blocks.shell.kernel import StubKernel
from ottima_flow_runtime.blocks.shell.mode import Mode


async def _regime(jitter: bool) -> float:
    """Malha fechada: processo pv' = (u - pv)/tau, kernel P incremental."""
    rng = random.Random(42)
    b = bloco(kernel=StubKernel(gain=1.5), out_startup=0.0)
    pv, tau, t = 0.0, 5.0, 0.0
    await passo(b, t, **{"in": amostra(pv)})
    b.write_sp(60.0)
    b.write_target(Mode.AUTO)
    ultimo_dt = 1.0
    for _ in range(300):
        dt = 1.0 + (rng.uniform(-0.3, 0.3) if jitter else 0.0)
        t += dt
        pv += (b.u - pv) * (ultimo_dt / tau)
        await passo(b, t, **{"in": amostra(pv)})
        ultimo_dt = dt
    return b.u


async def test_s11_regime_identico_com_e_sem_jitter() -> None:
    sem = await _regime(jitter=False)
    com = await _regime(jitter=True)
    assert abs(sem - com) <= 0.5  # 0.5% do span (ADR-039 secao 7)
