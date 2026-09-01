"""F5 + reexecucao dos cenarios S criticos com o FuzzyKernel real (SPEC_FUZZY secao 9)."""

from shell_harness import EPS, EventosFake, amostra, passo

from ottima_core.flowgraph.parse import FuzzyLoopConfig
from ottima_flow_runtime.blocks.kernels.fuzzy import build_fuzzy_kernel
from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.definition import fuzzy_kernel_cfg_from, shell_cfg_from


def _malha(*, eventos: EventosFake | None = None, **over) -> BlockShell:
    base = {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "ke": 0.05, "kde": 0.0, "ku": 4.0}
    base.update(over)
    cfg = FuzzyLoopConfig.model_validate(base)
    return BlockShell(
        "m",
        kernel=build_fuzzy_kernel(cfg.fll, fuzzy_kernel_cfg_from(cfg)),
        cfg=shell_cfg_from(cfg, 1.0),
        emit_event=eventos,
    )


async def test_f5_degrau_de_sp_sem_sobressinal_e_sem_erro_de_regime() -> None:
    """A malha fuzzy-PI e um integrador puro: o erro de regime some pela integracao do shell."""
    b = _malha(ku=1.0)  # ku alto gera sobressinal neste processo de 1a ordem
    pv, t, pico = 40.0, 0.0, 0.0
    await passo(b, t, **{"in": amostra(pv)})
    b.write_sp(50.0)
    b.write_target(Mode.AUTO)
    for _ in range(600):
        t += 1.0
        await passo(b, t, **{"in": amostra(pv)})
        pv += (b.u - pv) / 8.0
        pico = max(pico, pv)
    assert pico <= 50.0 + 1.0  # sobressinal <= 1% do span (criterio F5)
    assert abs(pv - 50.0) <= 1.0  # erro de regime < 1%


async def test_f6_ku_dobrado_dobra_a_velocidade_e_mantem_o_regime() -> None:
    """F6 na malha fechada: `ku` e o analogo do ganho integral (SPEC secao 6.4)."""

    async def corre(ku: float, scans: int) -> tuple[float, float]:
        b = _malha(ku=ku)
        pv, t = 40.0, 0.0
        await passo(b, t, **{"in": amostra(pv)})
        b.write_sp(50.0)
        b.write_target(Mode.AUTO)
        for _ in range(scans):
            t += 1.0
            await passo(b, t, **{"in": amostra(pv)})
            pv += (b.u - pv) / 8.0
        return b.u, pv

    u_lento, _ = await corre(1.0, 3)
    u_rapido, _ = await corre(2.0, 3)
    assert u_rapido - 40.0 > 1.7 * (u_lento - 40.0)  # ~2x de velocidade de atuacao
    _, pv_lento = await corre(1.0, 600)
    _, pv_rapido = await corre(2.0, 600)
    assert abs(pv_lento - pv_rapido) <= 1.0  # mesmo valor de regime


async def test_s1_s2_bumpless_com_kernel_fuzzy() -> None:
    b = _malha()
    t = 0.0
    await passo(b, t, **{"in": amostra(30.0)})
    b.write_sp(70.0)
    b.write_target(Mode.AUTO)
    u0 = b.u
    t += 1.0
    await passo(b, t, **{"in": amostra(30.0)})
    assert abs(b.u - u0) <= 4.0 * 1.0 + EPS  # so o incremento do kernel, sem salto
    b.write_target(Mode.MAN)
    t += 1.0
    await passo(b, t, **{"in": amostra(30.0)})
    u_man = b.u
    for _ in range(120):
        t += 1.0
        await passo(b, t, **{"in": amostra(45.0)})
    b.write_target(Mode.AUTO)
    t += 1.0
    await passo(b, t, **{"in": amostra(45.0)})
    assert abs(b.u - u_man) <= 4.0 * 1.0 + EPS  # align zerou de_f: sem chute (S2)


async def test_s12_regiao_sem_regra_segura_out() -> None:
    fll_com_buraco = FuzzyLoopConfig.model_validate(
        {"sp_hi_lim": 100.0, "sp_lo_lim": 0.0, "ke": 0.05, "ku": 4.0}
    ).fll
    for regra in ("  rule: if e is PP then du is PP\n", "  rule: if e is PG then du is PG\n"):
        fll_com_buraco = fll_com_buraco.replace(regra, "")
    eventos = EventosFake()
    b = _malha(fll=fll_com_buraco, ke=0.1, eventos=eventos)
    t = 0.0
    await passo(b, t, **{"in": amostra(50.0)})
    b.write_sp(50.0)
    b.write_target(Mode.AUTO)
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    u_antes = b.u
    b.write_sp(90.0)  # empurra o ponto de operacao para o buraco (e_n grande positivo)
    t += 1.0
    await passo(b, t, **{"in": amostra(50.0)})
    assert abs(b.u - u_antes) <= EPS  # OUT mantido (F3 na malha fechada)
    assert any(e.get("payload", {}).get("code") == "kernel_invalid_output" for e in eventos.eventos)


async def test_diag_do_kernel_chega_ao_estado_publicado() -> None:
    """O faceplate le `e_n`/`de_n` do LoopState para desenhar o ponto de operacao (secao 8)."""
    b = _malha(ke=0.05, kde=0.0)
    t = 0.0
    await passo(b, t, **{"in": amostra(40.0)})
    b.write_sp(50.0)
    b.write_target(Mode.AUTO)
    t += 1.0
    await passo(b, t, **{"in": amostra(40.0)})
    estado = b._loop_state()
    assert abs(estado.diag["e_n"] - 0.5) < 1e-9  # erro 10 EU * ke 0.05
    assert estado.diag["rule_fire_count"] >= 1.0
