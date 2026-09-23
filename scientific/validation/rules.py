"""
GridPulse — Validation Rules, Sanity Boundaries & Configurable Thresholds
Part of scientific.validation.

All rules adhere strictly to Phase 2 principles:
- Generic sanity limits are explicit GridPulse DATA-QUALITY CONVENTIONS,
  not universal electrical engineering limits or transformer ratings.
- Flatline detection is purely a DATA-QUALITY DIAGNOSTIC and never asserts sensor
  failure, sensor malfunction, asset failure, or asset abnormality.
- Operating limits are evaluated separately from physical data quality.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Dict, List, Optional, Set


class MeasurementType(str, Enum):
    """Supported electrical and environmental measurement channels."""
    VOLTAGE_A = "VOLTAGE_A"
    VOLTAGE_B = "VOLTAGE_B"
    VOLTAGE_C = "VOLTAGE_C"
    VOLTAGE_AVG = "VOLTAGE_AVG"
    CURRENT_A = "CURRENT_A"
    CURRENT_B = "CURRENT_B"
    CURRENT_C = "CURRENT_C"
    CURRENT_AVG = "CURRENT_AVG"
    ACTIVE_POWER = "ACTIVE_POWER"
    REACTIVE_POWER = "REACTIVE_POWER"
    APPARENT_POWER = "APPARENT_POWER"
    POWER_FACTOR = "POWER_FACTOR"
    FREQUENCY = "FREQUENCY"
    AMBIENT_TEMPERATURE = "AMBIENT_TEMPERATURE"


# Standard alias mapping to resolve diverse SCADA/AMI meter tags into canonical MeasurementType
CHANNEL_TAG_ALIASES: Dict[str, MeasurementType] = {
    # Voltages
    "v_a": MeasurementType.VOLTAGE_A,
    "va": MeasurementType.VOLTAGE_A,
    "voltage_a": MeasurementType.VOLTAGE_A,
    "v_an": MeasurementType.VOLTAGE_A,
    "v_ab": MeasurementType.VOLTAGE_A,
    "v_b": MeasurementType.VOLTAGE_B,
    "vb": MeasurementType.VOLTAGE_B,
    "voltage_b": MeasurementType.VOLTAGE_B,
    "v_bn": MeasurementType.VOLTAGE_B,
    "v_bc": MeasurementType.VOLTAGE_B,
    "v_c": MeasurementType.VOLTAGE_C,
    "vc": MeasurementType.VOLTAGE_C,
    "voltage_c": MeasurementType.VOLTAGE_C,
    "v_cn": MeasurementType.VOLTAGE_C,
    "v_ca": MeasurementType.VOLTAGE_C,
    "v_avg": MeasurementType.VOLTAGE_AVG,
    "vavg": MeasurementType.VOLTAGE_AVG,
    "voltage_avg": MeasurementType.VOLTAGE_AVG,
    # Currents
    "i_a": MeasurementType.CURRENT_A,
    "ia": MeasurementType.CURRENT_A,
    "current_a": MeasurementType.CURRENT_A,
    "i_b": MeasurementType.CURRENT_B,
    "ib": MeasurementType.CURRENT_B,
    "current_b": MeasurementType.CURRENT_B,
    "i_c": MeasurementType.CURRENT_C,
    "ic": MeasurementType.CURRENT_C,
    "current_c": MeasurementType.CURRENT_C,
    "i_avg": MeasurementType.CURRENT_AVG,
    "iavg": MeasurementType.CURRENT_AVG,
    "current_avg": MeasurementType.CURRENT_AVG,
    # Powers
    "p": MeasurementType.ACTIVE_POWER,
    "kw": MeasurementType.ACTIVE_POWER,
    "active_power": MeasurementType.ACTIVE_POWER,
    "active_power_kw": MeasurementType.ACTIVE_POWER,
    "q": MeasurementType.REACTIVE_POWER,
    "kvar": MeasurementType.REACTIVE_POWER,
    "reactive_power": MeasurementType.REACTIVE_POWER,
    "reactive_power_kvar": MeasurementType.REACTIVE_POWER,
    "s": MeasurementType.APPARENT_POWER,
    "kva": MeasurementType.APPARENT_POWER,
    "apparent_power": MeasurementType.APPARENT_POWER,
    "apparent_power_kva": MeasurementType.APPARENT_POWER,
    # Power Factor
    "pf": MeasurementType.POWER_FACTOR,
    "power_factor": MeasurementType.POWER_FACTOR,
    "cos_phi": MeasurementType.POWER_FACTOR,
    # Frequency
    "f": MeasurementType.FREQUENCY,
    "freq": MeasurementType.FREQUENCY,
    "frequency": MeasurementType.FREQUENCY,
    "hz": MeasurementType.FREQUENCY,
    # Ambient Temperature
    "t_amb": MeasurementType.AMBIENT_TEMPERATURE,
    "tamb": MeasurementType.AMBIENT_TEMPERATURE,
    "ambient_temp": MeasurementType.AMBIENT_TEMPERATURE,
    "ambient_temperature": MeasurementType.AMBIENT_TEMPERATURE,
    "temp_ambient": MeasurementType.AMBIENT_TEMPERATURE,
}

# Permitted engineering units by measurement type
ALLOWED_UNITS_BY_TYPE: Dict[MeasurementType, Set[str]] = {
    MeasurementType.VOLTAGE_A: {"V", "kV"},
    MeasurementType.VOLTAGE_B: {"V", "kV"},
    MeasurementType.VOLTAGE_C: {"V", "kV"},
    MeasurementType.VOLTAGE_AVG: {"V", "kV"},
    MeasurementType.CURRENT_A: {"A", "mA", "kA"},
    MeasurementType.CURRENT_B: {"A", "mA", "kA"},
    MeasurementType.CURRENT_C: {"A", "mA", "kA"},
    MeasurementType.CURRENT_AVG: {"A", "mA", "kA"},
    MeasurementType.ACTIVE_POWER: {"W", "kW", "MW"},
    MeasurementType.REACTIVE_POWER: {"VAR", "kVAR", "MVAR"},
    MeasurementType.APPARENT_POWER: {"VA", "kVA", "MVA"},
    MeasurementType.POWER_FACTOR: {"ratio", "pu", "percent", ""},
    MeasurementType.FREQUENCY: {"Hz"},
    MeasurementType.AMBIENT_TEMPERATURE: {"degC", "C", "°C"},
}


@dataclass(frozen=True)
class GenericSanityLimits:
    """
    Configurable physical sanity boundaries.

    IMPORTANT PROVENANCE & ARCHITECTURAL CLASSIFICATION:
    These limits represent GridPulse DATA-QUALITY CONVENTIONS established to flag
    sensor corruption, transmission noise, or unphysical values (e.g., negative frequency).
    They are NOT universal electrical engineering limits or transformer nameplate ratings.
    """
    min_value: float
    max_value: float
    rationale: str

    def __post_init__(self) -> None:
        if self.min_value >= self.max_value:
            raise ValueError(f"min_value ({self.min_value}) must be strictly less than max_value ({self.max_value}).")


# Default configurable GridPulse Data-Quality Sanity Conventions
DEFAULT_SANITY_LIMITS: Dict[MeasurementType, GenericSanityLimits] = {
    MeasurementType.VOLTAGE_A: GenericSanityLimits(
        min_value=0.0,
        max_value=100000.0,
        rationale="GridPulse data-quality convention: RMS voltage cannot be negative and exceeds medium-voltage distribution ceilings above 100 kV.",
    ),
    MeasurementType.VOLTAGE_B: GenericSanityLimits(
        min_value=0.0,
        max_value=100000.0,
        rationale="GridPulse data-quality convention: RMS voltage cannot be negative.",
    ),
    MeasurementType.VOLTAGE_C: GenericSanityLimits(
        min_value=0.0,
        max_value=100000.0,
        rationale="GridPulse data-quality convention: RMS voltage cannot be negative.",
    ),
    MeasurementType.VOLTAGE_AVG: GenericSanityLimits(
        min_value=0.0,
        max_value=100000.0,
        rationale="GridPulse data-quality convention: Average RMS voltage cannot be negative.",
    ),
    MeasurementType.CURRENT_A: GenericSanityLimits(
        min_value=0.0,
        max_value=50000.0,
        rationale="GridPulse data-quality convention: RMS current magnitude cannot be negative; 50 kA upper bound filters instrument corruptions.",
    ),
    MeasurementType.CURRENT_B: GenericSanityLimits(
        min_value=0.0,
        max_value=50000.0,
        rationale="GridPulse data-quality convention: RMS current magnitude cannot be negative.",
    ),
    MeasurementType.CURRENT_C: GenericSanityLimits(
        min_value=0.0,
        max_value=50000.0,
        rationale="GridPulse data-quality convention: RMS current magnitude cannot be negative.",
    ),
    MeasurementType.CURRENT_AVG: GenericSanityLimits(
        min_value=0.0,
        max_value=50000.0,
        rationale="GridPulse data-quality convention: Average RMS current cannot be negative.",
    ),
    MeasurementType.ACTIVE_POWER: GenericSanityLimits(
        min_value=-100000.0,
        max_value=100000.0,
        rationale="GridPulse data-quality convention: Bi-directional active power range in kW for distribution asset boundaries.",
    ),
    MeasurementType.REACTIVE_POWER: GenericSanityLimits(
        min_value=-100000.0,
        max_value=100000.0,
        rationale="GridPulse data-quality convention: Reactive power range in kVAR.",
    ),
    MeasurementType.APPARENT_POWER: GenericSanityLimits(
        min_value=0.0,
        max_value=150000.0,
        rationale="GridPulse data-quality convention: Apparent power magnitude is non-negative.",
    ),
    MeasurementType.POWER_FACTOR: GenericSanityLimits(
        min_value=-1.0,
        max_value=1.0,
        rationale="GridPulse data-quality convention: Dimensionless power factor magnitude cannot exceed unity (-1.0 to 1.0).",
    ),
    MeasurementType.FREQUENCY: GenericSanityLimits(
        min_value=30.0,
        max_value=75.0,
        rationale="GridPulse data-quality convention: Extreme frequency sanity envelope for 50 Hz and 60 Hz nominal grids.",
    ),
    MeasurementType.AMBIENT_TEMPERATURE: GenericSanityLimits(
        min_value=-50.0,
        max_value=80.0,
        rationale="GridPulse data-quality convention: Terrestrial physical ambient temperature envelope in degrees Celsius.",
    ),
}


@dataclass(frozen=True)
class FlatlineThreshold:
    """
    Configurable flatline detection threshold for a specific measurement type.

    IMPORTANT SCIENTIFIC GOVERNANCE:
    Flatline detection is purely a DATA-QUALITY DIAGNOSTIC signal.
    It indicates repeated identical telemetry across time intervals.
    It must NEVER claim:
    - sensor failure
    - sensor malfunction
    - asset failure
    - asset abnormality

    Attributes:
        min_consecutive_readings: Number of consecutive identical readings required to trigger flatline.
        abs_tol: Absolute tolerance for comparing consecutive floating-point values.
        rel_tol: Relative tolerance for comparing consecutive floating-point values.
    """
    min_consecutive_readings: int = 5
    abs_tol: float = 1e-4
    rel_tol: float = 0.0

    def __post_init__(self) -> None:
        if self.min_consecutive_readings < 2:
            raise ValueError("min_consecutive_readings must be at least 2.")
        if self.abs_tol < 0.0 or self.rel_tol < 0.0:
            raise ValueError("abs_tol and rel_tol must be non-negative.")

    def is_close(self, a: float, b: float) -> bool:
        """Determines if two values are equal within the configured tolerances."""
        return math.isclose(a, b, abs_tol=self.abs_tol, rel_tol=self.rel_tol)


# Default scale-appropriate flatline thresholds by measurement type
DEFAULT_FLATLINE_THRESHOLDS: Dict[MeasurementType, FlatlineThreshold] = {
    # Voltages: 0.1 V absolute tolerance avoids rounding jitter on 230V/11kV scales
    MeasurementType.VOLTAGE_A: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.1, rel_tol=0.0),
    MeasurementType.VOLTAGE_B: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.1, rel_tol=0.0),
    MeasurementType.VOLTAGE_C: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.1, rel_tol=0.0),
    MeasurementType.VOLTAGE_AVG: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.1, rel_tol=0.0),
    # Currents: 0.05 A absolute tolerance
    MeasurementType.CURRENT_A: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.05, rel_tol=0.0),
    MeasurementType.CURRENT_B: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.05, rel_tol=0.0),
    MeasurementType.CURRENT_C: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.05, rel_tol=0.0),
    MeasurementType.CURRENT_AVG: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.05, rel_tol=0.0),
    # Frequency: 0.005 Hz absolute tolerance
    MeasurementType.FREQUENCY: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.005, rel_tol=0.0),
    # Power Factor: 0.001 absolute tolerance
    MeasurementType.POWER_FACTOR: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.001, rel_tol=0.0),
    # Powers: 0.1 kW / kVAR / kVA
    MeasurementType.ACTIVE_POWER: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.1, rel_tol=0.0),
    MeasurementType.REACTIVE_POWER: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.1, rel_tol=0.0),
    MeasurementType.APPARENT_POWER: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.1, rel_tol=0.0),
    # Temperature: 0.05 °C
    MeasurementType.AMBIENT_TEMPERATURE: FlatlineThreshold(min_consecutive_readings=5, abs_tol=0.05, rel_tol=0.0),
}


@dataclass(frozen=True)
class ValidationConfig:
    """
    Configuration options governing telemetry validation behavior.

    Attributes:
        strict_mode: If True, contract or physical violations immediately raise domain exceptions.
                     If False (default), invalid telemetry is isolated with ProcessingIssue diagnostics.
        sanity_limits: Map of measurement types to generic sanity limits.
        flatline_thresholds: Map of measurement types to flatline detection thresholds.
        allow_missing_phases: If True, partial three-phase telemetry is accepted with missing channels.
    """
    strict_mode: bool = False
    sanity_limits: Dict[MeasurementType, GenericSanityLimits] = field(
        default_factory=lambda: dict(DEFAULT_SANITY_LIMITS)
    )
    flatline_thresholds: Dict[MeasurementType, FlatlineThreshold] = field(
        default_factory=lambda: dict(DEFAULT_FLATLINE_THRESHOLDS)
    )
    allow_missing_phases: bool = True
