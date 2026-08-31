"""Registro do pid_loop: conversores, hot-swap sintonia/estrutural, command, publish."""

from typing import Any, cast

from shell_harness import amostra, passo

from ottima_core.flowgraph import PidLoopConfig, TagRef, parse_graph
from ottima_flow_runtime.blocks.kernels.pid import PidKernel
from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.kernel import StubKernel
from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.definition import (
    LoopSeed,
    build_definition,
    pid_kernel_cfg_from,
    shell_cfg_from,
)


def _config(**over) -> PidLoopConfig:
    base = {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "kc": 2.0}
    base.update(over)
    return PidLoopConfig.model_validate(base)


def test_shell_cfg_from_converte_modos_e_max_dt() -> None:
    cfg = shell_cfg_from(_config(permitted=["oos", "man", "auto", "cas"]), ts_seconds=0.5)
    assert cfg.max_dt == 5.0
    assert cfg.permitted & Mode.CAS
    assert cfg.normal is Mode.AUTO


def test_pid_kernel_cfg_from_mapeia_campos() -> None:
    k = pid_kernel_cfg_from(_config(kc=3.0, ti_seconds=12.0, gamma=1.0))
    assert k.kc == 3.0 and k.ti == 12.0 and k.gamma == 1.0


async def test_p3_apply_tuning_kc_30pct_sem_degrau() -> None:
    cfg = _config(kc=2.0, ti_seconds=20.0)
    b = BlockShell("m", kernel=PidKernel(pid_kernel_cfg_from(cfg)), cfg=shell_cfg_from(cfg, 1.0))
    await passo(b, 0.0, **{"in": amostra(50.0)})
    b.write_sp(55.0)  # erro de 5%
    b.write_target(Mode.AUTO)
    t = 0.0
    for _ in range(10):
        t += 1.0
        await passo(b, t, **{"in": amostra(50.0)})
    u_antes = b.u
    nova = _config(kc=2.6, ti_seconds=20.0)  # +30%
    b.apply_tuning(shell_cfg_from(nova, 1.0), pid_kernel_cfg_from(nova))
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    # sem degrau: a variacao do scan e a do incremento normal, nao um salto de posicao
    assert abs(b.u - u_antes) <= abs(2.6 * 5.0 / 20.0) + 0.01  # so o incremento I


async def test_command_loop_mode_sp_out() -> None:
    cfg = _config()
    b = BlockShell("m", kernel=StubKernel(), cfg=shell_cfg_from(cfg, 1.0))
    await passo(b, 0.0, **{"in": amostra(50.0)})
    await b.command("loop_sp", {"value": 42.0}, "user:1")
    assert b.sp_op == 42.0
    await b.command("loop_out", {"value": 77.0}, "user:1")
    assert b.man_out == 77.0
    await b.command("loop_mode", {"target": "auto"}, "user:1")
    assert b.mode.target is Mode.AUTO
    await b.command("loop_mode", {"target": "cas"}, "user:1")  # fora de permitted
    assert b.mode.target is Mode.AUTO  # rejeitado, target intacto


# --------------------------------------------------------------------------------------
# build_definition — registro e hot-swap em duas classes (mesa pura, espelho de
# test_definition_filtros.py)
# --------------------------------------------------------------------------------------


def _no(node_id: str, exec_order: int, **data: object) -> dict:
    return {
        "id": node_id,
        "type": "pid_loop",
        "position": {"x": 0.0, "y": 0.0},
        "data": {"exec_order": exec_order, **data},
    }


def _graph(**over: object) -> dict:
    dados: dict[str, object] = {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "kc": 2.0}
    dados.update(over)
    return {
        "nodes": [
            {
                "id": "r1",
                "type": "opc_read",
                "position": {"x": 0.0, "y": 0.0},
                "data": {"exec_order": 1, "tag_id": 1},
            },
            _no("m", 2, **dados),
        ],
        "edges": [
            {
                "id": "e1",
                "source": "r1",
                "target": "m",
                "sourceHandle": "out",
                "targetHandle": "in",
            },
        ],
    }


def _tags() -> dict[int, TagRef]:
    return {1: TagRef(id=1, conn_id=1, direction="r", data_type="float")}


class _RedisFake:
    """Duplo do Redis: so o publish dos fechamentos e usado (sem step na maioria dos
    testes; quando ha step, a publicacao de LoopState cai no no-op)."""

    async def publish(self, channel: str, payload: str) -> None:
        return None


def _build(graph: dict, reuse: dict | None = None, **kwargs: Any):
    none: Any = None
    return build_definition(
        parse_graph(graph),
        _tags(),
        flow_id=1,
        ts_seconds=1.0,
        reuse=reuse or {},
        redis_client=cast(Any, _RedisFake()),
        pool=none,
        snapshot=none,
        **kwargs,
    )


def test_build_definition_instancia_blockshell_com_pidkernel() -> None:
    staged = _build(_graph())
    _, bloco = staged.blocks["m"]
    assert isinstance(bloco, BlockShell)
    assert isinstance(bloco.kernel, PidKernel)
    assert bloco.cfg.max_dt == 10.0  # 10x o Ts do flow


def test_hotswap_de_sintonia_preserva_instancia_e_estado() -> None:
    antes = _build(_graph())
    bloco = antes.blocks["m"][1]
    depois = _build(_graph(kc=2.6), reuse=antes.blocks)
    assert depois.blocks["m"][1] is bloco  # classe de sintonia: in-place (D11)
    assert isinstance(bloco, BlockShell)
    assert bloco.kernel.cfg.kc == 2.6
    assert bloco.cfg.max_dt == 10.0


def test_hotswap_estrutural_reinstancia_carregando_estado() -> None:
    antes = _build(_graph(out_startup=30.0))
    bloco = antes.blocks["m"][1]
    depois = _build(_graph(out_startup=30.0, out_scale_hi=400.0), reuse=antes.blocks)
    novo = depois.blocks["m"][1]
    assert novo is not bloco
    assert isinstance(novo, BlockShell)
    assert novo.u == bloco.u  # u carregado do predecessor


async def test_hotswap_estrutural_aterrissa_em_man_se_calculava() -> None:
    antes = _build(_graph())
    bloco = antes.blocks["m"][1]
    assert isinstance(bloco, BlockShell)
    await passo(bloco, 0.0, **{"in": amostra(50.0)})
    bloco.write_target(Mode.AUTO)
    await passo(bloco, 1.0, **{"in": amostra(50.0)})
    assert bloco.mode.actual is Mode.AUTO
    depois = _build(_graph(out_scale_hi=400.0), reuse=antes.blocks)
    novo = depois.blocks["m"][1]
    assert isinstance(novo, BlockShell)
    assert novo is not bloco
    await passo(novo, 2.0, **{"in": amostra(50.0)})
    assert novo.mode.actual is Mode.MAN  # aterrissagem estrutural (D11)


def test_loop_seeds_alimentam_sp_e_man_out() -> None:
    staged = _build(_graph(), loop_seeds={"m": LoopSeed(sp=42.0, man_out=11.0)})
    bloco = staged.blocks["m"][1]
    assert isinstance(bloco, BlockShell)
    assert bloco.sp_op == 42.0
    assert bloco.man_out == 11.0
