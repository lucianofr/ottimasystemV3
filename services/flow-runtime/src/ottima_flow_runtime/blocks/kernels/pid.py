"""PID ISA em forma incremental (SPEC_PID_with_SHELL secao 3)."""

import math
from dataclasses import dataclass


@dataclass(slots=True)
class PidKernelCfg:
    kc: float  # %span/EU, > 0; sentido SO via direct_acting
    ti: float = 0.0  # s; 0 desliga a acao integral (convencao ADR-031)
    td: float = 0.0  # s; 0 desliga a acao derivativa
    n: float = 8.0  # razao do filtro derivativo, Tf = td/n
    beta: float = 1.0  # ponderacao de SP no termo proporcional
    gamma: float = 0.0  # ponderacao de SP no termo derivativo
    gap_band: float = 0.0  # EU; 0 desabilita
    gap_gain: float = 1.0  # inclinacao de g() dentro da banda
    direct_acting: bool = False


class PidKernel:
    """PID ISA em forma incremental. Contrato: ADR-039 secao 4.5."""

    def __init__(self, cfg: PidKernelCfg):
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self.ep_prev = 0.0
        self.edf = 0.0
        self.r_prev = 0.0

    def _gap(self, d: float) -> float:
        b, k = self.cfg.gap_band, self.cfg.gap_gain
        if b <= 0.0:
            return d
        if abs(d) <= b:
            return k * d
        return math.copysign(k * b + (abs(d) - b), d)

    def align(self, u: float, sp: float, pv: float) -> None:
        c = self.cfg
        s = -1.0 if c.direct_acting else 1.0
        dg = self._gap(s * (sp - pv))
        self.ep_prev = dg - s * (1.0 - c.beta) * sp
        self.edf = s * (c.gamma * sp - pv)
        self.r_prev = 0.0  # termo D nulo no proximo scan

    def compute(self, sp: float, pv: float, dt: float) -> float:
        c = self.cfg
        s = -1.0 if c.direct_acting else 1.0

        dg = self._gap(s * (sp - pv))
        e = dg
        ep = dg - s * (1.0 - c.beta) * sp
        ed = s * (c.gamma * sp - pv)

        p_term = (ep - self.ep_prev) / dt
        self.ep_prev = ep

        i_term = (e / c.ti) if c.ti > 0.0 else 0.0

        d_term = 0.0
        if c.td > 0.0:
            tf = c.td / c.n
            a = dt / (tf + dt)
            edf_prev = self.edf
            self.edf += a * (ed - self.edf)
            r = (self.edf - edf_prev) / dt
            d_term = c.td * (r - self.r_prev) / dt
            self.r_prev = r

        return c.kc * (p_term + i_term + d_term)

    def validate(self) -> list[str]:
        c, errs = self.cfg, []
        if not math.isfinite(c.kc) or c.kc <= 0.0:
            errs.append("KC_MUST_BE_POSITIVE")  # sentido via DIRECT_ACTING
        if c.ti < 0.0:
            errs.append("TI_MUST_BE_NON_NEGATIVE")  # 0 = integral desligada
        if c.td < 0.0:
            errs.append("TD_MUST_BE_NON_NEGATIVE")
        if c.td > 0.0 and c.n <= 0.0:
            errs.append("N_MUST_BE_POSITIVE")
        if not (0.0 <= c.beta <= 1.0):
            errs.append("BETA_OUT_OF_RANGE")
        if not (0.0 <= c.gamma <= 1.0):
            errs.append("GAMMA_OUT_OF_RANGE")
        if c.gap_band < 0.0 or not (0.0 <= c.gap_gain <= 1.0):
            errs.append("GAP_CONFIG_INVALID")
        return errs
