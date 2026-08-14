"""Handles Core das hypertables (schema é da migration 0002; aqui só se lê e escreve).

O schema destas tabelas nasce em SQL cru na migration 0002 (spec F1 §3.2), então os handles
ficam numa `MetaData` própria, fora de `Base.metadata`: existem apenas para ler e escrever
e não devem poluir a superfície relacional gerenciada pelo autogenerate do Alembic.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Double,
    MetaData,
    SmallInteger,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

TIMESERIES_METADATA = MetaData()

samples_table = Table(
    "samples",
    TIMESERIES_METADATA,
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("tag_id", BigInteger, nullable=False),
    Column("value", Double, nullable=False),
    Column("quality", SmallInteger, nullable=False, server_default=text("0")),
)

events_table = Table(
    "events",
    TIMESERIES_METADATA,
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("severity", Text, nullable=False),
    Column("origin", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'")),
)

ssto_runs_table = Table(
    "ssto_runs",
    TIMESERIES_METADATA,
    # Auditoria do SSTO (ADR-027 §11): uma linha por execução, imutável — só INSERT.
    # Os vetores vão em JSONB porque a dimensão varia por bloco (nº de MVs/linhas é config,
    # não schema); os escalares que se consulta por filtro ficam em coluna própria.
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("flow_id", BigInteger, nullable=False),
    Column("block_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("config_hash", Text, nullable=False),
    Column("model_hash", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("solver", Text, nullable=False),
    Column("solve_ms", Double, nullable=False),
    Column("objective", Double, nullable=False),
    Column("mv", JSONB, nullable=False),
    Column("cv_ss", JSONB, nullable=False),
    Column("bias", JSONB, nullable=False),
    Column("dv", JSONB, nullable=False),
    Column("costs", JSONB, nullable=False),
    Column("delta_mv", JSONB, nullable=False),
    Column("mv_target", JSONB, nullable=False),
    Column("cv_target", JSONB, nullable=False),
    Column("given_up", JSONB, nullable=False),
    Column("active_constraints", JSONB, nullable=False),
    Column("duals", JSONB, nullable=False),
)

mpc_samples_table = Table(
    "mpc_samples",
    TIMESERIES_METADATA,
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("flow_id", BigInteger, nullable=False),
    Column("block_id", Text, nullable=False),
    Column("var_id", Text, nullable=False),
    Column("v", Double, nullable=False),
    Column("sp", Double, nullable=True),
    Column("auto", Boolean, nullable=False),
)

fuzzy_samples_table = Table(
    "fuzzy_samples",
    TIMESERIES_METADATA,
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("flow_id", BigInteger, nullable=False),
    Column("block_id", Text, nullable=False),
    Column("var_id", Text, nullable=False),
    Column("v", Double, nullable=False),
)
