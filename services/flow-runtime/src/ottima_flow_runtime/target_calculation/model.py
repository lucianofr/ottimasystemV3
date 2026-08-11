"""Modelo de regime permanente do SSTO: `G`, `Gd` e a base de predição (ADR-027 §3/§4).

**Não existe segundo modelo de ganho.** Cada entrada de `G`/`Gd` é o ganho do `PairSS` JÁ
DISCRETIZADO que o controlador monta (`mpc.discretize`), nunca uma segunda leitura de
`params`: se um dia a discretização mudar, o LP muda junto por construção.

Duas leituras de "ganho", uma por `kind` de linha (ADR-013):

- **`selfreg` (SOPDT)** — ganho DC `c·(I − a)⁻¹·b`, que para a forma do `discretize_sopdt`
  vale exatamente `K`. A linha entra no LP como nível: `ΔCVˢˢ = G·ΔMV + Gd·ΔDV`.
- **`integrating` (IOPDT)** — não tem ganho estático finito (`a = 1`, `(I − a)` singular):
  o que existe é a **taxa de rampa** `Ki` [EU/(EU·s)], recuperada como `(c·b)/Ts`. A linha
  entra no LP como condição de **taxa nula em regime** (ADR-027 §4), nunca como nível.

O tempo morto não participa: ele é shift register na entrada do par (fora de `(a, b, c)`) e
não altera regime permanente.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from ottima_core.flowgraph import MpcConfig, RowKind
from ottima_flow_runtime.mpc.discretize import PairSS, discretize_iopdt, discretize_sopdt


def pair_steady_state_gain(
    pair: PairSS, *, direct_gain: float | None, kind: RowKind, ts: float
) -> float:
    """Ganho de regime permanente de UM par, na leitura que o `kind` da linha exige.

    `direct_gain` cobre o caso degenerado `n == 0` (os dois estágios do SOPDT em passagem
    direta): o `PairSS` não representa ganho puro (`y = c@x = 0` sempre), então o `K` vem
    por fora — mesma convenção de `PairInit.direct_gain` no builder.
    """
    if pair.a.shape[0] == 0:
        return float(direct_gain or 0.0)
    if kind == "integrating":
        # `a = 1` torna `(I − a)` singular: o integrador não converge. A taxa de rampa por
        # amostra é `c·b`; por segundo, `(c·b)/Ts` — que devolve o `Ki` do config.
        return float((pair.c @ pair.b)[0, 0]) / ts
    identity = np.eye(pair.a.shape[0])
    return float((pair.c @ np.linalg.solve(identity - pair.a, pair.b))[0, 0])


@dataclass(frozen=True, slots=True, eq=False)
class SteadyStateModel:
    """`G`/`Gd` + metadados de ordem (ADR-027 §3).

    `row_ids`: CVs e depois Restrições — a MESMA ordem de `BuiltMpc.prediction_rows`, para
    que bias e medida cheguem indexados igual dos dois lados.

    `eq=False`: os campos carregam `np.ndarray` (mesmo motivo do `PairSS`).
    """

    row_ids: tuple[str, ...]
    row_kind: dict[str, RowKind]
    mv_ids: tuple[str, ...]
    dv_ids: tuple[str, ...]
    g: np.ndarray
    """(n_rows × n_mv) — ganho por par linha×MV, na leitura do `kind` da linha."""
    gd: np.ndarray
    """(n_rows × n_dv) — idem para as colunas DV. DV **nunca** é variável de decisão."""
    mv_operating_point: tuple[float, ...]
    dv_operating_point: tuple[float, ...]

    def base(
        self, *, u: Mapping[str, float], d: Mapping[str, float], bias: Mapping[str, float]
    ) -> np.ndarray:
        """Regime permanente previsto com as entradas ATUAIS congeladas (o "de onde parte").

        Linha `selfreg`: `G·(u − op) + Gd·(d − op) + bias` — o bias é a mesma correção DMC
        que o worker calcula (`y_medido − C·x`), então o alvo do LP nasce ancorado na medida.

        Linha `integrating`: a mesma combinação SEM o bias — ali o valor é uma TAXA
        [EU/s], e o bias corrige NÍVEL [EU]. Somá-los seria erro de unidade.
        """
        u_dev = np.array([u[mv_id] for mv_id in self.mv_ids], dtype=float) - np.array(
            self.mv_operating_point, dtype=float
        )
        d_dev = np.array([d[dv_id] for dv_id in self.dv_ids], dtype=float) - np.array(
            self.dv_operating_point, dtype=float
        )
        value = self.g @ u_dev + self.gd @ d_dev
        level = np.array(
            [
                bias[row_id] if self.row_kind[row_id] == "selfreg" else 0.0
                for row_id in self.row_ids
            ],
            dtype=float,
        )
        return value + level


def build_steady_state_model(config: MpcConfig, ts_mpc: float) -> SteadyStateModel:
    """Monta `G`/`Gd` a partir da matriz `models` do config, via `PairSS` (ADR-027 §3)."""
    rows = [*config.variables.cvs, *config.variables.constraints]
    row_ids = tuple(var.id for var in rows)
    row_kind: dict[str, RowKind] = {var.id: var.kind for var in rows}
    mv_ids = tuple(mv.id for mv in config.variables.mvs)
    dv_ids = tuple(dv.id for dv in config.variables.dvs)

    g = np.zeros((len(row_ids), len(mv_ids)))
    gd = np.zeros((len(row_ids), len(dv_ids)))
    mv_index = {mv_id: j for j, mv_id in enumerate(mv_ids)}
    dv_index = {dv_id: j for j, dv_id in enumerate(dv_ids)}

    for i, row_id in enumerate(row_ids):
        kind = row_kind[row_id]
        for col_id, pair_cfg in config.models.get(row_id, {}).items():
            if not pair_cfg.enabled:
                continue
            params = pair_cfg.params
            if kind == "selfreg":
                pair = discretize_sopdt(
                    params["K"], params["tau1"], params["tau2"], params["theta"], ts_mpc
                )
                direct_gain = params["K"]
            else:
                pair = discretize_iopdt(params["Ki"], params["theta"], ts_mpc)
                direct_gain = None
            gain = pair_steady_state_gain(pair, direct_gain=direct_gain, kind=kind, ts=ts_mpc)
            if col_id in mv_index:
                g[i, mv_index[col_id]] = gain
            elif col_id in dv_index:
                gd[i, dv_index[col_id]] = gain

    return SteadyStateModel(
        row_ids=row_ids,
        row_kind=row_kind,
        mv_ids=mv_ids,
        dv_ids=dv_ids,
        g=g,
        gd=gd,
        mv_operating_point=tuple(mv.operating_point for mv in config.variables.mvs),
        dv_operating_point=tuple(dv.operating_point for dv in config.variables.dvs),
    )
