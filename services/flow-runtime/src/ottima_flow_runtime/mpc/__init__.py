"""Montagem do-mpc do bloco MPC (spec F4 §3)."""

from .builder import R_DELTA_U, SLACK_WEIGHT_MULTIPLIER, BuiltMpc, build_mpc

__all__ = [
    "R_DELTA_U",
    "SLACK_WEIGHT_MULTIPLIER",
    "BuiltMpc",
    "build_mpc",
]
