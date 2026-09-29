"""Modelo LoopSetpoint espelha a DDL das migrations 0015/0016."""

from ottima_core.models.loop_setpoint import LoopSetpoint


def test_loop_setpoint_espelha_a_ddl() -> None:
    cols = {c.name for c in LoopSetpoint.__table__.columns}
    assert cols == {"flow_id", "block_id", "channel", "sp", "man_out", "target", "updated_at"}
    pk = {c.name for c in LoopSetpoint.__table__.primary_key.columns}
    assert pk == {"flow_id", "block_id", "channel"}
