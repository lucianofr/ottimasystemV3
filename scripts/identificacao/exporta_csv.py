"""Consolida um teste de degrau num CSV único, com nomes de engenharia.

Junta o histórico do bloco MPC (grade da varredura, 2 s) com as tags OPC cruas
(FT-202/FT-203, grade do poll) por vizinho mais próximo, e marca o degrau vigente.

Uso:
    uv run python scripts/identificacao/exporta_csv.py \
        --csv scripts/identificacao/out/fv201_1627_1636.csv --mv mv_chns \
        --out scripts/identificacao/out/teste1_FV-201_2026-09-13.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TZ = ZoneInfo("America/Sao_Paulo")
RENOMEIA_MPC = {
    "mv_chns": "FV-201_pct",
    "mv_fdou": "FV-202_pct",
    "cv_ij93": "LT-201_pct",
    "cv_ij93_sp": "LT-201_SP_pct",
    "cv_74nu": "Refluxo_pct",
    "cv_74nu_sp": "Refluxo_SP_pct",
    "co_vw9g": "FT-204_m3h",
    "auto": "modo_auto",
}
RENOMEIA_TAGS = {
    "tag_1480": "LT-201_raw_pct",
    "tag_1481": "FT-203_m3h",
    "tag_1482": "FT-204_raw_m3h",
    "tag_1487": "FT-202_m3h",
}
ORDEM = [
    "ts_utc",
    "ts_local",
    "t_s",
    "degrau",
    "modo_auto",
    "FV-201_pct",
    "FV-202_pct",
    "LT-201_pct",
    "LT-201_SP_pct",
    "Refluxo_pct",
    "Refluxo_SP_pct",
    "FT-204_m3h",
    "FT-202_m3h",
    "FT-203_m3h",
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True, help="CSV do histórico MPC (saída do coleta.py)")
    p.add_argument("--mv", required=True, choices=["mv_chns", "mv_fdou"], help="MV degrauada")
    p.add_argument("--out", required=True)
    a = p.parse_args()

    d = pd.read_csv(a.csv, parse_dates=["ts"]).sort_values("ts").reset_index(drop=True)
    mv_bruta = d[a.mv].to_numpy()

    tags_path = Path(a.csv).with_suffix(".tags.csv")
    if tags_path.exists():
        tags = pd.read_csv(tags_path, parse_dates=["ts"]).sort_values("ts").ffill()
        d = pd.merge_asof(d, tags, on="ts", direction="nearest")

    d = d.rename(columns=RENOMEIA_MPC | RENOMEIA_TAGS)
    d["ts_utc"] = d.ts.dt.strftime("%Y-%m-%dT%H:%M:%S.%f").str[:-3] + "Z"
    d["ts_local"] = d.ts.dt.tz_convert(TZ).dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3]
    d["t_s"] = (d.ts - d.ts.iloc[0]).dt.total_seconds().round(3)
    # patamar 0 = linha de base em MAN, 1..N = degraus; -1 = fora do ensaio (MPC em AUTO,
    # quem mexe na MV é o controlador e não o teste).
    em_man = ~d["modo_auto"].to_numpy(dtype=bool)
    passos = np.cumsum((np.abs(np.diff(mv_bruta, prepend=mv_bruta[0])) > 1.0) & em_man)
    d["degrau"] = np.where(em_man, passos, -1)

    colunas = [c for c in ORDEM if c in d.columns]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    d[colunas].to_csv(a.out, index=False, float_format="%.6f")
    print(f"{len(d)} linhas x {len(colunas)} colunas -> {a.out}")
    patamares = d.groupby("degrau")[RENOMEIA_MPC[a.mv]].agg(["mean", "count"]).round(2)
    print("  patamares:", patamares.to_dict("index"))


if __name__ == "__main__":
    main()
