"""Montagem do-mpc do bloco MPC (spec F4 §3) + worker do processo filho (spec F4 §3.3/§3.6)."""

from .builder import R_DELTA_U, SLACK_WEIGHT_MULTIPLIER, BuiltMpc, build_mpc
from .bumpless import init_bumpless
from .worker import SolveRequest, SolveResult, worker_main

__all__ = [
    "R_DELTA_U",
    "SLACK_WEIGHT_MULTIPLIER",
    "BuiltMpc",
    "SolveRequest",
    "SolveResult",
    "build_mpc",
    "init_bumpless",
    "worker_main",
]
