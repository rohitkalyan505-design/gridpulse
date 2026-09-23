"""
GridPulse — Ingestion Module Contracts
Boundary contract for raw telemetry intake and normalization.
References shared contracts from scientific.contracts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from scientific.contracts.measurement import CANONICAL_UNITS


@dataclass(frozen=True)
class RawTelemetryReading:
    """
    Single channel reading as received from raw telemetry payload.
    Unvalidated, with original source unit and meter tag.
    """
    channel_tag: str
    raw_value: Optional[float]
    source_unit: str
    timestamp: datetime
    sensor_id: Optional[str] = None
    raw_status_flag: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.channel_tag or not self.channel_tag.strip():
            raise ValueError("channel_tag must be non-empty.")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (strictly UTC).")


@dataclass(frozen=True)
class RawTelemetryRecord:
    """Collection of raw channel readings for a single timestamp interval."""
    asset_id: str
    timestamp: datetime
    readings: List[RawTelemetryReading] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.asset_id or not self.asset_id.strip():
            raise ValueError("asset_id must be non-empty.")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (strictly UTC).")


@dataclass(frozen=True)
class RawTelemetryBatch:
    """
    Time-series batch of raw telemetry records for a single transformer asset.
    Output of ingestion stage and input to validation stage.
    """
    asset_id: str
    nominal_interval_seconds: int
    records: List[RawTelemetryRecord] = field(default_factory=list)
    source_format: str = "JSON"  # e.g., 'JSON', 'CSV', 'MODBUS', 'IEC61850'
    ingestion_timestamp: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.asset_id or not self.asset_id.strip():
            raise ValueError("asset_id must be non-empty.")
        if self.nominal_interval_seconds <= 0:
            raise ValueError("nominal_interval_seconds must be strictly positive.")
