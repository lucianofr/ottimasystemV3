"""Ingest de loop.state no recorder: pv/sp/out toda mensagem, mode so na transicao."""

from datetime import UTC, datetime

from ottima_core.bus import LoopState


def _estado(actual: str = "auto") -> str:
    return LoopState(
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        target="auto",
        actual=actual,
        permitted=["oos", "man", "auto"],
        pv=50.0,
        pv_ok=True,
        sp=55.0,
        out=210.0,
        u_pct=52.5,
        man_out=52.5,
        hi_limited=False,
        lo_limited=False,
    ).model_dump_json()


def _pipeline():
    from ottima_recorder.pipeline import RecorderPipeline

    return RecorderPipeline(None, None)  # type: ignore[arg-type]  # buffers apenas


def test_ingest_grava_pv_sp_out_e_mode_so_na_transicao() -> None:
    p = _pipeline()
    p.ingest_loop_state("loop.state.7.abc", _estado("auto"))
    linhas = p._loop.snapshot()
    assert sorted(x["var_id"] for x in linhas) == ["mode", "out", "pv", "sp"]
    # mode na primeira mensagem (transicao OOS->auto implicita? nao — cache comeca vazio)
    p.ingest_loop_state("loop.state.7.abc", _estado("auto"))
    modos = [x for x in p._loop.snapshot() if x["var_id"] == "mode"]
    assert len(modos) == 1  # sem transicao, mode nao repete
    p.ingest_loop_state("loop.state.7.abc", _estado("man"))
    modos = [x for x in p._loop.snapshot() if x["var_id"] == "mode"]
    assert len(modos) == 2 and modos[-1]["v"] == 16.0  # man = 0x10


def test_ingest_loop_malformado_descarta_sem_explodir() -> None:
    p = _pipeline()
    p.ingest_loop_state("loop.state.7.abc", "{nao-e-json}")
    assert p._loop.snapshot() == []
    assert p._malformed_total == 1


def test_pv_none_grava_null() -> None:
    """PV BAD/None grava NULL em v (mesmo idiom de samples, ADR-037)."""
    from ottima_core.bus import LoopState as LS

    raw = LS(
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        target="auto",
        actual="man",
        permitted=[],
        pv=None,
        pv_ok=False,
        sp=55.0,
        out=0.0,
        u_pct=0.0,
        man_out=0.0,
        hi_limited=False,
        lo_limited=False,
    ).model_dump_json()
    p = _pipeline()
    p.ingest_loop_state("loop.state.7.abc", raw)
    pv = [x for x in p._loop.snapshot() if x["var_id"] == "pv"]
    assert pv[0]["v"] is None


def test_diag_com_nan_e_descartado_como_malformado() -> None:
    """Documenta a armadilha: `model_dump_json` emite NaN como `null`, mas o `_parse` do
    recorder revalida e `dict[str, float]` recusa null — o quadro INTEIRO cai, sem linha em
    `loop_samples` e sem erro visivel para quem opera. Por isso o kernel garante diag finito
    na origem, em vez de contar com null ser tolerado."""
    bruto = LoopState(
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        target="auto",
        actual="auto",
        permitted=["auto"],
        pv=50.0,
        pv_ok=True,
        sp=55.0,
        out=210.0,
        u_pct=52.5,
        man_out=52.5,
        hi_limited=False,
        lo_limited=False,
        diag={"e_n": 0.5, "rule_fire_count": float("nan")},
    ).model_dump_json()
    assert '"rule_fire_count":null' in bruto  # a serializacao aceita
    p = _pipeline()
    p.ingest_loop_state("loop.state.7.abc", bruto)
    assert p._loop.snapshot() == []  # a validacao nao: quadro perdido
    assert p.malformed_total == 1


def test_diag_do_kernel_fuzzy_ingere_nos_dois_caminhos() -> None:
    """Contraprova com o diag REAL do FuzzyKernel, com e sem LUT: ingere e grava."""
    from ottima_core.contracts_export import FUZZY_LOOP_DEFAULT_FLL
    from ottima_flow_runtime.blocks.kernels.fuzzy import FuzzyKernelCfg, build_fuzzy_kernel

    for lut in (False, True):
        k = build_fuzzy_kernel(
            FUZZY_LOOP_DEFAULT_FLL, FuzzyKernelCfg(ke=0.05, kde=0.0, ku=2.0, lut_enabled=lut)
        )
        k.align(0.0, 0.0, 0.0)
        k.compute(sp=10.0, pv=0.0, dt=1.0)
        bruto = LoopState(
            ts=datetime(2026, 1, 1, tzinfo=UTC),
            target="auto",
            actual="auto",
            permitted=["auto"],
            pv=0.0,
            pv_ok=True,
            sp=10.0,
            out=1.0,
            u_pct=1.0,
            man_out=0.0,
            hi_limited=False,
            lo_limited=False,
            diag=dict(k.diag),
        ).model_dump_json()
        p = _pipeline()
        p.ingest_loop_state("loop.state.7.abc", bruto)
        assert p.malformed_total == 0, f"lut={lut}"
        assert sorted({x["var_id"] for x in p._loop.snapshot()}) == ["mode", "out", "pv", "sp"]
