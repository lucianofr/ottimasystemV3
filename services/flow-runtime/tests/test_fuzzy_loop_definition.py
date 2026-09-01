"""fuzzy_loop no runtime: instanciacao, F10 (sintonia in-place) e F11 (estrutural->MAN)."""

from shell_harness import EPS, amostra, passo

from ottima_core.flowgraph.parse import FuzzyLoopConfig, loop_structural
from ottima_flow_runtime.blocks.kernels.fuzzy import BrokenKernel, FuzzyKernel, build_fuzzy_kernel
from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.definition import LOOP_TYPES, fuzzy_kernel_cfg_from, shell_cfg_from


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
