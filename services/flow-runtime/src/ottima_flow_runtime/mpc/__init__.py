"""Montagem do-mpc do bloco MPC (spec F4 §3) + worker do processo filho (spec F4 §3.3/§3.6)
+ host do processo pai (spec F4 §3.6/§4.2/§4.9, tarefa 1.2)."""

from .builder import R_DELTA_U, SLACK_WEIGHT_MULTIPLIER, BuiltMpc, build_mpc
from .bumpless import init_bumpless
from .host import MpcHost
from .worker import SolveRequest, SolveResult, worker_main

__all__ = [
    "R_DELTA_U",
    "SLACK_WEIGHT_MULTIPLIER",
    "BuiltMpc",
    "MpcHost",
    "SolveRequest",
    "SolveResult",
    "build_mpc",
    "init_bumpless",
    "worker_main",
]
