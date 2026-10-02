"""
GridPulse — Features Module
Deterministic electrical calculations and feature engineering.
"""

from scientific.features.calculations import (
    NEAR_ZERO_APPARENT_POWER_KVA,
    calculate_apparent_power,
    calculate_power_factor,
    calculate_three_phase_average_current,
    calculate_three_phase_average_voltage,
    normalize_power_to_canonical_kva,
)
from scientific.features.contracts import (
    ElectricalCalculationInput,
    TransformerLoadingInput,
)
from scientific.features.engine import ElectricalCalculationEngine
from scientific.features.loading import (
    CLASSIFICATION_SCREENING_CONVENTIONS,
    DEFAULT_EMERGENCY_SCREENING_QUALIFICATION,
    DEFAULT_MAX_GAP_MULTIPLIER,
    DEFAULT_NOMINAL_INTERVAL_SECONDS,
    calculate_batch_loading,
    calculate_record_loading,
    classify_loading_state,
    normalize_apparent_power_to_canonical_kva,
)

__all__ = [
    # Engine
    "ElectricalCalculationEngine",
    # Calculation Functions
    "calculate_apparent_power",
    "calculate_power_factor",
    "calculate_three_phase_average_voltage",
    "calculate_three_phase_average_current",
    "normalize_power_to_canonical_kva",
    "NEAR_ZERO_APPARENT_POWER_KVA",
    # Loading Functions & Constants
    "calculate_record_loading",
    "calculate_batch_loading",
    "classify_loading_state",
    "normalize_apparent_power_to_canonical_kva",
    "DEFAULT_NOMINAL_INTERVAL_SECONDS",
    "DEFAULT_MAX_GAP_MULTIPLIER",
    "DEFAULT_EMERGENCY_SCREENING_QUALIFICATION",
    "CLASSIFICATION_SCREENING_CONVENTIONS",
    # Contracts
    "ElectricalCalculationInput",
    "TransformerLoadingInput",
]

