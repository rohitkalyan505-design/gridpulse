"""
GridPulse — Core Measurement Representation & Unit Metadata
Part of scientific.contracts (Source of Truth)

Defines:
1. Measurement[T]: Generic container encapsulating physical observations and metrics
   with strict unit, evidence classification, data quality, and UTC timestamp metadata.
2. UnitMetadata: Representation of engineering units, physical dimensions, and canonical bases.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Generic, Optional, TypeVar

from scientific.contracts.enums import EvidenceClassification, MeasurementQuality

T = TypeVar("T")


@dataclass(frozen=True)
class UnitMetadata:
    """
    Representation of engineering measurement units and dimensional metadata.
    Establishes canonical baseline units for internal consistency across modules.
    Does not perform active unit conversion arithmetic (reserved for future steps).
    """
    unit_symbol: str
    dimension: str
    canonical_unit: str
    description: str

    def __post_init__(self) -> None:
        if not self.unit_symbol or not self.unit_symbol.strip():
            raise ValueError("unit_symbol must be non-empty.")
        if not self.dimension or not self.dimension.strip():
            raise ValueError("dimension must be non-empty.")
        if not self.canonical_unit or not self.canonical_unit.strip():
            raise ValueError("canonical_unit must be non-empty.")


# Canonical engineering unit registry baseline
CANONICAL_UNITS: Dict[str, UnitMetadata] = {
    "V": UnitMetadata(unit_symbol="V", dimension="voltage", canonical_unit="V", description="RMS Voltage (Volts)"),
    "kV": UnitMetadata(unit_symbol="kV", dimension="voltage", canonical_unit="V", description="Kilovolts"),
    "A": UnitMetadata(unit_symbol="A", dimension="current", canonical_unit="A", description="RMS Current (Amperes)"),
    "W": UnitMetadata(unit_symbol="W", dimension="active_power", canonical_unit="kW", description="Active Power (Watts)"),
    "kW": UnitMetadata(unit_symbol="kW", dimension="active_power", canonical_unit="kW", description="Active Power (Kilowatts)"),
    "MW": UnitMetadata(unit_symbol="MW", dimension="active_power", canonical_unit="kW", description="Active Power (Megawatts)"),
    "VAR": UnitMetadata(unit_symbol="VAR", dimension="reactive_power", canonical_unit="kVAR", description="Reactive Power (Volt-Amperes Reactive)"),
    "kVAR": UnitMetadata(unit_symbol="kVAR", dimension="reactive_power", canonical_unit="kVAR", description="Reactive Power (kVAR)"),
    "VA": UnitMetadata(unit_symbol="VA", dimension="apparent_power", canonical_unit="kVA", description="Apparent Power (Volt-Amperes)"),
    "kVA": UnitMetadata(unit_symbol="kVA", dimension="apparent_power", canonical_unit="kVA", description="Apparent Power (Kilovolt-Amperes)"),
    "MVA": UnitMetadata(unit_symbol="MVA", dimension="apparent_power", canonical_unit="kVA", description="Apparent Power (Megavolt-Amperes)"),
    "degC": UnitMetadata(unit_symbol="degC", dimension="temperature", canonical_unit="degC", description="Temperature in degrees Celsius"),
    "Hz": UnitMetadata(unit_symbol="Hz", dimension="frequency", canonical_unit="Hz", description="Grid Frequency in Hertz"),
    "pu": UnitMetadata(unit_symbol="pu", dimension="dimensionless", canonical_unit="pu", description="Per-Unit normalized value"),
    "percent": UnitMetadata(unit_symbol="percent", dimension="dimensionless", canonical_unit="percent", description="Percentage (0-100)"),
    "ratio": UnitMetadata(unit_symbol="ratio", dimension="dimensionless", canonical_unit="ratio", description="Dimensionless ratio (0.0 to 1.0)"),
    "hours": UnitMetadata(unit_symbol="hours", dimension="time", canonical_unit="hours", description="Duration in hours"),
    "seconds": UnitMetadata(unit_symbol="seconds", dimension="time", canonical_unit="seconds", description="Duration in seconds"),
}


@dataclass(frozen=True)
class Measurement(Generic[T]):
    """
    Fundamental unit of physical observation in GridPulse.
    Wraps an electrical or physical value with its scientific context:
    unit, evidence classification, data quality status, and UTC timestamp.

    Scientific Invariant:
    If quality is MISSING, value must be None and evidence must be UNKNOWN.
    Missing telemetry must never be silently fabricated with numerical defaults.
    """
    value: Optional[T]
    unit: str
    evidence: EvidenceClassification
    quality: MeasurementQuality
    timestamp: datetime
    sensor_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate timestamp timezone awareness
        if self.timestamp.tzinfo is None or self.timestamp.tzinfo.utcoffset(self.timestamp) is None:
            raise ValueError(
                f"Measurement timestamp '{self.timestamp}' must be timezone-aware (strictly UTC)."
            )

        # Enforce missing-data representation contract
        if self.quality == MeasurementQuality.MISSING:
            if self.value is not None:
                raise ValueError("Measurement with quality MISSING must have value=None.")
            if self.evidence != EvidenceClassification.UNKNOWN:
                raise ValueError(
                    f"Measurement with quality MISSING must carry evidence=UNKNOWN, got '{self.evidence}'."
                )

        if self.value is None and self.quality not in (MeasurementQuality.MISSING, MeasurementQuality.BAD):
            raise ValueError(
                f"Measurement with None value must have quality MISSING or BAD, got '{self.quality}'."
            )

    @classmethod
    def create_missing(
        cls,
        unit: str,
        timestamp: datetime,
        sensor_id: Optional[str] = None,
        reason: str = "Telemetry not provided"
    ) -> "Measurement[None]":
        """Factory for explicitly creating a missing measurement conforming to scientific invariants."""
        # Ensure UTC timezone
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return cls(
            value=None,
            unit=unit,
            evidence=EvidenceClassification.UNKNOWN,
            quality=MeasurementQuality.MISSING,
            timestamp=timestamp,
            sensor_id=sensor_id,
            metadata={"missing_reason": reason}
        )
