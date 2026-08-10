#!/usr/bin/env python3
"""Operacoes diretas na planta virtual debutanizadora via OPC-UA.

Uso (a partir da raiz do repo):

    uv run python planta_virtual/plant_ops.py snapshot
    uv run python planta_virtual/plant_ops.py reset
    uv run python planta_virtual/plant_ops.py disturb FT-100 step 5 0 0
    uv run python planta_virtual/plant_ops.py write Plant.MV.XV-101.CMD 52

Existe para inspecionar e preparar a planta fora do ottimaSystem. Quem controla a
planta durante a campanha e o MPC do ottimaSystemV3 -- este script nao regula nada.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from asyncua import Client, ua

ENDPOINT = "opc.tcp://127.0.0.1:4843/plant/"
NAMESPACE = "urn:lfr:virtual-plant:debutanizer"

MVS = ("XV-101", "XV-102", "SC-101", "SC-102")
CVS = ("TT-101", "TT-102", "LT-101", "LT-102")
DVS = ("FT-100", "AT-100")
READINGS = ("FT-101", "FT-102", "FT-103", "FT-104", "PT-101", "PT-102")

# Ponto de operacao nominal (docs/MPC_MODELS.md secao 1, o mesmo que Reset() restaura).
NOMINAL_MV = {"XV-101": 52.0, "XV-102": 50.0, "SC-101": 55.0, "SC-102": 58.0}
NOMINAL_CV = {"TT-101": 59.282, "TT-102": 111.674, "LT-101": 49.838, "LT-102": 50.025}
NOMINAL_DV = {"FT-100": 50.0, "AT-100": 0.45}


def caminhos() -> list[str]:
    """Todos os nos de processo lidos pelo `snapshot`, na ordem de exibicao."""
    return [
        *(f"Plant.MV.{t}.CMD" for t in MVS),
        "Plant.MV.XV-101.POS",
        "Plant.MV.XV-102.POS",
        "Plant.MV.SC-101.SPD",
        "Plant.MV.SC-102.SPD",
        *(f"Plant.CV.{t}.PV" for t in CVS),
        *(f"Plant.DV.{t}.PV" for t in DVS),
        *(f"Plant.Readings.{t}.PV" for t in READINGS),
        "Plant.Sim.Clock",
        "Plant.Sim.SpeedFactor",
        "Plant.Sim.Realtime",
        "Plant.Sim.Watchdog",
        "Plant.Events.Overflow101",
        "Plant.Events.DryRun101",
        "Plant.Events.Overflow102",
        "Plant.Events.DryRun102",
    ]


async def _com_cliente(fn):
    async with Client(url=ENDPOINT) as cliente:
        idx = await cliente.get_namespace_index(NAMESPACE)
        return await fn(cliente, idx)


async def snapshot() -> dict[str, float]:
    async def _ler(cliente: Client, idx: int) -> dict[str, float]:
        nos = [cliente.get_node(f"ns={idx};s={p}") for p in caminhos()]
        valores = await cliente.read_values(nos)
        return dict(zip(caminhos(), valores, strict=True))

    return await _com_cliente(_ler)


async def chamar_metodo(nome: str, *args) -> int:
    async def _chamar(cliente: Client, idx: int) -> int:
        pai = cliente.get_node(f"ns={idx};s=Plant.Methods")
        metodo = cliente.get_node(f"ns={idx};s=Plant.Methods.{nome}")
        return await pai.call_method(metodo, *args)

    return await _com_cliente(_chamar)


async def escrever(caminho: str, valor: float) -> None:
    async def _escrever(cliente: Client, idx: int) -> None:
        no = cliente.get_node(f"ns={idx};s={caminho}")
        await no.write_value(ua.DataValue(ua.Variant(float(valor), ua.VariantType.Double)))

    await _com_cliente(_escrever)


def _formatar(dados: dict[str, float]) -> str:
    return "\n".join(
        f"{k:34s} = {v:.4f}" if isinstance(v, float) else f"{k:34s} = {v}" for k, v in dados.items()
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot")
    sub.add_parser("snapshot-json")
    sub.add_parser("reset")
    sub.add_parser("clear-events")
    d = sub.add_parser("disturb")
    d.add_argument("target", choices=["FT-100", "AT-100"])
    d.add_argument("shape", choices=["none", "step", "ramp", "sine"])
    d.add_argument("amplitude", type=float)
    d.add_argument("duration", type=float, nargs="?", default=0.0)
    d.add_argument("period", type=float, nargs="?", default=0.0)
    w = sub.add_parser("write")
    w.add_argument("caminho")
    w.add_argument("valor", type=float)
    args = ap.parse_args()

    if args.cmd == "snapshot":
        print(_formatar(asyncio.run(snapshot())))
    elif args.cmd == "snapshot-json":
        print(json.dumps(asyncio.run(snapshot()), default=str))
    elif args.cmd == "reset":
        print("Reset() ->", asyncio.run(chamar_metodo("Reset")))
    elif args.cmd == "clear-events":
        print("ClearEvents() ->", asyncio.run(chamar_metodo("ClearEvents")))
    elif args.cmd == "disturb":
        status = asyncio.run(
            chamar_metodo(
                "InjectDisturbance",
                args.target,
                args.shape,
                float(args.amplitude),
                float(args.duration),
                float(args.period),
            )
        )
        print("InjectDisturbance() ->", status)
    elif args.cmd == "write":
        asyncio.run(escrever(args.caminho, args.valor))
        print(f"escrito {args.caminho} = {args.valor}")
    else:  # pragma: no cover - argparse ja barra
        sys.exit(2)


if __name__ == "__main__":
    main()
