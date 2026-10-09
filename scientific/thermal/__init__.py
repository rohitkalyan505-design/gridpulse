"""
GridPulse — Thermal Module
Contracts and deterministic engines for IEEE/IEC transformer thermal modeling
and insulation degradation analysis.
Phase 2 Step 5 (v2.5.0 Specification).
"""

from scientific.thermal.contracts import (
    ProvenancedParameter,
    ThermalModelParameters,
    ThermalAnalysisInput,
)
from scientific.thermal.solver import (
    IEEE_REF_TEMP_UPGRADED_C,
    IEEE_REF_TEMP_NON_UPGRADED_C,
    IEC_REF_TEMP_UPGRADED_C,
    IEC_REF_TEMP_NON_UPGRADED_C,
    calculate_ieee_ultimate_top_oil_rise,
    calculate_ieee_ultimate_hot_spot_rise,
    calculate_iec_ultimate_top_oil_rise,
    calculate_iec_ultimate_hot_spot_rise,
    solve_exponential_recurrence,
    calculate_ieee_aging_acceleration_factor,
    calculate_iec_relative_ageing_rate,
)
from scientific.thermal.engine import (
    ThermalCalculationEngine,
)

__all__ = [
    "ProvenancedParameter",
    "ThermalModelParameters",
    "ThermalAnalysisInput",
    "ThermalCalculationEngine",
    "IEEE_REF_TEMP_UPGRADED_C",
    "IEEE_REF_TEMP_NON_UPGRADED_C",
    "IEC_REF_TEMP_UPGRADED_C",
    "IEC_REF_TEMP_NON_UPGRADED_C",
    "calculate_ieee_ultimate_top_oil_rise",
    "calculate_ieee_ultimate_hot_spot_rise",
    "calculate_iec_ultimate_top_oil_rise",
    "calculate_iec_ultimate_hot_spot_rise",
    "solve_exponential_recurrence",
    "calculate_ieee_aging_acceleration_factor",
    "calculate_iec_relative_ageing_rate",
]
