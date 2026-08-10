#!/usr/bin/env python3
"""CLI de operacao do MPC da planta debutanizadora no ottimaSystemV3.

uv run python planta_virtual/ottima_ops.py estado
uv run python planta_virtual/ottima_ops.py modo local_remote remote
uv run python planta_virtual/ottima_ops.py modo man_auto auto
uv run python planta_virtual/ottima_ops.py sp cv_tt101=59.3 cv_lt101=50
uv run python planta_virtual/ottima_ops.py mv mv_xv101=0
uv run python planta_virtual/ottima_ops.py hist 30            # ultimos 30 min, CSV
uv run python planta_virtual/ottima_ops.py tags 30            # historico de tags, CSV
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

RAIZ = Path(__file__).resolve().parents[1]
FLOW_NOME = "Controle-MPC-Debutanizadora"
BLOCO = "mpc1"

MPC_VARS = (
    "cv_tt101",
    "cv_tt102",
    "cv_lt101",
    "cv_lt102",
    "mv_xv101",
    "mv_xv102",
    "mv_sc101",
    "mv_sc102",
    "dv_ft100",
    "dv_at100",
)


def _env() -> dict[str, str]:
    valores: dict[str, str] = {}
    for linha in (RAIZ / "deploy" / ".env").read_text().splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, _, valor = linha.partition("=")
            valores[chave.strip()] = valor.strip()
    return valores


def login() -> httpx.Client:
    env = _env()
    cliente = httpx.Client(
        base_url=os.environ.get("OTTIMA_BASE_URL", "http://localhost:8080"), timeout=30.0
    )
    r = cliente.post(
        "/api/auth/login",
        json={
            "username": os.environ.get("OTTIMA_ADMIN_USERNAME") or env["OTTIMA_ADMIN_USERNAME"],
            "password": os.environ.get("OTTIMA_ADMIN_PASSWORD") or env["OTTIMA_ADMIN_PASSWORD"],
        },
    )
    r.raise_for_status()
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cliente


def flow_id(api: httpx.Client) -> int:
    for f in api.get("/api/flows").raise_for_status().json():
        if f["name"] == FLOW_NOME:
            return int(f["id"])
    raise SystemExit(f"flow '{FLOW_NOME}' nao encontrado")


def saude(api: httpx.Client, fid: int) -> dict[str, Any]:
    tudo = api.get("/api/health/workers").json()
    runtime = tudo.get("flow_runtime", {})
    flow = runtime.get("flows", {}).get(str(fid), {})
    conexoes = tudo.get("opc_worker", {}).get("connections", {})
    return {"flow": flow, "conexoes": conexoes}


def ultimos(api: httpx.Client, fid: int, minutos: int = 10) -> dict[str, dict[str, Any]]:
    fim = datetime.now(UTC)
    r = api.get(
        "/api/history/mpc",
        params={
            "flow_id": fid,
            "block_id": BLOCO,
            "var_ids": ",".join(MPC_VARS),
            "start": (fim - timedelta(minutes=minutos)).isoformat(),
            "end": fim.isoformat(),
        },
    )
    r.raise_for_status()
    saida: dict[str, dict[str, Any]] = {}
    for serie in r.json()["series"]:
        if not serie["t"]:
            continue
        saida[serie["var_id"]] = {
            "t": serie["t"][-1],
            "v": round(serie["v"][-1], 4),
            "sp": None if serie["sp"][-1] is None else round(serie["sp"][-1], 4),
            "auto": serie["auto"][-1],
            "n": len(serie["t"]),
        }
    return saida


def cmd_estado(api: httpx.Client, args: argparse.Namespace) -> None:
    fid = flow_id(api)
    print(
        json.dumps(
            {"flow_id": fid, "saude": saude(api, fid), "ultimo": ultimos(api, fid)},
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


def cmd_modo(api: httpx.Client, args: argparse.Namespace) -> None:
    fid = flow_id(api)
    r = api.post(f"/api/operate/{fid}/{BLOCO}/mode", json={"axis": args.axis, "value": args.value})
    print(args.axis, args.value, r.status_code, r.text or "aceito")


def _comando_por_var(api: httpx.Client, rota: str, pares: list[str]) -> None:
    fid = flow_id(api)
    for par in pares:
        var_id, _, valor = par.partition("=")
        r = api.post(
            f"/api/operate/{fid}/{BLOCO}/{rota}", json={"var_id": var_id, "value": float(valor)}
        )
        print(var_id, valor, r.status_code, r.text or "aceito")


def cmd_sp(api: httpx.Client, args: argparse.Namespace) -> None:
    _comando_por_var(api, "sp", args.pares)


def cmd_mv(api: httpx.Client, args: argparse.Namespace) -> None:
    _comando_por_var(api, "mv", args.pares)


def cmd_hist(api: httpx.Client, args: argparse.Namespace) -> None:
    """CSV com uma linha por amostra de MPC (t, var, v, sp, auto) na saida padrao."""
    fid = flow_id(api)
    fim = datetime.now(UTC)
    r = api.get(
        "/api/history/mpc",
        params={
            "flow_id": fid,
            "block_id": BLOCO,
            "var_ids": ",".join(MPC_VARS),
            "start": (fim - timedelta(minutes=args.minutos)).isoformat(),
            "end": fim.isoformat(),
        },
    )
    r.raise_for_status()
    escritor = csv.writer(sys.stdout)
    escritor.writerow(["t", "var_id", "v", "sp", "auto"])
    for serie in r.json()["series"]:
        for t, v, sp, auto in zip(serie["t"], serie["v"], serie["sp"], serie["auto"], strict=True):
            escritor.writerow([t, serie["var_id"], v, sp, auto])


def cmd_tags(api: httpx.Client, args: argparse.Namespace) -> None:
    """CSV do historico de tags OPC (ate 6 por chamada, teto de RF-802)."""
    nomes = args.tags or ["TT-101", "TT-102", "LT-101", "LT-102", "FT-100", "AT-100"]
    todas = {t["name"]: t["id"] for t in api.get("/api/tags").json()}
    ids = [todas[n] for n in nomes if n in todas]
    fim = datetime.now(UTC)
    r = api.get(
        "/api/history",
        params={
            "tag_ids": ",".join(str(i) for i in ids),
            "start": (fim - timedelta(minutes=args.minutos)).isoformat(),
            "end": fim.isoformat(),
        },
    )
    r.raise_for_status()
    por_id = {v: k for k, v in todas.items()}
    escritor = csv.writer(sys.stdout)
    escritor.writerow(["t", "tag", "v", "q"])
    for serie in r.json()["series"]:
        nome = por_id.get(serie["tag_id"], str(serie["tag_id"]))
        for t, v, q in zip(serie["t"], serie["v"], serie["q"], strict=True):
            escritor.writerow([t, nome, v, q])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("estado").set_defaults(fn=cmd_estado)
    m = sub.add_parser("modo")
    m.add_argument("axis", choices=["local_remote", "man_auto"])
    m.add_argument("value", choices=["local", "remote", "man", "auto"])
    m.set_defaults(fn=cmd_modo)
    s = sub.add_parser("sp", help="pares var_id=valor")
    s.add_argument("pares", nargs="+")
    s.set_defaults(fn=cmd_sp)
    v = sub.add_parser("mv", help="pares var_id=valor")
    v.add_argument("pares", nargs="+")
    v.set_defaults(fn=cmd_mv)
    h = sub.add_parser("hist")
    h.add_argument("minutos", type=int, default=30, nargs="?")
    h.set_defaults(fn=cmd_hist)
    t = sub.add_parser("tags")
    t.add_argument("minutos", type=int, default=30, nargs="?")
    t.add_argument("tags", nargs="*")
    t.set_defaults(fn=cmd_tags)
    args = ap.parse_args()
    args.fn(login(), args)


if __name__ == "__main__":
    main()
