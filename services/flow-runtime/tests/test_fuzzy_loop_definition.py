"""fuzzy_loop no runtime: instanciacao, F10 (sintonia in-place) e F11 (estrutural->MAN)."""

from typing import Any, cast

from shell_harness import EPS, amostra, passo

from ottima_core.flowgraph import TagRef, parse_graph
from ottima_core.flowgraph.parse import FuzzyLoopConfig, loop_structural
from ottima_flow_runtime.blocks.kernels.fuzzy import BrokenKernel, FuzzyKernel, build_fuzzy_kernel
from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.definition import (
    LOOP_TYPES,
    build_definition,
    fuzzy_kernel_cfg_from,
    shell_cfg_from,
)


def _config(**over) -> FuzzyLoopConfig:
    base = {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "ke": 0.05, "ku": 3.0}
    base.update(over)
    return FuzzyLoopConfig.model_validate(base)


def _malha(cfg: FuzzyLoopConfig) -> BlockShell:
    return BlockShell(
        "m",
        kernel=build_fuzzy_kernel(cfg.fll, fuzzy_kernel_cfg_from(cfg)),
        cfg=shell_cfg_from(cfg, 1.0),
    )


def test_fuzzy_loop_e_um_tipo_de_malha_no_runtime() -> None:
    assert "fuzzy_loop" in LOOP_TYPES


def test_kernel_cfg_carrega_os_ganhos_e_o_sentido() -> None:
    cfg = fuzzy_kernel_cfg_from(_config(ke=0.2, kde=0.5, ku=7.0, tf_de=2.0, direct_acting=True))
    assert (cfg.ke, cfg.kde, cfg.ku, cfg.tf_de) == (0.2, 0.5, 7.0, 2.0)
    assert cfg.direct_acting is True


def test_fll_default_instancia_kernel_real() -> None:
    kernel = build_fuzzy_kernel(_config().fll, fuzzy_kernel_cfg_from(_config()))
    assert isinstance(kernel, FuzzyKernel)
    assert kernel.validate() == []


def test_fll_degradado_instancia_broken_kernel() -> None:
    """F1 no deploy: o shell le validate() e prende o bloco em OOS+CONFIG_ERROR."""
    quebrado = build_fuzzy_kernel("Engine: lixo\ninvalido", fuzzy_kernel_cfg_from(_config()))
    assert isinstance(quebrado, BrokenKernel)
    assert quebrado.validate() != []


def test_lut_habilitada_carrega_a_grade_na_instanciacao() -> None:
    """`lut_enabled` amostra a superficie UMA vez (SPEC secao 5.2): o scan so interpola."""
    from ottima_flow_runtime.definition import _build_loop_kernel

    sem_lut = _build_loop_kernel("fuzzy_loop", _config())
    com_lut = _build_loop_kernel("fuzzy_loop", _config(lut_enabled=True, lut_resolution=33))
    assert sem_lut.lut is None
    assert com_lut.lut is not None and com_lut.lut.shape == (33, 33)


async def test_f10_troca_de_ku_em_auto_sem_degrau() -> None:
    b = _malha(_config())
    t = 0.0
    await passo(b, t, **{"in": amostra(50.0)})
    b.write_sp(55.0)
    b.write_target(Mode.AUTO)
    for _ in range(5):
        t += 1.0
        await passo(b, t, **{"in": amostra(50.0)})
    u_antes = b.u
    nova = _config(ku=6.0)  # dobra KU: classe de sintonia
    b.apply_tuning(shell_cfg_from(nova, 1.0), fuzzy_kernel_cfg_from(nova))
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    # sem degrau de posicao: a variacao do scan e apenas o incremento (agora 2x maior)
    assert abs(b.u - u_antes) <= 2.0 * 3.0 * 1.0 + EPS
    assert b.mode.actual is Mode.AUTO  # sintonia nao mexe no modo


async def test_f11_troca_de_fll_e_estrutural() -> None:
    a = _config()
    outro_fll = a.fll.replace("Engine: fuzzy_loop_padrao", "Engine: outro")
    b = _config(fll=outro_fll)
    fa = {"type": "fuzzy_loop", **a.model_dump()}
    fb = {"type": "fuzzy_loop", **b.model_dump()}
    assert loop_structural(fa) != loop_structural(fb)  # build_definition re-instancia
    assert loop_structural(fa) == loop_structural(
        {"type": "fuzzy_loop", **_config(ku=9.0).model_dump()}
    )


# --------------------------------------------------------------------------------------
# build_definition — o caminho REAL do deploy (mesa pura, espelho de
# test_pid_loop_definition.py)
# --------------------------------------------------------------------------------------


def _graph(**over: object) -> dict:
    dados: dict[str, object] = {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "ke": 0.05, "ku": 2.0}
    dados.update(over)
    return {
        "nodes": [
            {
                "id": "r1",
                "type": "opc_read",
                "position": {"x": 0.0, "y": 0.0},
                "data": {"exec_order": 1, "tag_id": 1},
            },
            {
                "id": "m",
                "type": "fuzzy_loop",
                "position": {"x": 0.0, "y": 0.0},
                "data": {"exec_order": 2, **dados},
            },
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


class _RedisFake:
    async def publish(self, channel: str, payload: str) -> None:
        return None


def _build(graph: dict, reuse: dict | None = None):
    none: Any = None
    return build_definition(
        parse_graph(graph),
        {1: TagRef(id=1, conn_id=1, direction="r", data_type="float")},
        flow_id=1,
        ts_seconds=1.0,
        reuse=reuse or {},
        redis_client=cast(Any, _RedisFake()),
        pool=none,
        snapshot=none,
    )


def test_build_definition_instancia_blockshell_com_fuzzykernel() -> None:
    """Regressao: `_instantiate` despachava por `node.type == "pid_loop"` literal, e o
    fallback final da cadeia e `TfsBlock` — um `fuzzy_loop` caia no bloco de funcao de
    transferencia e o deploy morria com `'FuzzyLoopConfig' object has no attribute 'matrix'`.
    Achado no smoke fim-a-fim; o dispatch agora e por `LOOP_TYPES`."""
    staged = _build(_graph())
    _, bloco = staged.blocks["m"]
    assert isinstance(bloco, BlockShell)
    assert isinstance(bloco.kernel, FuzzyKernel)
    assert bloco.cfg.max_dt == 10.0  # 10x o Ts do flow


def test_build_definition_hotswap_de_sintonia_preserva_a_instancia() -> None:
    antes = _build(_graph())
    bloco = antes.blocks["m"][1]
    depois = _build(_graph(ku=6.0), reuse=antes.blocks)
    assert depois.blocks["m"][1] is bloco  # classe de sintonia: in-place (D11)
    assert isinstance(bloco, BlockShell)
    assert bloco.kernel.cfg.ku == 6.0


async def test_build_definition_hotswap_de_fll_aterrissa_em_man_se_calculava() -> None:
    """F11 no caminho real: trocar o `.fll` re-instancia e a malha aterrissa em MAN."""
    antes = _build(_graph())
    bloco = antes.blocks["m"][1]
    assert isinstance(bloco, BlockShell)
    t = 0.0
    await passo(bloco, t, **{"in": amostra(50.0)})
    bloco.write_sp(60.0)
    bloco.write_target(Mode.AUTO)
    for _ in range(3):
        t += 1.0
        await passo(bloco, t, **{"in": amostra(50.0)})
    assert bloco.mode.actual is Mode.AUTO
    u_antes = bloco.u

    outro = _graph(fll=_config().fll.replace("Engine: fuzzy_loop_padrao", "Engine: outro"))
    depois = _build(outro, reuse=antes.blocks)
    novo = depois.blocks["m"][1]
    assert novo is not bloco  # classe estrutural: re-instancia
    assert isinstance(novo, BlockShell)
    assert novo.mode.target is Mode.MAN  # aterrissou em MAN
    assert abs(novo.u - u_antes) < 1e-9  # com u mantido, sem degrau
