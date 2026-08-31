"""Canal loop.state e LoopState (ADR-039 secao 4.10)."""

from datetime import UTC, datetime

from ottima_core.bus import KIND_LOOP_MODE_CHANGED, LoopState, channel_loop_state


def test_canal_segue_a_convencao_dominio_assunto_ids() -> None:
    assert channel_loop_state(7, "abc") == "loop.state.7.abc"


def test_loop_state_roundtrip_json() -> None:
    s = LoopState(
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        target="auto",
        actual="man",
        permitted=["oos", "man", "auto"],
        pv=50.0,
        pv_ok=True,
        sp=55.0,
        out=210.0,
        u_pct=52.5,
        man_out=52.5,
        hi_limited=False,
        lo_limited=False,
    )
    assert LoopState.model_validate_json(s.model_dump_json()) == s


def test_kinds_iguais_aos_do_shell() -> None:
    from ottima_flow_runtime.blocks.shell.block import KIND_LOOP_MODE_CHANGED as SHELL_KIND

    assert KIND_LOOP_MODE_CHANGED == SHELL_KIND
