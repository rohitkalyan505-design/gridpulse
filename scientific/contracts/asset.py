"""
GridPulse — Asset Identification & Transformer Specification
Part of scientific.contracts (Source of Truth)

Defines:
1. TransformerAssetSpec: Complete static nameplate and design parameters required
   for physical modeling, thermal degradation analysis, and electrical loading.
2. OperationalLimits: Permissible physical thresholds and operating envelopes.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Optional, Tuple

from scientific.contracts.enums import CoolingType, InsulationClass, IssueSeverity, WindingMaterial
from scientific.contracts.issues import ProcessingIssue


@dataclass(frozen=True)
class OperationalLimits:
    """
    Standard operational and thermal limits governing transformer operation.
    Default baseline values align with standard distribution transformer ratings.
    """
    max_continuous_loading_pu: float = 1.0
    emergency_loading_pu: float = 1.4
    max_hot_spot_temp_c: float = 120.0
    max_top_oil_temp_c: float = 105.0
    voltage_tolerance_lower_pu: float = 0.90
    voltage_tolerance_upper_pu: float = 1.10
    max_voltage_unbalance_percent: float = 2.0
    max_current_unbalance_percent: float = 10.0

    def __post_init__(self) -> None:
        if self.max_top_oil_temp_c >= self.max_hot_spot_temp_c:
            raise ValueError("max_top_oil_temp_c must be strictly less than max_hot_spot_temp_c.")


def validate_loading_thresholds(
    continuous_threshold: float,
    emergency_threshold: float,
    asset_id: Optional[str] = None,
) -> Tuple[bool, Optional[ProcessingIssue]]:
    """
    Validates the configuration invariants for transformer loading thresholds:
    1. 0 < continuous_threshold < emergency_threshold
    2. 0.80 <= continuous_threshold < emergency_threshold
    3. Both thresholds must be finite positive numbers (not NaN, not Inf).

    Returns:
        (is_valid, optional_issue)
    """
    if not isinstance(continuous_threshold, (int, float)) or not isinstance(emergency_threshold, (int, float)):
        return False, ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.CRITICAL,
            code="ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION",
            message=(
                f"Loading thresholds must be numeric, got continuous={continuous_threshold}, "
                f"emergency={emergency_threshold}."
            ),
            field_name="operational_limits",
        )

    if not math.isfinite(continuous_threshold) or not math.isfinite(emergency_threshold):
        return False, ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.CRITICAL,
            code="ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION",
            message=(
                f"Loading thresholds must be finite numbers: "
                f"continuous_threshold={continuous_threshold}, emergency_threshold={emergency_threshold}."
            ),
            field_name="operational_limits",
        )

    if continuous_threshold <= 0 or emergency_threshold <= 0:
        return False, ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.CRITICAL,
            code="ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION",
            message=(
                f"Loading thresholds must be strictly positive: "
                f"continuous_threshold={continuous_threshold}, emergency_threshold={emergency_threshold}."
            ),
            field_name="operational_limits",
        )

    if continuous_threshold < 0.80:
        return False, ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.CRITICAL,
            code="ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION",
            message=(
                f"Continuous threshold {continuous_threshold} violates screening-band lower bound (must be >= 0.80 pu) "
                f"to ensure deterministic interval [0.80, continuous_threshold]."
            ),
            field_name="operational_limits.max_continuous_loading_pu",
        )

    if emergency_threshold <= continuous_threshold:
        return False, ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.CRITICAL,
            code="ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION",
            message=(
                f"Emergency threshold must be strictly greater than continuous threshold: "
                f"continuous_threshold={continuous_threshold}, emergency_threshold={emergency_threshold}."
            ),
            field_name="operational_limits.emergency_loading_pu",
        )

    return True, None



@dataclass(frozen=True)
class TransformerAssetSpec:
    """
    Static distribution transformer nameplate specification.
    Every scientific pipeline run must be anchored to an immutable asset specification.

    Attributes:
        asset_id: Unique distribution asset identifier (e.g., 'TX-SUB04-DT012').
        rated_power_kva: Nominal three-phase or single-phase apparent power rating in kVA.
        primary_voltage_v: Nominal line-to-line primary (HV) voltage in Volts.
        secondary_voltage_v: Nominal line-to-line secondary (LV) voltage in Volts.
        rated_frequency_hz: Nominal system grid frequency (e.g., 50.0 or 60.0 Hz).
        phases: Number of electrical phases (1 or 3).
        cooling_type: Standard cooling class (e.g., ONAN).
        winding_material: Conductor type (Copper or Aluminum).
        insulation_class: Thermal insulation classification.
        vector_group: Optional connection group (e.g., 'Dyn11', 'Yzn11').
        substation_id: Optional parent substation identifier.
        feeder_id: Optional parent medium-voltage feeder identifier.
        impedance_percent: Optional percent impedance voltage (%Z).
        no_load_loss_kw: Optional core/iron loss in kW.
        full_load_loss_kw: Optional copper/load loss in kW at rated load and 75°C.
        operational_limits: Specific operational and thermal constraint boundaries.
    """
    asset_id: str
    rated_power_kva: float
    primary_voltage_v: float
    secondary_voltage_v: float
    rated_frequency_hz: float
    phases: int
    cooling_type: CoolingType
    winding_material: WindingMaterial
    insulation_class: InsulationClass
    vector_group: Optional[str] = None
    substation_id: Optional[str] = None
    feeder_id: Optional[str] = None
    impedance_percent: Optional[float] = None
    no_load_loss_kw: Optional[float] = None
    full_load_loss_kw: Optional[float] = None
    operational_limits: OperationalLimits = field(default_factory=OperationalLimits)

    def __post_init__(self) -> None:
        if not self.asset_id or not self.asset_id.strip():
            raise ValueError("asset_id must be a non-empty string.")
        if self.rated_power_kva <= 0:
            raise ValueError(f"rated_power_kva must be strictly positive, got {self.rated_power_kva}.")
        if self.primary_voltage_v <= 0:
            raise ValueError(f"primary_voltage_v must be strictly positive, got {self.primary_voltage_v}.")
        if self.secondary_voltage_v <= 0:
            raise ValueError(f"secondary_voltage_v must be strictly positive, got {self.secondary_voltage_v}.")
        if self.rated_frequency_hz not in (50.0, 60.0):
            raise ValueError(f"rated_frequency_hz must be standard 50.0 or 60.0 Hz, got {self.rated_frequency_hz}.")
        if self.phases not in (1, 3):
            raise ValueError(f"phases must be 1 or 3, got {self.phases}.")
        if self.impedance_percent is not None and self.impedance_percent <= 0:
            raise ValueError(f"impedance_percent must be positive if specified, got {self.impedance_percent}.")
