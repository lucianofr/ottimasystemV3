"""Alarmes de nivel edge-triggered: um evento por episodio, rearme ao sanar.

S1-S17 seguram a condicao por exatamente um scan; aqui ela persiste por 3+ scans (o caso
real de uma fonte remota BAD permanente, de um ts congelado ou de um kernel em NaN) e o
pub/sub de eventos nao pode ser inundado a taxa de scan (ADR-039: evento por transicao).
"""

import math

from shell_harness import EventosFake, amostra, bloco, passo

from ottima_flow_runtime.blocks.shell.kernel import StubKernel
from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.blocks.shell.signal import Quality, make_signal


def _alarmes(eventos: EventosFake, code: str) -> list[dict]:
    return [
        e for e in eventos.eventos if e["kind"] == "loop_alarm" and e["payload"].get("code") == code
    ]


async def test_loop_shed_uma_vez_por_episodio() -> None:
    eventos = EventosFake()
    b = bloco(eventos=eventos, permitted=Mode.OOS | Mode.MAN | Mode.AUTO | Mode.CAS)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.CAS)

    for t in (1.0, 2.0, 3.0):  # cas_in BAD persistente
        await passo(b, t, **{"in": amostra(50.0), "cas_in": make_signal(50.0, Quality.BAD)})
    assert eventos.kinds().count("loop_shed") == 1

    await passo(b, 4.0, **{"in": amostra(50.0), "cas_in": make_signal(50.0, Quality.GOOD)})
    await passo(b, 5.0, **{"in": amostra(50.0), "cas_in": make_signal(50.0, Quality.BAD)})
    assert eventos.kinds().count("loop_shed") == 2  # sanou e falhou de novo: novo evento


async def test_scan_lost_uma_vez_por_episodio() -> None:
    eventos = EventosFake()
    b = bloco(eventos=eventos)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    await passo(b, 1.0, **{"in": amostra(50.0)})

    for _ in range(3):  # dt=0 (ts congelado) por 3 scans seguidos
        await passo(b, 1.0, **{"in": amostra(50.0)})
    assert len(_alarmes(eventos, "scan_lost")) == 1

    await passo(b, 2.0, **{"in": amostra(50.0)})  # scan com dt valido rearma
    await passo(b, 2.0, **{"in": amostra(50.0)})
    assert len(_alarmes(eventos, "scan_lost")) == 2


async def test_kernel_invalid_uma_vez_por_episodio() -> None:
    eventos = EventosFake()
    kernel = StubKernel(rate=math.nan)
    b = bloco(kernel=kernel, eventos=eventos)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.AUTO)

    for t in (1.0, 2.0, 3.0):  # compute() em NaN persistente
        await passo(b, t, **{"in": amostra(50.0)})
    assert len(_alarmes(eventos, "kernel_invalid_output")) == 1

    kernel.rate = 0.0  # du/dt finito rearma
    await passo(b, 4.0, **{"in": amostra(50.0)})
    kernel.rate = math.nan
    await passo(b, 5.0, **{"in": amostra(50.0)})
    assert len(_alarmes(eventos, "kernel_invalid_output")) == 2


async def test_kernel_invalid_rearma_depois_de_saida_forcada() -> None:
    """Latch preso: em MAN o `compute()` nem roda, entao o episodio de NaN terminou.

    Sem rearme por scan, o proximo AUTO em NaN fica mudo para sempre — a rota de saida
    forcada nao tem ponto natural onde limpar a flag do alarme.
    """
    eventos = EventosFake()
    kernel = StubKernel(rate=math.nan)
    b = bloco(kernel=kernel, eventos=eventos)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.AUTO)
    await passo(b, 1.0, **{"in": amostra(50.0)})
    assert len(_alarmes(eventos, "kernel_invalid_output")) == 1

    b.write_target(Mode.MAN)  # saida forcada: kernel fora do circuito
    await passo(b, 2.0, **{"in": amostra(50.0)})
    b.write_target(Mode.AUTO)
    await passo(b, 3.0, **{"in": amostra(50.0)})
    assert len(_alarmes(eventos, "kernel_invalid_output")) == 2


async def test_kernel_invalid_rearma_depois_de_scan_invalido() -> None:
    """Mesmo latch pela outra rota que pula `compute()`: um scan de dt invalido."""
    eventos = EventosFake()
    kernel = StubKernel(rate=math.nan)
    b = bloco(kernel=kernel, eventos=eventos)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.AUTO)
    await passo(b, 1.0, **{"in": amostra(50.0)})
    assert len(_alarmes(eventos, "kernel_invalid_output")) == 1

    await passo(b, 1.0, **{"in": amostra(50.0)})  # dt=0: kernel nao consultado
    await passo(b, 2.0, **{"in": amostra(50.0)})
    assert len(_alarmes(eventos, "kernel_invalid_output")) == 2


async def test_shed_rearma_por_rota_que_nao_avalia_a_fonte() -> None:
    """Episodio de shed encerrado por uma rota que nem olha a fonte remota (PV ruim)."""
    eventos = EventosFake()
    b = bloco(eventos=eventos, permitted=Mode.OOS | Mode.MAN | Mode.AUTO | Mode.CAS)
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_target(Mode.CAS)
    await passo(b, 1.0, **{"in": amostra(50.0), "cas_in": make_signal(50.0, Quality.BAD)})
    assert eventos.kinds().count("loop_shed") == 1

    await passo(b, 2.0, **{"in": amostra(50.0, ok=False)})  # cai por PV, sem avaliar cas_in
    await passo(b, 3.0, **{"in": amostra(50.0), "cas_in": make_signal(50.0, Quality.BAD)})
    assert eventos.kinds().count("loop_shed") == 2
