"""Validação dos modelos identificados: reconstrução do refluxo e simulação MIMO
fora-da-amostra.

Duas perguntas que o ajuste par-a-par não responde:

1. **O refluxo não é uma variável de processo, é uma razão** (`100·FT-203/FT-202`, bloco
   script). Aqui as duas vazões são identificadas separadamente (FOPDT por par) e o refluxo
   é RECONSTRUÍDO delas — é a forma honesta de modelar a não-linearidade em vez de esconder
   num ganho linear médio.
2. **Os modelos valem fora dos degraus?** A janela em que o MPC estava em AUTO, entre as
   campanhas, tem as duas MVs se movendo ao mesmo tempo e não entrou em nenhum ajuste.
   Simular ali, em MIMO, com uma única condição inicial e ZERO parâmetro livre, é validação
   de verdade.

Uso:
    uv run python scripts/identificacao/valida.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from identifica import TD_LT201, TZ, _metricas, sim_ifopdt, sim_sopdt  # noqa: E402
from scipy.optimize import least_squares  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
CAMPANHAS = [
    ("FV-201", "mv_chns", OUT / "fv201_1627_1636.csv"),
    ("FV-202", "mv_fdou", OUT / "fv202_1643_1652.csv"),
]
VALIDACOES = [
    ("A", OUT / "valida_auto1.csv", "16:37-16:42 (entre as campanhas)"),
    ("B", OUT / "valida_auto2.csv", "16:52-17:01 (após a campanha 2)"),
]
VAZOES = {"tag_1487": "FT-202", "tag_1481": "FT-203"}
# Faixa de MV realmente excitada nas campanhas — fora dela o modelo é extrapolação, e
# métrica calculada ali mede a extrapolação, não o par identificado.
ENVELOPE = {"mv_chns": (48.64, 68.64), "mv_fdou": (32.86, 52.86)}


# --------------------------------------------------------------------------------------
def carrega(csv: Path) -> tuple[pd.DataFrame, np.ndarray, float, pd.Series]:
    """CSV do coleta.py + tags cruas casadas, reamostrado em grade uniforme de Ts."""
    d = pd.read_csv(csv, parse_dates=["ts"]).sort_values("ts").reset_index(drop=True)
    tags = pd.read_csv(csv.with_suffix(".tags.csv"), parse_dates=["ts"]).sort_values("ts").ffill()
    d = pd.merge_asof(d, tags, on="ts", direction="nearest").ffill().bfill()
    t = (d.ts - d.ts.iloc[0]).dt.total_seconds().to_numpy()
    ts = float(np.median(np.diff(t)))
    grade = np.arange(0.0, t[-1] + 1e-9, ts)
    reamostrado = pd.DataFrame(
        {c: np.interp(grade, t, d[c].to_numpy()) for c in d.columns if c != "ts"}
    )
    horario = pd.Series(pd.to_datetime(d.ts.iloc[0]) + pd.to_timedelta(grade, unit="s"))
    return reamostrado, grade, ts, horario.dt.tz_convert(TZ)


def fopdt(u: np.ndarray, y: np.ndarray, ts: float) -> dict[str, float]:
    """FOPDT (K, tau1, theta) + offset, pelo mesmo critério do identifica.py."""
    ud = u - u[:5].mean()

    def modelo(p):
        return p[3] + sim_sopdt(ud, ts, p[0], p[1], 0.0, p[2])

    k0 = float(np.polyfit(ud, y, 1)[0]) if np.ptp(ud) > 1e-3 else 0.1
    sol = least_squares(
        lambda p: modelo(p) - y,
        [float(np.clip(k0, -50, 50)), 10.0, 3.0, float(y[0])],
        bounds=([-100, 0, 0, y.min() - 100], [100, 300, 60, y.max() + 100]),
        x_scale="jac",
    )
    r2, rms = _metricas(y, modelo(sol.x))
    return {
        "K": float(sol.x[0]),
        "tau1": float(sol.x[1]),
        "theta": float(sol.x[2]),
        "r2": r2,
        "rms": rms,
    }


def resposta_selfreg(ud: np.ndarray, ts: float, m: dict[str, float]) -> np.ndarray:
    return sim_sopdt(ud, ts, m["K"], m["tau1"], m.get("tau2", 0.0), m["theta"])


def resposta_integrador(ud: np.ndarray, ts: float, ki: float, tau1: float) -> np.ndarray:
    """Parcela de rampa de uma MV, sem a constante de desbalanço (tratada fora)."""
    return sim_ifopdt(ud, ts, ki, tau1, TD_LT201, 0.0)


# --------------------------------------------------------------------------------------
# 1. Vazões e refluxo reconstruído
# --------------------------------------------------------------------------------------
def identifica_vazoes() -> dict[str, dict[str, dict[str, float]]]:
    modelos: dict[str, dict[str, dict[str, float]]] = {v: {} for v in VAZOES.values()}
    for _, mv, csv in CAMPANHAS:
        d, grade, ts, horario = carrega(csv)
        for tag, nome in VAZOES.items():
            modelos[nome][mv] = fopdt(d[mv].to_numpy(), d[tag].to_numpy(), ts)
    return modelos


def figura_refluxo(nome_mv: str, mv: str, csv: Path, vaz: dict, destino: Path) -> dict[str, float]:
    """Refluxo medido × (a) modelo linear direto e (b) razão das vazões modeladas."""
    d, grade, ts, horario = carrega(csv)
    u = d[mv].to_numpy()
    ud = u - u[:5].mean()
    f202 = d["tag_1487"].to_numpy()
    f203 = d["tag_1481"].to_numpy()
    prev202 = f202[:5].mean() + resposta_selfreg(ud, ts, vaz["FT-202"][mv])
    prev203 = f203[:5].mean() + resposta_selfreg(ud, ts, vaz["FT-203"][mv])
    refluxo = d["cv_74nu"].to_numpy()

    def desenvies(previsao: np.ndarray) -> np.ndarray:
        """Mesmo direito de bias para os dois modelos — é o que o MPC faz a cada ciclo."""
        return previsao + float(np.mean(refluxo - previsao))

    razao = desenvies(100.0 * prev203 / prev202)
    r2, rms = _metricas(refluxo, razao)

    direto = json.loads((OUT / f"modelos_{mv}.json").read_text())
    md = next(m for m in direto["modelos"] if m["cv"] == "cv_74nu")
    linear = desenvies(
        resposta_selfreg(
            ud, ts, {"K": md["K_eu"], "tau1": md["tau1"], "tau2": md["tau2"], "theta": md["theta"]}
        )
    )
    r2l, rmsl = _metricas(refluxo, linear)

    fig, eixos = plt.subplots(
        3, 1, figsize=(15.5, 11.0), sharex=True, gridspec_kw={"height_ratios": [1.2, 3, 1.2]}
    )
    fig.suptitle(f"Refluxo reconstruído das vazões - MV {nome_mv}", fontsize=14)
    eixos[0].plot(horario, f202, color="black", lw=1.0, label="FT-202 medido")
    eixos[0].plot(horario, prev202, color="tab:blue", ls="--", lw=1.4, label="FT-202 modelo")
    eixos[0].plot(horario, f203, color="0.45", lw=1.0, label="FT-203 medido")
    eixos[0].plot(horario, prev203, color="tab:green", ls="--", lw=1.4, label="FT-203 modelo")
    eixos[0].set_ylabel("vazões [m³/h]")
    eixos[0].legend(loc="upper right", ncol=2, fontsize=8)

    eixos[1].plot(horario, refluxo, color="black", lw=1.2, label="medido")
    eixos[1].plot(horario, linear, color="red", ls="--", lw=1.5, label="modelo linear (direto)")
    eixos[1].plot(
        horario, razao, color="tab:blue", ls="-.", lw=1.8, label="reconstruído FT-203/FT-202"
    )
    eixos[1].set_ylabel("Refluxo [%]")
    eixos[1].legend(loc="upper left")
    eixos[1].text(
        0.985,
        0.03,
        f"linear:        R²={r2l:.4f}  RMS={rmsl:.3f} %\n"
        f"reconstruído:  R²={r2:.4f}  RMS={rms:.3f} %",
        transform=eixos[1].transAxes,
        ha="right",
        va="bottom",
        fontsize=10,
        family="monospace",
        bbox={"facecolor": "white", "edgecolor": "0.5"},
    )

    eixos[2].plot(horario, refluxo - linear, color="red", lw=1.0, label="linear")
    eixos[2].plot(horario, refluxo - razao, color="tab:blue", lw=1.2, label="reconstruído")
    eixos[2].axhline(0.0, color="0.5", lw=0.8)
    eixos[2].set_ylabel("resíduo [%]")
    eixos[2].legend(loc="upper right", fontsize=8)
    eixos[2].set_xlabel(f"horário ({horario.iloc[0].strftime('%d/%m/%Y')})")
    for eixo in eixos:
        eixo.grid(alpha=0.25)
    eixos[2].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=TZ))
    fig.tight_layout()
    fig.savefig(destino, dpi=110)
    plt.close(fig)
    return {"r2_linear": r2l, "rms_linear": rmsl, "r2_razao": r2, "rms_razao": rms}


# --------------------------------------------------------------------------------------
# 2. Simulação MIMO fora-da-amostra
# --------------------------------------------------------------------------------------
def constante_nivel(modelos: dict[str, dict], campanha: Path, mv_ativa: str) -> float:
    """Constante c de `dLT/dt = Ki₁·u₁ + Ki₂·u₂ + c`, tirada da deriva ajustada.

    A `deriva` de cada campanha é o desbalanço no ponto de operação DAQUELA campanha; a
    constante absoluta é o que permite simular em outra janela sem refitar nada.
    """
    d, _, _, _ = carrega(campanha)
    m = modelos[mv_ativa]["cv_ij93"]
    u1 = float(d["mv_chns"].to_numpy()[:5].mean())
    u2 = float(d["mv_fdou"].to_numpy()[:5].mean())
    ki1 = modelos["mv_chns"]["cv_ij93"]["K_eu"]
    ki2 = modelos["mv_fdou"]["cv_ij93"]["K_eu"]
    return float(m["deriva"] - ki1 * u1 - ki2 * u2)


def simula_mimo(
    d: pd.DataFrame, ts: float, modelos: dict[str, dict], vaz: dict, c_nivel: float
) -> dict[str, np.ndarray]:
    u1, u2 = d["mv_chns"].to_numpy(), d["mv_fdou"].to_numpy()
    u1d, u2d = u1 - u1[0], u2 - u2[0]
    previsto: dict[str, np.ndarray] = {}

    # âncora do t0 pela média das 5 primeiras amostras (mesma regra do resto do estudo):
    # uma amostra só carregaria o ruído da medição para dentro do offset da janela inteira.
    def ancora(coluna: str) -> float:
        return float(d[coluna].to_numpy()[:5].mean())

    for cv in ("cv_74nu", "co_vw9g"):
        m1, m2 = modelos["mv_chns"][cv], modelos["mv_fdou"][cv]
        resp = resposta_selfreg(u1d, ts, _eu(m1)) + resposta_selfreg(u2d, ts, _eu(m2))
        previsto[cv] = ancora(cv) + resp
    m1, m2 = modelos["mv_chns"]["cv_ij93"], modelos["mv_fdou"]["cv_ij93"]
    rampa = resposta_integrador(u1d, ts, m1["K_eu"], m1["tau1"]) + resposta_integrador(
        u2d, ts, m2["K_eu"], m2["tau1"]
    )
    # desbalanço no ponto inicial da janela, das MVs absolutas — nenhum parâmetro novo
    desbalanco = m1["K_eu"] * u1[0] + m2["K_eu"] * u2[0] + c_nivel
    previsto["cv_ij93"] = ancora("cv_ij93") + rampa + desbalanco * ts * np.arange(u1.size)
    # refluxo pela razão das vazões modeladas (as duas MVs somadas em cada vazão)
    f202 = (
        ancora("tag_1487")
        + resposta_selfreg(u1d, ts, vaz["FT-202"]["mv_chns"])
        + resposta_selfreg(u2d, ts, vaz["FT-202"]["mv_fdou"])
    )
    f203 = (
        ancora("tag_1481")
        + resposta_selfreg(u1d, ts, vaz["FT-203"]["mv_chns"])
        + resposta_selfreg(u2d, ts, vaz["FT-203"]["mv_fdou"])
    )
    # Piso físico no denominador: o modelo de vazão é linear e, extrapolado para fora da
    # faixa identificada, prevê FT-202 -> 0 e faz a razão explodir. Onde o piso morde, a
    # reconstrução está fora do domínio de validade — e o gráfico tem que mostrar isso.
    previsto["cv_74nu_razao"] = 100.0 * f203 / np.maximum(f202, 0.2)
    return previsto


def _eu(m: dict) -> dict[str, float]:
    return {"K": m["K_eu"], "tau1": m["tau1"], "tau2": m["tau2"], "theta": m["theta"]}


def figura_validacao(
    horario: pd.Series, d: pd.DataFrame, previsto: dict, titulo: str, destino: Path
) -> dict[str, dict[str, float]]:
    """Figura + métricas na janela inteira E só dentro do envelope identificado.

    Fora do envelope o modelo é extrapolado: julgar o par por ali mede a extrapolação, não
    o modelo. Os dois números vão para o relatório, com o trecho extrapolado sombreado.
    """
    rotulos = {
        "cv_ij93": ("LT-201", "%"),
        "cv_74nu": ("Refluxo", "%"),
        "co_vw9g": ("FT-204", "m³/h"),
    }
    u1, u2 = d["mv_chns"].to_numpy(), d["mv_fdou"].to_numpy()
    dentro = (
        (u1 >= ENVELOPE["mv_chns"][0])
        & (u1 <= ENVELOPE["mv_chns"][1])
        & (u2 >= ENVELOPE["mv_fdou"][0])
        & (u2 <= ENVELOPE["mv_fdou"][1])
    )
    fig, eixos = plt.subplots(4, 1, figsize=(15.5, 13.0), sharex=True)
    pct = 100.0 * dentro.mean()
    fig.suptitle(
        f"Validação fora-da-amostra (MPC em AUTO) - {titulo}\n"
        f"{pct:.0f}% das amostras dentro do envelope identificado "
        f"(FV-201 {ENVELOPE['mv_chns'][0]:.1f}-{ENVELOPE['mv_chns'][1]:.1f} %, "
        f"FV-202 {ENVELOPE['mv_fdou'][0]:.1f}-{ENVELOPE['mv_fdou'][1]:.1f} %)",
        fontsize=13,
    )
    eixos[0].plot(horario, u1, color="#1f4e79", lw=1.2, label="FV-201")
    eixos[0].plot(horario, u2, color="tab:orange", lw=1.2, label="FV-202")
    for lim in ENVELOPE["mv_chns"]:
        eixos[0].axhline(lim, color="#1f4e79", ls=":", lw=0.9)
    for lim in ENVELOPE["mv_fdou"]:
        eixos[0].axhline(lim, color="tab:orange", ls=":", lw=0.9)
    eixos[0].set_ylabel("MV [%]")
    eixos[0].legend(loc="upper right", fontsize=8)

    metricas: dict[str, dict[str, float]] = {}

    def anota(cv: str, y: np.ndarray, prev: np.ndarray) -> tuple[float, float]:
        r2, rms = _metricas(y, prev)
        if dentro.sum() > 10:
            _, rms_in = _metricas(y[dentro], prev[dentro])
        else:
            rms_in = float("nan")
        metricas[cv] = {"r2": r2, "rms": rms, "rms_dentro_envelope": rms_in}
        return rms, rms_in

    for eixo, (cv, (nome, eu)) in zip(eixos[1:], rotulos.items(), strict=True):
        y = d[cv].to_numpy()
        rms, rms_in = anota(cv, y, previsto[cv])
        eixo.plot(horario, y, color="black", lw=1.2, label="medido")
        eixo.plot(horario, previsto[cv], color="red", ls="--", lw=1.6, label="modelos (MIMO)")
        texto = f"RMS={rms:8.3f} {eu}   (no envelope: {rms_in:.3f})"
        if cv == "cv_74nu":
            rmsr, rmsr_in = anota("cv_74nu_razao", y, previsto["cv_74nu_razao"])
            eixo.plot(
                horario,
                previsto["cv_74nu_razao"],
                color="tab:blue",
                ls="-.",
                lw=1.8,
                label="reconstruído FT-203/FT-202",
            )
            texto = (
                f"linear:        {texto}\n"
                f"reconstruído:  RMS={rmsr:8.3f} {eu}   (no envelope: {rmsr_in:.3f})"
            )
            # A escala segue o medido + o modelo linear; a reconstrução extrapolada estoura
            # por ordens de grandeza e achataria tudo. Quando estoura, diz onde foi parar.
            lo = min(y.min(), float(np.nanmin(previsto[cv]))) - 5
            hi = max(y.max(), float(np.nanmax(previsto[cv]))) + 5
            eixo.set_ylim(lo, hi)
            razao = previsto["cv_74nu_razao"]
            if razao.max() > hi or razao.min() < lo:
                eixo.text(
                    0.5,
                    0.93,
                    f"reconstruído sai de escala no trecho extrapolado "
                    f"(mín {razao.min():.0f} %, máx {razao.max():.0f} %)",
                    transform=eixo.transAxes,
                    ha="center",
                    fontsize=9,
                    color="tab:blue",
                )
        eixo.set_ylabel(f"{nome} [{eu}]")
        eixo.legend(loc="upper left", fontsize=8)
        eixo.text(
            0.995,
            0.04,
            texto,
            transform=eixo.transAxes,
            ha="right",
            fontsize=9,
            family="monospace",
            bbox={"facecolor": "white", "edgecolor": "0.5"},
        )
    for eixo in eixos:
        eixo.grid(alpha=0.25)
        eixo.fill_between(
            horario,
            0,
            1,
            where=~dentro,
            transform=eixo.get_xaxis_transform(),
            color="0.85",
            alpha=0.5,
            zorder=0,
            label=None,
        )
    eixos[-1].set_xlabel(
        f"horário ({horario.iloc[0].strftime('%d/%m/%Y')})  — cinza: fora do envelope"
    )
    eixos[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=TZ))
    fig.tight_layout()
    fig.savefig(destino, dpi=110)
    plt.close(fig)
    return metricas


def nivel_desbalanco_reajustado(
    d: pd.DataFrame, ts: float, modelos: dict[str, dict]
) -> tuple[float, float, float]:
    """Refaz SÓ a constante de desbalanço na janela de validação (1 parâmetro, fechado).

    Separa o que é erro de DINÂMICA (Ki, tau) do que é erro de PONTO DE BALANÇO — este
    último o MPC corrige sozinho a cada ciclo pela atualização de bias.
    """
    u1, u2 = d["mv_chns"].to_numpy(), d["mv_fdou"].to_numpy()
    m1, m2 = modelos["mv_chns"]["cv_ij93"], modelos["mv_fdou"]["cv_ij93"]
    rampa = resposta_integrador(u1 - u1[0], ts, m1["K_eu"], m1["tau1"]) + resposta_integrador(
        u2 - u2[0], ts, m2["K_eu"], m2["tau1"]
    )
    y = d["cv_ij93"].to_numpy()
    base = y[0] + rampa
    t_ramp = ts * np.arange(y.size)
    taxa = float(np.sum((y - base) * t_ramp) / np.sum(t_ramp**2))
    _, rms = _metricas(y, base + taxa * t_ramp)
    return taxa, rms, float(m1["K_eu"] * u1[0] + m2["K_eu"] * u2[0] + 0.0)


# --------------------------------------------------------------------------------------
def main() -> None:
    modelos = {
        mv: {m["cv"]: m for m in json.loads((OUT / f"modelos_{mv}.json").read_text())["modelos"]}
        for mv in ("mv_chns", "mv_fdou")
    }

    print("== vazões (FOPDT, EU) — base da reconstrução do refluxo")
    vaz = identifica_vazoes()
    for nome, por_mv in vaz.items():
        for mv, m in por_mv.items():
            print(
                f"  {mv} -> {nome}: K={m['K']:+.5f} m³/h/%  tau={m['tau1']:5.2f} s  "
                f"theta={m['theta']:4.2f} s  R²={m['r2']:.4f}  RMS={m['rms']:.4f}"
            )

    print("\n== refluxo: modelo linear × reconstruído da razão")
    for nome_mv, mv, csv in CAMPANHAS:
        r = figura_refluxo(nome_mv, mv, csv, vaz, OUT / f"refluxo_reconstruido_{nome_mv}.png")
        print(
            f"  {nome_mv}: linear R²={r['r2_linear']:.4f} RMS={r['rms_linear']:.3f} %  |  "
            f"razão R²={r['r2_razao']:.4f} RMS={r['rms_razao']:.3f} %"
        )

    c1 = constante_nivel(modelos, CAMPANHAS[0][2], "mv_chns")
    c2 = constante_nivel(modelos, CAMPANHAS[1][2], "mv_fdou")
    print(f"\n== constante de desbalanço do nível: c(camp.1)={c1:+.5f}  c(camp.2)={c2:+.5f} %/s")

    print("\n== validação MIMO fora-da-amostra (zero parâmetro livre além do t0)")
    metricas: dict[str, dict] = {}
    for rotulo, csv, titulo in VALIDACOES:
        d, grade, ts, horario = carrega(csv)
        previsto = simula_mimo(d, ts, modelos, vaz, c1)
        met = figura_validacao(horario, d, previsto, titulo, OUT / f"validacao_{rotulo}.png")
        print(f"  janela {rotulo} ({grade[-1] / 60:.1f} min):")
        for cv, m in met.items():
            print(
                f"      {cv:16s} RMS={m['rms']:9.3f}   "
                f"no envelope={m['rms_dentro_envelope']:7.3f}   R²={m['r2']:+.4f}"
            )
        # nível: reajusta SÓ a constante de desbalanço (1 escalar) e devolve o c implícito
        taxa, rms_refit, termo_mv = nivel_desbalanco_reajustado(d, ts, modelos)
        c_implicito = taxa - termo_mv
        met["_nivel_c_reajustado"] = {
            "taxa_pct_s": taxa,
            "rms": rms_refit,
            "c_implicito": c_implicito,
        }
        # mesma simulação com a constante da OUTRA campanha: mostra quanto do erro é a
        # escolha de c, e não o modelo
        prev_c2 = simula_mimo(d, ts, modelos, vaz, c2)
        _, rms_c2 = _metricas(d["cv_ij93"].to_numpy(), prev_c2["cv_ij93"])
        met["_nivel_com_c2"] = {"rms": rms_c2}
        metricas[rotulo] = met
        print(
            f"      nível: RMS com c(camp.2)={rms_c2:.3f} %;  reajustando só a constante "
            f"({taxa * 60:+.3f} %/min) RMS={rms_refit:.3f} %;  c implícito={c_implicito:+.5f} %/s"
        )

    (OUT / "validacao.json").write_text(
        json.dumps(
            {"vazoes": vaz, "c_nivel": {"campanha1": c1, "campanha2": c2}, "metricas": metricas},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
