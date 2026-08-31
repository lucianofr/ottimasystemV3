"""Modelos relacionais do OttimaSystem (DDL: spec F1 §3.1)."""

from ottima_core.models.base import Base, TimestampMixin
from ottima_core.models.calculated_tag import CalculatedTag, CalculatedTagInput
from ottima_core.models.connection import OpcConnection
from ottima_core.models.flow import Flow
from ottima_core.models.history_retention import HistoryRetentionSettings
from ottima_core.models.loop_setpoint import LoopSetpoint
from ottima_core.models.mpc_setpoint import MpcSetpoint
from ottima_core.models.project import Project
from ottima_core.models.system_settings import SystemSettings
from ottima_core.models.tag import Tag
from ottima_core.models.timeseries import (
    events_table,
    fuzzy_samples_table,
    mpc_samples_table,
    samples_table,
    ssto_runs_table,
)
from ottima_core.models.user import User

__all__ = [
    "Base",
    "TimestampMixin",
    "User",
    "Project",
    "OpcConnection",
    "Tag",
    "CalculatedTag",
    "CalculatedTagInput",
    "Flow",
    "MpcSetpoint",
    "LoopSetpoint",
    "HistoryRetentionSettings",
    "SystemSettings",
    "samples_table",
    "events_table",
    "mpc_samples_table",
    "fuzzy_samples_table",
    "ssto_runs_table",
]
