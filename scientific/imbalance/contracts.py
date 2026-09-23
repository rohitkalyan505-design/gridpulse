"""
GridPulse — Phase Imbalance Module Contracts
Boundary contracts for three-phase asymmetrical loading, symmetrical component
unbalance ratios, and neutral current analysis.
References shared contracts from scientific.contracts.
"""

from dataclasses import dataclass
from typing import Optional

from scientific.contracts.asset import OperationalLimits, TransformerAssetSpec
from scientific.contracts.results import (
    ElectricalFeaturesResult,
    PhaseImbalanceResult,
    TransformerLoadingResult,
)


@dataclass(frozen=True)
class PhaseImbalanceInput:
    """
    Contract defining input requirements for phase unbalance calculations.
    Requires electrical features, transformer loading, and asset spec.
    """
    features: ElectricalFeaturesResult
    loading: TransformerLoadingResult
    asset_spec: TransformerAssetSpec
    operational_limits: Optional[OperationalLimits] = None
