"""Helpers dos testes do BlockShell — espelha o estilo bloco/alimenta/passo de test_pid.py."""

from datetime import UTC, datetime, timedelta

from ottima_flow_runtime.blocks.base import PortSample
from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.config import ShellCfg
from ottima_flow_runtime.blocks.shell.kernel import StubKernel

EPS = 0.01  # % do span (ADR-039 secao 7)
TS0 = datetime(2026, 1, 1, tzinfo=UTC)


class EventosFake:
    def __init__(self) -> None:
        self.eventos: list[dict] = []

    async def __call__(self, **kwargs) -> None:
        self.eventos.append(kwargs)

    def kinds(self) -> list[str]:
        return [e["kind"] for e in self.eventos]


def cfg_padrao(**over) -> ShellCfg:
    base = ShellCfg(sp_hi_lim=100.0, sp_lo_lim=0.0, max_dt=10.0)
    for chave, valor in over.items():
        setattr(base, chave, valor)
    return base


def bloco(
    *, kernel: StubKernel | None = None, eventos: EventosFake | None = None, **cfg_over
) -> BlockShell:
    return BlockShell(
        "malha1",
        kernel=kernel or StubKernel(),
        cfg=cfg_padrao(**cfg_over),
        emit_event=eventos,
    )


def amostra(v: float | bool | None, ok: bool = True) -> PortSample:
    return PortSample(v, ok)


async def passo(b: BlockShell, segundos: float, **portas) -> dict[str, PortSample]:
    """Executa um scan na marca `segundos` do relogio de teste."""
    inputs = {nome: valor for nome, valor in portas.items()}
    return await b.step(inputs, ts=TS0 + timedelta(seconds=segundos))
