"""
GridPulse — Validation Module Contracts
Boundary contracts for physical boundary checking, sanity validation,
and telemetry quality tagging. References shared contracts from scientific.contracts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from scientific.contracts.enums import EvidenceClassification, MeasurementQuality
from scientific.contracts.measurement import Measurement
from scientific.contracts.results import ValidationSummary


@dataclass(frozen=True)
class PhysicalBoundaryRule:
    """
    Physical plausible limits for an electrical channel.
    Values exceeding extreme limits are marked BAD or OUT_OF_RANGE.
    """
    channel_tag: str
    min_physical_value: float
    max_physical_value: float
    max_rate_of_change_per_second: Optional[float] = None
    expected_unit: str = ""

    def __post_init__(self) -> None:
        if self.min_physical_value >= self.max_physical_value:
            raise ValueError("min_physical_value must be strictly less than max_physical_value.")


@dataclass(frozen=True)
class ValidatedTelemetryRecord:
    """
    Physically validated telemetry record for a single observation timestamp.
    All channels are wrapped as typed Measurement[float] with quality status.
    """
    asset_id: str
    timestamp: datetime
    # Phase Voltages (V RMS)
    voltage_a: Measurement[float]
    voltage_b: Measurement[float]
    voltage_c: Measurement[float]
    # Phase Currents (A RMS)
    current_a: Measurement[float]
    current_b: Measurement[float]
    current_c: Measurement[float]
    # Grid Frequency (Hz)
    frequency: Measurement[float]
    # Ambient Temperature (°C)
    ambient_temp: Optional[Measurement[float]] = None
    # Optional direct powers (if metered at source)
    active_power_kw: Optional[Measurement[float]] = None
    reactive_power_kvar: Optional[Measurement[float]] = None
    power_factor: Optional[Measurement[float]] = None

    def __post_init__(self) -> None:
        if not self.asset_id or not self.asset_id.strip():
            raise ValueError("asset_id must be non-empty.")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (strictly UTC).")


@dataclass(frozen=True)
class ValidatedTelemetryBatch:
    """
    Time-series batch of validated telemetry records.
    Input to the downstream electrical calculation pipeline.
    """
    asset_id: str
    nominal_interval_seconds: int
    records: List[ValidatedTelemetryRecord]
    validation_summary: ValidationSummary
    is_monotonically_ordered: bool = True

    def __post_init__(self) -> None:
        if not self.asset_id or not self.asset_id.strip():
            raise ValueError("asset_id must be non-empty.")
        if self.nominal_interval_seconds <= 0:
            raise ValueError("nominal_interval_seconds must be strictly positive.")
