#!/usr/bin/env python3
"""Sonda de estabilidade da sessao OPC-UA com a planta.

Mantem UMA sessao aberta, le 6 tags a cada 2 s e imprime uma linha sempre que a
sessao cai. Serve para separar "o servidor da planta derruba sessoes" de "o
opc-worker do ottima derruba a propria sessao".
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from asyncua import Client

ENDPOINT = "opc.tcp://127.0.0.1:4843/plant/"
NAMESPACE = "urn:lfr:virtual-plant:debutanizer"
CAMINHOS = (
    "Plant.CV.TT-101.PV",
    "Plant.CV.TT-102.PV",
    "Plant.CV.LT-101.PV",
    "Plant.CV.LT-102.PV",
    "Plant.DV.FT-100.PV",
    "Plant.Sim.Clock",
)


def agora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def main() -> None:
    sessao = 0
    while True:
        sessao += 1
        inicio = time.monotonic()
        leituras = 0
        try:
            async with Client(url=ENDPOINT) as cliente:
                idx = await cliente.get_namespace_index(NAMESPACE)
                nos = [cliente.get_node(f"ns={idx};s={p}") for p in CAMINHOS]
                print(f"{agora()} sessao {sessao} ABERTA", flush=True)
                while True:
                    await cliente.read_values(nos)
                    leituras += 1
                    if leituras % 30 == 0:
                        print(
                            f"{agora()} sessao {sessao} viva ha {time.monotonic() - inicio:.0f}s "
                            f"({leituras} leituras)",
                            flush=True,
                        )
                    await asyncio.sleep(2.0)
        except Exception as exc:  # noqa: BLE001 - a sonda existe para relatar qualquer queda
            print(
                f"{agora()} sessao {sessao} CAIU apos {time.monotonic() - inicio:.0f}s "
                f"({leituras} leituras): {type(exc).__name__}: {exc}",
                flush=True,
            )
            await asyncio.sleep(2.0)


if __name__ == "__main__":
    asyncio.run(main())
