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
