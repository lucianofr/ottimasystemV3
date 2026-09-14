"""Coleta o histórico do bloco MPC (mpc_samples, 1 amostra por varredura) em CSV largo.

Uso:
    uv run python scripts/identificacao/coleta.py --start 2026-09-13T19:30:00Z \
        --end 2026-09-13T19:50:00Z --out scripts/identificacao/out/fv201.csv

Credenciais: OTTIMA_ADMIN_USERNAME/OTTIMA_ADMIN_PASSWORD (lidas de deploy/.env se ausentes).
"""

from __future__ import annotations

import argparse
import csv
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[2]
BASE = os.environ.get("OTTIMA_URL", "http://localhost:8080")
FLOW_ID = 987
BLOCK_ID = "mpc_f376ff5d"
VARS = ["mv_chns", "mv_fdou", "cv_ij93", "cv_74nu", "co_vw9g"]


def _cred(nome: str) -> str:
    if valor := os.environ.get(nome):
        return valor
    env = RAIZ / "deploy" / ".env"
    for linha in env.read_text().splitlines():
        if linha.startswith(f"{nome}="):
            return linha.split("=", 1)[1].strip()
    raise SystemExit(f"{nome} ausente no ambiente e em {env}")


def token(cli: httpx.Client) -> str:
    r = cli.post(
        "/api/auth/login",
        json={
            "username": _cred("OTTIMA_ADMIN_USERNAME"),
            "password": _cred("OTTIMA_ADMIN_PASSWORD"),
        },
    )
    r.raise_for_status()
    return r.json()["access_token"]


def coleta(start: datetime, end: datetime) -> list[dict[str, object]]:
    with httpx.Client(base_url=BASE, timeout=60.0) as cli:
        cli.headers["Authorization"] = f"Bearer {token(cli)}"
        r = cli.get(
            "/api/history/mpc",
            params={
                "flow_id": FLOW_ID,
                "block_id": BLOCK_ID,
                "var_ids": ",".join(VARS),
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
        r.raise_for_status()
        corpo = r.json()
    if corpo["mode"] != "raw":
        raise SystemExit("janela grande demais: a API devolveu médias de 1 min, não dado bruto")

    # Uma linha por timestamp; cada var vira coluna <var> (e <var>_sp para CV).
    linhas: dict[str, dict[str, object]] = {}
    for serie in corpo["series"]:
        var = serie["var_id"]
        for ts, v, sp, auto in zip(serie["t"], serie["v"], serie["sp"], serie["auto"], strict=True):
            linha = linhas.setdefault(ts, {"ts": ts})
            linha[var] = v
            if sp is not None:
                linha[f"{var}_sp"] = sp
            if auto is not None:
                linha["auto"] = auto
    return [linhas[ts] for ts in sorted(linhas)]


def coleta_tags(start: datetime, end: datetime, tag_ids: list[int]) -> list[dict[str, object]]:
    """Séries cruas das tags OPC (grade própria do poll, não a da varredura do flow)."""
    with httpx.Client(base_url=BASE, timeout=60.0) as cli:
        cli.headers["Authorization"] = f"Bearer {token(cli)}"
        r = cli.get(
            "/api/history",
            params={
                "tag_ids": ",".join(str(i) for i in tag_ids),
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
        r.raise_for_status()
        corpo = r.json()
    linhas: dict[str, dict[str, object]] = {}
    for serie in corpo["series"]:
        for ts, v in zip(serie["t"], serie["v"], strict=True):
            linhas.setdefault(ts, {"ts": ts})[f"tag_{serie['tag_id']}"] = v
    return [linhas[ts] for ts in sorted(linhas)]


def grava(linhas: list[dict[str, object]], destino: Path) -> None:
    if not linhas:
        raise SystemExit(f"nenhuma amostra na janela para {destino}")
    colunas = ["ts", *sorted({k for linha in linhas for k in linha} - {"ts"})]
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=colunas)
        w.writeheader()
        w.writerows(linhas)
    print(f"{len(linhas)} amostras -> {destino}  ({linhas[0]['ts']} .. {linhas[-1]['ts']})")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", help="ISO-8601 UTC; default: 20 min atrás")
    p.add_argument("--end", help="ISO-8601 UTC; default: agora")
    p.add_argument("--out", required=True)
    p.add_argument("--tags", help="ids de tag OPC separados por vírgula -> <out>.tags.csv")
    a = p.parse_args()
    end = datetime.fromisoformat(a.end) if a.end else datetime.now(UTC)
    start = datetime.fromisoformat(a.start) if a.start else end - timedelta(minutes=20)

    grava(coleta(start, end), Path(a.out))
    if a.tags:
        ids = [int(x) for x in a.tags.split(",")]
        grava(coleta_tags(start, end, ids), Path(a.out).with_suffix(".tags.csv"))


if __name__ == "__main__":
    main()
