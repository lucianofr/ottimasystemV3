"""Identificação dos pares MV->CV a partir dos degraus em malha aberta (MPC em MAN).

Estruturas idênticas às que o bloco MPC aceita (`flowgraph/mpc_config.py`):
  - selfreg     SOPDT  G(s) = K·e^(-θs) / ((τ1·s+1)(τ2·s+1))
  - integrating IFOPDT G(s) = Ki·e^(-θs) / (s·(τ1·s+1))
FOPDT é o SOPDT com τ2 = 0 — ajustado junto, para comparação.

O modelo é simulado com o SINAL DE MV MEDIDO (não com um degrau ideal), partindo do
começo da janela; o que se compara no gráfico é medido × previsto ao longo de toda a
campanha, mais o resíduo.

Uso:
    uv run python scripts/identificacao/identifica.py \
        --csv scripts/identificacao/out/fv201_1627_1636.csv \
        --marcas scripts/identificacao/out/marcas_fv201.json --mv mv_chns
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import least_squares  # noqa: E402

TZ = ZoneInfo("America/Sao_Paulo")
TD_LT201 = 23.0  # s — único parâmetro FIXADO (decisão do usuário)

# span de cada variável (mpc_config: K/Ki são normalizados por span de linha/coluna)
SPAN = {"mv_chns": 100.0, "mv_fdou": 100.0, "cv_ij93": 100.0, "cv_74nu": 100.0, "co_vw9g": 20.0}
NOME = {
    "mv_chns": "FV-201",
    "mv_fdou": "FV-202",
    "cv_ij93": "LT-201",
    "cv_74nu": "Refluxo",
    "co_vw9g": "FT-204",
}
EU = {"mv_chns": "%", "mv_fdou": "%", "cv_ij93": "%", "cv_74nu": "%", "co_vw9g": "m3/h"}
KIND = {"cv_ij93": "integrating", "cv_74nu": "selfreg", "co_vw9g": "selfreg"}


# --------------------------------------------------------------------------------------
# Simulação
# --------------------------------------------------------------------------------------
def atrasa(u: np.ndarray, ts: float, theta: float) -> np.ndarray:
    """Atraso fracionário por interpolação linear; antes da janela vale u[0]."""
    if theta <= 0:
        return u
    t = np.arange(u.size) * ts
    return np.interp(t - theta, t, u, left=u[0])


def _lag(u: np.ndarray, ts: float, tau: float) -> np.ndarray:
    """1a ordem discretizado exato (ZOH): y[k+1] = a·y[k] + (1-a)·u[k]."""
    if tau <= 1e-6:
        return u
    a = float(np.exp(-ts / tau))
    y = np.empty_like(u)
    y[0] = u[0]
    for k in range(u.size - 1):
        y[k + 1] = a * y[k] + (1.0 - a) * u[k]
    return y


def sim_sopdt(u: np.ndarray, ts: float, K: float, tau1: float, tau2: float, theta: float):
    """Resposta em desvio de K·e^(-θs)/((τ1 s+1)(τ2 s+1)) ao sinal u (já em desvio)."""
    return K * _lag(_lag(atrasa(u, ts, theta), ts, tau1), ts, tau2)


def sim_ifopdt(u: np.ndarray, ts: float, Ki: float, tau1: float, theta: float, deriva: float):
    """Ki·e^(-θs)/(s(τ1 s+1)) + deriva constante (desbalanço do ponto de operação)."""
    x = _lag(atrasa(u, ts, theta), ts, tau1)
    return np.cumsum(np.concatenate(([0.0], (Ki * x[:-1] + deriva) * ts)))


# --------------------------------------------------------------------------------------
# Ajuste
# --------------------------------------------------------------------------------------
@dataclass
class Modelo:
    mv: str
    cv: str
    kind: str
    estrutura: str
    # Unidades do config do MPC (mpc_config.py): K/Ki normalizados por span —
    # K_EU = K × span_CV / span_MV, logo K = K_EU × span_MV / span_CV.
    K: float  # %/% (selfreg) ou %/(%·s) (integrating)
    K_eu: float  # ganho em EU da CV por % de MV (o que aparece no gráfico)
    tau1: float
    tau2: float
    theta: float
    theta_fixo: bool
    deriva: float  # só integrating: %/s residual do ponto de operação
    r2: float
    rms: float
    sigma_K: float = 0.0  # desvio-padrão do ganho (EU/%), da covariância do ajuste
    sigma_tau1: float = 0.0
    sigma_theta: float = 0.0

    def params_mpc(self) -> dict[str, float]:
        if self.kind == "integrating":
            return {"Ki": self.K, "tau1": self.tau1, "theta": self.theta}
        return {"K": self.K, "tau1": self.tau1, "tau2": self.tau2, "theta": self.theta}


def _sigmas(sol, n: int) -> np.ndarray:
    """Desvio-padrão dos parâmetros por J^T·J (subestima com resíduo autocorrelacionado).

    Pseudo-inversa porque parâmetro no limite (tau1 -> 0) deixa J^T·J singular — ali o
    número sai ~0, que é a leitura correta: aquele parâmetro não está sendo estimado.
    """
    res = float(np.sum(sol.fun**2))
    dof = max(n - sol.x.size, 1)
    cov = np.linalg.pinv(sol.jac.T @ sol.jac) * res / dof
    return np.sqrt(np.abs(np.diag(cov)))


def _metricas(y: np.ndarray, yhat: np.ndarray) -> tuple[float, float]:
    res = y - yhat
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(res**2)) / sst if sst > 0 else float("nan")
    return r2, float(np.sqrt(np.mean(res**2)))


def ajusta(
    t: np.ndarray, u: np.ndarray, y: np.ndarray, ts: float, mv: str, cv: str
) -> tuple[Modelo, np.ndarray]:
    """Ajusta o par por mínimos quadrados não-linear sobre a janela inteira."""
    u0 = float(u[:5].mean())
    ud = u - u0
    kind = KIND[cv]
    amplitude = max(float(np.ptp(ud)), 1e-6)
    escala_y = max(float(np.ptp(y)), 1e-6)

    if kind == "integrating":
        # p = [Ki, tau1, deriva, y0]; theta FIXO em 23 s.
        def modelo(p):
            return p[3] + sim_ifopdt(ud, ts, p[0], p[1], TD_LT201, p[2])

        # chute do Ki: regressão da derivada do sinal medido contra a MV em desvio
        dydt = np.gradient(y, ts)
        ki0 = float(np.polyfit(ud, dydt, 1)[0]) if amplitude > 1e-3 else 1e-4
        p0 = [float(np.clip(ki0, -0.5, 0.5)), 20.0, 0.0, float(y[0])]
        lo = [-1.0, 0.0, -0.05, y.min() - escala_y]
        hi = [1.0, 400.0, 0.05, y.max() + escala_y]
        sol = least_squares(lambda p: modelo(p) - y, p0, bounds=(lo, hi), x_scale="jac")
        yhat = modelo(sol.x)
        r2, rms = _metricas(y, yhat)
        sig = _sigmas(sol, y.size)
        ganho_eu = float(sol.x[0])
        return (
            Modelo(
                mv=mv,
                cv=cv,
                kind=kind,
                estrutura="IFOPDT" if sol.x[1] > 1.0 else "IOPDT",
                K=ganho_eu * SPAN[mv] / SPAN[cv],
                K_eu=ganho_eu,
                tau1=float(sol.x[1]),
                tau2=0.0,
                theta=TD_LT201,
                theta_fixo=True,
                deriva=float(sol.x[2]),
                r2=r2,
                rms=rms,
                sigma_K=float(sig[0]),
                sigma_tau1=float(sig[1]),
            ),
            yhat,
        )

    # selfreg: ajusta FOPDT e depois SOPDT partindo dele (warm start: o SOPDT contém o
    # FOPDT, então sem partida quente ele às vezes para num mínimo local pior). Fica com o
    # de maior R².
    melhor: tuple[Modelo, np.ndarray] | None = None
    p_fopdt: list[float] | None = None
    for estrutura, tau2_livre in (("FOPDT", False), ("SOPDT", True)):

        def modelo(p, tau2_livre=tau2_livre):
            tau2 = p[2] if tau2_livre else 0.0
            return p[4] + sim_sopdt(ud, ts, p[0], p[1], tau2, p[3])

        if p_fopdt is not None:
            # metade do lag do FOPDT em cada polo, e o atraso encurtado para dar espaço ao
            # 2o polo — a forma em S que o FOPDT não consegue.
            p0 = [p_fopdt[0], p_fopdt[1] / 2, max(p_fopdt[1] / 2, 0.5), p_fopdt[3], p_fopdt[4]]
        else:
            # chute do ganho: regressão y × u sobre a janela (robusto ao fim do degrau)
            k0 = float(np.polyfit(ud, y, 1)[0]) if amplitude > 1e-3 else 0.1
            p0 = [float(np.clip(k0, -50.0, 50.0)), 10.0, 0.0, 3.0, float(y[0])]
        lo = [-100.0, 0.0, 0.0, 0.0, y.min() - escala_y]
        hi = [100.0, 300.0, 300.0 if tau2_livre else 1e-9, 60.0, y.max() + escala_y]
        p0 = [float(np.clip(v, lo[i], hi[i])) for i, v in enumerate(p0)]
        sol = least_squares(lambda p: modelo(p) - y, p0, bounds=(lo, hi), x_scale="jac")
        yhat = modelo(sol.x)
        r2, rms = _metricas(y, yhat)
        sig = _sigmas(sol, y.size)
        if not tau2_livre:
            p_fopdt = [float(v) for v in sol.x]
        cand = Modelo(
            mv=mv,
            cv=cv,
            kind=kind,
            estrutura=estrutura,
            K=float(sol.x[0]) * SPAN[mv] / SPAN[cv],
            K_eu=float(sol.x[0]),
            tau1=float(sol.x[1]),
            tau2=float(sol.x[2]) if tau2_livre else 0.0,
            theta=float(sol.x[3]),
            theta_fixo=False,
            deriva=0.0,
            r2=r2,
            rms=rms,
            sigma_K=float(sig[0]),
            sigma_tau1=float(sig[1]),
            sigma_theta=float(sig[3]),
        )
        if melhor is None or cand.r2 > melhor[0].r2 + 1e-4:
            melhor = (cand, yhat)
    assert melhor is not None
    return melhor


# --------------------------------------------------------------------------------------
# Gráfico
# --------------------------------------------------------------------------------------
def figura(
    ts_dt: pd.Series,
    u: np.ndarray,
    y: np.ndarray,
    yhat: np.ndarray,
    m: Modelo,
    n: int,
    destino: Path,
    marcas: list[pd.Timestamp],
) -> None:
    fig, eixos = plt.subplots(
        3, 1, figsize=(15.5, 12.0), sharex=True, gridspec_kw={"height_ratios": [1, 3, 1.2]}
    )
    fig.suptitle(f"Modelo {n} - {NOME[m.mv]} -> {NOME[m.cv]}", fontsize=14)

    eixos[0].plot(ts_dt, u, color="#1f4e79", lw=1.2)
    eixos[0].set_ylabel(f"MV\n{NOME[m.mv]} [{EU[m.mv]}]")

    eixos[1].plot(ts_dt, y, color="black", lw=1.2, label="medido")
    eixos[1].plot(ts_dt, yhat, color="red", lw=1.6, ls="--", label=f"modelo {n}")
    eixos[1].set_ylabel(f"CV\n{NOME[m.cv]} [{EU[m.cv]}]")
    eixos[1].legend(loc="upper left")
    if m.kind == "integrating":
        txt = (
            f"{m.estrutura}  Ki={m.K_eu:+.7f} {EU[m.cv]}/(%·s)  tau={m.tau1:.1f} s  "
            f"td={m.theta:.0f} s (fixo)\nR²={m.r2:.4f}   RMS={m.rms:.3f} {EU[m.cv]}\n"
            f"deriva={m.deriva * 60:+.3f} %/min (desbalanço do ponto de operação — NÃO vai\n"
            f"no par exportado; é o que o bias do MPC corrige a cada ciclo)"
        )
    else:
        tau_txt = f"tau1={m.tau1:.1f} s" + (f"  tau2={m.tau2:.1f} s" if m.tau2 > 0 else "")
        txt = (
            f"{m.estrutura}  K={m.K_eu:+.4f} {EU[m.cv]}/%  {tau_txt}  td={m.theta:.1f} s\n"
            f"R²={m.r2:.4f}   RMS={m.rms:.4f} {EU[m.cv]}"
        )
    eixos[1].text(
        0.985,
        0.03 if m.K_eu > 0 else 0.97,
        txt,
        transform=eixos[1].transAxes,
        ha="right",
        va="bottom" if m.K_eu > 0 else "top",
        fontsize=10,
        bbox={"facecolor": "white", "edgecolor": "0.5"},
    )

    eixos[2].plot(ts_dt, y - yhat, color="red", lw=1.0)
    eixos[2].axhline(0.0, color="0.5", lw=0.8)
    eixos[2].set_ylabel(f"resíduo\nmedido - modelo [{EU[m.cv]}]")
    eixos[2].set_xlabel(f"horário ({ts_dt.iloc[0].strftime('%d/%m/%Y')})")

    for eixo in eixos:
        eixo.grid(alpha=0.25)
        for marca in marcas:
            eixo.axvline(marca, color="0.35", ls=":", lw=1.0)
    eixos[2].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=TZ))
    fig.tight_layout()
    fig.savefig(destino, dpi=110)
    plt.close(fig)


def ganhos_por_degrau(
    grade: np.ndarray, u: np.ndarray, d: pd.DataFrame, t: np.ndarray, ts: float, cvs: list[str]
) -> list[dict[str, float | str]]:
    """Ganho incremental de CADA degrau, direto do dado — mede a (não-)linearidade.

    selfreg: ΔY entre médias dos 30 s finais de cada patamar / ΔU.
    integrating: Δ(taxa) entre as inclinações dos 60 s finais de cada patamar / ΔU.
    """
    bordas = [k for k in range(1, u.size) if abs(u[k] - u[k - 1]) > 1.0]
    fronteiras = [0, *bordas, u.size]
    trechos = [(fronteiras[i], fronteiras[i + 1]) for i in range(len(fronteiras) - 1)]
    n30, n60 = int(30 / ts), int(60 / ts)

    def cauda(fim: int, n: int) -> slice:
        """Últimas n amostras antes de `fim`, sem estourar o início da janela."""
        return slice(max(fim - n, 0), fim)

    linhas: list[dict[str, float | str]] = []
    for (_, ib), (_, jb) in zip(trechos, trechos[1:], strict=False):
        du = float(np.mean(u[cauda(jb, n30)]) - np.mean(u[cauda(ib, n30)]))
        if abs(du) < 1.0:
            continue
        for cv in cvs:
            y = np.interp(grade, t, d[cv].to_numpy())
            if KIND[cv] == "integrating":
                a_ini, d_ini = cauda(ib, n60), cauda(jb, n60)
                if ib - a_ini.start < 5 or jb - d_ini.start < 5:
                    continue  # patamar curto demais para estimar inclinação
                antes = float(np.polyfit(grade[a_ini], y[a_ini], 1)[0])
                depois = float(np.polyfit(grade[d_ini], y[d_ini], 1)[0])
                ganho = (depois - antes) / du
            else:
                ganho = float(np.mean(y[cauda(jb, n30)]) - np.mean(y[cauda(ib, n30)])) / du
            linhas.append(
                {
                    "cv": cv,
                    "u_de": round(float(np.mean(u[cauda(ib, n30)])), 2),
                    "u_para": round(float(np.mean(u[cauda(jb, n30)])), 2),
                    "delta_u": round(du, 2),
                    "ganho_eu_por_pct": ganho,
                }
            )
    return linhas


# --------------------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--marcas", required=True)
    p.add_argument("--mv", required=True, choices=["mv_chns", "mv_fdou"])
    p.add_argument("--cvs", default="cv_ij93,cv_74nu,co_vw9g")
    p.add_argument("--n0", type=int, default=1, help="número do primeiro modelo no relatório")
    p.add_argument("--out-dir", default="scripts/identificacao/out")
    a = p.parse_args()

    d = pd.read_csv(a.csv, parse_dates=["ts"])
    d = d.sort_values("ts").reset_index(drop=True)
    t = (d.ts - d.ts.iloc[0]).dt.total_seconds().to_numpy()
    ts = float(np.median(np.diff(t)))
    # grade uniforme: o jitter da varredura é <10 ms, mas o modelo é simulado em passo fixo
    grade = np.arange(0.0, t[-1] + 1e-9, ts)
    inicio = pd.to_datetime(d.ts.iloc[0])
    horario = pd.Series(inicio + pd.to_timedelta(grade, unit="s")).dt.tz_convert(TZ)
    u = np.interp(grade, t, d[a.mv].to_numpy())

    marcas_raw = json.loads(Path(a.marcas).read_text())
    t_ini, t_fim = horario.iloc[0], horario.iloc[-1]
    marcas = [
        marca
        for k, v in marcas_raw.items()
        if k.endswith("_cmd") and t_ini <= (marca := pd.Timestamp(v).tz_convert(TZ)) <= t_fim
    ]

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    resultados: list[Modelo] = []
    for i, cv in enumerate(a.cvs.split(","), start=a.n0):
        y = np.interp(grade, t, d[cv].to_numpy())
        m, yhat = ajusta(grade, u, y, ts, a.mv, cv)
        resultados.append(m)
        figura(horario, u, y, yhat, m, i, out / f"modelo{i}_{NOME[m.mv]}_{NOME[cv]}.png", marcas)
        print(
            f"Modelo {i}  {NOME[a.mv]:7s} -> {NOME[cv]:8s}  {m.estrutura:6s} "
            f"K={m.K_eu:+.6f} {EU[cv]}/%{'·s' if m.kind == 'integrating' else '':3s} "
            f"tau1={m.tau1:7.2f} tau2={m.tau2:6.2f} td={m.theta:5.1f}"
            f"{' (fixo)' if m.theta_fixo else '      '}  R²={m.r2:.4f}  RMS={m.rms:.4f}"
        )

    cvs = a.cvs.split(",")
    incrementais = ganhos_por_degrau(grade, u, d, t, ts, cvs)
    print("\nganhos incrementais medidos (linearidade):")
    for linha in incrementais:
        print(
            f"  {NOME[a.mv]} {linha['u_de']:6.2f} -> {linha['u_para']:6.2f} "
            f"({linha['delta_u']:+6.2f} %)  {NOME[str(linha['cv'])]:8s} "
            f"K={float(linha['ganho_eu_por_pct']):+.6f} {EU[str(linha['cv'])]}/%"
            f"{'·s' if KIND[str(linha['cv'])] == 'integrating' else ''}"
        )

    destino = out / f"modelos_{a.mv}.json"
    destino.write_text(
        json.dumps(
            {
                "janela": [str(d.ts.iloc[0]), str(d.ts.iloc[-1])],
                "ts_s": ts,
                "mv": a.mv,
                "modelos": [asdict(m) | {"params_mpc": m.params_mpc()} for m in resultados],
                "ganhos_incrementais": incrementais,
            },
            indent=2,
        )
    )
    print(f"-> {destino}")


if __name__ == "__main__":
    main()
