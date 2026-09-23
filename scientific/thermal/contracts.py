"""
GridPulse — Thermal Analysis Module Contracts
Boundary contracts for transformer thermal dynamics and insulation degradation.
References shared contracts from scientific.contracts.
"""

from dataclasses import dataclass
from typing import Optional

from scientific.contracts.asset import TransformerAssetSpec
from scientific.contracts.measurement import Measurement
from scientific.contracts.provenance import EngineeringAssumption
from scientific.contracts.results import (
    ElectricalFeaturesResult,
    ThermalStateResult,
    TransformerLoadingResult,
)


@dataclass(frozen=True)
class ThermalModelParameters:
    """
    Physical parameters required for thermal differential models (IEEE C57.91 / IEC 60076-7).
    Must be defined by transformer design test report or standard typical values.
    """
    rated_top_oil_rise_k: float = 55.0  # Rated top-oil temperature rise over ambient in Kelvin
    rated_hot_spot_rise_k: float = 65.0  # Rated winding hot-spot rise over ambient in Kelvin
    top_oil_time_constant_hours: float = 3.0  # Thermal time constant of top oil
    winding_time_constant_minutes: float = 5.0  # Thermal time constant of winding
    oil_exponent_n: float = 0.8  # Exponent for oil temperature rise
    winding_exponent_m: float = 0.8  # Exponent for winding temperature rise
    loss_ratio_r: float = 5.0  # Ratio of load losses to no-load losses at rated load
    reference_ambient_temp_c: float = 30.0  # Yearly average reference ambient


@dataclass(frozen=True)
class ThermalAnalysisInput:
    """
    Contract defining input requirements for thermal degradation analysis.
    Requires electrical features, transformer loading, ambient temperature,
    asset spec, and thermal design parameters.
    """
    features: ElectricalFeaturesResult
    loading: TransformerLoadingResult
    ambient_temp: Optional[Measurement[float]]
    asset_spec: TransformerAssetSpec
    parameters: ThermalModelParameters = ThermalModelParameters()
    ambient_assumption: Optional[EngineeringAssumption] = None
