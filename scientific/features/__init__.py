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
    # Contracts
    "ElectricalCalculationInput",
    "TransformerLoadingInput",
]
