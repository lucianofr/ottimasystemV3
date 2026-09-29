"""fuzzy_loop v2 MIMO: kernel multicanal, shell de N canais e malha fechada acoplada.

O cenario de aceitacao do redesenho: UM bloco com `n_loops` canais controla um processo
MIMO acoplado (TFS 2x2 na stack; aqui, dois primeiros-ordem com ganho cruzado), com SPs
independentes por canal e modo por bloco.
"""

import math

from shell_harness import EPS, EventosFake, amostra, passo

from ottima_core.bus import LoopState
from ottima_core.flowgraph.fll_defaults import fuzzy_loop_default_fll
from ottima_core.flowgraph.parse import FuzzyLoopConfig
from ottima_flow_runtime.blocks.kernels.fuzzy import FuzzyKernelCfg, build_fuzzy_kernel
from ottima_flow_runtime.blocks.shell.block import BlockShell
from ottima_flow_runtime.blocks.shell.mode import Mode
from ottima_flow_runtime.definition import fuzzy_kernel_cfg_from, shell_cfg_from

FLL_MIMO = fuzzy_loop_default_fll(2)

# Base autoral com regra de DESACOPLAMENTO: `e2` grande empurra `du1` contra o acoplamento
# positivo do processo (e vice-versa). Nomes livres — o contrato e posicional.
FLL_MIMO_DESACOPLADO = FLL_MIMO.replace(
    "  rule: if e1 is PG then du1 is PG",
    "  rule: if e1 is PG then du1 is PG\n"
    "  rule: if e2 is PG and de2 is ZE then du1 is NP\n"
    "  rule: if e2 is NG and de2 is ZE then du1 is PP",
).replace(
    "  rule: if e2 is PG then du2 is PG",
    "  rule: if e2 is PG then du2 is PG\n"
    "  rule: if e1 is PG and de1 is ZE then du2 is NP\n"
    "  rule: if e1 is NG and de1 is ZE then du2 is PP",
)


def _cfg(**over) -> FuzzyLoopConfig:
    base = {
        "sp_hi_lim": 100.0,
        "sp_lo_lim": 0.0,
        "ke": 0.05,
        "kde": 0.0,
        "ku": 4.0,
        "n_loops": 2,
        "fll": FLL_MIMO,
    }
    base.update(over)
    return FuzzyLoopConfig.model_validate(base)


def _malha(*, eventos: EventosFake | None = None, **over) -> BlockShell:
    cfg = _cfg(**over)
    return BlockShell(
        "m",
        kernel=build_fuzzy_kernel(cfg.fll, fuzzy_kernel_cfg_from(cfg)),
        cfg=shell_cfg_from(cfg, 1.0),
        emit_event=eventos,
        n_channels=cfg.n_loops,
        channel_ports=True,
    )


# --------------------------------------------------------------------------------------
# Kernel multicanal
# --------------------------------------------------------------------------------------


def test_kernel_mimo_instancia_e_valida() -> None:
    k = build_fuzzy_kernel(FLL_MIMO, FuzzyKernelCfg(ke=0.1, ku=5.0, n_loops=2))
    assert k.validate() == []
    assert len(k.diag_channels) == 2


def test_canais_independentes_na_base_descentralizada() -> None:
    """Base default multicanal = N controladores descentralizados: erro so no canal 2
    nao mexe no canal 1."""
    k = build_fuzzy_kernel(FLL_MIMO, FuzzyKernelCfg(ke=0.1, kde=0.0, ku=5.0, n_loops=2))
    k.align_all([0.0, 0.0], [10.0, 10.0], [10.0, 10.0])
    du1, du2 = k.compute_all([10.0, 30.0], [10.0, 10.0], 1.0)
    assert abs(du1) < 1e-9  # erro zero no canal 1 -> du1 zero
    assert du2 > 0.0  # erro +20 EU no canal 2 -> sobe


def test_regra_cruzada_desacopla_canais() -> None:
    """O mesmo cenario com a base desacopladora: o erro do canal 2 antecipa a reacao do
    canal 1 (du1 < 0), coisa que a base descentralizada nao faz."""
    cfg = FuzzyKernelCfg(ke=0.1, kde=0.0, ku=5.0, n_loops=2)
    simples = build_fuzzy_kernel(FLL_MIMO, cfg)
    cruzado = build_fuzzy_kernel(FLL_MIMO_DESACOPLADO, cfg)
    for k in (simples, cruzado):
        k.align_all([0.0, 0.0], [10.0, 10.0], [10.0, 10.0])
    du1_simples, _ = simples.compute_all([10.0, 30.0], [10.0, 10.0], 1.0)
    du1_cruzado, du2_cruzado = cruzado.compute_all([10.0, 30.0], [10.0, 10.0], 1.0)
    assert du1_cruzado < du1_simples  # acao corretiva cruzada no canal 1
    assert du2_cruzado > 0.0  # e o canal 2 segue mandando subir


def test_diag_por_canal() -> None:
    k = build_fuzzy_kernel(FLL_MIMO, FuzzyKernelCfg(ke=0.1, kde=0.0, ku=5.0, n_loops=2))
    k.align_all([0.0, 0.0], [10.0, 10.0], [10.0, 10.0])
    k.compute_all([10.0, 30.0], [10.0, 10.0], 1.0)
    assert abs(k.diag_channels[0]["e_n"]) < 1e-9
    assert abs(k.diag_channels[1]["e_n"] - 1.0) < 1e-9  # erro 20 EU * ke 0.1, saturado
    assert k.diag is k.diag_channels[0]  # vista SISO-compat


def test_entrada_nao_finita_devolve_nan_sem_tocar_estado() -> None:
    k = build_fuzzy_kernel(FLL_MIMO, FuzzyKernelCfg(ke=0.1, ku=5.0, n_loops=2))
    k.align_all([0.0, 0.0], [10.0, 10.0], [10.0, 10.0])
    dus = k.compute_all([10.0, math.nan], [10.0, 10.0], 1.0)
    assert all(math.isnan(du) for du in dus)
    # estado intacto: o scan seguinte com entradas finitas funciona
    dus = k.compute_all([10.0, 30.0], [10.0, 10.0], 1.0)
    assert all(math.isfinite(du) for du in dus)


def test_lut_por_canal() -> None:
    k = build_fuzzy_kernel(
        FLL_MIMO,
        FuzzyKernelCfg(ke=0.1, ku=5.0, n_loops=2, lut_enabled=True, lut_resolution=33),
    )
    assert len(k.luts) == 2
    assert all(lut is not None and lut.shape == (33, 33) for lut in k.luts)
    assert k.lut is k.luts[0]


def test_lut_mimo_coincide_com_inferencia() -> None:
    """F8 multicanal: a LUT de cada canal reproduz a inferencia do mesmo canal."""
    direto = build_fuzzy_kernel(FLL_MIMO, FuzzyKernelCfg(ke=1.0, kde=1.0, ku=100.0, n_loops=2))
    com_lut = build_fuzzy_kernel(
        FLL_MIMO,
        FuzzyKernelCfg(ke=1.0, kde=1.0, ku=100.0, n_loops=2, lut_enabled=True),
    )
    for k in (direto, com_lut):
        k.align_all([0.0, 0.0], [0.5, -0.25], [0.0, 0.0])
    a = direto.compute_all([0.5, -0.25], [0.0, 0.0], 1.0)
    b = com_lut.compute_all([0.5, -0.25], [0.0, 0.0], 1.0)
    assert all(abs(x - y) <= 0.5 for x, y in zip(a, b, strict=True))


# --------------------------------------------------------------------------------------
# Shell de 2 canais
# --------------------------------------------------------------------------------------


async def test_shell_mimo_publica_um_estado_por_canal() -> None:
    b = _malha()
    estado0 = b._loop_state(0)
    estado1 = b._loop_state(1)
    assert (estado0.channel, estado1.channel) == (0, 1)
    # round-trip do recorder: JSON valido, sem null em diag
    for estado in (estado0, estado1):
        assert isinstance(estado, LoopState)
        LoopState.model_validate_json(estado.model_dump_json())


async def test_sp_por_canal_e_modo_por_bloco() -> None:
    b = _malha()
    b.write_sp(30.0, 0)
    b.write_sp(70.0, 1)
    assert (b._canais[0].sp_op, b._canais[1].sp_op) == (30.0, 70.0)
    assert b.sp_op == 30.0  # vista SISO-compat = canal 0
    b.write_target(Mode.AUTO)
    t = 0.0
    await passo(b, t, **{"pv_1": amostra(30.0), "pv_2": amostra(70.0)})
    t += 1.0
    saida = await passo(b, t, **{"pv_1": amostra(30.0), "pv_2": amostra(70.0)})
    assert set(saida) == {"out_1", "out_2"}
    assert b.mode.actual is Mode.AUTO
    assert b._loop_state(1).sp == 70.0


async def test_comando_ignora_canal_fora_do_bloco() -> None:
    b = _malha()
    await b.command("loop_sp", {"value": 55.0, "channel": 5}, "teste")
    assert b._canais[0].sp_op == 0.0 and b._canais[1].sp_op == 0.0


async def test_pv_ruim_em_um_canal_segura_o_bloco_em_man() -> None:
    """Fail-safe multicanal: PV sem qualidade em QUALQUER canal tira o bloco do modo
    calculante (o motor e compartilhado)."""
    b = _malha()
    b.write_target(Mode.AUTO)
    t = 0.0
    await passo(b, t, **{"pv_1": amostra(50.0), "pv_2": amostra(50.0)})
    t += 1.0
    await passo(b, t, **{"pv_1": amostra(50.0), "pv_2": amostra(50.0, ok=False)})
    assert b.mode.actual is Mode.MAN


async def test_nan_num_canal_segura_ambos_e_alarma() -> None:
    fll_com_buraco = _cfg().fll
    for regra in ("  rule: if e1 is PP then du1 is PP\n", "  rule: if e1 is PG then du1 is PG\n"):
        fll_com_buraco = fll_com_buraco.replace(regra, "")
    eventos = EventosFake()
    b = _malha(eventos=eventos, fll=fll_com_buraco, ke=0.1, ku=4.0)
    t = 0.0
    await passo(b, t, **{"pv_1": amostra(50.0), "pv_2": amostra(50.0)})
    b.write_sp(50.0, 0)
    b.write_sp(50.0, 1)
    b.write_target(Mode.AUTO)
    t += 1.0
    await passo(b, t, **{"pv_1": amostra(50.0), "pv_2": amostra(50.0)})
    u1, u2 = b._canais[0].u, b._canais[1].u
    b.write_sp(90.0, 0)  # empurra o canal 1 para o buraco (e_n -> +1 sem regra)
    t += 1.0
    await passo(b, t, **{"pv_1": amostra(50.0), "pv_2": amostra(50.0)})
    assert abs(b._canais[0].u - u1) <= EPS  # OUT mantido nos DOIS canais
    assert abs(b._canais[1].u - u2) <= EPS
    assert any(e.get("payload", {}).get("code") == "kernel_invalid_output" for e in eventos.eventos)


# --------------------------------------------------------------------------------------
# Malha fechada MIMO acoplada — o criterio de sucesso do redesenho
# --------------------------------------------------------------------------------------


async def test_malha_fechada_mimo_acoplada_persegue_dois_sps() -> None:
    """Processo 2x2 acoplado (ganho cruzado 40%), base de regras com desacoplamento:
    os dois canais perseguem SPs distintos com erro de regime < 1 EU."""
    b = _malha(fll=FLL_MIMO_DESACOPLADO, ku=2.0)
    k11 = k22 = 1.0
    k12 = k21 = 0.4  # acoplamento positivo
    tau = 8.0
    pv1 = pv2 = 0.0
    t = 0.0
    await passo(b, t, **{"pv_1": amostra(pv1), "pv_2": amostra(pv2)})
    b.write_sp(50.0, 0)
    b.write_sp(70.0, 1)
    b.write_target(Mode.AUTO)
    for _ in range(600):
        t += 1.0
        await passo(b, t, **{"pv_1": amostra(pv1), "pv_2": amostra(pv2)})
        u1 = b._canais[0].u
        u2 = b._canais[1].u
        pv1 += (k11 * u1 + k12 * u2 - pv1) / tau
        pv2 += (k21 * u1 + k22 * u2 - pv2) / tau
    assert abs(pv1 - 50.0) <= 1.0, f"canal 1 nao convergiu: pv1={pv1:.2f}"
    assert abs(pv2 - 70.0) <= 1.0, f"canal 2 nao convergiu: pv2={pv2:.2f}"
    assert b.mode.actual is Mode.AUTO  # nunca caiu para MAN no caminho


async def test_malha_fechada_mimo_base_descentralizada_tambem_converge() -> None:
    """Sem regras cruzadas o integrador do shell ainda absorve o acoplamento (o ganho
    cruzado vira disturbio de carga) — a base autoral e otimizacao, nao pre-requisito."""
    b = _malha(ku=2.0)
    tau = 8.0
    pv1 = pv2 = 0.0
    t = 0.0
    await passo(b, t, **{"pv_1": amostra(pv1), "pv_2": amostra(pv2)})
    b.write_sp(60.0, 0)
    b.write_sp(30.0, 1)
    b.write_target(Mode.AUTO)
    for _ in range(900):
        t += 1.0
        await passo(b, t, **{"pv_1": amostra(pv1), "pv_2": amostra(pv2)})
        u1 = b._canais[0].u
        u2 = b._canais[1].u
        pv1 += (u1 + 0.4 * u2 - pv1) / tau
        pv2 += (0.4 * u1 + u2 - pv2) / tau
    assert abs(pv1 - 60.0) <= 1.0, f"canal 1 nao convergiu: pv1={pv1:.2f}"
    assert abs(pv2 - 30.0) <= 1.0, f"canal 2 nao convergiu: pv2={pv2:.2f}"
