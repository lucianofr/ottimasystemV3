"""Handles Core das hypertables (schema é da migration 0002; aqui só se lê e escreve).

O schema destas tabelas nasce em SQL cru na migration 0002 (spec F1 §3.2), então os handles
ficam numa `MetaData` própria, fora de `Base.metadata`: existem apenas para ler e escrever
e não devem poluir a superfície relacional gerenciada pelo autogenerate do Alembic.
"""

from sqlalchemy import (
    BigInteger,
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
