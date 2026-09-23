"""
GridPulse — Ingestion Module
Ingestion boundary contracts and normalization parser for raw telemetry intake.
"""

from scientific.ingestion.contracts import (
    RawTelemetryBatch,
    RawTelemetryReading,
    RawTelemetryRecord,
)
from scientific.ingestion.parser import parse_raw_telemetry_batch

__all__ = [
    "RawTelemetryReading",
    "RawTelemetryRecord",
    "RawTelemetryBatch",
    "parse_raw_telemetry_batch",
]
